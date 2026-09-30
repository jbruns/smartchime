"""Behaviour of the OLED State blueprint: every snapshot must satisfy the v2 contract."""

from datetime import datetime, time, timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from testing.automations import async_setup_automations, blueprint_automation
from testing.clock import Clock
from testing.helpers import Helpers
from tests.conftest import Broker, schema
from tests.schedule import display_schedule, set_time

BLUEPRINT = "blueprints/automation/smartchime_oled_state.yaml"
DOORBELL = "binary_sensor.example_doorbell"
PERSON = "binary_sensor.example_person"
LOCK = "lock.example_front_door"
WEATHER = "weather.example"
TOPIC = "smartchime/display/oled"


class Oled:
    def __init__(self, hass: HomeAssistant, broker: Broker, clock: Clock, schedule: dict[str, str]) -> None:
        self.hass, self.broker, self.clock, self.schedule = hass, broker, clock, schedule

    async def set(self, entity_id: str, state: str, **attributes: Any) -> None:
        self.hass.states.async_set(entity_id, state, attributes)
        await self.hass.async_block_till_done()

    @property
    def state(self) -> dict[str, Any]:
        message = self.broker.last
        assert (message.topic, message.qos, message.retain) == (TOPIC, 1, True)
        return message.payload

    def item(self, key: str) -> str | None:
        return next((i["text"] for i in self.state["line2"]["items"] if i["key"] == key), None)


@pytest.fixture
async def oled(hass: HomeAssistant, broker: Broker, clock: Clock, helpers: Helpers) -> Oled:
    broker.contract = schema("oled-v2-message-contract.schema.json")
    schedule = await display_schedule(hass, helpers)
    await clock.move_to(datetime(2027, 6, 1, 12, 0, 1, tzinfo=dt_util.get_default_time_zone()))
    hass.states.async_set(DOORBELL, "off")
    hass.states.async_set(PERSON, "off")
    hass.states.async_set(LOCK, "locked", {"friendly_name": "Front Door"})
    hass.states.async_set(WEATHER, "partlycloudy", {"temperature": 71.6})
    await async_setup_automations(
        hass,
        [
            blueprint_automation(
                BLUEPRINT,
                {
                    "doorbell": DOORBELL,
                    "person": PERSON,
                    "lock": LOCK,
                    "weather": WEATHER,
                    **schedule,
                },
            )
        ],
    )
    oled = Oled(hass, broker, clock, schedule)
    await oled.set(LOCK, "locked", friendly_name="Front Door", refresh=1)
    return oled


async def test_a_daytime_snapshot_shows_the_lock_and_weather(oled: Oled) -> None:
    state = oled.state
    assert state["active"] is True
    assert state["contrast"] == 0.5
    assert state["line1"] == {"mode": "clock, motion", "motion": state["line1"]["motion"]}
    assert state["line1"]["motion"]["active"] is False
    assert oled.item("security") == "Front Door Locked"
    assert oled.item("weather") == "72° Partly cloudy"
    assert state["override"] == {"active": False, "text": "", "expires_at": None}


async def test_an_unlocked_door_is_shown(oled: Oled) -> None:
    await oled.set(LOCK, "unlocked", friendly_name="Front Door")
    assert oled.item("security") == "Front Door Unlocked!"


async def test_a_person_shows_as_motion_now(oled: Oled) -> None:
    await oled.set(PERSON, "on")
    motion = oled.state["line1"]["motion"]
    assert motion["active"] is True
    assert abs(datetime.fromisoformat(motion["timestamp"]) - oled.clock.now()) < timedelta(seconds=1)


async def test_a_doorbell_press_overrides_the_rotation_for_two_minutes(oled: Oled) -> None:
    await oled.set(DOORBELL, "on")
    override = oled.state["override"]
    assert override["active"] is True
    assert override["text"] == "Someone's at the door!"
    expires = datetime.fromisoformat(override["expires_at"])
    assert abs(expires - (oled.clock.now() + timedelta(minutes=2))) < timedelta(seconds=1)
    await oled.set(DOORBELL, "off")
    assert oled.state["override"]["active"] is False


async def test_unavailable_sources_leave_out_their_items(oled: Oled) -> None:
    await oled.set(LOCK, "unavailable")
    await oled.set(WEATHER, "unavailable")
    await oled.set(PERSON, "unavailable")
    assert oled.state["line2"]["items"] == []
    assert oled.state["line1"]["motion"] == {"active": False}


@pytest.mark.parametrize(
    ("at", "active", "contrast"),
    [
        (time(5, 59), False, 0),
        (time(6, 0), True, 0.15),
        (time(8, 0), True, 0.5),
        (time(20, 0), True, 0.2),
        (time(23, 0), False, 0),
        (time(2, 0), False, 0),
    ],
)
async def test_each_period_sets_the_contrast_and_night_turns_the_oled_off(
    oled: Oled, at: time, active: bool, contrast: float
) -> None:
    now = oled.clock.now()
    when = datetime.combine(now.date() + timedelta(days=1), at, tzinfo=now.tzinfo)
    oled.broker.clear()
    await oled.clock.advance(when - now, step=timedelta(minutes=5))
    assert (oled.state["active"], oled.state["contrast"]) == (active, contrast)


async def test_a_schedule_change_republishes(oled: Oled) -> None:
    await set_time(oled.hass, oled.schedule["day"], time(13))
    assert oled.state["contrast"] == 0.15
