# Smartchime v2.0.0

A sophisticated smart doorbell system for Raspberry Pi/DietPi that combines video streaming, motion detection, OLED display, and AirPlay functionality. The system provides real-time notifications, customizable sounds, and hardware controls through rotary encoders.

## Features

- **OLED Display**
  - Shows current time and motion detection status
  - Scrolling message support
  - Sound selection interface
  - AirPlay track information display

- **Video Capabilities**
  - HDMI output for camera feed
  - Motion detection support
  - Video streaming from doorbell camera
  - Configurable display toggling

- **Audio Features**
  - Customizable doorbell sounds (WAV format)
  - Hardware volume control via rotary encoder
  - AirPlay support through Shairport Sync
  - ALSA audio system integration

- **Hardware Controls**
  - Dual rotary encoders for volume and sound selection
  - Hardware mute functionality
  - Physical display toggle

- **Connectivity**
  - MQTT integration for events and messages
  - Support for external video streams
  - I2C communication for OLED display

## Requirements

### Hardware
- Raspberry Pi (any model) or DietPi compatible board
- SSD1305 OLED display (I2C interface)
- 2× Rotary encoders with push button
- HDMI display (optional)
- Speakers or audio output device

### System Dependencies
Before installing the Python packages, you'll need to install these system dependencies:

```bash
# For Raspberry Pi OS / DietPi
sudo apt-get update
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    i2c-tools \
    libasound2-dev \
    libsdl2-dev \
    vlc \
    shairport-sync \
    fonts-font-awesome  # Added for icon support
```

# Create Font Awesome symlink for the OLED display
sudo mkdir -p /usr/share/fonts/fontawesome
sudo ln -s /usr/share/fonts/truetype/font-awesome/fa-solid-900.ttf /usr/share/fonts/fontawesome/fa-solid-900.ttf
sudo fc-cache -f -v

### Enable I2C Interface
1. Run `sudo raspi-config`
2. Navigate to "Interfacing Options"
3. Enable I2C
4. Reboot your device

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd chimellm
```

2. Install Python dependencies:
```bash
pip3 install -r requirements.txt
```

3. Copy and modify the configuration file:
```bash
cp config.yaml.example config.yaml
nano config.yaml
```

4. Configure your settings in `config.yaml`:
   - Set MQTT broker details
   - Configure audio directory and default sound
   - Set video stream URL
   - Adjust display settings
   - Configure GPIO pins for rotary encoders

## Configuration

The `config.yaml` file contains all system settings:

- MQTT configuration
  - Broker address and credentials
  - Topic definitions for doorbell, motion, and messages

- Audio settings
  - Directory for WAV sound files
  - Default doorbell sound
  - ALSA mixer device and control

- Video settings
  - Default video stream URL
  - HDMI framebuffer device

- Display configuration
  - OLED I2C port and address
  - HDMI framebuffer settings

- GPIO pin assignments
  - Volume encoder pins (CLK, DT, SW)
  - Sound selection encoder pins

- Shairport Sync settings
  - Metadata pipe location
  - Track info display duration

## Running the System

1. Ensure all hardware is properly connected
2. Configure your settings in `config.yaml`
3. Start the system:
```bash
python3 main.py
```

For automatic startup, you can create a systemd service:

```bash
sudo nano /etc/systemd/system/smartchime.service
```

Add the following content:
```ini
[Unit]
Description=Smartchime Doorbell System
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/chimellm/main.py
WorkingDirectory=/path/to/chimellm
User=pi
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl enable smartchime
sudo systemctl start smartchime
```

## Troubleshooting

### Common Issues

1. **OLED Display Not Working**
   - Check I2C connection and address
   - Verify I2C is enabled: `sudo i2cdetect -y 1`
   - Check permissions on I2C device

2. **Audio Problems**
   - Verify ALSA mixer device exists: `aplay -l`
   - Check audio files are valid WAV format
   - Test audio output: `aplay /path/to/test.wav`

3. **MQTT Connection Issues**
   - Verify broker is running: `systemctl status mosquitto`
   - Check network connectivity
   - Verify credentials if authentication is enabled

### Logging

The system logs to standard output with timestamp and log level. To save logs to a file:
```bash
python3 main.py > doorbell.log 2>&1
```

## Versioning

Smartchime follows semantic versioning (MAJOR.MINOR.PATCH):
- MAJOR version for incompatible API changes
- MINOR version for backwards-compatible functionality additions
- PATCH version for backwards-compatible bug fixes

Current version: 2.0.0

## License

[Add your license information here]

## Contributing

[Add contribution guidelines here]

## Acknowledgments

- Shairport Sync for AirPlay support
- https://dietpi.com/docs/software/media/#shairport-sync
- https://github.com/DanielHartUK/Dot-Matrix-Typeface
- luma.oled for OLED display drivers
- RPi.GPIO for hardware interface
- All other open source contributors