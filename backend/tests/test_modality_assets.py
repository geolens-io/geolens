"""Unit tests for modality-aware _build_assets and unified assets dict.

These are pure unit tests -- no database or fixtures required.
Uses SimpleNamespace mocks for Dataset and Record objects.
"""

from types import SimpleNamespace

from app.search.service import _build_assets


def _make_dataset(
    *,
    record_type: str = "vector_dataset",
    table_name: str | None = "test_table",
    dataset_id: str = "00000000-0000-0000-0000-000000000001",
) -> SimpleNamespace:
    """Create a minimal mock Dataset with nested record."""
    record = SimpleNamespace(record_type=record_type)
    return SimpleNamespace(id=dataset_id, table_name=table_name, record=record)


API_URL = "http://localhost:8080/api"


class TestModalityAssets:
    def test_vector_dataset_has_download_links(self):
        """Vector datasets should have download links, vector tiles, and OGC features."""
        ds = _make_dataset(record_type="vector_dataset", table_name="parcels")
        assets = _build_assets(ds, API_URL)

        assert "download_geojson" in assets
        assert "download_gpkg" in assets
        assert "download_shp" in assets
        assert "download_csv" in assets
        assert "vector_tiles" in assets
        assert "ogc_features" in assets
        # Must NOT have raster tiles
        assert "raster_tiles" not in assets

    def test_vector_dataset_no_table_name(self):
        """Vector dataset without table_name omits tile/feature assets."""
        ds = _make_dataset(record_type="vector_dataset", table_name=None)
        assets = _build_assets(ds, API_URL)

        assert "download_geojson" in assets
        assert "vector_tiles" not in assets
        assert "ogc_features" not in assets

    def test_raster_dataset_has_raster_tiles(self):
        """Raster datasets should have raster tiles and no vector assets."""
        ds = _make_dataset(record_type="raster_dataset")
        assets = _build_assets(ds, API_URL)

        assert "raster_tiles" in assets
        assert assets["raster_tiles"]["type"] == "image/png"
        # Must NOT have vector download links
        assert "download_geojson" not in assets
        assert "download_gpkg" not in assets
        assert "download_shp" not in assets
        assert "download_csv" not in assets
        assert "vector_tiles" not in assets
        assert "ogc_features" not in assets

    def test_vrt_dataset_has_raster_tiles(self):
        """VRT datasets should have raster tiles like raster datasets."""
        ds = _make_dataset(record_type="vrt_dataset")
        assets = _build_assets(ds, API_URL)

        assert "raster_tiles" in assets
        assert "download_geojson" not in assets
        assert "vector_tiles" not in assets

    def test_collection_has_empty_assets(self):
        """Collection records should return empty assets dict."""
        ds = _make_dataset(record_type="collection")
        assets = _build_assets(ds, API_URL)

        assert assets == {}

    def test_stac_asset_rows_merged(self):
        """DatasetAsset rows are merged into the unified assets dict."""
        ds = _make_dataset(record_type="raster_dataset")
        stac_rows = [
            {
                "key": "data",
                "href": "/storage/file.tif",
                "media_type": "image/tiff",
                "roles": ["data"],
                "title": "COG",
                "description": None,
            },
        ]
        assets = _build_assets(ds, API_URL, stac_asset_rows=stac_rows)

        # Should have both computed and merged assets
        assert "raster_tiles" in assets
        assert "data" in assets
        assert (
            assets["data"]["href"]
            == "http://localhost:8080/api/assets/storage/file.tif"
        )

    def test_stac_asset_precedence(self):
        """DatasetAsset rows win on key conflict with computed assets."""
        ds = _make_dataset(record_type="raster_dataset")
        # Override the computed raster_tiles key
        stac_rows = [
            {
                "key": "raster_tiles",
                "href": "/custom/tiles",
                "media_type": "image/png",
                "roles": ["visual"],
                "title": "Custom Tiles",
                "description": None,
            },
        ]
        assets = _build_assets(ds, API_URL, stac_asset_rows=stac_rows)

        # DatasetAsset row should override computed value
        assert (
            assets["raster_tiles"]["href"]
            == "http://localhost:8080/api/assets/custom/tiles"
        )
        assert assets["raster_tiles"]["title"] == "Custom Tiles"

    def test_default_record_type_fallback(self):
        """When record_type is None, defaults to vector_dataset behavior."""
        record = SimpleNamespace(record_type=None)
        ds = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            table_name="test_table",
            record=record,
        )
        assets = _build_assets(ds, API_URL)

        assert "download_geojson" in assets
        assert "raster_tiles" not in assets
