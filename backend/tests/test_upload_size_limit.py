"""Unit tests for IA-P0-02: chunked size enforcement in save_upload_file.

Pins the new max_size_bytes parameter behavior, including:
- Local mode: 413 raised once cumulative chunk total exceeds the limit
- Local mode: partial file cleaned up on 413
- S3 mode: 413 raised before storage.put() is called
- Both modes: no max_size_bytes → no enforcement (backwards compatible)

Requirement: IA-P0-02
Phase: 1066
"""

from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers


def _fake_upload(name: str, content: bytes) -> UploadFile:
    """Build an UploadFile around the given byte payload."""
    return UploadFile(
        filename=name,
        file=BytesIO(content),
        size=len(content),
        headers=Headers({"content-type": "application/octet-stream"}),
    )


class TestLocalModeSizeLimit:
    """Local-storage path enforcement (`save_upload_file` chunk loop)."""

    @pytest.mark.asyncio
    async def test_under_limit_succeeds(self, tmp_path):
        """Upload smaller than the cap saves successfully."""
        from app.processing.ingest.service import save_upload_file

        payload = b"x" * 1024  # 1 KiB
        file = _fake_upload("ok.geojson", payload)

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "local"
            mock_settings.upload_staging_dir = str(tmp_path)
            result = await save_upload_file(
                file, "job-ok", max_size_bytes=2048
            )

        assert isinstance(result, Path)
        assert result.exists()
        assert result.read_bytes() == payload

    @pytest.mark.asyncio
    async def test_over_limit_raises_413(self, tmp_path):
        """Upload exceeding cap raises 413 and partial file is cleaned up."""
        from app.processing.ingest.service import save_upload_file

        # 200 KiB payload, limit 100 KiB. Read in 64 KiB chunks — exceed
        # detected on the 2nd chunk (128 KiB > 100 KiB).
        payload = b"x" * (200 * 1024)
        file = _fake_upload("toobig.geojson", payload)

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "local"
            mock_settings.upload_staging_dir = str(tmp_path)
            with pytest.raises(HTTPException) as exc:
                await save_upload_file(
                    file, "job-too-big", max_size_bytes=100 * 1024
                )

        assert exc.value.status_code == 413
        assert "exceeds maximum" in exc.value.detail.lower()
        # Partial cleanup: the dest file must not be left on disk
        for p in tmp_path.iterdir():
            assert not p.is_file() or not p.name.startswith("job-too-big_")

    @pytest.mark.asyncio
    async def test_no_limit_param_is_backwards_compatible(self, tmp_path):
        """When max_size_bytes is omitted/None, no size enforcement happens."""
        from app.processing.ingest.service import save_upload_file

        # Large payload, no limit → succeeds.
        payload = b"y" * (500 * 1024)
        file = _fake_upload("nolimit.geojson", payload)

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "local"
            mock_settings.upload_staging_dir = str(tmp_path)
            result = await save_upload_file(file, "job-nolimit")

        assert isinstance(result, Path)
        assert result.exists()
        assert result.read_bytes() == payload


class TestS3ModeSizeLimit:
    """S3-storage path enforcement (`save_upload_file` BytesIO accumulator)."""

    @pytest.mark.asyncio
    async def test_s3_over_limit_raises_413_before_put(self):
        """S3 mode: 413 raised before storage.put() is called."""
        from app.processing.ingest.service import save_upload_file

        # 200 KiB payload, limit 50 KiB. Exceed on 1st chunk.
        payload = b"z" * (200 * 1024)
        file = _fake_upload("toobig.tif", payload)

        mock_storage = MagicMock()
        mock_storage.put = AsyncMock()

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "s3"
            with patch(
                "app.platform.storage.get_storage", return_value=mock_storage
            ):
                with pytest.raises(HTTPException) as exc:
                    await save_upload_file(
                        file, "job-s3-toobig", max_size_bytes=50 * 1024
                    )

        assert exc.value.status_code == 413
        # storage.put MUST NOT have been called — we rejected before upload.
        mock_storage.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_s3_under_limit_calls_put(self):
        """S3 mode: under-limit payload is forwarded to storage.put()."""
        from app.processing.ingest.service import save_upload_file

        payload = b"ok" * 100  # 200 bytes
        file = _fake_upload("ok.tif", payload)

        mock_storage = MagicMock()
        mock_storage.put = AsyncMock()

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "s3"
            with patch(
                "app.platform.storage.get_storage", return_value=mock_storage
            ):
                result = await save_upload_file(
                    file, "job-s3-ok", max_size_bytes=10 * 1024
                )

        assert result.startswith("staging/job-s3-ok/")
        mock_storage.put.assert_called_once()
