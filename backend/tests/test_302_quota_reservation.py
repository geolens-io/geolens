"""Atomic dataset-count reservation tests (fix #302).

The door's check_dataset_count_quota is a non-atomic pre-check: the Record
rows it counts are created later by the ingest worker, so concurrent
creates could overshoot max_datasets_per_user. reserve_dataset_slot is the
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
from types import SimpleNamespace
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


def _raster(session, owner: uuid.UUID):
    from app.processing.ingest.tasks_raster_common import create_raster_dataset

    return create_raster_dataset(
        session,
        meta={
            "driver": "GTiff",
            "epsg": 4326,
            "band_count": 1,
            "dtype": "uint8",
            "width": 64,
            "height": 64,
        },
        source_sha256="a" * 64,
        asset_sha256="b" * 64,
        cog_status="verified",
        cog_size=2048,
        source_filename="second.tif",
        created_by=owner,
        title="Second raster",
        summary=None,
        visibility="private",
    )


def _vrt(session, owner: uuid.UUID):
    from app.processing.ingest.tasks_vrt import create_vrt_dataset

    return create_vrt_dataset(
        session,
        meta={
            "epsg": 4326,
            "band_count": 1,
            "dtype": "uint8",
            "width": 256,
            "height": 256,
        },
        asset_sha256="a" * 64,
        vrt_size=512,
        source_filename="second.vrt",
        created_by=owner,
        title="Second mosaic",
        summary=None,
        visibility="private",
        vrt_type="mosaic",
        resolution_strategy="finest",
        source_dataset_ids=[],
    )


def _tileset(session, owner: uuid.UUID):
    from app.processing.ingest.tasks_tileset import create_tileset_dataset

    return create_tileset_dataset(
        session,
        dataset_id=uuid.uuid4(),
        # The refusal comes before the tileset is read.
        tileset=SimpleNamespace(
            layout=SimpleNamespace(unpacked_bytes=1), facts=None, contents=None
        ),
        attempt_prefix="tiles3d/second/a1/",
        source_filename="second.3tz",
        created_by=owner,
        user_metadata={},
    )


def _pointcloud(session, owner: uuid.UUID):
    from app.processing.ingest.tasks_pointcloud import create_pointcloud_dataset

    return create_pointcloud_dataset(
        session,
        dataset_id=uuid.uuid4(),
        # The refusal comes before the point cloud is read.
        cloud=SimpleNamespace(size_bytes=1, srid=4326),
        attempt_id=uuid.uuid4(),
        source_filename="second.copc.laz",
        created_by=owner,
        user_metadata={},
    )


def _pointcloud_before_the_copy(session, owner: uuid.UUID):
    from app.processing.ingest.tasks_pointcloud import refuse_before_the_copy

    return refuse_before_the_copy(owner, SimpleNamespace(size_bytes=1, srid=4326))


class TestTypedCreatorEnforcement:
    """Each record creator outside the datasets facade reserves its own slot."""

    @pytest.mark.parametrize(
        "create",
        [_raster, _vrt, _tileset, _pointcloud, _pointcloud_before_the_copy],
        ids=["raster", "vrt", "tileset", "pointcloud", "pointcloud-before-the-copy"],
    )
    async def test_a_creator_refuses_at_the_cap(
        self,
        create,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session,
        clean_tables,
    ) -> None:
        from tests.factories import create_dataset

        owner = uuid.UUID(
            (await client.get("/auth/me/", headers=editor_auth_header)).json()["id"]
        )
        await create_dataset(test_db_session, created_by=owner)

        p_count, p_storage = _patch_caps(1)
        try:
            with (
                p_count,
                p_storage,
                pytest.raises(DatasetQuotaExceededError) as refused,
            ):
                await create(test_db_session, owner)
        finally:
            await test_db_session.rollback()

        assert "Dataset quota exceeded: 1 of 1" in str(refused.value)


class TestStacImportEnforcement:
    async def test_stac_import_rejects_items_past_cap(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
    ) -> None:
        """A multi-item STAC batch cannot overshoot the cap.

        STAC import inserts Record rows directly (the 4th creation site), so
        it reserves a slot per item: with cap=1 and a fresh editor, a 2-item
        batch creates the first and records a per-item quota error for the
        second instead of overshooting.
        """
        p_count, p_storage = _patch_caps(1)
        with (
            p_count,
            p_storage,
            patch("app.modules.catalog.sources.stac_router.validate_url_for_ssrf"),
        ):
            resp = await client.post(
                "/services/stac/import",
                json={
                    "url": "https://stac.example.com/v1",
                    "items": [
                        {
                            "id": f"quota302-a-{uuid.uuid4().hex[:8]}",
                            "title": "quota-302 STAC item 1",
                            "data_asset_href": (
                                f"https://example.com/data/{uuid.uuid4().hex[:8]}.tif"
                            ),
                            "keywords": [],
                        },
                        {
                            "id": f"quota302-b-{uuid.uuid4().hex[:8]}",
                            "title": "quota-302 STAC item 2",
                            "data_asset_href": (
                                f"https://example.com/data/{uuid.uuid4().hex[:8]}.tif"
                            ),
                            "keywords": [],
                        },
                    ],
                    "visibility": "private",
                },
                headers=editor_auth_header,
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["created"] == 1
        assert data["errors"] == 1
        error_results = [r for r in data["results"] if r["status"] == "error"]
        assert "Dataset quota exceeded" in error_results[0]["error"]
