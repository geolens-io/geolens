"""Integration tests for STAC fields in OGC record output.

Verifies:
  - stac_version="1.1.0" at top level of OGC record
  - properties.datetime follows STAC 1.1.0 rules
  - stac_assets dict serialized from DatasetAsset rows
  - _build_stac_assets helper produces correct structure

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record
from app.raster.models import DatasetAsset
from app.search.service import (
    STAC_EXT_EO,
    STAC_EXT_PROJECTION,
    _build_stac_assets,
    dataset_to_ogc_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one().id


async def _create_record_and_dataset(
    session,
    *,
    admin_id: uuid.UUID,
    temporal_start: date | None = None,
    temporal_end: date | None = None,
) -> Dataset:
    """Create a minimal Record + Dataset and return the Dataset."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=f"STAC Record Test {uuid.uuid4().hex[:6]}",
        visibility="private",
        record_status="draft",
        created_by=admin_id,
        theme_category=[],
        temporal_start=temporal_start,
        temporal_end=temporal_end,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format="geotiff",
    )
    session.add(dataset)
    await session.flush()
    # Eager-load relationships needed by dataset_to_ogc_record
    await session.refresh(record, attribute_names=["keywords", "contacts", "distributions"])
    await session.refresh(dataset, attribute_names=["record"])
    return dataset


# ---------------------------------------------------------------------------
# stac_version tests
# ---------------------------------------------------------------------------


class TestStacVersion:
    async def test_ogc_record_has_stac_version(self, client, test_db_session):
        """OGC record dict has top-level stac_version = '1.1.0'."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
        assert result["stac_version"] == "1.1.0"


# ---------------------------------------------------------------------------
# properties.datetime tests
# ---------------------------------------------------------------------------


class TestStacDatetime:
    async def test_datetime_with_temporal_start_only(self, client, test_db_session):
        """Record with temporal_start has properties.datetime as RFC 3339."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session,
            admin_id=admin_id,
            temporal_start=date(2024, 6, 15),
        )

        result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
        assert result["properties"]["datetime"] == "2024-06-15T00:00:00Z"

    async def test_datetime_null_when_no_temporal(self, client, test_db_session):
        """Record with no temporal_start has properties.datetime = null."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
        assert result["properties"]["datetime"] is None

    async def test_datetime_range_with_start_and_end(self, client, test_db_session):
        """Record with both temporal bounds has start_datetime and end_datetime."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session,
            admin_id=admin_id,
            temporal_start=date(2024, 1, 1),
            temporal_end=date(2024, 12, 31),
        )

        result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
        props = result["properties"]
        assert props["datetime"] is None
        assert props["start_datetime"] == "2024-01-01T00:00:00Z"
        assert props["end_datetime"] == "2024-12-31T00:00:00Z"


# ---------------------------------------------------------------------------
# stac_assets tests
# ---------------------------------------------------------------------------


class TestStacAssets:
    async def test_stac_assets_with_dataset_assets(self, client, test_db_session):
        """OGC record includes stac_assets dict keyed by DatasetAsset.key."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        # Create DatasetAsset rows
        asset1 = DatasetAsset(
            dataset_id=dataset.id,
            key="data",
            href="/app/storage/test.tif",
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"],
            title="Cloud-Optimized GeoTIFF",
        )
        asset2 = DatasetAsset(
            dataset_id=dataset.id,
            key="thumbnail",
            href="/app/storage/thumb.png",
            media_type="image/png",
            roles=["thumbnail"],
            title="Thumbnail",
            description="256px quicklook",
        )
        test_db_session.add_all([asset1, asset2])
        await test_db_session.flush()

        stac_asset_rows = [
            {
                "key": "data",
                "href": "/app/storage/test.tif",
                "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data"],
                "title": "Cloud-Optimized GeoTIFF",
                "description": None,
            },
            {
                "key": "thumbnail",
                "href": "/app/storage/thumb.png",
                "media_type": "image/png",
                "roles": ["thumbnail"],
                "title": "Thumbnail",
                "description": "256px quicklook",
            },
        ]

        result = dataset_to_ogc_record(
            dataset, "http://localhost:8080/api", stac_asset_rows=stac_asset_rows
        )

        stac_assets = result["stac_assets"]
        assert "data" in stac_assets
        assert stac_assets["data"]["href"] == "/app/storage/test.tif"
        assert stac_assets["data"]["type"] == "image/tiff; application=geotiff; profile=cloud-optimized"
        assert stac_assets["data"]["roles"] == ["data"]
        assert stac_assets["data"]["title"] == "Cloud-Optimized GeoTIFF"

        assert "thumbnail" in stac_assets
        assert stac_assets["thumbnail"]["href"] == "/app/storage/thumb.png"
        assert stac_assets["thumbnail"]["description"] == "256px quicklook"

    async def test_stac_assets_empty_when_no_rows(self, client, test_db_session):
        """OGC record with no DatasetAsset rows has empty stac_assets dict."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
        assert result["stac_assets"] == {}


