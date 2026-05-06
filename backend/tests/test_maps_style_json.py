"""Tests for saved map MapLibre style JSON import/export helpers."""

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import MapLayerResponse
from app.modules.catalog.maps.style_json import (
    build_maplibre_style,
    parse_maplibre_style_import,
)
from app.processing.tiles.signing import verify_tile_signature


def _map(**overrides):
    map_obj = Map(
        id=overrides.get("id", uuid.uuid4()),
        name=overrides.get("name", "Transit map"),
        description=overrides.get("description", "Routes and stops"),
        created_by=uuid.uuid4(),
        center_lng=-73.98,
        center_lat=40.75,
        zoom=11,
        bearing=15,
        pitch=30,
        basemap_style="openfreemap-positron",
        show_basemap_labels=True,
        visibility="private",
    )
    return map_obj


def _layer(**overrides):
    return MapLayerResponse(
        id=overrides.get("id", uuid.uuid4()),
        dataset_id=overrides.get("dataset_id", uuid.uuid4()),
        dataset_name=overrides.get("dataset_name", "Stops"),
        dataset_geometry_type=overrides.get("dataset_geometry_type", "POINT"),
        dataset_table_name=overrides.get("dataset_table_name", "public_stops"),
        dataset_extent_bbox=None,
        dataset_column_info=None,
        dataset_feature_count=None,
        dataset_sample_values=None,
        display_name=overrides.get("display_name", "Stops"),
        sort_order=overrides.get("sort_order", 0),
        visible=overrides.get("visible", True),
        opacity=overrides.get("opacity", 0.9),
        paint=overrides.get(
            "paint",
            {
                "circle-color": "#2563eb",
                "circle-radius": 6,
                "_outline-color": "#111827",
            },
        ),
        layout=overrides.get("layout", {}),
        layer_type=overrides.get("layer_type", "vector_geolens"),
        dataset_record_type=overrides.get("dataset_record_type", "vector_dataset"),
        filter=overrides.get("filter", ["==", "status", "open"]),
        label_config=overrides.get("label_config", {"column": "name"}),
        popup_config=None,
        style_config=overrides.get("style_config", None),
        show_in_legend=True,
        is_3d=overrides.get("is_3d", False),
        is_dem=overrides.get("is_dem", False),
        dem_vertical_units=overrides.get("dem_vertical_units", None),
    )


def _dem_layer(dem_id=None, **overrides):
    defaults = {
        "id": uuid.uuid4(),
        "dataset_id": dem_id or uuid.uuid4(),
        "dataset_name": "Elevation",
        "dataset_geometry_type": None,
        "dataset_table_name": "dem_tiles",
        "layer_type": "raster_geolens",
        "dataset_record_type": "raster_dataset",
        "is_dem": True,
        "filter": None,
        "label_config": None,
        "style_config": {"render_mode": "hillshade"},
        "paint": {
            "hillshade-illumination-direction": 315,
            "hillshade-exaggeration": 0.7,
            "hillshade-shadow-color": "#222222",
        },
        "layout": {},
    }
    defaults.update(overrides)
    return _layer(**defaults)


def test_build_maplibre_style_exports_clean_sources_layers_and_viewport():
    dataset_id = uuid.uuid4()
    layer = _layer(dataset_id=dataset_id)

    style = build_maplibre_style(_map(), [layer])

    assert style["version"] == 8
    assert style["center"] == [-73.98, 40.75]
    assert style["zoom"] == 11
    assert style["sprite"] == [{"id": "geolens", "url": "/maps/sprites/geolens"}]
    assert style["glyphs"].endswith("/{fontstack}/{range}.pbf")
    assert list(style["sources"]) == [f"geolens-{dataset_id}"]
    source = style["sources"][f"geolens-{dataset_id}"]
    assert source["type"] == "vector"
    assert source["metadata"]["geolens"]["dataset_id"] == str(dataset_id)
    tile_url = source["tiles"][0]
    assert tile_url.startswith("/tiles/data.public_stops/{z}/{x}/{y}.pbf?")
    tile_params = parse_qs(urlsplit(tile_url).query)
    assert tile_params["scope"] == ["public_stops"]
    assert "sig" in tile_params
    assert "exp" in tile_params
    assert verify_tile_signature(
        "public_stops", int(tile_params["exp"][0]), tile_params["sig"][0]
    )

    primary = style["layers"][0]
    assert primary["type"] == "circle"
    assert primary["filter"] == ["==", "status", "open"]
    assert "_outline-color" not in primary["paint"]
    assert primary["metadata"]["geolens"]["style_config"] is None
    assert style["layers"][1]["id"].endswith("-label")
    assert style["layers"][1]["layout"]["text-field"] == ["get", "name"]


