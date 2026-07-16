"""Tests for saved map MapLibre style JSON import/export helpers."""

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import MapLayerResponse
from app.modules.catalog.maps import style_json
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
        dataset_feature_count=overrides.get("dataset_feature_count", None),
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
    assert style["layers"][1]["layout"]["text-font"] == ["Noto Sans Regular"]


def test_hosted_style_tile_signature_is_bound_to_active_tenant(monkeypatch):
    from app.core.db.tenant_session import current_tenant_var

    tenant_id = "00000000-0000-0000-0000-0000000000aa"
    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    token = current_tenant_var.set(tenant_id)
    try:
        style = build_maplibre_style(_map(), [_layer()])
    finally:
        current_tenant_var.reset(token)

    tile_url = next(iter(style["sources"].values()))["tiles"][0]
    params = parse_qs(urlsplit(tile_url).query)
    scope = f"{tenant_id}:public_stops"
    assert params["scope"] == [scope]
    assert verify_tile_signature(scope, int(params["exp"][0]), params["sig"][0])


def test_hosted_style_tile_signature_fails_closed_without_tenant(monkeypatch):
    from app.core.db.tenant_session import current_tenant_var

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    token = current_tenant_var.set(None)
    try:
        with pytest.raises(RuntimeError, match="Tenant context is required"):
            build_maplibre_style(_map(), [_layer()])
    finally:
        current_tenant_var.reset(token)


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
    assert symbol["layout"]["text-font"] == ["Noto Sans Regular"]


def test_build_maplibre_style_exports_line_dasharray_as_paint_property():
    layer = _layer(
        dataset_geometry_type="LineString",
        paint={"line-color": "#2255aa", "line-width": 3},
        layout={"line-dasharray": [4, 2], "line-cap": "square"},
        label_config=None,
    )

    style = build_maplibre_style(_map(), [layer])

    line = style["layers"][0]
    assert line["type"] == "line"
    assert line["paint"]["line-dasharray"] == [4, 2]
    assert "line-dasharray" not in line["layout"]


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
                "heightScale": 1.6,
                "extrusionMinZoom": 12.5,
                "extrusionOpacity": 0.94,
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
            "heightScale": 1.6,
            "extrusionMinZoom": 12.5,
            "extrusionOpacity": 0.94,
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
        "*",
        [
            "coalesce",
            ["to-number", ["get", "height_m"], 0],
            0,
        ],
        1.6,
    ]
    assert extrusion["minzoom"] == 12.5
    assert extrusion["paint"]["fill-extrusion-opacity"] == 0.94
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


def test_build_maplibre_style_exports_basemap_config_metadata():
    map_obj = _map()
    map_obj.basemap_config = {
        "label_mode": "subtle",
        "road_visibility": "hidden",
        "boundary_visibility": "subtle",
        "building_visibility": False,
        "land_water_tone": "muted",
        "relief_contrast": "strong",
    }

    style = build_maplibre_style(map_obj, [_layer()])

    # The serialized output normalizes BasemapConfig through Pydantic, which
    # adds the schema defaults: opacity=1.0 (Phase 1000),
    # background_color=None, sublayer_overrides=None (Phase 1059 BSE-01),
    # and basemap_position=None / projection=None (jsonb-additive).
    expected = {
        **map_obj.basemap_config,
        "opacity": 1.0,
        "background_color": None,
        "sublayer_overrides": None,
        "basemap_position": None,
        "projection": None,
    }
    assert style["metadata"]["geolens"]["basemap_config"] == expected


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


def test_build_maplibre_style_canonicalizes_legacy_builder_aliases():
    layer = _layer(
        dataset_geometry_type="POLYGON",
        paint={"fill-color": "#94a3b8"},
        label_config=None,
        style_config={
            "builder": {
                "outline_color": "#ffcf66",
                "outline_width": 0.25,
                "height_column": "height_m",
                "height_scale": 1.8,
                "extrusion_min_zoom": 12.5,
                "extrusion_opacity": 0.92,
                "cluster_radius": 72,
                "cluster_max_zoom": 13,
                "cluster_color": "#0ea5e9",
                "cluster_text_color": "#f8fafc",
                "cluster_text_size": 14,
            },
        },
    )

    style = build_maplibre_style(_map(), [layer])

    fill, outline, extrusion = style["layers"]
    builder = fill["metadata"]["geolens"]["style_config"]["builder"]
    assert builder == {
        "outlineColor": "#ffcf66",
        "outlineWidth": 0.25,
        "heightColumn": "height_m",
        "heightScale": 1.8,
        "extrusionMinZoom": 12.5,
        "extrusionOpacity": 0.92,
        "clusterRadius": 72,
        "clusterMaxZoom": 13,
        "clusterColor": "#0ea5e9",
        "clusterTextColor": "#f8fafc",
        "clusterTextSize": 14,
    }
    assert outline["paint"]["line-color"] == "#ffcf66"
    assert outline["paint"]["line-width"] == 0.25
    assert extrusion["minzoom"] == 12.5
    assert extrusion["paint"]["fill-extrusion-height"] == [
        "*",
        [
            "coalesce",
            ["to-number", ["get", "height_m"], 0],
            0,
        ],
        1.8,
    ]
    assert extrusion["paint"]["fill-extrusion-opacity"] == 0.92


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


