"""Host Status discovery: the Smartchime device and its upkeep entities, in a real Home Assistant core.

The discovery and status payloads come from the Pi application's own module, so this checks what Smartchime publishes.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message
from smartchime.host_status import discovery_config, read_host_status

STATUS_TOPIC = "smartchime/host/status"


def dietpi_host(root: Path, *, update: str | None = None, apt_updates: int | None = None, reboot: bool = False) -> Path:
    (root / "boot/dietpi").mkdir(parents=True)
    (root / "boot/dietpi/.version").write_text(
        "G_DIETPI_VERSION_CORE=10\nG_DIETPI_VERSION_SUB=7\nG_DIETPI_VERSION_RC=2\n"
    )
    (root / "run/dietpi").mkdir(parents=True)
    if update:
        (root / "run/dietpi/.update_available").write_text(f"{update}\n")
    if apt_updates is not None:
        (root / "run/dietpi/.apt_updates").write_text(f"{apt_updates}\n")
    if reboot:
        (root / "run/reboot-required").touch()
    return root


async def publish(hass: HomeAssistant, topic: str, payload: dict[str, Any]) -> None:
    async_fire_mqtt_message(hass, topic, json.dumps(payload), retain=True)
    await hass.async_block_till_done()


@pytest.fixture
async def discovered(hass: HomeAssistant, mqtt_mock: Any) -> None:
    topic, payload = discovery_config(STATUS_TOPIC, smartchime_version="2.6.0")
    await publish(hass, topic, payload)


def entity(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, "mqtt", unique_id)
    assert entity_id, f"no {domain} with unique_id {unique_id}"
    return entity_id


async def test_smartchime_is_one_device_reporting_its_release(hass: HomeAssistant, discovered: None) -> None:
    device = dr.async_get(hass).async_get_device(identifiers={("mqtt", "smartchime")})
    assert device is not None
    assert (device.name, device.sw_version) == ("Smartchime", "2.6.0")
    entities = er.async_entries_for_device(er.async_get(hass), device.id)
    assert sorted(e.domain for e in entities) == ["binary_sensor", "sensor", "update"]


async def test_an_up_to_date_host(hass: HomeAssistant, discovered: None, tmp_path: Path) -> None:
    await publish(hass, STATUS_TOPIC, read_host_status(dietpi_host(tmp_path), smartchime_version="2.6.0"))

    dietpi = hass.states.get(entity(hass, "update", "smartchime_dietpi"))
    assert dietpi.state == "off"
    assert (dietpi.attributes["installed_version"], dietpi.attributes["latest_version"]) == ("10.7.2", "10.7.2")
    assert hass.states.get(entity(hass, "sensor", "smartchime_apt_updates")).state == "0"
    assert hass.states.get(entity(hass, "binary_sensor", "smartchime_reboot_required")).state == "off"


async def test_a_host_with_upkeep_waiting(hass: HomeAssistant, discovered: None, tmp_path: Path) -> None:
    host = dietpi_host(tmp_path, update="10.8.0", apt_updates=5, reboot=True)
    await publish(hass, STATUS_TOPIC, read_host_status(host, smartchime_version="2.6.0"))

    dietpi = hass.states.get(entity(hass, "update", "smartchime_dietpi"))
    assert dietpi.state == "on"
    assert (dietpi.attributes["installed_version"], dietpi.attributes["latest_version"]) == ("10.7.2", "10.8.0")
    assert hass.states.get(entity(hass, "sensor", "smartchime_apt_updates")).state == "5"
    assert hass.states.get(entity(hass, "binary_sensor", "smartchime_reboot_required")).state == "on"
