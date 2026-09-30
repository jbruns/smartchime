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
BOOT_DIR="/boot/firmware"
[ -d "$BOOT_DIR" ] || BOOT_DIR="/boot"
CONFIG_TXT="$BOOT_DIR/config.txt"
CMDLINE_TXT="$BOOT_DIR/cmdline.txt"
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

# Merges with the stock libinput touchscreen catchall; no need to copy it.
cat > "$XORG_CONF_DIR/99-smartchime-touch.conf" << 'TOUCH_CONF'
Section "InputClass"
        Identifier "Smartchime touch rotation"
        MatchIsTouchscreen "on"
        Option "CalibrationMatrix" "0 1 0 -1 0 1 0 0 1"
EndSection
TOUCH_CONF
echo "Touch rotation config written to $XORG_CONF_DIR/99-smartchime-touch.conf."

# ---------- Display: hide mouse cursor ----------
# The Panel is touch-only and always on; startx prefers ~/.xserverrc over the
# system xserverrc, so this only affects the dietpi kiosk session.
echo ""
echo "--- Hiding X11 mouse cursor ---"
cat > /home/dietpi/.xserverrc << 'XSERVERRC'
#!/bin/sh
exec /usr/bin/X -nocursor -nolisten tcp "$@"
XSERVERRC
chown dietpi:dietpi /home/dietpi/.xserverrc
chmod 755 /home/dietpi/.xserverrc
echo "Cursor disabled via /home/dietpi/.xserverrc."

# ---------- Display: never blank (Home Assistant owns Panel sleep) ----------
# Sleep is Home Assistant's pure-black Panel Mode (docs/adr/0001), so X must
# never blank or power down the screen itself.
echo ""
echo "--- Disabling X11 DPMS and screen blanking ---"
cat > "$XORG_CONF_DIR/98-smartchime-no-blanking.conf" << 'NO_BLANK_CONF'
# Smartchime: Home Assistant owns Panel sleep; X never blanks the display.
Section "Extensions"
        Option "DPMS" "Disable"
EndSection

Section "ServerFlags"
        Option "BlankTime" "0"
        Option "StandbyTime" "0"
        Option "SuspendTime" "0"
        Option "OffTime" "0"
EndSection
NO_BLANK_CONF
echo "No-blanking config written to $XORG_CONF_DIR/98-smartchime-no-blanking.conf."

# ---------- Hardware: KMS overlay ----------
# Full KMS with 256MB CMA; noaudio keeps VC4 HDMI audio from competing with
# the HifiBerry.
echo ""
echo "--- Configuring display driver (KMS) ---"
/boot/dietpi/func/dietpi-set_hardware rpi-opengl vc4-kms-v3d 256
if ! grep -Eq '^[[:blank:]]*dtoverlay=vc4-kms-v3d(,.*)?,noaudio(,|$)' "$CONFIG_TXT"; then
    sed --follow-symlinks -Ei '/^[[:blank:]]*dtoverlay=vc4-kms-v3d(,|$)/s/$/,noaudio/' "$CONFIG_TXT"
fi
grep -E '^[[:blank:]]*dtoverlay=vc4-kms-v3d' "$CONFIG_TXT"

# ---------- Hardware: HDMI display ----------
# The Waveshare 5.5" AMOLED's EDID advertises the correct native mode
# (1080x1920@60, 137.52MHz), and KMS ignores legacy hdmi_* timings. But the
# firmware would otherwise pass the kernel a bogus 1280x720@100 mode with
# overscan margins (from the EDID's CEA block), so stop it from doing that.
echo ""
echo "--- Configuring HDMI display (Waveshare 5.5\" AMOLED) ---"
if ! grep -q "^disable_fw_kms_setup=1" "$CONFIG_TXT"; then
    printf '\n# Smartchime: let KMS take the AMOLED mode from its EDID\ndisable_fw_kms_setup=1\n' >> "$CONFIG_TXT"
    echo "disable_fw_kms_setup=1 added to config.txt."
else
    echo "disable_fw_kms_setup already set."
fi
# Rotate the boot console to match the X11 rotation.
if ! grep -q "video=HDMI-A-1:" "$CMDLINE_TXT"; then
    sed --follow-symlinks -i '1s/$/ video=HDMI-A-1:1080x1920@60,rotate=270/' "$CMDLINE_TXT"
    echo "Console rotation added to cmdline.txt."
else
    echo "HDMI-A-1 video= already present in cmdline.txt."
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

# ---------- Configuration file ----------
echo ""
echo "--- Setting up configuration ---"
if [ ! -f "$INSTALL_DIR/config.yaml" ]; then
    sudo -u dietpi cp "$INSTALL_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
    echo "config.yaml created from example. Edit this file with your settings."
else
    echo "config.yaml already exists."
fi

# ---------- Deploy + converge ----------
# smartchime-update installs uv, checks out the latest release, syncs the venv, holds the
# kernel/firmware packages, sets the dietpi.txt update policy and installs smartchime.service
# (left disabled until you enable it). Run it again later to update.
echo ""
echo "--- Running smartchime-update ---"
"$INSTALL_DIR/scripts/smartchime-update"

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
echo " 2. After reboot, verify the display output. Chromium kiosk"
echo "    should fill the AMOLED in landscape with no cursor. Check the"
echo "    active mode with:"
echo "      DISPLAY=:0 xrandr --verbose"
echo ""
echo " 3. Edit config.yaml with your MQTT broker, audio settings, etc.:"
echo "      nano $INSTALL_DIR/config.yaml"
echo ""
echo " 4. Enable and start the service:"
echo "      sudo systemctl enable --now smartchime.service"
echo ""
echo " 5. Update to the latest release (rolls back if it fails):"
echo "      sudo smartchime-update"
echo ""
echo "=========================================="