def test_build_maplibre_style_emits_line_arrow_companion_layer():
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="routes",
        paint={"line-color": "#2255aa", "line-width": 3},
        label_config=None,
        style_config={
            "render_mode": "arrow",
            "builder": {
                "arrowColor": "#fb923c",
                "arrowSize": 18,
                "arrowSpacing": 120,
            },
        },
    )

    style = build_maplibre_style(_map(), [layer])

    assert [entry["type"] for entry in style["layers"]] == ["line", "symbol"]
    primary, arrow = style["layers"]
    assert primary["source"] == f"geolens-{dataset_id}"
    assert primary["metadata"]["geolens"]["style_config"] == {
        "render_mode": "arrow",
        "builder": {
            "arrowColor": "#fb923c",
            "arrowSize": 18,
            "arrowSpacing": 120,
        },
    }
    assert arrow["id"] == f"{primary['id']}-arrow"
    assert arrow["metadata"]["geolens"] == {
        "companion": "arrow",
        "parent_layer_id": str(layer.id),
    }
    assert arrow["layout"] == {
        "symbol-placement": "line",
        "symbol-spacing": 120,
        "icon-image": "geolens:arrow-right",
        "icon-size": 18 / 14,
        "icon-allow-overlap": True,
        "icon-ignore-placement": True,
        "icon-rotation-alignment": "map",
    }
    assert arrow["paint"] == {
        "icon-color": "#fb923c",
        "icon-opacity": 0.9,
    }
    assert arrow["filter"] == ["==", "status", "open"]


def test_build_maplibre_style_exports_cluster_intent_with_point_fallback():
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type="POINT",
        dataset_feature_count=120,
        paint={"circle-color": "#2255aa", "circle-radius": 6},
        label_config=None,
        style_config={
            "render_mode": "cluster",
            "builder": {
                "clusterRadius": 64,
                "clusterMaxZoom": 12,
                "clusterColor": "#fb923c",
                "clusterTextColor": "#111827",
                "clusterTextSize": 13,
            },
        },
    )

    style = build_maplibre_style(_map(), [layer])

    source = style["sources"][f"geolens-{dataset_id}"]
    assert source["type"] == "vector"
    assert "cluster" not in source
    assert source["metadata"]["geolens"]["cluster_renderers"] == [
        {
            "layer_id": str(layer.id),
            "source_strategy": "bounded-geojson",
            "status": "eligible",
            "feature_count": 120,
            "geojson_feature_limit": 5000,
            "standalone_fallback": "point-vector-tile",
        }
    ]
    assert [entry["type"] for entry in style["layers"]] == ["circle"]
    primary = style["layers"][0]
    assert primary["paint"] == {"circle-color": "#2255aa", "circle-radius": 6}
    assert primary["metadata"]["geolens"]["style_config"] == {
        "render_mode": "cluster",
        "builder": {
            "clusterRadius": 64,
            "clusterMaxZoom": 12,
            "clusterColor": "#fb923c",
            "clusterTextColor": "#111827",
            "clusterTextSize": 13,
        },
    }


def test_build_maplibre_style_documents_server_cluster_standalone_fallback():
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type="POINT",
        dataset_feature_count=50_000,
        paint={"circle-color": "#2255aa", "circle-radius": 6},
        label_config=None,
        style_config={
            "render_mode": "cluster",
            "builder": {
                "clusterRadius": 72,
                "clusterMaxZoom": 13,
            },
        },
    )

    style = build_maplibre_style(_map(), [layer])

    source = style["sources"][f"geolens-{dataset_id}"]
    assert source["type"] == "vector"
    assert source["tiles"][0].startswith("/tiles/data.public_stops/")
    assert source["metadata"]["geolens"]["cluster_renderers"] == [
        {
            "layer_id": str(layer.id),
            "source_strategy": "server-tile",
            "status": "too-many-features",
            "feature_count": 50_000,
            "geojson_feature_limit": 5000,
            "standalone_fallback": "point-vector-tile",
        }
    ]
    assert style["layers"][0]["metadata"]["geolens"]["style_config"] == {
        "render_mode": "cluster",
        "builder": {
            "clusterRadius": 72,
            "clusterMaxZoom": 13,
        },
    }


def test_parse_maplibre_style_import_preserves_cluster_intent_metadata():
    dataset_id = uuid.uuid4()
    style = build_maplibre_style(
        _map(),
        [
            _layer(
                dataset_id=dataset_id,
                dataset_geometry_type="POINT",
                paint={"circle-color": "#2255aa", "circle-radius": 6},
                label_config=None,
                style_config={
                    "render_mode": "cluster",
                    "builder": {
                        "clusterRadius": 64,
                        "clusterMaxZoom": 12,
                        "clusterColor": "#fb923c",
                        "clusterTextColor": "#111827",
                        "clusterTextSize": 13,
                    },
                },
            )
        ],
    )

    imported = parse_maplibre_style_import(style)

    assert imported.summary.layers_imported == 1
    assert imported.summary.layers_skipped == 0
    layer = imported.layers[0]
    assert layer.dataset_id == dataset_id
    assert layer.paint == {"circle-color": "#2255aa", "circle-radius": 6}
    # Phase 1060 (`a400eb89`): MapLayerInput's `_normalize_paint_boundary`
    # post-validator runs `canonicalize_builder_style_config`, converting
    # builder.* keys to snake_case for storage parity (DB-side canonical form).
    # The wire-format export (build_maplibre_style) still emits camelCase, but
    # the model returned by parse_maplibre_style_import is the persistence shape.
    assert layer.style_config == {
        "render_mode": "cluster",
        "builder": {
            "cluster_radius": 64,
            "cluster_max_zoom": 12,
            "cluster_color": "#fb923c",
            "cluster_text_color": "#111827",
            "cluster_text_size": 13,
        },
    }


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


