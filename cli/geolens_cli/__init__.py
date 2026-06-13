# SPDX-License-Identifier: Apache-2.0
"""GeoLens CLI.

Hand-maintained — NOT regenerated. Version is sourced from package metadata
so cli/pyproject.toml is the single source of truth for the version string.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    # BUG-031: report the CLI's OWN distribution (`geolens-cli`), not the
    # `geolens` SDK dependency — the two version ranges may diverge at
    # install time (`pip install -U geolens` bumps only the SDK).
    __version__ = _pkg_version("geolens-cli")
except PackageNotFoundError:
    # Local dev tree before `pip install -e .` — fall back to a sentinel.
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
