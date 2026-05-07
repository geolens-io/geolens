"""Static-analysis tests for Phase 271 / 0015 audit_logs.action + users.username trigram indexes."""

import importlib.util
import inspect
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0015_audit_username_trgm_indexes.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "migration_0015_audit_username_trgm_indexes",
    _MIGRATION_PATH,
)
assert _SPEC is not None
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)


def test_revision_id_matches_filename():
    assert migration.revision == "0015_audit_username_trgm_indexes"


def test_chains_off_0014_fk_covering_indexes():
    assert migration.down_revision == "0014_fk_covering_indexes"


def test_upgrade_creates_audit_logs_action_trgm():
    src = inspect.getsource(migration.upgrade)
    assert "ix_audit_logs_action_trgm" in src
    assert "catalog.audit_logs" in src
    assert "lower(" in src
    assert "catalog.immutable_unaccent(action)" in src
    assert "gin_trgm_ops" in src


def test_upgrade_creates_users_username_trgm():
    src = inspect.getsource(migration.upgrade)
    assert "ix_users_username_trgm" in src
    assert "catalog.users" in src
    assert "catalog.immutable_unaccent(username)" in src
    assert "gin_trgm_ops" in src


def test_upgrade_does_not_recreate_immutable_unaccent_function():
    """0010 already created catalog.immutable_unaccent — 0015 must not duplicate."""
    src = inspect.getsource(migration.upgrade)
    assert "CREATE OR REPLACE FUNCTION catalog.immutable_unaccent" not in src
    assert "CREATE FUNCTION catalog.immutable_unaccent" not in src


def test_downgrade_drops_both_indexes():
    src = inspect.getsource(migration.downgrade)
    assert "DROP INDEX IF EXISTS catalog.ix_users_username_trgm" in src
    assert "DROP INDEX IF EXISTS catalog.ix_audit_logs_action_trgm" in src
