"""Static-analysis tests for Phase 271 / 0013 partial indexes."""

import importlib.util
import inspect
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0013_partial_indexes_embed_tokens_ingest_jobs.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "migration_0013_partial_indexes",
    _MIGRATION_PATH,
)
assert _SPEC is not None
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)


def test_revision_id_matches_filename():
    assert migration.revision == "0013_partial_indexes_embed_tokens_ingest_jobs"


def test_chains_off_0012_tile_columns():
    assert migration.down_revision == "0012_dataset_tile_columns"


def test_upgrade_creates_embed_tokens_partial_index():
    src = inspect.getsource(migration.upgrade)
    assert "ix_embed_tokens_active_expires" in src
    assert "WHERE is_active = true" in src
    assert "catalog.embed_tokens" in src


def test_upgrade_creates_ingest_jobs_partial_index():
    src = inspect.getsource(migration.upgrade)
    assert "ix_ingest_jobs_status_active" in src
    assert "WHERE status IN" in src
    assert "running" in src
    assert "pending" in src
    assert "catalog.ingest_jobs" in src


def test_downgrade_drops_both_indexes():
    src = inspect.getsource(migration.downgrade)
    assert "DROP INDEX IF EXISTS catalog.ix_embed_tokens_active_expires" in src
    assert "DROP INDEX IF EXISTS catalog.ix_ingest_jobs_status_active" in src
