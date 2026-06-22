"""Fail-before/pass-after enforcement boundary tests for per-user upload quotas.

These tests run against the real test DB (same pattern as test_ingest.py):
- save_upload_file and queue_ingest_job are mocked to avoid side effects.
- check_upload_quota and the DB aggregate query are NOT mocked.
- PersistentConfig.get() is patched per test to control cap values.

Requirements verified:
  QUOTA-01 — byte cap → 413
  QUOTA-02 — dataset count cap → 422
  QUOTA-03 — default 0 unlimited → never rejects
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import DatasetAsset
from app.core.config import settings


# ---------------------------------------------------------------------------
# Module-scoped mocks: prevent real file staging and procrastinate deferral
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_quota_ingest_task():
    """Prevent procrastinate task deferral in quota enforcement tests."""
    with patch(
        "app.processing.ingest.router.queue_ingest_job", new_callable=AsyncMock
    ) as mock_task:
        yield mock_task


@pytest.fixture(autouse=True)
def mock_quota_file_save(tmp_path: Path):
    """Save mocked uploads to a temp path so validation sees a real file."""
    with patch(
        "app.processing.ingest.router.save_upload_file", new_callable=AsyncMock
    ) as mock_save:

        async def _save_to_temp(file, job_id: str, **_) -> Path:
            dest = tmp_path / f"{job_id}_{file.filename}"
            dest.write_bytes(await file.read())
            await file.seek(0)
            return dest

        mock_save.side_effect = _save_to_temp
        yield mock_save


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_GEOJSON = b'{"type":"FeatureCollection","features":[]}'


async def _upload_geojson(client: AsyncClient, headers: dict) -> int:
    """POST a minimal GeoJSON to /ingest/upload. Returns HTTP status code."""
    resp = await client.post(
        "/ingest/upload",
        files={"file": ("test.geojson", _GEOJSON, "application/json")},
        headers=headers,
    )
    return resp.status_code


async def _create_record_with_asset(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    size_bytes: int,
) -> None:
    """Insert a Record + Dataset + DatasetAsset row so the quota aggregate sees bytes."""
    table_name = f"quota_test_{uuid.uuid4().hex[:8]}"
    record = Record(
        title="Quota Test Dataset",
        visibility="private",
        record_status="published",
        record_type="vector_dataset",
        created_by=user_id,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="data.geojson",
    )
    session.add(dataset)
    await session.flush()

    asset = DatasetAsset(
        dataset_id=dataset.id,
        key="data",
        href=f"s3://test-bucket/staging/{dataset.id}/data.geojson",
        size_bytes=size_bytes,
    )
    session.add(asset)
    await session.commit()


async def _create_record(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> None:
    """Insert a Record row so the quota aggregate sees an extra dataset count."""
    record = Record(
        title="Quota Count Test Dataset",
        visibility="private",
        record_status="published",
        record_type="vector_dataset",
        created_by=user_id,
    )
    session.add(record)
    await session.commit()


async def _get_test_user_id(session: AsyncSession, username: str) -> uuid.UUID:
    """Look up a user's UUID by username."""
    from sqlalchemy import select
    from app.modules.auth.models import User

    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUploadByteCap:
    async def test_upload_byte_cap_exceeded_rejects_413(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """Byte cap: pre-existing usage exceeds cap → 413 Storage quota exceeded.

        QUOTA-01 enforcement boundary (fail-before).
        """
        user_id = await _get_test_user_id(
            test_db_session, settings.geolens_admin_username
        )

        # Insert a dataset with 5_000_000 bytes of usage
        await _create_record_with_asset(
            test_db_session, user_id=user_id, size_bytes=5_000_000
        )

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=1_000_000,  # 1MB cap — pre-existing usage (5MB) already exceeds it
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,  # no count cap
            ),
        ):
            resp = await client.post(
                "/ingest/upload",
                files={"file": ("test.geojson", _GEOJSON, "application/json")},
                headers=admin_auth_header,
            )

        assert resp.status_code == 413, (
            f"Expected 413, got {resp.status_code}: {resp.text}"
        )
        assert "Storage quota exceeded" in resp.json()["detail"]

    async def test_upload_under_byte_cap_succeeds(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """Byte cap: usage within cap → 201 OK.

        QUOTA-01 pass-after case.
        """
        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=100_000_000,  # 100MB cap — well above any test usage
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            status_code = await _upload_geojson(client, admin_auth_header)

        assert status_code == 201, f"Expected 201, got {status_code}"


class TestUploadCountCap:
    async def test_upload_count_cap_exceeded_rejects_422(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """Count cap: user already AT cap → 422 Dataset quota exceeded.

        QUOTA-02 enforcement boundary (fail-before).
        """
        user_id = await _get_test_user_id(
            test_db_session, settings.geolens_admin_username
        )

        # Insert 1 record so count=1; cap=1 → count(1) >= cap(1) → 422
        await _create_record(test_db_session, user_id=user_id)

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,  # no byte cap
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=1,  # cap=1; user has ≥1 → reject
            ),
        ):
            resp = await client.post(
                "/ingest/upload",
                files={"file": ("test.geojson", _GEOJSON, "application/json")},
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, (
            f"Expected 422, got {resp.status_code}: {resp.text}"
        )
        assert "Dataset quota exceeded" in resp.json()["detail"]

    async def test_upload_default_unlimited_never_rejects(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """Default config (cap=0) never rejects — QUOTA-03 SC-3 guarantee.

        No patching of PersistentConfig: uses real defaults (both 0).
        """
        status_code = await _upload_geojson(client, admin_auth_header)
        assert status_code == 201, f"Default unlimited must pass; got {status_code}"


class TestUploadConfigRemainingQuota:
    async def test_config_reports_remaining_when_cap_set(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """GET /ingest/upload/config returns remaining = cap - current count.

        Lets the client cap a batch at what the user can actually create.
        """
        from app.modules.quota.service import get_user_quota_usage

        user_id = await _get_test_user_id(
            test_db_session, settings.geolens_admin_username
        )
        await _create_record(test_db_session, user_id=user_id)

        # Order-independent: derive expected from the actual count (other tests
        # in this file leave committed records on the same admin user).
        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=10,
            ),
        ):
            usage = await get_user_quota_usage(test_db_session, user_id)
            resp = await client.get("/ingest/upload/config", headers=admin_auth_header)

        assert resp.status_code == 200, resp.text
        assert usage.dataset_count >= 1  # our inserted record is counted
        assert resp.json()["remaining_dataset_quota"] == max(
            0, 10 - usage.dataset_count
        )

    async def test_config_remaining_is_null_when_unlimited(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """Default config (cap=0) → remaining is null (unlimited)."""
        resp = await client.get("/ingest/upload/config", headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        assert resp.json()["remaining_dataset_quota"] is None


class TestReuploadQuota:
    async def test_reupload_byte_cap_also_enforced(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        """Reupload path: byte cap is enforced (not bypassable via reupload).

        QUOTA-01 enforcement on the reupload path (T-1224-05 mitigation).
        """
        user_id = await _get_test_user_id(
            test_db_session, settings.geolens_admin_username
        )

        # Insert usage that exceeds the cap
        await _create_record_with_asset(
            test_db_session, user_id=user_id, size_bytes=5_000_000
        )

        # Create a dataset to reupload into
        from tests.factories import create_dataset

        dataset = await create_dataset(
            test_db_session,
            created_by=user_id,
            name=f"Reupload Target {uuid.uuid4().hex[:6]}",
        )

        with (
            patch(
                "app.modules.quota.service.MAX_STORAGE_BYTES_PER_USER.get",
                new_callable=AsyncMock,
                return_value=1_000_000,  # 1MB cap, pre-existing 5MB → exceeds
            ),
            patch(
                "app.modules.quota.service.MAX_DATASETS_PER_USER.get",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "app.modules.catalog.datasets.api.router_reupload.get_catalog_port"
            ) as mock_port_fn,
        ):
            mock_port = AsyncMock()
            mock_port.validate_file_extension = lambda filename, allowed_list: None
            mock_port.create_ingest_job = AsyncMock()
            mock_port.save_upload_file = AsyncMock(
                return_value=Path("/tmp/fake_reupload.geojson")
            )
            mock_port.validate_file_content = lambda path, filename: None
            mock_port_fn.return_value = mock_port

            resp = await client.post(
                f"/datasets/{dataset.id}/reupload",
                files={"file": ("update.geojson", _GEOJSON, "application/json")},
                headers=admin_auth_header,
            )

        assert resp.status_code == 413, (
            f"Expected 413 on reupload byte cap, got {resp.status_code}: {resp.text}"
        )
        assert "Storage quota exceeded" in resp.json()["detail"]
