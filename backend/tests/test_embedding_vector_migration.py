"""Round-trip tests for 0012_type_embedding_vector (#449 codex findings).

Tests
-----
A: with an empty table and EMBEDDING_DIMS=768, the migration types the column
   vector(768) and builds the HNSW index (codex P2: the empty-table fallback
   must honor the configured dimension, not a hardcoded 1536).
B: with EMBEDDING_DIMS=3072 (legal config, over pgvector's 2000-dim HNSW
   limit), the upgrade still exits 0, types the column vector(3072), and
   skips the index instead of failing (codex P1).

Notes
-----
- Shells out to ``alembic`` via subprocess (the real alembic.ini / env.py
  stack) with EMBEDDING_DIMS injected into the subprocess env; observes
  committed DDL through AUTOCOMMIT async queries.
- Each test truncates catalog.record_embeddings first (embeddings are a
  regenerable cache) to force the empty-table fallback, and restores the
  default vector(1536) + index state in a finally block.
- Run with:
    cd backend && set -a && source ../.env.test && set +a
    uv run pytest tests/test_embedding_vector_migration.py -x -q
"""

import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).parent.parent.resolve()
_ALEMBIC_INI = _BACKEND_DIR / "alembic.ini"

_PRE_TYPED_REVISION = "0011_allow_generic_geometry_type"


def _run_alembic(
    *args: str, extra_env: dict | None = None
) -> subprocess.CompletedProcess:
    """Run an alembic command via subprocess against the test DB.

    Uses the backend .venv python so the env matches what pytest runs with.
    PYTHONPATH is set so env.py can ``from app.core.config import settings``.
    """
    import os

    from app.core.config import settings

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    # Target the per-worker TEST DB (isolated + conftest-migrated to head) so the
    # destructive downgrade/upgrade roundtrips never mutate the SHARED main DB
    # (`postgres` on CI), which would corrupt sibling workers and the drift check.
    env["POSTGRES_DB"] = settings.postgres_db_test
    # The dims fallback under test reads these from the subprocess env; strip
    # any ambient values so each call sees exactly what the test injects.
    env.pop("EMBEDDING_DIMS", None)
    env.pop("ENV_ONLY_CONFIG", None)
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(_ALEMBIC_INI), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_BACKEND_DIR),
    )


async def _fresh_query(query: str):
    """Run a query on a fresh AUTOCOMMIT connection, bypassing the test
    transaction, so DDL committed by subprocess alembic is visible."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(
        settings.test_database_url,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa.text(query))
            return result.fetchall() if result.returns_rows else None
    finally:
        await engine.dispose()


async def _embedding_column_type() -> str:
    rows = await _fresh_query(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
        "WHERE attrelid = 'catalog.record_embeddings'::regclass "
        "AND attname = 'embedding'"
    )
    return rows[0][0]


async def _hnsw_index_exists() -> bool:
    rows = await _fresh_query(
        "SELECT 1 FROM pg_indexes WHERE schemaname = 'catalog' "
        "AND indexname = 'ix_record_embeddings_hnsw'"
    )
    return bool(rows)


def _enterprise_migrations_present() -> bool:
    """Multi-head under the enterprise overlay; see
    test_dormant_tenancy_migration_roundtrip.py for the full rationale."""
    import pathlib
    from importlib.metadata import entry_points

    for ep in entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
            if callable(fn) and any(pathlib.Path(p).is_dir() for p in fn()):
                return True
        except Exception:
            pass
    return False


_SKIP_UNDER_OVERLAY = pytest.mark.skipif(
    _enterprise_migrations_present(),
    reason="OSS migration test; multi-head under enterprise overlay — "
    "runs in the no-overlay Pytest Parallel Isolation job instead.",
)


async def _retype_via_migration(dims: str) -> subprocess.CompletedProcess:
    """Downgrade below 0012, empty the table, re-upgrade with EMBEDDING_DIMS set."""
    r = _run_alembic("downgrade", _PRE_TYPED_REVISION)
    assert r.returncode == 0, f"downgrade failed: {r.stderr}"
    await _fresh_query("TRUNCATE catalog.record_embeddings")
    await _fresh_query("DELETE FROM catalog.app_settings WHERE key = 'embedding_dims'")
    return _run_alembic("upgrade", "head", extra_env={"EMBEDDING_DIMS": dims})


async def _restore_default_head() -> None:
    """Back to the suite's expected state: head, vector(1536), index present."""
    r = _run_alembic("downgrade", _PRE_TYPED_REVISION)
    assert r.returncode == 0, f"restore downgrade failed: {r.stderr}"
    await _fresh_query("TRUNCATE catalog.record_embeddings")
    r = _run_alembic("upgrade", "head")
    assert r.returncode == 0, f"restore upgrade failed: {r.stderr}"
    assert await _embedding_column_type() == "vector(1536)"
    assert await _hnsw_index_exists()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@_SKIP_UNDER_OVERLAY
class TestEmbeddingVectorMigrationDims:
    async def test_env_dims_honored_on_empty_table(self):
        """fix(#449, codex P2): EMBEDDING_DIMS=768 types the column vector(768)."""
        try:
            r = await _retype_via_migration("768")
            assert r.returncode == 0, f"upgrade failed: {r.stderr}"
            assert await _embedding_column_type() == "vector(768)"
            assert await _hnsw_index_exists(), "HNSW should exist at 768 dims"
        finally:
            await _restore_default_head()

    async def test_large_dims_skip_hnsw_instead_of_failing(self):
        """fix(#449, codex P1): 3072 dims types the column but skips HNSW
        (pgvector rejects HNSW over 2000 dims) instead of failing the upgrade."""
        try:
            r = await _retype_via_migration("3072")
            assert r.returncode == 0, (
                f"upgrade must succeed at 3072 dims by skipping HNSW: {r.stderr}"
            )
            assert await _embedding_column_type() == "vector(3072)"
            assert not await _hnsw_index_exists(), (
                "HNSW must be skipped above pgvector's 2000-dim limit"
            )
        finally:
            await _restore_default_head()
