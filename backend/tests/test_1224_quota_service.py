"""Unit tests for the quota service module (QUOTA-01..03).

These are pure unit tests — they patch the DB execute result and
PersistentConfig.get so no real database is needed.

Run: cd backend && set -a && source ../.env.test && set +a &&
     uv run pytest tests/test_1224_quota_service.py -x -v
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db(bytes_used: int = 0, dataset_count: int = 0) -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns the given aggregate."""
    row = MagicMock()
    row.bytes_used = bytes_used
    row.dataset_count = dataset_count

    result = MagicMock()
    result.one.return_value = row

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _make_request() -> Request:
    """Return a minimal mock Request for enforce_limit calls."""
    req = MagicMock(spec=Request)
    req.state = MagicMock()
    return req


# ---------------------------------------------------------------------------
# Tests for get_user_quota_usage
# ---------------------------------------------------------------------------


class TestGetUserQuotaUsage:
    async def test_returns_correct_usage(self) -> None:
        """get_user_quota_usage returns bytes_used and dataset_count from SQL."""
        db = _make_mock_db(bytes_used=1_000_000, dataset_count=3)
        user_id = uuid.uuid4()

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=10_000_000,
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=10,
            ),
        ):
            from app.modules.quota.service import get_user_quota_usage

            usage = await get_user_quota_usage(db, user_id)

        assert usage.bytes_used == 1_000_000
        assert usage.dataset_count == 3
        assert usage.storage_cap == 10_000_000
        assert usage.count_cap == 10

    async def test_no_uploads_returns_zeros(self) -> None:
        """A user with no uploads returns bytes_used=0, dataset_count=0."""
        db = _make_mock_db(bytes_used=0, dataset_count=0)
        user_id = uuid.uuid4()

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            from app.modules.quota.service import get_user_quota_usage

            usage = await get_user_quota_usage(db, user_id)

        assert usage.bytes_used == 0
        assert usage.dataset_count == 0


# ---------------------------------------------------------------------------
# Tests for check_upload_quota
# ---------------------------------------------------------------------------


class TestCheckUploadQuota:
    async def test_under_cap_does_not_raise(self) -> None:
        """under_cap: bytes=5MB, cap=10MB → no raise."""
        db = _make_mock_db(bytes_used=5_000_000, dataset_count=2)
        user_id = uuid.uuid4()
        request = _make_request()

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=10_000_000,
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch(
                "app.modules.quota.service.enforce_limit",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.quota.service import check_upload_quota

            # Should not raise
            await check_upload_quota(db, user_id, 1_000_000, request)

    async def test_byte_cap_exceeded_raises_413(self) -> None:
        """byte_cap_exceeded: bytes=9MB, incoming=2MB, cap=10MB → HTTP 413."""
        db = _make_mock_db(bytes_used=9_000_000, dataset_count=2)
        user_id = uuid.uuid4()
        request = _make_request()

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=10_000_000,
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=10,
            ),
            patch(
                "app.modules.quota.service.enforce_limit",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.quota.service import check_upload_quota

            with pytest.raises(HTTPException) as exc_info:
                await check_upload_quota(db, user_id, 2_000_000, request)

        assert exc_info.value.status_code == 413
        assert "Storage quota exceeded" in exc_info.value.detail

    async def test_count_cap_exceeded_raises_422(self) -> None:
        """count_cap_exceeded: count=5, cap=5 → HTTP 422."""
        db = _make_mock_db(bytes_used=1_000, dataset_count=5)
        user_id = uuid.uuid4()
        request = _make_request()

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=10_000_000,
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "app.modules.quota.service.enforce_limit",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.quota.service import check_upload_quota

            with pytest.raises(HTTPException) as exc_info:
                await check_upload_quota(db, user_id, 100, request)

        assert exc_info.value.status_code == 422
        assert "Dataset quota exceeded" in exc_info.value.detail

    async def test_default_unlimited_never_raises(self) -> None:
        """default_unlimited: cap=0 for both → never raises even with large values.

        QUOTA-03 SC-3 guarantee: default 0 = unlimited, zero change for
        existing self-hosters.
        """
        db = _make_mock_db(bytes_used=500_000_000, dataset_count=99_999)
        user_id = uuid.uuid4()
        request = _make_request()

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,  # default unlimited
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,  # default unlimited
            ),
            patch(
                "app.modules.quota.service.enforce_limit",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.quota.service import check_upload_quota

            # Must NOT raise even with huge values
            await check_upload_quota(db, user_id, 999_999_999, request)

    async def test_reupload_also_checked(self) -> None:
        """reupload_also_checked: same function works for both upload and reupload.

        check_upload_quota is path-agnostic — it is called from both the
        upload and reupload routes.  This test verifies the byte cap is
        applied regardless of the call site.
        """
        db = _make_mock_db(bytes_used=0, dataset_count=0)
        user_id = uuid.uuid4()
        request = _make_request()

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=1,  # 1-byte cap
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.modules.quota.service.enforce_limit",
                new_callable=AsyncMock,
            ),
        ):
            from app.modules.quota.service import check_upload_quota

            # Simulating a reupload call — same function, different call site
            with pytest.raises(HTTPException) as exc_info:
                await check_upload_quota(db, user_id, 100, request)

        assert exc_info.value.status_code == 413
        assert "Storage quota exceeded" in exc_info.value.detail
