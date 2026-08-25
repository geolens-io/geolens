"""Tests for Alembic multi-directory migration discovery.

The ``_discover_migration_paths()`` function lives in ``alembic/env.py``, which
runs migrations at import time and so cannot be imported as a normal module.
Every test here compiles the REAL function out of that source (see
``_load_real_discover_fn``) and drives it with fake entry points.

fix(#1665): there used to be a hand-written mirror of the function at the top of
this file that four tests exercised instead. One of them asserted that a failing
plugin is "swallowed ... without breaking discovery" — the behaviour that let a
broken overlay produce a partial schema under a zero exit code. It stayed green
across the fix because it pinned the copy, not the code. The mirror is gone;
there is now one subject.
"""

from __future__ import annotations

import ast
import logging
import pathlib
import re
from importlib.metadata import entry_points as iter_entry_points
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# GAP-013 / #1665: _discover_migration_paths must distinguish "overlay not
# installed" (silent, and the only class that continues — normal OSS) from
# "overlay installed but broken" (raise, so the migration stops rather than
# succeeding over an incomplete revision graph).
# ---------------------------------------------------------------------------

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


def _discover_with(*eps):
    """Run the real function against the given fake entry points."""
    real_fn = _load_real_discover_fn()
    # The compiled function closes over the `iter_entry_points` name in its
    # exec namespace; patch that name directly.
    real_fn.__globals__["iter_entry_points"] = lambda **kw: list(eps)
    return real_fn()


def _ep(name, *, provides=None, load_raises=None):
    ep = MagicMock()
    ep.name = name
    if load_raises is not None:
        ep.load.side_effect = load_raises
    else:
        ep.load.return_value = lambda: list(provides or [])
    return ep


def test_real_discover_no_entry_points():
    """No geolens.migrations entry points at all — the plain OSS install."""
    assert _discover_with() == []


def test_real_discover_collects_plugin_dirs(tmp_path):
    """A working overlay's version directory is collected."""
    versions_dir = tmp_path / "migrations" / "versions"
    versions_dir.mkdir(parents=True)

    assert _discover_with(_ep("enterprise", provides=[str(versions_dir)])) == [
        str(versions_dir)
    ]


def test_real_discover_skips_nonexistent_dir():
    """A provider naming a path that is not a directory contributes nothing.

    This is not a broken provider — it returned normally — so it must not raise.
    """
    assert _discover_with(_ep("enterprise", provides=["/nonexistent/versions"])) == []


def test_real_discover_broken_overlay_beside_a_working_one_raises(tmp_path):
    """A broken overlay raises even when another overlay discovered paths.

    fix(#1665): the GEOLENS_EDITION=enterprise guard further down env.py only
    fires when NO paths were discovered at all, so this mixed case slipped past
    it entirely — the migration ran with one overlay's chain silently absent.
    """
    versions_dir = tmp_path / "working" / "versions"
    versions_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="broken"):
        _discover_with(
            _ep("working", provides=[str(versions_dir)]),
            _ep("broken", load_raises=RuntimeError("bad editable install")),
        )


def test_real_discover_oss_install_is_silent(caplog):
    """OSS deployment: an empty entry-point group logs nothing at error.

    This is what "overlay not installed" actually looks like.
    ``entry_points()`` only enumerates what an installed distribution declared,
    so a Community install yields an empty group and the loop body never runs.
    Verified against a stock OSS container, which reports
    ``entry_points(group="geolens.migrations") == []``.
    """
    with caplog.at_level(logging.ERROR, logger="alembic.env"):
        assert _discover_with() == []

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "The normal OSS deployment path must not log an error."
    )


def test_real_discover_entry_point_that_cannot_import_raises():
    """An enumerated entry point whose module is missing is BROKEN, not absent.

    fix(#1665, codex P1): this used to be read as "the overlay package is simply
    not installed" and skipped silently. But the entry point's presence already
    proves a distribution declared it, so the module failing to import means the
    install is broken — and a ModuleNotFoundError raised from INSIDE the
    overlay's own module (a missing submodule or dependency) is indistinguishable
    from an absent one at this point. Skipping either produced the same
    incomplete revision graph under a zero exit code.
    """
    with pytest.raises(RuntimeError) as excinfo:
        _discover_with(
            _ep(
                "enterprise",
                load_raises=ModuleNotFoundError(
                    "No module named 'geolens_enterprise.migrations._missing'"
                ),
            )
        )

    assert "enterprise" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, ModuleNotFoundError)


def test_real_discover_broken_overlay_raises():
    """Enterprise overlay present but broken must stop the migration.

    A non-import exception from ep.load() means the overlay IS installed but
    fails to import. GAP-013 required this never be silently dropped; #1665
    requires it RAISE rather than log-and-continue, because continuing left the
    overlay's revisions out of version_locations and let `upgrade heads` exit 0
    on a partial schema.
    """
    real_fn = _load_real_discover_fn()

    broken_ep = MagicMock()
    broken_ep.name = "enterprise"
    broken_ep.load.side_effect = RuntimeError("broken editable install")

    real_fn.__globals__["iter_entry_points"] = lambda **kw: [broken_ep]
    with pytest.raises(RuntimeError) as excinfo:
        real_fn()

    assert "enterprise" in str(excinfo.value), (
        "The error must name the failing entry point for breadcrumbs."
    )
    assert isinstance(excinfo.value.__cause__, RuntimeError), (
        "The original failure must be chained as __cause__, not discarded."
    )


def test_real_discover_provider_import_error_raises():
    """Codex PR #250: ep.load() SUCCEEDS but the loaded provider raises ImportError
    when CALLED (e.g. a missing submodule imported inside the overlay's provider).

    The overlay IS installed (load() succeeded), so this is a BROKEN overlay and
    must RAISE — it must NOT be reclassified as 'overlay not installed', which
    is what happened when the import-error suppression also wrapped the provider
    call.
    """
    real_fn = _load_real_discover_fn()

    def _provider_raises_import_error():
        raise ImportError("No module named 'geolens_enterprise.migrations._missing'")

    installed_ep = MagicMock()
    installed_ep.name = "enterprise"
    installed_ep.load.return_value = _provider_raises_import_error

    real_fn.__globals__["iter_entry_points"] = lambda **kw: [installed_ep]
    with pytest.raises(RuntimeError) as excinfo:
        real_fn()

    assert "enterprise" in str(excinfo.value), (
        "A provider ImportError from an INSTALLED overlay must raise and name the "
        "entry point (broken), not be swallowed as 'overlay not installed' "
        "(GAP-013 / Codex PR #250 / #1665)."
    )
    assert isinstance(excinfo.value.__cause__, ImportError), (
        "The provider's own ImportError must be chained as __cause__."
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
