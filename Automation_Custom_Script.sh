#!/bin/bash
# Smartchime Post-Boot Setup Script
# ==================================
# This script is executed automatically by DietPi after first-boot setup.
# Place this file on the SD card boot partition as Automation_Custom_Script.sh,
# alongside dietpi.txt.
#
# Log file: /var/tmp/dietpi/logs/dietpi-automation_custom_script.log
#
# For more information, see: https://github.com/jbruns/smartchime


set -euo pipefail

INSTALL_DIR="/home/dietpi/smartchime"
CONFIG_TXT="/boot/config.txt"
SHAIRPORT_CONF="/usr/local/etc/shairport-sync.conf"
XORG_CONF_DIR="/etc/X11/xorg.conf.d"

echo "=========================================="
echo " Smartchime Post-Boot Setup"
echo " Started at $(date)"
echo "=========================================="

# ---------- Hardware: SPI ----------
echo ""
echo "--- Enabling SPI ---"
/boot/dietpi/func/dietpi-set_hardware spi enable

# ---------- Display and touch rotation (X11) ----------
echo ""
echo "--- Configuring display and touch rotation for X11 ---"
mkdir -p "$XORG_CONF_DIR"
cat > "$XORG_CONF_DIR/99-rotate-display.conf" << 'ROTATE_CONF'
Section "Monitor"
        Identifier "Monitor0"
        Option "Rotate" "right"
EndSection

Section "Screen"
        Identifier "Screen0"
        Device "Card0"
        Monitor "Monitor0"
EndSection
ROTATE_CONF
echo "Display rotation config written to $XORG_CONF_DIR/99-rotate-display.conf."

LIBINPUT_CONF="$XORG_CONF_DIR/40-libinput.conf"
if [ ! -f "$LIBINPUT_CONF" ]; then
    cp /usr/share/X11/xorg.conf.d/40-libinput.conf "$XORG_CONF_DIR/"
    echo "Copied 40-libinput.conf to $XORG_CONF_DIR/."
fi
if ! grep -q "CalibrationMatrix" "$LIBINPUT_CONF"; then
    sed -i '/MatchIsTouchscreen/a\        Option "CalibrationMatrix" "0 1 0 -1 0 1 0 0 1"' "$LIBINPUT_CONF"
    echo "Touch rotation added to $LIBINPUT_CONF."
else
    echo "Touch rotation already configured in $LIBINPUT_CONF."
fi

# ---------- Hardware: KMS overlay ----------
echo ""
echo "--- Configuring display driver (KMS) ---"
/boot/dietpi/func/dietpi-set_hardware rpi-opengl vc4-kms-v3d

# ---------- Hardware: HDMI display ----------
echo ""
echo "--- Configuring HDMI display (Waveshare 5.5\" AMOLED) ---"
# Target: 1080x1920@60Hz, rotated 270 degrees.
# If these settings don't produce the correct output, use dietpi-config
# (Display Options) as a fallback.
if ! grep -q "^hdmi_cvt=" "$CONFIG_TXT"; then
    cat >> "$CONFIG_TXT" << 'HDMI_CONFIG'

# Smartchime: Waveshare 5.5" AMOLED display (1080x1920@60Hz)
max_framebuffer_height=1920
config_hdmi_boost=10
hdmi_group=2
hdmi_force_hotplug=1
hdmi_mode=87
hdmi_timings=1080 1 80 16 80 1920 1 4 10 16 0 0 0 60 0 146950000 3
HDMI_CONFIG
    echo "HDMI display settings added to config.txt."
else
    echo "HDMI display settings already present."
fi

# ---------- User groups ----------
echo ""
echo "--- Adding dietpi user to hardware groups ---"
usermod -aG video,render,audio,gpio,spi dietpi
echo "User 'dietpi' added to: video, render, audio, gpio, spi."

# ---------- Shairport-sync configuration ----------
echo ""
echo "--- Configuring shairport-sync ---"
if [ -f "$SHAIRPORT_CONF" ]; then
    cp "$SHAIRPORT_CONF" "${SHAIRPORT_CONF}.bak"
    echo "Original config backed up to ${SHAIRPORT_CONF}.bak"
fi
cat > "$SHAIRPORT_CONF" << 'SHAIRPORT_CONFIG'
// Shairport Sync Configuration
// Set by Smartchime setup. Original backed up to shairport-sync.conf.bak.

general = {
  name = "Smartchime";
};

alsa = {
  mixer_control_name = "Digital";
};

metadata = {
  enabled = "yes";
  include_cover_art = "no";
  pipe_name = "/tmp/shairport-sync-metadata";
};
SHAIRPORT_CONFIG
echo "Shairport-sync configured (mixer: Digital, metadata: enabled)."
systemctl restart shairport-sync 2>/dev/null || echo "Note: shairport-sync restart deferred until next boot."

# ---------- Clone repository ----------
echo ""
echo "--- Cloning Smartchime repository ---"
if [ ! -d "$INSTALL_DIR" ]; then
    sudo -u dietpi git clone https://github.com/jbruns/smartchime.git "$INSTALL_DIR"
    echo "Repository cloned to $INSTALL_DIR."
else
    echo "Repository already exists at $INSTALL_DIR."
fi

# ---------- Python venv + install ----------
echo ""
echo "--- Setting up Python virtual environment ---"
cd "$INSTALL_DIR"
sudo -u dietpi python3 -m venv .venv
echo "Installing smartchime with hardware dependencies..."
sudo -u dietpi .venv/bin/pip install --quiet ".[hw]"
echo "Python environment ready."

# ---------- Configuration file ----------
echo ""
echo "--- Setting up configuration ---"
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    sudo -u dietpi cp "$INSTALL_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
    echo "config.yaml created from example. Edit this file with your settings."
else
    echo "config.yaml already exists."
fi

# ---------- systemd service ----------
echo ""
echo "--- Creating systemd service (disabled) ---"
cat > /etc/systemd/system/smartchime.service << 'SYSTEMD_SERVICE'
[Unit]
Description=Smartchime
After=network.target

[Service]
Type=exec
WorkingDirectory=/home/dietpi/smartchime
ExecStart=/home/dietpi/smartchime/.venv/bin/python -m smartchime
Restart=always
User=dietpi
Group=dietpi

[Install]
WantedBy=multi-user.target
SYSTEMD_SERVICE
systemctl daemon-reload
echo "Service created at /etc/systemd/system/smartchime.service (not yet enabled)."

# ---------- Summary ----------
echo ""
echo "=========================================="
echo " Smartchime setup complete!"
echo "=========================================="
echo ""
echo " NEXT STEPS (after reboot):"
echo ""
echo " 1. Reboot to apply hardware changes (SPI, display driver):"
echo "      sudo reboot"
echo ""
echo " 2. After reboot, verify the display output."
echo "    Chromium kiosk will manage the display. If the resolution"
echo "    or rotation is wrong, fix it with:"
echo "      sudo dietpi-config  (Display Options)"
echo ""
echo " 3. Edit config.yaml with your MQTT broker, audio settings, etc.:"
echo "      nano $INSTALL_DIR/config.yaml"
echo ""
echo " 4. Enable and start the service:"
echo "      sudo systemctl enable --now smartchime.service"
echo ""
echo "=========================================="
