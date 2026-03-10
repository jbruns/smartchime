"""Tests for AudioManager."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def mock_mixer(_mock_hardware_modules):
    """Return a configured mock Mixer instance."""
    mixer = MagicMock()
    mixer.getmute.return_value = [0]
    mixer.getvolume.return_value = [-5000]
    _mock_hardware_modules["alsaaudio"].Mixer.return_value = mixer
    _mock_hardware_modules["alsaaudio"].ALSAAudioError = Exception
    return mixer


@pytest.fixture()
def audio_dir(tmp_path):
    """Create a temp audio directory with sample .wav files."""
    d = tmp_path / "audio"
    d.mkdir()
    (d / "doorbell.wav").touch()
    (d / "chime.wav").touch()
    return d


@pytest.fixture()
def manager(mock_mixer, audio_dir):
    """Create an AudioManager with mocked mixer and real temp audio dir."""
    from smartchime.audio_manager import AudioManager

    return AudioManager(audio_dir=str(audio_dir), mixer_device="default", mixer_control="Digital")


@pytest.fixture()
def manager_with_oled(mock_mixer, audio_dir):
    """Create an AudioManager with a mock OLED manager attached."""
    from smartchime.audio_manager import AudioManager

    oled = MagicMock()
    return AudioManager(audio_dir=str(audio_dir), mixer_device="default", mixer_control="Digital", oled_manager=oled)


class TestGetAvailableSounds:
    def test_returns_wav_filenames(self, manager, audio_dir):
        sounds = manager.get_available_sounds()
        assert sorted(sounds) == ["chime.wav", "doorbell.wav"]

    def test_returns_empty_when_no_wav_files(self, mock_mixer, tmp_path):
        from smartchime.audio_manager import AudioManager

        empty_dir = tmp_path / "empty_audio"
        empty_dir.mkdir()
        (empty_dir / "readme.txt").touch()
        mgr = AudioManager(audio_dir=str(empty_dir))
        assert mgr.get_available_sounds() == []


class TestAdjustVolume:
    def test_clamps_to_upper_bound(self, manager, mock_mixer):
        mock_mixer.getvolume.return_value = [-100]
        manager.adjust_volume(500)
        mock_mixer.setvolume.assert_called_once_with(0, units=2)

    def test_clamps_to_lower_bound(self, manager, mock_mixer):
        mock_mixer.getvolume.return_value = [-10000]
        manager.adjust_volume(-500)
        mock_mixer.setvolume.assert_called_once_with(-10300, units=2)

    def test_skips_when_muted(self, manager, mock_mixer):
        mock_mixer.getmute.return_value = [1]
        manager.adjust_volume(100)
        mock_mixer.setvolume.assert_not_called()


class TestToggleMute:
    def test_unmutes_when_muted(self, manager, mock_mixer):
        mock_mixer.getmute.return_value = [1]
        manager.toggle_mute()
        mock_mixer.setmute.assert_called_once_with(0)

    def test_mutes_when_unmuted(self, manager, mock_mixer):
        mock_mixer.getmute.return_value = [0]
        manager.toggle_mute()
        mock_mixer.setmute.assert_called_once_with(1)


class TestPlaySound:
    def test_skips_when_muted(self, manager, mock_mixer):
        mock_mixer.getmute.return_value = [1]
        with patch("os.system") as mock_system:
            manager.play_sound("doorbell.wav")
            mock_system.assert_not_called()

    def test_skips_when_file_not_found(self, manager):
        with patch("os.system") as mock_system:
            manager.play_sound("nonexistent.wav")
            mock_system.assert_not_called()

    def test_calls_aplay_with_correct_command(self, manager, audio_dir):
        with patch("os.system", return_value=0) as mock_system:
            manager.play_sound("doorbell.wav")
            mock_system.assert_called_once_with(f"aplay {audio_dir / 'doorbell.wav'}")


class TestDisplayVolume:
    def test_shows_mute_on_oled(self, manager_with_oled, mock_mixer):
        mock_mixer.getmute.return_value = [1]
        manager_with_oled._display_volume()
        manager_with_oled.oled.set_volume_display.assert_called_once_with(level=0.0, muted=True, duration=3)

    def test_shows_volume_bar_on_oled(self, manager_with_oled, mock_mixer):
        mock_mixer.getmute.return_value = [0]
        mock_mixer.getvolume.return_value = [-5150]  # -51.50 dB → (−5150+10300)/10300 = 0.5
        manager_with_oled._display_volume()
        manager_with_oled.oled.set_volume_display.assert_called_once_with(level=0.5, muted=False, duration=3)

    def test_full_volume_level(self, manager_with_oled, mock_mixer):
        mock_mixer.getmute.return_value = [0]
        mock_mixer.getvolume.return_value = [0]  # 0 dB → level = 1.0
        manager_with_oled._display_volume()
        manager_with_oled.oled.set_volume_display.assert_called_once_with(level=1.0, muted=False, duration=3)

    def test_min_volume_level(self, manager_with_oled, mock_mixer):
        mock_mixer.getmute.return_value = [0]
        mock_mixer.getvolume.return_value = [-10300]  # -103 dB → level = 0.0
        manager_with_oled._display_volume()
        manager_with_oled.oled.set_volume_display.assert_called_once_with(level=0.0, muted=False, duration=3)


class TestInit:
    def test_warns_for_nonexistent_audio_dir(self, mock_mixer, tmp_path, caplog):
        import logging

        from smartchime.audio_manager import AudioManager

        with caplog.at_level(logging.WARNING):
            AudioManager(audio_dir=str(tmp_path / "missing"))
        assert "Audio directory does not exist" in caplog.text
