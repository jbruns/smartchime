"""Creating automations, from any context's blueprint or from plain config."""

from pathlib import Path
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.setup import async_setup_component

from testing.blueprints import HA_ROOT, OWNER, blueprint_files


def blueprint_automation(
    path: str | Path, inputs: dict[str, Any], *, alias: str = "Blueprint automation"
) -> dict[str, Any]:
    """An automation using the blueprint at a repo path such as
    blueprints/automation/smartchime_panel_mode.yaml."""
    blueprint = (HA_ROOT / path).resolve()
    if blueprint not in blueprint_files():
        raise ValueError(f"{path} is not a blueprint in this repo")
    return {
        "alias": alias,
        "use_blueprint": {"path": f"{OWNER}/{blueprint.name}", "input": inputs},
    }


async def async_setup_automations(hass: HomeAssistant, automations: list[dict[str, Any]]) -> None:
    """Create the automations and check every one loaded."""

    async def detach_triggers(_: Event) -> None:
        # Time and time pattern triggers otherwise leave timers behind the test.
        await hass.services.async_call("automation", "turn_off", {"entity_id": "all"}, blocking=True)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, detach_triggers)
    assert await async_setup_component(hass, "automation", {"automation": automations})
    await hass.async_block_till_done()
    states = hass.states.async_all("automation")
    assert len(states) == len(automations)
    # An automation whose blueprint fails to load is created unavailable.
    assert all(state.state == "on" for state in states), [(state.entity_id, state.state) for state in states]
