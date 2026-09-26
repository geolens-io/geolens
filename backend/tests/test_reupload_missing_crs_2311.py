"""A file re-upload with no detectable CRS carries a stable code (#2311)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.platform.jobs.models import IngestJob
from app.processing.ingest.ogr import IngestionError
from app.processing.ingest.tasks import reupload_file

from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _seed(session, *, srid_override: int | None = None):
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        name="Missing CRS reupload",
        record_type="vector_dataset",
        geometry_type="MULTIPOINT",
        feature_count=10,
        source_format="gpkg",
        source_filename="original.gpkg",
        column_info=[{"name": "name", "type": "character varying"}],
    )
    user_metadata = {"reupload": True, "dataset_id": str(dataset.id)}
    if srid_override is not None:
        user_metadata["srid_override"] = srid_override
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        # Not a GeoJSON/CSV suffix: those assume EPSG:4326 with no CRS
        # declared, which would skip the missing-CRS gate this test exists
        # to exercise (ASSUMES_4326_SUFFIXES in tasks_common.py).
        source_filename="no_crs.gpkg",
        created_by=admin_id,
        user_metadata=user_metadata,
        file_path="/tmp/fake-2311.gpkg",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return admin_id, dataset, job


def _patched_pipeline(*, srid: int | None):
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
                    "srid": srid,
                    "geometry_type": "MULTIPOINT",
                    "layer_name": "no_crs",
                    "feature_count": 10,
                    "columns": [{"name": "name", "type": "String"}],
                }
            ),
        ),
        patch("app.processing.ingest.ogr.run_ogr2ogr", new=AsyncMock()),
    )


async def test_a_reupload_with_no_detectable_crs_stores_its_code(
    client: AsyncClient, test_db_session
):
    admin_id, dataset, job = await _seed(test_db_session)
    resolve, validate, ogrinfo, ogr2ogr = _patched_pipeline(srid=None)

    with resolve, validate, ogrinfo, ogr2ogr as mock_load:
        with pytest.raises(IngestionError, match="Missing CRS"):
            await reupload_file(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                file_path=job.file_path or "",
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

    mock_load.assert_not_awaited()
    await test_db_session.refresh(job)
    assert job.status == "failed"
    # Its own code: this text's SRID-override remedy is not the vector
    # gate's, so `missing_crs`'s translation would drop it.
    assert job.error_code == "missing_crs_reupload"
    assert "Missing CRS" in (job.error_message or "")
    assert "SRID override" in (job.error_message or "")


async def test_an_srid_override_lets_the_same_reupload_proceed(
    client: AsyncClient, test_db_session
):
    """Counterfactual for the gate above: an override skips the refusal."""
    admin_id, dataset, job = await _seed(test_db_session, srid_override=3857)
    resolve, validate, ogrinfo, ogr2ogr = _patched_pipeline(srid=None)

    with resolve, validate, ogrinfo, ogr2ogr as mock_load:
        with pytest.raises(Exception) as exc_info:
            await reupload_file(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                file_path=job.file_path or "",
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

    # The staging load ran, so the missing-CRS gate let this through; whatever
    # failed next is unrelated to CRS detection.
    mock_load.assert_awaited_once()
    assert "Missing CRS" not in str(exc_info.value)
