"""Regression tests for PERF-001: S3 upload spool-to-disk instead of full in-memory buffer.

Phase 1183 — Plan 01.

RED test: before fix, the S3 branch uses io.BytesIO which never rolls to disk.
GREEN test: after fix, SpooledTemporaryFile spills large files to disk past threshold.

Acceptance criteria:
- Large (> spool threshold) S3 upload: SpooledTemporaryFile rolls to disk (_rolled is True).
- Content delivered to storage.put is byte-correct.
- 413 still fires mid-stream for over-limit uploads; temp file cleaned up on that path.
- Small (< spool threshold) upload stays in memory and content is byte-correct.
- The max_size_bytes=None streaming branch is NOT touched.
"""

import tempfile
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers


def _fake_upload(name: str, content: bytes) -> UploadFile:
    """Build an UploadFile backed by a BytesIO payload."""
    return UploadFile(
        filename=name,
        file=BytesIO(content),
        size=len(content),
        headers=Headers({"content-type": "application/octet-stream"}),
    )


class TestS3SpoolUpload:
    """PERF-001: S3 upload path spools to disk for large files."""

    @pytest.mark.asyncio
    async def test_large_s3_upload_spills_to_disk(self):
        """RED → GREEN: upload larger than _UPLOAD_SPOOL_MAX_BYTES must roll to disk.

        Pre-fix: io.BytesIO never sets _rolled — this assertion fails.
        Post-fix: SpooledTemporaryFile._rolled is True after threshold exceeded.

        The spooled file is closed by save_upload_file after put() returns
        (try/finally cleanup), so we inspect it INSIDE the mock put call,
        before it is closed.
        """
        from app.processing.ingest.service import (
            _UPLOAD_SPOOL_MAX_BYTES,
            save_upload_file,
        )

        # Payload is threshold + 1 byte to guarantee a spill.
        payload = b"A" * (_UPLOAD_SPOOL_MAX_BYTES + 1)
        file = _fake_upload("large.geojson", payload)

        captured_state = {}

        mock_storage = MagicMock()

        async def _capture_put(key, fobj):
            # Inspect BEFORE close — read content and check rollover state.
            captured_state["rolled"] = getattr(fobj, "_rolled", None)
            captured_state["type"] = type(fobj).__name__
            captured_state["content"] = fobj.read()

        mock_storage.put = AsyncMock(side_effect=_capture_put)

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "s3"
            with patch("app.platform.storage.get_storage", return_value=mock_storage):
                result = await save_upload_file(
                    file,
                    "job-spool-large",
                    max_size_bytes=_UPLOAD_SPOOL_MAX_BYTES * 2,  # well above file size
                )

        assert result.startswith("staging/job-spool-large/")
        assert captured_state, "storage.put must be called exactly once"

        # SpooledTemporaryFile.rolled indicates it has spilled to a real temp file.
        assert captured_state["type"] == "SpooledTemporaryFile", (
            f"Expected SpooledTemporaryFile, got {captured_state['type']}"
        )
        assert captured_state["rolled"] is True, (
            "SpooledTemporaryFile must have rolled to disk for a large payload; "
            "_rolled is False — file is still buffered in memory"
        )
        assert captured_state["content"] == payload, (
            "Bytes delivered to storage.put must be byte-correct"
        )

    @pytest.mark.asyncio
    async def test_small_s3_upload_content_correct(self):
        """Small (sub-threshold) upload stays in memory but content is byte-correct."""
        from app.processing.ingest.service import (
            _UPLOAD_SPOOL_MAX_BYTES,
            save_upload_file,
        )

        payload = b"B" * 512  # well below any sane threshold
        file = _fake_upload("small.geojson", payload)

        captured_state = {}

        mock_storage = MagicMock()

        async def _capture_put(key, fobj):
            captured_state["rolled"] = getattr(fobj, "_rolled", None)
            captured_state["type"] = type(fobj).__name__
            captured_state["content"] = fobj.read()

        mock_storage.put = AsyncMock(side_effect=_capture_put)

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "s3"
            with patch("app.platform.storage.get_storage", return_value=mock_storage):
                result = await save_upload_file(
                    file,
                    "job-spool-small",
                    max_size_bytes=_UPLOAD_SPOOL_MAX_BYTES * 2,
                )

        assert result.startswith("staging/job-spool-small/")
        assert captured_state
        assert captured_state["type"] == "SpooledTemporaryFile"
        # Small file: _rolled may be False (still in memory) — that's correct behavior
        assert captured_state["content"] == payload, (
            "Small upload content must be byte-correct"
        )

    @pytest.mark.asyncio
    async def test_413_still_fires_mid_stream_and_put_not_called(self):
        """413 limit still fires mid-stream; storage.put must NOT be called."""
        from app.processing.ingest.service import save_upload_file

        # Very tiny limit so we 413 on the first chunk.
        limit = 100
        payload = b"C" * (200 * 1024)  # 200 KiB — way over limit
        file = _fake_upload("huge.tif", payload)

        mock_storage = MagicMock()
        mock_storage.put = AsyncMock()

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "s3"
            with patch("app.platform.storage.get_storage", return_value=mock_storage):
                with pytest.raises(HTTPException) as exc_info:
                    await save_upload_file(file, "job-413-spool", max_size_bytes=limit)

        assert exc_info.value.status_code == 413
        assert "exceeds maximum" in exc_info.value.detail.lower()
        mock_storage.put.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_max_size_streaming_branch_unchanged(self):
        """max_size_bytes=None branch (else path) still passes file.file directly."""
        from app.processing.ingest.service import save_upload_file

        payload = b"D" * 1024
        file = _fake_upload("stream.geojson", payload)

        mock_storage = MagicMock()
        mock_storage.put = AsyncMock()

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "s3"
            with patch("app.platform.storage.get_storage", return_value=mock_storage):
                result = await save_upload_file(file, "job-no-limit")

        assert result.startswith("staging/job-no-limit/")
        mock_storage.put.assert_called_once()
        # The else branch passes file.file (the raw BytesIO), NOT a SpooledTemporaryFile.
        _, call_kwargs = mock_storage.put.call_args
        positional_args = mock_storage.put.call_args.args
        fobj = (
            positional_args[1] if len(positional_args) > 1 else call_kwargs.get("data")
        )
        assert not isinstance(fobj, tempfile.SpooledTemporaryFile), (
            "else branch must pass file.file directly, not a SpooledTemporaryFile"
        )
