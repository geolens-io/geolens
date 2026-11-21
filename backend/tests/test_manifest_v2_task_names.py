"""Manifest version 2 creates are queued under names earlier workers lack."""

from __future__ import annotations

import uuid
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import Request
from sqlalchemy import select

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.service import queue_ingest_job
from app.processing.ingest.tasks import (
    ingest_file,
    ingest_manifest_v2_file,
    ingest_manifest_v2_raster,
    ingest_raster,
)
from tests.test_admin_dataset_list_after_publish import (  # noqa: F401
    _fake_ogr2ogr,
    job_ids,
    store,
)

pytestmark = pytest.mark.anyio

_VECTOR = "tests/fixtures/ingest/basic_attrs.geojson"
_RASTER = "rasters/task-name-raster.tif"


def _stage(tmp_path) -> None:
    vector = Path(settings.upload_staging_dir) / _VECTOR
    vector.parent.mkdir(parents=True, exist_ok=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", vector)
    raster = Path(settings.upload_staging_dir) / _RASTER
    raster.parent.mkdir(parents=True, exist_ok=True)
    raster.write_bytes(b"routing-only-cog")


def _request(key: str, version: str, source_type: str) -> ManifestApplyRequest:
    uri = _VECTOR if source_type == "vector" else _RASTER
    body = {
        "manifest_version": version,
        "catalog": {"title": "Task names"},
        "datasets": [
            {
                "key": key,
                "title": "Task names",
                "sources": [{"type": source_type, "uri": uri}],
                "metadata": {"crs": "EPSG:4326"},
                "publication": {"intent": "published"},
            }
        ],
    }
    if version == "2":
        body["client"] = {"id": "geolens-qgis", "version": "0.2.0"}
    return ManifestApplyRequest.model_validate(body)


def _http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ingest/manifest/apply",
            "headers": [],
        }
    )


def _task_name(deferred) -> str:
    """A task, or the deferrer a queue-configured task returns."""
    return getattr(deferred, "name", None) or deferred.job.task_name


async def _admin(session) -> User:
    return (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()


async def _create(session, key, version, source_type) -> tuple[AsyncMock, uuid.UUID]:
    defer = AsyncMock()
    with (
        patch("app.processing.ingest.service.defer_async_with_tenant", new=defer),
        patch(
            "app.processing.ingest.manifest_service._manifest_source_size_bytes",
            new=AsyncMock(return_value=1024),
        ),
    ):
        response = await apply_manifest(
            session,
            _request(key, version, source_type),
            await _admin(session),
            _http_request(),
        )
    result = response.results[0]
    assert result.action == "create", result
    return defer, result.job_id


def test_the_v2_create_names_run_the_same_bodies() -> None:
    assert ingest_manifest_v2_file.func is ingest_file.func
    assert ingest_manifest_v2_raster.func is ingest_raster.func
    assert ingest_manifest_v2_file.name == "app.ingest.tasks.ingest_manifest_v2_file"
    assert (
        ingest_manifest_v2_raster.name == "app.ingest.tasks.ingest_manifest_v2_raster"
    )


@pytest.mark.parametrize(
    "version,source_type,name",
    [
        ("2", "vector", "app.ingest.tasks.ingest_manifest_v2_file"),
        ("2", "raster_cog", "app.ingest.tasks.ingest_manifest_v2_raster"),
        ("1", "vector", ingest_file.name),
        ("1", "raster_cog", ingest_raster.name),
    ],
    ids=["v2-vector", "v2-raster", "v1-vector", "v1-raster"],
)
async def test_a_manifest_create_is_queued_under_its_versions_name(
    test_db_session, clean_tables, tmp_path, version, source_type, name
):
    _stage(tmp_path)
    defer, _ = await _create(
        test_db_session,
        f"task-name-{version}-{source_type.replace('_', '-')}",
        version,
        source_type,
    )

    defer.assert_awaited_once()
    assert _task_name(defer.await_args.args[0]) == name


async def test_a_plain_upload_keeps_the_original_name(test_db_session, tmp_path):
    source = tmp_path / "points.geojson"
    source.write_bytes(b"{}")
    admin = await _admin(test_db_session)
    job = IngestJob(
        source_filename="points.geojson",
        file_path=str(source),
        created_by=admin.id,
        status="pending",
        user_metadata={"title": "Plain"},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    defer = AsyncMock()
    try:
        with patch("app.processing.ingest.service.defer_async_with_tenant", new=defer):
            await queue_ingest_job(job, str(admin.id), db=test_db_session)
        assert _task_name(defer.await_args.args[0]) == ingest_file.name
    finally:
        await test_db_session.delete(job)
        await test_db_session.commit()


async def test_a_v2_create_completes_through_its_name(
    test_db_session,
    clean_tables,
    tmp_path,
    store,  # noqa: F811
    job_ids,  # noqa: F811
):
    _stage(tmp_path)
    defer, job_id = await _create(test_db_session, "task-name-runs", "2", "vector")
    job_ids.append(job_id)
    kwargs = defer.await_args.kwargs
    ogrinfo = {
        "srid": 4326,
        "geometry_type": "Point",
        "columns": [{"name": "name", "type": "String"}],
    }
    with (
        patch(
            "app.processing.ingest.service.resolve_file_path",
            AsyncMock(side_effect=lambda path, job_id: path),
        ),
        patch("app.processing.ingest.ogr.run_ogrinfo", AsyncMock(return_value=ogrinfo)),
        patch("app.processing.ingest.ogr.run_ogr2ogr", new=_fake_ogr2ogr),
        patch("app.processing.ingest.metadata.grant_reader_access", AsyncMock()),
        patch(
            "app.processing.ingest.publish_followups.invalidate_catalog_cache",
            AsyncMock(),
        ),
        patch("app.processing.embeddings.helpers.defer_embedding", AsyncMock()),
    ):
        await ingest_manifest_v2_file.func(**kwargs)

    test_db_session.expire_all()
    job = await test_db_session.get(IngestJob, job_id)
    assert (job.status, job.error_message) == ("complete", None)
    dataset = await test_db_session.get(Dataset, job.dataset_id)
    await test_db_session.refresh(dataset, ["record"])
    assert dataset.record.visibility == "private"
