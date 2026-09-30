# Smartchime is self-contained in Home Assistant

Smartchime owns every Home Assistant artifact it needs (its blueprints, helpers, groups and the Panel dashboard), and nothing outside Smartchime (other dashboards, automations or devices) may depend on them. In the other direction, Smartchime reaches household entities (cameras, locks, door and Hazard sensors, weather) only through blueprint inputs. This lets Smartchime be installed, replaced or removed as a unit. It is also why the Wallboard keeps its own Hazard and open-door groups instead of reusing Smartchime's, even though they currently hold the same sensors. Do not merge them.

Smartchime's blueprints follow the conventions of the household's `ha-elevations` repo: they never hard-code entities, because the repo is public (ha-elevations ADR 0004); they compute derived values themselves instead of depending on template sensors (ADR 0005); and each blueprint filename starts with `smartchime_`, because Home Assistant flattens imported blueprints into one folder per GitHub owner (ADR 0007).

## Consequences

- The Hazard and open-door sensor lists are kept in two places, Smartchime's groups and the Wallboard's. Both must be updated when a sensor is added.
- Smartchime copies ha-elevations' blueprint test helpers rather than importing them.
