"""Discovery reports no row estimate for a table PostgreSQL has never analyzed."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

pytestmark = pytest.mark.anyio


async def _estimated_rows(client: AsyncClient, headers: dict, table: str) -> int | None:
    response = await client.get("/ingest/discover/", headers=headers)
    [row] = [t for t in response.json()["tables"] if t["table_name"] == table]
    return row["estimated_rows"]


@pytest.mark.parametrize("rows", [3, 0])
async def test_the_estimate_is_null_until_the_table_is_analyzed(
    client: AsyncClient, admin_auth_header: dict, test_db_session, rows: int
) -> None:
    """An unanalyzed table has no estimate, and an analyzed one reports its count."""
    table = f"estimate_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, geom geometry(Point, 4326))"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table} (geom) "
            "SELECT ST_SetSRID(ST_MakePoint(0, 0), 4326) FROM generate_series(1, :n)"
        ),
        {"n": rows},
    )
    await test_db_session.commit()
    try:
        assert await _estimated_rows(client, admin_auth_header, table) is None

        await test_db_session.execute(text(f"ANALYZE data.{table}"))
        await test_db_session.commit()

        assert await _estimated_rows(client, admin_auth_header, table) == rows
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()
