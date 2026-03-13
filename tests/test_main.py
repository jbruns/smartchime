"""Tests for SmartchimeSystem."""

import json
import logging
import time
from threading import Lock
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def system(sample_config):
    """Create a SmartchimeSystem without running __init__."""
    from smartchime.main import SmartchimeSystem

    sys_obj = object.__new__(SmartchimeSystem)
    sys_obj.logger = logging.getLogger("test")
    sys_obj.config = sample_config
    sys_obj.oled = MagicMock()
    sys_obj.audio = MagicMock()
    sys_obj.hdmi = MagicMock()
    sys_obj.encoders = MagicMock()
    sys_obj.shairport = MagicMock()
    sys_obj.mqtt_client = MagicMock()
    sys_obj.control_locks = {"volume": 0.0, "sound_select": 0.0, "toggle": 0.0}
    sys_obj._throttle_lock = Lock()
    sys_obj.available_sounds = ["doorbell.wav", "chime.wav"]
    sys_obj.current_sound_index = 0
    sys_obj._active_event_source = None
    return sys_obj


# ---------------------------------------------------------------------------
# _check_control_throttle
# ---------------------------------------------------------------------------


class TestCheckControlThrottle:
    def test_returns_false_first_call(self, system):
        assert system._check_control_throttle("volume") is False

    def test_returns_true_within_throttle_period(self, system):
        system._check_control_throttle("volume")
        assert system._check_control_throttle("volume") is True

    def test_uses_config_throttle_period(self, system):
        before = time.monotonic()
        system._check_control_throttle("volume")
        after = time.monotonic()
        assert before <= system.control_locks["volume"] <= after

    def test_unknown_control_type_uses_default(self, system):
        before = time.monotonic()
        assert system._check_control_throttle("nonexistent") is False
        after = time.monotonic()
        assert before <= system.control_locks["default"] <= after

    def test_lock_decremented_to_zero_allows_again(self, system):
        system._check_control_throttle("volume")
        system.control_locks["volume"] = 0
        assert system._check_control_throttle("volume") is False


# ---------------------------------------------------------------------------
# handle_event_message
# ---------------------------------------------------------------------------


class TestHandleEventMessage:
    VALID_PAYLOAD = {
        "active": True,
        "timestamp": "2025-01-01T12:00:00",
        "video_url": "http://example.com/clip.mp4",
    }

    def test_rejects_non_dict_payload(self, system):
        system.handle_event_message("smartchime/events/doorbell", "not a dict")
        system.audio.play_sound.assert_not_called()

    def test_rejects_missing_required_fields(self, system):
        system.handle_event_message("smartchime/events/doorbell", {"timestamp": "2025-01-01T12:00:00"})
        system.audio.play_sound.assert_not_called()

    def test_accepts_payload_without_video_url(self, system):
        payload = {"active": True, "timestamp": "2025-01-01T12:00:00"}
        system.handle_event_message("smartchime/events/doorbell", payload)
        system.audio.play_sound.assert_called_once()

    def test_rejects_invalid_timestamp(self, system):
        payload = {**self.VALID_PAYLOAD, "timestamp": "not-a-date"}
        system.handle_event_message("smartchime/events/doorbell", payload)
        system.audio.play_sound.assert_not_called()

    # --- Doorbell events ---

    def test_doorbell_active_plays_sound_and_video(self, system):
        payload = {**self.VALID_PAYLOAD, "active": True}
        system.handle_event_message("smartchime/events/doorbell", payload)
        system.audio.play_sound.assert_called_once_with("doorbell.wav")
        system.hdmi.play_video.assert_called_once_with("http://example.com/clip.mp4")
        assert system._active_event_source == "doorbell"

    def test_doorbell_active_without_video_url_uses_default(self, system):
        payload = {"active": True, "timestamp": "2025-01-01T12:00:00"}
        system.handle_event_message("smartchime/events/doorbell", payload)
        system.hdmi.play_video.assert_called_once_with("http://example.com/stream")

    def test_doorbell_inactive_stops_video(self, system):
        system._active_event_source = "doorbell"
        payload = {**self.VALID_PAYLOAD, "active": False}
        system.handle_event_message("smartchime/events/doorbell", payload)
        system.hdmi.stop_video.assert_called_once()
        assert system._active_event_source is None

    def test_doorbell_inactive_noop_when_not_source(self, system):
        system._active_event_source = "motion"
        payload = {**self.VALID_PAYLOAD, "active": False}
        system.handle_event_message("smartchime/events/doorbell", payload)
        system.hdmi.stop_video.assert_not_called()
        assert system._active_event_source == "motion"

    # --- Motion events ---

    def test_motion_active_plays_video(self, system):
        payload = {**self.VALID_PAYLOAD, "active": True}
        system.handle_event_message("smartchime/events/motion", payload)
        system.hdmi.play_video.assert_called_once_with("http://example.com/clip.mp4")
        assert system._active_event_source == "motion"

    def test_motion_active_without_video_url_uses_default(self, system):
        payload = {"active": True, "timestamp": "2025-01-01T12:00:00"}
        system.handle_event_message("smartchime/events/motion", payload)
        system.hdmi.play_video.assert_called_once_with("http://example.com/stream")

    def test_motion_active_suppressed_by_doorbell(self, system):
        system._active_event_source = "doorbell"
        payload = {**self.VALID_PAYLOAD, "active": True}
        system.handle_event_message("smartchime/events/motion", payload)
        system.hdmi.play_video.assert_not_called()
        assert system._active_event_source == "doorbell"

    def test_motion_inactive_stops_video(self, system):
        system._active_event_source = "motion"
        payload = {**self.VALID_PAYLOAD, "active": False}
        system.handle_event_message("smartchime/events/motion", payload)
        system.hdmi.stop_video.assert_called_once()
        assert system._active_event_source is None

    def test_motion_inactive_noop_when_doorbell_active(self, system):
        system._active_event_source = "doorbell"
        payload = {**self.VALID_PAYLOAD, "active": False}
        system.handle_event_message("smartchime/events/motion", payload)
        system.hdmi.stop_video.assert_not_called()
        assert system._active_event_source == "doorbell"

    # --- Priority: doorbell preempts motion ---

    def test_doorbell_preempts_motion(self, system):
        """Doorbell active takes over from motion — plays doorbell video, source switches."""
        system._active_event_source = "motion"
        payload = {**self.VALID_PAYLOAD, "active": True, "video_url": "http://example.com/doorbell.mp4"}
        system.handle_event_message("smartchime/events/doorbell", payload)
        system.audio.play_sound.assert_called_once()
        system.hdmi.play_video.assert_called_once_with("http://example.com/doorbell.mp4")
        assert system._active_event_source == "doorbell"

    def test_motion_does_not_play_sound(self, system):
        """Motion events should not trigger chime playback."""
        payload = {**self.VALID_PAYLOAD, "active": True}
        system.handle_event_message("smartchime/events/motion", payload)
        system.audio.play_sound.assert_not_called()


