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
from functools import partial
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
from app.processing.ingest import database_import
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


async def _column_type(session, dataset: Dataset) -> str:
    return await session.scalar(
        text(
            "SELECT type FROM geometry_columns WHERE f_table_schema = 'data' "
            "AND f_table_name = :t AND f_geometry_column = 'geom'"
        ),
        {"t": dataset.table_name},
    )


async def test_a_table_of_points_imports_and_refreshes_as_point(
    client: AsyncClient, editor_auth_header, configured, table, test_db_session
):
    kwargs = await _import(client, editor_auth_header, table)
    job = await _job(test_db_session, kwargs["job_id"])
    assert job.status == "complete", job.error_message
    dataset = await _dataset(test_db_session, job.dataset_id)
    assert dataset.geometry_type == "POINT"
    assert await _column_type(test_db_session, dataset) == "POINT"
    rows = await _rows(test_db_session, dataset, "SELECT ST_AsText(geom) FROM {t}")
    assert "POINT(987654.25 203456.75)" in {wkt for (wkt,) in rows}
    # Release the read lock the refresh's swap needs.
    await test_db_session.commit()

    items = await client.get(
        f"/collections/{dataset.id}/items", headers=editor_auth_header
    )
    assert items.status_code == 200, items.text
    features = items.json()["features"]
    assert len(features) == 3
    assert {f["geometry"]["type"] for f in features} == {"Point"}

    await _admin(
        f"INSERT INTO dbo.{table} VALUES (14, N'd', 4, geometry::STGeomFromText("
        "'MULTIPOINT ((990100 201100), (990200 201200))', 2263))"
    )
    run = await _refresh(client, editor_auth_header, test_db_session, dataset.id)
    assert run.status == "succeeded", run.error_message
    assert run.verification["review_reasons"] == []
    dataset = await _dataset(test_db_session, dataset.id)
    assert (dataset.geometry_type, dataset.feature_count) == ("MULTIPOINT", 4)
    assert await _column_type(test_db_session, dataset) == "GEOMETRY"

    await _admin(f"DELETE FROM dbo.{table} WHERE pk = 14")
    run = await _refresh(client, editor_auth_header, test_db_session, dataset.id)
    assert run.status == "succeeded", run.error_message
    assert run.verification["review_reasons"] == []
    dataset = await _dataset(test_db_session, dataset.id)
    assert (dataset.geometry_type, dataset.feature_count) == ("POINT", 3)
    assert await _column_type(test_db_session, dataset) == "POINT"


async def test_a_multipoint_dataset_becomes_point_at_its_next_refresh(
    client: AsyncClient,
    editor_auth_header,
    configured,
    table,
    test_db_session,
    monkeypatch,
):
    with monkeypatch.context() as unnarrowed:
        unnarrowed.setattr(
            database_import, "_store_single_points_as_point", AsyncMock()
        )
        kwargs = await _import(client, editor_auth_header, table)
    dataset_id = (await _job(test_db_session, kwargs["job_id"])).dataset_id
    assert (await _dataset(test_db_session, dataset_id)).geometry_type == "MULTIPOINT"

    run = await _refresh(client, editor_auth_header, test_db_session, dataset_id)

    assert run.status == "succeeded", run.error_message
    assert run.verification["review_reasons"] == []
    dataset = await _dataset(test_db_session, dataset_id)
    assert (dataset.geometry_type, dataset.feature_count) == ("POINT", 3)


async def test_a_point_beside_a_two_part_multipoint_imports_as_multipoint(
    client: AsyncClient, editor_auth_header, configured, test_db_session
):
    name = f"p_{uuid.uuid4().hex[:10]}"
    await _admin(f"CREATE TABLE dbo.{name} (id int PRIMARY KEY, geom geometry)")
    try:
        await _admin(
            f"INSERT INTO dbo.{name} VALUES "
            "(1, geometry::STGeomFromText('POINT (1 1)', 4326)),"
            "(2, geometry::STGeomFromText('MULTIPOINT ((2 2), (3 3))', 4326)),"
            "(3, NULL)"
        )
        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        dataset = await _dataset(test_db_session, job.dataset_id)
        assert dataset.geometry_type == "MULTIPOINT"
        assert dataset.feature_count == 3
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


