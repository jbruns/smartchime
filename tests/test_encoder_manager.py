"""Tests for RotaryEncoder and EncoderManager classes."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def encoder(_mock_hardware_modules):
    """Create a RotaryEncoder with mocked GPIO pins."""
    # Each Button() call must return a distinct mock so clk/dt/sw don't share state
    _mock_hardware_modules["gpiozero"].Button.side_effect = [MagicMock(), MagicMock(), MagicMock()]

    from smartchime.encoder_manager import RotaryEncoder

    enc = RotaryEncoder(1, 2, 3)
    enc.clk_last_state = 0
    return enc


@pytest.fixture
def manager(_mock_hardware_modules):
    """Create an EncoderManager with mocked GPIO pins."""
    _mock_hardware_modules["gpiozero"].Button.side_effect = [MagicMock() for _ in range(6)]

    from smartchime.encoder_manager import EncoderManager

    return EncoderManager(volume_pins=(1, 2, 3), sound_select_pins=(4, 5, 6))


class TestRotaryEncoder:
    def test_set_callbacks(self, encoder):
        cw = MagicMock()
        ccw = MagicMock()
        btn = MagicMock()

        encoder.set_callbacks(cw, ccw, btn)

        assert encoder.callback_cw is cw
        assert encoder.callback_ccw is ccw
        assert encoder.callback_button is btn

    def test_rotation_cw(self, encoder):
        """CW fires when clk_state != clk_last_state and dt_state != clk_state."""
        cw = MagicMock()
        ccw = MagicMock()
        encoder.set_callbacks(cw, ccw, None)

        # clk_last_state=0, clk=1 (changed), dt=0 (dt != clk) → CW
        encoder.clk.value = 1
        encoder.dt.value = 0
        encoder._rotation_callback()

        cw.assert_called_once()
        ccw.assert_not_called()

    def test_rotation_ccw(self, encoder):
        """CCW fires when clk_state != clk_last_state and dt_state == clk_state."""
        cw = MagicMock()
        ccw = MagicMock()
        encoder.set_callbacks(cw, ccw, None)

        # clk_last_state=0, clk=1 (changed), dt=1 (dt == clk) → CCW
        encoder.clk.value = 1
        encoder.dt.value = 1
        encoder._rotation_callback()

        ccw.assert_called_once()
        cw.assert_not_called()

    def test_rotation_no_change(self, encoder):
        """No callback when clk_state == clk_last_state."""
        cw = MagicMock()
        ccw = MagicMock()
        encoder.set_callbacks(cw, ccw, None)

        # clk_last_state=0, clk=0 (unchanged) → nothing
        encoder.clk.value = 0
        encoder.dt.value = 1
        encoder._rotation_callback()

        cw.assert_not_called()
        ccw.assert_not_called()

    def test_rotation_no_callbacks_set(self, encoder):
        """No error when rotating without callbacks configured."""
        encoder.clk.value = 1
        encoder.dt.value = 0
        encoder._rotation_callback()  # should not raise

    def test_button_callback(self, encoder):
        btn = MagicMock()
        encoder.set_callbacks(None, None, btn)

        encoder._button_callback()

        btn.assert_called_once()

    def test_button_no_callback_set(self, encoder):
        """No error when button pressed without a callback configured."""
        encoder._button_callback()  # should not raise


class TestEncoderManager:
    def test_init_creates_two_encoders(self, manager):
        assert manager.volume_encoder is not None
        assert manager.sound_select_encoder is not None

    def test_setup_volume_callbacks(self, manager):
        up = MagicMock()
        down = MagicMock()
        mute = MagicMock()

        manager.setup_volume_callbacks(up, down, mute)

        assert manager.volume_encoder.callback_cw is up
        assert manager.volume_encoder.callback_ccw is down
        assert manager.volume_encoder.callback_button is mute

    def test_setup_sound_select_callbacks(self, manager):
        nxt = MagicMock()
        prev = MagicMock()
        play = MagicMock()

        manager.setup_sound_select_callbacks(nxt, prev, play)

        assert manager.sound_select_encoder.callback_cw is nxt
        assert manager.sound_select_encoder.callback_ccw is prev
        assert manager.sound_select_encoder.callback_button is play
