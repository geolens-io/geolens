"""Static-analysis tests for Phase 271 / DBM-08: 0001_baseline downgrade error."""

import importlib.util
from pathlib import Path

import pytest


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0001_baseline.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "migration_0001_baseline",
    _MIGRATION_PATH,
)
assert _SPEC is not None
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)


def test_downgrade_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        migration.downgrade()


def test_downgrade_message_references_squash_baseline_and_reset_path():
    try:
        migration.downgrade()
    except NotImplementedError as exc:
        msg = str(exc)
    else:
        pytest.fail("downgrade() should raise NotImplementedError")
    assert "0001_baseline" in msg
    assert "docker compose down" in msg
