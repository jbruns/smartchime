"""Smartchime — a smart doorbell system for Raspberry Pi 4B."""

import importlib.metadata

try:
    # hatch-vcs sets the distribution version from the git tag at install time.
    __version__ = importlib.metadata.version("smartchime")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0+unknown"
