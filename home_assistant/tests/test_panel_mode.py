"""Behaviour of the Panel Mode blueprint: the Panel's transition table (ADR 0001).

The Display Schedule is 06:00 Morning to 23:00 Night; tests start at noon in Idle.
"""

from datetime import datetime, time, timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from testing.automations import async_setup_automations, blueprint_automation
from testing.clock import Clock
from testing.helpers import Helpers
from tests.schedule import display_schedule

BLUEPRINT = "blueprints/automation/smartchime_panel_mode.yaml"
DOORBELL = "binary_sensor.example_doorbell"
PERSON = "binary_sensor.example_person"
HAZARD = "binary_sensor.example_hazard"
TOUCH = "binary_sensor.example_browser"
MODES = ["sleep", "idle", "visitor", "person", "hazard", "controls"]


class Panel:
    def __init__(self, hass: HomeAssistant, clock: Clock, mode: str, timer: str) -> None:
        self.hass, self.clock, self.mode_entity, self.timer = hass, clock, mode, timer

    @property
    def mode(self) -> str:
        return self.hass.states.get(self.mode_entity).state

    @property
    def timer_state(self) -> str:
        return self.hass.states.get(self.timer).state

    async def select(self, mode: str) -> None:
        """What a dashboard button does."""
        await self.hass.services.async_call(
            "input_select", "select_option", {"entity_id": self.mode_entity, "option": mode}, blocking=True
        )
        await self.hass.async_block_till_done()

    async def set(self, entity_id: str, state: str) -> None:
        self.hass.states.async_set(entity_id, state)
        await self.hass.async_block_till_done()

    async def pulse(self, entity_id: str) -> None:
        await self.set(entity_id, "on")
        await self.set(entity_id, "off")

    async def wait(self, **delta: float) -> None:
        await self.clock.advance(timedelta(**delta), step=timedelta(seconds=5))

    async def at(self, when: time) -> None:
        """Move forward to the next time of day given."""
        now = self.clock.now()
        target = datetime.combine(now.date(), when, tzinfo=now.tzinfo)
        if target <= now:
            target += timedelta(days=1)
        await self.clock.advance(target - now, step=timedelta(minutes=1))


@pytest.fixture
async def panel(hass: HomeAssistant, clock: Clock, helpers: Helpers) -> Panel:
    schedule = await display_schedule(hass, helpers)
    mode = await helpers.input_select("Smartchime Panel Mode", MODES, initial="sleep")
    timer = await helpers.timer("Smartchime Panel Timeout")
    await clock.move_to(datetime(2027, 6, 1, 12, 0, 0, tzinfo=dt_util.get_default_time_zone()))
    for entity_id in (DOORBELL, PERSON, HAZARD, TOUCH):
        hass.states.async_set(entity_id, "off")
    await async_setup_automations(
        hass,
        [
            blueprint_automation(
                BLUEPRINT,
                {
                    "panel_mode": mode,
                    "panel_timeout": timer,
                    "doorbell": DOORBELL,
                    "person": PERSON,
                    "hazard": HAZARD,
                    "touch": [TOUCH],
                    "morning": schedule["morning"],
                    "night": schedule["night"],
                },
            )
        ],
    )
    panel = Panel(hass, clock, mode, timer)
    await panel.select("idle")
    return panel


async def test_idle_sleeps_after_five_minutes(panel: Panel) -> None:
    assert panel.timer_state == "active"
    await panel.wait(minutes=4, seconds=50)
    assert panel.mode == "idle"
    await panel.wait(seconds=15)
    assert panel.mode == "sleep"
    assert panel.timer_state == "idle"


async def test_a_touch_wakes_the_panel_and_keeps_it_awake(panel: Panel) -> None:
    await panel.wait(minutes=6)
    assert panel.mode == "sleep"
    await panel.pulse(TOUCH)
    assert panel.mode == "idle"
    await panel.wait(minutes=4)
    await panel.pulse(TOUCH)
    await panel.wait(minutes=4)
    assert panel.mode == "idle"


