"""Tests for Alembic multi-directory migration discovery.

The _discover_migration_paths() function lives in alembic/env.py which can't
be imported as a normal module. We replicate the function logic here to test
the algorithm independently.
"""

from __future__ import annotations

import logging
import pathlib
import re
from importlib.metadata import entry_points as iter_entry_points
from unittest.mock import MagicMock, patch

import pytest


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
    with patch("tests.test_migration_discovery.iter_entry_points", return_value=[]):
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


# ---------------------------------------------------------------------------
# GAP-013: the REAL _discover_migration_paths from alembic/env.py must
# distinguish "overlay not installed" (silent — normal OSS) from "overlay
# installed but broken" (loud — log error). We load the actual function from
# env.py source so this test can't drift from the replica above.
# ---------------------------------------------------------------------------

import ast  # noqa: E402

# Repo root: backend/tests/test_migration_discovery.py -> parents[2].
_ENV_PY = pathlib.Path(__file__).resolve().parents[2] / "backend" / "alembic" / "env.py"


def _load_real_discover_fn():
    """Compile the real _discover_migration_paths() from alembic/env.py.

    env.py runs migrations at import time, so it cannot be imported directly.
    We parse the source, extract only the _discover_migration_paths function
    definition, and exec it in an isolated namespace with the same imports it
    relies on. This exercises the SHIPPING code, not a copy.
    """
    src = _ENV_PY.read_text()
    module = ast.parse(src)
    fn_node = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_discover_migration_paths"
    )
    fn_src = ast.get_source_segment(src, fn_node)

    ns: dict = {
        "pathlib": pathlib,
        "logging": logging,
        "_log": logging.getLogger("alembic.env"),
        "iter_entry_points": iter_entry_points,
    }
    exec(fn_src, ns)
    return ns["_discover_migration_paths"]


def test_real_discover_absent_overlay_is_silent(caplog):
    """OSS deployment: a missing overlay (ImportError) logs nothing at error.

    iter_entry_points returns the not-installed overlay whose load() raises
    ModuleNotFoundError. This is the normal OSS path — it must NOT log an
    error (only debug) and must return an empty path list.
    """
    real_fn = _load_real_discover_fn()

    absent_ep = MagicMock()
    absent_ep.name = "enterprise"
    absent_ep.load.side_effect = ModuleNotFoundError(
        "No module named 'geolens_enterprise'"
    )

    # The compiled function closes over the `iter_entry_points` name in its
    # exec namespace; patch that name directly.
    real_fn.__globals__["iter_entry_points"] = lambda **kw: [absent_ep]
    with caplog.at_level(logging.ERROR, logger="alembic.env"):
        result = real_fn()

    assert result == []
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not error_records, (
        "An absent overlay (ModuleNotFoundError) must NOT log an error — "
        "that is the normal OSS deployment path."
    )


def test_real_discover_broken_overlay_logs_error(caplog):
    """Enterprise overlay present but broken must surface a loud error log.

    A non-import exception from ep.load() means the overlay IS installed but
    its migration-path provider is broken. GAP-013: this must be logged at
    ERROR with the entry point name, never silently dropped.
    """
    real_fn = _load_real_discover_fn()

    broken_ep = MagicMock()
    broken_ep.name = "enterprise"
    broken_ep.load.side_effect = RuntimeError("broken editable install")

    real_fn.__globals__["iter_entry_points"] = lambda **kw: [broken_ep]
    with caplog.at_level(logging.ERROR, logger="alembic.env"):
        result = real_fn()

    assert result == []
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, (
        "A broken (installed-but-failing) overlay must log an ERROR so the "
        "dropped e-chain is not a silent failure (GAP-013)."
    )
    joined = " ".join(r.getMessage() for r in error_records)
    assert "enterprise" in joined, (
        "The error log must name the failing entry point for breadcrumbs."
    )


# Repo root: backend/tests/test_migration_discovery.py -> parents[2] == repo root.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Files that invoke `alembic upgrade`. With the enterprise overlay installed the
# revision graph forks into two heads (core 0003 + enterprise e002), so a bare
# `alembic upgrade head` raises "Multiple head revisions are present" and the
# stack never boots. Every invocation must use `heads` (plural). See BUG-001.
_MIGRATION_INVOCATION_FILES = (
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "Makefile",
    "backend/scripts/api-entrypoint.sh",
)

# Matches `alembic upgrade head` NOT followed by `s` — i.e. the buggy singular.
_BARE_HEAD_RE = re.compile(r"alembic upgrade head(?!s)")


def test_migration_invocations_use_heads_plural():
    """Every `alembic upgrade` site uses `heads`, never bare `head` (BUG-001).

    Bare `head` is ambiguous once the enterprise overlay adds a second head and
    aborts the migrate one-shot, so api/worker never start. Robust in-container:
    skips files that aren't present rather than failing on the missing tree.
    """
    checked = []
    for rel in _MIGRATION_INVOCATION_FILES:
        path = _REPO_ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text()
        offenders = _BARE_HEAD_RE.findall(text)
        assert not offenders, (
            f"{rel} invokes `alembic upgrade head` (singular); use `heads` so the "
            f"enterprise two-head graph upgrades both branches (BUG-001)."
        )
        checked.append(rel)

    if not checked:
        pytest.skip("migration invocation files not present (e.g. in-container run)")
