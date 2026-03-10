"""Tests for OLEDManager class."""

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


def _make_text_font():
    """Return a mock font where getlength returns len(text)*8 and getbbox returns a 10px-high bbox."""
    font = MagicMock()
    font.getlength = MagicMock(side_effect=lambda text: len(text) * 8)
    font.getbbox = MagicMock(side_effect=lambda text: (0, 0, len(text) * 8, 10))
    return font


def _make_scroll_font(char_width=10):
    """Return a mock scroll font where getlength returns len(text)*char_width."""
    font = MagicMock()
    font.getlength = MagicMock(side_effect=lambda text: len(text) * char_width)
    return font


@pytest.fixture()
def mgr(_mock_hardware_modules):
    """Construct an OLEDManager (all hardware is mocked) and patch attributes for pure-logic testing."""
    import sys

    # Configure the mocked ssd1306 to return a device with real int dimensions
    # so PIL Image.new() calls in __init__ work.
    mock_device = MagicMock()
    mock_device.width = 128
    mock_device.height = 32
    sys.modules["luma.oled.device"].ssd1306.return_value = mock_device

    from smartchime.oled_manager import OLEDManager

    with patch("smartchime.oled_manager.ImageFont"):
        manager = OLEDManager()

    manager.text_font = _make_text_font()
    manager.scroll_font = _make_scroll_font()
    manager.icon_font = _make_text_font()
    manager.status_font = _make_text_font()
    return manager


