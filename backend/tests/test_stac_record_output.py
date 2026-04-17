"""Integration tests for record output fields.

Verifies:
  - properties.datetime follows STAC 1.0.0 rules
  - STAC-specific keys (stac_version, stac_extensions, stac_assets) are NOT
    present in OGC Records responses
  - _build_stac_assets helper produces correct structure
  - Raster records include proj:* properties

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from datetime import date

from sqlalchemy import select

from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.search.service import (
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
    await session.flush()
    # Eager-load relationships needed by dataset_to_ogc_record
    await session.refresh(
        record, attribute_names=["keywords", "contacts", "distributions"]
    )
    await session.refresh(dataset, attribute_names=["record"])
    return dataset


async def _prepare_for_sync(session, dataset):
    """Refresh all attributes so dataset_to_ogc_record can run synchronously."""
    record = dataset.record
    await session.refresh(
        record, attribute_names=["keywords", "contacts", "distributions"]
    )
    await session.refresh(dataset, attribute_names=["record"])


# ---------------------------------------------------------------------------
# stac_version tests
# ---------------------------------------------------------------------------


class TestNoStacBleedthrough:
    async def test_ogc_record_no_stac_version(self, client, test_db_session):
        """OGC record dict must NOT have stac_version (STAC-specific)."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
        assert "stac_version" not in result


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
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

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


class TestStacAssetsRemoved:
    async def test_stac_assets_not_in_ogc_record(self, client, test_db_session):
        """OGC record must NOT have stac_assets (STAC-specific). assets key is fine."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        stac_asset_rows = [
            {
                "key": "data",
                "href": "/app/storage/test.tif",
                "media_type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "roles": ["data"],
                "title": "Cloud-Optimized GeoTIFF",
                "description": None,
            },
        ]

        result = dataset_to_ogc_record(
            dataset, "http://localhost:8080/api", stac_asset_rows=stac_asset_rows
        )

        assert "stac_assets" not in result
        # assets (OGC-compliant) should still be present
        assert "assets" in result


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
        assert result == {
            "raw": {"href": "http://localhost:8080/api/assets/storage/raw.dat"}
        }

    def test_build_stac_assets_empty(self):
        """_build_stac_assets with None returns empty dict."""
        assert _build_stac_assets(None) == {}

    def test_build_stac_assets_empty_list(self):
        """_build_stac_assets with empty list returns empty dict."""
        assert _build_stac_assets([]) == {}


# ---------------------------------------------------------------------------
# STAC extensions and properties tests
# ---------------------------------------------------------------------------


class TestStacExtensionsRemoved:
    async def test_raster_record_no_stac_extensions(self, client, test_db_session):
        """Raster records must NOT have stac_extensions in OGC Records output."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)
        dataset.record.record_type = "raster_dataset"
        await test_db_session.flush()
        await _prepare_for_sync(test_db_session, dataset)

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

        assert "stac_extensions" not in result

    async def test_vector_record_no_stac_extensions(self, client, test_db_session):
        """Vector records should not have stac_extensions."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        result = dataset_to_ogc_record(dataset, "http://localhost:8080/api")
        assert "stac_extensions" not in result

    async def test_raster_record_proj_properties(self, client, test_db_session):
        """Raster record should have proj:* properties in properties dict."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)
        dataset.record.record_type = "raster_dataset"
        await test_db_session.flush()
        await _prepare_for_sync(test_db_session, dataset)

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

    async def test_no_bands_without_band_info(self, client, test_db_session):
        """No bands array when band_info is None."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)
        dataset.record.record_type = "raster_dataset"
        await test_db_session.flush()
        await _prepare_for_sync(test_db_session, dataset)

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

        assert "stac_extensions" not in result
        assert "bands" not in result["properties"]
