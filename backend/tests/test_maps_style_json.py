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


def test_build_maplibre_style_emits_line_metrics_for_line_gradient_layer():
    gradient = [
        "interpolate",
        ["linear"],
        ["line-progress"],
        0,
        "#0000ff",
        1,
        "#00ff00",
    ]
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="roads",
        paint={
            "line-color": "#000000",
            "line-width": 2,
            "line-gradient": gradient,
        },
        label_config=None,
        filter=None,
    )
    style = build_maplibre_style(_map(), [layer])
    source = style["sources"][f"geolens-{dataset_id}"]
    assert source["type"] == "vector"
    assert source["lineMetrics"] is True
    primary = style["layers"][0]
    assert primary["type"] == "line"
    assert primary["paint"]["line-gradient"] == gradient


def test_build_maplibre_style_emits_line_metrics_for_builder_intent_only():
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="roads",
        paint={
            "line-color": "#000000",
            "line-width": 2,
        },
        style_config={
            "builder": {
                "lineGradient": {
                    "stops": [{"position": 0.0, "color": "#0000ff"}],
                }
            }
        },
        label_config=None,
        filter=None,
    )
    style = build_maplibre_style(_map(), [layer])
    source = style["sources"][f"geolens-{dataset_id}"]
    assert source["type"] == "vector"
    assert source["lineMetrics"] is True
    primary = style["layers"][0]
    assert "line-gradient" not in primary["paint"]


def test_build_maplibre_style_rejects_array_shaped_builder_line_gradient_intent():
    """Locked contract per CONTEXT D-01: builder.lineGradient must be a non-empty plain dict.

    Arrays must be rejected for parity with the frontend `lineGradientNeededFor` helper, which
    uses `!Array.isArray(intent)`. If a future Phase 256 change emits an array-shaped intent,
    both sides must be aligned in lockstep. This test locks the backend half.
    """
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="roads",
        paint={"line-color": "#000000", "line-width": 2},
        style_config={
            "builder": {
                "lineGradient": [{"position": 0.0, "color": "#0000ff"}],
            }
        },
        label_config=None,
        filter=None,
    )
    style = build_maplibre_style(_map(), [layer])
    source = style["sources"][f"geolens-{dataset_id}"]
    assert source["type"] == "vector"
    assert "lineMetrics" not in source


def test_build_maplibre_style_omits_line_metrics_when_source_has_no_gradient_consumer():
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="roads",
        paint={"line-color": "#000000", "line-width": 2},
        label_config=None,
        filter=None,
    )
    style = build_maplibre_style(_map(), [layer])
    source = style["sources"][f"geolens-{dataset_id}"]
    assert source["type"] == "vector"
    assert "lineMetrics" not in source


def test_build_maplibre_style_drops_line_gradient_paint_on_unsupported_source_type(
    caplog,
):
    """Drop line-gradient paint when the backing source type cannot support lineMetrics.

    Mirrors the Phase 251 _HILLSHADE_PAINT_KEYS silent-filter convention. The
    `style_json` module logger is re-enabled before the test because the conftest's
    alembic `fileConfig(...)` call defaults to `disable_existing_loggers=True`,
    which silences module loggers loaded before alembic ran (see alembic/env.py).
    """
    import logging

    gradient = [
        "interpolate",
        ["linear"],
        ["line-progress"],
        0,
        "#0000ff",
        1,
        "#00ff00",
    ]
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type=None,
        dataset_table_name="raster_tiles",
        layer_type="raster_geolens",
        dataset_record_type="raster_dataset",
        paint={"line-gradient": gradient},
        label_config=None,
        filter=None,
        style_config=None,
    )
    target_logger = logging.getLogger("app.modules.catalog.maps.style_json")
    was_disabled = target_logger.disabled
    target_logger.disabled = False
    try:
        with caplog.at_level(
            logging.WARNING, logger="app.modules.catalog.maps.style_json"
        ):
            style = build_maplibre_style(_map(), [layer])
    finally:
        target_logger.disabled = was_disabled
    source = style["sources"][f"geolens-{dataset_id}"]
    assert source["type"] == "raster"
    assert "lineMetrics" not in source
    primary = style["layers"][0]
    assert "line-gradient" not in primary["paint"]
    assert any(
        "Dropping line-gradient" in record.getMessage() for record in caplog.records
    )


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


def test_parse_maplibre_style_import_restores_terrain_from_top_level_block():
    dem_id = uuid.uuid4()
    style = {
        "version": 8,
        "name": "Terrain",
        "sources": {
            f"geolens-{dem_id}": {
                "type": "raster-dem",
                "tiles": [f"/raster-tiles/{dem_id}/tiles/{{z}}/{{x}}/{{y}}.png"],
                "tileSize": 256,
                "encoding": "mapbox",
                "metadata": {"geolens": {"dataset_id": str(dem_id)}},
            }
        },
        "layers": [],
        "terrain": {"source": f"geolens-{dem_id}", "exaggeration": 2.5},
    }
    imported = parse_maplibre_style_import(style)
    assert imported.terrain_config == {
        "enabled": True,
        "source_dataset_id": str(dem_id),
        "exaggeration": 2.5,
    }