@pytest.mark.parametrize(
    "values",
    [
        ["POINT (1.5 2.25)", "POINT (3 4)", None],
        ["POINT (1 1 10.5)", "POINT (2 2 20.25)"],
        ["POINT (1 1)", "POINT (2 2 20.25)"],
        ["POINT (1 1 NULL 5)", "POINT (2 2 3 6)"],
        ["MULTIPOINT ((2 2))", "MULTIPOINT ((3 3))"],
    ],
    ids=["xy", "xyz", "xy-and-xyz", "m-and-zm", "one-part-multipoints"],
)
async def test_storing_points_as_point_changes_no_coordinate_of_the_copy(
    configured, test_db_session, monkeypatch, values
):
    """Each narrowed value is the one point the multi copy stores, as stored."""
    name = f"c_{uuid.uuid4().hex[:10]}"
    await _admin(f"CREATE TABLE dbo.{name} (id int PRIMARY KEY, geom geometry)")
    multi, narrowed = f"{name}_multi", f"{name}_point"
    try:
        rows = ",".join(
            f"({i}, geometry::STGeomFromText('{wkt}', 4326))" if wkt else f"({i}, NULL)"
            for i, wkt in enumerate(values, start=1)
        )
        await _admin(f"INSERT INTO dbo.{name} VALUES {rows}")
        copy = partial(
            database_import.copy_database_table,
            "gis",
            schema_name="dbo",
            table_name=name,
            column="geom",
            target_schema="data",
            srid=4326,
        )
        with monkeypatch.context() as unnarrowed:
            unnarrowed.setattr(
                database_import, "_store_single_points_as_point", AsyncMock()
            )
            await copy(target_table=multi)
        await copy(target_table=narrowed)

        column = await test_db_session.scalar(
            text(
                "SELECT type FROM geometry_columns WHERE f_table_schema = 'data' "
                "AND f_table_name = :t"
            ),
            {"t": narrowed},
        )
        assert column == "POINT"
        pairs = (
            await test_db_session.execute(
                text(
                    "SELECT ST_AsEWKB(ST_GeometryN(m._geolens_geom, 1)), "
                    "ST_AsEWKB(p._geolens_geom) "
                    f'FROM data."{multi}" m JOIN data."{narrowed}" p USING (id)'
                )
            )
        ).all()
        assert len(pairs) == len(values)
        assert all(before == after for before, after in pairs)
    finally:
        for staged in (multi, narrowed):
            await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{staged}"'))
        await test_db_session.commit()
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


@pytest.mark.parametrize("column_type", ["geometry", "geography"])
async def test_a_table_with_an_invalid_value_imports_and_refreshes(
    client: AsyncClient, editor_auth_header, configured, test_db_session, column_type
):
    name = f"iv_{uuid.uuid4().hex[:10]}"
    bowtie = "POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))"
    await _admin(f"CREATE TABLE dbo.{name} (id int PRIMARY KEY, g {column_type})")
    try:
        await _admin(
            f"INSERT INTO dbo.{name} VALUES "
            f"(1, {column_type}::STGeomFromText('{bowtie}', 4326)),"
            f"(2, {column_type}::STGeomFromText('POINT (1 1)', 4326))"
        )
        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        dataset = await _dataset(test_db_session, job.dataset_id)
        assert dataset.feature_count == 2

        await _admin(
            f"INSERT INTO dbo.{name} VALUES "
            f"(3, {column_type}::STGeomFromText('POINT (2 2)', 4326))"
        )
        run = await _refresh(client, editor_auth_header, test_db_session, dataset.id)
        assert run.status == "succeeded", run.error_message
        assert (await _dataset(test_db_session, dataset.id)).feature_count == 3
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def _spatial_table(prefix: str, values: list[str | None], kind="geometry") -> str:
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    await _admin(f"CREATE TABLE dbo.{name} (id int PRIMARY KEY, g {kind})")
    await _insert(name, values, kind=kind)
    return name


