"""Helpers for tests that need files from the repository root."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root(anchor: str | Path) -> Path:
    """Return the GeoLens repository root for host and container test layouts."""
    env_root = os.environ.get("GEOLENS_REPO_ROOT")
    if env_root:
        candidate = Path(env_root)
        if (candidate / "docker-compose.yml").exists():
            return candidate

    path = Path(anchor).resolve()
    for candidate in (path, *path.parents):
        if (candidate / "docker-compose.yml").exists() and (
            candidate / "backend"
        ).exists():
            return candidate

    raise AssertionError(f"Could not locate GeoLens repo root from {path}")
