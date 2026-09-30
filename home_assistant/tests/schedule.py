"""The Display Schedule: time-only helpers, created as a user would."""

from datetime import time

from homeassistant.core import HomeAssistant

from testing.helpers import Helpers

TIMES = {"morning": time(6), "day": time(8), "evening": time(20), "night": time(23)}


async def display_schedule(hass: HomeAssistant, helpers: Helpers) -> dict[str, str]:
    """Create the four Period helpers, set to 06:00, 08:00, 20:00 and 23:00."""
    entities = {}
    for period, start in TIMES.items():
        entity_id = await helpers.input_datetime(f"Smartchime {period}", has_date=False)
        await set_time(hass, entity_id, start)
        entities[period] = entity_id
    return entities


async def set_time(hass: HomeAssistant, entity_id: str, value: time) -> None:
    await hass.services.async_call(
        "input_datetime", "set_datetime", {"entity_id": entity_id, "time": value.isoformat()}, blocking=True
    )
    await hass.async_block_till_done()
