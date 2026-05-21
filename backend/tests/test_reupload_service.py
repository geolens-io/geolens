"""Tests for service-source re-upload commit dispatch and worker invariants."""

import uuid
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.collections.models import DatasetVersion
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.ingest.ogr import IngestionError
from app.processing.ingest.tasks import reupload_service
from app.platform.jobs.models import IngestJob

from tests.factories import get_user_id


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "Service Reupload Dataset",
    visibility: str = "public",
) -> Dataset:
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="original.geojson",
        source_url="https://old.example.com/source",
        column_info=[
            {"name": "name", "type": "character varying"},
            {"name": "value", "type": "integer"},
        ],
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_service_reupload_job(
    session,
    *,
    dataset_id: uuid.UUID,
    created_by: uuid.UUID,
    source_url: str = "https://example.com/wfs",
    source_layer: str = "roads",
    source_filename: str = "Roads Layer",
) -> IngestJob:
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename=source_filename,
        source_url=source_url,
        source_layer=source_layer,
        created_by=created_by,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": "WFS 2.0.0",
            "layer_id": None,
            "source_type": "service_url",
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


class TestServiceReuploadCommitDispatch:
    async def test_commit_dispatches_to_reupload_service_and_keeps_token_request_only(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)
        job = await _create_service_reupload_job(
            test_db_session,
            dataset_id=dataset.id,
            created_by=admin_id,
        )

        mock_reupload_service = MagicMock()
        mock_reupload_file = MagicMock()
        mock_reupload_service.defer_async = AsyncMock(return_value=None)
        mock_reupload_file.defer_async = AsyncMock(return_value=None)
        mock_reupload_file.configure.return_value.defer_async = AsyncMock(
            return_value=None
        )
        mock_catalog_port = MagicMock()
        mock_catalog_port.reupload_service_task.return_value = mock_reupload_service
        mock_catalog_port.reupload_file_task.return_value = mock_reupload_file
        mock_catalog_port.priority_queue_threshold_bytes = 10_000_000

        with patch(
            "app.modules.catalog.datasets.api.router_reupload.get_catalog_port",
            return_value=mock_catalog_port,
        ):
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job.id}/commit",
                json={"token": "super-secret-token"},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202
        payload = resp.json()
        assert payload["status"] == "pending"
        assert payload["message"] == "Re-upload queued"

        mock_reupload_service.defer_async.assert_awaited_once()
        service_kwargs = mock_reupload_service.defer_async.call_args.kwargs
        assert service_kwargs["job_id"] == str(job.id)
        assert service_kwargs["dataset_id"] == str(dataset.id)
        assert service_kwargs["source_url"] == "https://example.com/wfs"
        assert service_kwargs["source_layer"] == "roads"
        assert service_kwargs["user_id"] == str(admin_id)
        assert service_kwargs["token"] == "super-secret-token"

        mock_reupload_file.defer_async.assert_not_awaited()
        mock_reupload_file.configure.assert_not_called()

        result = await test_db_session.execute(
            select(IngestJob).where(IngestJob.id == job.id)
        )
        updated_job = result.scalar_one()
        assert "token" not in (updated_job.user_metadata or {})
        assert "super-secret-token" not in str(updated_job.user_metadata)