async def _insert(name: str, values: list[str | None], *, start=1, kind="geometry"):
    rows = ",".join(
        f"({i}, {kind}::STGeomFromText('{wkt}', 4326))" if wkt else f"({i}, NULL)"
        for i, wkt in enumerate(values, start=start)
    )
    await _admin(f"INSERT INTO dbo.{name} VALUES {rows}")


async def _geometry_column(session, table: str) -> tuple[str, int]:
    row = (
        await session.execute(
            text(
                "SELECT type, coord_dimension FROM geometry_columns "
                "WHERE f_table_schema = 'data' AND f_table_name = :t"
            ),
            {"t": table},
        )
    ).one()
    return (row.type, row.coord_dimension)


def _warnings(job: IngestJob) -> list[dict]:
    return (job.user_metadata or {}).get("warnings", [])


@pytest.mark.parametrize(
    ("values", "kind", "stored", "column"),
    [
        (
            ["POINT (1 1 10.5)", "POINT (2 2 0)", None],
            "geometry",
            ["POINT Z (1 1 10.5)", "POINT Z (2 2 0)", None],
            ("POINT", 3),
        ),
        (
            ["POINT (1 1 NULL 5)", "POINT (2 2 NULL 0)"],
            "geometry",
            ["POINT M (1 1 5)", "POINT M (2 2 0)"],
            ("POINTM", 3),
        ),
        (
            ["POINT (1 1 3 5)", "POINT (2 2 0 6)"],
            "geometry",
            ["POINT ZM (1 1 3 5)", "POINT ZM (2 2 0 6)"],
            ("POINT", 4),
        ),
        (
            ["LINESTRING (0 0 1, 1 1 2)", "LINESTRING (2 2 NULL 3, 3 3 NULL 4)"],
            "geometry",
            ["MULTILINESTRING((0 0,1 1))", "MULTILINESTRING((2 2,3 3))"],
            ("GEOMETRY", 2),
        ),
        (
            ["POLYGON ((0 0 5, 1 0 5, 1 1 5, 0 0 5))"],
            "geometry",
            ["MULTIPOLYGON Z (((0 0 5,1 0 5,1 1 5,0 0 5)))"],
            ("GEOMETRY", 3),
        ),
        (
            ["POINT (-73.9857 40.7484 12)"],
            "geography",
            ["POINT Z (-73.9857 40.7484 12)"],
            ("POINT", 3),
        ),
        (
            ["POINT (1.5 2.25)", "POINT (3 4)"],
            "geometry",
            ["POINT(1.5 2.25)", "POINT(3 4)"],
            ("POINT", 2),
        ),
    ],
    ids=["xyz", "xym", "xyzm", "z-and-m-lines", "polygon-z", "geography-z", "xy"],
)
async def test_the_copy_keeps_z_and_m_that_every_value_has(
    configured, test_db_session, values, kind, stored, column
):
    """No ordinate is padded or dropped when every value shares its dimensions."""
    name = await _spatial_table("d", values, kind=kind)
    target = f"{name}_copy"
    try:
        lost = await database_import.copy_database_table(
            "gis",
            schema_name="dbo",
            table_name=name,
            column="g",
            target_schema="data",
            target_table=target,
            srid=4326,
        )
        rows = (
            await test_db_session.execute(
                text(
                    f'SELECT ST_AsText(_geolens_geom) FROM data."{target}" ORDER BY id'
                )
            )
        ).all()
        assert [wkt for (wkt,) in rows] == stored
        assert await _geometry_column(test_db_session, target) == column
        mixed = kind == "geometry" and values[0].startswith("LINESTRING")
        assert lost == (2 if mixed else 0)
    finally:
        await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{target}"'))
        await test_db_session.commit()
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_xyz_points_import_with_z_and_ogc_items_return_it(
    client: AsyncClient, editor_auth_header, configured, test_db_session
):
    name = await _spatial_table("z", ["POINT (1 1 10.5)", "POINT (2 2 20.25)"])
    try:
        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        assert _warnings(job) == []
        dataset = await _dataset(test_db_session, job.dataset_id)
        assert (dataset.geometry_type, dataset.is_3d) == ("POINT", True)
        await test_db_session.commit()

        items = await client.get(
            f"/collections/{dataset.id}/items", headers=editor_auth_header
        )
        assert items.status_code == 200, items.text
        # Items serve the 2D WGS 84 copy; a point's Z rides along as ``elev``.
        elevations = sorted(f["properties"]["elev"] for f in items.json()["features"])
        assert elevations == [10.5, 20.25]
        rows = await _rows(test_db_session, dataset, "SELECT ST_AsText(geom) FROM {t}")
        assert sorted(wkt for (wkt,) in rows) == [
            "POINT Z (1 1 10.5)",
            "POINT Z (2 2 20.25)",
        ]
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_a_mixed_table_imports_2d_and_says_how_many_lost_z_or_m(
    client: AsyncClient, editor_auth_header, configured, test_db_session
):
    name = await _spatial_table(
        "x", ["POINT (1 1)", "POINT (2 2 20.25)", "POINT (3 3 NULL 5)", None]
    )
    try:
        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        assert _warnings(job) == [{"kind": "zm_dropped", "details": {"features": 2}}]
        dataset = await _dataset(test_db_session, job.dataset_id)
        rows = await _rows(test_db_session, dataset, "SELECT ST_AsText(geom) FROM {t}")
        assert sorted(wkt for (wkt,) in rows if wkt) == [
            "POINT(1 1)",
            "POINT(2 2)",
            "POINT(3 3)",
        ]
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