def test_build_maplibre_style_warns_on_builder_line_gradient_intent_with_unsupported_source(
    caplog,
):
    """WR-03: builder-intent on incompatible source type must emit a warning.

    The paint-drop warning fires only when paint['line-gradient'] is set. Without this
    test, a layer with `style_config.builder.lineGradient` but no paint key (e.g. a
    raster layer with a misconfigured intent) would silently produce no lineMetrics
    and no operator-visible signal. This test asserts the parallel warning path.
    """
    import logging

    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type=None,
        dataset_table_name="raster_tiles",
        layer_type="raster_geolens",
        dataset_record_type="raster_dataset",
        paint={},  # No paint['line-gradient'] — pure builder-intent path.
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
    assert any(
        "Skipping lineMetrics" in record.getMessage() for record in caplog.records
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
    # Phase 1060 (`a400eb89`): MapLayerInput canonicalizes builder.* keys to
    # snake_case (e.g. fillDisabled -> fill_disabled). Note `symbol.iconImage`
    # stays camelCase — the canonicalization map only covers builder keys.
    assert layer.style_config == {
        "render_mode": "symbol",
        "symbol": {"iconImage": "bus"},
        "builder": {"fill_disabled": True},
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
    assert imported.terrain_config == {
        "enabled": True,
        "source_dataset_id": str(dem_id),
        "exaggeration": 1.5,
    }


@pytest.mark.parametrize(
    "terrain_config",
    [
        {
            "enabled": True,
            "source_dataset_id": "not-a-uuid",
            "exaggeration": 1.5,
        },
        {
            "enabled": True,
            "source_dataset_id": str(uuid.uuid4()),
            "exaggeration": 3.5,
        },
    ],
    ids=["invalid-source-dataset-id", "exaggeration-above-maximum"],
)
def test_parse_maplibre_style_import_drops_invalid_terrain_metadata(
    terrain_config,
):
    imported = parse_maplibre_style_import(
        {
            "version": 8,
            "name": "Invalid terrain metadata",
            "sources": {},
            "layers": [],
            "metadata": {"geolens": {"terrain_config": terrain_config}},
        }
    )

    assert imported.terrain_config is None


def test_parse_maplibre_style_import_restores_basemap_config_from_metadata():
    style = {
        "version": 8,
        "name": "Basemap config style",
        "sources": {},
        "layers": [],
        "metadata": {
            "geolens": {
                "basemap_config": {
                    "label_mode": "hidden",
                    "road_visibility": "subtle",
                    "boundary_visibility": "full",
                    "building_visibility": True,
                    "land_water_tone": "contrast",
                    "relief_contrast": "soft",
                }
            }
        },
    }

    imported = parse_maplibre_style_import(style)

    # The Pydantic schema fills opacity=1.0 (v1000 default),
    # background_color=None, sublayer_overrides=None (Phase 1059 BSE-01),
    # and basemap_position=None / projection=None (jsonb-additive default).
    assert imported.basemap_config == {
        "label_mode": "hidden",
        "road_visibility": "subtle",
        "boundary_visibility": "full",
        "building_visibility": True,
        "land_water_tone": "contrast",
        "relief_contrast": "soft",
        "opacity": 1.0,
        "background_color": None,
        "sublayer_overrides": None,
        "basemap_position": None,
        "projection": None,
    }


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
    # Phase 1060 (`a400eb89`): MapLayerInput canonicalizes builder.* keys to
    # snake_case. Companion-restoration helpers in style_json.py still write
    # camelCase into the builder dict, but the model_validator rewrites them
    # at the persistence boundary.
    assert layer.style_config["builder"] == {
        "outline_color": "#112233",
        "outline_width": 4,
        "height_column": "height_m",
    }


def test_parse_maplibre_style_import_restores_line_arrow_companion():
    dataset_id = uuid.uuid4()
    style = {
        "version": 8,
        "name": "Arrow routes",
        "sources": {
            "src": {
                "type": "vector",
                "tiles": ["/tiles/data.routes/{z}/{x}/{y}.pbf"],
                "metadata": {"geolens": {"dataset_id": str(dataset_id)}},
            }
        },
        "layers": [
            {
                "id": "routes",
                "type": "line",
                "source": "src",
                "source-layer": "routes",
                "paint": {"line-color": "#2255aa", "line-width": 3},
                "metadata": {"geolens": {"layer_id": "layer-1"}},
            },
            {
                "id": "routes-arrow",
                "type": "symbol",
                "source": "src",
                "source-layer": "routes",
                "layout": {
                    "symbol-placement": "line",
                    "symbol-spacing": 120,
                    "icon-image": "geolens:arrow-right",
                    "icon-size": 18 / 14,
                },
                "paint": {"icon-color": "#fb923c", "icon-opacity": 0.9},
                "metadata": {
                    "geolens": {"companion": "arrow", "parent_layer_id": "layer-1"}
                },
            },
        ],
    }

    imported = parse_maplibre_style_import(style)

    assert imported.summary.layers_imported == 1
    layer = imported.layers[0]
    assert layer.dataset_id == dataset_id
    # Phase 1060 (`a400eb89`): MapLayerInput canonicalizes builder.* keys to
    # snake_case. Arrow size/spacing also come back as floats because
    # `_builder_from_arrow_companion` runs the layout values through
    # `_finite_number`, which casts to float.
    assert layer.style_config == {
        "render_mode": "arrow",
        "builder": {
            "arrow_color": "#fb923c",
            "arrow_size": 18.0,
            "arrow_spacing": 120.0,
        },
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
                "heightScale": 1.4,
                "extrusionMinZoom": 12.25,
                "extrusionOpacity": 0.91,
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
    # Phase 1060 (`a400eb89`): MapLayerInput canonicalizes builder.* keys to
    # snake_case at the persistence boundary. The full round-trip
    # (build -> parse -> MapLayerInput) lands here with snake_case keys.
    assert builder["outline_color"] == "#abcdef"
    assert builder["outline_width"] == 3
    assert builder["height_column"] == "h"
    assert builder["height_scale"] == 1.4
    assert builder["extrusion_min_zoom"] == 12.25
    assert builder["extrusion_opacity"] == 0.91

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

    # Semantic identity (Python `==` is element-wise structural equality on lists/dicts):
    # line-gradient and lineMetrics survive a full round-trip. Byte-identity is not asserted
    # — undefined paint values may be normalized away across import — but semantic equality
    # is the agreed bar per CONTEXT.md line 59.
    assert re_style["sources"][f"geolens-{line_dataset_id}"]["lineMetrics"] is True
    re_line_export = next(
        entry
        for entry in re_style["layers"]
        if entry["type"] == "line" and entry["source"] == f"geolens-{line_dataset_id}"
    )
    assert re_line_export["paint"]["line-gradient"] == gradient


def test_build_maplibre_style_round_trip_preserves_builder_line_gradient_intent():
    """Full round-trip for the BUILDER-INTENT detection path (WR-01 from REVIEW.md).

    The companion test above covers paint-driven gradient. This one covers the second
    detection input — `style_config.builder.lineGradient` — through the full
    export -> import -> re-export cycle. Phase 256 builder UI is the primary consumer
    of this intent field; if a future allowlist change in `_clean_style_metadata`
    silently strips it, this test catches it. Both lineMetrics and the builder.lineGradient
    payload must survive the full round-trip.
    """
    builder_intent = {
        "stops": [
            {"position": 0.0, "color": "#0000ff"},
            {"position": 1.0, "color": "#00ff00"},
        ]
    }
    line_dataset_id = uuid.uuid4()
    line_layer = _layer(
        id=uuid.uuid4(),
        dataset_id=line_dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="roads",
        paint={
            "line-color": "#000000",
            "line-width": 2,
            # Note: NO paint['line-gradient'] — builder-intent only.
        },
        style_config={"builder": {"lineGradient": builder_intent}},
        label_config=None,
        filter=None,
        sort_order=0,
    )

    # First export: builder intent triggers source.lineMetrics=true; paint omits line-gradient.
    style = build_maplibre_style(_map(), [line_layer])
    line_source_id = f"geolens-{line_dataset_id}"
    assert style["sources"][line_source_id]["lineMetrics"] is True
    line_export = next(
        entry
        for entry in style["layers"]
        if entry["type"] == "line" and entry["source"] == line_source_id
    )
    assert "line-gradient" not in line_export["paint"]
    # Builder intent must round-trip via metadata.geolens.style_config.
    assert (
        line_export["metadata"]["geolens"]["style_config"]["builder"]["lineGradient"]
        == builder_intent
    )

    # Import: parse_maplibre_style_import restores style_config.builder.lineGradient.
    imported = parse_maplibre_style_import(style)
    assert imported.summary.layers_imported == 1
    imported_line = next(
        entry for entry in imported.layers if entry.dataset_id == line_dataset_id
    )
    assert imported_line.style_config is not None
    assert imported_line.style_config["builder"]["lineGradient"] == builder_intent

    # Re-export: thread the imported style_config back through the layer factory.
    re_line = _layer(
        dataset_id=imported_line.dataset_id,
        dataset_geometry_type="LINESTRING",
        dataset_table_name="roads",
        paint=imported_line.paint,
        style_config=imported_line.style_config,
        label_config=None,
        filter=None,
        sort_order=0,
    )
    re_style = build_maplibre_style(_map(), [re_line])

    # Semantic identity: lineMetrics + builder intent both survive the full round-trip.
    assert re_style["sources"][line_source_id]["lineMetrics"] is True
    re_line_export = next(
        entry
        for entry in re_style["layers"]
        if entry["type"] == "line" and entry["source"] == line_source_id
    )
    assert "line-gradient" not in re_line_export["paint"]
    assert (
        re_line_export["metadata"]["geolens"]["style_config"]["builder"]["lineGradient"]
        == builder_intent
    )


# ---------------------------------------------------------------------------
# builder-audit #338 remediation tests (STYLE_JSON cluster)
# ---------------------------------------------------------------------------


def test_export_uses_data_prefixed_mvt_source_layer_p1_01():
    """P1-01: exported vector source-layer must be `data.<table>` to match runtime."""
    layer = _layer(
        dataset_geometry_type="POLYGON",
        dataset_table_name="parcels",
        paint={"fill-color": "#94a3b8"},
        label_config={"column": "name"},
        style_config={"builder": {"outlineColor": "#112233", "outlineWidth": 2}},
    )
    style = build_maplibre_style(_map(), [layer])
    # primary + outline + label all carry the data.-prefixed source-layer.
    for entry in style["layers"]:
        if "source-layer" in entry:
            assert entry["source-layer"] == "data.parcels", entry["id"]


def test_export_uses_tenant_prefixed_mvt_source_layer():
    """Hosted style exports use the physical MVT layer name in every companion."""
    layer = _layer(
        dataset_geometry_type="POLYGON",
        dataset_table_name="parcels",
        paint={"fill-color": "#94a3b8"},
        label_config={"column": "name"},
        style_config={"builder": {"outlineColor": "#112233", "outlineWidth": 2}},
    )

    style = build_maplibre_style(
        _map(),
        [layer],
        mvt_source_layer_prefix=("data_t_12345678_1234_1234_1234_123456789abc"),
    )

    for entry in style["layers"]:
        if "source-layer" in entry:
            assert entry["source-layer"] == (
                "data_t_12345678_1234_1234_1234_123456789abc.parcels"
            ), entry["id"]


def test_export_tile_url_includes_sorted_cols_for_all_references_p1_02():
    """P1-02/P1-03: cols= contains data-driven, label, paint ['get'], and filter columns."""
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type="POINT",
        style_config={"column": "pop"},
        paint={"circle-color": ["get", "category"], "circle-radius": 6},
        label_config={"column": "name"},
        # legacy bare-field filter — must be normalized then walked for `status`.
        filter=["==", "status", "open"],
    )
    style = build_maplibre_style(_map(), [layer])
    tile_url = style["sources"][f"geolens-{dataset_id}"]["tiles"][0]
    cols = parse_qs(urlsplit(tile_url).query)["cols"][0].split(",")
    assert cols == sorted(["pop", "category", "name", "status"])
    # Stable + sorted output.
    assert cols == sorted(cols)


def test_export_cols_includes_extrusion_and_heatmap_builder_columns_p1_02():
    layer = _layer(
        dataset_geometry_type="POLYGON",
        dataset_table_name="parcels",
        paint={"fill-color": "#94a3b8"},
        label_config=None,
        filter=None,
        style_config={
            "builder": {
                "heightColumn": "height_m",
                "heatmapWeightColumn": "magnitude",
            }
        },
    )
    style = build_maplibre_style(_map(), [layer])
    tile_url = style["sources"][f"geolens-{layer.dataset_id}"]["tiles"][0]
    cols = parse_qs(urlsplit(tile_url).query)["cols"][0].split(",")
    assert "height_m" in cols
    assert "magnitude" in cols


def test_terrain_export_emits_dedicated_raster_dem_source_for_image_dem_p1_05():
    """P1-05: terrain must point at a raster-dem source even when DEM renders as image."""
    dem_id = uuid.uuid4()
    map_obj = _map()
    map_obj.terrain_config = {
        "enabled": True,
        "source_dataset_id": str(dem_id),
        "exaggeration": 2.0,
    }
    # DEM rendered as a plain raster image (NOT hillshade) → visible source is `raster`.
    image_dem = _dem_layer(
        dem_id=dem_id,
        style_config={"render_mode": "image"},
        paint={},
    )
    style = build_maplibre_style(map_obj, [image_dem])
    mesh_source_id = f"geolens-terrain-{dem_id}"
    assert style["terrain"]["source"] == mesh_source_id
    assert style["terrain"]["exaggeration"] == 2.0
    assert style["sources"][mesh_source_id]["type"] == "raster-dem"
    assert style["sources"][mesh_source_id]["encoding"] == "mapbox"
    # The visible DEM source stays a plain raster (suppressed terrain-mode visuals).
    assert style["sources"][f"geolens-{dem_id}"]["type"] == "raster"


def test_terrain_export_reuses_visible_raster_dem_when_hillshade_p1_05():
    """P1-05 regression: hillshade DEM keeps pointing terrain at its raster-dem source."""
    dem_id = uuid.uuid4()
    map_obj = _map()
    map_obj.terrain_config = {
        "enabled": True,
        "source_dataset_id": str(dem_id),
        "exaggeration": 2.5,
    }
    style = build_maplibre_style(map_obj, [_dem_layer(dem_id=dem_id)])
    assert style["terrain"] == {"source": f"geolens-{dem_id}", "exaggeration": 2.5}
    assert f"geolens-terrain-{dem_id}" not in style["sources"]


def test_export_emits_color_relief_companion_for_hypso_dem_p1_06():
    """P1-06: a hypsometric-tinted DEM exports a valid color-relief companion layer."""
    dem_id = uuid.uuid4()
    layer = _dem_layer(
        dem_id=dem_id,
        style_config={
            "render_mode": "hillshade",
            "builder": {"hypso_enabled": True, "hypso_ramp": "Inferno"},
        },
    )
    style = build_maplibre_style(_map(), [layer])
    types = [entry["type"] for entry in style["layers"]]
    assert "color-relief" in types
    # Color-relief renders BELOW the hillshade (drawn first in the array).
    assert types.index("color-relief") < types.index("hillshade")
    relief = next(e for e in style["layers"] if e["type"] == "color-relief")
    color_expr = relief["paint"]["color-relief-color"]
    assert color_expr[0] == "interpolate"
    assert color_expr[1] == ["linear"]
    assert color_expr[2] == ["elevation"]
    assert "color-relief-opacity" in relief["paint"]
    assert relief["metadata"]["geolens"]["companion"] == "color-relief"
    assert relief["metadata"]["geolens"]["ramp"] == "Inferno"
    # Builder-internal _hypso-* keys never leak into emitted paint anywhere.
    for entry in style["layers"]:
        assert not any(str(k).startswith("_hypso") for k in entry.get("paint", {}))


def test_color_relief_round_trips_through_build_parse_p1_06():
    dem_id = uuid.uuid4()
    layer = _dem_layer(
        dem_id=dem_id,
        style_config={
            "render_mode": "hillshade",
            "builder": {"hypso_enabled": True, "hypso_ramp": "Plasma"},
        },
    )
    style = build_maplibre_style(_map(), [layer])
    imported = parse_maplibre_style_import(style)
    assert imported.summary.layers_imported == 1
    builder = imported.layers[0].style_config["builder"]
    assert builder.get("hypso_enabled") is True
    assert builder.get("hypso_ramp") == "Plasma"

    # Re-export must emit the color-relief companion again (full round-trip).
    re_layer = _dem_layer(
        dem_id=dem_id,
        style_config=imported.layers[0].style_config,
    )
    re_style = build_maplibre_style(_map(), [re_layer])
    assert any(e["type"] == "color-relief" for e in re_style["layers"])


def test_export_basemap_config_drops_unknown_key_forward_skew_style_04():
    """STYLE-04: a stored basemap_config with an unknown key degrades, never 500s."""
    map_obj = _map()
    # Forward-compat write then rollback: a key the running backend doesn't know.
    map_obj.basemap_config = {
        "label_mode": "subtle",
        "future_unknown_field": {"nested": 1},
    }
    style = build_maplibre_style(map_obj, [_layer()])
    basemap_config = style["metadata"]["geolens"]["basemap_config"]
    assert basemap_config is not None
    assert "future_unknown_field" not in basemap_config
    assert basemap_config["label_mode"] == "subtle"


def test_export_basemap_config_degrades_to_none_on_invalid_value_style_04():
    """STYLE-04: a structurally-invalid stored basemap_config degrades to None."""
    map_obj = _map()
    # background_color must be #RRGGBB; an invalid value would raise under strict
    # validation. On the export path it must degrade rather than 500 the document.
    map_obj.basemap_config = {"background_color": "not-a-hex-color"}
    style = build_maplibre_style(map_obj, [_layer()])
    assert style["metadata"]["geolens"]["basemap_config"] is None


def test_emitted_style_strips_unknown_paint_properties_spec_01():
    """SPEC-01: misspelled / wrong-surface paint properties are stripped on emit."""
    layer = _layer(
        dataset_geometry_type="POLYGON",
        paint={
            "fill-color": "#94a3b8",
            "fill-colour": "#000000",  # misspelled — not a real property
            "circle-radius": 9,  # wrong surface for a fill layer
        },
        label_config=None,
        filter=None,
        style_config=None,
    )
    style = build_maplibre_style(_map(), [layer])
    fill = next(e for e in style["layers"] if e["type"] == "fill")
    assert "fill-color" in fill["paint"]
    assert "fill-colour" not in fill["paint"]
    assert "circle-radius" not in fill["paint"]


def test_emitted_style_strips_wrong_typed_paint_values_spec_01():
    """SPEC-01: a string where ``*-opacity`` expects a number, or a non-string
    ``*-color``, is dropped on emit; valid scalars and expressions survive."""
    layer = _layer(
        dataset_geometry_type="POLYGON",
        paint={
            "fill-color": 123,  # number where a color string is required
            "fill-opacity": "0.5",  # string where a number is required (NaN risk)
            "fill-outline-color": "#1d4ed8",  # valid — kept
        },
        label_config=None,
        filter=None,
        style_config=None,
    )
    style = build_maplibre_style(_map(), [layer])
    fill = next(e for e in style["layers"] if e["type"] == "fill")
    assert "fill-color" not in fill["paint"]
    assert "fill-opacity" not in fill["paint"]
    assert fill["paint"]["fill-outline-color"] == "#1d4ed8"


def test_emitted_style_keeps_expression_opacity_spec_01():
    """SPEC-01 guard: a zoom expression for opacity is a list and is preserved."""
    expr = ["interpolate", ["linear"], ["zoom"], 0, 0.2, 10, 0.9]
    layer = _layer(
        dataset_geometry_type="POLYGON",
        paint={"fill-color": "#94a3b8", "fill-opacity": expr},
        label_config=None,
        filter=None,
        style_config=None,
    )
    style = build_maplibre_style(_map(), [layer])
    fill = next(e for e in style["layers"] if e["type"] == "fill")
    assert fill["paint"]["fill-opacity"] == expr


def test_emitted_style_keeps_all_valid_companion_properties_spec_01():
    """SPEC-01 guard: validation must not strip any property the builder emits."""
    layer = _layer(
        dataset_geometry_type="POLYGON",
        paint={"fill-color": "#94a3b8"},
        label_config={"column": "name"},
        style_config={
            "builder": {
                "outlineColor": "#112233",
                "outlineWidth": 2,
                "heightColumn": "height_m",
            }
        },
    )
    style = build_maplibre_style(_map(), [layer])
    extrusion = next(e for e in style["layers"] if e["type"] == "fill-extrusion")
    assert "fill-extrusion-height" in extrusion["paint"]
    assert "fill-extrusion-vertical-gradient" in extrusion["paint"]
    label = next(e for e in style["layers"] if e["id"].endswith("-label"))
    assert label["layout"]["text-field"] == ["get", "name"]
    assert "text-color" in label["paint"]


def test_style_config_round_trippable_keys_survive_build_parse_spec_03():
    """SPEC-03: legend/ramp/render-mode UI state survives the export/import path."""
    style_config = {
        "mode": "graduated",
        "column": "pop",
        "legendLabel": "Population",
        "reversed": True,
        "sizeRange": [2, 10],
        "sizeLabel": "Size",
        "colorLabel": "Color",
        "heatmapPaint": {"heatmap-radius": 20},
        "savedCirclePaint": {"circle-radius": 5},
    }
    layer = _layer(
        dataset_geometry_type="POINT",
        label_config=None,
        filter=None,
        style_config=style_config,
    )
    style = build_maplibre_style(_map(), [layer])
    emitted = style["layers"][0]["metadata"]["geolens"]["style_config"]
    for key in (
        "legendLabel",
        "reversed",
        "sizeRange",
        "sizeLabel",
        "colorLabel",
        "heatmapPaint",
        "savedCirclePaint",
    ):
        assert emitted[key] == style_config[key], key

    imported = parse_maplibre_style_import(style)
    imported_config = imported.layers[0].style_config
    for key in (
        "legendLabel",
        "reversed",
        "sizeRange",
        "sizeLabel",
        "colorLabel",
        "heatmapPaint",
        "savedCirclePaint",
    ):
        assert imported_config[key] == style_config[key], key


def test_export_emits_projection_at_style_root_spec_07():
    """SPEC-07: basemap_config.projection is emitted at the GL style root."""
    map_obj = _map()
    map_obj.basemap_config = {"projection": "globe"}
    style = build_maplibre_style(map_obj, [_layer()])
    assert style["projection"] == {"type": "globe"}


def test_root_light_and_transition_preserved_on_import_spec_07():
    """SPEC-07: GL root light/transition are preserved across import."""
    style = {
        "version": 8,
        "name": "Lit",
        "sources": {},
        "layers": [],
        "light": {"anchor": "viewport", "intensity": 0.4},
        "transition": {"duration": 300, "delay": 0},
    }
    imported = parse_maplibre_style_import(style)
    assert imported.light == {"anchor": "viewport", "intensity": 0.4}
    assert imported.transition == {"duration": 300, "delay": 0}


@pytest.mark.parametrize(
    "style_config",
    [
        None,
        {"render_mode": "arrow", "builder": {"arrowColor": "#fb923c", "arrowSize": 18}},
        {
            "builder": {
                "outlineColor": "#112233",
                "outlineWidth": 4,
                "heightColumn": "height_m",
                "heightScale": 1.5,
            }
        },
        {
            "render_mode": "cluster",
            "builder": {"clusterRadius": 64, "clusterMaxZoom": 12},
        },
    ],
)
def test_build_parse_build_idempotence_per_render_mode_style_02(style_config):
    """STYLE-02: build -> parse -> build is idempotent per render mode/companion set."""
    geometry = "POLYGON"
    if style_config and style_config.get("render_mode") == "arrow":
        geometry = "LINESTRING"
    elif style_config and style_config.get("render_mode") == "cluster":
        geometry = "POINT"
    dataset_id = uuid.uuid4()
    layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type=geometry,
        dataset_table_name="features",
        paint={"fill-color": "#94a3b8"}
        if geometry == "POLYGON"
        else (
            {"line-color": "#2255aa", "line-width": 3}
            if geometry == "LINESTRING"
            else {"circle-color": "#2255aa", "circle-radius": 6}
        ),
        label_config=None,
        filter=None,
        style_config=style_config,
        dataset_feature_count=120,
    )
    style = build_maplibre_style(_map(), [layer])
    imported = parse_maplibre_style_import(style)
    assert imported.summary.layers_imported == 1

    imported_layer = imported.layers[0]
    re_layer = _layer(
        dataset_id=dataset_id,
        dataset_geometry_type=geometry,
        dataset_table_name="features",
        paint=imported_layer.paint,
        label_config=imported_layer.label_config,
        filter=imported_layer.filter,
        style_config=imported_layer.style_config,
        dataset_feature_count=120,
    )
    re_style = build_maplibre_style(_map(), [re_layer])

    def _layer_types(doc):
        return [entry["type"] for entry in doc["layers"]]

    assert _layer_types(style) == _layer_types(re_style)


def test_default_palette_constants_exported_for_service_shared_style_07():
    """STYLE-07: the default palette/magic constants are named, importable values."""
    assert style_json.DEFAULT_FILL_COLOR == "#3b82f6"
    assert style_json.DEFAULT_STROKE_COLOR == "#1d4ed8"
    assert style_json.DEFAULT_OUTLINE_WIDTH == 1
    assert style_json.DEFAULT_ARROW_BASE_SIZE == 14
    assert style_json.DEFAULT_ARROW_SPACING == 80
    assert style_json.DEFAULT_EXTRUSION_MIN_ZOOM == 14
    assert style_json.EXTRUSION_OPACITY_CAP == 0.85


def test_builder_alias_table_is_single_source_inverse_style_01():
    """STYLE-01: style_json reuses the schemas inverse (incl. folder_group_* keys)."""
    from app.modules.catalog.maps.schemas import BUILDER_SNAKE_TO_CAMEL_KEYS

    assert style_json._BUILDER_KEY_ALIASES is BUILDER_SNAKE_TO_CAMEL_KEYS
    # The previously-drifting folder_group_* keys are now present on export.
    assert style_json._BUILDER_KEY_ALIASES["folder_group_id"] == "folderGroupId"


# ---------------------------------------------------------------------------
# fix(#394) ST-01 / ST-04: symbol icon-image expression hardening
# ---------------------------------------------------------------------------


def test_symbol_icon_expression_zero_pairs_falls_back_flat_st01():
    """ST-01: when every category icon is empty, emit the flat fallback id —
    a zero-pair ["match", input, fallback] (length 3) makes addLayer throw."""
    expr = style_json._symbol_icon_expression(
        {
            "iconImage": "marker",
            "categoryColumn": "kind",
            "categories": [
                {"value": "a", "icon": None},
                {"value": "b"},  # no icon key
            ],
        }
    )
    assert expr == "geolens:marker"


def test_symbol_icon_expression_to_string_input_and_labels_st04():
    """ST-04: match input is to-string-wrapped and labels are stringified so
    numeric MVT values match the editor's stringified sample values."""
    expr = style_json._symbol_icon_expression(
        {
            "iconImage": "marker",
            "categoryColumn": "mag",
            "categories": [
                {"value": 4.0, "icon": "star"},
                {"value": "5", "icon": "circle"},
                {"value": None, "icon": "square"},  # null value skipped
            ],
        }
    )
    assert expr[0] == "match"
    assert expr[1] == ["to-string", ["get", "mag"]]
    # 4.0 stringifies like JS String(4) — no trailing ".0".
    assert expr[2] == "4"
    assert expr[4] == "5"
    # The null-valued pair was skipped: match has exactly 2 pairs + fallback.
    assert len(expr) == 7


def test_vector_source_maxzoom_mirrors_live_builder_394():
    """fix(#394): plain vector sources export maxzoom 14 (overzoom beyond, like
    the live builder); server-cluster sources keep 22 so clusters can expand."""
    plain = _layer(style_config=None)
    source = style_json._source_for_layer(plain)
    assert source["maxzoom"] == 14

    cluster = _layer(
        style_config={"render_mode": "cluster"},
        dataset_feature_count=10,
    )
    cluster_source = style_json._source_for_layer(cluster)
    assert cluster_source["maxzoom"] == 22


# fix(#526 B-044): the builder stores the per-layer zoom range as
# builder-private `_minzoom`/`_maxzoom` layout keys; export previously
# stripped them (underscore-key cleaning) without re-emitting spec-level
# minzoom/maxzoom, so a zoom-limited layer rendered at ALL zooms in the
# exported style.json.
def test_export_emits_layer_zoom_range_from_builder_layout_keys():
    layer = _layer(layout={"_minzoom": 8, "_maxzoom": 12})
    exported = style_json._style_layer_for_map_layer(layer, "src-1")
    primary = next(entry for entry in exported if entry["id"].startswith("layer-"))
    assert primary["minzoom"] == 8
    assert primary["maxzoom"] == 12
    # The builder-private keys themselves must not leak into the layout.
    assert "_minzoom" not in primary["layout"]
    assert "_maxzoom" not in primary["layout"]


def test_export_omits_default_zoom_range():
    layer = _layer(layout={"_minzoom": 0, "_maxzoom": 22})
    exported = style_json._style_layer_for_map_layer(layer, "src-1")
    primary = next(entry for entry in exported if entry["id"].startswith("layer-"))
    assert "minzoom" not in primary
    assert "maxzoom" not in primary
