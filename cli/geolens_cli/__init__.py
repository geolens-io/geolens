"""GeoLens CLI.

Hand-maintained — NOT regenerated. Version is sourced from package metadata
so cli/pyproject.toml is the single source of truth for the version string.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("geolens")
except PackageNotFoundError:
    # Local dev tree before `pip install -e .` — fall back to a sentinel.
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
