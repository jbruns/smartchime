"""Behaviour of the Doorbell Event blueprint."""

import pytest
from homeassistant.core import HomeAssistant

from testing.automations import async_setup_automations, blueprint_automation
from tests.conftest import Broker, schema

BLUEPRINT = "blueprints/automation/smartchime_doorbell_event.yaml"
DOORBELL = "binary_sensor.example_doorbell"
TOPIC = "smartchime/events/doorbell"


@pytest.fixture
async def doorbell(hass: HomeAssistant, broker: Broker) -> Broker:
    broker.contract = schema("event-state-doorbell-contract.schema.json")
    hass.states.async_set(DOORBELL, "off")
    await async_setup_automations(hass, [blueprint_automation(BLUEPRINT, {"doorbell": DOORBELL})])
    return broker


async def press(hass: HomeAssistant, state: str) -> None:
    hass.states.async_set(DOORBELL, state)
    await hass.async_block_till_done()


async def test_a_press_sends_an_active_doorbell_event(hass: HomeAssistant, doorbell: Broker) -> None:
    await press(hass, "on")
    message = doorbell.last
    assert (message.topic, message.qos, message.retain) == (TOPIC, 1, False)
    assert message.payload["active"] is True


async def test_the_end_of_a_press_sends_an_inactive_doorbell_event(hass: HomeAssistant, doorbell: Broker) -> None:
    await press(hass, "on")
    await press(hass, "off")
    assert [m.payload["active"] for m in doorbell.messages] == [True, False]


async def test_returning_from_unavailable_does_not_chime(hass: HomeAssistant, doorbell: Broker) -> None:
    await press(hass, "unavailable")
    await press(hass, "on")
    await press(hass, "unavailable")
    await press(hass, "off")
    assert doorbell.messages == []


async def test_the_topic_is_an_input(hass: HomeAssistant, broker: Broker) -> None:
    hass.states.async_set(DOORBELL, "off")
    await async_setup_automations(
        hass, [blueprint_automation(BLUEPRINT, {"doorbell": DOORBELL, "topic": "chime/doorbell"})]
    )
    await press(hass, "on")
    assert broker.last.topic == "chime/doorbell"
