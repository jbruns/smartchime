"""Host Status: the chime's own upkeep, read from what DietPi already writes."""

import json
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest

from smartchime.host_status import read_host_status

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "mqtt-schema" / "host-status-contract.schema.json").read_text()
)


@pytest.fixture
def root(tmp_path):
    """A DietPi 10.7.2 host with the update checks enabled and nothing pending."""
    (tmp_path / "boot/dietpi").mkdir(parents=True)
    (tmp_path / "boot/dietpi/.version").write_text(
        "G_DIETPI_VERSION_CORE=10\nG_DIETPI_VERSION_SUB=7\nG_DIETPI_VERSION_RC=2\n"
        "G_GITBRANCH='master'\nG_GITOWNER='MichaIng'\n"
    )
    (tmp_path / "run/dietpi").mkdir(parents=True)
    return tmp_path


def read(root):
    status = read_host_status(root, smartchime_version="2.6.0")
    jsonschema.validate(status, CONTRACT)
    assert datetime.fromisoformat(status["timestamp"]).tzinfo is not None
    return status


def test_an_up_to_date_host_has_nothing_waiting(root):
    status = read(root)

    assert status["smartchime_version"] == "2.6.0"
    assert status["dietpi"] == {"installed": "10.7.2", "latest": "10.7.2"}
    assert status["apt_updates"] == 0
    assert status["reboot_required"] is False


def test_a_waiting_dietpi_update_is_the_latest_version(root):
    (root / "run/dietpi/.update_available").write_text("10.8.0\n")

    assert read(root)["dietpi"] == {"installed": "10.7.2", "latest": "10.8.0"}


def test_pending_apt_updates_are_counted(root):
    (root / "run/dietpi/.apt_updates").write_text("7\n")

    assert read(root)["apt_updates"] == 7


def test_a_reboot_is_required_while_the_flag_file_exists(root):
    (root / "run/reboot-required").write_text("*** System restart required ***\n")

    assert read(root)["reboot_required"] is True


def test_an_unreadable_dietpi_version_is_unknown(root):
    (root / "boot/dietpi/.version").unlink()

    assert read(root)["dietpi"] == {"installed": None, "latest": None}
