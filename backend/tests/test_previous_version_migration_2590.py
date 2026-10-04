"""Migration 0077's downgrade drops only the previous versions datasets recorded in their own schema."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.platform.jobs.heartbeat import previous_version_table
from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query,
    run_alembic,
)
from tests.factories import create_dataset, get_user_id

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        enterprise_migrations_present(),
        reason="OSS migration round-trip runs in the no-overlay migration job",
    ),
]

_OTHER_SCHEMA = f"archive_{uuid.uuid4().hex[:8]}"


async def _exists(schema: str, table: str) -> bool:
    rows = await fresh_query(
        "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = :table",
        {"schema": schema, "table": table},
    )
    return bool(rows)


async def test_the_downgrade_drops_only_recorded_previous_versions(
    test_db_session,
) -> None:
    """Recorded previous versions go, partitioned ones too; another schema's and another dataset's tables stay."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    datasets = []
    for _ in range(3):
        created = await create_dataset(
            session, created_by=admin_id, table_name=f"mig_{uuid.uuid4().hex[:10]}"
        )
        datasets.append((created.id, created.table_name))
    (kept_id, kept_table), (claimed_id, claimed_table), parted = datasets
    kept_previous = previous_version_table(kept_table, kept_id)
    parted_previous = previous_version_table(parted[1], parted[0])
    claimed_previous = previous_version_table(claimed_table, claimed_id)
    await create_dataset(session, created_by=admin_id, table_name=claimed_previous)
    await session.execute(
        text(
            "UPDATE catalog.datasets SET previous_version_number = 1 "
            "WHERE id IN (:kept, :claimed, :parted)"
        ),
        {"kept": kept_id, "claimed": claimed_id, "parted": parted[0]},
    )
    await session.execute(text(f'CREATE SCHEMA "{_OTHER_SCHEMA}"'))
    for schema, table in (
        ("data", kept_previous),
        (_OTHER_SCHEMA, kept_previous),
        ("data", claimed_previous),
    ):
        await session.execute(text(f'CREATE TABLE "{schema}"."{table}" (gid int)'))
    await session.execute(
        text(
            f'CREATE TABLE "data"."{parted_previous}" (gid int) PARTITION BY RANGE (gid)'
        )
    )
    await session.commit()

    try:
        down = run_alembic("downgrade", "0076_feature_create_keys")
        assert down.returncode == 0, down.stderr

        assert not await _exists("data", kept_previous)
        assert not await _exists("data", parted_previous)
        assert await _exists(_OTHER_SCHEMA, kept_previous)
        assert await _exists("data", claimed_previous)
    finally:
        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
        await session.rollback()
        await session.execute(text(f'DROP SCHEMA IF EXISTS "{_OTHER_SCHEMA}" CASCADE'))
        for table in (kept_previous, claimed_previous, parted_previous):
            await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
        await session.commit()


async def test_the_downgrade_refuses_while_restore_runs_exist(test_db_session) -> None:
    """With a restore run on record the downgrade stops before changing anything."""
    from app.platform.refresh.service import create_pending_run

    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    created = await create_dataset(session, created_by=admin_id)
    dataset_id = created.id
    run = await create_pending_run(
        session,
        dataset_id=dataset_id,
        origin_kind="restore",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=None,
        feature_count_before=None,
    )
    run_id = run.id
    await session.commit()
    try:
        down = run_alembic("downgrade", "0076_feature_create_keys", normalize=False)
        assert down.returncode != 0
        assert "origin_kind restore" in down.stderr
        definition = await fresh_query(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'chk_refresh_runs_origin_kind'"
        )
        assert "restore" in definition[0][0]
        assert await fresh_query(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'catalog' "
            "AND table_name = 'datasets' AND column_name = 'previous_version_number'"
        )
    finally:
        await session.rollback()
        await session.execute(
            text("DELETE FROM catalog.dataset_refresh_runs WHERE id = :id"),
            {"id": run_id},
        )
        await session.commit()
        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
