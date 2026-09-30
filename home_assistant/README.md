# Smartchime in Home Assistant

Everything Home Assistant needs to drive Smartchime: three automation blueprints, the Panel dashboard for the AMOLED screen, and its theme. The words used here (Doorbell Press, OLED State, Panel Mode, Hazard, Display Schedule…) are defined in [CONTEXT.md](../CONTEXT.md).

Smartchime is self-contained ([ADR 0002](../docs/adr/0002-smartchime-is-self-contained.md)): nothing else in Home Assistant should use its helpers, and it uses nothing but the sensors you choose for it.

| Blueprint | What it does | Import |
|-----------|--------------|--------|
| [Smartchime: Doorbell Event](blueprints/automation/smartchime_doorbell_event.yaml) | Sends a Doorbell Event when a Doorbell Press starts and ends; an active one plays the Chime. | [![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjbruns%2Fsmartchime%2Fblob%2Fmain%2Fhome_assistant%2Fblueprints%2Fautomation%2Fsmartchime_doorbell_event.yaml) |
| [Smartchime: OLED State](blueprints/automation/smartchime_oled_state.yaml) | Publishes the OLED State: the clock, a person at the door, the lock, the weather, and a message during a Doorbell Press. The Display Schedule sets its contrast and turns it off at Night. | [![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjbruns%2Fsmartchime%2Fblob%2Fmain%2Fhome_assistant%2Fblueprints%2Fautomation%2Fsmartchime_oled_state.yaml) |
| [Smartchime: Panel Mode](blueprints/automation/smartchime_panel_mode.yaml) | Chooses what the Panel shows, and when it sleeps ([ADR 0001](../docs/adr/0001-home-assistant-owns-panel-sleep.md)). | [![Import the blueprint](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Fjbruns%2Fsmartchime%2Fblob%2Fmain%2Fhome_assistant%2Fblueprints%2Fautomation%2Fsmartchime_panel_mode.yaml) |

## Before you start

- The [MQTT integration](https://www.home-assistant.io/integrations/mqtt/), connected to the broker Smartchime uses.
- For the Panel, from HACS: [Advanced Camera Card](https://github.com/dermotduffy/advanced-camera-card), [card-mod](https://github.com/thomasloven/lovelace-card-mod) and [browser_mod](https://github.com/thomasloven/hass-browser_mod).

## 1. Create the helpers

In **Settings → Devices & services → Helpers**:

| Helper | Type | Used by |
|--------|------|---------|
| Smartchime Morning, Day, Evening and Night | Date and/or time, **time only**: when each Period of the Display Schedule starts, such as 06:00, 08:00, 20:00 and 23:00 | OLED State (all four), Panel Mode (Morning and Night) |
| Smartchime Panel Mode | Dropdown with the options `sleep`, `idle`, `visitor`, `person`, `hazard`, `controls` | Panel Mode, the dashboard |
| Smartchime Panel Timeout | Timer | Panel Mode only |
| Smartchime Hazard | Group → Binary sensor, of your smoke, carbon monoxide and leak sensors | Panel Mode, the dashboard |
| Smartchime Open Doors | Group → Binary sensor, of your door and window contact sensors | the dashboard |

Change the Display Schedule whenever you like; both blueprints follow it.

## 2. Import the blueprints and create the automations

Use the import buttons above, then **Create automation** from each and choose your entities and helpers. Every input is described in the editor.

Leave Panel Mode's **Touch** input empty for now; its sensor only exists once the Panel's browser is registered, and you set it in step 4.

## 3. Add the theme

Copy [themes/smartchime_amoled.yaml](themes/smartchime_amoled.yaml) into your themes folder, with `themes: !include_dir_merge_named themes` under `frontend:` in `configuration.yaml`, then run **Reload themes**.

## 4. Create the dashboard

1. Copy [dashboards/smartchime_panel.yaml](dashboards/smartchime_panel.yaml) and replace each entity in the table at its top with your own.
2. **Settings → Dashboards → Add dashboard → New dashboard from scratch**, named Smartchime, not shown in the sidebar.
3. Open it, choose **Edit dashboard → ⋮ → Raw configuration editor**, and paste.
4. With the Panel running, register its browser in browser_mod (**Browser Mod** in the sidebar, then **Register**). For that browser, turn on **Kiosk mode** and **Hide header**, and set its default dashboard to the Smartchime dashboard.
5. Back in the Panel Mode automation, set **Touch** to the browser's activity binary sensor: `binary_sensor.<browser id>`, such as `binary_sensor.smartchime`, not one of the `binary_sensor.<browser id>_browser_*` sensors. Without it the Panel still wakes for the doorbell, a person, a Hazard and Morning, but not for a touch.

## Development

The blueprints are tested in a real Home Assistant core, pinned to the release running live. The OLED State and Doorbell Event tests check every payload against the schemas in [`mqtt-schema/`](../mqtt-schema/).

```bash
cd home_assistant
uv run pytest
uvx ruff check . && uvx ruff format --check .
```

The `testing/` harness is copied from [jbruns/ha-elevations](https://github.com/jbruns/ha-elevations) rather than shared (ADR 0002).
