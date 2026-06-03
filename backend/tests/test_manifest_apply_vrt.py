from __future__ import annotations

from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.modules.auth.models import User
from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.tasks_raster import _is_manifest_vrt_job
from app.processing.ingest.tasks_vrt import create_vrt_dataset


def _vrt_request(*, dry_run: bool = False) -> ManifestApplyRequest:
    return ManifestApplyRequest.model_validate(
        {
            "manifest_version": "1",
            "catalog": {"title": "Raster mosaic catalog"},
            "dry_run": dry_run,
            "datasets": [
                {
                    "key": "flood-depth-mosaic",
                    "title": "Flood depth mosaic",
                    "description": "Local VRT mosaic assembled from staged sources.",
                    "sources": [
                        {
                            "type": "vrt",
                            "uri": "./rasters/flood-depth-mosaic.vrt",
                            "format": "vrt",
                        }
                    ],
                    "metadata": {
                        "tags": ["hydrology", "flood"],
                        "organization": "Emergency Management",
                        "crs": "EPSG:4326",
                    },
                    "publication": {"intent": "internal"},
                }
            ],
        }
    )


async def _admin_user(session):
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one()


class TestManifestVrtApplyRouting:
    async def test_vrt_entry_routes_to_existing_raster_queue(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        request = _vrt_request()

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(test_db_session, request, user)

        result = response.results[0]
        assert result.action == "create"
        assert result.job_id is not None
        queue.assert_awaited_once()

        job = await test_db_session.get(IngestJob, result.job_id)
        assert job is not None
        assert job.file_path == "./rasters/flood-depth-mosaic.vrt"
        assert job.user_metadata["manifest_key"] == "flood-depth-mosaic"
        assert job.user_metadata["manifest_source_type"] == "vrt"
        assert job.user_metadata["file_type"] == "raster"
        assert job.user_metadata["visibility"] == "internal"
        assert job.user_metadata["record_status"] == "internal"

    async def test_vrt_dry_run_preserves_result_contract_without_queue(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        request = _vrt_request(dry_run=True)

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(test_db_session, request, user)

        assert response.dry_run is True
        assert response.results[0].action == "create"
        assert response.results[0].job_id is None
        queue.assert_not_awaited()


class TestManifestVrtCompletion:
    async def test_manifest_vrt_job_detection(self):
        job = IngestJob(
            source_filename="flood-depth-mosaic.vrt",
            user_metadata={"manifest_source_type": "vrt"},
        )

        assert _is_manifest_vrt_job(job) is True

    async def test_manifest_vrt_dataset_creation_uses_vrt_contract(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        record, dataset, raster_asset = await create_vrt_dataset(
            test_db_session,
            meta={
                "driver": "VRT",
                "epsg": 4326,
                "band_count": 1,
                "dtype": "float32",
                "width": 128,
                "height": 128,
            },
            asset_sha256="b" * 64,
            vrt_size=1024,
            source_filename="flood-depth-mosaic.vrt",
            created_by=user.id,
            title="Flood depth mosaic",
            summary="Manifest VRT summary",
            visibility="internal",
            record_status="internal",
            vrt_type="mosaic",
            resolution_strategy="finest",
            source_dataset_ids=[],
        )

        await test_db_session.commit()
        await test_db_session.refresh(record)
        await test_db_session.refresh(dataset)
        await test_db_session.refresh(raster_asset)

        assert record.record_type == "vrt_dataset"
        assert record.record_status == "internal"
        assert record.visibility == "internal"
        assert dataset.table_name.startswith("vrt_")
        assert dataset.source_format is None
        assert dataset.source_filename == "flood-depth-mosaic.vrt"
        assert raster_asset.dataset_id == dataset.id
        assert raster_asset.driver == "VRT"
        assert raster_asset.status == "ready"


class TestManifestVrtRoundTripContract:
    async def test_manifest_vrt_metadata_matches_existing_search_preview_shape(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        record, dataset, raster_asset = await create_vrt_dataset(
            test_db_session,
            meta={
                "driver": "VRT",
                "epsg": 4326,
                "band_count": 2,
                "dtype": "uint16",
                "width": 256,
                "height": 256,
            },
            asset_sha256="c" * 64,
            vrt_size=2048,
            source_filename="roundtrip.vrt",
            created_by=user.id,
            title="Round-trip VRT",
            summary="Visible VRT summary",
            visibility="public",
            record_status="published",
            vrt_type="mosaic",
            resolution_strategy="finest",
            source_dataset_ids=[],
        )

        await test_db_session.commit()
        await test_db_session.refresh(record)
        await test_db_session.refresh(dataset)
        await test_db_session.refresh(raster_asset)

        assert dataset.record.record_type == "vrt_dataset"
        assert dataset.record.visibility == "public"
        assert dataset.record.record_status == "published"
        assert raster_asset.asset_uri == ""
        assert raster_asset.vrt_type == "mosaic"
        assert raster_asset.band_count == 2
