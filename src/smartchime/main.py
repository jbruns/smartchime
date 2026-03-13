import json
import logging
import time
from datetime import datetime
from threading import Lock

import paho.mqtt.client as mqtt
import yaml

from smartchime import __version__

logger = logging.getLogger(__name__)

try:
    from smartchime import luma_patch  # noqa: F401 — must import before any luma usage

    logger.info("Luma patch imported")
except Exception as e:
    logger.error(f"Failed to import luma patch: {e}", exc_info=True)

from smartchime.audio_manager import AudioManager  # noqa: E402
from smartchime.encoder_manager import EncoderManager  # noqa: E402
from smartchime.hdmi_manager import HDMIManager  # noqa: E402
from smartchime.oled_manager import OLEDManager  # noqa: E402
from smartchime.shairport_metadata import ShairportMetadata  # noqa: E402


class SmartchimeSystem:
    def __init__(self):
        """Initialize the Smartchime system and its components."""
        logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG)
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Initializing Smartchime v{__version__}")

        try:
            with open("config.yaml") as f:
                self.config = yaml.safe_load(f)
                self.logger.info("Configuration loaded successfully")

        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            raise

        self._migrate_throttle_config()

        try:
            self.logger.info("Initializing system components")

            self.oled = OLEDManager(
                self.config["displays"]["oled"]["spi_port"], self.config["displays"]["oled"]["spi_device"]
            )

            self.shairport = ShairportMetadata(
                pipe_path=self.config.get("shairport", {}).get("metadata_pipe", "/tmp/shairport-sync-metadata")
            )
            self.shairport.add_callback(self._handle_airplay_metadata)
            self.shairport.start()
            self.logger.info("Initialized Shairport metadata reader")

            self.audio = AudioManager(
                self.config["audio"]["directory"],
                mixer_device=self.config["audio"]["mixer"]["device"],
                mixer_control=self.config["audio"]["mixer"]["control"],
                oled_manager=self.oled,
            )

            self.hdmi = HDMIManager()

            self.encoders = EncoderManager(
                volume_pins=(
                    self.config["gpio"]["volume_encoder"]["clk"],
                    self.config["gpio"]["volume_encoder"]["dt"],
                    self.config["gpio"]["volume_encoder"]["sw"],
                ),
                sound_select_pins=(
                    self.config["gpio"]["sound_select_encoder"]["clk"],
                    self.config["gpio"]["sound_select_encoder"]["dt"],
                    self.config["gpio"]["sound_select_encoder"]["sw"],
                ),
                max_steps=self.config["gpio"].get("max_steps", 0),
            )
            self.control_locks = {"volume": 0.0, "sound_select": 0.0, "toggle": 0.0}
            self._throttle_lock = Lock()

            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_message = self.on_message
            self.mqtt_client.on_disconnect = self.on_disconnect

            self.current_sound_index = None
            self.available_sounds = self.audio.get_available_sounds()
            self._active_event_source = None  # tracks which event type owns AMOLED ("doorbell" or "motion")
            if not self.available_sounds:
                self.logger.warning("No sound files found in audio directory")
            else:
                for i in range(0, len(self.available_sounds)):
                    if self.available_sounds[i] == self.config["audio"]["default_sound"]:
                        self.current_sound_index = i

            self.setup_encoder_callbacks()

            self.logger.info("System initialization complete")

        except Exception as e:
            self.logger.error(f"System initialization failed: {e}")
            self.cleanup()
            raise

    def _migrate_throttle_config(self):
        """Detect and convert legacy cycle-count throttle values to seconds.

        Old config used cycle counts (e.g., 10, 20, 40) where each cycle ≈ 12.5ms.
        New config uses seconds (e.g., 0.15, 0.4, 1.0). Any value > 5 is clearly
        a legacy cycle count and is converted automatically.
        """
        throttle = self.config.get("controls", {}).get("throttle", {})
        migrated = False
        for key, value in throttle.items():
            if isinstance(value, (int, float)) and value > 5:
                new_value = round(value * 0.0125, 3)
                throttle[key] = new_value
                self.logger.warning(f"Migrated legacy throttle '{key}': {value} cycles → {new_value}s")
                migrated = True
        if migrated:
            self.logger.info("Legacy throttle config detected and auto-converted to seconds")

    def toggle_display(self):
        """Toggle the display power state between on and off."""
        if self._check_control_throttle("toggle"):
            self.logger.debug("Display toggle throttled, skipping")
            return

        if self.hdmi.get_display_power_state() == "off":
            self.hdmi.play_video(self.config["video"]["default_stream"])
        else:
            self.hdmi.stop_video()

    def setup_encoder_callbacks(self):
        """Set up the callbacks for the encoders (volume and sound selection)."""
        self.logger.debug("Setting up encoder callbacks")

        def volume_up_throttled():
            """Throttle function for volume up action."""
            if not self._check_control_throttle("volume"):
                self.audio.adjust_volume(100)

        def volume_down_throttled():
            """Throttle function for volume down action."""
            if not self._check_control_throttle("volume"):
                self.audio.adjust_volume(-100)

        def volume_mute_throttled():
            """Throttle function for volume mute toggle action."""
            if not self._check_control_throttle("toggle"):
                self.audio.toggle_mute()

        self.encoders.setup_volume_callbacks(
            volume_up=volume_up_throttled, volume_down=volume_down_throttled, volume_mute=volume_mute_throttled
        )

        self.encoders.setup_sound_select_callbacks(
            next_sound=self.next_sound, prev_sound=self.prev_sound, play_selected=self.toggle_display
        )

    def _check_control_throttle(self, control_type="default"):
        """Check and manage the throttle control for various actions.

        Uses time.monotonic() for frame-rate-independent throttling.
        Throttle periods in config are in seconds.

        Args:
            control_type (str): The type of control to check (e.g., 'volume', 'sound_select').

        Returns:
            bool: True if the control is currently throttled, False otherwise.
        """
        if control_type not in self.control_locks:
            control_type = "default"

        now = time.monotonic()

        with self._throttle_lock:
            last_action = self.control_locks.get(control_type, 0.0)
            throttle_config = self.config["controls"]["throttle"]
            throttle_period = throttle_config.get(control_type, throttle_config.get("default", 0.4))

            if now - last_action < throttle_period:
                remaining = throttle_period - (now - last_action)
                self.logger.debug(f"{control_type} control still locked ({remaining:.2f}s remaining)")
                return True

            self.control_locks[control_type] = now
            self.logger.debug(f"{control_type} control lock engaged for {throttle_period}s")

            return False

    def next_sound(self):
        """Select the next sound in the available sounds list."""
        if self._check_control_throttle("sound_select"):
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
        if self._check_control_throttle("sound_select"):
            self.logger.debug("Sound selection throttled, skipping previous sound")
            return

        if not self.available_sounds:
            self.logger.warning("Cannot select previous sound: no sounds available")
            return

        self.current_sound_index = (self.current_sound_index - 1) % len(self.available_sounds)
        filename = self.available_sounds[self.current_sound_index]
        self.logger.info(f"Selected sound: {filename}")

        self.oled.set_mode("centered_2line", "Select sound:", filename, duration=5)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        """Handle the MQTT connection event.

        Args:
            client: The MQTT client instance.
            userdata: User data of the client.
            flags: Response flags from the broker.
            reason_code: Connection result reason code.
            properties: MQTT v5.0 properties.
        """
        if reason_code == 0:
            self.logger.info("Connected to MQTT broker")
            topics = [
                (self.config["mqtt"]["topics"]["doorbell"], 0),
                (self.config["mqtt"]["topics"]["motion"], 0),
                (self.config["mqtt"]["topics"]["oled_state"], 0),
            ]
            client.subscribe(topics)
            self.oled.set_v2_state_transport_ready(True)
            self.logger.info(f"Subscribed to topics: {[t[0] for t in topics]}")
        else:
            self.oled.set_v2_state_transport_ready(False)
            self.logger.error(f"Failed to connect to MQTT broker: {reason_code}")

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Handle the MQTT disconnection event.

        Args:
            client: The MQTT client instance.
            userdata: User data of the client.
            flags: Response flags from the broker.
            reason_code: Disconnection result reason code.
            properties: MQTT v5.0 properties.
        """
        self.oled.set_v2_state_transport_ready(False)
        if reason_code != 0:
            self.logger.error(f"Unexpected MQTT disconnection: {reason_code}")
        else:
            self.logger.info("Disconnected from MQTT broker")

    def handle_event_message(self, topic, payload):
        """Handle incoming event messages from MQTT.

        Doorbell events always take priority over motion events for AMOLED display.
        OLED display changes are managed by the v2 state contract (oled_state topic).

        Args:
            topic (str): The MQTT topic of the message.
            payload (dict): The message payload as a dictionary.
        """
        try:
            if not isinstance(payload, dict):
                self.logger.warning(f"Invalid payload format on {topic}: expected dict, got {type(payload)}")
                return

            missing_fields = [f for f in ["active", "timestamp"] if f not in payload]
            if missing_fields:
                self.logger.warning(f"Missing required fields in {topic} payload: {missing_fields}")
                return

            try:
                event_time = datetime.fromisoformat(payload["timestamp"])
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid timestamp format in {topic} payload: {payload['timestamp']}")
                return

            self.logger.info(f"Event message: topic={topic}, active={payload['active']}, time={event_time}")

            video_url = payload.get("video_url") or self.config["video"]["default_stream"]

            if topic == self.config["mqtt"]["topics"]["doorbell"]:
                if payload["active"]:
                    sound_file = (
                        self.available_sounds[self.current_sound_index] or self.config["audio"]["default_sound"]
                    )
                    self.audio.play_sound(sound_file)
                    self.hdmi.play_video(video_url)
                    self._active_event_source = "doorbell"
                else:
                    if self._active_event_source == "doorbell":
                        self.hdmi.stop_video()
                        self._active_event_source = None

            elif topic == self.config["mqtt"]["topics"]["motion"]:
                if payload["active"]:
                    if self._active_event_source != "doorbell":
                        self.hdmi.play_video(video_url)
                        self._active_event_source = "motion"
                    else:
                        self.logger.info("Motion video suppressed — doorbell has priority")
                else:
                    if self._active_event_source == "motion":
                        self.hdmi.stop_video()
                        self._active_event_source = None

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

            if msg.topic in [self.config["mqtt"]["topics"]["doorbell"], self.config["mqtt"]["topics"]["motion"]]:
                self.handle_event_message(msg.topic, payload)
            elif msg.topic == self.config["mqtt"]["topics"]["oled_state"]:
                self.handle_oled_state(payload)

        except json.JSONDecodeError as e:
            self.logger.warning(f"Invalid JSON received on topic {msg.topic}: {e}")
            self.logger.debug(f"Raw payload: {msg.payload}")

    def handle_oled_state(self, payload):
        """Handle a v2 OLED state contract message.

        Args:
            payload (dict): The v2 contract JSON payload.
        """
        try:
            self.oled.apply_v2_state(payload)
        except ValueError as e:
            self.logger.warning(f"Invalid v2 OLED state: {e}")
        except Exception as e:
            self.logger.error(f"Error applying v2 OLED state: {e}", exc_info=True)

    def run(self):
        """Run the main loop of the Smartchime system, processing events and messages."""
        self.logger.info("Starting doorbell system")

        mqtt_username = self.config["mqtt"]["username"]
        mqtt_password = self.config["mqtt"]["password"]

        if mqtt_username and mqtt_password:
            self.mqtt_client.username_pw_set(mqtt_username, mqtt_password)
            self.logger.debug("Set MQTT authentication credentials")

        try:
            self.mqtt_client.connect(self.config["mqtt"]["broker"], self.config["mqtt"]["port"], 60)
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
        if getattr(self, "mqtt_client", None):
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        if getattr(self, "hdmi", None):
            self.hdmi.cleanup()
        if getattr(self, "oled", None):
            self.oled.cleanup()
        if getattr(self, "shairport", None):
            self.shairport.stop()
            self.logger.info("Stopped Shairport metadata reader")
        self.logger.info("Cleanup complete")


def main():
    """Entry point for the Smartchime system."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.DEBUG,
    )
    try:
        system = SmartchimeSystem()
        system.run()
    except Exception as e:
        logging.getLogger(__name__).error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()
