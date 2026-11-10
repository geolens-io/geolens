"""Migration 0088 moves the one kept version onto its version row and back, and refuses to drop any; 0101 drops the emptied dataset columns."""

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

_BEFORE = "0087_publish_api_keys"
_KEPT = "0088_dataset_kept_versions"


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


_LEGACY_COLUMNS = (
    "previous_version_number",
    "previous_version_retained_at",
    "previous_version_bytes",
    "previous_version_refreshed_at",
)


async def _legacy_columns() -> set[str]:
    rows = await fresh_query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'catalog' AND table_name = 'datasets' "
        "AND column_name LIKE 'previous_version_%'"
    )
    return {row[0] for row in rows}


@pytest.mark.parametrize("legacy_columns", ["kept", "dropped"])
async def test_one_kept_version_survives_a_downgrade_and_an_upgrade(
    test_db_session, legacy_columns
) -> None:
    """Down: the kept table takes the single name and the dataset columns, whether or not 0088 left them; up: it is kept again, rows intact."""
    session = test_db_session
    dataset_id, base, tables = await _seed(session, versions=[2])
    single = _single_name(base, dataset_id)
    try:
        if legacy_columns == "dropped":
            down = run_alembic("downgrade", _KEPT)
            assert down.returncode == 0, down.stderr
            await fresh_query(
                "ALTER TABLE catalog.datasets "
                + ", ".join(f"DROP COLUMN {c}" for c in _LEGACY_COLUMNS)
            )
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


async def test_0088_empties_the_dataset_columns_and_head_drops_them(
    test_db_session,
) -> None:
    """0088 moves the kept version to its version row and leaves the columns a 1.26 process maps, all NULL; head has none of them."""
    session = test_db_session
    dataset_id, base, tables = await _seed(session, versions=[2])
    single = _single_name(base, dataset_id)
    try:
        down = run_alembic("downgrade", _BEFORE)
        assert down.returncode == 0, down.stderr
        up = run_alembic("upgrade", _KEPT)
        assert up.returncode == 0, up.stderr

        assert await _legacy_columns() == set(_LEGACY_COLUMNS)
        row = await fresh_query(
            f"SELECT {', '.join(_LEGACY_COLUMNS)} FROM catalog.datasets WHERE id = :id",
            {"id": dataset_id},
        )
        assert row == [(None, None, None, None)]

        up = run_alembic("upgrade", "heads")
        assert up.returncode == 0, up.stderr
        assert await _legacy_columns() == set()
        kept = await fresh_query(
            "SELECT version_number, kept_table, kept_bytes FROM "
            "catalog.dataset_versions WHERE dataset_id = :id "
            "AND kept_table IS NOT NULL",
            {"id": dataset_id},
        )
        assert kept == [(2, single, 8192)]
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


async def test_the_downgrade_finds_a_kept_table_in_any_data_schema(
    test_db_session,
) -> None:
    """A kept table in another data schema is still moved back; one no schema holds leaves the number empty."""
    session = test_db_session
    found_id, found_base, _ = await _seed(session, versions=[])
    missing_id, _, _ = await _seed(session, versions=[])
    schema = "data_t_" + str(uuid.uuid4()).replace("-", "_")
    kept = previous_version_table(found_base, found_id, 2)
    await session.execute(text(f'CREATE SCHEMA "{schema}"'))
    await session.execute(text(f'CREATE TABLE "{schema}"."{kept}" (gid int)'))
    for dataset_id, table in (
        (found_id, kept),
        (missing_id, f"gone_previous_2_{missing_id.hex}"),
    ):
        await session.execute(
            text(
                "INSERT INTO catalog.dataset_versions "
                "(dataset_id, version_number, kept_table, kept_at) "
                "VALUES (:id, 2, :t, now())"
            ),
            {"id": dataset_id, "t": table},
        )
    await session.commit()
    single = _single_name(found_base, found_id)
    try:
        down = run_alembic("downgrade", _BEFORE)
        assert down.returncode == 0, down.stderr
        numbers = dict(
            await fresh_query(
                "SELECT id, previous_version_number FROM catalog.datasets "
                "WHERE id IN (:a, :b)",
                {"a": found_id, "b": missing_id},
            )
        )
        assert numbers == {found_id: 2, missing_id: None}
        assert await fresh_query(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND c.relname = :t",
            {"s": schema, "t": single},
        )
    finally:
        run_alembic("upgrade", "heads")
        await session.rollback()
        await session.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await session.commit()
        await _drop(session, found_id, [])
        await _drop(session, missing_id, [])


async def test_the_downgrade_leaves_another_datasets_table_under_a_kept_name(
    test_db_session,
) -> None:
    """A same-named table that another dataset uses, outside the dataset's own schema, is neither renamed nor recorded."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    dataset_id, base, _ = await _seed(session, versions=[])
    schema = "data_t_" + str(uuid.uuid4()).replace("-", "_")
    name = previous_version_table(base, dataset_id, 2)
    claimant = await create_dataset(session, created_by=admin_id, table_name=name)
    claimant_id = claimant.id
    await session.execute(text(f'CREATE SCHEMA "{schema}"'))
    await session.execute(text(f'CREATE TABLE "{schema}"."{name}" (gid int)'))
    await session.execute(
        text(
            "INSERT INTO catalog.dataset_versions "
            "(dataset_id, version_number, kept_table, kept_at) "
            "VALUES (:id, 2, :t, now())"
        ),
        {"id": dataset_id, "t": name},
    )
    await session.commit()
    try:
        down = run_alembic("downgrade", _BEFORE)
        assert down.returncode == 0, down.stderr
        number = await fresh_query(
            "SELECT previous_version_number FROM catalog.datasets WHERE id = :id",
            {"id": dataset_id},
        )
        assert number == [(None,)]
        assert await fresh_query(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND c.relname = :t",
            {"s": schema, "t": name},
        )
    finally:
        run_alembic("upgrade", "heads")
        await session.rollback()
        await session.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await session.commit()
        await _drop(session, dataset_id, [])
        await _drop(session, claimant_id, [])
