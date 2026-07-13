from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from httpx import AsyncByteStream, AsyncClient, MockTransport, Request as HttpxRequest
from httpx import Response as HttpxResponse
from sqlalchemy import func, select, text

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.quota.schemas import UserQuotaUsage
from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import ManifestApplyRequest, ManifestSource
from app.processing.ingest.manifest_service import _download_http_source, apply_manifest
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


class _StreamingBody(AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks
        self.iterated = False

    async def __aiter__(self):
        self.iterated = True
        for chunk in self._chunks:
            yield chunk


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


def _http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ingest/manifest/apply",
            "headers": [],
        }
    )


def _stage_basic_vector_fixture() -> Path:
    from app.core.config import settings

    relative = Path("tests/fixtures/ingest/basic_attrs.geojson")
    destination = Path(settings.upload_staging_dir) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", destination)
    return destination


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

    async def test_manifest_job_metadata_redacts_remote_credentials(self):
        dataset = _request(
            _manifest_dataset(
                uri=(
                    "https://alice:topsecret@example.test/roads.geojson"
                    "?token=super-secret&version=1"
                )
            )
        ).datasets[0]
        with patch(
            "app.modules.catalog.sources.security.validate_url_for_ssrf",
            new=AsyncMock(),
        ):
            prepared = await classify_manifest_source(dataset.sources[0])

        metadata = manifest_job_metadata(
            dataset,
            prepared,
            fingerprint=manifest_dataset_fingerprint(dataset),
        )

        persisted_uri = str(metadata["manifest_source_uri"])
        assert "topsecret" not in persisted_uri
        assert "super-secret" not in persisted_uri
        assert "alice" not in persisted_uri
        assert "version=1" in persisted_uri

    async def test_local_seed_staging_uses_unique_job_owned_copies(
        self, tmp_path, monkeypatch
    ):
        from app.core.config import settings
        from app.processing.ingest.manifest_service import _stage_source_if_needed

        seed = tmp_path / "seed.geojson"
        seed.write_bytes(b'{"type":"FeatureCollection","features":[]}')
        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
        dataset = _request(_manifest_dataset(uri="seed.geojson")).datasets[0]
        prepared = await classify_manifest_source(dataset.sources[0])

        first = await _stage_source_if_needed(AsyncMock(), prepared, dry_run=False)
        second = await _stage_source_if_needed(AsyncMock(), prepared, dry_run=False)

        assert first is not None and second is not None
        assert first != second
        assert first != str(seed)
        assert Path(first).read_bytes() == seed.read_bytes()
        assert Path(second).read_bytes() == seed.read_bytes()

    @pytest.mark.anyio
    async def test_classification_defends_against_forged_source_extension(self):
        source = ManifestSource.model_construct(
            type="raster_cog",
            uri="./rasters/mosaic.vrt",
            title=None,
            description=None,
            format=None,
            layer=None,
        )

        with pytest.raises(ManifestSourceError, match="Standalone VRT"):
            await classify_manifest_source(source)

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
    async def test_local_source_persists_canonical_validated_staging_path(
        self, monkeypatch, tmp_path
    ):
        from app.core.config import settings

        staging = tmp_path / "staging"
        (staging / "nested").mkdir(parents=True)
        source_path = staging / "nested" / "roads.geojson"
        source_path.write_text('{"type":"FeatureCollection","features":[]}')
        monkeypatch.setattr(settings, "upload_staging_dir", str(staging))

        prepared = await classify_manifest_source(
            ManifestSource(type="vector", uri="./nested/roads.geojson")
        )

        assert prepared.file_path == str(source_path.resolve())
        assert prepared.source_uri == "./nested/roads.geojson"

    @pytest.mark.anyio
    async def test_local_source_accepts_explicit_staging_root_marker(
        self, monkeypatch, tmp_path
    ):
        from app.core.config import settings

        staging = tmp_path / "staging"
        staging.mkdir()
        source_path = staging / "roads.geojson"
        source_path.write_text('{"type":"FeatureCollection","features":[]}')
        monkeypatch.setattr(settings, "upload_staging_dir", str(staging))

        prepared = await classify_manifest_source(
            ManifestSource(type="vector", uri="staging/roads.geojson")
        )

        assert prepared.file_path == str(source_path.resolve())

    @pytest.mark.anyio
    @pytest.mark.parametrize("with_content_length", [False, True])
    async def test_http_download_stops_at_streaming_quota_budget(
        self, test_db_session, monkeypatch, tmp_path, with_content_length: bool
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))
        source = ManifestSource(
            type="vector",
            uri="https://data.example.test/roads.geojson",
        )

        body = _StreamingBody(b"123", b"456")

        def handler(_request: HttpxRequest) -> HttpxResponse:
            return HttpxResponse(
                200,
                headers={"content-length": "6"} if with_content_length else {},
                stream=body,
            )

        client = AsyncClient(transport=MockTransport(handler))
        with (
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.catalog.sources.security.make_safe_client",
                return_value=client,
            ),
            patch(
                "app.processing.ingest.manifest_service.UPLOAD_MAX_SIZE_MB.get",
                new=AsyncMock(return_value=100),
            ),
        ):
            prepared = await classify_manifest_source(source)
            with pytest.raises(
                ManifestSourceError,
                match="remaining storage quota",
            ):
                await _download_http_source(
                    test_db_session,
                    prepared,
                    quota_byte_limit=5,
                )

        assert list(tmp_path.glob("manifest_*")) == []
        assert body.iterated is not with_content_length


