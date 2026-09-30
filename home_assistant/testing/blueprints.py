"""Finds the blueprints and installs them in a test Home Assistant config the
way a URL import would. Adapted from jbruns/ha-elevations (ADR 0002)."""

import shutil
from pathlib import Path

import pytest

HA_ROOT = Path(__file__).resolve().parent.parent
# Home Assistant takes the owner folder from the import URL, not the repo path.
OWNER = "jbruns"


def blueprint_files(root: Path = HA_ROOT) -> list[Path]:
    """Every blueprint: blueprints/<domain>/<file>."""
    return sorted(path for path in (root / "blueprints").rglob("*") if path.suffix in {".yaml", ".yml"})


def blueprint_domain(path: Path) -> str:
    """The folder under blueprints/, such as automation or script."""
    return path.parts[path.parts.index("blueprints") + 1]


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Install every blueprint as blueprints/<domain>/<OWNER>/<filename>."""
    for blueprint in blueprint_files():
        target = Path(hass_tmp_config_dir) / "blueprints" / blueprint_domain(blueprint) / OWNER
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(blueprint, target / blueprint.name)
    return hass_tmp_config_dir
