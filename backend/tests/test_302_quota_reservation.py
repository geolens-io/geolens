"""Atomic dataset-count reservation tests (fix #302).

The upload-time check_upload_quota is a non-atomic pre-check: the Record
rows it counts are created later by the ingest worker, so concurrent
uploads could overshoot max_datasets_per_user. reserve_dataset_slot is the
authoritative check at Record-creation time, under a per-user advisory
lock.

Unit tests are mock-based (same pattern as test_1224_quota_service.py).
The facade test runs against the real test DB (same pattern as
test_1224_ingest_quota_enforcement.py).

Run: cd backend && set -a && source ../.env.test && set +a &&
     uv run pytest tests/test_302_quota_reservation.py -x -v
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.modules.quota.service import (
    DatasetQuotaExceededError,
    reserve_dataset_slot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_db(dataset_count: int = 0) -> AsyncMock:
    """Return a mock AsyncSession whose execute() returns the given count."""
    row = MagicMock()
    row.bytes_used = 0
    row.dataset_count = dataset_count

    result = MagicMock()
    result.one.return_value = row

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _patch_caps(count_cap: int):
    """Patch both PersistentConfig gets used along the reservation path."""
    return (
        patch(
            "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
            new_callable=AsyncMock,
            return_value=count_cap,
        ),
        patch(
            "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
            new_callable=AsyncMock,
            return_value=0,
        ),
    )


# ---------------------------------------------------------------------------
# Unit tests for reserve_dataset_slot
# ---------------------------------------------------------------------------


class TestReserveDatasetSlot:
    async def test_unlimited_cap_is_noop(self) -> None:
        """cap=0 (default) → returns without touching the DB at all."""
        db = _make_mock_db()
        p_count, p_storage = _patch_caps(0)
        with p_count, p_storage:
            await reserve_dataset_slot(db, uuid.uuid4())

        db.execute.assert_not_awaited()

    async def test_under_cap_does_not_raise(self) -> None:
        """count=4, cap=5 → slot reserved, no raise."""
        db = _make_mock_db(dataset_count=4)
        p_count, p_storage = _patch_caps(5)
        with p_count, p_storage:
            await reserve_dataset_slot(db, uuid.uuid4())

    async def test_takes_advisory_lock_before_counting(self) -> None:
        """The per-user pg_advisory_xact_lock is the first statement executed."""
        db = _make_mock_db(dataset_count=0)
        p_count, p_storage = _patch_caps(5)
        with p_count, p_storage:
            await reserve_dataset_slot(db, uuid.uuid4())

        first_sql = str(db.execute.await_args_list[0].args[0])
        assert "pg_advisory_xact_lock" in first_sql

    async def test_at_cap_raises(self) -> None:
        """count=5, cap=5 → DatasetQuotaExceededError with a usable message."""
        db = _make_mock_db(dataset_count=5)
        p_count, p_storage = _patch_caps(5)
        with p_count, p_storage:
            with pytest.raises(DatasetQuotaExceededError) as exc_info:
                await reserve_dataset_slot(db, uuid.uuid4())

        assert "Dataset quota exceeded: 5 of 5" in str(exc_info.value)

    async def test_already_over_cap_raises(self) -> None:
        """Rows that pre-date enforcement and overshoot still hard-stop new ones."""
        db = _make_mock_db(dataset_count=7)
        p_count, p_storage = _patch_caps(5)
        with p_count, p_storage:
            with pytest.raises(DatasetQuotaExceededError):
                await reserve_dataset_slot(db, uuid.uuid4())


# ---------------------------------------------------------------------------
# DB-backed facade enforcement
# ---------------------------------------------------------------------------


class TestFacadeEnforcement:
    async def test_create_dataset_rejects_when_cap_reached(
        self,
        client: AsyncClient,
        test_db_session,
        admin_auth_header: dict,
    ) -> None:
        """The datasets facade enforces the cap at Record creation.

        Uses a freshly created user (zero owned datasets) so the count is
        deterministic regardless of what other tests seeded for admin.
        The second create sees the first, still-uncommitted Record in the
        same transaction — exactly the atomicity the upload-time pre-check
        lacks.
        """
        from app.modules.catalog.datasets.domain.service import create_dataset

        resp = await client.post(
            "/admin/users/",
            json={
                "username": f"quota302_{uuid.uuid4().hex[:8]}",
                "password": "TestPass1234!",
                "role": "editor",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        user_id = uuid.UUID(resp.json()["id"])

        p_count, p_storage = _patch_caps(1)
        with p_count, p_storage:
            await create_dataset(
                test_db_session,
                table_name=f"quota302_{uuid.uuid4().hex[:12]}",
                title="quota-302 first dataset",
                created_by=user_id,
            )

            with pytest.raises(DatasetQuotaExceededError) as exc_info:
                await create_dataset(
                    test_db_session,
                    table_name=f"quota302_{uuid.uuid4().hex[:12]}",
                    title="quota-302 second dataset",
                    created_by=user_id,
                )

        assert "Dataset quota exceeded: 1 of 1" in str(exc_info.value)
        await test_db_session.rollback()
