"""Tests for VRT creation endpoint and task (Phase 173-02).

Covers:
- VrtCreateRequest / VrtCreateResponse schema validation
- build_vrt dispatch (mosaic vs band_stack) subprocess behavior
- resolve_vrt_source_path for local and S3 storage
- POST /ingest/vrt/create endpoint: source count and existence validation

All tests are pure unit tests — no DB, no real files, no network.
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.ingest.schemas import VrtCreateRequest, VrtCreateResponse
from app.raster.vrt import build_vrt, resolve_vrt_source_path


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
        req = VrtCreateRequest(**_valid_vrt_request(
            vrt_type="band_stack",
            resolution_strategy="coarsest",
        ))
        assert req.vrt_type == "band_stack"

    def test_valid_mosaic_average_passes(self):
        req = VrtCreateRequest(**_valid_vrt_request(resolution_strategy="average"))
        assert req.resolution_strategy == "average"

    def test_invalid_vrt_type_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            VrtCreateRequest(**_valid_vrt_request(vrt_type="invalid"))
        assert "vrt_type" in str(exc_info.value).lower() or "literal" in str(exc_info.value).lower()

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

        with patch("app.raster.vrt.subprocess.run", return_value=mock_result) as mock_run:
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

        with patch("app.raster.vrt.subprocess.run", return_value=mock_result) as mock_run:
            result = build_vrt("band_stack", sources, output, "coarsest")

        assert result == output
        cmd = mock_run.call_args[0][0]
        assert "-separate" in cmd
        assert "lowest" in cmd  # "coarsest" maps to "lowest"

    def test_build_mosaic_vrt_raises_on_nonzero_returncode(self):
        mock_result = _make_subprocess_result(returncode=1, stderr="gdalbuildvrt error")

        with patch("app.raster.vrt.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="gdalbuildvrt failed"):
                build_vrt("mosaic", ["/a.tif"], "/out.vrt", "finest")

    def test_build_band_stack_vrt_raises_on_nonzero_returncode(self):
        mock_result = _make_subprocess_result(returncode=1, stderr="gdalbuildvrt error")

        with patch("app.raster.vrt.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="gdalbuildvrt failed"):
                build_vrt("band_stack", ["/a.tif"], "/out.vrt", "finest")

    def test_resolution_strategy_finest_maps_to_highest(self):
        mock_result = _make_subprocess_result(returncode=0)

        with patch("app.raster.vrt.subprocess.run", return_value=mock_result) as mock_run:
            build_vrt("mosaic", ["/a.tif"], "/out.vrt", "finest")

        cmd = mock_run.call_args[0][0]
        res_idx = cmd.index("-resolution")
        assert cmd[res_idx + 1] == "highest"

    def test_resolution_strategy_coarsest_maps_to_lowest(self):
        mock_result = _make_subprocess_result(returncode=0)

        with patch("app.raster.vrt.subprocess.run", return_value=mock_result) as mock_run:
            build_vrt("mosaic", ["/a.tif"], "/out.vrt", "coarsest")

        cmd = mock_run.call_args[0][0]
        res_idx = cmd.index("-resolution")
        assert cmd[res_idx + 1] == "lowest"

    def test_resolution_strategy_average_maps_to_average(self):
        mock_result = _make_subprocess_result(returncode=0)

        with patch("app.raster.vrt.subprocess.run", return_value=mock_result) as mock_run:
            build_vrt("mosaic", ["/a.tif"], "/out.vrt", "average")

        cmd = mock_run.call_args[0][0]
        res_idx = cmd.index("-resolution")
        assert cmd[res_idx + 1] == "average"


# ---------------------------------------------------------------------------
# TestResolveSourcePath
# ---------------------------------------------------------------------------

class TestResolveSourcePath:
    """Test resolve_vrt_source_path for local and S3 storage."""

    def test_local_storage_returns_filesystem_path(self):
        mock_settings = MagicMock()
        mock_settings.storage_provider = "local"
        mock_settings.upload_staging_dir = "/data/staging"

        with patch("app.raster.vrt.settings", mock_settings):
            path = resolve_vrt_source_path("rasters/abc/source.cog.tif")

        assert path == "/data/staging/rasters/abc/source.cog.tif"

    def test_s3_storage_returns_vsis3_path(self):
        mock_settings = MagicMock()
        mock_settings.storage_provider = "s3"
        mock_settings.s3_bucket = "my-geolens-bucket"

        with patch("app.raster.vrt.settings", mock_settings):
            path = resolve_vrt_source_path("rasters/abc/source.cog.tif")

        assert path == "/vsis3/my-geolens-bucket/rasters/abc/source.cog.tif"

    def test_s3_path_uses_permanent_path_not_presigned(self):
        """S3 paths must be permanent /vsis3/ paths, not presigned URLs."""
        mock_settings = MagicMock()
        mock_settings.storage_provider = "s3"
        mock_settings.s3_bucket = "test-bucket"

        with patch("app.raster.vrt.settings", mock_settings):
            path = resolve_vrt_source_path("rasters/xyz/source.cog.tif")

        assert path.startswith("/vsis3/")
        assert "?" not in path  # no presigned URL query params

    def test_local_path_includes_asset_uri(self):
        mock_settings = MagicMock()
        mock_settings.storage_provider = "local"
        mock_settings.upload_staging_dir = "/mnt/data"

        with patch("app.raster.vrt.settings", mock_settings):
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
            from app.ingest.router import create_vrt
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
            from app.ingest.router import create_vrt
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
