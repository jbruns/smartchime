# Copilot Instructions for Smartchime

## Project Overview

Smartchime is a Python-based smart doorbell system for Raspberry Pi 4B. It integrates hardware (HifiBerry Amp2, OLED display, AMOLED display, rotary encoders) with MQTT-driven events from Home Assistant to play chimes, show camera feeds, and display messages.

## Architecture

The system follows a manager pattern with `SmartchimeSystem` (in `src/smartchime/main.py`) as the central orchestrator:

- **`audio_manager.py`** — WAV playback via `aplay`, ALSA mixer volume/mute control
- **`hdmi_manager.py`** — AMOLED display power and VLC-based RTSP/video playback via `vcgencmd`
- **`oled_manager.py`** — SSD1305 128x32 OLED driven via `luma.oled` (SPI), with a two-layer composition (status bar + content area) and scrolling text
- **`encoder_manager.py`** — Two rotary encoders via `gpiozero` (volume control and sound selection)
- **`shairport_metadata.py`** — Reads AirPlay metadata from the shairport-sync named pipe in a background thread
- **`luma_patch.py`** — Monkey-patches `luma.core.image_composition` for Pillow compatibility; must be imported before any luma usage

All modules live in `src/smartchime/`. Configuration is loaded from `config.yaml` (copy `config.example.yaml` to create it). MQTT topics, GPIO pins, audio paths, and throttle timings are all config-driven.

## Key Conventions

- **Logging everywhere.** Every module uses `logging.getLogger(__name__)` extensively. Follow this pattern in new code.
- **`luma_patch` import order matters.** `main.py` imports `luma_patch` before other smartchime modules to patch luma's `ImageComposition.refresh` for modern Pillow.
- **OLED display uses SSD1305**, but is initialized as `ssd1306` with manual register fixups (`0xDA, 0x12` and column offset adjustments).
- **Throttle system** — Control inputs are throttled via a cycle-counting mechanism in the main loop (each cycle ≈ 12.5ms via `time.sleep(0.0125)`). Throttle periods are configured per control type.
- **MQTT payloads** — Doorbell/motion events expect `{"active": bool, "timestamp": "ISO8601", "video_url": "url"}`. OLED messages accept `{"text": "string"}` or plain strings.

## Code Quality

- **Ruff** is configured in `pyproject.toml` for linting and formatting (target: py311, line-length: 120).
- **Pytest** is set up with tests in `tests/`. Hardware-dependent tests use the `@pytest.mark.hardware` marker. Run `pytest` to execute tests (excluding hardware tests by default with `-m "not hardware"`).
- Hardware dependencies are mocked in `tests/conftest.py` so tests run on any platform.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate

# Local development (no hardware packages):
pip install -e ".[dev]"

# On the Pi (with hardware packages):
pip install ".[hw]"
```

The project uses `pyproject.toml` exclusively for dependency management. Dependencies are split into core (paho-mqtt, pillow, PyYAML), `hw` (hardware-specific: luma.oled, gpiozero, alsaaudio, etc.), and `dev` (ruff, pytest).

Target platform: Raspberry Pi 4B running DietPi with HifiBerry DAC+ overlay, SPI enabled, and FKMS video driver.
