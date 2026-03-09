"""Tests for SmartchimeSystem."""

import json
import logging
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
    sys_obj.control_locks = {"volume": 0, "sound_select": 0, "toggle": 0}
    sys_obj.available_sounds = ["doorbell.wav", "chime.wav"]
    sys_obj.current_sound_index = 0
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
        system._check_control_throttle("volume")
        assert system.control_locks["volume"] == system.config["controls"]["throttle"]["volume"]

    def test_unknown_control_type_uses_default(self, system):
        system._check_control_throttle("nonexistent")
        assert system.control_locks["default"] == system.config["controls"]["throttle"]["default"]

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
        system.handle_event_message("smartchime/doorbell/ring", "not a dict")
        system.oled.update_motion_status.assert_not_called()
        system.audio.play_sound.assert_not_called()

    def test_rejects_missing_fields(self, system):
        system.handle_event_message("smartchime/doorbell/ring", {"active": True})
        system.audio.play_sound.assert_not_called()

    def test_rejects_invalid_timestamp(self, system):
        payload = {**self.VALID_PAYLOAD, "timestamp": "not-a-date"}
        system.handle_event_message("smartchime/doorbell/ring", payload)
        system.audio.play_sound.assert_not_called()

    def test_motion_active_updates_oled(self, system):
        payload = {**self.VALID_PAYLOAD, "active": True}
        system.handle_event_message("smartchime/motion/detected", payload)
        system.oled.update_motion_status.assert_called_once()
        system.oled.set_temporary_message.assert_called_once_with("Person detected on doorbell camera!")

    def test_motion_inactive_clears_message(self, system):
        payload = {**self.VALID_PAYLOAD, "active": False}
        system.handle_event_message("smartchime/motion/detected", payload)
        system.oled.clear_temporary_message.assert_called_once()

    def test_doorbell_active_plays_sound_and_video(self, system):
        payload = {**self.VALID_PAYLOAD, "active": True}
        system.handle_event_message("smartchime/doorbell/ring", payload)
        system.audio.play_sound.assert_called_once_with("doorbell.wav")
        system.hdmi.play_video.assert_called_once_with("http://example.com/clip.mp4")

    def test_doorbell_inactive_stops_video(self, system):
        payload = {**self.VALID_PAYLOAD, "active": False}
        system.handle_event_message("smartchime/doorbell/ring", payload)
        system.oled.clear_temporary_message.assert_called_once()
        system.hdmi.stop_video.assert_called_once()


# ---------------------------------------------------------------------------
# handle_message
# ---------------------------------------------------------------------------


class TestHandleMessage:
    def test_dict_payload_extracts_text(self, system):
        system.handle_message({"text": "hello"})
        system.oled.set_scrolling_message.assert_called_once_with("hello")

    def test_string_payload_used_directly(self, system):
        system.handle_message("hello")
        system.oled.set_scrolling_message.assert_called_once_with("hello")


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
        system.on_connect(client, None, {}, 0)
        client.subscribe.assert_called_once()
        subscribed = client.subscribe.call_args[0][0]
        topics = {t[0] for t in subscribed}
        assert topics == {"smartchime/doorbell/ring", "smartchime/motion/detected", "smartchime/display/message"}

    def test_failed_connection(self, system):
        client = MagicMock()
        system.on_connect(client, None, {}, 1)
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
        msg = self._make_msg("smartchime/doorbell/ring", payload)
        with patch.object(system, "handle_event_message") as mock_hem:
            system.on_message(None, None, msg)
            mock_hem.assert_called_once_with("smartchime/doorbell/ring", payload)

    def test_routes_message_topic(self, system):
        payload = {"text": "hello"}
        msg = self._make_msg("smartchime/display/message", payload)
        with patch.object(system, "handle_message") as mock_hm:
            system.on_message(None, None, msg)
            mock_hm.assert_called_once_with(payload)

    def test_invalid_json(self, system):
        msg = MagicMock()
        msg.topic = "smartchime/doorbell/ring"
        msg.payload = b"not json"
        system.on_message(None, None, msg)
