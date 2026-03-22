"""Integration tests for Phase 165 schema changes.

Verifies:
  - record_type column migration: defaults, constraint values, constraint rejection
  - raster_assets table: inserts, FK cascade delete, unique constraint
  - map_layers.layer_type: default, accepts new values

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied (includes 165_02, 165_03, 165_04)
"""

import uuid

import pytest
import sqlalchemy.exc
from sqlalchemy import select, text

from app.auth.models import User
from app.datasets.models import Dataset, Record
from app.maps.models import Map, MapLayer
from app.raster.models import RasterAsset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one().id


async def _create_record_and_dataset(session, *, admin_id: uuid.UUID) -> Dataset:
    """Create a minimal Record + Dataset and return the Dataset."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=f"Raster Test Dataset {uuid.uuid4().hex[:6]}",
        visibility="private",
        record_status="draft",
        created_by=admin_id,
        theme_category=[],
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format="geojson",
    )
    session.add(dataset)
    await session.flush()
    return dataset


# ---------------------------------------------------------------------------
# record_type tests
# ---------------------------------------------------------------------------


class TestRecordType:
    async def test_record_type_defaults_to_vector_dataset(
        self, client, test_db_session
    ):
        """Creating a Record without explicit record_type defaults to 'vector_dataset'."""
        admin_id = await _get_admin_id(test_db_session)
        record = Record(
            title=f"Default Type Test {uuid.uuid4().hex[:6]}",
            visibility="private",
            record_status="draft",
            created_by=admin_id,
            theme_category=[],
        )
        test_db_session.add(record)
        await test_db_session.flush()
        await test_db_session.refresh(record)

        assert record.record_type == "vector_dataset"

    async def test_existing_records_have_vector_dataset_type(
        self, client, test_db_session
    ):
        """All existing records have record_type='vector_dataset', not 'dataset'."""
        result = await test_db_session.execute(
            text("SELECT COUNT(*) FROM catalog.records WHERE record_type = 'dataset'")
        )
        old_count = result.scalar_one()
        assert old_count == 0, (
            f"Found {old_count} records with obsolete record_type='dataset'"
        )

    async def test_record_type_rejects_invalid_value(self, client, test_db_session):
        """Check constraint rejects invalid record_type value."""
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await test_db_session.execute(
                text(
                    "INSERT INTO catalog.records (title, record_type, visibility, record_status) "
                    "VALUES ('bad type test', 'invalid', 'private', 'draft')"
                )
            )
            await test_db_session.flush()

    async def test_record_type_accepts_raster_dataset(self, client, test_db_session):
        """Check constraint accepts 'raster_dataset'."""
        admin_id = await _get_admin_id(test_db_session)
        record = Record(
            title=f"Raster Record {uuid.uuid4().hex[:6]}",
            record_type="raster_dataset",
            visibility="private",
            record_status="draft",
            created_by=admin_id,
            theme_category=[],
        )
        test_db_session.add(record)
        await test_db_session.flush()
        await test_db_session.refresh(record)

        assert record.record_type == "raster_dataset"


# ---------------------------------------------------------------------------
# raster_assets tests
# ---------------------------------------------------------------------------


class TestRasterAssets:
    async def test_raster_asset_insert(self, client, test_db_session):
        """raster_assets table accepts inserts with valid dataset FK."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        asset = RasterAsset(
            dataset_id=dataset.id,
            asset_uri="/app/staging/test.tif",
            driver="GTiff",
            storage_backend="local",
        )
        test_db_session.add(asset)
        await test_db_session.flush()
        await test_db_session.refresh(asset)

        assert asset.id is not None
        assert asset.dataset_id == dataset.id
        assert asset.storage_backend == "local"
        assert asset.created_at is not None

    async def test_raster_asset_cascade_delete(self, client, test_db_session):
        """Deleting a dataset cascades to delete its raster_asset row."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        asset = RasterAsset(
            dataset_id=dataset.id,
            asset_uri="/app/staging/cascade_test.tif",
        )
        test_db_session.add(asset)
        await test_db_session.flush()
        asset_id = asset.id

        # Delete the dataset — cascade should remove the asset
        await test_db_session.delete(dataset)
        await test_db_session.flush()

        result = await test_db_session.execute(
            select(RasterAsset).where(RasterAsset.id == asset_id)
        )
        assert result.scalar_one_or_none() is None

    async def test_raster_asset_unique_constraint(self, client, test_db_session):
        """raster_assets unique constraint prevents two assets for the same dataset."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        asset1 = RasterAsset(
            dataset_id=dataset.id,
            asset_uri="/app/staging/first.tif",
        )
        test_db_session.add(asset1)
        await test_db_session.flush()

        with pytest.raises(sqlalchemy.exc.IntegrityError):
            asset2 = RasterAsset(
                dataset_id=dataset.id,
                asset_uri="/app/staging/second.tif",
            )
            test_db_session.add(asset2)
            await test_db_session.flush()


# ---------------------------------------------------------------------------
# map_layers.layer_type tests
# ---------------------------------------------------------------------------


class TestMapLayerType:
    async def test_map_layer_type_defaults_to_vector_geolens(
        self, client, test_db_session
    ):
        """Creating a MapLayer without explicit layer_type defaults to 'vector_geolens'."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        map_obj = Map(
            name=f"Test Map {uuid.uuid4().hex[:6]}",
            created_by=admin_id,
        )
        test_db_session.add(map_obj)
        await test_db_session.flush()

        layer = MapLayer(
            map_id=map_obj.id,
            dataset_id=dataset.id,
        )
        test_db_session.add(layer)
        await test_db_session.flush()
        await test_db_session.refresh(layer)

        assert layer.layer_type == "vector_geolens"

    async def test_map_layer_type_accepts_raster_geolens(
        self, client, test_db_session
    ):
        """layer_type accepts 'raster_geolens' value."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        map_obj = Map(
            name=f"Raster Map {uuid.uuid4().hex[:6]}",
            created_by=admin_id,
        )
        test_db_session.add(map_obj)
        await test_db_session.flush()

        layer = MapLayer(
            map_id=map_obj.id,
            dataset_id=dataset.id,
            layer_type="raster_geolens",
        )
        test_db_session.add(layer)
        await test_db_session.flush()
        await test_db_session.refresh(layer)

        assert layer.layer_type == "raster_geolens"
