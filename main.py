import logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

try:
    import luma_patch
    logging.info("Luma patch imported")

except Exception as e:
    logging.error(f"Failed to import luma patch: {e}", exc_info=True)

import json
import time
import yaml
from datetime import datetime
import paho.mqtt.client as mqtt
import jsonschema
from jsonschema import validate, ValidationError
import threading

from audio_manager import AudioManager
from hdmi_manager import HDMIManager
from oled_manager import OLEDManager
from encoder_manager import EncoderManager
from shairport_metadata import ShairportMetadata

__version__ = "2.0.0"

CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "displays": {
            "type": "object",
            "properties": {
                "oled": {
                    "type": "object",
                    "properties": {
                        "spi_port": {"type": "integer"},
                        "spi_device": {"type": "integer"}
                    },
                    "required": ["spi_port", "spi_device"]
                }
            },
            "required": ["oled"]
        },
        "audio": {
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "mixer": {
                    "type": "object",
                    "properties": {
                        "device": {"type": "string"},
                        "control": {"type": "string"}
                    },
                    "required": ["device", "control"]
                },
                "default_sound": {"type": "string"}
            },
            "required": ["directory", "mixer", "default_sound"]
        },
        "gpio": {
            "type": "object",
            "properties": {
                "volume_encoder": {
                    "type": "object",
                    "properties": {
                        "clk": {"type": "integer"},
                        "dt": {"type": "integer"},
                        "sw": {"type": "integer"}
                    },
                    "required": ["clk", "dt", "sw"]
                },
                "sound_select_encoder": {
                    "type": "object",
                    "properties": {
                        "clk": {"type": "integer"},
                        "dt": {"type": "integer"},
                        "sw": {"type": "integer"}
                    },
                    "required": ["clk", "dt", "sw"]
                }
            },
            "required": ["volume_encoder", "sound_select_encoder"]
        },
        "mqtt": {
            "type": "object",
            "properties": {
                "broker": {"type": "string"},
                "port": {"type": "integer"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "topics": {
                    "type": "object",
                    "properties": {
                        "doorbell": {"type": "string"},
                        "motion": {"type": "string"},
                        "message": {"type": "string"}
                    },
                    "required": ["doorbell", "motion", "message"]
                }
            },
            "required": ["broker", "port", "topics"]
        }
    },
    "required": ["displays", "audio", "gpio", "mqtt"]
}

