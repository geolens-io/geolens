"""Registration and refresh give a table without ``gid`` one readers can key on, and refuse a ``gid`` they cannot."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest.schemas import UNUSABLE_GID_CODE
from app.processing.ingest.service import UNUSABLE_GID_REASON
from app.processing.ingest.tasks_postgis_refresh import (
    PostgisRefreshError,
    refresh_postgis,
)

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


async def _register_recreated(
    client: AsyncClient, headers: dict, session, table: str, columns: str
) -> str:
    """Register a keyed table, then drop and recreate it with ``columns``, as ``ogr2ogr -overwrite`` does."""
    await session.execute(
        text(
            f"CREATE TABLE data.{table} "
            "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
        )
    )
    await session.execute(
        text(f"INSERT INTO data.{table} (name, geom) VALUES ('a', {_POINTS})")
    )
    await session.commit()
    response = await client.post(
        "/ingest/register/",
        json={"table_name": table, "title": "Recreated", "visibility": "public"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    await session.execute(text(f"DROP TABLE data.{table}"))
    await session.execute(text(f"CREATE TABLE data.{table} ({columns})"))
    await session.execute(
        text(
            f"INSERT INTO data.{table} (name, geom) "
            f"VALUES ('b', {_POINTS}), ('c', {_POINTS})"
        )
    )
    await session.commit()
    return response.json()["dataset_id"]


async def _refresh(
    client: AsyncClient, headers: dict, session, dataset_id: str
) -> DatasetRefreshRun:
    """Dispatch a refresh through the API, run its worker task, and return the run."""
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    port = MagicMock()
    port.refresh_postgis_task.return_value = task
    with patch.object(router_refresh, "get_catalog_port", return_value=port):
        response = await client.post(f"/datasets/{dataset_id}/refresh", headers=headers)
    assert response.status_code == 202, response.text
    payload = response.json()
    job = await session.get(IngestJob, uuid.UUID(payload["job_id"]))
    attempt_id = str(job.attempt_id)
    await session.rollback()
    try:
        await refresh_postgis.func(
            job_id=payload["job_id"], dataset_id=dataset_id, attempt_id=attempt_id
        )
    except PostgisRefreshError:
        pass
    return (
        await session.execute(
            select(DatasetRefreshRun)
            .where(DatasetRefreshRun.dataset_id == uuid.UUID(dataset_id))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_a_table_recreated_without_gid_is_keyed_again_by_refresh(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A refresh adds gid back to a table recreated without one, and its tiles and rows read."""
    table = f"recreated_{uuid.uuid4().hex[:10]}"
    try:
        dataset_id = await _register_recreated(
            client,
            admin_auth_header,
            test_db_session,
            table,
            "ogc_fid serial PRIMARY KEY, name text, geom geometry(Point, 4326)",
        )

        run = await _refresh(client, admin_auth_header, test_db_session, dataset_id)

        assert (run.status, run.error_code) == ("succeeded", None)
        tile = await client.get(
            f"/tiles/data.{table}/0/0/0.pbf", headers=admin_auth_header
        )
        rows = await client.get(
            f"/datasets/{dataset_id}/rows/", headers=admin_auth_header
        )
        assert (tile.status_code, rows.status_code) == (200, 200)
        assert len(rows.json()["rows"]) == 2
    finally:
        await _drop(test_db_session, table)


async def test_a_table_recreated_with_an_unusable_gid_fails_refresh_with_its_code(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A refresh of a table recreated with a text gid fails with the gid code and leaves it unaltered."""
    table = f"recreated_{uuid.uuid4().hex[:10]}"
    try:
        dataset_id = await _register_recreated(
            client,
            admin_auth_header,
            test_db_session,
            table,
            "gid text, name text, geom geometry(Point, 4326)",
        )
        before = await _columns(test_db_session, table)

        run = await _refresh(client, admin_auth_header, test_db_session, dataset_id)

        assert (run.status, run.error_code) == ("failed", UNUSABLE_GID_CODE)
        assert await _columns(test_db_session, table) == before
    finally:
        await _drop(test_db_session, table)
