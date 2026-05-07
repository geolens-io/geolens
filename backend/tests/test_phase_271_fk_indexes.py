"""Static-analysis tests for Phase 271 / 0014 FK covering indexes."""

import importlib.util
import inspect
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0014_fk_covering_indexes.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "migration_0014_fk_covering_indexes",
    _MIGRATION_PATH,
)
assert _SPEC is not None
migration = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(migration)


def test_revision_id_matches_filename():
    assert migration.revision == "0014_fk_covering_indexes"


def test_chains_off_0013_partial_indexes():
    assert migration.down_revision == "0013_partial_indexes_embed_tokens_ingest_jobs"


def test_upgrade_creates_three_fk_indexes():
    src = inspect.getsource(migration.upgrade)
    # vrt_generations.vrt_dataset_id
    assert "ix_vrt_generations_vrt_dataset_id" in src
    assert "catalog.vrt_generations" in src
    assert "(vrt_dataset_id)" in src
    # refresh_tokens.user_id
    assert "ix_refresh_tokens_user_id" in src
    assert "catalog.refresh_tokens" in src
    assert "(user_id)" in src
    # dataset_versions.dataset_id
    assert "ix_dataset_versions_dataset_id" in src
    assert "catalog.dataset_versions" in src
    assert "(dataset_id)" in src


def test_downgrade_drops_all_three():
    src = inspect.getsource(migration.downgrade)
    assert "DROP INDEX IF EXISTS catalog.ix_vrt_generations_vrt_dataset_id" in src
    assert "DROP INDEX IF EXISTS catalog.ix_refresh_tokens_user_id" in src
    assert "DROP INDEX IF EXISTS catalog.ix_dataset_versions_dataset_id" in src
