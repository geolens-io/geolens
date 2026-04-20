"""Tests for VRT creation endpoint and task (Phase 173-02).

Covers:
- VrtCreateRequest / VrtCreateResponse schema validation
- build_vrt dispatch (mosaic vs band_stack) subprocess behavior
- resolve_vrt_source_path for local and S3 storage
- POST /ingest/vrt/create endpoint: source count and existence validation

All tests are pure unit tests — no DB, no real files, no network.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.processing.ingest.schemas import VrtCreateRequest, VrtCreateResponse
from app.processing.raster.vrt import build_vrt, resolve_vrt_source_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_vrt_request(**overrides) -> dict:
    base = {
        "source_dataset_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
        "vrt_type": "mosaic",
        "resolution_strategy": "finest",
        "title": "Test VRT",
    }
    base.update(overrides)
    return base


def _make_subprocess_result(returncode: int = 0, stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# TestVrtSchemas
# ---------------------------------------------------------------------------


class TestVrtSchemas:
    """Schema-level validation for VrtCreateRequest and VrtCreateResponse."""

    def test_valid_mosaic_finest_passes(self):
        req = VrtCreateRequest(**_valid_vrt_request())
        assert req.vrt_type == "mosaic"
        assert req.resolution_strategy == "finest"

    def test_valid_band_stack_coarsest_passes(self):
        req = VrtCreateRequest(
            **_valid_vrt_request(
                vrt_type="band_stack",
                resolution_strategy="coarsest",
            )
        )
        assert req.vrt_type == "band_stack"

    def test_valid_mosaic_average_passes(self):
        req = VrtCreateRequest(**_valid_vrt_request(resolution_strategy="average"))
        assert req.resolution_strategy == "average"

    def test_invalid_vrt_type_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            VrtCreateRequest(**_valid_vrt_request(vrt_type="invalid"))
        assert (
            "vrt_type" in str(exc_info.value).lower()
            or "literal" in str(exc_info.value).lower()
        )

    def test_invalid_resolution_strategy_raises_validation_error(self):
        with pytest.raises(ValidationError):
            VrtCreateRequest(**_valid_vrt_request(resolution_strategy="random"))

    def test_missing_title_raises_validation_error(self):
        data = _valid_vrt_request()
        del data["title"]
        with pytest.raises(ValidationError):
            VrtCreateRequest(**data)

    def test_default_visibility_is_private(self):
        req = VrtCreateRequest(**_valid_vrt_request())
        assert req.visibility == "private"

    def test_summary_defaults_to_none(self):
        req = VrtCreateRequest(**_valid_vrt_request())
        assert req.summary is None

    def test_response_model_default_status(self):
        resp = VrtCreateResponse(job_id=uuid.uuid4(), message="queued")
        assert resp.status == "accepted"

    def test_response_model_accepts_job_id(self):
        job_id = uuid.uuid4()
        resp = VrtCreateResponse(job_id=job_id, message="VRT creation queued")
        assert resp.job_id == job_id


# ---------------------------------------------------------------------------
# TestVrtBuildFunctions
# ---------------------------------------------------------------------------


class TestVrtBuildFunctions:
    """Test build_vrt dispatch with mocked subprocess."""

    def test_build_mosaic_vrt_runs_correct_command(self):
        mock_result = _make_subprocess_result(returncode=0)
        sources = ["/path/a.tif", "/path/b.tif"]
        output = "/tmp/out.vrt"

        with patch(
            "app.processing.raster.vrt.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = build_vrt("mosaic", sources, output, "finest")

        assert result == output
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "gdalbuildvrt"
        assert "-resolution" in cmd
        assert "highest" in cmd  # "finest" maps to "highest"
        assert "-separate" not in cmd
        assert output in cmd
        assert "/path/a.tif" in cmd
        assert "/path/b.tif" in cmd

    def test_build_band_stack_vrt_includes_separate_flag(self):
        mock_result = _make_subprocess_result(returncode=0)
        sources = ["/path/a.tif", "/path/b.tif"]
        output = "/tmp/out.vrt"

        with patch(
            "app.processing.raster.vrt.subprocess.run", return_value=mock_result
        ) as mock_run:
            result = build_vrt("band_stack", sources, output, "coarsest")

        assert result == output
        cmd = mock_run.call_args[0][0]
        assert "-separate" in cmd
        assert "lowest" in cmd  # "coarsest" maps to "lowest"

    def test_build_mosaic_vrt_raises_on_nonzero_returncode(self):
        mock_result = _make_subprocess_result(returncode=1, stderr="gdalbuildvrt error")

        with patch(
            "app.processing.raster.vrt.subprocess.run", return_value=mock_result
        ):
            with pytest.raises(RuntimeError, match="gdalbuildvrt failed"):
                build_vrt("mosaic", ["/a.tif"], "/out.vrt", "finest")

    def test_build_band_stack_vrt_raises_on_nonzero_returncode(self):
        mock_result = _make_subprocess_result(returncode=1, stderr="gdalbuildvrt error")

        with patch(
            "app.processing.raster.vrt.subprocess.run", return_value=mock_result
        ):
            with pytest.raises(RuntimeError, match="gdalbuildvrt failed"):
                build_vrt("band_stack", ["/a.tif"], "/out.vrt", "finest")

    def test_resolution_strategy_finest_maps_to_highest(self):
        mock_result = _make_subprocess_result(returncode=0)

        with patch(
            "app.processing.raster.vrt.subprocess.run", return_value=mock_result
        ) as mock_run:
            build_vrt("mosaic", ["/a.tif"], "/out.vrt", "finest")

        cmd = mock_run.call_args[0][0]
        res_idx = cmd.index("-resolution")
        assert cmd[res_idx + 1] == "highest"

    def test_resolution_strategy_coarsest_maps_to_lowest(self):
        mock_result = _make_subprocess_result(returncode=0)

        with patch(
            "app.processing.raster.vrt.subprocess.run", return_value=mock_result
        ) as mock_run:
            build_vrt("mosaic", ["/a.tif"], "/out.vrt", "coarsest")

        cmd = mock_run.call_args[0][0]
        res_idx = cmd.index("-resolution")
        assert cmd[res_idx + 1] == "lowest"

    def test_resolution_strategy_average_maps_to_average(self):
        mock_result = _make_subprocess_result(returncode=0)

        with patch(
            "app.processing.raster.vrt.subprocess.run", return_value=mock_result
        ) as mock_run:
            build_vrt("mosaic", ["/a.tif"], "/out.vrt", "average")

        cmd = mock_run.call_args[0][0]
        res_idx = cmd.index("-resolution")
        assert cmd[res_idx + 1] == "average"

    def test_build_vrt_falls_back_to_python_writer_when_cli_missing(self, tmp_path):
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        src_a = tmp_path / "a.tif"
        src_b = tmp_path / "b.tif"
        for path, origin_x in ((src_a, 0), (src_b, 5)):
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=5,
                height=5,
                count=1,
                dtype="uint8",
                crs="EPSG:4326",
                transform=from_origin(origin_x, 5, 1, 1),
            ) as dataset:
                dataset.write(np.ones((1, 5, 5), dtype="uint8"))

        output = tmp_path / "out.vrt"
        with patch(
            "app.processing.raster.vrt.subprocess.run", side_effect=FileNotFoundError()
        ):
            result = build_vrt(
                "mosaic",
                [str(src_a), str(src_b)],
                str(output),
                "finest",
            )

        assert result == str(output)
        with rasterio.open(output) as dataset:
            assert dataset.count == 1
            assert dataset.width == 10
            assert dataset.height == 5


# ---------------------------------------------------------------------------
# TestResolveSourcePath
# ---------------------------------------------------------------------------


class TestResolveSourcePath:
    """Test resolve_vrt_source_path for local and S3 storage."""

    def test_local_storage_returns_filesystem_path(self):
        mock_settings = MagicMock()
        mock_settings.storage_provider = "local"
        mock_settings.upload_staging_dir = "/data/staging"

        with patch("app.processing.raster.vrt.settings", mock_settings):
            path = resolve_vrt_source_path("rasters/abc/source.cog.tif")

        assert path == "/data/staging/rasters/abc/source.cog.tif"

    def test_s3_storage_returns_vsis3_path(self):
        mock_settings = MagicMock()
        mock_settings.storage_provider = "s3"
        mock_settings.s3_bucket = "my-geolens-bucket"

        with patch("app.processing.raster.vrt.settings", mock_settings):
            path = resolve_vrt_source_path("rasters/abc/source.cog.tif")

        assert path == "/vsis3/my-geolens-bucket/rasters/abc/source.cog.tif"

    def test_s3_path_uses_permanent_path_not_presigned(self):
        """S3 paths must be permanent /vsis3/ paths, not presigned URLs."""
        mock_settings = MagicMock()
        mock_settings.storage_provider = "s3"
        mock_settings.s3_bucket = "test-bucket"

        with patch("app.processing.raster.vrt.settings", mock_settings):
            path = resolve_vrt_source_path("rasters/xyz/source.cog.tif")

        assert path.startswith("/vsis3/")
        assert "?" not in path  # no presigned URL query params

    def test_local_path_includes_asset_uri(self):
        mock_settings = MagicMock()
        mock_settings.storage_provider = "local"
        mock_settings.upload_staging_dir = "/mnt/data"

        with patch("app.processing.raster.vrt.settings", mock_settings):
            path = resolve_vrt_source_path("rasters/def/source.cog.tif")

        assert "rasters/def/source.cog.tif" in path


# ---------------------------------------------------------------------------
# TestVrtCreateEndpoint
# ---------------------------------------------------------------------------


class TestVrtCreateEndpoint:
    """Unit tests for the POST /ingest/vrt/create endpoint validation logic."""

    def test_fewer_than_2_sources_returns_422(self):
        """Endpoint must reject requests with fewer than 2 source IDs."""
        from fastapi import HTTPException
        import asyncio

        async def _check():
            from app.processing.ingest.router import create_vrt

            mock_request = MagicMock()
            mock_request.source_dataset_ids = [uuid.uuid4()]  # only 1
            mock_user = MagicMock()
            mock_db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await create_vrt(mock_request, mock_user, mock_db)
            assert exc_info.value.status_code == 422
            assert "2" in str(exc_info.value.detail)

        asyncio.run(_check())

    def test_empty_source_list_returns_422(self):
        """Endpoint must reject empty source_dataset_ids."""
        from fastapi import HTTPException
        import asyncio

        async def _check():
            from app.processing.ingest.router import create_vrt

            mock_request = MagicMock()
            mock_request.source_dataset_ids = []
            mock_user = MagicMock()
            mock_db = MagicMock()

            with pytest.raises(HTTPException) as exc_info:
                await create_vrt(mock_request, mock_user, mock_db)
            assert exc_info.value.status_code == 422

        asyncio.run(_check())

    def test_schema_accepts_two_valid_uuids(self):
        """VrtCreateRequest should accept exactly 2 valid source_dataset_ids."""
        ids = [uuid.uuid4(), uuid.uuid4()]
        req = VrtCreateRequest(
            source_dataset_ids=ids,
            vrt_type="mosaic",
            resolution_strategy="finest",
            title="Two source VRT",
        )
        assert len(req.source_dataset_ids) == 2

    def test_vrt_type_mosaic_is_accepted(self):
        req = VrtCreateRequest(
            source_dataset_ids=[uuid.uuid4(), uuid.uuid4()],
            vrt_type="mosaic",
            resolution_strategy="coarsest",
            title="Mosaic VRT",
        )
        assert req.vrt_type == "mosaic"

    def test_vrt_type_band_stack_is_accepted(self):
        req = VrtCreateRequest(
            source_dataset_ids=[uuid.uuid4(), uuid.uuid4()],
            vrt_type="band_stack",
            resolution_strategy="average",
            title="Band Stack VRT",
        )
        assert req.vrt_type == "band_stack"


# ---------------------------------------------------------------------------
# TestCreateVrtJob — K5 extraction of validation + queuing logic to service layer
# ---------------------------------------------------------------------------


class TestCreateVrtJob:
    """Tests for ``ingest.service.create_vrt_job`` (K5/KISS-10 extraction).

    These exercise the validation paths end-to-end through the service helper
    so the router handler stays a 3-line wrapper with no business logic.
    """

    def _minimal_request(self, *, source_count: int = 2) -> VrtCreateRequest:
        return VrtCreateRequest(
            source_dataset_ids=[uuid.uuid4() for _ in range(source_count)],
            vrt_type="mosaic",
            resolution_strategy="finest",
            title="Service Test VRT",
            summary="Test",
        )

    def test_rejects_fewer_than_two_sources(self):
        """< 2 sources → 422 HTTPException, no DB touch, no task deferred."""
        import asyncio

        from fastapi import HTTPException
        from unittest.mock import AsyncMock

        from app.processing.ingest.service import create_vrt_job

        async def _check():
            mock_db = AsyncMock()
            mock_user = MagicMock()
            request = self._minimal_request(source_count=1)

            with pytest.raises(HTTPException) as exc_info:
                await create_vrt_job(mock_db, request, mock_user)
            assert exc_info.value.status_code == 422
            assert "2" in str(exc_info.value.detail)
            # Should fail fast before hitting the DB.
            mock_db.execute.assert_not_called()

        asyncio.run(_check())

    def test_rejects_missing_source_dataset(self):
        """Source in request but not in DB → 422 with the missing UUID in detail."""
        import asyncio

        from fastapi import HTTPException
        from unittest.mock import AsyncMock

        from app.processing.ingest.service import create_vrt_job

        async def _check():
            mock_db = AsyncMock()
            # DB returns empty for the source lookup
            empty_result = MagicMock()
            empty_scalars = MagicMock()
            empty_scalars.all.return_value = []
            empty_result.scalars.return_value = empty_scalars
            mock_db.execute = AsyncMock(return_value=empty_result)

            mock_user = MagicMock()
            request = self._minimal_request()

            with pytest.raises(HTTPException) as exc_info:
                await create_vrt_job(mock_db, request, mock_user)
            assert exc_info.value.status_code == 422
            # Missing UUID should appear in the detail message
            missing_id = request.source_dataset_ids[0]
            assert str(missing_id) in str(exc_info.value.detail)

        asyncio.run(_check())

    def test_rejects_incompatible_sources(self):
        """Compatibility validation failure → 422 with structured error list."""
        import asyncio

        from fastapi import HTTPException
        from unittest.mock import AsyncMock, patch

        from app.processing.ingest.service import create_vrt_job

        async def _check():
            mock_db = AsyncMock()
            request = self._minimal_request()

            # Build assets that "match" all the requested dataset IDs.
            assets = []
            for sid in request.source_dataset_ids:
                asset = MagicMock()
                asset.dataset_id = sid
                assets.append(asset)

            lookup_result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = assets
            lookup_result.scalars.return_value = scalars
            mock_db.execute = AsyncMock(return_value=lookup_result)

            # Mock validate_sources to return a compatibility error.
            fake_error = MagicMock()
            fake_error.model_dump.return_value = {
                "code": "crs_mismatch",
                "message": "CRS mismatch between sources",
            }

            with patch(
                "app.processing.raster.validation.validate_sources",
                return_value=[fake_error],
            ):
                mock_user = MagicMock()
                with pytest.raises(HTTPException) as exc_info:
                    await create_vrt_job(mock_db, request, mock_user)
                assert exc_info.value.status_code == 422
                detail = exc_info.value.detail
                assert isinstance(detail, list)
                assert detail[0]["code"] == "crs_mismatch"

        asyncio.run(_check())

    def test_happy_path_creates_job_and_defers_task(self):
        """Valid request → IngestJob created, user_metadata populated, task deferred."""
        import asyncio

        from unittest.mock import AsyncMock, patch

        from app.processing.ingest.service import create_vrt_job

        async def _check():
            mock_db = AsyncMock()
            request = self._minimal_request()

            # Mock DB lookup to return matching assets.
            assets = []
            for sid in request.source_dataset_ids:
                asset = MagicMock()
                asset.dataset_id = sid
                assets.append(asset)

            lookup_result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = assets
            lookup_result.scalars.return_value = scalars
            mock_db.execute = AsyncMock(return_value=lookup_result)
            mock_db.commit = AsyncMock()

            # Mock create_ingest_job to return a stub job with a uuid.
            stub_job = MagicMock()
            stub_job.id = uuid.uuid4()
            stub_job.user_metadata = None

            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            mock_defer = AsyncMock()

            with (
                patch(
                    "app.processing.raster.validation.validate_sources",
                    return_value=[],
                ),
                patch(
                    "app.processing.ingest.service.create_ingest_job",
                    new=AsyncMock(return_value=stub_job),
                ),
                patch(
                    "app.processing.ingest.tasks.ingest_vrt",
                    defer_async=mock_defer,
                ),
            ):
                result = await create_vrt_job(mock_db, request, mock_user)

            # Returns the job record
            assert result is stub_job
            # user_metadata populated with title/summary/visibility/vrt_type
            assert stub_job.user_metadata["vrt_type"] == "mosaic"
            assert stub_job.user_metadata["title"] == "Service Test VRT"
            # Defer was called with a JSON-encoded source id list
            mock_defer.assert_awaited_once()
            kwargs = mock_defer.await_args.kwargs
            assert kwargs["vrt_type"] == "mosaic"
            assert kwargs["resolution_strategy"] == "finest"
            assert kwargs["job_id"] == str(stub_job.id)
            import json as _json

            source_ids_passed = _json.loads(kwargs["source_dataset_ids"])
            assert len(source_ids_passed) == len(request.source_dataset_ids)

        asyncio.run(_check())

    def test_defer_failure_marks_job_failed_and_raises_503(self):
        """RESILIENCE-2: defer_async raising must flip the committed job to failed.

        Regression for the orphan-job bug where a Procrastinate outage left
        the pending IngestJob row dangling for 60 minutes (PENDING_TIMEOUT)
        before stale-cleanup caught up. The helper must mark the job failed
        before re-raising so /jobs listings reflect the real state and the
        user gets a clean 503 instead of a generic 500.
        """
        import asyncio

        from fastapi import HTTPException
        from unittest.mock import AsyncMock, patch

        from app.processing.ingest.service import create_vrt_job

        async def _check():
            mock_db = AsyncMock()
            request = self._minimal_request()

            assets = []
            for sid in request.source_dataset_ids:
                asset = MagicMock()
                asset.dataset_id = sid
                assets.append(asset)

            lookup_result = MagicMock()
            scalars = MagicMock()
            scalars.all.return_value = assets
            lookup_result.scalars.return_value = scalars
            mock_db.execute = AsyncMock(return_value=lookup_result)
            mock_db.commit = AsyncMock()

            stub_job = MagicMock()
            stub_job.id = uuid.uuid4()
            stub_job.user_metadata = None
            stub_job.status = "pending"

            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            # Simulate Procrastinate being unreachable.
            failing_defer = AsyncMock(
                side_effect=RuntimeError("procrastinate unreachable")
            )

            with (
                patch(
                    "app.processing.raster.validation.validate_sources",
                    return_value=[],
                ),
                patch(
                    "app.processing.ingest.service.create_ingest_job",
                    new=AsyncMock(return_value=stub_job),
                ),
                patch(
                    "app.processing.ingest.tasks.ingest_vrt",
                    defer_async=failing_defer,
                ),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await create_vrt_job(mock_db, request, mock_user)

            # Propagated as 503 so the frontend can retry cleanly.
            assert exc_info.value.status_code == 503
            # Job was marked failed before the exception propagated.
            assert stub_job.status == "failed"
            assert stub_job.error_message is not None
            assert "procrastinate unreachable" in stub_job.error_message
            assert stub_job.completed_at is not None
            # Two commits: one after create_ingest_job, one after flipping
            # the job to failed. Verifies the failed state is durable.
            assert mock_db.commit.await_count == 2

        asyncio.run(_check())

    def test_router_wrapper_delegates_to_service(self):
        """After K5, router.create_vrt is a 3-line wrapper around create_vrt_job."""
        import asyncio

        from unittest.mock import AsyncMock, patch

        from app.processing.ingest.router import create_vrt

        async def _check():
            request = VrtCreateRequest(
                source_dataset_ids=[uuid.uuid4(), uuid.uuid4()],
                vrt_type="band_stack",
                resolution_strategy="coarsest",
                title="Router Delegation Test",
            )
            mock_user = MagicMock()
            mock_db = AsyncMock()

            fake_job = MagicMock()
            fake_job.id = uuid.uuid4()

            with patch(
                "app.processing.ingest.service.create_vrt_job",
                new=AsyncMock(return_value=fake_job),
            ) as mock_svc:
                response = await create_vrt(request, mock_user, mock_db)

            # The router hands the request/user/db straight to the service.
            mock_svc.assert_awaited_once_with(mock_db, request, mock_user)
            # And wraps the returned job id in a VrtCreateResponse.
            assert response.job_id == fake_job.id

        asyncio.run(_check())