def _probe_then(monkeypatch, *, after_first=None, before_second=None):
    """Write to the table between the first count and the copy, or after it."""
    real = database_import.probe_table_dimensions
    calls = 0

    async def _probe(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2 and before_second:
            await before_second()
        counted = await real(*args, **kwargs)
        if calls == 1 and after_first:
            await after_first()
        return counted

    monkeypatch.setattr(database_import, "probe_table_dimensions", _probe)


async def test_a_value_without_z_written_during_the_copy_leaves_no_padded_z(
    client: AsyncClient, editor_auth_header, configured, test_db_session, monkeypatch
):
    name = await _spatial_table("r", ["POINT (1 1 10.5)", "POINT (2 2 20.25)"])
    try:
        _probe_then(
            monkeypatch, after_first=partial(_insert, name, ["POINT (3 3)"], start=3)
        )
        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        assert _warnings(job) == [{"kind": "zm_dropped", "details": {"features": 2}}]
        dataset = await _dataset(test_db_session, job.dataset_id)
        rows = await _rows(
            test_db_session, dataset, "SELECT ST_NDims(geom), ST_AsText(geom) FROM {t}"
        )
        assert sorted(tuple(r) for r in rows) == [
            (2, "POINT(1 1)"),
            (2, "POINT(2 2)"),
            (2, "POINT(3 3)"),
        ]
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_a_busy_table_that_keeps_its_dimensions_keeps_z(
    client: AsyncClient, editor_auth_header, configured, test_db_session, monkeypatch
):
    name = await _spatial_table("b", ["POINT (1 1 10.5)", "POINT (2 2 20.25)"])
    try:
        _probe_then(
            monkeypatch, after_first=partial(_insert, name, ["POINT (3 3 7)"], start=3)
        )
        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        assert _warnings(job) == []
        dataset = await _dataset(test_db_session, job.dataset_id)
        rows = await _rows(test_db_session, dataset, "SELECT ST_AsText(geom) FROM {t}")
        assert sorted(wkt for (wkt,) in rows) == [
            "POINT Z (1 1 10.5)",
            "POINT Z (2 2 20.25)",
            "POINT Z (3 3 7)",
        ]
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_a_2d_copy_of_an_xyz_table_gains_z_at_its_next_refresh(
    client: AsyncClient, editor_auth_header, configured, test_db_session, monkeypatch
):
    from app.platform.database_sources import TableDimensions

    name = await _spatial_table("g", ["POINT (1 1 10.5)", "POINT (2 2 20.25)"])
    try:
        with monkeypatch.context() as before_the_fix:
            before_the_fix.setattr(
                database_import,
                "probe_table_dimensions",
                AsyncMock(return_value=TableDimensions(2, 0, 0, 0, 0)),
            )
            kwargs = await _import(client, editor_auth_header, name)
        dataset_id = (await _job(test_db_session, kwargs["job_id"])).dataset_id
        assert (await _dataset(test_db_session, dataset_id)).is_3d is False

        run = await _refresh(client, editor_auth_header, test_db_session, dataset_id)

        assert run.status == "succeeded", run.error_message
        assert run.verification["review_reasons"] == []
        dataset = await _dataset(test_db_session, dataset_id)
        assert (dataset.geometry_type, dataset.is_3d) == ("POINT", True)
        rows = await _rows(test_db_session, dataset, "SELECT ST_AsText(geom) FROM {t}")
        assert sorted(wkt for (wkt,) in rows) == [
            "POINT Z (1 1 10.5)",
            "POINT Z (2 2 20.25)",
        ]
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_a_refresh_that_reads_mixed_dimensions_warns_on_its_job(
    client: AsyncClient, editor_auth_header, configured, test_db_session
):
    name = await _spatial_table("m", ["POINT (1 1 10.5)", "POINT (2 2 20.25)"])
    try:
        kwargs = await _import(client, editor_auth_header, name)
        dataset_id = (await _job(test_db_session, kwargs["job_id"])).dataset_id
        await _insert(name, ["POINT (3 3)"], start=3)

        run = await _refresh(client, editor_auth_header, test_db_session, dataset_id)

        assert run.status == "blocked"
        assert "coordinate_dimension_reduced" in run.verification["review_reasons"]
        job = await _job(test_db_session, run.ingest_job_id)
        assert _warnings(job) == [{"kind": "zm_dropped", "details": {"features": 2}}]
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_z_cleared_at_the_source_after_the_copy_still_warns(
    client: AsyncClient, editor_auth_header, configured, test_db_session, monkeypatch
):
    name = await _spatial_table("c", ["POINT (1 1 10.5)", "POINT (2 2 20.25)"])
    try:
        _probe_then(
            monkeypatch,
            before_second=partial(
                _admin,
                f"UPDATE dbo.{name} SET g = geometry::STGeomFromText("
                "'POINT (' + CAST(id AS varchar) + ' ' + CAST(id AS varchar) + ')', 4326)",
            ),
        )
        kwargs = await _import(client, editor_auth_header, name)
        job = await _job(test_db_session, kwargs["job_id"])
        assert job.status == "complete", job.error_message
        assert _warnings(job) == [{"kind": "zm_dropped", "details": {"features": 2}}]
        dataset = await _dataset(test_db_session, job.dataset_id)
        rows = await _rows(test_db_session, dataset, "SELECT ST_AsText(geom) FROM {t}")
        assert sorted(wkt for (wkt,) in rows) == ["POINT(1 1)", "POINT(2 2)"]
    finally:
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


def _curve(template: str, dim: str) -> str:
    ordinates = {"XYZ": "{} {} 5", "XYM": "{} {} NULL 7", "XYZM": "{} {} 5 7"}[dim]
    return template.format(
        arc=", ".join(ordinates.format(x, y) for x, y in [(0, 0), (1, 1), (2, 0)]),
        ring=", ".join(
            ordinates.format(x, y) for x, y in [(0, 0), (1, 1), (2, 0), (1, -1), (0, 0)]
        ),
        seg=", ".join(ordinates.format(x, y) for x, y in [(2, 0), (3, 0)]),
        point=ordinates.format(5, 5),
    )


_ARC = "CIRCULARSTRING ({arc})"
_COMPOUND = "COMPOUNDCURVE (CIRCULARSTRING ({arc}), ({seg}))"
_CURVE_POLYGON = "CURVEPOLYGON (CIRCULARSTRING ({ring}))"
_COLLECTION = "GEOMETRYCOLLECTION (CIRCULARSTRING ({arc}), POINT ({point}))"


@pytest.mark.parametrize(
    ("template", "dim", "kept"),
    [
        (_ARC, "XYZ", True),
        (_ARC, "XYM", False),
        (_ARC, "XYZM", False),
        (_COMPOUND, "XYZ", True),
        (_COMPOUND, "XYM", False),
        (_COMPOUND, "XYZM", False),
        (_CURVE_POLYGON, "XYZ", False),
        (_CURVE_POLYGON, "XYM", False),
        (_CURVE_POLYGON, "XYZM", False),
        (_COLLECTION, "XYZ", True),
        (_COLLECTION, "XYM", True),
        (_COLLECTION, "XYZM", True),
    ],
)
async def test_a_curve_keeps_only_the_ordinates_gdal_carries_through(
    configured, test_db_session, template, dim, kept
):
    """GDAL drops M on linearized arcs and Z and M on curve polygons."""
    name = await _spatial_table("cv", [_curve(template, dim)])
    target = f"{name}_copy"
    try:
        lost = await database_import.copy_database_table(
            "gis",
            schema_name="dbo",
            table_name=name,
            column="g",
            target_schema="data",
            target_table=target,
            srid=4326,
        )
        z, m, dims = (
            await test_db_session.execute(
                text(
                    "SELECT array_agg(DISTINCT ST_Z((p).geom)), "
                    "array_agg(DISTINCT ST_M((p).geom)), "
                    "array_agg(DISTINCT ST_NDims((p).geom)) "
                    f'FROM (SELECT ST_DumpPoints(_geolens_geom) AS p FROM data."{target}") s'
                )
            )
        ).one()
        if kept:
            assert lost == 0
            assert z == ([5.0] if "Z" in dim else [None])
            assert m == ([7.0] if "M" in dim else [None])
        else:
            assert lost == 1
            assert dims == [2]
    finally:
        await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{target}"'))
        await test_db_session.commit()
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")


async def test_an_invalid_curve_polygon_with_z_is_stored_2d(
    configured, test_db_session
):
    """STGeometryType raises on an invalid value, so its WKT names the type."""
    bowtie = "CURVEPOLYGON (CIRCULARSTRING (0 0 1, 2 2 1, 0 2 1, 2 0 1, 0 0 1))"
    name = await _spatial_table(
        "ic", [bowtie, "POLYGON ((0 0 1, 1 0 1, 1 1 1, 0 0 1))"]
    )
    target = f"{name}_copy"
    try:
        lost = await database_import.copy_database_table(
            "gis",
            schema_name="dbo",
            table_name=name,
            column="g",
            target_schema="data",
            target_table=target,
            srid=4326,
        )
        dims = await test_db_session.scalar(
            text(
                f'SELECT array_agg(DISTINCT ST_NDims(_geolens_geom)) FROM data."{target}"'
            )
        )
        assert (lost, dims) == (2, [2])
    finally:
        await test_db_session.execute(text(f'DROP TABLE IF EXISTS data."{target}"'))
        await test_db_session.commit()
        await _admin(f"DROP TABLE IF EXISTS dbo.{name}")
