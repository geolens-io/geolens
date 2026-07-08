"""Regression tests for completion-time presigned upload size checks."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.processing.ingest import presigned


class _FakeStorage:
    def __init__(self, actual_size: int) -> None:
        self.actual_size = actual_size
        self.deleted: list[str] = []
        self.aborted: list[tuple[str, str]] = []

    async def size(self, key: str) -> int:
        return self.actual_size

    async def delete(self, key: str) -> None:
        self.deleted.append(key)

    def abort_multipart_upload(self, key: str, upload_id: str) -> None:
        self.aborted.append((key, upload_id))


@pytest.mark.anyio
async def test_presigned_completion_rejects_declared_size_mismatch(monkeypatch):
    storage = _FakeStorage(actual_size=20)
    monkeypatch.setattr(presigned.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=1))
    quota_check = AsyncMock()
    monkeypatch.setattr(presigned, "check_upload_quota", quota_check)

    with pytest.raises(HTTPException) as exc:
        await presigned.verify_completed_presigned_upload(
            db=object(),
            storage=storage,
            key="staging/job/file.geojson",
            expected_size=10,
            user_id="00000000-0000-0000-0000-000000000001",
            request=object(),
            job_id="00000000-0000-0000-0000-000000000002",
        )

    assert exc.value.status_code == 422
    assert storage.deleted == ["staging/job/file.geojson"]
    quota_check.assert_not_called()


@pytest.mark.anyio
async def test_presigned_completion_rejects_actual_size_over_max(monkeypatch):
    storage = _FakeStorage(actual_size=2 * 1024 * 1024)
    monkeypatch.setattr(presigned.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=1))
    quota_check = AsyncMock()
    monkeypatch.setattr(presigned, "check_upload_quota", quota_check)

    with pytest.raises(HTTPException) as exc:
        await presigned.verify_completed_presigned_upload(
            db=object(),
            storage=storage,
            key="staging/job/file.geojson",
            expected_size=2 * 1024 * 1024,
            user_id="00000000-0000-0000-0000-000000000001",
            request=object(),
            job_id="00000000-0000-0000-0000-000000000002",
        )

    assert exc.value.status_code == 422
    assert storage.deleted == ["staging/job/file.geojson"]
    quota_check.assert_not_called()


@pytest.mark.anyio
async def test_presigned_completion_accepts_matching_size(monkeypatch):
    storage = _FakeStorage(actual_size=10)
    monkeypatch.setattr(presigned.UPLOAD_MAX_SIZE_MB, "get", AsyncMock(return_value=1))
    quota_check = AsyncMock()
    monkeypatch.setattr(presigned, "check_upload_quota", quota_check)

    actual = await presigned.verify_completed_presigned_upload(
        db=object(),
        storage=storage,
        key="staging/job/file.geojson",
        expected_size=10,
        user_id="00000000-0000-0000-0000-000000000001",
        request=object(),
        job_id="00000000-0000-0000-0000-000000000002",
    )

    assert actual == 10
    assert storage.deleted == []
    quota_check.assert_awaited_once()


@pytest.mark.anyio
async def test_presigned_abort_multipart_upload_calls_provider() -> None:
    storage = _FakeStorage(actual_size=10)

    await presigned.abort_presigned_multipart_upload(
        storage,
        key="staging/job/file.geojson",
        upload_id="upload-1",
        job_id="00000000-0000-0000-0000-000000000002",
    )

    assert storage.aborted == [("staging/job/file.geojson", "upload-1")]
