"""Tests for HDMIManager."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def hdmi_manager(_mock_hardware_modules):
    """Create an HDMIManager instance with all hardware mocked."""
    from smartchime.hdmi_manager import HDMIManager

    manager = HDMIManager()
    # Reset mock call history from __init__
    manager.vcgencmd.reset_mock()
    return manager


class TestHDMIManager:
    def test_init_powers_off_display(self, _mock_hardware_modules):
        """__init__ calls vcgencmd.display_power_off(2)."""
        from smartchime.hdmi_manager import HDMIManager

        manager = HDMIManager()
        manager.vcgencmd.display_power_off.assert_called_once_with(2)

    def test_set_display_power_on(self, hdmi_manager):
        """_set_display_power('on') calls display_power_on(2)."""
        hdmi_manager._set_display_power("on")
        hdmi_manager.vcgencmd.display_power_on.assert_called_once_with(2)

    def test_set_display_power_off(self, hdmi_manager):
        """_set_display_power('off') calls display_power_off(2)."""
        hdmi_manager._set_display_power("off")
        hdmi_manager.vcgencmd.display_power_off.assert_called_once_with(2)

    def test_get_display_power_state(self, hdmi_manager):
        """Delegates to vcgencmd.display_power_state(2)."""
        hdmi_manager.vcgencmd.display_power_state.return_value = "on"
        result = hdmi_manager.get_display_power_state()
        hdmi_manager.vcgencmd.display_power_state.assert_called_once_with(2)
        assert result == "on"

    def test_play_video_creates_player(self, hdmi_manager, _mock_hardware_modules):
        """Creates VLC instance, sets MRL, and calls play."""
        vlc_mock = _mock_hardware_modules["vlc"]
        mock_instance = MagicMock()
        mock_player = MagicMock()
        mock_player.get_state.return_value = MagicMock()
        mock_player.event_manager.return_value = MagicMock()
        mock_instance.media_player_new.return_value = mock_player
        vlc_mock.Instance.return_value = mock_instance

        # Make the playback event fire immediately
        hdmi_manager._playback_event = MagicMock()
        hdmi_manager._playback_event.wait.return_value = True

        hdmi_manager.play_video("rtsp://example.com/stream")

        vlc_mock.Instance.assert_called_once()
        mock_instance.media_player_new.assert_called_once()
        mock_player.set_mrl.assert_called_once_with("rtsp://example.com/stream")
        mock_player.play.assert_called_once()

    def test_play_video_stops_existing_player(self, hdmi_manager, _mock_hardware_modules):
        """Stops previous player before creating a new one."""
        vlc_mock = _mock_hardware_modules["vlc"]
        old_player = MagicMock()
        hdmi_manager.player = old_player

        mock_instance = MagicMock()
        mock_player = MagicMock()
        mock_player.get_state.return_value = MagicMock()
        mock_player.event_manager.return_value = MagicMock()
        mock_instance.media_player_new.return_value = mock_player
        vlc_mock.Instance.return_value = mock_instance

        hdmi_manager._playback_event = MagicMock()
        hdmi_manager._playback_event.wait.return_value = True

        hdmi_manager.play_video("rtsp://example.com/stream")

        old_player.stop.assert_called_once()

    def test_play_video_error_state_powers_off(self, hdmi_manager, _mock_hardware_modules):
        """Powers off display when VLC enters error state."""
        vlc_mock = _mock_hardware_modules["vlc"]
        error_state = vlc_mock.State.Error

        mock_instance = MagicMock()
        mock_player = MagicMock()
        mock_player.get_state.return_value = error_state
        mock_player.event_manager.return_value = MagicMock()
        mock_instance.media_player_new.return_value = mock_player
        vlc_mock.Instance.return_value = mock_instance

        hdmi_manager._playback_event = MagicMock()
        hdmi_manager._playback_event.wait.return_value = True

        hdmi_manager.play_video("rtsp://example.com/bad")

        hdmi_manager.vcgencmd.display_power_off.assert_called_with(2)

    def test_stop_video_stops_player(self, hdmi_manager):
        """Stops player, releases it, sets to None, and powers off display."""
        mock_player = MagicMock()
        hdmi_manager.player = mock_player

        hdmi_manager.stop_video()

        mock_player.stop.assert_called_once()
        mock_player.release.assert_called_once()
        assert hdmi_manager.player is None
        hdmi_manager.vcgencmd.display_power_off.assert_called_once_with(2)

    def test_stop_video_noop_without_player(self, hdmi_manager):
        """Powers off display even when self.player is None."""
        hdmi_manager.player = None
        hdmi_manager.stop_video()
        hdmi_manager.vcgencmd.display_power_off.assert_called_once_with(2)

    def test_cleanup_releases_vlc_instance(self, hdmi_manager, _mock_hardware_modules):
        """cleanup() releases the VLC instance."""
        vlc_mock = _mock_hardware_modules["vlc"]
        mock_instance = MagicMock()
        vlc_mock.Instance.return_value = mock_instance
        hdmi_manager._vlc_instance = mock_instance

        hdmi_manager.cleanup()

        mock_instance.release.assert_called_once()
        assert hdmi_manager._vlc_instance is None