def test_build_maplibre_style_consolidates_symbol_label_output():
    layer = _layer(
        style_config={
            "render_mode": "symbol",
            "symbol": {
                "iconImage": "bus",
                "iconSize": 1.25,
                "iconRotation": 30,
                "iconAnchor": "bottom",
                "iconOffset": [0, -1],
            },
        },
        label_config={"column": "route"},
    )

    style = build_maplibre_style(_map(), [layer])

    assert len(style["layers"]) == 1
    symbol = style["layers"][0]
    assert symbol["type"] == "symbol"
    assert symbol["layout"]["icon-image"] == "geolens:bus"
    assert symbol["layout"]["icon-size"] == 1.25
    assert symbol["layout"]["icon-rotate"] == 30
    assert symbol["layout"]["icon-anchor"] == "bottom"
    assert symbol["layout"]["icon-offset"] == [0, -1]
    assert symbol["layout"]["text-field"] == ["get", "route"]


def test_build_maplibre_style_exports_fill_companion_layers():
    layer = _layer(
        dataset_geometry_type="POLYGON",
        paint={"fill-color": "#94a3b8"},
        label_config=None,
        style_config={
            "builder": {
                "outlineColor": "#112233",
                "outlineWidth": 4,
                "heightColumn": "height_m",
            }
        },
    )

    style = build_maplibre_style(_map(), [layer])

    assert [entry["type"] for entry in style["layers"]] == [
        "fill",
        "line",
        "fill-extrusion",
    ]
    fill, outline, extrusion = style["layers"]
    assert fill["metadata"]["geolens"]["style_config"] == {
        "builder": {
            "outlineColor": "#112233",
            "outlineWidth": 4,
            "heightColumn": "height_m",
        }
    }
    assert outline["id"] == f"{fill['id']}-outline"
    assert outline["metadata"]["geolens"]["companion"] == "outline"
    assert outline["paint"] == {
        "line-color": "#112233",
        "line-width": 4,
        "line-opacity": 0.9,
    }
    assert outline["filter"] == ["==", "status", "open"]
    assert extrusion["id"] == f"{fill['id']}-extrusion"
    assert extrusion["metadata"]["geolens"]["companion"] == "extrusion"
    assert extrusion["paint"]["fill-extrusion-height"] == [
        "coalesce",
        ["to-number", ["get", "height_m"], 0],
        0,
    ]
    assert extrusion["paint"]["fill-extrusion-color"] == "#94a3b8"


def test_build_maplibre_style_emits_raster_dem_source_for_hillshade():
    dem_id = uuid.uuid4()
    layer = _dem_layer(dem_id=dem_id)
    style = build_maplibre_style(_map(), [layer])
    source = style["sources"][f"geolens-{dem_id}"]
    assert source["type"] == "raster-dem"
    assert source["encoding"] == "mapbox"
    assert source["tileSize"] == 256
    assert source["tiles"][0].startswith(f"/raster-tiles/{dem_id}/tiles/")


def test_build_maplibre_style_emits_hillshade_layer_type_and_no_fill_companions():
    layer = _dem_layer()
    style = build_maplibre_style(_map(), [layer])
    layer_types = [entry["type"] for entry in style["layers"]]
    assert layer_types == ["hillshade"]
    primary = style["layers"][0]
    assert primary["type"] == "hillshade"
    assert "source-layer" not in primary
    assert set(primary["paint"]).issubset(
        {
            "hillshade-illumination-direction",
            "hillshade-illumination-anchor",
            "hillshade-exaggeration",
            "hillshade-shadow-color",
            "hillshade-highlight-color",
            "hillshade-accent-color",
        }
    )
    assert primary["paint"]["hillshade-exaggeration"] == 0.7


def test_build_maplibre_style_exports_terrain_block():
    dem_id = uuid.uuid4()
    map_obj = _map()
    map_obj.terrain_config = {
        "enabled": True,
        "source_dataset_id": str(dem_id),
        "exaggeration": 2.5,
    }
    style = build_maplibre_style(map_obj, [_dem_layer(dem_id=dem_id)])
    assert style["terrain"] == {
        "source": f"geolens-{dem_id}",
        "exaggeration": 2.5,
    }
    # metadata fallback is still emitted
    assert style["metadata"]["geolens"]["terrain_config"]["enabled"] is True
    assert style["metadata"]["geolens"]["terrain_config"]["source_dataset_id"] == str(
        dem_id
    )


