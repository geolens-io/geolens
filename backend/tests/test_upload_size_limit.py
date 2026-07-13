"""Unit tests for IA-P0-02: chunked size enforcement in save_upload_file.

Pins the new max_size_bytes parameter behavior, including:
- Local mode: 413 raised once cumulative chunk total exceeds the limit
- Local mode: partial file cleaned up on 413
- S3 mode: 413 raised before storage.put() is called
- Both modes: no max_size_bytes → no enforcement (backwards compatible)

Requirement: IA-P0-02
Phase: 1066
"""

import asyncio
import uuid
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
            result = await save_upload_file(file, "job-ok", max_size_bytes=2048)

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
                await save_upload_file(file, "job-too-big", max_size_bytes=100 * 1024)

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

    @pytest.mark.asyncio
    async def test_cancelled_upload_removes_partial_file(self, tmp_path):
        """A client disconnect cannot strand a partially written local upload."""
        from app.processing.ingest.service import save_upload_file

        second_read_started = asyncio.Event()
        never_finish = asyncio.Event()

        class BlockingUpload:
            filename = "cancelled.geojson"

            def __init__(self) -> None:
                self.read_count = 0

            async def read(self, _size: int) -> bytes:
                self.read_count += 1
                if self.read_count == 1:
                    return b"partial upload"
                second_read_started.set()
                await never_finish.wait()
                return b""

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "local"
            mock_settings.upload_staging_dir = str(tmp_path)
            task = asyncio.create_task(
                save_upload_file(BlockingUpload(), "job-cancelled", max_size_bytes=1024)  # type: ignore[arg-type]
            )
            await second_read_started.wait()
            assert list(tmp_path.glob("job-cancelled_*"))

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert list(tmp_path.glob("job-cancelled_*")) == []


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
            with patch("app.platform.storage.get_storage", return_value=mock_storage):
                with pytest.raises(HTTPException) as exc:
                    await save_upload_file(
                        file, "job-s3-toobig", max_size_bytes=50 * 1024
                    )

        assert exc.value.status_code == 413
        # storage.put MUST NOT have been called — we rejected before upload.
        mock_storage.put.assert_not_called()


@pytest.mark.asyncio
async def test_upload_commit_failure_cleans_owned_staged_file(tmp_path):
    from app.processing.ingest import router

    staged = tmp_path / "job_commit-failure.geojson"
    staged.write_bytes(b"{}")
    job = MagicMock(id=uuid.uuid4(), user_metadata={})
    db = AsyncMock()
    db.commit.side_effect = RuntimeError("commit failed")
    cleanup = AsyncMock()

    with (
        patch.object(
            router,
            "_get_allowed_extensions_safely",
            AsyncMock(return_value=[".geojson"]),
        ),
        patch.object(router.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=10)),
        patch.object(router, "check_upload_quota", AsyncMock()),
        patch.object(router, "create_ingest_job", AsyncMock(return_value=job)),
        patch.object(router, "save_upload_file", AsyncMock(return_value=staged)),
        patch.object(router, "validate_file_content"),
        patch.object(router, "_stamp_raster_metadata", AsyncMock()),
        patch.object(router, "_cleanup_saved_upload", cleanup),
    ):
        with pytest.raises(HTTPException) as exc:
            await router.upload_file(
                MagicMock(),
                _fake_upload("commit-failure.geojson", b"{}"),
                MagicMock(id=uuid.uuid4()),
                db,
            )

    assert exc.value.status_code == 500
    cleanup.assert_awaited_once_with(staged, str(job.id))


@pytest.mark.asyncio
async def test_presigned_multipart_url_failure_aborts_initialized_session():
    from app.processing.ingest import router
    from app.processing.ingest.schemas import PresignedUploadRequest

    job = MagicMock(id=uuid.uuid4(), user_metadata={})
    db = AsyncMock()
    storage = MagicMock()
    storage.initiate_multipart_upload.return_value = "upload-1"
    storage.generate_presigned_part_url.side_effect = RuntimeError("presign failed")
    abort = AsyncMock()

    with (
        patch.object(router.settings, "storage_provider", "s3"),
        patch.object(router.settings, "presigned_multipart_threshold_mb", 1),
        patch.object(
            router,
            "_get_allowed_extensions_safely",
            AsyncMock(return_value=[".geojson"]),
        ),
        patch.object(router.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=10)),
        patch.object(router, "check_upload_quota", AsyncMock()),
        patch.object(router, "create_ingest_job", AsyncMock(return_value=job)),
        patch.object(router, "get_storage", return_value=storage),
        patch.object(router, "abort_presigned_multipart_upload", abort),
    ):
        with pytest.raises(HTTPException) as exc:
            await router.request_presigned_upload(
                PresignedUploadRequest(
                    filename="roads.geojson",
                    file_size=2 * 1024 * 1024,
                    content_type="application/geo+json",
                ),
                MagicMock(),
                MagicMock(id=uuid.uuid4()),
                db,
            )

    assert exc.value.status_code == 502
    abort.assert_awaited_once()


@pytest.mark.asyncio
async def test_thread_drain_capture_preserves_result_for_cancel_cleanup():
    import threading

    from app.core.async_io import run_in_thread_draining_capture_cancel

    started = threading.Event()
    release = threading.Event()

    def create_resource() -> str:
        started.set()
        release.wait(timeout=5)
        return "upload-id-created-after-cancel"

    task = asyncio.create_task(run_in_thread_draining_capture_cancel(create_resource))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    release.set()

    result, cancellation = await task
    assert result == "upload-id-created-after-cancel"
    assert isinstance(cancellation, asyncio.CancelledError)

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
            with patch("app.platform.storage.get_storage", return_value=mock_storage):
                result = await save_upload_file(
                    file, "job-s3-ok", max_size_bytes=10 * 1024
                )

        assert result.startswith("staging/job-s3-ok/")
        mock_storage.put.assert_called_once()

    @pytest.mark.asyncio
    async def test_s3_cancellation_drains_put_and_deletes_completed_object(self):
        """Cancellation cannot close the spool under a live SDK upload thread."""
        from app.processing.ingest.service import save_upload_file

        payload = b"ok" * 100
        file = _fake_upload("cancelled.tif", payload)
        put_started = asyncio.Event()
        finish_put = asyncio.Event()
        mock_storage = MagicMock()

        async def slow_put(_key, data):
            assert data.read(2) == b"ok"
            data.seek(0)
            put_started.set()
            await finish_put.wait()
            assert data.read() == payload

        mock_storage.put = AsyncMock(side_effect=slow_put)
        mock_storage.delete = AsyncMock()

        with patch("app.processing.ingest.service.settings") as mock_settings:
            mock_settings.storage_provider = "s3"
            with patch("app.platform.storage.get_storage", return_value=mock_storage):
                task = asyncio.create_task(
                    save_upload_file(file, "job-s3-cancelled", max_size_bytes=10 * 1024)
                )
                await put_started.wait()
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()

                finish_put.set()
                with pytest.raises(asyncio.CancelledError):
                    await task

        mock_storage.delete.assert_awaited_once_with(
            "staging/job-s3-cancelled/cancelled.tif"
        )