class SmartchimeSystem:
    def __init__(self):
        """Initialize the Smartchime system and its components."""
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.DEBUG
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing Smartchime v{__version__}")

        try:
            with open('config.yaml', 'r') as f:
                self.config = yaml.safe_load(f)
                validate(instance=self.config, schema=CONFIG_SCHEMA)
                self.logger.info("Configuration loaded and validated successfully")
        except FileNotFoundError:
            self.logger.error("Configuration file 'config.yaml' not found")
            raise
        except ValidationError as e:
            self.logger.error(f"Configuration validation error: {e.message}")
            self.logger.debug(f"Validation details: {e.schema_path}")
            raise
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise

        try:
            self.logger.info("Initializing system components")

            self.oled = OLEDManager(
                self.config['displays']['oled']['spi_port'],
                self.config['displays']['oled']['spi_device']
            )
            
            self.shairport = ShairportMetadata(
                pipe_path=self.config.get('shairport', {}).get('metadata_pipe', '/tmp/shairport-sync-metadata')
            )
            self.shairport.add_callback(self._handle_airplay_metadata)
            self.shairport.start()
            self.logger.info("Initialized Shairport metadata reader")

            self.audio = AudioManager(
                self.config['audio']['directory'],
                mixer_device=self.config['audio']['mixer']['device'],
                mixer_control=self.config['audio']['mixer']['control'],
                oled_manager=self.oled
            )

            self.hdmi = HDMIManager()

            self.encoders = EncoderManager(
                volume_pins=(
                    self.config['gpio']['volume_encoder']['clk'],
                    self.config['gpio']['volume_encoder']['dt'],
                    self.config['gpio']['volume_encoder']['sw']
                ),
                sound_select_pins=(
                    self.config['gpio']['sound_select_encoder']['clk'],
                    self.config['gpio']['sound_select_encoder']['dt'],
                    self.config['gpio']['sound_select_encoder']['sw']
                )
            )
            self.control_locks = {}
            self.lock_timers = {}

            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_message = self.on_message
            self.mqtt_client.on_disconnect = self.on_disconnect

            self.current_sound_index = None
            self.available_sounds = self.audio.get_available_sounds()
            if not self.available_sounds:
                self.logger.warning("No sound files found in audio directory")
            else:
                for i in range(0, len(self.available_sounds)):
                    if self.available_sounds[i] == self.config['audio']['default_sound']:
                        self.current_sound_index = i

            self.setup_encoder_callbacks()

            self.logger.info("System initialization complete")

        except Exception as e:
            self.logger.error(f"System initialization failed: {e}")
            self.cleanup()
            raise

    def toggle_display(self):
        """Toggle the display power state between on and off."""
        if self._check_control_throttle('toggle'):
            self.logger.debug("Display toggle throttled, skipping")
            return
            
        if self.hdmi.get_display_power_state() == "off":
            self.hdmi.play_video(self.config['video']['default_stream'])
        else:
            self.hdmi.stop_video()

    def setup_encoder_callbacks(self):
        """Set up the callbacks for the encoders (volume and sound selection)."""
        self.logger.debug("Setting up encoder callbacks")
        
        def volume_up_throttled():
            """Throttle function for volume up action."""
            if not self._check_control_throttle('volume'):
                self.audio.adjust_volume(100)
                
        def volume_down_throttled():
            """Throttle function for volume down action."""
            if not self._check_control_throttle('volume'):
                self.audio.adjust_volume(-100)
                
        def volume_mute_throttled():
            """Throttle function for volume mute toggle action."""
            if not self._check_control_throttle('toggle'):
                self.audio.toggle_mute()
        
        self.encoders.setup_volume_callbacks(
            volume_up=volume_up_throttled,
            volume_down=volume_down_throttled,
            volume_mute=volume_mute_throttled
        )
        
        self.encoders.setup_sound_select_callbacks(
            next_sound=self.next_sound,
            prev_sound=self.prev_sound,
            play_selected=self.toggle_display
        )
        
    def _check_control_throttle(self, control_type='default'):
        """Check and manage the throttle control for various actions.

        Args:
            control_type (str): The type of control to check (e.g., 'volume', 'sound_select').

        Returns:
            bool: True if the control is currently throttled, False otherwise.
        """
        if control_type not in self.control_locks:
            control_type = 'default'

        last_action_time = self.control_locks.get(control_type, 0)
        current_time = time.time() * 1000  # Convert to milliseconds

        throttle_config = self.config['controls']['throttle']
        throttle_period_ms = throttle_config.get(control_type, throttle_config.get('default', 200))

        if current_time - last_action_time < throttle_period_ms:
            self.logger.debug(f"{control_type} control still locked (elapsed: {current_time - last_action_time} ms, required: {throttle_period_ms} ms)")
            return True

        self.control_locks[control_type] = current_time
        self.logger.debug(f"{control_type} control lock engaged until {current_time + throttle_period_ms} ms")

        return False

    def cleanup(self):
        """Clean up resources before shutting down."""
        self.logger.info("Cleaning up system resources")
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        self.hdmi.stop_video()
        self.oled.cleanup()
        if hasattr(self, 'shairport'):
            self.shairport.stop()
            self.logger.info("Stopped Shairport metadata reader")
        self.control_locks.clear()  # Reset control locks
        self.logger.info("Cleanup complete")

    def next_sound(self):
        """Select the next sound in the available sounds list."""
        if self._check_control_throttle('sound_select'):
            self.logger.debug("Sound selection throttled, skipping next sound")
            return

        if not self.available_sounds:
            self.logger.warning("Cannot select next sound: no sounds available")
            return
            
        self.current_sound_index = (self.current_sound_index + 1) % len(self.available_sounds)
        filename = self.available_sounds[self.current_sound_index]
        self.logger.info(f"Selected sound: {filename}")

        self.oled.set_mode("centered_2line", "Select sound:", filename, duration=5)
            
    def prev_sound(self):
        """Select the previous sound in the available sounds list."""
        if self._check_control_throttle('sound_select'):
            self.logger.debug("Sound selection throttled, skipping previous sound")
            return

        if not self.available_sounds:
            self.logger.warning("Cannot select previous sound: no sounds available")
            return
            
        self.current_sound_index = (self.current_sound_index - 1) % len(self.available_sounds)
        filename = self.available_sounds[self.current_sound_index]
        self.logger.info(f"Selected sound: {filename}")

        self.oled.set_mode("centered_2line", "Select sound:", filename, duration=5)
                        
    def on_connect(self, client, userdata, flags, rc):
        """Handle the MQTT connection event.

        Args:
            client: The MQTT client instance.
            userdata: User data of the client.
            flags: Response flags from the broker.
            rc: Connection result code.
        """
        if rc == 0:
            self.logger.info("Connected to MQTT broker")
            topics = [
                (self.config['mqtt']['topics']['doorbell'], 0),
                (self.config['mqtt']['topics']['motion'], 0),
                (self.config['mqtt']['topics']['message'], 0)
            ]
            client.subscribe(topics)
            self.logger.info(f"Subscribed to topics: {[t[0] for t in topics]}")
        else:
            self.logger.error(f"Failed to connect to MQTT broker: {rc}")
            
    def on_disconnect(self, client, userdata, rc):
        """Handle the MQTT disconnection event.

        Args:
            client: The MQTT client instance.
            userdata: User data of the client.
            rc: Disconnection result code.
        """
        if rc != 0:
            self.logger.error(f"Unexpected MQTT disconnection: {rc}")
        else:
            self.logger.info("Disconnected from MQTT broker")
            
    def handle_event_message(self, topic, payload):
        """Handle incoming event messages from MQTT.

        Args:
            topic (str): The MQTT topic of the message.
            payload (dict): The message payload as a dictionary.
        """
        try:
            if not isinstance(payload, dict):
                self.logger.warning(f"Invalid payload format on {topic}: expected dict, got {type(payload)}")
                return
                
            missing_fields = [f for f in ['active', 'timestamp', 'video_url'] if f not in payload]
            if missing_fields:
                self.logger.warning(f"Missing required fields in {topic} payload: {missing_fields}")
                return
                
            try:
                event_time = datetime.fromisoformat(payload['timestamp'])

            except (ValueError, TypeError) as e:
                self.logger.warning(f"Invalid timestamp format in {topic} payload: {payload['timestamp']}")
                return
                
            self.logger.info(f"Event message: topic={topic}, active={payload['active']}, time={event_time}")
            
            if topic == self.config['mqtt']['topics']['motion']:
                self.oled.update_motion_status(active=payload['active'], last_time=event_time)
                if payload['active']:
                    self.oled.set_temporary_message("Person detected on doorbell camera!")
                else:
                    self.oled.clear_temporary_message()
            
            if topic == self.config['mqtt']['topics']['doorbell']:
                if payload['active']:
                    self.oled.set_temporary_message("Someone's at the door!")
                    sound_file = self.available_sounds[self.current_sound_index] or self.config['audio']['default_sound']
                    self.audio.play_sound(sound_file)
                    video_url = payload['video_url'] or self.config['video']['default_stream']
                    self.hdmi.play_video(video_url)
                else:
                    self.oled.clear_temporary_message()
                    self.hdmi.stop_video()
                
        except Exception as e:
            self.logger.error(f"Error processing {topic} message: {e}")
            self.logger.debug(f"Problematic payload: {payload}")
            
    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages.

        Args:
            client: The MQTT client instance.
            userdata: User data of the client.
            msg: The received message.
        """
        self.logger.debug(f"Received message on topic {msg.topic}")
        try:
            payload = json.loads(msg.payload.decode())
            
            if msg.topic in [self.config['mqtt']['topics']['doorbell'], 
                           self.config['mqtt']['topics']['motion']]:
                self.handle_event_message(msg.topic, payload)
            elif msg.topic == self.config['mqtt']['topics']['message']:
                self.handle_message(payload)
                
        except json.JSONDecodeError as e:
            self.logger.warning(f"Invalid JSON received on topic {msg.topic}: {e}")
            self.logger.debug(f"Raw payload: {msg.payload}")
            
    def handle_message(self, payload):
        """Handle and display a message payload.

        Args:
            payload (dict): The message payload.
        """
        message = payload['text'] if isinstance(payload, dict) and 'text' in payload else str(payload)
        self.logger.info(f"Displaying message: {message}")
        self.oled.set_scrolling_message(message)
        
    def run(self):
        """Run the main loop of the Smartchime system, processing events and messages."""
        self.logger.info("Starting doorbell system")

        mqtt_username = self.config['mqtt']['username']
        mqtt_password = self.config['mqtt']['password']
        
        if mqtt_username and mqtt_password:
            self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)
            self.logger.debug("Set MQTT authentication credentials")
            
        try:
            self.mqtt_client.connect(
                self.config['mqtt']['broker'],
                self.config['mqtt']['port'],
                60
            )
            self.mqtt_client.loop_start()
                       
            self.logger.info("System running")
            while True:
                self.oled.update_display()
                time.sleep(0.0125)
                
        except KeyboardInterrupt:
            self.logger.info("Received shutdown signal")
            self.cleanup()

        except Exception as e:
            self.logger.error(f"Runtime error: {e}")
            self.cleanup()
            raise
            
    def _handle_airplay_metadata(self, artist, title, is_playing):
        """Handle metadata updates from AirPlay.

        Args:
            artist (str): Name of the artist.
            title (str): Title of the track.
            is_playing (bool): Playback state.
        """
        try:
            if is_playing and (artist or title):
                display_text = ""
                if artist and title:
                    display_text = f"{title} - {artist}"
                elif title:
                    display_text = title
                elif artist:
                    display_text = artist
                
                if display_text:
                    self.oled.set_temporary_message(display_text, duration=30)
                    self.logger.debug(f"Updated display with AirPlay metadata: {display_text}")
        except Exception as e:
            self.logger.error(f"Error handling AirPlay metadata: {e}")

    def cleanup(self):
        """Clean up resources before shutting down."""
        self.logger.info("Cleaning up system resources")
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        self.hdmi.stop_video()
        self.oled.cleanup()
        if hasattr(self, 'shairport'):
            self.shairport.stop()
            self.logger.info("Stopped Shairport metadata reader")
        self.control_locks.clear()  # Reset control locks
        self.logger.info("Cleanup complete")

if __name__ == "__main__":
    try:
        system = SmartchimeSystem()
        system.run()

    except Exception as e:
        logging.getLogger(__name__).error(f"Fatal error: {e}")
        raise