class TestOLEDManager:
    # -- _format_motion_time --------------------------------------------------

    def test_format_motion_time_active(self, mgr):
        mgr.motion_active = True
        assert mgr._format_motion_time() == "now"

    def test_format_motion_time_no_last_time(self, mgr):
        mgr.motion_active = False
        mgr.last_motion_time = None
        assert mgr._format_motion_time() == "--"

    def test_format_motion_time_minutes(self, mgr):
        mgr.motion_active = False
        mgr.last_motion_time = datetime.now(UTC) - timedelta(minutes=5)
        result = mgr._format_motion_time()
        assert result == "5m"

    def test_format_motion_time_hours(self, mgr):
        mgr.motion_active = False
        mgr.last_motion_time = datetime.now(UTC) - timedelta(hours=2, minutes=30)
        result = mgr._format_motion_time()
        assert result == "2h"

    # -- set_mode -------------------------------------------------------------

    def test_set_mode_centered(self, mgr):
        mgr.set_mode(mgr.MODE_CENTERED, line1="Hello", line2="World")
        assert mgr.current_mode == mgr.MODE_CENTERED
        assert mgr.line1 == "Hello"
        assert mgr.line2 == "World"
        assert mgr.status_update_needed is True
        assert mgr.content_update_needed is True

    def test_set_mode_invalid(self, mgr):
        with pytest.raises(ValueError, match="Invalid mode"):
            mgr.set_mode("bogus_mode")

    @patch("smartchime.oled_manager.Timer")
    def test_set_mode_with_duration(self, mock_timer_cls, mgr):
        timer_instance = MagicMock()
        mock_timer_cls.return_value = timer_instance
        mgr.set_mode(mgr.MODE_CENTERED, line1="Alert", duration=5.0)
        mock_timer_cls.assert_called_once_with(5.0, mgr._revert_to_default)
        timer_instance.start.assert_called_once()

    @patch("smartchime.oled_manager.Timer")
    def test_set_mode_cancels_previous_timer(self, mock_timer_cls, mgr):
        old_timer = MagicMock()
        mgr.mode_timer = old_timer

        new_timer = MagicMock()
        mock_timer_cls.return_value = new_timer

        mgr.set_mode(mgr.MODE_CENTERED, line1="New", duration=3.0)
        old_timer.cancel.assert_called_once()
        assert mgr.mode_timer is new_timer

    # -- set_scrolling_message ------------------------------------------------

    def test_set_scrolling_message(self, mgr):
        mgr.current_mode = mgr.MODE_DEFAULT
        mgr.set_scrolling_message("Hello World")
        assert mgr.current_message == "Hello World"
        assert mgr.scroll_position == 0
        assert mgr.scroll_start_time is None
        assert mgr.scroll_paused is False
        assert mgr.content_update_needed is True

    def test_set_scrolling_message_ignored_in_centered_mode(self, mgr):
        mgr.current_mode = mgr.MODE_CENTERED
        mgr.current_message = "original"
        mgr.set_scrolling_message("new message")
        assert mgr.current_message == "original"

    # -- set_temporary_message / clear_temporary_message ----------------------

    def test_set_temporary_message(self, mgr):
        mgr.current_mode = mgr.MODE_DEFAULT
        mgr.current_message = "original"
        mgr.set_temporary_message("temp msg")
        assert mgr.current_message == "temp msg"
        assert mgr.temp_message == "temp msg"
        assert mgr.original_message == "original"
        assert mgr.scroll_position == 0
        assert mgr.content_update_needed is True

    def test_clear_temporary_message(self, mgr):
        mgr.current_mode = mgr.MODE_DEFAULT
        mgr.current_message = "original"
        mgr.set_temporary_message("temp msg")
        mgr.clear_temporary_message()
        assert mgr.current_message == "original"
        assert mgr.temp_message is None

    # -- update_motion_status -------------------------------------------------

    def test_update_motion_status(self, mgr):
        mgr.status_update_needed = False
        now = datetime.now(UTC)
        mgr.update_motion_status(active=True, last_time=now)
        assert mgr.motion_active is True
        assert mgr.last_motion_time == now
        assert mgr.status_update_needed is True

    def test_update_motion_status_no_change(self, mgr):
        now = datetime.now(UTC)
        mgr.motion_active = True
        mgr.last_motion_time = now
        mgr.status_update_needed = False
        mgr.update_motion_status(active=True, last_time=now)
        assert mgr.status_update_needed is False

    # -- _update_scroll_state -------------------------------------------------

    def test_update_scroll_state_initializes_start_time(self, mgr):
        mgr.current_mode = mgr.MODE_DEFAULT
        mgr.current_message = "A" * 50  # 50*10=500 > 128
        mgr._cached_msg_width = 500
        mgr.scroll_start_time = None
        mgr._update_scroll_state()
        assert mgr.scroll_start_time is not None

    def test_update_scroll_state_increments_position(self, mgr):
        mgr.current_mode = mgr.MODE_DEFAULT
        mgr.current_message = "A" * 50  # 500px > 128
        mgr._cached_msg_width = 500
        # Set start_time 1 second ago → position = int(1.0 * 45) = 45
        mgr.scroll_start_time = time.monotonic() - 1.0
        mgr.scroll_position = 0
        mgr._last_rendered_scroll_pos = -1
        mgr.scroll_paused = False
        mgr._update_scroll_state()
        assert mgr.scroll_position == 45
        assert mgr.content_update_needed is True

    def test_update_scroll_state_pauses_at_end(self, mgr):
        mgr.current_mode = mgr.MODE_DEFAULT
        mgr.current_message = "A" * 50  # msg_width=500
        mgr._cached_msg_width = 500
        mgr.scroll_paused = False
        # Need elapsed time such that int(elapsed * 45) >= 500 + 128 = 628
        # elapsed = 628 / 45 = ~13.96s
        mgr.scroll_start_time = time.monotonic() - 14.0
        mgr._last_rendered_scroll_pos = -1
        mgr._update_scroll_state()
        assert mgr.scroll_paused is True

    def test_update_scroll_state_resumes_after_pause(self, mgr):
        mgr.current_mode = mgr.MODE_DEFAULT
        mgr.current_message = "A" * 50
        mgr._cached_msg_width = 500
        mgr.scroll_paused = True
        mgr.scroll_start_time = time.monotonic() - 2.5  # > 2.0s pause
        mgr._update_scroll_state()
        assert mgr.scroll_paused is False
        assert mgr.scroll_position == 0
        assert mgr.content_update_needed is True

    # -- _truncate_text -------------------------------------------------------

    def test_truncate_text_fits(self, mgr):
        draw = MagicMock()
        short = "Hi"  # 2*8=16 < 128
        assert mgr._truncate_text(short, 128, draw) == "Hi"

    def test_truncate_text_too_long(self, mgr):
        draw = MagicMock()
        long_text = "A" * 30  # 30*8=240 > 128
        result = mgr._truncate_text(long_text, 128, draw)
        assert result.endswith("...")
        assert len(result) < len(long_text)

    # -- _center_text ---------------------------------------------------------

    def test_center_text(self, mgr):
        draw = MagicMock()
        text = "Test"  # width=4*8=32, bbox height=10
        x, y = mgr._center_text(text, draw, height=12, y_offset=0)
        expected_x = (128 - 32) // 2  # 48
        expected_y = (12 - 10) // 2  # 1
        assert x == expected_x
        assert y == expected_y

    # -- set_volume_display ---------------------------------------------------

    def test_set_volume_display_sets_mode(self, mgr):
        mgr.set_volume_display(level=0.5)
        assert mgr.current_mode == mgr.MODE_VOLUME
        assert mgr.volume_level == 0.5
        assert mgr.volume_muted is False
        assert mgr.content_update_needed is True

    def test_set_volume_display_muted(self, mgr):
        mgr.set_volume_display(level=0.0, muted=True)
        assert mgr.volume_muted is True

    def test_set_volume_display_clamps_level(self, mgr):
        mgr.set_volume_display(level=1.5)
        assert mgr.volume_level == 1.0
        mgr.set_volume_display(level=-0.5)
        assert mgr.volume_level == 0.0

    @patch("smartchime.oled_manager.Timer")
    def test_set_volume_display_starts_timer(self, mock_timer_cls, mgr):
        timer_instance = MagicMock()
        mock_timer_cls.return_value = timer_instance
        mgr.set_volume_display(level=0.5, duration=3.0)
        mock_timer_cls.assert_called_once_with(3.0, mgr._revert_to_default)
        timer_instance.start.assert_called_once()

    @patch("smartchime.oled_manager.Timer")
    def test_set_volume_display_resets_timer_on_repeat(self, mock_timer_cls, mgr):
        first_timer = MagicMock()
        second_timer = MagicMock()
        mock_timer_cls.side_effect = [first_timer, second_timer]

        mgr.set_volume_display(level=0.3, duration=3.0)
        mgr.set_volume_display(level=0.6, duration=3.0)

        first_timer.cancel.assert_called_once()
        second_timer.start.assert_called_once()
        assert mgr.volume_level == 0.6

    def test_revert_to_default_from_volume(self, mgr):
        mgr.set_volume_display(level=0.5)
        assert mgr.current_mode == mgr.MODE_VOLUME
        mgr._revert_to_default()
        assert mgr.current_mode == mgr.MODE_DEFAULT

    # -- cleanup --------------------------------------------------------------

    def test_cleanup_cancels_timers(self, mgr):
        timer = MagicMock()
        mgr.temp_timer = timer
        mgr.cleanup()
        timer.cancel.assert_called_once()
        assert mgr.temp_timer is None
