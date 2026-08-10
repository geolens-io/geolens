"""fix(#1372): raster tile URLs carry ``v=<tile_cache_version>``.

nginx's shared raster_cache keys on ``$arg_v`` (frontend/nginx.conf), so a
raster replace — which bumps ``Dataset.tile_cache_version`` — rolls the shared
cache immediately instead of serving pre-replace bytes for up to
``proxy_cache_valid``. These pins cover the response builders that emit the
versioned template; the token endpoint's pin lives in
``tests/test_raster_tiles.py::TestRasterTokenEndpoint``.
"""

import uuid
from types import SimpleNamespace

from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata
from app.modules.catalog.maps.service_public import _build_shared_layer_dict
from app.modules.catalog.maps.style_json import build_maplibre_style

from tests.test_maps_style_json import _dem_layer, _map
from tests.test_vrt_catalog_175 import _make_mock_dataset, _make_mock_raster_asset


class TestRasterMetadataTileUrlVersion:
    def test_tile_url_carries_tile_cache_version(self):
        dataset = _make_mock_dataset("raster_dataset")
        dataset.tile_cache_version = 7
        asset = _make_mock_raster_asset(
            vrt_type=None, resolution_strategy=None, status="ready"
        )

        result = _build_raster_metadata(dataset, asset, is_admin=False)

        assert result.tile_url == (
            f"/raster-tiles/{dataset.id}/tiles/{{z}}/{{x}}/{{y}}.png?v=7"
        )

    def test_connect_tile_url_stays_unversioned(self):
        """The connect template is copied once into desktop GIS tools, where a
        frozen ``v`` would pin exactly the staleness the param exists to bust."""
        dataset = _make_mock_dataset("raster_dataset")
        dataset.tile_cache_version = 7
        asset = _make_mock_raster_asset(
            vrt_type=None, resolution_strategy=None, status="ready"
        )

        result = _build_raster_metadata(
            dataset, asset, is_admin=False, base_url="https://gis.example.com"
        )

        assert "?v=" not in result.connect.tile_url
        assert "&v=" not in result.connect.tile_url
        assert "api_key={your_key}" in result.connect.tile_url


def _shared_layer() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        display_name="Raster",
        sort_order=0,
        visible=True,
        opacity=1.0,
        paint={},
        layout={},
        layer_type="raster_geolens",
        filter=None,
        label_config=None,
        popup_config=None,
        style_config=None,
        show_in_legend=True,
    )


class TestSharedLayerTileUrlVersion:
    def _build(self, tile_version):
        layer = _shared_layer()
        layer_dict, _ = _build_shared_layer_dict(
            layer,
            ds_name="Raster",
            ds_geom_type=None,
            ds_table_name=None,
            ds_column_info=None,
            ds_visibility="public",
            ds_record_type="raster_dataset",
            ds_is_3d=None,
            ds_feature_count=None,
            ds_is_dem=None,
            ds_dem_vertical_units=None,
            ds_tile_version=tile_version,
        )
        return layer, layer_dict

    def test_raster_tile_url_carries_version(self):
        layer, layer_dict = self._build(7)
        assert layer_dict["tile_url"] == (
            f"/raster-tiles/{layer.dataset_id}/tiles/{{z}}/{{x}}/{{y}}.png?v=7"
        )

    def test_raster_tile_url_bare_without_version(self):
        layer, layer_dict = self._build(None)
        assert layer_dict["tile_url"] == (
            f"/raster-tiles/{layer.dataset_id}/tiles/{{z}}/{{x}}/{{y}}.png"
        )


class TestStyleJsonRasterTileVersion:
    def test_raster_dem_source_tiles_carry_version(self):
        dem_id = uuid.uuid4()
        layer = _dem_layer(dem_id=dem_id).model_copy(update={"tile_version": 7})
        style = build_maplibre_style(_map(), [layer])
        assert style["sources"][f"geolens-{dem_id}"]["tiles"][0] == (
            f"/raster-tiles/{dem_id}/tiles/{{z}}/{{x}}/{{y}}.png?v=7"
        )

    def test_raster_dem_source_tiles_bare_without_version(self):
        dem_id = uuid.uuid4()
        layer = _dem_layer(dem_id=dem_id)
        style = build_maplibre_style(_map(), [layer])
        assert style["sources"][f"geolens-{dem_id}"]["tiles"][0] == (
            f"/raster-tiles/{dem_id}/tiles/{{z}}/{{x}}/{{y}}.png"
        )
