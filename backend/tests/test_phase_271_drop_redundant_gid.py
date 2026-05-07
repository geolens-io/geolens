"""Static-analysis tests for Phase 271 / 0016 drop redundant idx_*_gid indexes + metadata.py source change."""

import importlib.util
import inspect
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0016_drop_redundant_data_gid_indexes.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "migration_0016_drop_redundant_data_gid_indexes",
    _MIGRATION_PATH,
)
assert _SPEC is not None
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)

_METADATA_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "processing"
    / "ingest"
    / "metadata.py"
)


def test_revision_id_matches_filename():
    assert migration.revision == "0016_drop_redundant_data_gid_indexes"


def test_chains_off_0015_audit_username_trgm():
    assert migration.down_revision == "0015_audit_username_trgm_indexes"


def test_upgrade_iterates_data_schema_for_idx_gid_indexes():
    src = inspect.getsource(migration.upgrade)
    assert "pg_indexes" in src
    assert "schemaname = 'data'" in src
    assert "idx_%_gid" in src or "idx\\_%\\_gid" in src
    assert "DROP INDEX IF EXISTS" in src


def test_downgrade_is_documented_noop():
    src = inspect.getsource(migration.downgrade)
    # Acceptable: pass + docstring/comment, OR explicit raise NotImplementedError
    assert "pass" in src or "NotImplementedError" in src
    # Must have rationale text mentioning the irreversibility
    assert (
        "no-op" in src.lower()
        or "cannot" in src.lower()
        or "irrecoverable" in src.lower()
        or "no longer" in src.lower()
    )


def test_metadata_py_no_longer_creates_idx_gid_index():
    """DBM-05 coupled change: removing the migration without removing the source recreates indexes on next ingest."""
    src = _METADATA_PATH.read_text()
    # The exact line `CREATE INDEX IF NOT EXISTS idx_{table_name}_gid` must be gone.
    assert "idx_{table_name}_gid" not in src, (
        "metadata.py still contains the line creating idx_{table_name}_gid — "
        "removing the migration without removing the source recreates the index "
        "on the next ingest. Plan 271-05 must remove both."
    )