async def test_a_doorbell_press_shows_visitor_then_resumes(panel: Panel) -> None:
    await panel.wait(minutes=6)
    await panel.pulse(DOORBELL)
    assert panel.mode == "visitor"
    await panel.wait(minutes=1, seconds=50)
    assert panel.mode == "visitor"
    await panel.wait(seconds=15)
    assert panel.mode == "idle"


async def test_a_second_press_restarts_visitor(panel: Panel) -> None:
    await panel.pulse(DOORBELL)
    await panel.wait(minutes=1, seconds=30)
    await panel.pulse(DOORBELL)
    await panel.wait(minutes=1, seconds=30)
    assert panel.mode == "visitor"


async def test_a_person_shows_person_and_lingers_after_they_go(panel: Panel) -> None:
    await panel.set(PERSON, "on")
    assert panel.mode == "person"
    await panel.wait(seconds=20)
    await panel.set(PERSON, "off")
    await panel.wait(seconds=10)
    assert panel.mode == "person"
    await panel.wait(seconds=10)
    assert panel.mode == "idle"


async def test_person_ends_even_if_the_person_stays(panel: Panel) -> None:
    await panel.set(PERSON, "on")
    await panel.wait(seconds=50)
    assert panel.mode == "idle"


async def test_a_person_does_not_interrupt_a_visitor(panel: Panel) -> None:
    await panel.pulse(DOORBELL)
    await panel.set(PERSON, "on")
    assert panel.mode == "visitor"


async def test_a_hazard_takes_over_until_it_clears(panel: Panel) -> None:
    await panel.pulse(DOORBELL)
    await panel.set(HAZARD, "on")
    assert panel.mode == "hazard"
    assert panel.timer_state == "idle"
    await panel.pulse(DOORBELL)
    await panel.wait(minutes=30)
    assert panel.mode == "hazard"
    await panel.set(HAZARD, "off")
    assert panel.mode == "idle"


async def test_a_hazard_present_when_its_sensor_returns_takes_over(panel: Panel) -> None:
    await panel.set(HAZARD, "unavailable")
    await panel.set(HAZARD, "on")
    assert panel.mode == "hazard"


async def test_acknowledging_a_hazard_holds_until_it_clears(panel: Panel) -> None:
    await panel.set(HAZARD, "on")
    await panel.select("idle")
    await panel.wait(minutes=10)
    assert panel.mode == "sleep"
    await panel.set(HAZARD, "off")
    assert panel.mode == "sleep"
    await panel.set(HAZARD, "on")
    assert panel.mode == "hazard"


async def test_controls_return_to_idle(panel: Panel) -> None:
    await panel.select("controls")
    await panel.wait(minutes=1, seconds=50)
    assert panel.mode == "controls"
    await panel.wait(seconds=15)
    assert panel.mode == "idle"


async def test_night_sleeps_an_idle_panel_and_morning_wakes_it(panel: Panel) -> None:
    await panel.at(time(22, 58))
    await panel.pulse(TOUCH)
    assert panel.mode == "idle"
    await panel.at(time(23, 0, 30))
    assert panel.mode == "sleep"
    await panel.at(time(6, 0, 30))
    assert panel.mode == "idle"


async def test_at_night_modes_resume_to_sleep(panel: Panel) -> None:
    await panel.at(time(1, 0))
    await panel.pulse(DOORBELL)
    assert panel.mode == "visitor"
    await panel.wait(minutes=2, seconds=10)
    assert panel.mode == "sleep"


async def test_a_touch_does_not_dismiss_a_hazard(panel: Panel) -> None:
    await panel.set(HAZARD, "on")
    await panel.pulse(TOUCH)
    assert panel.mode == "hazard"


async def test_touch_is_optional(hass: HomeAssistant, clock: Clock, helpers: Helpers) -> None:
    schedule = await display_schedule(hass, helpers)
    mode = await helpers.input_select("Panel Mode", MODES, initial="sleep")
    timer = await helpers.timer("Panel Timeout")
    await async_setup_automations(
        hass,
        [
            blueprint_automation(
                BLUEPRINT,
                {
                    "panel_mode": mode,
                    "panel_timeout": timer,
                    "doorbell": DOORBELL,
                    "person": PERSON,
                    "hazard": HAZARD,
                    "morning": schedule["morning"],
                    "night": schedule["night"],
                },
            )
        ],
    )
