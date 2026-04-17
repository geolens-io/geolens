"""Integration tests for Phase 171 VRT schema changes.

Verifies:
  - record_type accepts 'vrt_dataset' value
  - raster_assets VRT tracking columns: status default, vrt_type CHECK, status CHECK
  - catalog.vrt_source_links: insert with position, unique constraint,
    ON DELETE RESTRICT (COG side), ON DELETE CASCADE (VRT side)

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (alembic upgrade head)
"""

import uuid

import pytest
import sqlalchemy.exc
from sqlalchemy import select, text

from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


async def _create_vrt_record_and_dataset(
    session, admin_id: uuid.UUID
) -> tuple[Record, Dataset, RasterAsset]:
    """Create a Record (record_type='vrt_dataset') + Dataset + RasterAsset (vrt_type='mosaic')."""
    record = Record(
        title=f"VRT Test Dataset {uuid.uuid4().hex[:6]}",
        visibility="private",
        record_status="draft",
        record_type="vrt_dataset",
        created_by=admin_id,
        theme_category=[],
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"vrt_{uuid.uuid4().hex[:12]}",
        source_format="geotiff",
    )
    session.add(dataset)
    await session.flush()

    asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/source.vrt",
        storage_backend="local",
        vrt_type="mosaic",
    )
    session.add(asset)
    await session.flush()

    return record, dataset, asset


async def _create_cog_record_and_dataset(
    session, admin_id: uuid.UUID
) -> tuple[Record, Dataset, RasterAsset]:
    """Create a Record (record_type='raster_dataset') + Dataset + RasterAsset (COG)."""
    record = Record(
        title=f"COG Test Dataset {uuid.uuid4().hex[:6]}",
        visibility="private",
        record_status="draft",
        record_type="raster_dataset",
        created_by=admin_id,
        theme_category=[],
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"cog_{uuid.uuid4().hex[:12]}",
        source_format="geotiff",
    )
    session.add(dataset)
    await session.flush()

    asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/source.cog.tif",
        storage_backend="local",
    )
    session.add(asset)
    await session.flush()

    return record, dataset, asset


# ---------------------------------------------------------------------------
# record_type tests
# ---------------------------------------------------------------------------


class TestVrtRecordType:
    async def test_record_type_accepts_vrt_dataset(self, client, test_db_session):
        """record_type CHECK constraint accepts 'vrt_dataset'."""
        admin_id = await _get_admin_id(test_db_session)
        record = Record(
            title=f"VRT Record {uuid.uuid4().hex[:6]}",
            record_type="vrt_dataset",
            visibility="private",
            record_status="draft",
            created_by=admin_id,
            theme_category=[],
        )
        test_db_session.add(record)
        await test_db_session.flush()
        await test_db_session.refresh(record)

        assert record.record_type == "vrt_dataset"


# ---------------------------------------------------------------------------
# raster_assets VRT column tests
# ---------------------------------------------------------------------------