def test_parse_maplibre_style_import_restores_terrain_from_metadata_fallback():
    dem_id = uuid.uuid4()
    style = {
        "version": 8,
        "name": "Terrain meta",
        "sources": {},
        "layers": [],
        "metadata": {
            "geolens": {
                "terrain_config": {
                    "enabled": True,
                    "source_dataset_id": str(dem_id),
                    "exaggeration": 1.5,
                }
            }
        },
    }
    imported = parse_maplibre_style_import(style)
    assert imported.terrain_config["enabled"] is True
    assert imported.terrain_config["source_dataset_id"] == str(dem_id)
    assert imported.terrain_config["exaggeration"] == 1.5


def test_parse_maplibre_style_import_restores_outline_and_extrusion_companions():
    dataset_id = uuid.uuid4()
    style = {
        "version": 8,
        "name": "Companions",
        "sources": {
            "src": {
                "type": "vector",
                "tiles": ["/tiles/data.tbl/{z}/{x}/{y}.pbf"],
                "metadata": {"geolens": {"dataset_id": str(dataset_id)}},
            }
        },
        "layers": [
            {
                "id": "primary",
                "type": "fill",
                "source": "src",
                "source-layer": "tbl",
                "paint": {"fill-color": "#94a3b8"},
                "metadata": {"geolens": {"layer_id": "layer-1"}},
            },
            {
                "id": "primary-outline",
                "type": "line",
                "source": "src",
                "source-layer": "tbl",
                "paint": {"line-color": "#112233", "line-width": 4},
                "metadata": {
                    "geolens": {"companion": "outline", "parent_layer_id": "layer-1"}
                },
            },
            {
                "id": "primary-extrusion",
                "type": "fill-extrusion",
                "source": "src",
                "source-layer": "tbl",
                "paint": {
                    "fill-extrusion-height": [
                        "coalesce",
                        ["to-number", ["get", "height_m"], 0],
                        0,
                    ]
                },
                "metadata": {
                    "geolens": {"companion": "extrusion", "parent_layer_id": "layer-1"}
                },
            },
        ],
    }
    imported = parse_maplibre_style_import(style)
    assert imported.summary.layers_imported == 1
    layer = imported.layers[0]
    assert layer.style_config is not None
    assert layer.style_config["builder"] == {
        "outlineColor": "#112233",
        "outlineWidth": 4,
        "heightColumn": "height_m",
    }


def test_build_maplibre_style_round_trip_preserves_terrain_and_builder_state():
    dem_id = uuid.uuid4()
    polygon_dataset_id = uuid.uuid4()
    polygon_layer = _layer(
        dataset_id=polygon_dataset_id,
        dataset_geometry_type="POLYGON",
        dataset_table_name="parcels",
        filter=None,
        label_config=None,
        paint={"fill-color": "#94a3b8"},
        style_config={
            "builder": {
                "outlineColor": "#abcdef",
                "outlineWidth": 3,
                "heightColumn": "h",
            }
        },
    )
    dem_layer = _dem_layer(dem_id=dem_id)
    map_obj = _map()
    map_obj.terrain_config = {
        "enabled": True,
        "source_dataset_id": str(dem_id),
        "exaggeration": 2.0,
    }

    style = build_maplibre_style(map_obj, [polygon_layer, dem_layer])
    imported = parse_maplibre_style_import(style)

    assert imported.terrain_config is not None
    assert imported.terrain_config["enabled"] is True
    assert imported.terrain_config["source_dataset_id"] == str(dem_id)
    assert imported.terrain_config["exaggeration"] == 2.0

    assert imported.summary.layers_imported == 2

    imported_polygon = next(
        layer for layer in imported.layers if layer.dataset_id == polygon_dataset_id
    )
    assert imported_polygon.style_config is not None
    builder = imported_polygon.style_config["builder"]
    assert builder["outlineColor"] == "#abcdef"
    assert builder["outlineWidth"] == 3
    assert builder["heightColumn"] == "h"

    imported_dem = next(
        layer for layer in imported.layers if layer.dataset_id == dem_id
    )
    assert imported_dem.layer_type == "raster_geolens"
    assert imported_dem.style_config is not None
    assert imported_dem.style_config.get("render_mode") == "hillshade"


def test_parse_maplibre_style_import_restores_line_gradient_paint():
    gradient = [
        "interpolate",
        ["linear"],
        ["line-progress"],
        0,
        "#0000ff",
        1,
        "#00ff00",
    ]
    dataset_id = uuid.uuid4()
    style = {
        "version": 8,
        "name": "Gradient roads",
        "sources": {
            f"geolens-{dataset_id}": {
                "type": "vector",
                "tiles": ["/tiles/data.roads/{z}/{x}/{y}.pbf"],
                "minzoom": 1,
                "maxzoom": 22,
                "lineMetrics": True,
                "metadata": {"geolens": {"dataset_id": str(dataset_id)}},
            }
        },
        "layers": [
            {
                "id": "primary",
                "type": "line",
                "source": f"geolens-{dataset_id}",
                "source-layer": "roads",
                "paint": {
                    "line-color": "#000000",
                    "line-width": 2,
                    "line-gradient": gradient,
                },
                "metadata": {"geolens": {"layer_id": "layer-1"}},
            }
        ],
    }
    imported = parse_maplibre_style_import(style)
    assert imported.summary.layers_imported == 1
    layer = imported.layers[0]
    assert layer.paint["line-gradient"] == gradient
    assert layer.paint["line-color"] == "#000000"
    assert layer.paint["line-width"] == 2


