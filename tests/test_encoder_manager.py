"""Tests for RotaryEncoder and EncoderManager classes."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def encoder(_mock_hardware_modules):
    """Create a RotaryEncoder with mocked GPIO pins."""
    _mock_hardware_modules["gpiozero"].Button.side_effect = [MagicMock()]
    _mock_hardware_modules["gpiozero"].RotaryEncoder.return_value = MagicMock()

    from smartchime.encoder_manager import RotaryEncoder

    enc = RotaryEncoder(1, 2, 3)
    return enc


@pytest.fixture
def manager(_mock_hardware_modules):
    """Create an EncoderManager with mocked GPIO pins."""
    _mock_hardware_modules["gpiozero"].Button.side_effect = [MagicMock(), MagicMock()]
    _mock_hardware_modules["gpiozero"].RotaryEncoder.return_value = MagicMock()

    from smartchime.encoder_manager import EncoderManager

    return EncoderManager(volume_pins=(1, 2, 3), sound_select_pins=(4, 5, 6))


class TestRotaryEncoder:
    def test_set_callbacks(self, encoder):
        cw = MagicMock()
        ccw = MagicMock()
        btn = MagicMock()

        encoder.set_callbacks(cw, ccw, btn)

        assert encoder._callback_button is btn
        assert encoder._callback_cw is cw
        assert encoder._callback_ccw is ccw
        # Verify gpiozero callbacks are wired (they wrap our callbacks)
        assert encoder.encoder.when_rotated_clockwise is not None
        assert encoder.encoder.when_rotated_counter_clockwise is not None

    def test_button_callback(self, encoder):
        btn = MagicMock()
        encoder.set_callbacks(None, None, btn)

        encoder._button_callback()

        btn.assert_called_once()

    def test_button_no_callback_set(self, encoder):
        """No error when button pressed without a callback configured."""
        encoder._callback_button = None
        encoder._button_callback()  # should not raise

    def test_encoder_uses_gpiozero_rotary_encoder(self, _mock_hardware_modules):
        """Verifies that gpiozero.RotaryEncoder is used instead of raw Buttons."""
        gpio_mock = _mock_hardware_modules["gpiozero"]
        gpio_mock.Button.side_effect = [MagicMock()]
        gpio_mock.RotaryEncoder.return_value = MagicMock()

        from smartchime.encoder_manager import RotaryEncoder

        enc = RotaryEncoder(10, 11, 12)
        gpio_mock.RotaryEncoder.assert_called_once_with(10, 11, max_steps=0)
        gpio_mock.Button.assert_called_once_with(12, bounce_time=0.05)
        assert enc.encoder is gpio_mock.RotaryEncoder.return_value

    def test_encoder_max_steps_forwarded(self, _mock_hardware_modules):
        """Verifies that max_steps is forwarded to gpiozero.RotaryEncoder."""
        gpio_mock = _mock_hardware_modules["gpiozero"]
        gpio_mock.Button.side_effect = [MagicMock()]
        gpio_mock.RotaryEncoder.return_value = MagicMock()

        from smartchime.encoder_manager import RotaryEncoder

        RotaryEncoder(10, 11, 12, max_steps=2)
        gpio_mock.RotaryEncoder.assert_called_once_with(10, 11, max_steps=2)

    def test_rotation_callback_logs_and_fires(self, encoder):
        """Rotation callback wrapper fires the user callback and logs timing."""
        cw = MagicMock()
        ccw = MagicMock()
        encoder.encoder.steps = 1
        encoder.set_callbacks(cw, ccw, MagicMock())

        encoder._rotation_callback("CW")
        cw.assert_called_once()

        encoder._rotation_callback("CCW")
        ccw.assert_called_once()


class TestEncoderManager:
    def test_init_creates_two_encoders(self, manager):
        assert manager.volume_encoder is not None
        assert manager.sound_select_encoder is not None

    def test_setup_volume_callbacks(self, manager):
        up = MagicMock()
        down = MagicMock()
        mute = MagicMock()

        manager.setup_volume_callbacks(up, down, mute)

        assert manager.volume_encoder._callback_button is mute
        assert manager.volume_encoder._callback_cw is up
        assert manager.volume_encoder._callback_ccw is down

    def test_setup_sound_select_callbacks(self, manager):
        nxt = MagicMock()
        prev = MagicMock()
        play = MagicMock()

        manager.setup_sound_select_callbacks(nxt, prev, play)

        assert manager.sound_select_encoder._callback_button is play
        assert manager.sound_select_encoder._callback_cw is nxt
        assert manager.sound_select_encoder._callback_ccw is prev
