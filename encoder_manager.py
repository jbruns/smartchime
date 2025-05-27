import logging
from gpiozero import Button

class RotaryEncoder:
    def __init__(self, clk_pin, dt_pin, sw_pin):
        """Initialize a rotary encoder with GPIO pins.

        Args:
            clk_pin (int): GPIO pin for the clock signal.
            dt_pin (int): GPIO pin for the data signal.
            sw_pin (int): GPIO pin for the button signal.
        """
        self.logger = logging.getLogger(__name__)
        self.callback_cw = None
        self.callback_ccw = None
        self.callback_button = None
        
        try:
            self.clk = Button(clk_pin)
            self.dt = Button(dt_pin)
            self.sw = Button(sw_pin)
            
            self.logger.info(f"Initialized rotary encoder on pins CLK:{clk_pin}, DT:{dt_pin}, SW:{sw_pin}")
        except Exception as e:
            self.logger.error(f"Failed to setup GPIO pins for rotary encoder: {e}")
            raise
        
        self.clk_last_state = self.clk.value
        
        self.clk.when_pressed = self._rotation_callback
        self.clk.when_released = self._rotation_callback
        self.sw.when_pressed = self._button_callback
        
    def _rotation_callback(self):
        """Handle rotation events and trigger appropriate callbacks."""
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
        """Handle button press events and trigger the button callback."""
        if self.callback_button:
            self.logger.debug("Encoder button pressed")
            self.callback_button()
            
    def set_callbacks(self, callback_cw, callback_ccw, callback_button):
        """Set the callbacks for clockwise, counter-clockwise, and button press events.

        Args:
            callback_cw (callable): Function to call on clockwise rotation.
            callback_ccw (callable): Function to call on counter-clockwise rotation.
            callback_button (callable): Function to call on button press.
        """
        self.callback_cw = callback_cw
        self.callback_ccw = callback_ccw
        self.callback_button = callback_button
        self.logger.debug("Encoder callbacks configured")

class EncoderManager:
    def __init__(self, volume_pins, sound_select_pins):
        """Initialize the encoder manager with volume and sound selection encoders.

        Args:
            volume_pins (tuple): GPIO pins for the volume encoder (CLK, DT, SW).
            sound_select_pins (tuple): GPIO pins for the sound selection encoder (CLK, DT, SW).
        """
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing encoder manager")
        
        try:
            self.volume_encoder = RotaryEncoder(*volume_pins)
            self.logger.info("Volume encoder initialized")
            
            self.sound_select_encoder = RotaryEncoder(*sound_select_pins)
            self.logger.info("Sound selection encoder initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize encoders: {e}")
            raise
        
    def setup_volume_callbacks(self, volume_up, volume_down, volume_mute):
        """Configure callbacks for the volume encoder.

        Args:
            volume_up (callable): Function to call on volume up.
            volume_down (callable): Function to call on volume down.
            volume_mute (callable): Function to call on volume mute.
        """
        try:
            self.volume_encoder.set_callbacks(volume_up, volume_down, volume_mute)
            self.logger.info("Volume encoder callbacks configured")
        except Exception as e:
            self.logger.error(f"Failed to set volume encoder callbacks: {e}")
            raise
        
    def setup_sound_select_callbacks(self, next_sound, prev_sound, play_selected):
        """Configure callbacks for the sound selection encoder.

        Args:
            next_sound (callable): Function to call on next sound selection.
            prev_sound (callable): Function to call on previous sound selection.
            play_selected (callable): Function to call on play selected sound.
        """
        try:
            self.sound_select_encoder.set_callbacks(next_sound, prev_sound, play_selected)
            self.logger.info("Sound selection encoder callbacks configured")
        except Exception as e:
            self.logger.error(f"Failed to set sound selection encoder callbacks: {e}")
            raise
