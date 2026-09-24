"""Registration refuses a geom column that declares no SRID."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import Dataset
from app.processing.ingest.service import UNDECLARED_SRID_REASON

pytestmark = pytest.mark.anyio

_TABLES = {
    "unconstrained": "geom geometry",
    "typed_without_srid": "geom geometry(Point)",
    "own_geom_4326": "geom geometry(Point), geom_4326 geometry(Geometry, 4326)",
}


async def _columns(session, table: str) -> list[str]:
    result = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :t ORDER BY column_name"
        ),
        {"t": table},
    )
    return list(result.scalars())


@pytest.mark.parametrize("columns", list(_TABLES.values()), ids=list(_TABLES))
async def test_a_geom_column_without_an_srid_is_refused_and_flagged(
    client: AsyncClient, admin_auth_header: dict, test_db_session, columns: str
) -> None:
    """Registration answers 400 with the SRID reason, and discovery flags the table."""
    table = f"srid_zero_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, name text, {columns})"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table} (name, geom) "
            "VALUES ('a', ST_GeomFromText('POINT(-73.9 40.7)'))"
        )
    )
    await test_db_session.commit()
    before = await _columns(test_db_session, table)
    try:
        response = await client.post(
            "/ingest/register/",
            json={"table_name": table, "title": "No SRID", "visibility": "private"},
            headers=admin_auth_header,
        )

        assert response.status_code == 400, response.text
        assert UNDECLARED_SRID_REASON in response.json()["detail"]
        assert (
            await test_db_session.scalar(
                select(Dataset.id).where(Dataset.table_name == table)
            )
            is None
        )
        assert await _columns(test_db_session, table) == before
        discovered = await client.get("/ingest/discover/", headers=admin_auth_header)
        [row] = [t for t in discovered.json()["tables"] if t["table_name"] == table]
        assert row["refusal_reason"] == UNDECLARED_SRID_REASON
    finally:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()


async def test_a_table_with_a_declared_srid_has_no_refusal_reason(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """Discovery gives no refusal reason for a table with a declared SRID."""
    table = f"srid_ok_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, geom geometry(Point, 4326))"
        )
    )
    await test_db_session.commit()
    try:
        discovered = await client.get("/ingest/discover/", headers=admin_auth_header)
        [row] = [t for t in discovered.json()["tables"] if t["table_name"] == table]
        assert row["srid"] == 4326
        assert row["refusal_reason"] is None
    finally:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()


async def test_a_refused_bulk_item_reports_the_refusal(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A refused bulk item reports the refusal's own message."""
    table = f"srid_zero_bulk_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, geom geometry(Point))"
        )
    )
    await test_db_session.commit()
    try:
        response = await client.post(
            "/ingest/register/bulk/",
            json={"tables": [{"table_name": table, "title": "No SRID"}]},
            headers=admin_auth_header,
        )

        assert response.status_code == 201, response.text
        [item] = response.json()["results"]
        assert item["status"] == "error"
        assert item["error"] == (
            f"Table '{table}' cannot be registered. {UNDECLARED_SRID_REASON}"
        )
    finally:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()
