"""Registration refuses a geom column that declares no SRID and reports failures without driver text."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.core.failure_reason import INTERNAL_FAILURE_REASON
from app.modules.catalog.datasets.domain.models import Dataset
from app.processing.ingest.schemas import UNDECLARED_SRID_CODE
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
    """Registration answers 400 with the SRID reason, and discovery gives its code."""
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
        assert row["refusal_reason"] == UNDECLARED_SRID_CODE
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


async def test_an_unexpected_registration_error_returns_the_handlers_500(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    """An unexpected registration failure answers the route's own 500 message."""

    async def _fail(*args, **kwargs):
        raise RuntimeError("unexpected")

    with patch("app.processing.ingest.router.register_existing_table", _fail):
        response = await client.post(
            "/ingest/register/",
            json={"table_name": "any_table", "title": "Any", "visibility": "private"},
            headers=admin_auth_header,
        )

    assert response.status_code == 500
    assert response.json()["detail"] == "Registration failed — see server logs"


async def test_a_failed_bulk_item_reports_no_sql_or_row_text(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    """A bulk item that fails in the database reports a fixed code, not the driver text."""

    async def _fail(*args, **kwargs):
        raise IntegrityError(
            "INSERT INTO catalog.datasets (table_name, srid) VALUES ($1, $2)",
            ("any_table", 0),
            Exception("new row violates check constraint; Failing row contains (0)"),
        )

    with patch("app.processing.ingest.router.register_existing_table", _fail):
        response = await client.post(
            "/ingest/register/bulk/",
            json={"tables": [{"table_name": "any_table", "title": "Any"}]},
            headers=admin_auth_header,
        )

    assert response.status_code == 201, response.text
    [item] = response.json()["results"]
    assert item["status"] == "error"
    assert item["error"] == INTERNAL_FAILURE_REASON


_STEPS = {
    "add_4326_column": (
        "geom geometry(Point, 4326)",
        "Failed to add geom_4326 column to '{table}'.",
    ),
    "linearize_existing_4326": (
        "geom geometry(Point, 4326), geom_4326 geometry(Geometry, 4326)",
        "Failed to linearize geom_4326 on '{table}'.",
    ),
}


@pytest.mark.parametrize("step", list(_STEPS))
async def test_a_failed_geom_4326_step_reports_no_driver_text(
    client: AsyncClient, admin_auth_header: dict, test_db_session, step: str
) -> None:
    """A geom_4326 step that fails in the database answers its own sentence."""
    columns, message = _STEPS[step]
    table = f"srid_step_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, {columns})")
    )
    await test_db_session.commit()

    async def _fail(*args, **kwargs):
        raise ProgrammingError(
            f"ALTER TABLE data.{table} ADD COLUMN geom_4326 geometry",
            {},
            Exception("permission denied for table"),
        )

    try:
        with patch(f"app.processing.ingest.service.{step}", _fail):
            response = await client.post(
                "/ingest/register/",
                json={"table_name": table, "title": "Step", "visibility": "private"},
                headers=admin_auth_header,
            )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == message.format(table=table)
    finally:
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()