# ---------------------------------------------------------------------------
# _build_stac_assets unit tests
# ---------------------------------------------------------------------------


class TestBuildStacAssets:
    def test_build_stac_assets_full(self):
        """_build_stac_assets produces correct structure from row dicts."""
        rows = [
            {
                "key": "data",
                "href": "/storage/file.tif",
                "media_type": "image/tiff",
                "roles": ["data"],
                "title": "COG",
                "description": "Main file",
            },
        ]
        result = _build_stac_assets(rows, public_api_url="http://localhost:8080/api")
        assert result == {
            "data": {
                "href": "http://localhost:8080/api/assets/storage/file.tif",
                "type": "image/tiff",
                "roles": ["data"],
                "title": "COG",
                "description": "Main file",
            },
        }

    def test_build_stac_assets_minimal(self):
        """_build_stac_assets with only href produces minimal entry."""
        rows = [{"key": "raw", "href": "/storage/raw.dat"}]
        result = _build_stac_assets(rows, public_api_url="http://localhost:8080/api")
        assert result == {"raw": {"href": "http://localhost:8080/api/assets/storage/raw.dat"}}

    def test_build_stac_assets_empty(self):
        """_build_stac_assets with None returns empty dict."""
        assert _build_stac_assets(None) == {}

    def test_build_stac_assets_empty_list(self):
        """_build_stac_assets with empty list returns empty dict."""
        assert _build_stac_assets([]) == {}


# ---------------------------------------------------------------------------
# STAC extensions and properties tests
# ---------------------------------------------------------------------------


class TestStacExtensions:
    async def test_raster_record_has_stac_extensions(self, client, test_db_session):
        """Raster record with epsg and bands gets both STAC extension URIs."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )
        # Set record_type to raster
        dataset.record.record_type = "raster_dataset"
        await test_db_session.flush()

        raster_meta = {
            "epsg": 4326,
            "width": 1024,
            "height": 512,
            "res_x": 0.01,
            "res_y": -0.01,
            "band_count": 3,
            "dtype": "uint8",
            "nodata": None,
            "band_info": [
                {"name": "Red", "dtype": "uint8", "nodata": None},
                {"name": "Green", "dtype": "uint8", "nodata": None},
                {"name": "Blue", "dtype": "uint8", "nodata": None},
            ],
        }

        result = dataset_to_ogc_record(
            dataset, "http://localhost:8080/api", raster_meta=raster_meta
        )

        assert "stac_extensions" in result
        assert STAC_EXT_PROJECTION in result["stac_extensions"]
        assert STAC_EXT_EO in result["stac_extensions"]

    async def test_vector_record_no_stac_extensions(self, client, test_db_session):
        """Vector records should not have stac_extensions."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )

        result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
        assert "stac_extensions" not in result

    async def test_raster_record_stac_properties(self, client, test_db_session):
        """Raster record should have STAC properties in properties dict."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )
        dataset.record.record_type = "raster_dataset"
        await test_db_session.flush()

        raster_meta = {
            "epsg": 32618,
            "width": 2048,
            "height": 1024,
            "res_x": 10.0,
            "res_y": -10.0,
            "band_count": 4,
            "dtype": "uint16",
            "nodata": "0",
            "band_info": [
                {"name": "Red", "dtype": "uint16", "nodata": 0},
                {"name": "Green", "dtype": "uint16", "nodata": 0},
                {"name": "Blue", "dtype": "uint16", "nodata": 0},
                {"name": "NIR", "dtype": "uint16", "nodata": 0},
            ],
        }

        result = dataset_to_ogc_record(
            dataset, "http://localhost:8080/api", raster_meta=raster_meta
        )
        props = result["properties"]

        assert props["proj:epsg"] == 32618
        assert props["proj:shape"] == [1024, 2048]
        assert props["gsd"] == 10.0
        assert props["band_count"] == 4
        assert "bands" in props
        assert len(props["bands"]) == 4
        assert props["bands"][0]["name"] == "Red"
        assert props["bands"][0]["data_type"] == "uint16"

    async def test_eo_extension_requires_bands_not_band_count(
        self, client, test_db_session
    ):
        """EO extension should be gated on bands array, not band_count."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )
        dataset.record.record_type = "raster_dataset"
        await test_db_session.flush()

        # band_count set but band_info is None -- no bands array
        raster_meta = {
            "epsg": 4326,
            "width": 512,
            "height": 256,
            "res_x": 0.1,
            "res_y": -0.1,
            "band_count": 3,
            "dtype": "uint8",
            "nodata": None,
            "band_info": None,
        }

        result = dataset_to_ogc_record(
            dataset, "http://localhost:8080/api", raster_meta=raster_meta
        )

        # Should have projection extension (epsg is set) but NOT eo
        assert "stac_extensions" in result
        assert STAC_EXT_PROJECTION in result["stac_extensions"]
        assert STAC_EXT_EO not in result["stac_extensions"]
        # No bands array in properties
        assert "bands" not in result["properties"]
