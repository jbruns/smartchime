import os
import json
import time
import yaml
import logging
from pathlib import Path
from datetime import datetime
import paho.mqtt.client as mqtt

from audio_manager import AudioManager
from hdmi_manager import HDMIManager
from oled_manager import OLEDManager
from encoder_manager import EncoderManager
from shairport_manager import ShairportManager

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
            level=logging.INFO
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
                self.config['displays']['oled']['i2c_port'],
                self.config['displays']['oled']['i2c_address']
            )
            
            self.audio = AudioManager(
                self.config['audio']['directory'],
                mixer_device=self.config['audio']['mixer']['device'],
                mixer_control=self.config['audio']['mixer']['control'],
                oled_manager=self.oled
            )
            
            self.hdmi = HDMIManager(self.config['displays']['hdmi']['framebuffer'])
            
            self.shairport = ShairportManager(
                self.config['shairport']['metadata_pipe'],
                oled_manager=self.oled,
                show_duration=self.config['shairport']['show_duration']
            )
            
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
            
            # Setup MQTT client with logging callbacks
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.on_connect = self.on_connect
            self.mqtt_client.on_message = self.on_message
            self.mqtt_client.on_disconnect = self.on_disconnect
            
            # Initialize state
            self.current_sound_index = 0
            self.selected_sound_index = 0
            self.available_sounds = self.audio.get_available_sounds()
            if not self.available_sounds:
                self.logger.warning("No sound files found in audio directory")
            
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
        if self.hdmi.is_display_on:
            self.logger.info("Turning off HDMI display")
            self.hdmi.turn_off_display()
        else:
            self.logger.info("Turning on HDMI display and starting video stream")
            self.hdmi.turn_on_display()
            self.hdmi.play_video(self.config['video']['default_stream'])
            
    def setup_encoder_callbacks(self):
        """Configure the rotary encoder callbacks for system control.
        
        Sets up:
        - Volume encoder for audio control (up/down/mute)
        - Sound selection encoder for choosing doorbell sounds and display toggle"""
        self.logger.debug("Setting up encoder callbacks")
        self.encoders.setup_volume_callbacks(
            volume_up=lambda: self.audio.adjust_volume(0.05),
            volume_down=lambda: self.audio.adjust_volume(-0.05),
            volume_mute=self.audio.toggle_mute
        )
        
        self.encoders.setup_sound_select_callbacks(
            next_sound=self.next_sound,
            prev_sound=self.prev_sound,
            play_selected=self.toggle_display
        )
        
    def next_sound(self):
        """Select the next available doorbell sound in the list.
        Shows the selected sound name on the OLED display.
        Does nothing if no sounds are available."""
        if not self.available_sounds:
            self.logger.warning("Cannot select next sound: no sounds available")
            return
            
        self.selected_sound_index = (self.selected_sound_index + 1) % len(self.available_sounds)
        filename = self.available_sounds[self.selected_sound_index]
        self.logger.info(f"Selected sound: {filename}")
        self.oled.show_centered_text("Select Sound", filename, duration=5.0)
            
    def prev_sound(self):
        """Select the previous available doorbell sound in the list.
        Shows the selected sound name on the OLED display.
        Does nothing if no sounds are available."""
        if not self.available_sounds:
            self.logger.warning("Cannot select previous sound: no sounds available")
            return
            
        self.selected_sound_index = (self.selected_sound_index - 1) % len(self.available_sounds)
        filename = self.available_sounds[self.selected_sound_index]
        self.logger.info(f"Selected sound: {filename}")
        self.oled.show_centered_text("Select Sound", filename, duration=5.0)
            
    def play_selected_sound(self):
        """Play the currently selected doorbell sound.
        Also turns on the HDMI display and starts the default video stream.
        Does nothing if no sounds are available."""
        if not self.available_sounds:
            self.logger.warning("Cannot play sound: no sounds available")
            return
            
        self.current_sound_index = self.selected_sound_index
        filename = self.available_sounds[self.current_sound_index]
        self.logger.info(f"Playing selected sound: {filename}")
        self.hdmi.turn_on_display()
        self.audio.play_sound(filename)
        self.hdmi.play_video(self.config['video']['default_stream'])
            
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
                
            if topic == self.config['mqtt']['topics']['motion']:
                self.oled.show_status(motion_active=payload['active'], motion_time=event_time)
                if payload['active']:
                    self.oled.show_scrolling_text("Motion detected on doorbell camera!")
                else:
                    self.oled.clear_display()
            else:  # Doorbell event
                if payload['active']:
                    self.oled.show_scrolling_text("Someone's at the door!")
                else:
                    self.oled.clear_display()
            
            if payload['active']:
                self.hdmi.turn_on_display()
                if topic == self.config['mqtt']['topics']['doorbell']:
                    self.audio.play_sound(self.config['audio']['default_sound'])
                
                video_url = payload['video_url'] or self.config['video']['default_stream']
                self.hdmi.play_video(video_url)
                
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
        self.oled.show_scrolling_text(message)
        
    def run(self):
        """Main system loop.
        
        - Connects to MQTT broker
        - Starts Shairport metadata monitoring
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
            
            # Start Shairport metadata monitoring
            self.shairport.start()
            
            self.logger.info("System running")
            while True:
                self.oled.update_display()
                time.sleep(0.1)
                
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
        - Stops audio and Shairport systems
        - Cleans up OLED display"""
        self.logger.info("Cleaning up system resources")
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        self.encoders.cleanup()
        self.hdmi.turn_off_display()
        self.audio.cleanup()
        self.shairport.stop()
        self.oled.cleanup()
        self.logger.info("Cleanup complete")

if __name__ == "__main__":
    try:
        system = SmartchimeSystem()
        system.run()
    except Exception as e:
        logging.getLogger(__name__).error(f"Fatal error: {e}")
        raise