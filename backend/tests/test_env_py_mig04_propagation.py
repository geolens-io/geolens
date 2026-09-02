"""fix(#1778): MIG-04 propagation must refuse, not just log, on failure.

``_propagate_extra_paths_to_live_script()`` in alembic/env.py pushes the
discovered enterprise (overlay) migration version directories onto the LIVE
``ScriptDirectory`` an already-running ``alembic upgrade heads`` built before
this env.py ran. Before this fix, a failure here was caught and logged at
ERROR, and execution fell through to ``run_migrations_online()`` and exited
0 — the exact anti-pattern the file's own GAP-013 docstring says it was
rewritten to prevent ("An ERROR log is not enough when the process goes on
to claim success"). This function only ever runs when the caller has already
confirmed an overlay is installed (``extra_paths`` is non-empty), so failing
closed cannot affect a Community install.

These tests run the REAL function — extracted from alembic/env.py at test
time so the harness cannot drift — against fake ScriptDirectory-shaped
objects.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# Repo root: backend/tests/test_env_py_mig04_propagation.py -> parents[2].
_ENV_PY = pathlib.Path(__file__).resolve().parents[2] / "backend" / "alembic" / "env.py"


def _load_real_propagate_fn():
    """Compile the real _propagate_extra_paths_to_live_script() from env.py.

    env.py runs migrations at import time, so it cannot be imported directly
    (same constraint test_migration_discovery.py's _load_real_discover_fn
    documents for _discover_migration_paths). Parse the source, extract only
    this function definition, and exec it in an isolated namespace with the
    one module-level name it closes over (`pathlib`).
    """
    src = _ENV_PY.read_text()
    module = ast.parse(src)
    fn_node = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_propagate_extra_paths_to_live_script"
    )
    fn_src = ast.get_source_segment(src, fn_node)

    ns: dict = {"pathlib": pathlib}
    exec(fn_src, ns)
    return ns["_propagate_extra_paths_to_live_script"]


class _WorkingScript:
    """A ScriptDirectory stand-in whose version_locations assignment and
    revision-map rebuild both succeed normally."""

    def __init__(self):
        self.dir = "/repo/backend/alembic"
        self.version_locations = ["/repo/backend/alembic/versions"]
        self._load_revisions = lambda: []


class _ScriptThatRaisesOnAssignment:
    """A ScriptDirectory stand-in whose version_locations SETTER raises —
    the shape the fix's own recommendation calls out: "patch
    `_live_script.version_locations` to a property that raises"."""

    dir = "/repo/backend/alembic"
    _load_revisions = staticmethod(lambda: [])

    def __init__(self):
        self._version_locations = []

    @property
    def version_locations(self):
        return self._version_locations

    @version_locations.setter
    def version_locations(self, value):
        raise OSError("simulated: live ScriptDirectory rejected the update")


def test_propagation_success_extends_version_locations():
    propagate = _load_real_propagate_fn()
    script = _WorkingScript()

    propagate(script, ["/repo/enterprise/alembic_e/versions"])

    assert script.version_locations == [
        "/repo/backend/alembic/versions",
        "/repo/enterprise/alembic_e/versions",
    ]
    # RevisionMap was rebuilt (not left as the stale pre-propagation object).
    assert script.revision_map is not None


def test_propagation_failure_raises_instead_of_logging_and_continuing():
    """Before the fix this branch logged at ERROR and returned normally —
    the caller then fell through to run_migrations_online() and exited 0.
    The counterfactual: on that code, this call would return None here
    rather than raise."""
    propagate = _load_real_propagate_fn()
    script = _ScriptThatRaisesOnAssignment()

    with pytest.raises(RuntimeError, match="MIG-04") as excinfo:
        propagate(script, ["/repo/enterprise/alembic_e/versions"])

    # The real failure is chained, not swallowed.
    assert isinstance(excinfo.value.__cause__, OSError)
    assert "simulated" in str(excinfo.value.__cause__)
