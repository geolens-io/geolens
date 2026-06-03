from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select, text

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import ManifestApplyRequest, ManifestSource
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import (
    ManifestSourceError,
    classify_manifest_source,
    derive_source_extension,
    derive_source_filename,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
    parse_manifest_crs,
    publication_to_catalog_fields,
)
from tests.factories import create_dataset


def _manifest_dataset(
    *,
    key: str = "roads",
    title: str = "Road centerlines",
    uri: str = "tests/fixtures/ingest/basic_attrs.geojson",
    source_type: str = "vector",
    intent: str = "draft",
    crs: str | None = "EPSG:4326",
    tags: list[str] | None = None,
) -> dict:
    metadata: dict[str, object] = {
        "organization": "City GIS",
        "license": "CC-BY-4.0",
        "attribution": "City GIS",
    }
    if crs is not None:
        metadata["crs"] = crs
    if tags is not None:
        metadata["tags"] = tags
    return {
        "key": key,
        "title": title,
        "description": f"{title} description",
        "sources": [
            {
                "type": source_type,
                "uri": uri,
                "format": "geojson" if source_type == "vector" else "cog",
            }
        ],
        "metadata": metadata,
        "publication": {"intent": intent},
    }


def _request(
    *datasets: dict,
    dry_run: bool = False,
) -> ManifestApplyRequest:
    return ManifestApplyRequest.model_validate(
        {
            "manifest_version": "1",
            "catalog": {"title": "Manifest catalog"},
            "datasets": list(datasets),
            "dry_run": dry_run,
        }
    )


async def _admin_user(session):
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one()


