# OS updates: APT auto-applies, kernel/firmware are held

The chime is a doorbell, so it has to keep working. It also sits on the network, so it has to stay patched. We set DietPi to apply APT upgrades automatically (`CONFIG_CHECK_APT_UPDATES=2`) and only notify of DietPi updates (`CONFIG_CHECK_DIETPI_UPDATES=1`). Three packages are held with `apt-mark hold`, so the automatic upgrades skip them: `linux-image-rpi-v8`, `raspi-firmware` and `rpi-eeprom`. The whole stack depends on them: the HifiBerry overlay, the KMS mode taken from the AMOLED's EDID, and the Chromium kiosk. A kernel or firmware update can break any of these, which leaves a silent or blank doorbell. The failure only shows after a reboot, which is often unattended and happens long after the upgrade.

Held updates are applied on purpose with `sudo smartchime-update --os`: it unholds the three packages, upgrades them, holds them again and reports whether a reboot is required. It never reboots, so someone can reboot when they're around to check the chime and the Panel.

`smartchime-update` sets the holds and the two `dietpi.txt` values on every run, so every chime converges on this policy, including ones provisioned before it existed.

## Consequences

- The kernel and firmware stay behind until someone runs `--os`. Security fixes in them are delayed, and running `--os` now and then is part of looking after the chime.
- Everything else, including userland security fixes, applies unattended every day. A bad userland package could still break the chime without warning.
- DietPi's own updates are never applied automatically. They show up as a notification to act on.
