"""ArcGIS fields GDAL loads as text are cast to the types Esri declares."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.platform.jobs.models import IngestJob
from app.processing.ingest import tasks_vector
from app.processing.ingest.tasks_reupload import reupload_service

from tests.factories import get_user_id
from tests.test_service_reupload_3d import _BASE, _dispatch_harness

pytestmark = pytest.mark.anyio

_META = {
    "fields": [
        {"name": "OBJECTID", "type": "esriFieldTypeOID"},
        {"name": "Big", "type": "esriFieldTypeBigInteger"},
        {"name": "Day", "type": "esriFieldTypeDateOnly"},
        {"name": "Clock", "type": "esriFieldTypeTimeOnly"},
        {"name": "Stamp", "type": "esriFieldTypeTimestampOffset"},
        {"name": "Iso_Day", "type": "esriFieldTypeDateOnly"},
        {"name": "Note", "type": "esriFieldTypeString"},
        {"name": "FID", "type": "esriFieldTypeBigInteger"},
    ]
}
_COLUMNS = "big", "day", "clock", "stamp", "iso_day", "note", "fid"
# Strings as the ESRIJSON driver hands them over: it types none of the four.
_ROW = (
    "9007199254740993",
    "1700000000000",
    "13:45:30",
    "2024-03-05T10:20:30.000+02:00",
    "2024-03-05",
    "12",
    "42",
)


def _fake_fetch():
    async def _fetch(
        gdal_source, layer_name, table_name, db_conn_str, service_type, **kw
    ):
        if kw.get("on_spawn") is not None:
            kw["on_spawn"]()
        from app.core.db import async_session

        target = f'"{kw["schema"]}"."{table_name}"'
        fields = "".join(f"{c} character varying, " for c in _COLUMNS)
        async with async_session() as session:
            await session.execute(text(f"DROP TABLE IF EXISTS {target}"))
            await session.execute(
                text(
                    f"CREATE TABLE {target} (gid serial PRIMARY KEY, {fields}"
                    "geom geometry(Point, 4326))"
                )
            )
            await session.execute(
                text(
                    f"INSERT INTO {target} ({', '.join(_COLUMNS)}, geom) VALUES "
                    f"({', '.join(f':{c}' for c in _COLUMNS)}, "
                    "ST_GeomFromText('POINT (1 2)', 4326))"
                ),
                dict(zip(_COLUMNS, _ROW, strict=True)),
            )
            await session.commit()

    return _fetch


@contextmanager
def _source(monkeypatch):
    async def _page_info(source_url, layer_id, token, **_):
        return 1, 1000, False, None

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _page_info)
    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        patch("app.processing.ingest.ogr.run_ogr2ogr_service", new=_fake_fetch()),
        patch(
            "app.modules.catalog.sources.adapters.arcgis.fetch_arcgis_layer_meta",
            new=AsyncMock(return_value=_META),
        ),
    ):
        yield


async def _assert_typed(session, dataset_id) -> None:
    table = await session.scalar(
        text("SELECT table_name FROM catalog.datasets WHERE id = :i"),
        {"i": dataset_id},
    )
    types = dict(
        (
            await session.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = :t"
                ),
                {"t": table},
            )
        ).all()
    )
    stored = [("src_" + c if c == "fid" else c) for c in _COLUMNS]
    assert {c: types[c] for c in stored} == {
        "big": "bigint",
        "day": "date",
        "clock": "time without time zone",
        "stamp": "timestamp with time zone",
        "iso_day": "date",
        "note": "character varying",
        "src_fid": "bigint",
    }
    row = (
        await session.execute(
            text(
                "SELECT big, day::text, clock::text, stamp AT TIME ZONE 'UTC', "
                'iso_day::text FROM data."' + table + '"'
            )
        )
    ).one()
    assert row[0] == 9007199254740993
    assert row[1:3] == ("2023-11-14", "13:45:30")
    assert str(row[3]) == "2024-03-05 08:20:30"
    assert row[4] == "2024-03-05"


async def _ingest(session, monkeypatch) -> uuid.UUID:
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        source_filename="Wells",
        source_url=_BASE,
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "title": f"Wells {uuid.uuid4().hex[:8]}",
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "geometry_type": "Point",
        },
    )
    session.add(job)
    await session.commit()
    with _source(monkeypatch):
        await tasks_vector.ingest_service.func(
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            source_url=_BASE,
            source_layer="0",
            user_id=str(admin_id),
        )
    await session.refresh(job)
    assert job.status == "complete", job.error_message
    return job.dataset_id


async def test_an_imported_layer_stores_newer_esri_types_as_native_types(
    test_db_session, monkeypatch
):
    dataset_id = await _ingest(test_db_session, monkeypatch)
    await _assert_typed(test_db_session, dataset_id)


async def test_a_refresh_stores_newer_esri_types_as_native_types(
    client, admin_auth_header, test_db_session, monkeypatch
):
    dataset_id = await _ingest(test_db_session, monkeypatch)
    async with _dispatch_harness() as task:
        response = await client.post(
            f"/datasets/{dataset_id}/refresh", json={}, headers=admin_auth_header
        )
    assert response.status_code == 202, response.text
    with _source(monkeypatch):
        await reupload_service.func(**task.defer_async.call_args.kwargs)
    await _assert_typed(test_db_session, dataset_id)
