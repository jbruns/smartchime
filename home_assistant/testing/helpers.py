"""Helpers created by name through the same websocket commands the UI uses."""

from dataclasses import dataclass, field
from typing import Any

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.typing import WebSocketGenerator


@dataclass
class Helpers:
    hass: HomeAssistant
    ws_client: WebSocketGenerator
    _client: Any = field(default=None, init=False)

    async def input_boolean(self, name: str, *, initial: bool = False) -> str:
        return await self._create("input_boolean", name, initial=initial)

    async def input_select(self, name: str, options: list[str], *, initial: str | None = None) -> str:
        extra = {} if initial is None else {"initial": initial}
        return await self._create("input_select", name, options=options, **extra)

    async def input_datetime(self, name: str, *, has_date: bool = True, has_time: bool = True) -> str:
        return await self._create("input_datetime", name, has_date=has_date, has_time=has_time)

    async def input_text(self, name: str, *, initial: str = "") -> str:
        return await self._create("input_text", name, initial=initial)

    async def timer(self, name: str) -> str:
        entity_id = await self._create("timer", name)

        async def cancel(_: Event) -> None:
            # A running timer otherwise leaves its timer behind the test.
            await self.hass.services.async_call("timer", "cancel", {"entity_id": entity_id}, blocking=True)

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cancel)
        return entity_id

    async def _create(self, domain: str, name: str, **fields: Any) -> str:
        """Create the helper and return its entity ID."""
        assert await async_setup_component(self.hass, domain, {})
        if self._client is None:
            self._client = await self.ws_client(self.hass)
        await self._client.send_json_auto_id({"type": f"{domain}/create", "name": name, **fields})
        response = await self._client.receive_json()
        assert response["success"], response
        await self.hass.async_block_till_done()
        entity_id = f"{domain}.{slugify(name)}"
        assert self.hass.states.get(entity_id) is not None, entity_id
        return entity_id


@pytest.fixture
def helpers(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> Helpers:
    return Helpers(hass, hass_ws_client)
