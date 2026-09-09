"""The re-upload worker's geometry-loss refusal (#2031).

Replacing a vector dataset with a geometry-less file committed without a
warning: the swap derived `record_type` from the new measurement, so the
dataset became a table with null geometry, and `schema_drift_status` saw
nothing because the schema diff reads attribute columns only. The preview
door answers the same refusal (tests in test_reupload.py); this covers the
client that skips the preview and commits straight away.
"""

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


async def _seed(session, *, record_type: str):
    admin_id = await get_user_id(session, "admin")
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        name=f"Geometry loss {record_type}",
        record_type=record_type,
        feature_count=100,
        source_filename="original.geojson",
        column_info=[{"name": "name", "type": "character varying"}],
    )
    job = IngestJob(
        dataset_id=dataset.id,
        status="pending",
        attempt_id=uuid.uuid4(),
        source_filename="attributes.csv",
        file_path="/tmp/fake-2031.csv",
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return admin_id, dataset, job


def _patched_pipeline(*, geometry_type: str | None):
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


async def test_worker_refuses_to_de_spatialize_a_vector_dataset(
    client: AsyncClient, test_db_session
):
    admin_id, dataset, job = await _seed(test_db_session, record_type="vector_dataset")
    resolve, validate, ogrinfo, ogr2ogr = _patched_pipeline(geometry_type=None)

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


async def test_worker_allows_a_geometry_less_replacement_of_a_table(
    client: AsyncClient, test_db_session
):
    """A table has no geometry to lose, so the gate must not stand in its way."""
    admin_id, dataset, job = await _seed(test_db_session, record_type="table")
    resolve, validate, ogrinfo, ogr2ogr = _patched_pipeline(geometry_type=None)

    with resolve, validate, ogrinfo, ogr2ogr as mock_load:
        with pytest.raises(Exception) as exc_info:
            await reupload_file(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                file_path=job.file_path or "",
                user_id=str(admin_id),
                attempt_id=str(job.attempt_id),
            )

    # The staging load ran, so the gate let this through; the task then fails
    # on the staging table the stubbed ogr2ogr never created.
    mock_load.assert_awaited_once()
    assert "no geometry" not in str(exc_info.value)