class TestServiceReuploadWorker:
    async def test_reupload_service_preserves_identity_and_increments_version(
        self,
        client: AsyncClient,  # ensures app.database.async_session points to test DB
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)
        job = await _create_service_reupload_job(
            test_db_session,
            dataset_id=dataset.id,
            created_by=admin_id,
            source_url="https://services.example.com/wfs",
            source_layer="roads",
            source_filename="roads_wfs",
        )
        original_dataset_id = dataset.id
        original_table_name = dataset.table_name
        original_version = dataset.current_version

        async def _fake_run_ogr2ogr_service(
            gdal_source: str,
            layer_name: str,
            table_name: str,
            db_conn_str: str,
            service_type: str,
            timeout: float = 1800.0,
            token: str | None = None,
        ) -> None:
            import app.core.db as db_module

            async with db_module.async_session() as session:
                await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
                await session.execute(
                    text(
                        f"CREATE TABLE data.{table_name} "
                        "(gid serial PRIMARY KEY, name text, value integer)"
                    )
                )
                await session.commit()

        metadata_payload = {
            "srid": 4326,
            "geometry_type": "MULTIPOLYGON",
            "feature_count": 275,
            "extent_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
            "column_info": [
                {
                    "name": "name",
                    "type": "character varying",
                    "ordinal_position": 1,
                    "is_nullable": True,
                },
                {
                    "name": "value",
                    "type": "integer",
                    "ordinal_position": 2,
                    "is_nullable": True,
                },
            ],
        }

        with (
            # Phase 1066 IA-P0-03 (commit f8c91297) added a defense-in-depth
            # SSRF re-validation of ``source_url`` at the top of the
            # ``reupload_service`` worker body (tasks_reupload.py:373-378)
            # via a LAZY from-import inside the function body:
            #     from app.modules.catalog.sources.security import validate_url_for_ssrf
            # The lazy import re-binds the symbol on every call, so the
            # patch target MUST be the function's defining module (NOT
            # the worker's namespace). The fixture URL
            # ``services.example.com`` fails DNS resolution in the test
            # sandbox, which is unrelated to this test's contract
            # (identity preservation + version increment), so we no-op
            # the gate via AsyncMock. Same fix shape as Plan 1075-03
            # closed in test_ingest.py:1369-1372.
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.catalog.sources.preview.build_gdal_source",
                return_value=("WFS:https://services.example.com/wfs", "roads"),
            ),
            patch(
                "app.processing.ingest.ogr.run_ogr2ogr_service", new_callable=AsyncMock
            ) as mock_run_ogr2ogr_service,
            patch(
                "app.processing.ingest.metadata.ensure_geom_column",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.processing.ingest.metadata.clip_to_mercator_bounds",
                new_callable=AsyncMock,
            ) as mock_clip,
            patch(
                "app.processing.ingest.metadata.add_4326_column",
                new_callable=AsyncMock,
            ) as mock_add_4326,
            patch(
                "app.processing.ingest.metadata.grant_reader_access",
                new_callable=AsyncMock,
            ) as mock_grant,
            patch(
                "app.processing.ingest.metadata.extract_metadata",
                new_callable=AsyncMock,
            ) as mock_extract_metadata,
            patch(
                "app.processing.ingest.metadata.get_sample_values",
                new_callable=AsyncMock,
            ) as mock_sample_values,
            patch(
                "app.processing.ingest.metadata.refresh_attribute_metadata",
                new_callable=AsyncMock,
            ) as mock_refresh_attributes,
            patch(
                "app.processing.ingest.metadata.compute_quality_score",
                new_callable=AsyncMock,
            ) as mock_quality_score,
            patch(
                "app.processing.ingest.tasks_reupload.invalidate_catalog_cache",
                new_callable=AsyncMock,
            ) as mock_invalidate_catalog,
        ):
            mock_run_ogr2ogr_service.side_effect = _fake_run_ogr2ogr_service
            mock_extract_metadata.return_value = metadata_payload
            mock_sample_values.return_value = {"name": ["Main St"]}
            mock_quality_score.return_value = {
                "overall": 92,
                "metadata_completeness": 90,
                "geometry_validity": 100,
                "attribute_completeness": 85,
                "crs_defined": 100,
            }

            await reupload_service(
                job_id=str(job.id),
                dataset_id=str(dataset.id),
                source_url=job.source_url or "",
                source_layer=job.source_layer or "",
                user_id=str(admin_id),
                token="runtime-token",
            )

        await test_db_session.refresh(dataset)

        assert dataset.id == original_dataset_id
        assert dataset.table_name == original_table_name
        assert dataset.current_version == original_version + 1
        assert dataset.feature_count == 275
        assert dataset.source_url == "https://services.example.com/wfs"
        assert dataset.source_format == "wfs"
        assert dataset.source_filename == "roads_wfs"

        table_exists = await test_db_session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='data' AND table_name=:tn)"
            ),
            {"tn": original_table_name},
        )
        assert table_exists.scalar() is True

        version_result = await test_db_session.execute(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset.id)
            .order_by(DatasetVersion.version_number.desc())
        )
        version = version_result.scalar_one()
        assert version.version_number == original_version + 1
        assert version.source_format == "wfs"
        assert version.source_filename == "roads_wfs"
        assert version.feature_count == 275
        assert version.srid == 4326
        assert version.geometry_type == "MULTIPOLYGON"
        assert version.file_hash is None
        assert version.uploaded_by == admin_id

        await test_db_session.refresh(job)
        assert job.status == "complete"
        assert job.error_message is None

        mock_clip.assert_awaited_once_with(ANY, f"{original_table_name}_staging")
        mock_add_4326.assert_awaited_once_with(
            ANY, f"{original_table_name}_staging", 4326
        )
        mock_grant.assert_awaited_once_with(ANY, f"{original_table_name}_staging")
        mock_refresh_attributes.assert_awaited_once()
        mock_quality_score.assert_awaited_once()
        mock_invalidate_catalog.assert_awaited_once_with()

    async def test_reupload_service_without_token_returns_retry_guidance_on_auth_failure(
        self,
        client: AsyncClient,  # ensures app.database.async_session points to test DB
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _create_dataset(test_db_session, created_by=admin_id)
        job = await _create_service_reupload_job(
            test_db_session,
            dataset_id=dataset.id,
            created_by=admin_id,
            source_url="https://protected.example.com/wfs",
            source_layer="roads",
        )

        with (
            # Phase 1066 IA-P0-03: same SSRF defense-in-depth as the first
            # worker test. Fixture URL ``protected.example.com`` fails DNS
            # in the sandbox; mock the gate so the test exercises its actual
            # contract (401-retry guidance message from IngestionError).
            # Plan 1075-03 / test_ingest.py:1369 is the canonical pattern.
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.catalog.sources.preview.build_gdal_source",
                return_value=("WFS:https://protected.example.com/wfs", "roads"),
            ),
            patch(
                "app.processing.ingest.ogr.run_ogr2ogr_service",
                new_callable=AsyncMock,
            ) as mock_run_ogr2ogr_service,
        ):
            mock_run_ogr2ogr_service.side_effect = IngestionError(
                "ogr2ogr failed (exit 1): HTTP error code : 401 Unauthorized"
            )

            with pytest.raises(
                IngestionError, match="Retry commit with a service token"
            ):
                await reupload_service(
                    job_id=str(job.id),
                    dataset_id=str(dataset.id),
                    source_url=job.source_url or "",
                    source_layer=job.source_layer or "",
                    user_id=str(admin_id),
                    token=None,
                )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "Retry commit with a service token" in (job.error_message or "")
