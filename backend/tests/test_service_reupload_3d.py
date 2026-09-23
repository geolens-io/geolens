"""Service re-upload and refresh derive the 3D facts first ingest derives."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.processing.ingest import tasks_vector
from app.processing.ingest.metadata import compute_table_content_digest
from app.processing.ingest.tasks_reupload import reupload_service

from tests.factories import get_user_id
from tests.test_refresh_gate_1269 import _dispatch_harness, _runs_ordered

pytestmark = pytest.mark.anyio

_BASE = "https://services.example.com/arcgis/rest/services/Wells/FeatureServer"
_WELLS = [(-73.9, 40.7, 100.0), (-74.0, 40.8, 200.0), (-73.8, 40.6, 300.0)]
_FLAT_WELLS = [(x, y, None) for x, y, _ in _WELLS]


def _fake_fetch(points):
    """Land ``points`` in the target table the way ogr2ogr lands a point layer."""

    async def _fetch(
        gdal_source, layer_name, table_name, db_conn_str, service_type, **kw
    ):
        if kw.get("on_spawn") is not None:
            kw["on_spawn"]()
        from app.core.db import async_session

        target = f'"{kw["schema"]}"."{table_name}"'
        geometry = "Point" if points[0][2] is None else "PointZ"
        async with async_session() as session:
            await session.execute(text(f"DROP TABLE IF EXISTS {target}"))
            await session.execute(
                text(
                    f"CREATE TABLE {target} (gid serial PRIMARY KEY, name text, "
                    f"geom geometry({geometry}, 4326))"
                )
            )
            for index, (x, y, z) in enumerate(points):
                wkt = f"POINT ({x} {y})" if z is None else f"POINT Z ({x} {y} {z})"
                await session.execute(
                    text(
                        f"INSERT INTO {target} (name, geom) "
                        "VALUES (:name, ST_GeomFromText(:wkt, 4326))"
                    ),
                    {"name": f"well {index}", "wkt": wkt},
                )
            await session.commit()

    return _fetch


@contextmanager
def _source(monkeypatch, points):
    """Serve ``points`` as the ArcGIS layer for every fetch inside the block."""

    async def _page_info(source_url, layer_id, token):
        return len(points), 1000, False, None

    monkeypatch.setattr(tasks_vector, "_fetch_arcgis_import_page_info", _page_info)
    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        patch("app.processing.ingest.ogr.run_ogr2ogr_service", new=_fake_fetch(points)),
    ):
        yield


async def _ingest(session, monkeypatch, points) -> uuid.UUID:
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
    with _source(monkeypatch, points):
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


async def _refresh(client, headers, monkeypatch, dataset_id, points) -> None:
    async with _dispatch_harness() as task:
        response = await client.post(
            f"/datasets/{dataset_id}/refresh", json={}, headers=headers
        )
    assert response.status_code == 202, response.text
    with _source(monkeypatch, points):
        await reupload_service.func(**task.defer_async.call_args.kwargs)


async def _reupload(session, monkeypatch, dataset_id, points) -> None:
    admin_id = await get_user_id(session, "admin")
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename="Wells",
        source_url=_BASE,
        source_layer="0",
        created_by=admin_id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "ArcGIS FeatureServer",
            "layer_id": "0",
            "source_type": "service_url",
        },
    )
    session.add(job)
    await session.commit()
    with _source(monkeypatch, points):
        await reupload_service.func(
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            dataset_id=str(dataset_id),
            source_url=_BASE,
            source_layer="0",
            user_id=str(admin_id),
        )
    await session.refresh(job)
    assert job.status == "complete", job.error_message


async def _dataset(session, dataset_id) -> Dataset:
    session.expire_all()
    return await session.get(Dataset, dataset_id)


def _three_d(dataset: Dataset) -> tuple:
    return dataset.is_3d, dataset.n_dims, dataset.z_min, dataset.z_max


async def _live_columns(session, table_name: str) -> list[str]:
    result = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'data' AND table_name = :table"
        ),
        {"table": table_name},
    )
    return list(result.scalars())


async def _elev(session, table_name: str) -> list[float]:
    result = await session.execute(
        text(f'SELECT elev FROM data."{table_name}" ORDER BY elev')
    )
    return list(result.scalars())


async def test_a_3d_point_refresh_keeps_elev_and_updates_the_z_range(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """A 3D point refresh keeps ``elev`` and records the new z range."""
    dataset_id = await _ingest(test_db_session, monkeypatch, _WELLS)
    raised = [(x, y, z + 50) for x, y, z in _WELLS]

    await _refresh(client, admin_auth_header, monkeypatch, dataset_id, raised)

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.status == "succeeded", run.verification
    dataset = await _dataset(test_db_session, dataset_id)
    assert _three_d(dataset) == (True, 3, 150.0, 350.0)
    assert "elev" in [column["name"] for column in dataset.column_info]
    assert sorted(dataset.sample_values["elev"]) == ["150", "250", "350"]
    assert await _elev(test_db_session, dataset.table_name) == [150.0, 250.0, 350.0]


async def test_an_unchanged_3d_point_source_refreshes_without_a_reported_change(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """Refreshing an unchanged 3D point source reports no schema or content change."""
    dataset_id = await _ingest(test_db_session, monkeypatch, _WELLS)

    for _ in range(2):
        await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _WELLS)

    runs = await _runs_ordered(test_db_session, dataset_id)
    assert [run.status for run in runs] == ["succeeded", "succeeded"]
    for run in runs:
        diff = run.schema_diff
        assert not (diff["columns_added"] or diff["columns_removed"]), diff
    digests = {run.verification["content_digest"] for run in runs}
    dataset = await _dataset(test_db_session, dataset_id)
    assert dataset.schema_drift_status == "none"
    published = await compute_table_content_digest(
        test_db_session, dataset.table_name, schema="data", has_geometry=True
    )
    await test_db_session.rollback()
    assert digests == {published}


async def test_a_2d_layer_that_gains_z_values_becomes_3d(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """A refresh that brings Z values sets ``is_3d`` and adds ``elev``."""
    dataset_id = await _ingest(test_db_session, monkeypatch, _FLAT_WELLS)
    flat = await _dataset(test_db_session, dataset_id)
    assert _three_d(flat) == (False, 2, None, None)

    await _refresh(client, admin_auth_header, monkeypatch, dataset_id, _WELLS)

    [run] = await _runs_ordered(test_db_session, dataset_id)
    assert run.status == "succeeded", run.verification
    dataset = await _dataset(test_db_session, dataset_id)
    assert _three_d(dataset) == (True, 3, 100.0, 300.0)
    assert await _elev(test_db_session, dataset.table_name) == [100.0, 200.0, 300.0]


async def test_a_3d_layer_that_loses_z_values_is_no_longer_3d(
    client: AsyncClient, test_db_session, monkeypatch
):
    """A re-upload without Z values clears the 3D facts."""
    dataset_id = await _ingest(test_db_session, monkeypatch, _WELLS)

    await _reupload(test_db_session, monkeypatch, dataset_id, _FLAT_WELLS)

    dataset = await _dataset(test_db_session, dataset_id)
    assert _three_d(dataset) == (False, 2, None, None)
    assert "elev" not in await _live_columns(test_db_session, dataset.table_name)
