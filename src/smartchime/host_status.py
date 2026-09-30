"""Host Status: the chime's own upkeep, read from what DietPi already writes.

Smartchime never runs apt itself; it relies on DietPi's update checks being enabled (the deploy script does).
"""

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

VERSION_FILE = "boot/dietpi/.version"
UPDATE_AVAILABLE_FILE = "run/dietpi/.update_available"
APT_UPDATES_FILE = "run/dietpi/.apt_updates"
REBOOT_REQUIRED_FILE = "run/reboot-required"

DEFAULT_STATUS_TOPIC = "smartchime/host/status"
DEFAULT_DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "smartchime"
REPOSITORY_URL = "https://github.com/jbruns/smartchime"


def discovery_config(
    status_topic: str, smartchime_version: str, discovery_prefix: str = DEFAULT_DISCOVERY_PREFIX
) -> tuple[str, dict]:
    """Home Assistant device discovery for the Smartchime device and its Host Status entities.

    Returns the discovery topic and payload; publish it retained.
    """
    return f"{discovery_prefix}/device/{DEVICE_ID}/config", {
        "device": {
            "identifiers": [DEVICE_ID],
            "name": "Smartchime",
            "manufacturer": "Smartchime",
            "model": "Raspberry Pi 4B",
            "sw_version": smartchime_version,
        },
        "origin": {"name": "smartchime", "sw_version": smartchime_version, "support_url": REPOSITORY_URL},
        "state_topic": status_topic,
        "components": {
            "dietpi": {
                "platform": "update",
                "unique_id": f"{DEVICE_ID}_dietpi",
                "name": "DietPi",
                "title": "DietPi",
                "device_class": "firmware",
                "entity_category": "diagnostic",
                "value_template": "{{ value_json.dietpi.installed }}",
                "latest_version_topic": status_topic,
                "latest_version_template": "{{ value_json.dietpi.latest }}",
                "release_url": "https://dietpi.com/docs/releases/",
            },
            "apt_updates": {
                "platform": "sensor",
                "unique_id": f"{DEVICE_ID}_apt_updates",
                "name": "APT updates",
                "icon": "mdi:package-up",
                "state_class": "measurement",
                "entity_category": "diagnostic",
                "value_template": "{{ value_json.apt_updates }}",
            },
            "reboot_required": {
                "platform": "binary_sensor",
                "unique_id": f"{DEVICE_ID}_reboot_required",
                "name": "Reboot required",
                "device_class": "problem",
                "entity_category": "diagnostic",
                "value_template": "{{ 'ON' if value_json.reboot_required else 'OFF' }}",
            },
        },
    }


def read_host_status(root: Path, smartchime_version: str) -> dict:
    """Read the Host Status snapshot from a filesystem rooted at root."""
    root = Path(root)
    installed = _installed_dietpi_version(root / VERSION_FILE)
    return {
        "smartchime_version": smartchime_version,
        # DietPi deletes .update_available once it is up to date.
        "dietpi": {"installed": installed, "latest": _first_line(root / UPDATE_AVAILABLE_FILE) or installed},
        "apt_updates": _apt_updates(root / APT_UPDATES_FILE),
        "reboot_required": (root / REBOOT_REQUIRED_FILE).exists(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _first_line(path: Path) -> str | None:
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning(f"Cannot read {path}: {e}")
        return None
    return lines[0].strip() if lines and lines[0].strip() else None


def _apt_updates(path: Path) -> int:
    count = _first_line(path)
    if count is None:
        return 0
    try:
        return max(int(count), 0)
    except ValueError:
        logger.warning(f"Unrecognised APT update count in {path}: {count!r}")
        return 0


def _installed_dietpi_version(path: Path) -> str | None:
    try:
        text = path.read_text()
    except OSError as e:
        logger.warning(f"Cannot read DietPi version from {path}: {e}")
        return None
    parts = dict(re.findall(r"^G_DIETPI_VERSION_(CORE|SUB|RC)=(\d+)", text, re.MULTILINE))
    if len(parts) != 3:
        logger.warning(f"Unrecognised DietPi version file {path}")
        return None
    return f"{parts['CORE']}.{parts['SUB']}.{parts['RC']}"