async def _create_completed_manifest_job(
    session,
    *,
    user: User,
    dataset: Dataset,
    manifest_dataset,
) -> IngestJob:
    prepared = await classify_manifest_source(manifest_dataset.sources[0])
    fingerprint = manifest_dataset_fingerprint(manifest_dataset)
    job = IngestJob(
        dataset_id=dataset.id,
        source_filename=prepared.source_filename,
        file_path=prepared.file_path,
        created_by=user.id,
        status="complete",
        completed_at=datetime.now(timezone.utc),
        user_metadata=manifest_job_metadata(
            manifest_dataset,
            prepared,
            fingerprint=fingerprint,
        ),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


class TestManifestApplyHelpers:
    def test_manifest_dataset_fingerprint_is_stable_and_sensitive(self):
        first = _request(_manifest_dataset()).datasets[0]
        second = _request(_manifest_dataset()).datasets[0]
        changed = _request(_manifest_dataset(title="Roads 2026")).datasets[0]

        assert manifest_dataset_fingerprint(first) == manifest_dataset_fingerprint(
            second
        )
        assert manifest_dataset_fingerprint(first) != manifest_dataset_fingerprint(
            changed
        )

    def test_publication_mapping(self):
        assert publication_to_catalog_fields("draft") == ("private", "draft")
        assert publication_to_catalog_fields("ready") == ("private", "ready")
        assert publication_to_catalog_fields("internal") == ("internal", "internal")
        assert publication_to_catalog_fields("published") == (
            "public",
            "published",
        )

    def test_crs_parsing(self):
        assert parse_manifest_crs("EPSG:3857") == 3857
        assert parse_manifest_crs(None) is None

    def test_source_filename_and_extension_derivation(self):
        local = ManifestSource(type="vector", uri="./data/roads.geojson")
        remote = ManifestSource(
            type="raster_cog",
            uri="s3://example-geolens-public/rasters/tile-001.tif",
        )

        assert derive_source_filename(local) == "roads.geojson"
        assert derive_source_extension(local) == ".geojson"
        assert derive_source_filename(remote) == "tile-001.tif"
        assert derive_source_extension(remote) == ".tif"

    @pytest.mark.anyio
    async def test_unsafe_http_uri_is_rejected(self):
        source = ManifestSource(
            type="vector",
            uri="http://127.0.0.1/private.geojson",
        )

        with pytest.raises(ManifestSourceError, match="private/internal"):
            await classify_manifest_source(source)

    def test_dotdot_traversal_rejected_at_schema_layer(self):
        """Phase 268 H-29: ManifestSource must reject any URI containing
        a `..` path segment. The Pydantic validator catches it before any
        ingest classification runs."""
        for unsafe in (
            "../etc/passwd",
            "../../app/.env",
            "data/../../../proc/self/environ",
            "./..",
            "foo/../bar",
            "tests/fixtures/../../etc/passwd",
        ):
            with pytest.raises(Exception) as exc_info:
                ManifestSource(type="vector", uri=unsafe)
            # Either the regex pattern OR the field validator should reject;
            # both manifest as ValidationError.
            err = str(exc_info.value)
            assert (
                "`..`" in err or ".." in err or "String should match pattern" in err
            ), f"unexpected error for {unsafe!r}: {err}"

    @pytest.mark.anyio
    async def test_classify_manifest_source_rejects_paths_outside_staging_dir(
        self, monkeypatch
    ):
        """Phase 268 H-29: defense-in-depth — even if the regex/validator
        is bypassed somehow, classify_manifest_source must refuse paths
        whose resolved form escapes upload_staging_dir."""
        # Construct a ManifestSource directly bypassing validation by
        # patching the validator to a no-op, simulating any future
        # accidental relaxation of the schema.
        from app.processing.ingest import manifest_schemas
        from app.processing.ingest.manifest_sources import classify_manifest_source

        original_validator = manifest_schemas.ManifestSource._reject_dotdot_segments

        def passthrough(cls, uri: str) -> str:
            return uri

        monkeypatch.setattr(
            manifest_schemas.ManifestSource,
            "_reject_dotdot_segments",
            classmethod(passthrough),
        )
        # Also clear the regex pattern by constructing model_validate over
        # a value that would have failed it; simpler: just call the runtime
        # check directly via a forged-shaped object.
        forged = manifest_schemas.ManifestSource.model_construct(
            type="vector",
            uri="../../etc/secrets.geojson",
            title=None,
            description=None,
            format=None,
            layer=None,
        )

        with pytest.raises(ManifestSourceError, match="upload_staging_dir"):
            await classify_manifest_source(forged)

        # Restore validator (defensive — monkeypatch teardown handles it
        # but be explicit).
        monkeypatch.setattr(
            manifest_schemas.ManifestSource,
            "_reject_dotdot_segments",
            original_validator,
        )


@pytest.mark.anyio
class TestManifestApplyService:
    async def test_new_vector_entry_creates_job_and_queues_ingest(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        request = _request(
            _manifest_dataset(
                key="manifest-create-vector",
                tags=["transportation", "roads"],
                intent="ready",
            )
        )

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(test_db_session, request, user)

        assert response.accepted is True
        result = response.results[0]
        assert result.action == "create"
        assert result.job_id is not None
        queue.assert_awaited_once()

        job = await test_db_session.get(IngestJob, result.job_id)
        assert job is not None
        assert job.user_metadata["manifest_key"] == "manifest-create-vector"
        assert job.user_metadata["manifest_source_type"] == "vector"
        assert job.user_metadata["manifest_tags"] == ["transportation", "roads"]
        assert job.user_metadata["visibility"] == "private"
        assert job.user_metadata["record_status"] == "ready"
        assert job.user_metadata["srid_override"] == 4326

    async def test_new_raster_entry_sets_raster_queue_metadata(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        request = _request(
            _manifest_dataset(
                key="manifest-create-raster",
                uri="rasters/tile-001.tif",
                source_type="raster_cog",
                intent="published",
                crs="EPSG:32618",
            )
        )

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ):
            response = await apply_manifest(test_db_session, request, user)

        result = response.results[0]
        assert result.action == "create"
        job = await test_db_session.get(IngestJob, result.job_id)
        assert job.user_metadata["file_type"] == "raster"
        assert job.user_metadata["visibility"] == "public"
        assert job.user_metadata["record_status"] == "published"
        assert job.user_metadata["srid_override"] == 32618

    async def test_completed_same_fingerprint_skips(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-skip-complete"))
        dataset = await create_dataset(
            test_db_session,
            created_by=user.id,
            name="Existing roads",
        )
        job = await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=dataset,
            manifest_dataset=request.datasets[0],
        )

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(test_db_session, request, user)

        result = response.results[0]
        assert result.action == "skip"
        assert result.job_id == job.id
        assert result.dataset_id == dataset.id
        queue.assert_not_awaited()

    async def test_changed_completed_fingerprint_creates_reupload_job(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        original_request = _request(_manifest_dataset(key="manifest-update"))
        changed_request = _request(
            _manifest_dataset(key="manifest-update", title="Updated roads")
        )
        dataset = await create_dataset(
            test_db_session,
            created_by=user.id,
            name="Existing roads",
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=dataset,
            manifest_dataset=original_request.datasets[0],
        )
        task = MagicMock()
        task.defer_async = AsyncMock()
        port = MagicMock()
        port.reupload_file_task.return_value = task

        with patch(
            "app.processing.ingest.manifest_service.get_catalog_port",
            return_value=port,
        ):
            response = await apply_manifest(test_db_session, changed_request, user)

        result = response.results[0]
        assert result.action == "update"
        assert result.dataset_id == dataset.id
        assert result.job_id is not None
        task.defer_async.assert_awaited_once()

        job = await test_db_session.get(IngestJob, result.job_id)
        assert job.dataset_id == dataset.id
        assert job.user_metadata["reupload"] is True
        assert job.user_metadata["manifest_key"] == "manifest-update"
        assert job.user_metadata["title"] == "Updated roads"


@pytest.mark.anyio
class TestManifestInFlightIdempotency:
    async def test_same_fingerprint_in_flight_skips(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="manifest-in-flight"))
        prepared = await classify_manifest_source(request.datasets[0].sources[0])
        fingerprint = manifest_dataset_fingerprint(request.datasets[0])
        pending = IngestJob(
            source_filename=prepared.source_filename,
            file_path=prepared.file_path,
            created_by=user.id,
            status="pending",
            user_metadata=manifest_job_metadata(
                request.datasets[0],
                prepared,
                fingerprint=fingerprint,
            ),
        )
        test_db_session.add(pending)
        await test_db_session.commit()
        await test_db_session.refresh(pending)

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(test_db_session, request, user)

        result = response.results[0]
        assert result.action == "skip"
        assert result.job_id == pending.id
        assert "queued or running" in result.message
        queue.assert_not_awaited()

    async def test_different_fingerprint_in_flight_errors_without_new_job(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        original = _request(_manifest_dataset(key="manifest-in-flight-conflict"))
        changed = _request(
            _manifest_dataset(
                key="manifest-in-flight-conflict",
                title="Competing roads",
            )
        )
        prepared = await classify_manifest_source(original.datasets[0].sources[0])
        pending = IngestJob(
            source_filename=prepared.source_filename,
            file_path=prepared.file_path,
            created_by=user.id,
            status="running",
            user_metadata=manifest_job_metadata(
                original.datasets[0],
                prepared,
                fingerprint=manifest_dataset_fingerprint(original.datasets[0]),
            ),
        )
        test_db_session.add(pending)
        await test_db_session.commit()
        before = await test_db_session.scalar(select(func.count(IngestJob.id)))

        response = await apply_manifest(test_db_session, changed, user)

        after = await test_db_session.scalar(select(func.count(IngestJob.id)))
        result = response.results[0]
        assert result.action == "error"
        assert "in-flight apply" in result.message
        assert after == before


@pytest.mark.anyio
class TestManifestDryRun:
    async def test_dry_run_previews_create_update_skip_without_writes(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        existing_request = _request(_manifest_dataset(key="manifest-dry-skip"))
        changed_request = _request(
            _manifest_dataset(key="manifest-dry-update", title="Original")
        )
        skip_dataset = await create_dataset(
            test_db_session,
            created_by=user.id,
            name="Skip dataset",
        )
        update_dataset = await create_dataset(
            test_db_session,
            created_by=user.id,
            name="Update dataset",
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=skip_dataset,
            manifest_dataset=existing_request.datasets[0],
        )
        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=update_dataset,
            manifest_dataset=changed_request.datasets[0],
        )
        request = _request(
            _manifest_dataset(key="manifest-dry-create"),
            _manifest_dataset(key="manifest-dry-update", title="Changed"),
            _manifest_dataset(key="manifest-dry-skip"),
            dry_run=True,
        )
        before = await test_db_session.scalar(select(func.count(IngestJob.id)))

        with patch(
            "app.processing.ingest.manifest_service.queue_ingest_job",
            new=AsyncMock(),
        ) as queue:
            response = await apply_manifest(test_db_session, request, user)

        after = await test_db_session.scalar(select(func.count(IngestJob.id)))
        actions = {result.dataset_key: result.action for result in response.results}
        assert response.dry_run is True
        assert actions == {
            "manifest-dry-create": "create",
            "manifest-dry-update": "update",
            "manifest-dry-skip": "skip",
        }
        assert response.results[0].job_id is None
        assert response.results[1].job_id is None
        assert response.results[1].dataset_id == update_dataset.id
        assert after == before
        queue.assert_not_awaited()


@pytest.mark.anyio
class TestManifestMetadataPropagation:
    async def test_vector_finalize_uses_manifest_record_status(
        self, test_db_session, clean_tables
    ):
        from app.processing.ingest.tasks_common import IngestContext, _finalize_ingest

        user = await _admin_user(test_db_session)
        table_name = f"manifest_meta_{uuid.uuid4().hex[:10]}"
        await test_db_session.execute(
            text(f"CREATE TABLE data.{table_name} (gid serial PRIMARY KEY, name text)")
        )
        await test_db_session.commit()
        job = IngestJob(
            source_filename="roads.geojson",
            file_path="tests/fixtures/ingest/basic_attrs.geojson",
            created_by=user.id,
            status="running",
            user_metadata={
                "title": "Manifest roads",
                "summary": "Manifest summary",
                "visibility": "private",
                "record_status": "ready",
            },
        )
        test_db_session.add(job)
        await test_db_session.flush()

        try:
            with (
                patch(
                    "app.processing.ingest.tasks_common.invalidate_catalog_cache",
                    new=AsyncMock(),
                ),
                patch(
                    "app.processing.ingest.tasks_common.defer_embedding",
                    new=AsyncMock(),
                ),
            ):
                dataset = await _finalize_ingest(
                    IngestContext(
                        session=test_db_session,
                        job=job,
                        table_name=table_name,
                        user_id=str(user.id),
                        has_geometry=False,
                        effective_srid=None,
                        source_format="geojson",
                        source_filename="roads.geojson",
                        original_srid=None,
                        user_metadata=job.user_metadata,
                    )
                )
            assert dataset.record.summary == "Manifest summary"
            assert dataset.record.visibility == "private"
            assert dataset.record.record_status == "ready"
        finally:
            await test_db_session.execute(
                text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
            )
            await test_db_session.commit()

    async def test_raster_dataset_creation_uses_manifest_record_status(
        self, test_db_session, clean_tables
    ):
        from app.processing.ingest.tasks_raster import create_raster_dataset

        user = await _admin_user(test_db_session)
        record, dataset, _asset = await create_raster_dataset(
            test_db_session,
            meta={
                "driver": "GTiff",
                "epsg": 4326,
                "band_count": 1,
                "dtype": "uint8",
                "width": 16,
                "height": 16,
            },
            source_sha256="0" * 64,
            asset_sha256="1" * 64,
            cog_status="verified",
            cog_size=128,
            source_filename="tile.tif",
            created_by=user.id,
            title="Manifest raster",
            summary="Raster summary",
            visibility="internal",
            record_status="internal",
        )

        assert record.record_status == "internal"
        assert record.visibility == "internal"
        assert dataset.source_filename == "tile.tif"
