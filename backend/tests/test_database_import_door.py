"""POST /services/databases/{connection}/imports/ and the job it queues."""

from __future__ import annotations

import secrets
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import structlog
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.config_database_sources import DatabaseConnection
from app.modules.catalog.sources import database_router
from app.platform.database_sources import (
    DatabaseConnectError,
    TableGeometry,
    SpatialTable,
    SpatialTableListing,
)
from app.platform.dataset_origin import KEEP, SourceBinding, restamp
from app.platform.jobs.models import IngestJob
from app.processing.ingest import database_import
from app.processing.ingest import service as ingest_service
from app.processing.ingest import tasks_database
from app.processing.ingest.tasks_database import ingest_database
from tests.factories import create_dataset

pytestmark = pytest.mark.anyio

HOST = "gis-sql.corp.example"
USERNAME = "geolens_reader"
PASSWORD = secrets.token_hex(16)
URL = "/services/databases/gis/imports/"


def _connection() -> DatabaseConnection:
    return DatabaseConnection.model_validate(
        {
            "engine": "sqlserver",
            "host": HOST,
            "database": "GIS",
            "username": USERNAME,
            "password": PASSWORD,
        }
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "database_sources", {"gis": _connection()})


def _table(schema: str, table: str, srid: int | None = 2263) -> SpatialTable:
    return SpatialTable(
        schema_name=schema,
        table_name=table,
        object_type="table",
        geometry_column="shape",
        column_type="geometry",
        srid=srid,
    )


@pytest.fixture
def listing(monkeypatch) -> AsyncMock:
    listed = AsyncMock(
        return_value=SpatialTableListing(
            tables=[_table("dbo", "parcels"), _table("gis", "sketch", None)],
            truncated=False,
        )
    )
    monkeypatch.setattr(database_router, "list_spatial_tables", listed)
    return listed


@pytest.fixture
def deferred(monkeypatch) -> AsyncMock:
    defer = AsyncMock()
    monkeypatch.setattr(ingest_service, "defer_async_with_tenant", defer)
    return defer


async def _user_id(client: AsyncClient, headers: dict) -> uuid.UUID:
    return uuid.UUID((await client.get("/auth/me", headers=headers)).json()["id"])


async def _jobs(session, user_id: uuid.UUID) -> list[IngestJob]:
    session.expire_all()
    return list(
        (
            await session.scalars(
                select(IngestJob).where(
                    IngestJob.created_by == user_id,
                    IngestJob.user_metadata.has_key("database_source"),
                )
            )
        ).all()
    )


async def test_queues_a_listed_table_by_name(
    client: AsyncClient,
    editor_auth_header: dict,
    configured,
    listing,
    deferred,
    test_db_session,
):
    resp = await client.post(
        URL,
        json={"schema_name": "gis", "table_name": "sketch", "srid_override": 2263},
        headers=editor_auth_header,
    )

    assert resp.status_code == 202, resp.text
    # The door only needs the catalog; the worker probes the SRID it imports.
    listing.assert_awaited_once_with("gis", probe_srids=False)
    [job] = await _jobs(test_db_session, await _user_id(client, editor_auth_header))
    assert str(job.id) == resp.json()["job_id"]
    assert job.source_url is None and job.file_path is None
    assert job.source_filename == "gis.sketch"
    assert job.user_metadata["database_source"] == {
        "connection": "gis",
        "schema": "gis",
        "table": "sketch",
    }
    assert job.user_metadata["title"] == "sketch"
    assert job.user_metadata["srid_override"] == 2263
    task = deferred.await_args.args[0]
    assert task is ingest_database
    assert set(deferred.await_args.kwargs) == {"job_id", "attempt_id", "user_id"}
    stored = str(job.user_metadata) + resp.text
    for leaked in (HOST, USERNAME, PASSWORD):
        assert leaked not in stored


async def test_no_trailing_slash_alias(
    client: AsyncClient, editor_auth_header, configured, listing, deferred
):
    resp = await client.post(
        URL.rstrip("/"),
        json={"schema_name": "dbo", "table_name": "parcels"},
        headers=editor_auth_header,
    )
    assert resp.status_code == 202, resp.text


