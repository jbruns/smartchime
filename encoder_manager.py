import RPi.GPIO as GPIO
import logging
from pathlib import Path

class RotaryEncoder:
    def __init__(self, clk_pin, dt_pin, sw_pin):
        """Initialize a rotary encoder with GPIO pins.
        
        Args:
            clk_pin (int): GPIO pin number for the clock signal
            dt_pin (int): GPIO pin number for the data signal
            sw_pin (int): GPIO pin number for the switch/button"""
        self.logger = logging.getLogger(__name__)
        self.clk_pin = clk_pin
        self.dt_pin = dt_pin
        self.sw_pin = sw_pin
        self.clk_last_state = None
        self.callback_cw = None
        self.callback_ccw = None
        self.callback_button = None
        
        try:
            GPIO.setup(clk_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(dt_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(sw_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.logger.info(f"Initialized rotary encoder on pins CLK:{clk_pin}, DT:{dt_pin}, SW:{sw_pin}")
        except Exception as e:
            self.logger.error(f"Failed to setup GPIO pins for rotary encoder: {e}")
            raise
        
        self.clk_last_state = GPIO.input(clk_pin)
        
        GPIO.add_event_detect(clk_pin, GPIO.BOTH, callback=self._rotation_callback)
        GPIO.add_event_detect(sw_pin, GPIO.FALLING, callback=self._button_callback, bouncetime=300)
        
    def _rotation_callback(self, channel):
        """Internal callback for handling rotary encoder rotation events.
        Called when the clock pin state changes. Determines rotation direction
        by comparing clock and data pin states.
        
        Args:
            channel (int): GPIO channel that triggered the event
        
        Note:
            Calls self.callback_cw for clockwise rotation
            Calls self.callback_ccw for counter-clockwise rotation"""
        clk_state = GPIO.input(self.clk_pin)
        dt_state = GPIO.input(self.dt_pin)
        
        if clk_state != self.clk_last_state:
            if dt_state != clk_state:
                if self.callback_cw:
                    self.logger.debug(f"Encoder {self.clk_pin} rotated clockwise")
                    self.callback_cw()
            else:
                if self.callback_ccw:
                    self.logger.debug(f"Encoder {self.clk_pin} rotated counter-clockwise")
                    self.callback_ccw()
                    
        self.clk_last_state = clk_state
        
    def _button_callback(self, channel):
        if self.callback_button:
            self.logger.debug(f"Encoder {self.sw_pin} button pressed")
            self.callback_button()
            
    def set_callbacks(self, callback_cw, callback_ccw, callback_button):
        """Set the callback functions for encoder events.
        
        Args:
            callback_cw (callable): Function to call on clockwise rotation
            callback_ccw (callable): Function to call on counter-clockwise rotation
            callback_button (callable): Function to call on button press"""
        self.callback_cw = callback_cw
        self.callback_ccw = callback_ccw
        self.callback_button = callback_button
        self.logger.debug("Encoder callbacks configured")

class EncoderManager:
    def __init__(self, volume_pins, sound_select_pins):
        """Initialize manager for multiple rotary encoders.
        Sets up GPIO mode and initializes encoders for volume and sound selection.
        
        Args:
            volume_pins (tuple): Tuple of (clk, dt, sw) pins for volume encoder
            sound_select_pins (tuple): Tuple of (clk, dt, sw) pins for sound selection encoder
        
        Raises:
            Exception: If GPIO initialization fails or encoder setup fails"""
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing encoder manager")
        
        try:
            GPIO.setmode(GPIO.BCM)
            self.logger.debug("Set GPIO mode to BCM")
        except Exception as e:
            self.logger.error(f"Failed to set GPIO mode: {e}")
            raise
        
        try:
            # Volume encoder
            self.volume_encoder = RotaryEncoder(*volume_pins)
            self.logger.info("Volume encoder initialized")
            
            # Sound selection encoder
            self.sound_select_encoder = RotaryEncoder(*sound_select_pins)
            self.logger.info("Sound selection encoder initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize encoders: {e}")
            GPIO.cleanup()
            raise
        
    def setup_volume_callbacks(self, volume_up, volume_down, volume_mute):
        """Configure callbacks for the volume control encoder.
        
        Args:
            volume_up (callable): Function to call when volume should increase
            volume_down (callable): Function to call when volume should decrease
            volume_mute (callable): Function to call when volume should be muted
            
        Raises:
            Exception: If setting callbacks fails"""
        try:
            self.volume_encoder.set_callbacks(volume_up, volume_down, volume_mute)
            self.logger.info("Volume encoder callbacks configured")
        except Exception as e:
            self.logger.error(f"Failed to set volume encoder callbacks: {e}")
            raise
        
    def setup_sound_select_callbacks(self, next_sound, prev_sound, play_selected):
        """Configure callbacks for the sound selection encoder.
        
        Args:
            next_sound (callable): Function to call to select next sound
            prev_sound (callable): Function to call to select previous sound
            play_selected (callable): Function to call to play selected sound
            
        Raises:
            Exception: If setting callbacks fails"""
        try:
            self.sound_select_encoder.set_callbacks(next_sound, prev_sound, play_selected)
            self.logger.info("Sound selection encoder callbacks configured")
        except Exception as e:
            self.logger.error(f"Failed to set sound selection encoder callbacks: {e}")
            raise
        
    def cleanup(self):
        """Clean up GPIO resources.
        Should be called when shutting down to release GPIO pins."""
        try:
            GPIO.cleanup()
            self.logger.info("GPIO resources cleaned up")
        except Exception as e:
            self.logger.error(f"Error during GPIO cleanup: {e}")