"""Tests for Alembic multi-directory migration discovery.

The _discover_migration_paths() function lives in alembic/env.py which can't
be imported as a normal module. We replicate the function logic here to test
the algorithm independently.
"""

from __future__ import annotations

import pathlib
from importlib.metadata import entry_points as iter_entry_points
from unittest.mock import MagicMock, patch


def _discover_migration_paths() -> list[str]:
    """Mirror of alembic/env.py _discover_migration_paths for testing."""
    paths = []
    for ep in iter_entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
            if callable(fn):
                for p in fn():
                    if pathlib.Path(p).is_dir():
                        paths.append(p)
        except Exception:
            pass
    return paths


def test_discover_migration_paths_empty():
    """Returns empty list when no geolens.migrations entry points exist."""
    with patch(
        "tests.test_migration_discovery.iter_entry_points", return_value=[]
    ):
        result = _discover_migration_paths()
    assert result == []


def test_discover_migration_paths_with_plugin(tmp_path):
    """Returns paths from a plugin that provides a valid directory."""
    versions_dir = tmp_path / "migrations" / "versions"
    versions_dir.mkdir(parents=True)

    mock_ep = MagicMock()
    mock_ep.name = "enterprise"
    mock_ep.load.return_value = lambda: [str(versions_dir)]

    with patch(
        "tests.test_migration_discovery.iter_entry_points",
        return_value=[mock_ep],
    ):
        result = _discover_migration_paths()

    assert len(result) == 1
    assert str(versions_dir) in result[0]


def test_discover_migration_paths_skips_nonexistent():
    """Skips paths that don't exist on disk."""
    mock_ep = MagicMock()
    mock_ep.name = "enterprise"
    mock_ep.load.return_value = lambda: ["/nonexistent/path/versions"]

    with patch(
        "tests.test_migration_discovery.iter_entry_points",
        return_value=[mock_ep],
    ):
        result = _discover_migration_paths()

    assert result == []


def test_discover_migration_paths_handles_failure():
    """Swallows exceptions from failing plugins without breaking discovery."""
    bad_ep = MagicMock()
    bad_ep.name = "broken"
    bad_ep.load.side_effect = Exception("plugin load error")

    with patch(
        "tests.test_migration_discovery.iter_entry_points",
        return_value=[bad_ep],
    ):
        result = _discover_migration_paths()

    assert result == []
