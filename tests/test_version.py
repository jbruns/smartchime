"""The package version comes from the installed distribution, which hatch-vcs derives from the git tag."""

import importlib
import importlib.metadata


def test_version_is_the_installed_distribution_version(monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: {"smartchime": "9.8.7"}[name])

    assert importlib.import_module("smartchime").__version__ == "9.8.7"


def test_version_is_unknown_when_not_installed(monkeypatch):
    def not_installed(name):
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", not_installed)

    assert importlib.import_module("smartchime").__version__ == "0+unknown"
