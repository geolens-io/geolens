"""Migration 0087 moves the one kept version onto its version row and back, and refuses to drop any."""

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
from tests.test_previous_version_migration_2590 import (
    previous_version_table as _single_name,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        enterprise_migrations_present(),
        reason="OSS migration round-trip runs in the no-overlay migration job",
    ),
]

_BEFORE = "0086_dataset_append_api_keys"


async def _seed(session, *, versions: list[int]):
    """A dataset at version 3 keeping ``versions``, each in a table holding its number."""
    admin_id = await get_user_id(session, "admin")
    created = await create_dataset(
        session, created_by=admin_id, table_name=f"kept_{uuid.uuid4().hex[:10]}"
    )
    await session.execute(
        text("UPDATE catalog.datasets SET current_version = 3 WHERE id = :id"),
        {"id": created.id},
    )
    tables = {}
    for number in versions:
        table = previous_version_table(created.table_name, created.id, number)
        await session.execute(
            text(f'CREATE TABLE "data"."{table}" (gid int PRIMARY KEY)')
        )
        await session.execute(
            text(f'INSERT INTO "data"."{table}" (gid) VALUES (:n)'), {"n": number}
        )
        await session.execute(
            text(
                "INSERT INTO catalog.dataset_versions (dataset_id, version_number, "
                "uploaded_at, kept_table, kept_at, kept_bytes, kept_refreshed_at) "
                "VALUES (:id, :n, '2026-01-01', :t, '2026-02-01', 8192, '2026-01-15')"
            ),
            {"id": created.id, "n": number, "t": table},
        )
        tables[number] = table
    await session.commit()
    return created.id, created.table_name, tables


async def _gids(table: str) -> list[int]:
    rows = await fresh_query(f'SELECT gid FROM "data"."{table}"')
    return [row[0] for row in rows]


async def _drop(session, dataset_id, tables) -> None:
    await session.rollback()
    for table in tables:
        await session.execute(text(f'DROP TABLE IF EXISTS "data"."{table}"'))
    await session.execute(
        text("DELETE FROM catalog.datasets WHERE id = :id"), {"id": dataset_id}
    )
    await session.commit()


async def test_one_kept_version_survives_a_downgrade_and_an_upgrade(
    test_db_session,
) -> None:
    """Down: the kept table takes the single name and the dataset columns; up: it is kept again, rows intact."""
    session = test_db_session
    dataset_id, base, tables = await _seed(session, versions=[2])
    single = _single_name(base, dataset_id)
    try:
        down = run_alembic("downgrade", _BEFORE)
        assert down.returncode == 0, down.stderr
        row = await fresh_query(
            "SELECT previous_version_number, previous_version_bytes, "
            "previous_version_retained_at, previous_version_refreshed_at "
            "FROM catalog.datasets WHERE id = :id",
            {"id": dataset_id},
        )
        assert row[0][0:2] == (2, 8192)
        assert row[0][2] is not None and row[0][3] is not None
        assert await _gids(single) == [2]

        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
        kept = await fresh_query(
            "SELECT version_number, kept_table, kept_bytes, kept_at, "
            "kept_refreshed_at FROM catalog.dataset_versions "
            "WHERE dataset_id = :id AND kept_table IS NOT NULL",
            {"id": dataset_id},
        )
        assert [(r[0], r[1], r[2]) for r in kept] == [(2, single, 8192)]
        assert kept[0][3] == row[0][2] and kept[0][4] == row[0][3]
        assert await _gids(single) == [2]
    finally:
        run_alembic("upgrade", "heads")
        await _drop(session, dataset_id, [*tables.values(), single])


async def test_an_upgrade_writes_a_missing_version_row(test_db_session) -> None:
    """A previous version recorded only on the dataset gets a version row naming its table."""
    session = test_db_session
    dataset_id, base, _ = await _seed(session, versions=[])
    single = _single_name(base, dataset_id)
    try:
        down = run_alembic("downgrade", _BEFORE)
        assert down.returncode == 0, down.stderr
        await session.rollback()
        await session.execute(
            text(
                "UPDATE catalog.datasets SET previous_version_number = 2, "
                "previous_version_bytes = 4096 WHERE id = :id"
            ),
            {"id": dataset_id},
        )
        await session.commit()

        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
        kept = await fresh_query(
            "SELECT version_number, kept_table, kept_bytes FROM "
            "catalog.dataset_versions WHERE dataset_id = :id",
            {"id": dataset_id},
        )
        assert kept == [(2, single, 4096)]
    finally:
        run_alembic("upgrade", "heads")
        await _drop(session, dataset_id, [single])


async def test_the_downgrade_refuses_while_a_dataset_keeps_several_versions(
    test_db_session,
) -> None:
    """With two kept versions the downgrade stops, and both stay kept and restorable."""
    session = test_db_session
    dataset_id, _, tables = await _seed(session, versions=[1, 2])
    try:
        down = run_alembic("downgrade", _BEFORE, normalize=False)
        assert down.returncode != 0
        assert "more than one previous version" in down.stderr
        kept = await fresh_query(
            "SELECT version_number FROM catalog.dataset_versions "
            "WHERE dataset_id = :id AND kept_table IS NOT NULL ORDER BY 1",
            {"id": dataset_id},
        )
        assert [r[0] for r in kept] == [1, 2]
        assert await _gids(tables[1]) == [1]
        assert await _gids(tables[2]) == [2]
    finally:
        run_alembic("upgrade", "heads")
        await _drop(session, dataset_id, tables.values())
