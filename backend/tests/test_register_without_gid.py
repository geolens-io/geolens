"""Registration gives a table without ``gid`` one readers can key on, and refuses a ``gid`` they cannot."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import Dataset
from app.processing.ingest.schemas import UNUSABLE_GID_CODE
from app.processing.ingest.service import UNUSABLE_GID_REASON

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.usefixtures("_init_tile_pool_for_tests"),
]

_POINTS = "ST_SetSRID(ST_MakePoint(-73.9, 40.7), 4326)"

_KEYED = {
    "id_primary_key": "id serial PRIMARY KEY, name text, geom geometry(Point, 4326)",
    "no_primary_key": "name text, geom geometry(Point, 4326)",
    "ogc_fid": "ogc_fid serial PRIMARY KEY, name text, geom geometry(Point, 4326)",
    "gid_primary_key": "gid serial PRIMARY KEY, name text, geom geometry(Point, 4326)",
}

_UNKEYABLE = {
    "text": ("gid text PRIMARY KEY", "('a'), ('b')"),
    "duplicated": ("gid integer NOT NULL", "(1), (1)"),
    "nullable": ("gid integer UNIQUE", "(NULL), (1)"),
    "not_unique_alone": (
        "gid integer NOT NULL, part integer, UNIQUE (gid, part)",
        "(1), (2)",
    ),
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


async def _discovered(client: AsyncClient, headers: dict, table: str) -> dict:
    response = await client.get("/ingest/discover/", headers=headers)
    [row] = [t for t in response.json()["tables"] if t["table_name"] == table]
    return row


async def _drop(session, table: str) -> None:
    await session.rollback()
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table} CASCADE"))
    await session.commit()


@pytest.mark.parametrize("columns", list(_KEYED.values()), ids=list(_KEYED))
async def test_a_registered_table_is_read_by_feature_id(
    client: AsyncClient, admin_auth_header: dict, test_db_session, columns: str
) -> None:
    """Tiles, OGC items and rows read a registered table, and its new rows get a gid."""
    table = f"keyed_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(text(f"CREATE TABLE data.{table} ({columns})"))
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table} (name, geom) "
            f"VALUES ('a', {_POINTS}), ('b', {_POINTS}), ('c', {_POINTS})"
        )
    )
    await test_db_session.commit()
    before = await _columns(test_db_session, table)
    try:
        assert (await _discovered(client, admin_auth_header, table))[
            "refusal_reason"
        ] is None
        response = await client.post(
            "/ingest/register/",
            json={"table_name": table, "title": "Keyed", "visibility": "public"},
            headers=admin_auth_header,
        )
        assert response.status_code == 201, response.text
        dataset_id = response.json()["dataset_id"]

        reads = {
            "tile": f"/tiles/data.{table}/0/0/0.pbf",
            "cluster_tile": f"/tiles/clusters/data.{table}/0/0/0.pbf",
            "items": f"/collections/{dataset_id}/items",
            "rows": f"/datasets/{dataset_id}/rows/",
        }
        responses = {
            name: await client.get(url, headers=admin_auth_header)
            for name, url in reads.items()
        }
        assert {name: r.status_code for name, r in responses.items()} == dict.fromkeys(
            reads, 200
        )
        assert responses["tile"].content
        assert len(responses["rows"].json()["rows"]) == 3
        ids = [feature["id"] for feature in responses["items"].json()["features"]]
        assert len(set(ids)) == 3
        assert all(isinstance(feature_id, int) for feature_id in ids)
        item = await client.get(
            f"/collections/{dataset_id}/items/{ids[0]}", headers=admin_auth_header
        )
        assert item.status_code == 200, item.text

        assert set(await _columns(test_db_session, table)) == {
            *before,
            "gid",
            "geom_4326",
        }
        await test_db_session.execute(
            text(f"INSERT INTO data.{table} (name, geom) VALUES ('d', {_POINTS})")
        )
        await test_db_session.commit()
        assert (
            await test_db_session.scalar(
                text(f"SELECT count(DISTINCT gid) FROM data.{table}")
            )
            == 4
        )
    finally:
        await _drop(test_db_session, table)


async def test_a_non_spatial_table_without_gid_is_read_by_rows(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A non-spatial table without gid registers and its rows read."""
    table = f"keyed_plain_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(f"CREATE TABLE data.{table} (id serial PRIMARY KEY, name text)")
    )
    await test_db_session.execute(
        text(f"INSERT INTO data.{table} (name) VALUES ('a'), ('b')")
    )
    await test_db_session.commit()
    try:
        response = await client.post(
            "/ingest/register/",
            json={"table_name": table, "title": "Plain", "visibility": "private"},
            headers=admin_auth_header,
        )
        assert response.status_code == 201, response.text

        rows = await client.get(
            f"/datasets/{response.json()['dataset_id']}/rows/",
            headers=admin_auth_header,
        )
        assert rows.status_code == 200, rows.text
        assert len(rows.json()["rows"]) == 2
    finally:
        await _drop(test_db_session, table)


@pytest.mark.parametrize("shape", list(_UNKEYABLE.values()), ids=list(_UNKEYABLE))
async def test_a_gid_readers_cannot_key_on_is_refused_and_flagged(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    shape: tuple[str, str],
) -> None:
    """Registration answers 400 with the gid reason, and discovery gives its code."""
    columns, values = shape
    table = f"unkeyed_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(f"CREATE TABLE data.{table} ({columns}, geom geometry(Point, 4326))")
    )
    await test_db_session.execute(
        text(f"INSERT INTO data.{table} (gid) VALUES {values}")
    )
    await test_db_session.commit()
    before = await _columns(test_db_session, table)
    try:
        assert (await _discovered(client, admin_auth_header, table))[
            "refusal_reason"
        ] == UNUSABLE_GID_CODE

        response = await client.post(
            "/ingest/register/",
            json={"table_name": table, "title": "Unkeyed", "visibility": "private"},
            headers=admin_auth_header,
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == (
            f"Table '{table}' cannot be registered. {UNUSABLE_GID_REASON}"
        )
        assert (
            await test_db_session.scalar(
                select(Dataset.id).where(Dataset.table_name == table)
            )
            is None
        )
        assert await _columns(test_db_session, table) == before

        bulk = await client.post(
            "/ingest/register/bulk/",
            json={"tables": [{"table_name": table, "title": "Unkeyed"}]},
            headers=admin_auth_header,
        )
        [item] = bulk.json()["results"]
        assert item["error"] == response.json()["detail"]
    finally:
        await _drop(test_db_session, table)