def test_parse_maplibre_style_import_restores_builder_line_gradient_intent():
    dataset_id = uuid.uuid4()
    style = {
        "version": 8,
        "name": "Gradient intent",
        "sources": {
            f"geolens-{dataset_id}": {
                "type": "vector",
                "tiles": ["/tiles/data.roads/{z}/{x}/{y}.pbf"],
                "minzoom": 1,
                "maxzoom": 22,
                "lineMetrics": True,
                "metadata": {"geolens": {"dataset_id": str(dataset_id)}},
            }
        },
        "layers": [
            {
                "id": "primary",
                "type": "line",
                "source": f"geolens-{dataset_id}",
                "source-layer": "roads",
                "paint": {
                    "line-color": "#000000",
                    "line-width": 2,
                },
                "metadata": {
                    "geolens": {
                        "layer_id": "layer-1",
                        "style_config": {
                            "builder": {
                                "lineGradient": {
                                    "stops": [
                                        {"position": 0.0, "color": "#0000ff"},
                                        {"position": 1.0, "color": "#00ff00"},
                                    ]
                                }
                            }
                        },
                    }
                },
            }
        ],
    }
    imported = parse_maplibre_style_import(style)
    assert imported.summary.layers_imported == 1
    layer = imported.layers[0]
    assert layer.style_config is not None
    assert layer.style_config["builder"]["lineGradient"]["stops"] == [
        {"position": 0.0, "color": "#0000ff"},
        {"position": 1.0, "color": "#00ff00"},
    ]


def test_build_maplibre_style_round_trip_preserves_line_gradient_paint_and_source_flag():
    gradient = [
        "interpolate",
        ["linear"],
        ["line-progress"],
        0,
        "#0000ff",
        1,
        "#00ff00",
    ]
    line_dataset_id = uuid.uuid4()
    polygon_dataset_id = uuid.uuid4()
    polygon_layer = _layer(
        dataset_id=polygon_dataset_id,
        dataset_geometry_type="POLYGON",
        dataset_table_name="parcels",
        paint={"fill-color": "#94a3b8"},
        label_config=None,
        filter=None,
        sort_order=0,
    )
    line_layer = _layer(
        id=uuid.uuid4(),
        dataset_id=line_dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="roads",
        paint={
            "line-color": "#000000",
            "line-width": 2,
            "line-gradient": gradient,
        },
        label_config=None,
        filter=None,
        sort_order=1,
    )

    # First export: build_maplibre_style emits paint['line-gradient'] AND source.lineMetrics=true.
    style = build_maplibre_style(_map(), [polygon_layer, line_layer])
    line_source_id = f"geolens-{line_dataset_id}"
    assert style["sources"][line_source_id]["lineMetrics"] is True
    line_export = next(
        entry
        for entry in style["layers"]
        if entry["type"] == "line" and entry["source"] == line_source_id
    )
    assert line_export["paint"]["line-gradient"] == gradient

    # Import: parse_maplibre_style_import restores paint['line-gradient'].
    imported = parse_maplibre_style_import(style)
    assert imported.summary.layers_imported == 2
    imported_line = next(
        entry for entry in imported.layers if entry.dataset_id == line_dataset_id
    )
    assert imported_line.paint["line-gradient"] == gradient

    # Re-export: construct a MapLayerResponse from the imported MapLayerInput and re-build the style.
    # This mechanic mirrors Phase 251 Plan 02 round-trip pattern: imported.layers (MapLayerInput) ->
    # _layer(...) factory -> MapLayerResponse -> build_maplibre_style.
    imported_polygon = next(
        entry for entry in imported.layers if entry.dataset_id == polygon_dataset_id
    )
    re_polygon = _layer(
        dataset_id=imported_polygon.dataset_id,
        dataset_geometry_type="POLYGON",
        dataset_table_name="parcels",
        paint=imported_polygon.paint,
        label_config=None,
        filter=None,
        sort_order=0,
    )
    re_line = _layer(
        dataset_id=imported_line.dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="roads",
        paint=imported_line.paint,
        label_config=None,
        filter=None,
        sort_order=1,
    )
    re_style = build_maplibre_style(_map(), [re_polygon, re_line])

    # Byte-or-semantic identity: line-gradient and lineMetrics survive a full round-trip.
    assert re_style["sources"][f"geolens-{line_dataset_id}"]["lineMetrics"] is True
    re_line_export = next(
        entry
        for entry in re_style["layers"]
        if entry["type"] == "line" and entry["source"] == f"geolens-{line_dataset_id}"
    )
    assert re_line_export["paint"]["line-gradient"] == gradient
