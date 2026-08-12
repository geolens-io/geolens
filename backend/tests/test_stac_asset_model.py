"""Integration tests for DatasetAsset model and RasterAsset.to_stac_properties().

Verifies:
  - DatasetAsset CRUD: insert, unique constraint, cascade delete
  - RasterAsset.to_stac_properties(): full metadata, sparse, and empty cases
  - Backfill asset key conventions: COG='data', VRT='vrt', thumbnail, overview

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
import sqlalchemy.exc
from sqlalchemy import select

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import DatasetAsset, RasterAsset

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    return await get_user_id(session, "admin")


async def _create_record_and_dataset(session, *, admin_id: uuid.UUID) -> Dataset:
    """Create a minimal Record + Dataset and return the Dataset."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=f"STAC Test Dataset {uuid.uuid4().hex[:6]}",
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
        source_format="geotiff",
    )
    session.add(dataset)
    await session.flush()
    return dataset


# ---------------------------------------------------------------------------
# DatasetAsset CRUD tests
# ---------------------------------------------------------------------------


class TestDatasetAssetCRUD:
    async def test_dataset_asset_insert(self, client, test_db_session):
        """DatasetAsset table accepts inserts and round-trips via SELECT."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        asset = DatasetAsset(
            dataset_id=dataset.id,
            key="data",
            href="/app/storage/test.tif",
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"],
            size_bytes=1024000,
        )
        test_db_session.add(asset)
        await test_db_session.flush()
        await test_db_session.refresh(asset)

        assert asset.id is not None
        assert asset.dataset_id == dataset.id
        assert asset.key == "data"
        assert asset.href == "/app/storage/test.tif"
        assert (
            asset.media_type
            == "image/tiff; application=geotiff; profile=cloud-optimized"
        )
        assert asset.roles == ["data"]
        assert asset.size_bytes == 1024000
        assert asset.created_at is not None

    async def test_dataset_asset_unique_key(self, client, test_db_session):
        """UniqueConstraint rejects duplicate (dataset_id, key) pairs."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        asset1 = DatasetAsset(
            dataset_id=dataset.id,
            key="data",
            href="/app/storage/first.tif",
        )
        test_db_session.add(asset1)
        await test_db_session.flush()

        with pytest.raises(sqlalchemy.exc.IntegrityError):
            asset2 = DatasetAsset(
                dataset_id=dataset.id,
                key="data",
                href="/app/storage/second.tif",
            )
            test_db_session.add(asset2)
            await test_db_session.flush()

    async def test_dataset_asset_cascade_delete(self, client, test_db_session):
        """Deleting a Dataset cascades to delete its DatasetAsset rows."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        asset = DatasetAsset(
            dataset_id=dataset.id,
            key="data",
            href="/app/storage/cascade_test.tif",
        )
        test_db_session.add(asset)
        await test_db_session.flush()
        asset_id = asset.id

        # Delete the dataset -- cascade should remove the asset
        await test_db_session.delete(dataset)
        await test_db_session.flush()

        result = await test_db_session.execute(
            select(DatasetAsset).where(DatasetAsset.id == asset_id)
        )
        assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# to_stac_properties tests
# ---------------------------------------------------------------------------


class TestGsdUnits:
    """fix(#1375 review): ``gsd`` is metres by STAC's definition, and
    ``res_x``/``res_y`` are in the CRS's own unit.

    #1375 made this reachable for remote rasters — it is the change that
    starts populating their resolutions — and EPSG:4326 is ordinary in the
    STAC catalogs those resolutions now come from, so the degree case is not
    an exotic one. These are pure model-level unit tests: no DB row, because
    ``to_stac_properties`` reads only the fields set here.
    """

    @staticmethod
    def _asset(crs_wkt: str | None, res: float) -> RasterAsset:
        return RasterAsset(
            dataset_id=uuid.uuid4(),
            asset_uri="/app/storage/x.tif",
            crs_wkt=crs_wkt,
            res_x=res,
            res_y=-res,
        )

    def test_a_metre_based_projection_publishes_the_resolution_unchanged(self):
        from rasterio.crs import CRS

        wkt = CRS.from_epsg(32621).to_wkt(version="WKT2_2019")
        props = self._asset(wkt, 10.0).to_stac_properties()
        assert props["gsd"] == pytest.approx(10.0)

    def test_a_foot_based_projection_is_converted_to_metres(self):
        """EPSG:2263 (NY Long Island) measures in US survey feet. A 10-foot
        pixel is 3.048 m, and publishing the raw 10 overstated it by 3.28x."""
        from rasterio.crs import CRS

        wkt = CRS.from_epsg(2263).to_wkt(version="WKT2_2019")
        props = self._asset(wkt, 10.0).to_stac_properties()
        assert props["gsd"] == pytest.approx(3.048006, rel=1e-4)

    def test_a_geographic_crs_omits_gsd_rather_than_publishing_degrees(self):
        """The case the review named: a 0.0001° pixel is roughly 11 m, and
        publishing 0.0001 into a metres field reads as a tenth of a
        millimetre. An optional field left out is always conformant."""
        from rasterio.crs import CRS

        wkt = CRS.from_epsg(4326).to_wkt(version="WKT2_2019")
        props = self._asset(wkt, 0.0001).to_stac_properties()
        assert "gsd" not in props
        # The resolution itself still reaches CRS-aware consumers through the
        # row; it is only this metres-defined export that declines to guess.
        assert props["proj:wkt2"] == wkt

    def test_an_unknown_crs_omits_gsd(self):
        """No WKT, so no unit, so no defensible number. Covers the
        unparseable case too — both resolve to None."""
        assert "gsd" not in self._asset(None, 10.0).to_stac_properties()
        assert "gsd" not in self._asset("GEOGCS[...]", 10.0).to_stac_properties()


class TestToStacProperties:
    async def test_to_stac_properties_full(self, client, test_db_session):
        """to_stac_properties() with full metadata returns complete STAC dict."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        raster = RasterAsset(
            dataset_id=dataset.id,
            asset_uri="/app/storage/full.tif",
            epsg=4326,
            crs_wkt="GEOGCS[...]",
            width=1024,
            height=2048,
            res_x=0.001,
            res_y=-0.001,
            band_count=3,
            band_info=[
                {"dtype": "uint8", "nodata": 0, "color_interp": "Red"},
                {"dtype": "uint8", "nodata": 0, "color_interp": "Green"},
                {"dtype": "uint8", "nodata": 0, "color_interp": "Blue"},
            ],
        )
        test_db_session.add(raster)
        await test_db_session.flush()

        props = raster.to_stac_properties()

        assert props["proj:code"] == "EPSG:4326"
        assert props["proj:wkt2"] == "GEOGCS[...]"
        assert props["proj:shape"] == [2048, 1024]  # [height, width]
        # fix(#1375 review): this raster's resolution is 0.001 DEGREES and
        # STAC's gsd is metres, so the field is omitted rather than published
        # as 0.001 — which a conforming consumer would read as a millimetre.
        # This assertion used to pin that exact wrong number.
        assert "gsd" not in props
        assert len(props["raster:bands"]) == 3
        assert props["raster:bands"][0] == {
            "data_type": "uint8",
            "nodata": 0,
            "name": "Red",
        }
        assert props["raster:bands"][1] == {
            "data_type": "uint8",
            "nodata": 0,
            "name": "Green",
        }
        assert props["raster:bands"][2] == {
            "data_type": "uint8",
            "nodata": 0,
            "name": "Blue",
        }

    async def test_to_stac_properties_sparse(self, client, test_db_session):
        """to_stac_properties() with only epsg returns Projection v2 code."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        raster = RasterAsset(
            dataset_id=dataset.id,
            asset_uri="/app/storage/sparse.tif",
            epsg=32632,
        )
        test_db_session.add(raster)
        await test_db_session.flush()

        props = raster.to_stac_properties()

        assert props == {"proj:code": "EPSG:32632"}

    async def test_to_stac_properties_empty(self, client, test_db_session):
        """to_stac_properties() with no metadata returns empty dict."""
        admin_id = await _get_admin_id(test_db_session)
        dataset = await _create_record_and_dataset(test_db_session, admin_id=admin_id)

        raster = RasterAsset(
            dataset_id=dataset.id,
            asset_uri="/app/storage/empty.tif",
        )
        test_db_session.add(raster)
        await test_db_session.flush()

        props = raster.to_stac_properties()

        assert props == {}


# ---------------------------------------------------------------------------
# Backfill key assertion tests
# ---------------------------------------------------------------------------


class TestBackfillAssetKeys:
    async def test_backfill_asset_keys(self, client, test_db_session):
        """Validate backfill constants: COG key='data', VRT key='vrt', thumbnail, overview."""
        admin_id = await _get_admin_id(test_db_session)

        # Create COG dataset + asset
        cog_dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )
        cog_data_asset = DatasetAsset(
            dataset_id=cog_dataset.id,
            key="data",
            href="/app/storage/cog.tif",
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"],
        )
        test_db_session.add(cog_data_asset)

        # Create VRT dataset + asset
        vrt_dataset = await _create_record_and_dataset(
            test_db_session, admin_id=admin_id
        )
        vrt_data_asset = DatasetAsset(
            dataset_id=vrt_dataset.id,
            key="vrt",
            href="/app/storage/mosaic.vrt",
            media_type="application/x-gdal-vrt",
            roles=["data", "virtual"],
        )
        test_db_session.add(vrt_data_asset)

        # Create thumbnail + overview for COG dataset
        thumb_asset = DatasetAsset(
            dataset_id=cog_dataset.id,
            key="thumbnail",
            href="/app/storage/thumb_256.png",
            media_type="image/png",
            roles=["thumbnail"],
        )
        overview_asset = DatasetAsset(
            dataset_id=cog_dataset.id,
            key="overview",
            href="/app/storage/thumb_512.png",
            media_type="image/png",
            roles=["overview"],
        )
        test_db_session.add(thumb_asset)
        test_db_session.add(overview_asset)
        await test_db_session.flush()

        # Verify COG data asset
        await test_db_session.refresh(cog_data_asset)
        assert cog_data_asset.key == "data"
        assert (
            cog_data_asset.media_type
            == "image/tiff; application=geotiff; profile=cloud-optimized"
        )
        assert cog_data_asset.roles == ["data"]

        # Verify VRT data asset
        await test_db_session.refresh(vrt_data_asset)
        assert vrt_data_asset.key == "vrt"
        assert vrt_data_asset.media_type == "application/x-gdal-vrt"
        assert vrt_data_asset.roles == ["data", "virtual"]

        # Verify thumbnail
        await test_db_session.refresh(thumb_asset)
        assert thumb_asset.key == "thumbnail"
        assert thumb_asset.media_type == "image/png"
        assert thumb_asset.roles == ["thumbnail"]

        # Verify overview
        await test_db_session.refresh(overview_asset)
        assert overview_asset.key == "overview"
        assert overview_asset.media_type == "image/png"
        assert overview_asset.roles == ["overview"]
