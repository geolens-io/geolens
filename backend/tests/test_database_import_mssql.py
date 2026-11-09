"""Database import and refresh against a real SQL Server.

Runs only where GDAL has the FreeTDS ODBC driver and a SQL Server is reachable:
the API image, with the ``GEOLENS_TEST_MSSQL_*`` variables naming the server, a
database, a read-only login and an admin login that creates the tables. CI's
SQL Server job sets them; everywhere else this module is skipped.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.config_database_sources import DatabaseConnection
from app.modules.catalog.datasets.api import router_refresh_database
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.database_sources import database_gdal_source, freetds_workdir
from app.platform.gdal_env import gdal_database_safe_env
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest import service as ingest_service
from app.processing.ingest.database_import import DatabaseImportError
from app.processing.ingest.tasks_database import ingest_database, refresh_database

_ENV = {
    key: os.environ.get(f"GEOLENS_TEST_MSSQL_{key.upper()}")
    for key in (
        "host",
        "port",
        "database",
        "user",
        "password",
        "admin_user",
        "admin_password",
    )
}

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.requires_ogr2ogr,
    pytest.mark.skipif(
        not all(_ENV.values()), reason="GEOLENS_TEST_MSSQL_* is not set"
    ),
]


def _connection(username: str, password: str) -> DatabaseConnection:
    return DatabaseConnection.model_validate(
        {
            "engine": "sqlserver",
            "host": _ENV["host"],
            "port": int(_ENV["port"] or 1433),
            "database": _ENV["database"],
            "username": username,
            "password": password,
            "trust_server_certificate": True,
        }
    )


async def _admin(sql: str) -> None:
    """Run one statement as the admin login; the reader can't write."""
    connection = _connection(_ENV["admin_user"], _ENV["admin_password"])
    with freetds_workdir(connection) as workdir:
        proc = await asyncio.create_subprocess_exec(
            "ogrinfo",
            "-q",
            "-if",
            "MSSQLSpatial",
            database_gdal_source(connection),
            "-sql",
            sql,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=gdal_database_safe_env(
                os.path.join(workdir, "freetds.conf"),
                connection.username,
                connection.password.get_secret_value(),
            ),
        )
        _, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode(errors="replace")


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(
        settings,
        "database_sources",
        {"gis": _connection(_ENV["user"], _ENV["password"])},
    )


@pytest.fixture
async def table():
    """A fresh table of three points in SRID 2263; dropped afterwards."""
    name = f"t_{uuid.uuid4().hex[:10]}"
    await _admin(
        f"CREATE TABLE dbo.{name} "
        "(pk int PRIMARY KEY, label nvarchar(20), extra int, shape geometry)"
    )
    await _admin(
        f"INSERT INTO dbo.{name} VALUES "
        "(11, N'a', 1, geometry::STGeomFromText('POINT (987654.25 203456.75)', 2263)),"
        "(12, N'b', 2, geometry::STGeomFromText('POINT (1000000 200000)', 2263)),"
        "(13, N'c', 3, geometry::STGeomFromText('POINT (990000 201000)', 2263))"
    )
    yield name
    await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def _import(client, headers, table_name: str, **extra) -> IngestJob:
    deferred = AsyncMock()
    original = ingest_service.defer_async_with_tenant
    ingest_service.defer_async_with_tenant = deferred
    try:
        resp = await client.post(
            "/services/databases/gis/imports/",
            json={"schema_name": "dbo", "table_name": table_name, **extra},
            headers=headers,
        )
    finally:
        ingest_service.defer_async_with_tenant = original
    assert resp.status_code == 202, resp.text
    kwargs = deferred.await_args.kwargs
    await ingest_database.func(**kwargs)
    return kwargs


