"""Shared fixtures for Smartchime tests.

Hardware dependencies (luma, gpiozero, alsaaudio, vcgencmd, vlc, rpi-lgpio)
are mocked at import time so tests can run on any platform.
"""

import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock hardware modules before any smartchime imports that need them.
# Each entry creates a MagicMock that stands in for the real module.
# ---------------------------------------------------------------------------
_HARDWARE_MODULES = [
    "alsaaudio",
    "gpiozero",
    "luma",
    "luma.core",
    "luma.core.interface",
    "luma.core.interface.serial",
    "luma.core.render",
    "luma.core.image_composition",
    "luma.oled",
    "luma.oled.device",
    "vcgencmd",
    "vlc",
    "lgpio",
]


@pytest.fixture(autouse=True)
def _mock_hardware_modules(monkeypatch):
    """Inject mock modules for all hardware dependencies."""
    mocks = {}
    for mod_name in _HARDWARE_MODULES:
        mock = MagicMock()
        mocks[mod_name] = mock
        monkeypatch.setitem(sys.modules, mod_name, mock)

    yield mocks

    # Clean up any smartchime modules cached with mocked deps so they
    # don't leak between tests.
    to_remove = [key for key in sys.modules if key.startswith("smartchime")]
    for key in to_remove:
        del sys.modules[key]


@pytest.fixture()
def sample_config(tmp_path):
    """Provide a minimal config dict matching config.example.yaml structure."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "doorbell.wav").touch()
    (audio_dir / "chime.wav").touch()

    return {
        "mqtt": {
            "broker": "localhost",
            "port": 1883,
            "username": "",
            "password": "",
            "topics": {
                "doorbell": "smartchime/events/doorbell",
                "motion": "smartchime/events/motion",
                "oled_state": "smartchime/state/oled",
            },
        },
        "audio": {
            "directory": str(audio_dir),
            "default_sound": "doorbell.wav",
            "mixer": {
                "device": "default",
                "control": "Digital",
            },
        },
        "video": {
            "default_stream": "http://example.com/stream",
        },
        "displays": {
            "oled": {
                "spi_port": 0,
                "spi_device": 0,
            },
        },
        "gpio": {
            "volume_encoder": {"clk": 15, "dt": 23, "sw": 14},
            "sound_select_encoder": {"clk": 27, "dt": 22, "sw": 17},
        },
        "controls": {
            "throttle": {
                "volume": 0.15,
                "sound_select": 0.25,
                "toggle": 0.5,
                "default": 0.25,
            },
        },
        "shairport": {
            "metadata_pipe": "/tmp/shairport-sync-metadata",
        },
    }
