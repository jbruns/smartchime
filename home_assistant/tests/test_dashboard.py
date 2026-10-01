"""Structure of the Panel dashboard and theme: they follow the Panel Mode helper."""

import re
from pathlib import Path
from typing import Any

import yaml

HA_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = HA_ROOT / "dashboards" / "smartchime_panel.yaml"
THEME = HA_ROOT / "themes" / "smartchime_amoled.yaml"
PANEL_MODE = "input_select.smartchime_panel_mode"
MODES = {"sleep", "idle", "visitor", "person", "hazard", "controls"}
ALLOWED_CUSTOM_CARDS = {"custom:advanced-camera-card"}
ENTITY = re.compile(r"\b(?:input_select|binary_sensor|camera|lock|light|cover|weather|sensor)\.[a-z0-9_]+\b")


def cards(node: Any) -> list[dict[str, Any]]:
    """Every card in the dashboard, nested ones included."""
    found = []
    if isinstance(node, dict):
        if "type" in node and isinstance(node["type"], str):
            found.append(node)
        for value in node.values():
            found += cards(value)
    elif isinstance(node, list):
        for value in node:
            found += cards(value)
    return found


def dashboard() -> dict[str, Any]:
    return yaml.safe_load(DASHBOARD.read_text())


def modes_shown(condition: dict[str, Any]) -> set[str]:
    if condition.get("condition") == "or":
        return set().union(*(modes_shown(c) for c in condition["conditions"]))
    assert condition == {"condition": "state", "entity": PANEL_MODE, "state": condition["state"]}
    return {condition["state"]}


def test_every_awake_mode_has_exactly_one_card_and_sleep_shows_nothing() -> None:
    shown: list[str] = []
    for card in cards(dashboard()):
        if card["type"] == "conditional":
            for condition in card["conditions"]:
                shown += sorted(modes_shown(condition))
    assert sorted(shown) == sorted(MODES - {"sleep"})


def test_buttons_only_select_real_modes() -> None:
    for card in cards(dashboard()):
        for key in ("tap_action", "icon_tap_action"):
            action = card.get(key, {})
            if action.get("perform_action") == "input_select.select_option":
                assert action["target"]["entity_id"] == PANEL_MODE
                assert action["data"]["option"] in MODES


def test_every_mode_fills_exactly_one_screen() -> None:
    """Each mode's card is pinned to the viewport, so the Panel never scrolls."""
    for card in cards(dashboard()):
        if card["type"] == "conditional":
            style = re.sub(r"\s+", " ", card["card"]["card_mod"]["style"])
            host = re.search(r":host \{([^}]*)\}", style)
            assert host, style
            assert "height: 100vh !important" in host.group(1)
            assert "overflow: hidden !important" in host.group(1)


def test_no_button_cards() -> None:
    """A button card's icon grows with its width, which is what pushed the Panel off the screen."""
    assert not [card for card in cards(dashboard()) if card["type"] == "button"]


def test_only_the_named_custom_cards_are_used() -> None:
    custom = {card["type"] for card in cards(dashboard()) if card["type"].startswith("custom:")}
    assert custom <= ALLOWED_CUSTOM_CARDS


def test_every_entity_is_in_the_find_and_replace_table() -> None:
    text = DASHBOARD.read_text()
    header, _, body = text.partition("\ntitle:")
    used = set(ENTITY.findall(body)) - {"input_select.select_option"}
    assert used == set(ENTITY.findall(header))


def test_the_dashboard_uses_the_shipped_theme() -> None:
    theme = yaml.safe_load(THEME.read_text())
    assert [view["theme"] for view in dashboard()["views"]] == list(theme)
