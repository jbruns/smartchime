import logging
import time

from gpiozero import Button
from gpiozero import RotaryEncoder as GpioRotaryEncoder


class RotaryEncoder:
    BUTTON_BOUNCE_TIME = 0.05

    def __init__(self, clk_pin, dt_pin, sw_pin, max_steps=0):
        """Initialize a rotary encoder with GPIO pins.

        Uses gpiozero's RotaryEncoder for proper hardware quadrature decoding
        with built-in debouncing, and a separate Button for the push switch.

        Args:
            clk_pin (int): GPIO pin for the clock signal (channel A).
            dt_pin (int): GPIO pin for the data signal (channel B).
            sw_pin (int): GPIO pin for the button signal.
            max_steps (int): Maximum step counter range for gpiozero's RotaryEncoder.
                0 = unbounded. A small value (e.g. 2) can reduce ghost inputs
                from contact bounce after the user stops turning.
        """
        self.logger = logging.getLogger(__name__)
        self._last_rotation_time = 0.0
        self._label = f"CLK:{clk_pin}"

        try:
            self.encoder = GpioRotaryEncoder(clk_pin, dt_pin, max_steps=max_steps)
            self.sw = Button(sw_pin, bounce_time=self.BUTTON_BOUNCE_TIME)
            self.logger.info(
                f"Initialized rotary encoder on pins CLK:{clk_pin}, DT:{dt_pin}, SW:{sw_pin} (max_steps={max_steps})"
            )
        except Exception as e:
            self.logger.error(f"Failed to setup GPIO pins for rotary encoder: {e}")
            raise

        self._callback_button = None
        self._callback_cw = None
        self._callback_ccw = None
        self.sw.when_pressed = self._button_callback

    def _button_callback(self):
        """Handle button press events and trigger the button callback."""
        if self._callback_button:
            self.logger.debug("Encoder button pressed")
            self._callback_button()

    def _rotation_callback(self, direction):
        """Log rotation events with timing info for ghost input debugging."""
        now = time.monotonic()
        delta = now - self._last_rotation_time if self._last_rotation_time else 0.0
        self._last_rotation_time = now
        self.logger.debug(f"[{self._label}] rotation {direction} | steps={self.encoder.steps} | dt={delta:.4f}s")
        cb = self._callback_cw if direction == "CW" else self._callback_ccw
        if cb:
            cb()

    def set_callbacks(self, callback_cw, callback_ccw, callback_button):
        """Set the callbacks for clockwise, counter-clockwise, and button press events.

        Args:
            callback_cw (callable): Function to call on clockwise rotation.
            callback_ccw (callable): Function to call on counter-clockwise rotation.
            callback_button (callable): Function to call on button press.
        """
        self._callback_button = callback_button
        self._callback_cw = callback_cw
        self._callback_ccw = callback_ccw
        self.encoder.when_rotated_clockwise = lambda: self._rotation_callback("CW")
        self.encoder.when_rotated_counter_clockwise = lambda: self._rotation_callback("CCW")
        self.logger.debug("Encoder callbacks configured")


class EncoderManager:
    def __init__(self, volume_pins, sound_select_pins, max_steps=0):
        """Initialize the encoder manager with volume and sound selection encoders.

        Args:
            volume_pins (tuple): GPIO pins for the volume encoder (CLK, DT, SW).
            sound_select_pins (tuple): GPIO pins for the sound selection encoder (CLK, DT, SW).
            max_steps (int): max_steps parameter for gpiozero RotaryEncoder (0 = unbounded).
        """
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing encoder manager")

        try:
            self.volume_encoder = RotaryEncoder(*volume_pins, max_steps=max_steps)
            self.logger.info("Volume encoder initialized")

            self.sound_select_encoder = RotaryEncoder(*sound_select_pins, max_steps=max_steps)
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