class TestRasterAssetsVrtColumns:
    async def test_status_defaults_to_ready(self, client, test_db_session):
        """RasterAsset.status defaults to 'ready' when not specified."""
        admin_id = await _get_admin_id(test_db_session)

        # Create a minimal record + dataset
        record = Record(
            title=f"Status Default Test {uuid.uuid4().hex[:6]}",
            visibility="private",
            record_status="draft",
            record_type="raster_dataset",
            created_by=admin_id,
            theme_category=[],
        )
        test_db_session.add(record)
        await test_db_session.flush()

        dataset = Dataset(
            record_id=record.id,
            table_name=f"status_test_{uuid.uuid4().hex[:8]}",
            source_format="geotiff",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()

        # Do NOT specify status — rely on server_default
        asset = RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/source.cog.tif",
        )
        test_db_session.add(asset)
        await test_db_session.flush()
        await test_db_session.refresh(asset)

        assert asset.status == "ready"

    async def test_vrt_type_check_accepts_mosaic(self, client, test_db_session):
        """vrt_type CHECK constraint accepts 'mosaic'."""
        admin_id = await _get_admin_id(test_db_session)
        _, _, asset = await _create_vrt_record_and_dataset(test_db_session, admin_id)
        await test_db_session.refresh(asset)

        assert asset.vrt_type == "mosaic"

    async def test_vrt_type_check_rejects_invalid(self, client, test_db_session):
        """vrt_type CHECK constraint rejects invalid values."""
        admin_id = await _get_admin_id(test_db_session)

        record = Record(
            title=f"Invalid vrt_type Test {uuid.uuid4().hex[:6]}",
            visibility="private",
            record_status="draft",
            record_type="vrt_dataset",
            created_by=admin_id,
            theme_category=[],
        )
        test_db_session.add(record)
        await test_db_session.flush()

        dataset = Dataset(
            record_id=record.id,
            table_name=f"vrt_invalid_{uuid.uuid4().hex[:8]}",
            source_format="geotiff",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()

        dataset_id = dataset.id

        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await test_db_session.execute(
                text(
                    "INSERT INTO catalog.raster_assets (dataset_id, asset_uri, vrt_type) "
                    "VALUES (:dataset_id, 'rasters/test/source.vrt', 'invalid')"
                ),
                {"dataset_id": dataset_id},
            )
            await test_db_session.flush()

        await test_db_session.rollback()

    async def test_status_check_accepts_regenerating(self, client, test_db_session):
        """status CHECK constraint accepts 'regenerating'."""
        admin_id = await _get_admin_id(test_db_session)

        record = Record(
            title=f"Status Regenerating Test {uuid.uuid4().hex[:6]}",
            visibility="private",
            record_status="draft",
            record_type="vrt_dataset",
            created_by=admin_id,
            theme_category=[],
        )
        test_db_session.add(record)
        await test_db_session.flush()

        dataset = Dataset(
            record_id=record.id,
            table_name=f"status_regen_{uuid.uuid4().hex[:8]}",
            source_format="geotiff",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()

        dataset_id = dataset.id

        await test_db_session.execute(
            text(
                "INSERT INTO catalog.raster_assets (dataset_id, asset_uri, status) "
                "VALUES (:dataset_id, 'rasters/test/source.vrt', 'regenerating')"
            ),
            {"dataset_id": dataset_id},
        )
        await test_db_session.flush()

        result = await test_db_session.execute(
            text(
                "SELECT status FROM catalog.raster_assets WHERE dataset_id = :dataset_id"
            ),
            {"dataset_id": dataset_id},
        )
        row = result.one()
        assert row.status == "regenerating"

    async def test_status_check_rejects_invalid(self, client, test_db_session):
        """status CHECK constraint rejects invalid status values."""
        admin_id = await _get_admin_id(test_db_session)

        record = Record(
            title=f"Invalid Status Test {uuid.uuid4().hex[:6]}",
            visibility="private",
            record_status="draft",
            record_type="vrt_dataset",
            created_by=admin_id,
            theme_category=[],
        )
        test_db_session.add(record)
        await test_db_session.flush()

        dataset = Dataset(
            record_id=record.id,
            table_name=f"status_invalid_{uuid.uuid4().hex[:8]}",
            source_format="geotiff",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()

        dataset_id = dataset.id

        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await test_db_session.execute(
                text(
                    "INSERT INTO catalog.raster_assets (dataset_id, asset_uri, status) "
                    "VALUES (:dataset_id, 'rasters/test/source.vrt', 'invalid_status')"
                ),
                {"dataset_id": dataset_id},
            )
            await test_db_session.flush()

        await test_db_session.rollback()

    async def test_vrt_type_and_resolution_strategy_nullable(
        self, client, test_db_session
    ):
        """vrt_type and resolution_strategy columns are nullable (COG assets need no VRT columns)."""
        admin_id = await _get_admin_id(test_db_session)

        record = Record(
            title=f"Nullable VRT Columns Test {uuid.uuid4().hex[:6]}",
            visibility="private",
            record_status="draft",
            record_type="raster_dataset",
            created_by=admin_id,
            theme_category=[],
        )
        test_db_session.add(record)
        await test_db_session.flush()

        dataset = Dataset(
            record_id=record.id,
            table_name=f"cog_nullable_{uuid.uuid4().hex[:8]}",
            source_format="geotiff",
        )
        test_db_session.add(dataset)
        await test_db_session.flush()

        # No vrt_type, no resolution_strategy — should be NULL
        asset = RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/source.cog.tif",
        )
        test_db_session.add(asset)
        await test_db_session.flush()
        await test_db_session.refresh(asset)

        assert asset.vrt_type is None
        assert asset.resolution_strategy is None


# ---------------------------------------------------------------------------
# vrt_source_links tests
# ---------------------------------------------------------------------------


class TestVrtSourceLinks:
    async def test_insert_with_position(self, client, test_db_session):
        """Inserting a vrt_source_links row with position=0 succeeds."""
        admin_id = await _get_admin_id(test_db_session)
        _, vrt_dataset, _ = await _create_vrt_record_and_dataset(
            test_db_session, admin_id
        )
        _, cog_dataset, _ = await _create_cog_record_and_dataset(
            test_db_session, admin_id
        )

        await test_db_session.execute(
            text(
                "INSERT INTO catalog.vrt_source_links "
                "(vrt_dataset_id, source_dataset_id, position) "
                "VALUES (:vrt_id, :cog_id, 0)"
            ),
            {"vrt_id": vrt_dataset.id, "cog_id": cog_dataset.id},
        )
        await test_db_session.flush()

        result = await test_db_session.execute(
            text(
                "SELECT position FROM catalog.vrt_source_links "
                "WHERE vrt_dataset_id = :vrt_id AND source_dataset_id = :cog_id"
            ),
            {"vrt_id": vrt_dataset.id, "cog_id": cog_dataset.id},
        )
        row = result.one()
        assert row.position == 0

    async def test_unique_constraint_prevents_duplicate_link(
        self, client, test_db_session
    ):
        """Inserting the same (vrt_dataset_id, source_dataset_id) pair twice raises IntegrityError."""
        admin_id = await _get_admin_id(test_db_session)
        _, vrt_dataset, _ = await _create_vrt_record_and_dataset(
            test_db_session, admin_id
        )
        _, cog_dataset, _ = await _create_cog_record_and_dataset(
            test_db_session, admin_id
        )

        # First insert should succeed
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.vrt_source_links "
                "(vrt_dataset_id, source_dataset_id, position) "
                "VALUES (:vrt_id, :cog_id, 0)"
            ),
            {"vrt_id": vrt_dataset.id, "cog_id": cog_dataset.id},
        )
        await test_db_session.flush()

        # Second insert of same pair should fail with IntegrityError
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await test_db_session.execute(
                text(
                    "INSERT INTO catalog.vrt_source_links "
                    "(vrt_dataset_id, source_dataset_id, position) "
                    "VALUES (:vrt_id, :cog_id, 1)"
                ),
                {"vrt_id": vrt_dataset.id, "cog_id": cog_dataset.id},
            )
            await test_db_session.flush()

        await test_db_session.rollback()

    async def test_on_delete_restrict_blocks_cog_deletion(
        self, client, test_db_session
    ):
        """ON DELETE RESTRICT: deleting a COG dataset referenced in vrt_source_links raises IntegrityError."""
        admin_id = await _get_admin_id(test_db_session)
        _, vrt_dataset, _ = await _create_vrt_record_and_dataset(
            test_db_session, admin_id
        )
        _, cog_dataset, _ = await _create_cog_record_and_dataset(
            test_db_session, admin_id
        )

        # Create the link
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.vrt_source_links "
                "(vrt_dataset_id, source_dataset_id, position) "
                "VALUES (:vrt_id, :cog_id, 0)"
            ),
            {"vrt_id": vrt_dataset.id, "cog_id": cog_dataset.id},
        )
        await test_db_session.flush()

        # Attempt to delete the COG dataset — RESTRICT FK should prevent it
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await test_db_session.execute(
                text("DELETE FROM catalog.datasets WHERE id = :cog_id"),
                {"cog_id": cog_dataset.id},
            )
            await test_db_session.flush()

        # Reset session state after expected error
        await test_db_session.rollback()

    async def test_on_delete_cascade_removes_links_when_vrt_deleted(
        self, client, test_db_session
    ):
        """ON DELETE CASCADE: deleting the VRT dataset cascades to remove its vrt_source_links rows."""
        admin_id = await _get_admin_id(test_db_session)
        vrt_record, vrt_dataset, _ = await _create_vrt_record_and_dataset(
            test_db_session, admin_id
        )
        _, cog_dataset, _ = await _create_cog_record_and_dataset(
            test_db_session, admin_id
        )

        # Create the link
        await test_db_session.execute(
            text(
                "INSERT INTO catalog.vrt_source_links "
                "(vrt_dataset_id, source_dataset_id, position) "
                "VALUES (:vrt_id, :cog_id, 0)"
            ),
            {"vrt_id": vrt_dataset.id, "cog_id": cog_dataset.id},
        )
        await test_db_session.flush()

        vrt_dataset_id = vrt_dataset.id
        cog_dataset_id = cog_dataset.id

        # Delete the VRT record (cascades to datasets, which cascades to vrt_source_links)
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :record_id"),
            {"record_id": vrt_record.id},
        )
        await test_db_session.flush()

        # vrt_source_links row should be gone
        result = await test_db_session.execute(
            text(
                "SELECT COUNT(*) FROM catalog.vrt_source_links "
                "WHERE vrt_dataset_id = :vrt_id"
            ),
            {"vrt_id": vrt_dataset_id},
        )
        assert result.scalar_one() == 0

        # COG dataset should still exist
        result = await test_db_session.execute(
            text("SELECT COUNT(*) FROM catalog.datasets WHERE id = :cog_id"),
            {"cog_id": cog_dataset_id},
        )
        assert result.scalar_one() == 1
