"""Both re-upload workers refuse a replacement that would strip geometry (#2031)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.platform.jobs.models import IngestJob
from app.processing.ingest.ogr import IngestionError
from app.processing.ingest.tasks import reupload_file, reupload_service

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _seed(
    session,
    *,
    record_type: str,
    geometry_type: str | None = "MULTIPOINT",
    service: bool = False,
):
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        name=f"Geometry loss {record_type} {'service' if service else 'file'}",
        record_type=record_type,
        geometry_type=geometry_type,
        feature_count=100,
        source_format="wfs" if service else "geojson",
        source_filename="original.geojson",
        column_info=[{"name": "name", "type": "character varying"}],
    )
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="attributes.csv",
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    if service:
        job.source_url = "https://services.example.com/wfs"
        job.source_layer = "attribute_table"
        job.user_metadata = {
            **job.user_metadata,
            "service_type": "WFS 2.0.0",
            "layer_id": None,
            "source_type": "service_url",
        }
    else:
        job.file_path = "/tmp/fake-2031.csv"
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return admin_id, dataset, job


def _patched_file_pipeline(*, geometry_type: str | None):
    """ogrinfo's verdict on the replacement, with the I/O before it stubbed."""
    return (
        patch(
            "app.processing.ingest.service.resolve_file_path",
            new=AsyncMock(side_effect=lambda path, job_id: path),
        ),
        patch(
            "app.processing.ingest.tasks_reupload._validate_upload_file_safety",
            new=AsyncMock(),
        ),
        patch(
            "app.processing.ingest.ogr.run_ogrinfo",
            new=AsyncMock(
                return_value={
                    "srid": 4326,
                    "geometry_type": geometry_type,
                    "layer_name": "attributes",
                    "feature_count": 12,
                    "columns": [{"name": "name", "type": "String"}],
                }
            ),
        ),
        patch("app.processing.ingest.ogr.run_ogr2ogr", new=AsyncMock()),
    )


async def test_file_worker_refuses_to_de_spatialize_a_vector_dataset(
    client: AsyncClient, test_db_session
):
    admin_id, dataset, job = await _seed(test_db_session, record_type="vector_dataset")
    resolve, validate, ogrinfo, ogr2ogr = _patched_file_pipeline(geometry_type=None)

    with resolve, validate, ogrinfo, ogr2ogr as mock_load:
        with pytest.raises(IngestionError, match="no geometry"):
            await reupload_file(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                file_path=job.file_path or "",
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

    mock_load.assert_not_awaited()
    await test_db_session.refresh(job)
    await test_db_session.refresh(dataset)
    assert job.status == "failed"
    assert "no geometry" in (job.error_message or "")
    assert dataset.record.record_type == "vector_dataset"
    assert dataset.geometry_type == "MULTIPOINT"


@pytest.mark.parametrize(
    "record_type,geometry_type",
    [("table", "MULTIPOINT"), ("vector_dataset", None)],
    ids=["table", "vector_dataset_that_never_measured_geometry"],
)
async def test_file_worker_allows_a_replacement_that_loses_nothing(
    client: AsyncClient, test_db_session, record_type: str, geometry_type: str | None
):
    """Neither dataset has geometry recorded, so neither can lose any."""
    admin_id, dataset, job = await _seed(
        test_db_session, record_type=record_type, geometry_type=geometry_type
    )
    resolve, validate, ogrinfo, ogr2ogr = _patched_file_pipeline(geometry_type=None)

    with resolve, validate, ogrinfo, ogr2ogr as mock_load:
        with pytest.raises(Exception) as exc_info:
            await reupload_file(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                file_path=job.file_path or "",
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

    # The staging load ran, so the gate let this through.
    mock_load.assert_awaited_once()
    assert "no geometry" not in str(exc_info.value)


async def test_service_worker_refuses_to_de_spatialize_a_vector_dataset(
    client: AsyncClient, test_db_session
):
    """fix(#2031 review): this path reads geometry off the staging table."""
    admin_id, dataset, job = await _seed(
        test_db_session, record_type="vector_dataset", service=True
    )
    original_table_name = dataset.table_name
    original_version = dataset.current_version

    async def _fake_service_import(
        gdal_source: str,
        layer_name: str,
        table_name: str,
        db_conn_str: str,
        service_type: str,
        timeout: float = 1800.0,
        token: str | None = None,
        is_non_spatial: bool = False,
        append: bool = False,
        *,
        schema: str,
        on_spawn=None,
    ) -> None:
        """Land the attribute table the service actually served: no geometry."""
        if on_spawn is not None:
            on_spawn()
        import app.core.db as db_module

        async with db_module.async_session() as session:
            await session.execute(
                text(
                    f'CREATE TABLE "{schema}"."{table_name}" '
                    "(gid serial PRIMARY KEY, name text)"
                )
            )
            await session.commit()

    with (
        patch("app.platform.security.validate_url_for_ssrf", new=AsyncMock()),
        patch(
            "app.modules.catalog.sources.preview.build_gdal_source",
            return_value=("WFS:https://services.example.com/wfs", "attribute_table"),
        ),
        patch(
            "app.processing.ingest.ogr.run_ogr2ogr_service",
            new=AsyncMock(side_effect=_fake_service_import),
        ),
    ):
        with pytest.raises(IngestionError, match="no geometry"):
            await reupload_service(
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                dataset_id=str(dataset.id),
                source_url=job.source_url or "",
                source_layer=job.source_layer or "",
                user_id=str(admin_id),
                token=None,
            )

    await test_db_session.refresh(job)
    await test_db_session.refresh(dataset)
    assert job.status == "failed"
    assert "no geometry" in (job.error_message or "")
    assert dataset.record.record_type == "vector_dataset"
    assert dataset.geometry_type == "MULTIPOINT"
    assert dataset.table_name == original_table_name
    assert dataset.current_version == original_version
