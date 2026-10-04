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


async def test_the_downgrade_spares_other_schemas_and_claimed_tables(
    test_db_session,
) -> None:
    """A same-named table in another schema and a table another dataset uses survive the downgrade."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    datasets = []
    for _ in range(2):
        created = await create_dataset(
            session, created_by=admin_id, table_name=f"mig_{uuid.uuid4().hex[:10]}"
        )
        datasets.append((created.id, created.table_name))
    (kept_id, kept_table), (claimed_id, claimed_table) = datasets
    kept_previous = previous_version_table(kept_table, kept_id)
    claimed_previous = previous_version_table(claimed_table, claimed_id)
    await create_dataset(session, created_by=admin_id, table_name=claimed_previous)
    await session.execute(
        text(
            "UPDATE catalog.datasets SET previous_version_number = 1 "
            "WHERE id IN (:kept, :claimed)"
        ),
        {"kept": kept_id, "claimed": claimed_id},
    )
    await session.execute(text(f'CREATE SCHEMA "{_OTHER_SCHEMA}"'))
    for schema, table in (
        ("data", kept_previous),
        (_OTHER_SCHEMA, kept_previous),
        ("data", claimed_previous),
    ):
        await session.execute(text(f'CREATE TABLE "{schema}"."{table}" (gid int)'))
    await session.commit()

    try:
        down = run_alembic("downgrade", "0076_feature_create_keys")
        assert down.returncode == 0, down.stderr

        assert not await _exists("data", kept_previous)
        assert await _exists(_OTHER_SCHEMA, kept_previous)
        assert await _exists("data", claimed_previous)
    finally:
        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
        await session.rollback()
        await session.execute(text(f'DROP SCHEMA IF EXISTS "{_OTHER_SCHEMA}" CASCADE'))
        for table in (kept_previous, claimed_previous):
            await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
        await session.commit()
