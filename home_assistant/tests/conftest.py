"""Runs the blueprints in a real Home Assistant core, reading back what they
publish to Smartchime. Every entity here is a placeholder."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from homeassistant.core import HomeAssistant

SCHEMAS = Path(__file__).resolve().parents[2] / "mqtt-schema"


def schema(name: str) -> dict[str, Any]:
    return json.loads((SCHEMAS / name).read_text())


@pytest.fixture
def expected_lingering_timers() -> bool:
    # The mocked MQTT client leaves its periodic housekeeping timer behind.
    return True


@dataclass
class Published:
    topic: str
    payload: dict[str, Any]
    qos: int
    retain: bool


@dataclass
class Broker:
    """What the blueprints publish, checked against the Smartchime contract."""

    hass: HomeAssistant
    mqtt_mock: Any
    contract: dict[str, Any] | None = None

    @property
    def messages(self) -> list[Published]:
        messages = []
        for call in self.mqtt_mock.async_publish.call_args_list:
            topic, payload, qos, retain = call.args
            message = Published(topic, json.loads(payload), qos, retain)
            if self.contract is not None:
                jsonschema.validate(message.payload, self.contract)
                for timestamp in _timestamps(message.payload):
                    assert datetime.fromisoformat(timestamp).tzinfo is not None, timestamp
            messages.append(message)
        return messages

    @property
    def last(self) -> Published:
        assert self.messages, "nothing was published"
        return self.messages[-1]

    def clear(self) -> None:
        self.mqtt_mock.async_publish.reset_mock()


def _timestamps(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        found = []
        for key, value in payload.items():
            if key in {"timestamp", "expires_at"} and isinstance(value, str):
                found.append(value)
            else:
                found += _timestamps(value)
        return found
    return []


@pytest.fixture
def broker(hass: HomeAssistant, mqtt_mock: Any) -> Broker:
    return Broker(hass, mqtt_mock)