@pytest.mark.parametrize(
    ("schema_name", "table_name"),
    [("dbo", "missing"), ("DBO", "parcels"), ("dbo", "parcels ")],
)
async def test_a_table_the_listing_does_not_return_is_refused(
    client: AsyncClient,
    editor_auth_header,
    configured,
    listing,
    deferred,
    test_db_session,
    schema_name,
    table_name,
):
    resp = await client.post(
        URL,
        json={"schema_name": schema_name, "table_name": table_name},
        headers=editor_auth_header,
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["code"] == "database_table_not_listed"
    assert (
        await _jobs(test_db_session, await _user_id(client, editor_auth_header)) == []
    )
    deferred.assert_not_awaited()


async def test_a_name_gdal_could_misread_is_refused_before_listing(
    client: AsyncClient, editor_auth_header, configured, listing, deferred
):
    listing.return_value = SpatialTableListing(
        tables=[_table("dbo", "a.b")], truncated=False
    )
    resp = await client.post(
        URL,
        json={"schema_name": "dbo", "table_name": "a.b"},
        headers=editor_auth_header,
    )
    assert resp.status_code == 404
    listing.assert_not_awaited()


async def test_second_import_by_the_same_user_is_a_duplicate(
    client: AsyncClient,
    editor_auth_header,
    admin_auth_header,
    configured,
    listing,
    deferred,
    test_db_session,
):
    editor_id = await _user_id(client, editor_auth_header)
    dataset = await create_dataset(
        test_db_session,
        created_by=editor_id,
        name="Parcels",
        source_format="database",
    )
    restamp(
        dataset,
        SourceBinding.database("gis", schema="dbo", table="parcels"),
        contacted_at=None,
        refreshed_at=KEEP,
    )
    await test_db_session.commit()
    body = {"schema_name": "dbo", "table_name": "parcels"}

    resp = await client.post(URL, json=body, headers=editor_auth_header)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "duplicate_source"
    assert detail["existing_dataset_id"] == str(dataset.id)
    assert detail["existing_title"] == "Parcels"
    listing.assert_not_awaited()

    other = await client.post(URL, json=body, headers=admin_auth_header)
    assert other.status_code == 202, other.text


async def test_unknown_connection_is_404(
    client: AsyncClient, editor_auth_header, configured, listing, deferred
):
    resp = await client.post(
        "/services/databases/other/imports/",
        json={"schema_name": "dbo", "table_name": "parcels"},
        headers=editor_auth_header,
    )
    assert resp.status_code == 404
    listing.assert_not_awaited()


async def test_requires_create_layers(
    client: AsyncClient, viewer_auth_header, configured, listing, deferred
):
    resp = await client.post(
        URL,
        json={"schema_name": "dbo", "table_name": "parcels"},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403
    listing.assert_not_awaited()


async def test_listing_failure_is_502_naming_only_the_connection(
    client: AsyncClient, editor_auth_header, configured, listing, deferred
):
    listing.side_effect = DatabaseConnectError("gis")
    resp = await client.post(
        URL,
        json={"schema_name": "dbo", "table_name": "parcels"},
        headers=editor_auth_header,
    )
    assert resp.status_code == 502
    assert "'gis'" in resp.json()["detail"]
    deferred.assert_not_awaited()


async def test_unknown_epsg_override_is_422(
    client: AsyncClient, editor_auth_header, configured, listing, deferred
):
    resp = await client.post(
        URL,
        json={"schema_name": "gis", "table_name": "sketch", "srid_override": 998998},
        headers=editor_auth_header,
    )
    assert resp.status_code == 422
    listing.assert_not_awaited()


async def test_a_user_at_quota_is_refused(
    client: AsyncClient,
    editor_auth_header,
    configured,
    listing,
    deferred,
    test_db_session,
):
    editor_id = await _user_id(client, editor_auth_header)
    await create_dataset(test_db_session, created_by=editor_id)
    await test_db_session.commit()
    with patch(
        "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
        new_callable=AsyncMock,
        return_value=1,
    ):
        resp = await client.post(
            URL,
            json={"schema_name": "dbo", "table_name": "parcels"},
            headers=editor_auth_header,
        )
    assert resp.status_code == 422, resp.text
    assert "quota" in resp.json()["detail"].lower()
    listing.assert_not_awaited()
    assert (
        await _jobs(test_db_session, await _user_id(client, editor_auth_header)) == []
    )


async def test_retry_of_a_failed_import_routes_to_the_database_task(
    client: AsyncClient,
    editor_auth_header,
    configured,
    listing,
    deferred,
    test_db_session,
):
    resp = await client.post(
        URL,
        json={"schema_name": "dbo", "table_name": "parcels"},
        headers=editor_auth_header,
    )
    assert resp.status_code == 202
    [job] = await _jobs(test_db_session, await _user_id(client, editor_auth_header))
    job.status = "failed"
    await test_db_session.commit()
    deferred.reset_mock()

    retried = await client.post(f"/jobs/{job.id}/retry", headers=editor_auth_header)

    assert retried.status_code == 202, retried.text
    assert deferred.await_args.args[0] is ingest_database
    assert deferred.await_args.kwargs["job_id"] == str(job.id)


class _Proc:
    def __init__(self, stderr: bytes = b"", returncode: int = 0):
        self._stderr = stderr
        self._returncode = returncode
        self.returncode = None

    async def communicate(self):
        self.returncode = self._returncode
        return b"", self._stderr


async def test_copy_names_the_table_as_a_layer_and_keeps_the_login_off_argv(
    monkeypatch,
):
    monkeypatch.setattr(settings, "database_sources", {"gis": _connection()})
    monkeypatch.setenv("CPL_DEBUG", "ON")
    spawned: list[tuple[tuple, dict]] = []

    async def _spawn(*argv, **kwargs):
        spawned.append((argv, kwargs))
        return _Proc()

    monkeypatch.setattr(database_import.asyncio, "create_subprocess_exec", _spawn)

    await database_import.copy_database_table(
        "gis",
        schema_name="dbo",
        table_name="parcels",
        target_schema="data",
        target_table="parcels_copy",
        srid=2263,
    )

    [(argv, kwargs)] = spawned
    assert argv[:3] == ("ogr2ogr", "-if", "MSSQLSpatial")
    assert argv[-1] == "dbo.parcels"
    assert "EPSG:2263" in argv
    assert "MSSQLSPATIAL_SHOW_FID_COLUMN" in argv
    source = next(a for a in argv if a.startswith("MSSQL:"))
    assert source == "MSSQL:Driver=FreeTDS;Servername=geolens;Database=GIS"
    joined = " ".join(argv)
    for leaked in (HOST, USERNAME, PASSWORD):
        assert leaked not in joined
    env = kwargs["env"]
    assert env["MSSQLSPATIAL_PWD"] == PASSWORD
    assert env["CPL_DEBUG"] == "OFF"
    assert "MSSQLSpatial" not in env["GDAL_SKIP"].split()


@pytest.mark.parametrize(
    ("stderr", "message"),
    [
        (
            "ERROR 1: Unable to initialize connection to the server for MSSQL:x",
            "Couldn't connect or sign in to the database connection 'gis'.",
        ),
        (
            "ERROR 1: Couldn't fetch requested layer 'dbo.parcels'!",
            "A table in the database connection 'gis' was not found or is not "
            "readable.",
        ),
        (
            "ERROR 1: COPY statement failed.",
            "Copying the table from the database connection 'gis' failed.",
        ),
    ],
)
async def test_copy_failures_name_only_the_connection(monkeypatch, stderr, message):
    monkeypatch.setattr(settings, "database_sources", {"gis": _connection()})

    async def _spawn(*argv, **kwargs):
        leak = f"ODBC: SQLDriverConnect(Server={HOST};UID={USERNAME};PWD={PASSWORD})\n"
        return _Proc(stderr=(leak + stderr).encode(), returncode=1)

    monkeypatch.setattr(database_import.asyncio, "create_subprocess_exec", _spawn)

    with pytest.raises(database_import.DatabaseImportError) as raised:
        await database_import.copy_database_table(
            "gis",
            schema_name="dbo",
            table_name="parcels",
            target_schema="data",
            target_table="parcels_copy",
            srid=2263,
        )
    assert str(raised.value) == message


@pytest.mark.parametrize(("schema", "table"), [("dbo", "a.b"), ("-x", "t")])
async def test_copy_refuses_a_stored_name_gdal_could_misread(
    monkeypatch, schema, table
):
    monkeypatch.setattr(settings, "database_sources", {"gis": _connection()})
    spawn = AsyncMock()
    monkeypatch.setattr(database_import.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(database_import.DatabaseImportError):
        await database_import.copy_database_table(
            "gis",
            schema_name=schema,
            table_name=table,
            target_schema="data",
            target_table="t",
            srid=4326,
        )
    spawn.assert_not_awaited()


@pytest.mark.parametrize(
    ("probed", "fallback", "chosen"),
    [(2263, 3857, 2263), (None, 3857, 3857), (None, None, None)],
    ids=["table-srid-wins", "fallback-when-none", "neither"],
)
def test_the_table_srid_wins_over_an_override_or_the_stored_srid(
    probed, fallback, chosen
):
    from app.processing.ingest.tasks_database import chosen_srid

    assert chosen_srid(probed, fallback) == chosen


@pytest.mark.requires_ogr2ogr
async def test_a_multi_word_postgis_password_never_reaches_the_log_or_the_job(
    client: AsyncClient,
    editor_auth_header,
    configured,
    listing,
    deferred,
    test_db_session,
    monkeypatch,
):
    tail = f"pw-{uuid.uuid4().hex}"
    echo = (
        "ERROR 1: Unable to open datasource `PG:host=db dbname=geolens "
        f"user=geolens password='*** {tail}'' with the following drivers.\n"
    )

    async def _spawn(*argv, **kwargs):
        return _Proc(stderr=echo.encode(), returncode=1)

    monkeypatch.setattr(database_import.asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr(
        tasks_database,
        "probe_table_geometry",
        AsyncMock(return_value=TableGeometry(column="shape", srid=2263)),
    )
    resp = await client.post(
        URL,
        json={"schema_name": "dbo", "table_name": "parcels"},
        headers=editor_auth_header,
    )
    assert resp.status_code == 202, resp.text

    with structlog.testing.capture_logs() as logs:
        with pytest.raises(database_import.DatabaseImportError) as raised:
            await tasks_database.ingest_database.func(**deferred.await_args.kwargs)

    [job] = await _jobs(test_db_session, await _user_id(client, editor_auth_header))
    assert job.status == "failed"
    assert any(log["event"] == "database import failed" for log in logs)
    for text in (repr(logs), str(raised.value), job.error_message or ""):
        assert tail not in text