async def _job(session, job_id) -> IngestJob:
    return (
        await session.execute(
            select(IngestJob)
            .where(IngestJob.id == uuid.UUID(str(job_id)))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _dataset(session, dataset_id) -> Dataset:
    return (
        await session.execute(
            select(Dataset)
            .where(Dataset.id == dataset_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _refresh(client, headers, session, dataset_id, **body) -> DatasetRefreshRun:
    deferred = AsyncMock()
    original = router_refresh_database.defer_async_with_tenant
    router_refresh_database.defer_async_with_tenant = deferred
    try:
        resp = await client.post(
            f"/datasets/{dataset_id}/refresh", json=body or None, headers=headers
        )
    finally:
        router_refresh_database.defer_async_with_tenant = original
    assert resp.status_code == 202, resp.text
    await refresh_database.func(**deferred.await_args.kwargs)
    return (
        await session.execute(
            select(DatasetRefreshRun)
            .where(DatasetRefreshRun.id == uuid.UUID(resp.json()["run_id"]))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _rows(session, dataset: Dataset, sql: str):
    return (
        await session.execute(text(sql.format(t=f'data."{dataset.table_name}"')))
    ).all()


async def test_geometry_table_imports_with_its_srid_and_key(
    client: AsyncClient, editor_auth_header, configured, table, test_db_session
):
    kwargs = await _import(client, editor_auth_header, table)

    job = await _job(test_db_session, kwargs["job_id"])
    assert job.status == "complete", job.error_message
    dataset = await _dataset(test_db_session, job.dataset_id)
    assert dataset.source_format == "database"
    assert dataset.source_url is None
    assert dataset.origin_uri == f"database://gis/dbo.{table}"
    assert dataset.origin_ref == {
        "kind": "database",
        "connection": "gis",
        "schema": "dbo",
        "table": table,
    }
    assert dataset.srid == 2263
    assert dataset.feature_count == 3
    # The import read SQL Server, so it dates the contact; health is the
    # probe's to say and stays unknown.
    assert dataset.last_checked_at is not None
    assert dataset.source_health is None
    rows = await _rows(
        test_db_session,
        dataset,
        "SELECT pk, label, ST_SRID(geom), ST_X(ST_GeometryN(geom, 1)) "
        "FROM {t} ORDER BY pk",
    )
    assert [tuple(r) for r in rows][0] == (11, "a", 2263, 987654.25)

    dup = await client.post(
        "/services/databases/gis/imports/",
        json={"schema_name": "dbo", "table_name": table},
        headers=editor_auth_header,
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["existing_dataset_id"] == str(dataset.id)


async def test_a_table_with_two_spatial_columns_lists_and_imports_the_first(
    client: AsyncClient, editor_auth_header, configured, test_db_session
):
    name = f"m_{uuid.uuid4().hex[:10]}"
    await _admin(
        f"CREATE TABLE dbo.{name} "
        "(id int PRIMARY KEY, zz_first geography, aa_second geometry)"
    )
    try:
        await _admin(
            f"INSERT INTO dbo.{name} VALUES (1, "
            "geography::STGeomFromText('POINT (-73.9857 40.7484)', 4326), "
            "geometry::STGeomFromText('POINT (987654 203456)', 2263))"
        )
        listed = await client.get(
            "/services/databases/gis/tables/", headers=editor_auth_header
        )
        assert listed.status_code == 200, listed.text
        rows = [t for t in listed.json()["tables"] if t["table_name"] == name]
        assert [(r["geometry_column"], r["srid"]) for r in rows] == [("zz_first", 4326)]

        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        dataset = await _dataset(test_db_session, job.dataset_id)
        assert dataset.srid == 4326
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_geography_table_imports_as_lon_lat(
    client: AsyncClient, editor_auth_header, configured, test_db_session
):
    name = f"g_{uuid.uuid4().hex[:10]}"
    await _admin(f"CREATE TABLE dbo.{name} (id int PRIMARY KEY, geog geography)")
    try:
        await _admin(
            f"INSERT INTO dbo.{name} VALUES "
            "(1, geography::STGeomFromText('POINT (-73.9857 40.7484)', 4326))"
        )
        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        dataset = await _dataset(test_db_session, job.dataset_id)
        assert dataset.srid == 4326
        [(x, y)] = await _rows(
            test_db_session,
            dataset,
            "SELECT ST_X(ST_GeometryN(geom, 1)), ST_Y(ST_GeometryN(geom, 1)) FROM {t}",
        )
        assert (round(x, 4), round(y, 4)) == (-73.9857, 40.7484)
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_srid_0_asks_for_a_crs_and_keeps_it_across_a_refresh(
    client: AsyncClient, editor_auth_header, configured, test_db_session
):
    name = f"z_{uuid.uuid4().hex[:10]}"
    await _admin(f"CREATE TABLE dbo.{name} (id int PRIMARY KEY, geom geometry)")
    try:
        await _admin(
            f"INSERT INTO dbo.{name} VALUES "
            "(1, geometry::STGeomFromText('POINT (500000 4500000)', 0))"
        )
        asked = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, asked["job_id"])
        assert job.status == "failed"
        assert job.error_code == "missing_crs_database"

        kwargs = await _import(
            client, editor_auth_header, name, srid_override=32618, title="UTM"
        )
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        dataset = await _dataset(test_db_session, job.dataset_id)
        assert dataset.srid == 32618

        await _admin(
            f"INSERT INTO dbo.{name} VALUES "
            "(2, geometry::STGeomFromText('POINT (500100 4500100)', 0))"
        )
        run = await _refresh(client, editor_auth_header, test_db_session, dataset.id)
        assert run.status == "succeeded", run.error_message
        dataset = await _dataset(test_db_session, dataset.id)
        assert (dataset.srid, dataset.feature_count) == (32618, 2)
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_an_override_never_replaces_the_tables_own_srid(
    client: AsyncClient, editor_auth_header, configured, table, test_db_session
):
    kwargs = await _import(client, editor_auth_header, table, srid_override=3857)
    job = await _job(test_db_session, kwargs["job_id"])
    assert job.status == "complete", job.error_message
    dataset = await _dataset(test_db_session, job.dataset_id)
    assert dataset.srid == 2263

    run = await _refresh(client, editor_auth_header, test_db_session, dataset.id)
    assert run.status == "succeeded", run.error_message


async def test_refresh_picks_up_updated_rows(
    client: AsyncClient, editor_auth_header, configured, table, test_db_session
):
    kwargs = await _import(client, editor_auth_header, table)
    dataset_id = (await _job(test_db_session, kwargs["job_id"])).dataset_id
    imported_at = (await _dataset(test_db_session, dataset_id)).last_checked_at
    await _admin(f"UPDATE dbo.{table} SET label = N'renamed' WHERE pk = 12")

    run = await _refresh(client, editor_auth_header, test_db_session, dataset_id)

    assert run.status == "succeeded", run.error_message
    refreshed = await _dataset(test_db_session, dataset_id)
    assert refreshed.last_checked_at > imported_at
    assert refreshed.source_health == "healthy"
    assert run.verification["count_status"] == "matched"
    assert run.verification["review_reasons"] == []
    dataset = await _dataset(test_db_session, dataset_id)
    [(label,)] = await _rows(
        test_db_session, dataset, "SELECT label FROM {t} WHERE pk = 12"
    )
    assert label == "renamed"


async def test_a_dropped_column_blocks_until_accepted(
    client: AsyncClient, editor_auth_header, configured, table, test_db_session
):
    kwargs = await _import(client, editor_auth_header, table)
    dataset_id = (await _job(test_db_session, kwargs["job_id"])).dataset_id
    await _admin(f"ALTER TABLE dbo.{table} DROP COLUMN extra")

    blocked = await _refresh(client, editor_auth_header, test_db_session, dataset_id)

    assert blocked.status == "blocked"
    assert blocked.verification["review_reasons"] == ["destructive_schema_change"]
    dataset = await _dataset(test_db_session, dataset_id)
    assert "extra" in {c["name"] for c in dataset.column_info}

    accepted = await _refresh(
        client,
        editor_auth_header,
        test_db_session,
        dataset_id,
        accept_blocked_run_id=str(blocked.id),
    )
    assert accepted.status == "succeeded", accepted.error_message
    dataset = await _dataset(test_db_session, dataset_id)
    assert "extra" not in {c["name"] for c in dataset.column_info}


async def test_a_truncated_table_stops_for_review(
    client: AsyncClient, editor_auth_header, configured, table, test_db_session
):
    kwargs = await _import(client, editor_auth_header, table)
    dataset_id = (await _job(test_db_session, kwargs["job_id"])).dataset_id
    await _admin(f"TRUNCATE TABLE dbo.{table}")

    run = await _refresh(client, editor_auth_header, test_db_session, dataset_id)

    assert run.status == "blocked"
    assert run.verification["review_reasons"] == ["empty_result"]
    assert (await _dataset(test_db_session, dataset_id)).feature_count == 3


async def test_a_connection_that_is_gone_fails_naming_it(
    client: AsyncClient,
    editor_auth_header,
    configured,
    table,
    test_db_session,
    monkeypatch,
):
    kwargs = await _import(client, editor_auth_header, table)
    dataset_id = (await _job(test_db_session, kwargs["job_id"])).dataset_id
    deferred = AsyncMock()
    monkeypatch.setattr(router_refresh_database, "defer_async_with_tenant", deferred)
    admitted = await client.post(
        f"/datasets/{dataset_id}/refresh", headers=editor_auth_header
    )
    assert admitted.status_code == 202, admitted.text
    gone = {}
    monkeypatch.setattr(settings, "database_sources", gone)

    with pytest.raises(DatabaseImportError, match="'gis'"):
        await refresh_database.func(**deferred.await_args.kwargs)

    run = (
        await test_db_session.execute(
            select(DatasetRefreshRun)
            .where(DatasetRefreshRun.id == uuid.UUID(admitted.json()["run_id"]))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert run.status == "failed"
    assert "'gis'" in run.error_message
    assert (await _dataset(test_db_session, dataset_id)).feature_count == 3

    refused = await client.post(
        f"/datasets/{dataset_id}/refresh", headers=editor_auth_header
    )
    assert refused.status_code == 409
    assert "'gis'" in refused.json()["detail"]["message"]


async def test_an_import_by_a_user_at_quota_is_refused(
    client: AsyncClient, editor_auth_header, configured, table, test_db_session
):
    await _import(client, editor_auth_header, table)
    with patch(
        "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
        new_callable=AsyncMock,
        return_value=1,
    ):
        resp = await client.post(
            "/services/databases/gis/imports/",
            json={"schema_name": "dbo", "table_name": table, "title": "again"},
            headers=editor_auth_header,
        )
    assert resp.status_code == 422, resp.text
    assert "quota" in resp.json()["detail"].lower()


async def test_mixed_srids_are_refused_on_import_and_refresh(
    client: AsyncClient, editor_auth_header, configured, table, test_db_session
):
    name = f"m_{uuid.uuid4().hex[:10]}"
    await _admin(f"CREATE TABLE dbo.{name} (id int PRIMARY KEY, geom geometry)")
    try:
        await _admin(
            f"INSERT INTO dbo.{name} VALUES "
            "(1, geometry::STGeomFromText('POINT (1 1)', 4326)),"
            "(2, geometry::STGeomFromText('POINT (500000 4500000)', 32618))"
        )
        asked = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, asked["job_id"])
        assert job.status == "failed"
        assert job.error_code == "mixed_srid_database"
        assert job.dataset_id is None
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")

    kwargs = await _import(client, editor_auth_header, table)
    dataset_id = (await _job(test_db_session, kwargs["job_id"])).dataset_id
    await _admin(
        f"INSERT INTO dbo.{table} VALUES "
        "(14, N'd', 4, geometry::STGeomFromText('POINT (1 1)', 4326))"
    )
    run = await _refresh(client, editor_auth_header, test_db_session, dataset_id)
    assert run.status == "failed"
    assert run.error_code == "mixed_srid_database"
    assert (await _dataset(test_db_session, dataset_id)).feature_count == 3