@pytest.mark.anyio
class TestManifestApplyService:
    async def test_new_vector_entry_creates_job_and_queues_ingest(
        self, test_db_session, clean_tables
    ):
        staged_source = _stage_basic_vector_fixture()
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
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.accepted is True
        result = response.results[0]
        assert result.action == "create"
        assert result.job_id is not None
        queue.assert_awaited_once()

        job = await test_db_session.get(IngestJob, result.job_id)
        assert job is not None
        assert job.file_path != str(staged_source.resolve())
        assert Path(job.file_path).read_bytes() == staged_source.read_bytes()
        assert job.user_metadata["manifest_key"] == "manifest-create-vector"
        assert job.user_metadata["manifest_source_type"] == "vector"
        assert job.user_metadata["manifest_tags"] == ["transportation", "roads"]
        assert job.user_metadata["visibility"] == "private"
        assert job.user_metadata["record_status"] == "ready"
        assert job.user_metadata["srid_override"] == 4326

    async def test_new_raster_entry_sets_raster_queue_metadata(
        self, test_db_session, clean_tables
    ):
        from app.core.config import settings

        user = await _admin_user(test_db_session)
        staged_raster = Path(settings.upload_staging_dir) / "rasters/tile-001.tif"
        staged_raster.parent.mkdir(parents=True, exist_ok=True)
        staged_raster.write_bytes(b"test raster seed")
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
            with patch(
                "app.processing.ingest.manifest_service._manifest_source_size_bytes",
                new=AsyncMock(return_value=1024),
            ):
                response = await apply_manifest(
                    test_db_session, request, user, _http_request()
                )

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
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        result = response.results[0]
        assert result.action == "skip"
        assert result.job_id == job.id
        assert result.dataset_id == dataset.id
        queue.assert_not_awaited()

    async def test_changed_completed_fingerprint_creates_reupload_job(
        self, test_db_session, clean_tables
    ):
        _stage_basic_vector_fixture()
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
            response = await apply_manifest(
                test_db_session, changed_request, user, _http_request()
            )

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

    async def test_raster_update_is_rejected_before_staging_or_queue(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        original_request = _request(_manifest_dataset(key="manifest-raster-update"))
        changed_request = _request(
            _manifest_dataset(
                key="manifest-raster-update",
                title="Replacement raster",
                source_type="raster_cog",
                uri="rasters/replacement.tif",
            )
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

        with (
            patch(
                "app.processing.ingest.manifest_service._stage_source_and_check_quota",
                new=AsyncMock(),
            ) as stage,
            patch(
                "app.processing.ingest.manifest_service._queue_reupload_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session, changed_request, user, _http_request()
            )

        assert response.results[0].action == "error"
        assert "raster updates are not supported" in response.results[0].message
        stage.assert_not_awaited()
        queue.assert_not_awaited()

    async def test_vector_update_cannot_replace_existing_raster_dataset(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        original_request = _request(_manifest_dataset(key="manifest-type-mismatch"))
        changed_request = _request(
            _manifest_dataset(
                key="manifest-type-mismatch",
                title="Vector replacement",
            )
        )
        dataset = await create_dataset(
            test_db_session,
            created_by=user.id,
            name="Existing raster",
        )
        dataset.record.record_type = "raster_dataset"
        await test_db_session.commit()
        await _create_completed_manifest_job(
            test_db_session,
            user=user,
            dataset=dataset,
            manifest_dataset=original_request.datasets[0],
        )

        with patch(
            "app.processing.ingest.manifest_service._stage_source_and_check_quota",
            new=AsyncMock(),
        ) as stage:
            response = await apply_manifest(
                test_db_session, changed_request, user, _http_request()
            )

        assert response.results[0].action == "error"
        assert (
            "cannot replace an existing raster_dataset" in response.results[0].message
        )
        stage.assert_not_awaited()

    async def test_dataset_quota_is_checked_before_http_download(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        request = _request(
            _manifest_dataset(
                key="manifest-http-count-quota",
                uri="https://data.example.test/roads.geojson",
            )
        )
        usage = UserQuotaUsage(
            bytes_used=0,
            dataset_count=5,
            storage_cap=0,
            count_cap=5,
        )

        with (
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.quota.service.get_user_quota_usage",
                new=AsyncMock(return_value=usage),
            ),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(),
            ) as download,
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.accepted is False
        assert response.results[0].action == "error"
        assert "Dataset quota exceeded" in response.results[0].message
        download.assert_not_awaited()
        queue.assert_not_awaited()

    async def test_batch_count_quota_includes_jobs_admitted_earlier_in_request(
        self, test_db_session, clean_tables, tmp_path
    ):
        user = await _admin_user(test_db_session)
        request = _request(
            _manifest_dataset(
                key="manifest-batch-count-a",
                uri="https://data.example.test/a.geojson",
            ),
            _manifest_dataset(
                key="manifest-batch-count-b",
                uri="https://data.example.test/b.geojson",
            ),
        )
        staged = tmp_path / "a.geojson"
        staged.write_bytes(b"a")
        usage = UserQuotaUsage(
            bytes_used=0,
            dataset_count=0,
            storage_cap=0,
            count_cap=1,
        )

        with (
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.quota.service.get_user_quota_usage",
                new=AsyncMock(return_value=usage),
            ),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(staged)),
            ) as download,
            patch(
                "app.modules.quota.service.check_upload_quota",
                new=AsyncMock(),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ),
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert [result.action for result in response.results] == ["create", "error"]
        assert "Dataset quota exceeded" in response.results[1].message
        download.assert_awaited_once()

    async def test_batch_byte_quota_includes_sources_admitted_earlier_in_request(
        self, test_db_session, clean_tables, tmp_path
    ):
        user = await _admin_user(test_db_session)
        request = _request(
            _manifest_dataset(
                key="manifest-batch-bytes-a",
                uri="https://data.example.test/a.geojson",
            ),
            _manifest_dataset(
                key="manifest-batch-bytes-b",
                uri="https://data.example.test/b.geojson",
            ),
        )
        first = tmp_path / "a.geojson"
        second = tmp_path / "b.geojson"
        first.write_bytes(b"a" * 6)
        second.write_bytes(b"b" * 6)
        usage = UserQuotaUsage(
            bytes_used=0,
            dataset_count=0,
            storage_cap=10,
            count_cap=0,
        )

        with (
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.modules.quota.service.get_user_quota_usage",
                new=AsyncMock(return_value=usage),
            ),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(side_effect=[str(first), str(second)]),
            ),
            patch(
                "app.modules.quota.service.check_upload_quota",
                new=AsyncMock(),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ),
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert [result.action for result in response.results] == ["create", "error"]
        assert "Storage quota exceeded" in response.results[1].message
        assert not second.exists()

    async def test_tenant_admin_cannot_use_unowned_raw_seed_source(
        self, test_db_session, clean_tables
    ):
        user = await _admin_user(test_db_session)
        request = _request(_manifest_dataset(key="tenant-admin-raw-seed"))

        with (
            patch("app.core.tenancy.is_multi_tenant", return_value=True),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.results[0].action == "error"
        assert "disabled in multi-tenant mode" in response.results[0].message
        queue.assert_not_awaited()

    async def test_downloaded_http_vector_is_quota_checked_and_removed_on_denial(
        self, test_db_session, clean_tables, tmp_path
    ):
        user = await _admin_user(test_db_session)
        request = _request(
            _manifest_dataset(
                key="manifest-http-quota",
                uri="https://data.example.test/roads.geojson",
            )
        )
        staged = tmp_path / "manifest_http_roads.geojson"
        staged.write_bytes(b"x" * 4096)
        user_id = user.id

        with (
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(staged)),
            ),
            patch(
                "app.modules.quota.service.check_upload_quota",
                new=AsyncMock(
                    side_effect=HTTPException(status_code=413, detail="quota denied")
                ),
            ) as quota_check,
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.accepted is False
        assert response.results[0].action == "error"
        assert "quota denied" in response.results[0].message
        assert not staged.exists()
        quota_check.assert_awaited_once()
        assert quota_check.await_args.args[1] == user_id
        assert quota_check.await_args.args[2] == 4096
        queue.assert_not_awaited()
        assert await test_db_session.scalar(select(func.count(IngestJob.id))) == 0

    async def test_admin_same_bucket_seed_is_sized_and_quota_checked(
        self, test_db_session, clean_tables, monkeypatch
    ):
        from app.core.config import settings

        user = await _admin_user(test_db_session)
        user_id = user.id
        monkeypatch.setattr(settings, "storage_provider", "s3")
        monkeypatch.setattr(settings, "s3_bucket", "geolens-seed-bucket")
        request = _request(
            _manifest_dataset(
                key="manifest-admin-storage-seed",
                uri="s3://geolens-seed-bucket/operator/roads.geojson",
            )
        )

        with (
            patch(
                "app.processing.ingest.manifest_service._manifest_source_size_bytes",
                new=AsyncMock(return_value=8192),
            ) as source_size,
            patch(
                "app.modules.quota.service.check_upload_quota",
                new=AsyncMock(),
            ) as quota_check,
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.accepted is True
        assert response.results[0].action == "create"
        source_size.assert_awaited_once()
        quota_check.assert_awaited_once()
        assert quota_check.await_args.args[1:3] == (user_id, 8192)
        queue.assert_awaited_once()

    async def test_downloaded_http_source_is_removed_if_job_persistence_fails(
        self, test_db_session, clean_tables, tmp_path
    ):
        user = await _admin_user(test_db_session)
        request = _request(
            _manifest_dataset(
                key="manifest-http-persist-failure",
                uri="https://data.example.test/persist-failure.geojson",
            )
        )
        staged = tmp_path / "manifest_http_persist_failure.geojson"
        staged.write_bytes(b"valid-enough-for-admission")

        with (
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
            patch(
                "app.processing.ingest.manifest_service._download_http_source",
                new=AsyncMock(return_value=str(staged)),
            ),
            patch(
                "app.modules.quota.service.check_upload_quota",
                new=AsyncMock(),
            ),
            patch.object(
                test_db_session,
                "flush",
                new=AsyncMock(side_effect=RuntimeError("database unavailable")),
            ),
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert response.accepted is False
        assert response.results[0].action == "error"
        assert "database unavailable" in response.results[0].message
        assert not staged.exists()
        queue.assert_not_awaited()


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
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

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

        response = await apply_manifest(test_db_session, changed, user, _http_request())

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
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

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
