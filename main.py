# Apply luma patch before any other imports that might use it
import logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

try:
    # Import and apply the patch
    import luma_patch
    logging.info("Luma patch imported")

except Exception as e:
    logging.error(f"Failed to import luma patch: {e}", exc_info=True)

import json
import time
import yaml
import logging
from datetime import datetime
import paho.mqtt.client as mqtt

from audio_manager import AudioManager
from hdmi_manager import HDMIManager
from oled_manager import OLEDManager
from encoder_manager import EncoderManager

__version__ = "2.0.0"

class SmartchimeSystem:
    """Main system controller for the Smartchime doorbell system.
    
    Coordinates all components including OLED display, audio system,
    HDMI output, rotary encoders, and MQTT communication. Handles
    events from motion detection, doorbell triggers, and user input."""
    
    def __init__(self):
        # Setup logging with timestamps and levels
        logging.basicConfig(
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            level=logging.DEBUG
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing Smartchime v{__version__}")
        
        try:
            with open('config.yaml', 'r') as f:
                self.config = yaml.safe_load(f)
                self.logger.info("Configuration loaded successfully")
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise
        
        try:
            # Initialize components
            self.logger.info("Initializing system components")
            
            self.oled = OLEDManager(
                self.config['displays']['oled']['spi_port'],
                self.config['displays']['oled']['spi_device']
            )
            
            self.audio = AudioManager(
                self.config['audio']['directory'],
                mixer_device=self.config['audio']['mixer']['device'],
                mixer_control=self.config['audio']['mixer']['control'],
                oled_manager=self.oled
            )
            
            self.hdmi = HDMIManager(self.config['displays']['hdmi']['framebuffer'])
                 
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
            
            # Initialize control throttling
            self.control_locks = {
                'volume': 0,
                'sound_select': 0,
                'toggle': 0
            }

            # Setup MQTT client with logging callbacks
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_message = self.on_message
            self.mqtt_client.on_disconnect = self.on_disconnect
            
            # Initialize state
            self.current_sound_index = None
            self.available_sounds = self.audio.get_available_sounds()
            if not self.available_sounds:
                self.logger.warning("No sound files found in audio directory")
            else:
                # convenience: set the current sound index to the default sound, if we find a match
                for i in range(0, len(self.available_sounds)):
                    if self.available_sounds[i] == self.config['audio']['default_sound']:
                        self.current_sound_index = i

            # Setup encoder callbacks
            self.setup_encoder_callbacks()
            self.logger.info("System initialization complete")
            
        except Exception as e:
            self.logger.error(f"System initialization failed: {e}")
            self.cleanup()
            raise
        
    def toggle_display(self):
        """Toggle the HDMI display on/off.
        When turning on, automatically starts playing the default video stream."""
        if self._check_control_throttle('toggle'):
            self.logger.debug("Display toggle throttled, skipping")
            return
            
        if self.hdmi.get_display_power_state() == "off":
            self.hdmi.play_video(self.config['video']['default_stream'])
        else:
            self.hdmi.stop_video()

    def setup_encoder_callbacks(self):
        """Configure the rotary encoder callbacks for system control.
        
        Sets up:
        - Volume encoder for audio control (up/down/mute)
        - Sound selection encoder for choosing doorbell sounds and display toggle"""
        self.logger.debug("Setting up encoder callbacks")
        
        # Wrapper functions for volume control with throttling
        def volume_up_throttled():
            if not self._check_control_throttle('volume'):
                self.audio.adjust_volume(0.05)
                
        def volume_down_throttled():
            if not self._check_control_throttle('volume'):
                self.audio.adjust_volume(-0.05)
                
        def volume_mute_throttled():
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
        """Throttle control actions to prevent rapid triggering.
        
        Args:
            control_type (str): Type of control being activated
                Supported values: 'volume', 'sound_select', 'toggle', 'default'
                
        Returns:
            bool: True if action should be blocked (throttled), False if action can proceed
        """
        # If control type is not specifically defined, use default
        if control_type not in self.control_locks:
            control_type = 'default'
            
        # If this control type is locked, block the action
        if self.control_locks.get(control_type, 0) > 0:
            self.logger.debug(f"{control_type} control still locked ({self.control_locks[control_type]} cycles remaining)")
            return True
            
        # Get the throttle period from config, default to 20 cycles
        throttle_config = self.config['controls']['throttle']
        throttle_period = throttle_config.get(control_type, throttle_config.get('default', 20))
        
        # Set the lock period
        self.control_locks[control_type] = throttle_period
        self.logger.debug(f"{control_type} control lock engaged for {throttle_period} cycles")
        
        # Action can proceed
        return False

    def next_sound(self):
        """Select the next available doorbell sound in the list.
        Shows the selected sound name on the OLED display.
        Does nothing if no sounds are available."""
        
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
        """Select the previous available doorbell sound in the list.
        Shows the selected sound name on the OLED display.
        Does nothing if no sounds are available."""
        if self._check_control_throttle('sound_select'):
            self.logger.debug("Sound selection throttled, skipping previous sound")
            return

        if not self.available_sounds:
            self.logger.warning("Cannot select previous sound: no sounds available")
            return
            
        self.current_sound_index = (self.current_sound_index + 1) % len(self.available_sounds)
        filename = self.available_sounds[self.current_sound_index]
        self.logger.info(f"Selected sound: {filename}")
        self.oled.set_mode("centered_2line", "Select sound:", filename, duration=5)
                        
    def on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback.
        
        Args:
            client: MQTT client instance
            userdata: User-defined data passed to callback
            flags: Response flags sent by the broker
            rc (int): Connection result code
                0: Connection successful
                1: Connection refused - incorrect protocol version
                2: Connection refused - invalid client identifier
                3: Connection refused - server unavailable
                4: Connection refused - bad username or password
                5: Connection refused - not authorized"""
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
        """MQTT disconnection callback.
        
        Args:
            client: MQTT client instance
            userdata: User-defined data passed to callback
            rc (int): Disconnection reason code
                0: Expected disconnect
                other: Unexpected disconnect"""
        if rc != 0:
            self.logger.error(f"Unexpected MQTT disconnection: {rc}")
        else:
            self.logger.info("Disconnected from MQTT broker")
            
    def handle_event_message(self, topic, payload):
        """Process doorbell and motion detection events from MQTT messages.
        
        Args:
            topic (str): MQTT topic that received the message
            payload (dict): Message payload containing event data
                Required fields:
                - active (bool): Whether the event is active
                - timestamp (str): ISO8601 timestamp of the event
                - video_url (str): URL of the video stream to display
                
        Note:
            - Displays appropriate message on OLED
            - Shows video stream on HDMI display for active events
            - Plays doorbell sound for doorbell events
            - Updates motion status display"""
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
            
            # MOTION
            if topic == self.config['mqtt']['topics']['motion']:
                self.oled.update_motion_status(active=payload['active'], last_time=event_time)
                if payload['active']:
                    self.oled.set_temporary_message("Person detected on doorbell camera!")
                else:
                    self.oled.clear_temporary_message()
            
            # DOORBELL
            if topic == self.config['mqtt']['topics']['doorbell']:
                if payload['active']:
                    self.oled.set_temporary_message("Someone's at the door!")
                    sound_file = self.available_sounds[self.current_sound_index] or self.config['audio']['default_sound']
                    self.audio.play_sound(sound_file)
                    video_url = payload['video_url'] or self.config['video']['default_stream']
                    self.hdmi.play_video(video_url)
                else:
                    self.oled.clear_temporary_message()
                
        except Exception as e:
            self.logger.error(f"Error processing {topic} message: {e}")
            self.logger.debug(f"Problematic payload: {payload}")
            
    def on_message(self, client, userdata, msg):
        """MQTT message received callback.
        Routes messages to appropriate handlers based on topic.
        
        Args:
            client: MQTT client instance
            userdata: User-defined data passed to callback
            msg: MQTTMessage containing topic and payload"""
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
        """Process generic message events and display them on the OLED screen.
        
        Args:
            payload (dict or str): Message to display
                If dict: Must have 'text' key with message
                If str: Used directly as message"""
        message = payload['text'] if isinstance(payload, dict) and 'text' in payload else str(payload)
        self.logger.info(f"Displaying message: {message}")
        self.oled.set_scrolling_message(message)
        
    def run(self):
        """Main system loop.
        
        - Connects to MQTT broker
        - Updates OLED display continuously
        - Handles cleanup on shutdown
        
        Raises:
            Exception: If connection fails or system encounters fatal error"""
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
                # Update all control locks
                for control_type in self.control_locks:
                    if self.control_locks[control_type] > 0:
                        self.control_locks[control_type] -= 1
                        if self.control_locks[control_type] == 0:
                            self.logger.debug(f"{control_type} control lock released")
                time.sleep(0.0125)
                
        except KeyboardInterrupt:
            self.logger.info("Received shutdown signal")
            self.cleanup()
        except Exception as e:
            self.logger.error(f"Runtime error: {e}")
            self.cleanup()
            raise
            
    def cleanup(self):
        """Clean up system resources on shutdown.
        
        - Stops MQTT client
        - Cleans up GPIO resources
        - Turns off HDMI display
        - Cleans up OLED display"""
        self.logger.info("Cleaning up system resources")
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        self.hdmi.stop_video()
        self.oled.cleanup()
        self.logger.info("Cleanup complete")

if __name__ == "__main__":
    try:
        system = SmartchimeSystem()
        system.run()
    except Exception as e:
        logging.getLogger(__name__).error(f"Fatal error: {e}")
        raise