def test_build_maplibre_style_omits_terrain_block_when_dem_source_missing():
    map_obj = _map()
    map_obj.terrain_config = {
        "enabled": True,
        "source_dataset_id": str(uuid.uuid4()),  # no matching layer below
        "exaggeration": 1.5,
    }
    style = build_maplibre_style(map_obj, [_layer()])  # vector layer only
    assert "terrain" not in style
    assert style["metadata"]["geolens"]["terrain_config"]["enabled"] is True


def test_build_maplibre_style_preserves_builder_style_config_in_layer_metadata():
    layer = _layer(
        dataset_geometry_type="POLYGON",
        paint={"fill-color": "#94a3b8"},
        label_config=None,
        style_config={
            "builder": {
                "outlineColor": "#aabbcc",
                "outlineWidth": 2,
                "heightColumn": "h",
                "_private": "should-be-dropped",
            },
            "render_mode": None,  # not a real render mode; ignored by allowlist
        },
    )
    style = build_maplibre_style(_map(), [layer])
    primary = style["layers"][0]
    builder = primary["metadata"]["geolens"]["style_config"]["builder"]
    assert builder["outlineColor"] == "#aabbcc"
    assert builder["outlineWidth"] == 2
    assert builder["heightColumn"] == "h"
    assert "_private" not in builder


def test_parse_maplibre_style_import_matches_geolens_sources_and_warns_external():
    dataset_id = uuid.uuid4()
    style = {
        "version": 8,
        "name": "Imported",
        "center": [1, 2],
        "zoom": 4,
        "sources": {
            "matched": {
                "type": "vector",
                "tiles": ["/tiles/data.tbl/{z}/{x}/{y}.pbf"],
                "metadata": {"geolens": {"dataset_id": str(dataset_id)}},
            },
            "external": {
                "type": "vector",
                "tiles": ["https://tiles.example.com/{z}/{x}/{y}.pbf"],
            },
        },
        "layers": [
            {
                "id": "supported",
                "type": "symbol",
                "source": "matched",
                "source-layer": "tbl",
                "paint": {"text-color": "#111827", "_private": True},
                "layout": {"icon-image": "geolens:bus", "text-field": ["get", "name"]},
                "metadata": {
                    "geolens": {
                        "layer_id": "layer-1",
                        "display_name": "Supported",
                        "sort_order": 3,
                        "opacity": 0.5,
                        "label_config": {"column": "name", "_private": True},
                        "style_config": {
                            "render_mode": "symbol",
                            "symbol": {"iconImage": "bus", "_private": True},
                            "builder": {"fillDisabled": True},
                            "_private": True,
                            "unknown": "ignored",
                        },
                    }
                },
            },
            {
                "id": "supported-outline",
                "type": "line",
                "source": "matched",
                "metadata": {
                    "geolens": {
                        "companion": "outline",
                        "parent_layer_id": "layer-1",
                    }
                },
            },
            {
                "id": "supported-extrusion",
                "type": "fill-extrusion",
                "source": "matched",
                "metadata": {
                    "geolens": {
                        "companion": "extrusion",
                        "parent_layer_id": "layer-1",
                    }
                },
            },
            {"id": "skipped", "type": "circle", "source": "external"},
        ],
    }

    imported = parse_maplibre_style_import(style)

    assert imported.name == "Imported"
    assert imported.center_lng == 1
    assert imported.center_lat == 2
    assert imported.zoom == 4
    assert imported.summary.sources_matched == 1
    assert imported.summary.sources_unsupported == 1
    assert imported.summary.layers_imported == 1
    assert imported.summary.layers_skipped == 1
    assert [warning.code for warning in imported.summary.warnings] == [
        "unsupported_source",
        "skipped_layer",
    ]
    layer = imported.layers[0]
    assert layer.dataset_id == dataset_id
    assert layer.display_name == "Supported"
    assert layer.sort_order == 3
    assert layer.opacity == 0.5
    assert "_private" not in layer.paint
    assert layer.label_config == {"column": "name"}
    assert layer.style_config == {
        "render_mode": "symbol",
        "symbol": {"iconImage": "bus"},
        "builder": {"fillDisabled": True},
    }


def test_parse_maplibre_style_import_rejects_unsupported_version():
    with pytest.raises(ValueError, match="version 8"):
        parse_maplibre_style_import({"version": 7, "sources": {}, "layers": []})
