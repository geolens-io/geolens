"""Migration 0074 copies a point cloud's attempt from a well-formed pointer row without holding readers, and its downgrade drops the column."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query,
    run_alembic,
)

pytestmark = pytest.mark.skipif(
    enterprise_migrations_present(),
    reason="OSS migration round-trip runs in the no-overlay migration job",
)

_PREVIOUS = "0073_raster_crs_facts"
_TITLE_PREFIX = "migration-0074-"


async def _point_cloud(attempt: str, *, prefix_of: str | None = None) -> str:
    """A point cloud dataset whose pointer row names ``attempt``; returns the dataset id."""
    rows = await fresh_query(
        "INSERT INTO catalog.records (title, record_type, visibility, record_status) "
        "VALUES (:title, 'pointcloud_dataset', 'private', 'draft') RETURNING id",
        {"title": f"{_TITLE_PREFIX}{uuid.uuid4().hex[:8]}"},
    )
    rows = await fresh_query(
        "INSERT INTO catalog.datasets (record_id, table_name, source_format) "
        "VALUES (:record_id, :table_name, 'copc') RETURNING id",
        {"record_id": rows[0][0], "table_name": f"m0074_{uuid.uuid4().hex[:12]}"},
    )
    dataset_id = str(rows[0][0])
    await fresh_query(
        "INSERT INTO catalog.dataset_assets (dataset_id, key, href, size_bytes) "
        "VALUES (CAST(:dataset_id AS uuid), 'pointcloud', :href, 1)",
        {
            "dataset_id": dataset_id,
            "href": f"pointclouds/{prefix_of or dataset_id}/{attempt}/data.copc.laz",
        },
    )
    return dataset_id


async def _attempt_of(dataset_id: str) -> uuid.UUID | None:
    rows = await fresh_query(
        "SELECT pointcloud_attempt_id FROM catalog.datasets WHERE id = CAST(:id AS uuid)",
        {"id": dataset_id},
    )
    return rows[0][0]


async def _remove_rows_and_restore_head() -> None:
    await fresh_query(
        "DELETE FROM catalog.records WHERE title LIKE :p", {"p": f"{_TITLE_PREFIX}%"}
    )
    restored = run_alembic("upgrade", "heads")
    assert restored.returncode == 0, restored.stderr


async def test_the_upgrade_copies_the_attempt_only_from_a_well_formed_pointer() -> None:
    """A pointer naming one of the dataset's attempt objects fills the column; any other shape leaves it null."""
    attempt = uuid.uuid4()
    try:
        down = run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        well_formed = await _point_cloud(str(attempt))
        malformed = [
            await _point_cloud("a1"),
            await _point_cloud(str(uuid.uuid4()).upper()),
            await _point_cloud(str(uuid.uuid4()), prefix_of=str(uuid.uuid4())),
        ]

        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr

        assert await _attempt_of(well_formed) == attempt
        for dataset_id in malformed:
            assert await _attempt_of(dataset_id) is None
    finally:
        await _remove_rows_and_restore_head()


async def test_the_downgrade_drops_the_column_and_the_upgrade_refills_it() -> None:
    """0074 downgrades while a point cloud exists, and upgrading again restores its attempt."""
    attempt = uuid.uuid4()
    try:
        dataset_id = await _point_cloud(str(attempt))
        await fresh_query(
            "UPDATE catalog.datasets SET pointcloud_attempt_id = CAST(:attempt AS uuid) "
            "WHERE id = CAST(:id AS uuid)",
            {"attempt": str(attempt), "id": dataset_id},
        )

        down = run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        columns = await fresh_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'catalog' AND table_name = 'datasets' "
            "AND column_name = 'pointcloud_attempt_id'"
        )
        assert list(columns) == []

        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
        assert await _attempt_of(dataset_id) == attempt
    finally:
        await _remove_rows_and_restore_head()


async def test_a_retry_fills_only_the_attempts_still_empty() -> None:
    """After a backfill that failed past its ADD COLUMN, the upgrade runs again and keeps any attempt already written."""
    written, pointed = uuid.uuid4(), uuid.uuid4()
    empty_attempt = uuid.uuid4()
    try:
        down = run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        written_id = await _point_cloud(str(pointed))
        empty_id = await _point_cloud(str(empty_attempt))
        await fresh_query(
            "ALTER TABLE catalog.datasets ADD COLUMN pointcloud_attempt_id uuid"
        )
        await fresh_query(
            "UPDATE catalog.datasets SET pointcloud_attempt_id = CAST(:a AS uuid) "
            "WHERE id = CAST(:id AS uuid)",
            {"a": str(written), "id": written_id},
        )

        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr

        assert await _attempt_of(written_id) == written
        assert await _attempt_of(empty_id) == empty_attempt
    finally:
        await _remove_rows_and_restore_head()


# Holds the backfill's UPDATE on a row lock of the point cloud's record, which
# another connection holds. A lock on the dataset row itself would hold up the
# ADD COLUMN instead, whichever transaction the backfill ran in.
_HOLD_THE_BACKFILL = [
    """
    CREATE FUNCTION catalog.test_0074_hold_backfill() RETURNS trigger AS $$
    BEGIN
        PERFORM 1 FROM catalog.records WHERE id = NEW.record_id FOR UPDATE;
        RETURN NEW;
    END $$ LANGUAGE plpgsql
    """,
    "CREATE TRIGGER test_0074_hold_backfill BEFORE UPDATE ON catalog.datasets "
    "FOR EACH ROW EXECUTE FUNCTION catalog.test_0074_hold_backfill()",
]
_RELEASE_THE_BACKFILL = [
    "DROP TRIGGER IF EXISTS test_0074_hold_backfill ON catalog.datasets",
    "DROP FUNCTION IF EXISTS catalog.test_0074_hold_backfill()",
]