# ---------------------------------------------------------------------------
# Sound selection
# ---------------------------------------------------------------------------


class TestSoundSelection:
    def test_next_sound_wraps_around(self, system):
        system.current_sound_index = 1
        system.next_sound()
        assert system.current_sound_index == 0

    def test_prev_sound_wraps_around(self, system):
        system.current_sound_index = 0
        system.prev_sound()
        assert system.current_sound_index == 1

    def test_next_sound_no_sounds_available(self, system):
        system.available_sounds = []
        system.next_sound()
        system.oled.set_mode.assert_not_called()


# ---------------------------------------------------------------------------
# on_connect
# ---------------------------------------------------------------------------


class TestOnConnect:
    def test_subscribes_to_topics(self, system):
        client = MagicMock()
        system.on_connect(client, None, MagicMock(), 0, None)
        client.subscribe.assert_called_once()
        subscribed = client.subscribe.call_args[0][0]
        topics = {t[0] for t in subscribed}
        assert topics == {
            "smartchime/events/doorbell",
            "smartchime/events/motion",
            "smartchime/state/oled",
        }

    def test_failed_connection(self, system):
        client = MagicMock()
        system.on_connect(client, None, MagicMock(), 1, None)
        client.subscribe.assert_not_called()


# ---------------------------------------------------------------------------
# AirPlay metadata
# ---------------------------------------------------------------------------


class TestAirplayMetadata:
    def test_artist_and_title(self, system):
        system._handle_airplay_metadata("Artist", "Title", True)
        system.oled.set_temporary_message.assert_called_once_with("Title - Artist", duration=30)

    def test_title_only(self, system):
        system._handle_airplay_metadata("", "Title", True)
        system.oled.set_temporary_message.assert_called_once_with("Title", duration=30)

    def test_artist_only(self, system):
        system._handle_airplay_metadata("Artist", "", True)
        system.oled.set_temporary_message.assert_called_once_with("Artist", duration=30)

    def test_not_playing(self, system):
        system._handle_airplay_metadata("Artist", "Title", False)
        system.oled.set_temporary_message.assert_not_called()


# ---------------------------------------------------------------------------
# on_message
# ---------------------------------------------------------------------------


class TestOnMessage:
    def _make_msg(self, topic, payload):
        msg = MagicMock()
        msg.topic = topic
        msg.payload = json.dumps(payload).encode()
        return msg

    def test_routes_doorbell_topic(self, system):
        payload = {"active": True, "timestamp": "2025-01-01T12:00:00", "video_url": "http://example.com/clip.mp4"}
        msg = self._make_msg("smartchime/events/doorbell", payload)
        with patch.object(system, "handle_event_message") as mock_hem:
            system.on_message(None, None, msg)
            mock_hem.assert_called_once_with("smartchime/events/doorbell", payload)

    def test_invalid_json(self, system):
        msg = MagicMock()
        msg.topic = "smartchime/events/doorbell"
        msg.payload = b"not json"
        system.on_message(None, None, msg)

    def test_routes_oled_state_topic(self, system):
        payload = {"version": 2, "active": True}
        msg = self._make_msg("smartchime/state/oled", payload)
        with patch.object(system, "handle_oled_state") as mock_hos:
            system.on_message(None, None, msg)
            mock_hos.assert_called_once_with(payload)


# ---------------------------------------------------------------------------
# handle_oled_state
# ---------------------------------------------------------------------------


class TestHandleOledState:
    def test_calls_apply_v2_state(self, system):
        payload = {"version": 2, "active": True}
        system.handle_oled_state(payload)
        system.oled.apply_v2_state.assert_called_once_with(payload)

    def test_catches_value_error(self, system):
        system.oled.apply_v2_state.side_effect = ValueError("bad version")
        system.handle_oled_state({"version": 99})
        # Should not raise

    def test_catches_runtime_error(self, system):
        system.oled.apply_v2_state.side_effect = RuntimeError("device error")
        system.handle_oled_state({"version": 2})
        # Should not raise
