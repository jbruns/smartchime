"""Sensors whose state and attributes a test sets directly.

A sensor given an integration is a real entity from a platform of that name,
so integration_entities() and the entity registry see it as that integration's.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from pytest_homeassistant_custom_component.common import MockEntityPlatform


class SettableEntity(Entity):
    _attr_should_poll = False

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        self._attr_unique_id = entity_id
        self._state: Any = None
        self._extra: dict[str, Any] = {}

    @property
    def state(self) -> Any:
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._extra

    def update(
        self,
        state: Any,
        device_class: str | None,
        unit: str | None,
        friendly_name: str | None,
        attributes: dict[str, Any],
    ) -> None:
        self._state = str(state)
        self._attr_device_class = device_class
        self._attr_unit_of_measurement = unit
        self._attr_name = friendly_name
        self._extra = attributes
        self.async_write_ha_state()


@dataclass
class Sensors:
    hass: HomeAssistant
    _entities: dict[str, SettableEntity] = field(default_factory=dict, init=False)

    async def set(
        self,
        entity_id: str,
        state: Any,
        *,
        device_class: str | None = None,
        unit: str | None = None,
        friendly_name: str | None = None,
        integration: str | None = None,
        **attributes: Any,
    ) -> None:
        """Set any entity's state, for example a sensor or binary_sensor."""
        entity = self._entities.get(entity_id)
        if entity is None and integration is not None:
            entity = await self._add(entity_id, integration)
        if entity is None:
            named = {
                "device_class": device_class,
                "unit_of_measurement": unit,
                "friendly_name": friendly_name,
            }
            self.hass.states.async_set(
                entity_id,
                str(state),
                {**{k: v for k, v in named.items() if v is not None}, **attributes},
            )
            return
        entity.update(state, device_class, unit, friendly_name, attributes)

    async def battery(self, entity_id: str, level: Any, *, integration: str, **attributes: Any) -> None:
        """A battery level sensor, in percent, from the named integration."""
        await self.set(
            entity_id,
            level,
            device_class="battery",
            unit="%",
            integration=integration,
            **attributes,
        )

    async def _add(self, entity_id: str, integration: str) -> SettableEntity:
        entity = SettableEntity(entity_id)
        platform = MockEntityPlatform(self.hass, domain=entity_id.split(".")[0], platform_name=integration)
        await platform.async_add_entities([entity])
        assert entity.entity_id == entity_id, (entity.entity_id, entity_id)
        self._entities[entity_id] = entity
        return entity


@pytest.fixture
def sensors(hass: HomeAssistant) -> Sensors:
    return Sensors(hass)
