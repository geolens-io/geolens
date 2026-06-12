"""Unit tests for modality-aware build_assets and unified assets dict.

These are pure unit tests -- no database or fixtures required.
Uses SimpleNamespace mocks for Dataset and Record objects.
"""

from types import SimpleNamespace

from app.modules.catalog.search.service import build_assets


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
        assets = build_assets(ds, API_URL)

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
        assets = build_assets(ds, API_URL)

        assert "download_geojson" in assets
        assert "vector_tiles" not in assets
        assert "ogc_features" not in assets

    def test_raster_dataset_has_raster_tiles(self):
        """Raster datasets should have raster tiles and no vector assets."""
        ds = _make_dataset(record_type="raster_dataset")
        assets = build_assets(ds, API_URL)

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
        assets = build_assets(ds, API_URL)

        assert "raster_tiles" in assets
        assert "download_geojson" not in assets
        assert "vector_tiles" not in assets

    def test_collection_has_empty_assets(self):
        """Collection records should return empty assets dict."""
        ds = _make_dataset(record_type="collection")
        assets = build_assets(ds, API_URL)

        assert assets == {}

    def test_stac_asset_rows_local_storage_omitted(self):
        """GAP-031: local-storage DatasetAsset rows are omitted (no dead /assets/ URL).

        dataset_assets is never populated (BUG-041), so this tests the path
        that would have been taken had it been populated. The fix ensures no
        /assets/{key} proxy URL is emitted for local storage.
        """
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
        # Default storage_backend="local" → all stac rows skipped (no proxy URL)
        assets = build_assets(ds, API_URL, stac_asset_rows=stac_rows)

        # Computed raster_tiles still present; local storage "data" asset omitted
        assert "raster_tiles" in assets
        assert "data" not in assets, (
            "GAP-031: local storage asset must not appear in output"
        )

    def test_stac_asset_precedence_local_does_not_override(self):
        """GAP-031: local-storage DatasetAsset row does NOT override computed keys.

        Previously a local-storage row could clobber the computed raster_tiles
        entry with a /assets/ proxy URL.  After GAP-031 the row is skipped.
        """
        ds = _make_dataset(record_type="raster_dataset")
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
        # Default storage_backend="local" → stac row skipped
        assets = build_assets(ds, API_URL, stac_asset_rows=stac_rows)

        # Computed raster_tiles is preserved; local storage row was not applied
        assert "raster_tiles" in assets
        assert assets["raster_tiles"]["title"] == "Raster tiles", (
            "GAP-031: computed raster_tiles should not be overridden by local-storage row"
        )

    def test_default_record_type_fallback(self):
        """When record_type is None, defaults to vector_dataset behavior."""
        record = SimpleNamespace(record_type=None)
        ds = SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            table_name="test_table",
            record=record,
        )
        assets = build_assets(ds, API_URL)

        assert "download_geojson" in assets
        assert "raster_tiles" not in assets