async def _record_of(dataset_id: str) -> uuid.UUID:
    [(record_id,)] = await fresh_query(
        "SELECT record_id FROM catalog.datasets WHERE id = CAST(:id AS uuid)",
        {"id": dataset_id},
    )
    return record_id


async def _backfill_is_waiting() -> bool:
    rows = await fresh_query(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
        "AND pid <> pg_backend_pid() AND wait_event_type = 'Lock' "
        "AND query LIKE '%UPDATE catalog.datasets AS d%'"
    )
    return rows[0][0] > 0


async def test_readers_never_wait_behind_the_backfill() -> None:
    """While the backfill waits on a row lock another connection holds, catalog.datasets stays readable."""
    engine = create_async_engine(settings.test_database_url)
    upgrade = None
    try:
        down = run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        dataset_id = await _point_cloud(str(uuid.uuid4()))
        record_id = await _record_of(dataset_id)
        for statement in _HOLD_THE_BACKFILL:
            await fresh_query(statement)

        async with engine.connect() as holder:
            await holder.begin()
            await holder.execute(
                text("SELECT 1 FROM catalog.records WHERE id = :id FOR UPDATE"),
                {"id": record_id},
            )
            upgrade = asyncio.create_task(
                asyncio.to_thread(run_alembic, "upgrade", "heads")
            )
            for _ in range(300):
                if await _backfill_is_waiting() or upgrade.done():
                    break
                await asyncio.sleep(0.1)
            assert await _backfill_is_waiting(), "precondition: the backfill waits"

            async with engine.connect() as reader:
                await reader.execute(text("SET lock_timeout = '1s'"))
                try:
                    await reader.execute(text("SELECT count(*) FROM catalog.datasets"))
                except DBAPIError as exc:
                    pytest.fail(f"a reader waited behind the backfill: {exc.orig}")
            await holder.rollback()

        up = await upgrade
        assert up.returncode == 0, up.stderr
        assert await _attempt_of(dataset_id) is not None
    finally:
        if upgrade is not None and not upgrade.done():
            await upgrade
        for statement in _RELEASE_THE_BACKFILL:
            await fresh_query(statement)
        await engine.dispose()
        await _remove_rows_and_restore_head()


async def test_a_held_row_lock_fails_the_backfill_fast_and_a_rerun_succeeds() -> None:
    """The backfill gives up on a row lock after its timeout, and the next upgrade fills the attempt."""
    attempt = uuid.uuid4()
    engine = create_async_engine(settings.test_database_url)
    upgrade = None
    try:
        down = run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        dataset_id = await _point_cloud(str(attempt))
        record_id = await _record_of(dataset_id)
        for statement in _HOLD_THE_BACKFILL:
            await fresh_query(statement)

        async with engine.connect() as holder:
            await holder.begin()
            await holder.execute(
                text("SELECT 1 FROM catalog.records WHERE id = :id FOR UPDATE"),
                {"id": record_id},
            )
            upgrade = asyncio.create_task(
                asyncio.to_thread(run_alembic, "upgrade", "heads")
            )
            finished, _ = await asyncio.wait({upgrade}, timeout=40)
            await holder.rollback()
        failed = await upgrade
        assert finished, "the backfill kept waiting on the held row lock"
        assert failed.returncode != 0
        assert "lock timeout" in failed.stderr

        for statement in _RELEASE_THE_BACKFILL:
            await fresh_query(statement)
        rerun = run_alembic("upgrade", "heads")
        assert rerun.returncode == 0, rerun.stderr
        assert await _attempt_of(dataset_id) == attempt
    finally:
        if upgrade is not None and not upgrade.done():
            await upgrade
        for statement in _RELEASE_THE_BACKFILL:
            await fresh_query(statement)
        await engine.dispose()
        await _remove_rows_and_restore_head()


def _upgrade_0074_in_one_session(connection) -> tuple[str, str]:
    """``lock_timeout`` before 0074's upgrade and after it, on the connection a run shares."""
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0074_pointcloud_attempt_id.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0074", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    context = MigrationContext.configure(connection)
    with context.begin_transaction():
        before = connection.execute(text("SHOW lock_timeout")).scalar_one()
        with Operations.context(context):
            migration.upgrade()
        return before, connection.execute(text("SHOW lock_timeout")).scalar_one()


async def test_the_backfill_timeout_ends_with_the_backfill() -> None:
    """A migration that runs after 0074 in the same run sees the lock timeout it started with."""
    engine = create_async_engine(settings.test_database_url)
    try:
        down = run_alembic("downgrade", _PREVIOUS)
        assert down.returncode == 0, down.stderr
        async with engine.connect() as connection:
            before, after = await connection.run_sync(_upgrade_0074_in_one_session)
        assert after == before
    finally:
        await engine.dispose()
        await _remove_rows_and_restore_head()
