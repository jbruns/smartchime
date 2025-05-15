import logging
from pathlib import Path
from gpiozero import Button
from functools import partial

class RotaryEncoder:
    def __init__(self, clk_pin, dt_pin, sw_pin):
        """Initialize a rotary encoder with GPIO pins.
        
        Args:
            clk_pin (int): GPIO pin number for the clock signal
            dt_pin (int): GPIO pin number for the data signal
            sw_pin (int): GPIO pin number for the switch/button"""
        self.logger = logging.getLogger(__name__)
        self.callback_cw = None
        self.callback_ccw = None
        self.callback_button = None
        
        try:
            # Initialize GPIO pins using gpiozero Button class
            # Pull-up is the default for Button class
            self.clk = Button(clk_pin)
            self.dt = Button(dt_pin)
            self.sw = Button(sw_pin, bounce_time=0.3)
            
            self.logger.info(f"Initialized rotary encoder on pins CLK:{clk_pin}, DT:{dt_pin}, SW:{sw_pin}")
        except Exception as e:
            self.logger.error(f"Failed to setup GPIO pins for rotary encoder: {e}")
            raise
        
        # Store initial state
        self.clk_last_state = self.clk.value
        
        # Setup event handlers
        self.clk.when_pressed = self._rotation_callback
        self.clk.when_released = self._rotation_callback
        self.sw.when_pressed = self._button_callback
        
    def _rotation_callback(self):
        """Internal callback for handling rotary encoder rotation events."""
        clk_state = self.clk.value
        dt_state = self.dt.value
        
        if clk_state != self.clk_last_state:
            if dt_state != clk_state:
                if self.callback_cw:
                    self.logger.debug("Encoder rotated clockwise")
                    self.callback_cw()
            else:
                if self.callback_ccw:
                    self.logger.debug("Encoder rotated counter-clockwise")
                    self.callback_ccw()
                    
        self.clk_last_state = clk_state
        
    def _button_callback(self):
        """Internal callback for handling button press events."""
        if self.callback_button:
            self.logger.debug("Encoder button pressed")
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
        Sets up encoders for volume and sound selection.
        
        Args:
            volume_pins (tuple): Tuple of (clk, dt, sw) pins for volume encoder
            sound_select_pins (tuple): Tuple of (clk, dt, sw) pins for sound selection encoder
        
        Raises:
            Exception: If encoder setup fails"""
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing encoder manager")
        
        try:
            # Volume encoder
            self.volume_encoder = RotaryEncoder(*volume_pins)
            self.logger.info("Volume encoder initialized")
            
            # Sound selection encoder
            self.sound_select_encoder = RotaryEncoder(*sound_select_pins)
            self.logger.info("Sound selection encoder initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize encoders: {e}")
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
        Note: gpiozero handles cleanup automatically, but we keep this method
        for compatibility and explicit cleanup if needed."""
        self.logger.info("GPIO cleanup handled automatically by gpiozero")