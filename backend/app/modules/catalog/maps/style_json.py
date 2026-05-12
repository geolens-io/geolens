"""MapLibre style JSON import/export helpers for saved maps."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError

from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import (
    BasemapConfig,
    LEGACY_BUILDER_PAINT_KEYS,
    MapLayerInput,
    MapLayerResponse,
    MapStyleImportSummary,
    MapStyleImportWarning,
)
from app.platform.extensions import get_catalog_port

STYLE_VERSION = 8
GEOLENS_SPRITE_ID = "geolens"
SPRITE_URL = "/maps/sprites/geolens"
GLYPHS_URL = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf"
DEFAULT_FILL_COLOR = "#3b82f6"
DEFAULT_STROKE_COLOR = "#1d4ed8"
DEFAULT_ARROW_ICON = "arrow-right"
DEFAULT_ARROW_BASE_SIZE = 14
CLUSTER_GEOJSON_FEATURE_LIMIT = 5000

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_LABEL_METADATA_KEYS = {
    "column",
    "fontSize",
    "textColor",
    "haloColor",
    "haloWidth",
    "minZoom",
    "maxZoom",
    "placement",
    "textAnchor",
    "textOpacity",
    "textOffset",
    "allowOverlap",
}
_STYLE_METADATA_KEYS = {
    "mode",
    "column",
    "ramp",
    "classCount",
    "method",
    "categories",
    "breaks",
    "colors",
    "target",
    "sizes",
    "render_mode",
    "symbol",
    "builder",
}
_HILLSHADE_PAINT_KEYS = {
    "hillshade-illumination-direction",
    "hillshade-illumination-anchor",
    "hillshade-exaggeration",
    "hillshade-shadow-color",
    "hillshade-highlight-color",
    "hillshade-accent-color",
}
# Source types that can render `line-gradient` paint. MapLibre requires the source
# to also be constructed with `lineMetrics: true` (set by `build_maplibre_style`).
_LINE_GRADIENT_SOURCE_TYPES = {"vector", "geojson"}
_SYMBOL_METADATA_KEYS = {
    "iconImage",
    "iconSize",
    "iconRotation",
    "iconAnchor",
    "iconOffset",
    "categoryColumn",
    "categories",
}
_BUILDER_KEY_ALIASES = {
    "fill_disabled": "fillDisabled",
    "stroke_disabled": "strokeDisabled",
    "fill_opacity_saved": "fillOpacitySaved",
    "outline_width_saved": "outlineWidthSaved",
    "outline_color": "outlineColor",
    "outline_width": "outlineWidth",
    "heatmap_ramp": "heatmapRamp",
    "heatmap_weight_column": "heatmapWeightColumn",
    "height_column": "heightColumn",
    "height_scale": "heightScale",
    "extrusion_min_zoom": "extrusionMinZoom",
    "extrusion_opacity": "extrusionOpacity",
    "arrow_color": "arrowColor",
    "arrow_size": "arrowSize",
    "arrow_spacing": "arrowSpacing",
    "cluster_radius": "clusterRadius",
    "cluster_max_zoom": "clusterMaxZoom",
    "cluster_color": "clusterColor",
    "cluster_text_color": "clusterTextColor",
    "cluster_text_size": "clusterTextSize",
}

logger = logging.getLogger(__name__)


@dataclass
class ImportedStyleMap:
    """Normalized import payload ready for the maps service layer."""

    name: str
    description: str | None
    center_lng: float | None = None
    center_lat: float | None = None
    zoom: float | None = None
    bearing: float | None = None
    pitch: float | None = None
    basemap_style: str | None = None
    layers: list[MapLayerInput] = field(default_factory=list)
    summary: MapStyleImportSummary = field(default_factory=MapStyleImportSummary)
    terrain_config: dict | None = None
    basemap_config: dict | None = None


def _safe_id(value: str) -> str:
    safe = _SAFE_ID_RE.sub("-", value).strip("-")
    return safe or "layer"


def _clean_paint(paint: dict[str, Any] | None) -> dict[str, Any]:
    """Return MapLibre paint without known/private GeoLens builder keys.

    NOTE — `line-gradient` is intentionally NOT filtered here (Phase 255
    GRAD engine contract): `line-gradient` paint is part of the public MapLibre
    style surface and must round-trip through export/import without modification.
    See `_layer_uses_line_gradient` and `_drop_unsupported_line_gradient` in this
    module for the source-type-aware emission path. Do NOT add `line-gradient`
    to LEGACY_BUILDER_PAINT_KEYS in schemas.py — doing so breaks GRAD-05/06.
    """

    clean: dict[str, Any] = {}
    for key, value in dict(paint or {}).items():
        if key in LEGACY_BUILDER_PAINT_KEYS or str(key).startswith("_"):
            continue
        clean[key] = value
    return clean


def _clean_layout(layout: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(layout or {}).items()
        if not str(key).startswith("_")
    }


def _clean_label_metadata(label_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(label_config, dict):
        return None
    clean = {
        key: value
        for key, value in label_config.items()
        if key in _LABEL_METADATA_KEYS and not str(key).startswith("_")
    }
    return clean or None


def _clean_symbol_metadata(symbol: Any) -> dict[str, Any] | None:
    if not isinstance(symbol, dict):
        return None
    clean: dict[str, Any] = {}
    for key, value in symbol.items():
        if key not in _SYMBOL_METADATA_KEYS or str(key).startswith("_"):
            continue
        if key == "categories" and isinstance(value, list):
            categories: list[dict[str, Any]] = []
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                categories.append(
                    {
                        entry_key: entry[entry_key]
                        for entry_key in ("value", "icon")
                        if entry_key in entry
                    }
                )
            clean[key] = categories
        else:
            clean[key] = value
    return clean or None


def _clean_builder_block(value: dict[str, Any]) -> dict[str, Any]:
    """Allow-list builder sub-keys but strip underscore-prefixed private flags."""
    cleaned: dict[str, Any] = {}
    for sub_key, sub_value in value.items():
        if isinstance(sub_key, str) and sub_key.startswith("_"):
            continue
        key = _BUILDER_KEY_ALIASES.get(sub_key, sub_key)
        if sub_key in _BUILDER_KEY_ALIASES and key in cleaned:
            continue
        cleaned[key] = sub_value
    return cleaned


def _clean_style_metadata(style_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(style_config, dict):
        return None
    clean: dict[str, Any] = {}
    for key, value in style_config.items():
        if key not in _STYLE_METADATA_KEYS or str(key).startswith("_"):
            continue
        if key == "symbol":
            symbol = _clean_symbol_metadata(value)
            if symbol:
                clean[key] = symbol
            continue
        if key == "builder":
            if isinstance(value, dict):
                builder = _clean_builder_block(value)
                if builder:
                    clean[key] = builder
            continue
        clean[key] = value
    return clean or None


def _builder_style_config(style_config: dict[str, Any] | None) -> dict[str, Any]:
    builder = (style_config or {}).get("builder")
    return _clean_builder_block(builder) if isinstance(builder, dict) else {}


def _clean_basemap_config(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("basemap_config must be an object")
    try:
        return BasemapConfig.model_validate(value).model_dump(mode="json")
    except ValidationError as exc:
        raise ValueError("Invalid basemap_config metadata") from exc


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _clamp_number(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _extrusion_height_expression(height_column: str, height_scale: float) -> list[Any]:
    base_expression: list[Any] = [
        "coalesce",
        ["to-number", ["get", height_column], 0],
        0,
    ]
    if height_scale == 1:
        return base_expression
    return ["*", base_expression, height_scale]


def _extrusion_column_from_expression(value: Any) -> tuple[str | None, float | None]:
    height_scale: float | None = None
    height_expr = value
    if isinstance(value, list) and len(value) == 3 and value[0] == "*":
        left, right = value[1], value[2]
        if isinstance(right, (int, float)) and not isinstance(right, bool):
            height_expr = left
            height_scale = float(right)
        elif isinstance(left, (int, float)) and not isinstance(left, bool):
            height_expr = right
            height_scale = float(left)

    # Canonical export shape: ["coalesce", ["to-number", ["get", <column>], 0], 0]
    if (
        isinstance(height_expr, list)
        and len(height_expr) >= 2
        and height_expr[0] == "coalesce"
        and isinstance(height_expr[1], list)
        and len(height_expr[1]) >= 2
        and height_expr[1][0] == "to-number"
        and isinstance(height_expr[1][1], list)
        and len(height_expr[1][1]) == 2
        and height_expr[1][1][0] == "get"
        and isinstance(height_expr[1][1][1], str)
    ):
        return height_expr[1][1][1], height_scale
    return None, None


def _layer_uses_line_gradient(layer: MapLayerResponse) -> bool:
    """Return True if this layer needs `lineMetrics: true` on its backing source.

    Detection rule (locked per .planning/phases/255-line-gradient-engine-foundation/255-CONTEXT.md D-01):
      1. `paint['line-gradient']` is set (any non-None value).
      2. `style_config.builder.lineGradient` is a non-empty dict (Phase 256 builder intent).
    Sticky lifecycle (D-02): once a source emits the flag, downstream paths do not
    recompute it on subsequent saves; the source itself is torn down only when no
    consumers remain.
    """
    paint = layer.paint or {}
    if paint.get("line-gradient") is not None:
        return True
    builder = (layer.style_config or {}).get("builder") or {}
    intent = builder.get("lineGradient") if isinstance(builder, dict) else None
    if isinstance(intent, dict) and len(intent) > 0:
        return True
    return False


def _drop_unsupported_line_gradient(
    layer: MapLayerResponse, paint: dict[str, Any], source_type: str
) -> dict[str, Any]:
    """Drop `line-gradient` paint when the backing source type cannot support it.

    Mirrors the Phase 251 `_HILLSHADE_PAINT_KEYS` silent-filter convention and logs
    a warning to API logs. A structured export-summary surface (analogous to
    MapStyleImportSummary) can be added later if a UI consumer surfaces it.
    """
    if "line-gradient" not in paint:
        return paint
    if source_type in _LINE_GRADIENT_SOURCE_TYPES:
        return paint
    filtered = {k: v for k, v in paint.items() if k != "line-gradient"}
    logger.warning(
        "Dropping line-gradient paint on layer %s: source type %r cannot support lineMetrics",
        layer.id,
        source_type,
    )
    return filtered


def _cluster_feature_count(layer: MapLayerResponse) -> int | None:
    count = layer.dataset_feature_count
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        return count
    return None


def _is_cluster_point_vector(layer: MapLayerResponse) -> bool:
    if (layer.style_config or {}).get("render_mode") != "cluster":
        return False
    if layer.is_dem is True:
        return False
    if layer.layer_type == "raster_geolens":
        return False
    if layer.dataset_record_type and layer.dataset_record_type != "vector_dataset":
        return False
    geometry_type = (layer.dataset_geometry_type or "").upper()
    return "POINT" in geometry_type


def _cluster_source_strategy(layer: MapLayerResponse) -> tuple[str, str]:
    count = _cluster_feature_count(layer)
    if (layer.style_config or {}).get("render_mode") != "cluster":
        return "fallback", "not-cluster"
    if not _is_cluster_point_vector(layer):
        return "fallback", "unsupported-source"
    if count is None:
        return "fallback", "missing-count"
    if count > CLUSTER_GEOJSON_FEATURE_LIMIT:
        return "server-tile", "too-many-features"
    return "bounded-geojson", "eligible"


def _append_cluster_source_metadata(
    source: dict[str, Any],
    layer: MapLayerResponse,
) -> None:
    if (layer.style_config or {}).get("render_mode") != "cluster":
        return
    metadata = source.setdefault("metadata", {})
    geolens = metadata.setdefault("geolens", {})
    if not isinstance(geolens, dict):
        return
    strategy, status = _cluster_source_strategy(layer)
    renderers = geolens.setdefault("cluster_renderers", [])
    if not isinstance(renderers, list):
        return
    renderers.append(
        {
            "layer_id": str(layer.id),
            "source_strategy": strategy,
            "status": status,
            "feature_count": _cluster_feature_count(layer),
            "geojson_feature_limit": CLUSTER_GEOJSON_FEATURE_LIMIT,
            "standalone_fallback": "point-vector-tile",
        }
    )


def _geometry_layer_type(
    geometry_type: str | None,
    style_config: dict | None,
    *,
    is_dem: bool = False,
    layer_type: str | None = None,
) -> str:
    render_mode = (style_config or {}).get("render_mode")
    if render_mode == "hillshade" and (is_dem or layer_type == "raster_geolens"):
        return "hillshade"
    if render_mode == "heatmap":
        return "heatmap"
    if render_mode == "symbol":
        return "symbol"
    if render_mode == "arrow":
        return "line"
    if layer_type == "raster_geolens":
        return "raster"
    gt = (geometry_type or "").upper()
    if "POINT" in gt:
        return "circle"
    if "LINE" in gt:
        return "line"
    return "fill"


def _tile_url_for_layer(layer: MapLayerResponse) -> str:
    if layer.layer_type == "raster_geolens" or layer.dataset_record_type in {
        "raster_dataset",
        "vrt_dataset",
    }:
        return f"/raster-tiles/{layer.dataset_id}/tiles/{{z}}/{{x}}/{{y}}.png"
    port = get_catalog_port()
    exp = port.round_tile_expiry()
    params = urlencode(
        {
            "sig": port.generate_tile_signature(layer.dataset_table_name, exp),
            "exp": exp,
            "scope": layer.dataset_table_name,
        }
    )
    return f"/tiles/data.{layer.dataset_table_name}/{{z}}/{{x}}/{{y}}.pbf?{params}"


def _source_for_layer(layer: MapLayerResponse) -> dict[str, Any]:
    source: dict[str, Any]
    if (layer.is_dem is True) and (
        (layer.style_config or {}).get("render_mode") == "hillshade"
    ):
        source = {
            "type": "raster-dem",
            "tiles": [_tile_url_for_layer(layer)],
            "tileSize": 256,
            "encoding": "mapbox",
        }
    elif layer.layer_type == "raster_geolens" or layer.dataset_record_type in {
        "raster_dataset",
        "vrt_dataset",
    }:
        source = {
            "type": "raster",
            "tiles": [_tile_url_for_layer(layer)],
            "tileSize": 256,
        }
    else:
        source = {
            "type": "vector",
            "tiles": [_tile_url_for_layer(layer)],
            "minzoom": 1,
            "maxzoom": 22,
        }
    source["metadata"] = {
        "geolens": {
            "dataset_id": str(layer.dataset_id),
            "table_name": layer.dataset_table_name,
            "geometry_type": layer.dataset_geometry_type,
            "record_type": layer.dataset_record_type,
        }
    }
    _append_cluster_source_metadata(source, layer)
    return source


def _label_layout(label_config: dict[str, Any]) -> dict[str, Any]:
    column = label_config.get("column")
    layout: dict[str, Any] = {}
    if column:
        layout["text-field"] = ["get", column]
    layout["text-size"] = label_config.get("fontSize", 12)
    layout["text-font"] = ["Noto Sans Regular"]
    layout["text-allow-overlap"] = label_config.get("allowOverlap", False)
    layout["text-anchor"] = label_config.get("textAnchor", "center")
    layout["text-offset"] = label_config.get("textOffset", [0, -1.5])
    return layout


def _label_paint(label_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "text-color": label_config.get("textColor", "#111827"),
        "text-halo-color": label_config.get("haloColor", "#ffffff"),
        "text-halo-width": label_config.get("haloWidth", 1.5),
        "text-opacity": label_config.get("textOpacity", 1),
    }


def _symbol_layout_from_style(
    layout: dict[str, Any],
    style_config: dict[str, Any] | None,
    label_config: dict[str, Any] | None,
) -> dict[str, Any]:
    symbol = dict((style_config or {}).get("symbol") or {})
    builder_symbol = dict(
        ((style_config or {}).get("builder") or {}).get("symbol") or {}
    )
    symbol = {**builder_symbol, **symbol}
    next_layout = dict(layout)
    icon_image = _symbol_icon_expression(symbol)
    if icon_image:
        next_layout["icon-image"] = icon_image
    if symbol.get("iconSize") is not None:
        next_layout["icon-size"] = symbol["iconSize"]
    if symbol.get("iconRotation") is not None:
        next_layout["icon-rotate"] = symbol["iconRotation"]
    if symbol.get("iconAnchor"):
        next_layout["icon-anchor"] = symbol["iconAnchor"]
    if symbol.get("iconOffset") is not None:
        next_layout["icon-offset"] = symbol["iconOffset"]
    if label_config and label_config.get("column"):
        next_layout.update(_label_layout(label_config))
    return next_layout


def _symbol_icon_expression(symbol: dict[str, Any]) -> Any:
    fallback = symbol.get("iconImage") or symbol.get("icon_image") or "marker"
    category_column = symbol.get("categoryColumn") or symbol.get("category_column")
    categories = symbol.get("categories")
    if category_column and isinstance(categories, list):
        expression: list[Any] = ["match", ["get", category_column]]
        for entry in categories:
            if not isinstance(entry, dict) or entry.get("icon") is None:
                continue
            expression.append(entry.get("value"))
            expression.append(_sprite_icon_id(entry["icon"]))
        expression.append(_sprite_icon_id(fallback))
        return expression
    return _sprite_icon_id(fallback)


def _sprite_icon_id(icon: Any) -> Any:
    if isinstance(icon, str) and ":" not in icon:
        return f"{GEOLENS_SPRITE_ID}:{icon}"
    if isinstance(icon, list):
        if len(icon) >= 4 and icon[0] == "match":
            result = [icon[0], icon[1]]
            for index in range(2, len(icon) - 1, 2):
                result.append(icon[index])
                if index + 1 < len(icon) - 1:
                    result.append(_sprite_icon_id(icon[index + 1]))
            result.append(_sprite_icon_id(icon[-1]))
            return result
        return icon
    return icon


def _stored_icon_id(icon: Any) -> Any:
    if isinstance(icon, str) and icon.startswith(f"{GEOLENS_SPRITE_ID}:"):
        return icon.split(":", 1)[1]
    if isinstance(icon, list):
        if len(icon) >= 4 and icon[0] == "match":
            result = [icon[0], icon[1]]
            for index in range(2, len(icon) - 1, 2):
                result.append(icon[index])
                if index + 1 < len(icon) - 1:
                    result.append(_stored_icon_id(icon[index + 1]))
            result.append(_stored_icon_id(icon[-1]))
            return result
        return icon
    return icon


def _layer_metadata(layer: MapLayerResponse) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "geolens": {
            "layer_id": str(layer.id),
            "dataset_id": str(layer.dataset_id),
            "display_name": layer.display_name,
            "sort_order": layer.sort_order,
            "opacity": layer.opacity,
            "show_in_legend": layer.show_in_legend,
            "style_config": _clean_style_metadata(layer.style_config),
            "label_config": _clean_label_metadata(layer.label_config),
            "layer_type": layer.layer_type,
        }
    }
    return metadata


def _companion_visibility(
    layer: MapLayerResponse, hidden: bool = False
) -> dict[str, Any]:
    return {"visibility": "none"} if hidden or not layer.visible else {}


def _fill_companion_layers(
    layer: MapLayerResponse,
    source_id: str,
    layer_id: str,
) -> list[dict[str, Any]]:
    builder = _builder_style_config(layer.style_config)
    paint = dict(layer.paint or {})
    stroke_disabled = bool(
        builder.get("strokeDisabled") or paint.get("_stroke-disabled")
    )
    outline_color = (
        builder.get("outlineColor")
        or paint.get("_outline-color")
        or paint.get("outline-color")
        or DEFAULT_STROKE_COLOR
    )
    outline_width = (
        builder.get("outlineWidth")
        or paint.get("_outline-width")
        or paint.get("outline-width")
        or 1
    )
    companions: list[dict[str, Any]] = [
        {
            "id": f"{layer_id}-outline",
            "type": "line",
            "source": source_id,
            "source-layer": layer.dataset_table_name,
            "metadata": {
                "geolens": {
                    "companion": "outline",
                    "parent_layer_id": str(layer.id),
                }
            },
            "layout": _companion_visibility(layer, hidden=stroke_disabled),
            "paint": {
                "line-color": outline_color,
                "line-width": outline_width,
                "line-opacity": layer.opacity,
            },
        }
    ]
    if layer.filter:
        companions[0]["filter"] = layer.filter

    height_column = builder.get("heightColumn") or paint.get("_height_column")
    if isinstance(height_column, str) and height_column:
        fill_color = paint.get("fill-color", DEFAULT_FILL_COLOR)
        height_scale = _finite_number(builder.get("heightScale")) or 1
        extrusion_min_zoom = _finite_number(builder.get("extrusionMinZoom")) or 14
        configured_opacity = _finite_number(builder.get("extrusionOpacity"))
        extrusion_opacity = (
            min(layer.opacity, 0.85)
            if configured_opacity is None
            else _clamp_number(configured_opacity, 0, 1)
        )
        extrusion_layer: dict[str, Any] = {
            "id": f"{layer_id}-extrusion",
            "type": "fill-extrusion",
            "source": source_id,
            "source-layer": layer.dataset_table_name,
            "metadata": {
                "geolens": {
                    "companion": "extrusion",
                    "parent_layer_id": str(layer.id),
                }
            },
            "layout": _companion_visibility(layer),
            "minzoom": extrusion_min_zoom,
            "paint": {
                "fill-extrusion-height": _extrusion_height_expression(
                    height_column,
                    height_scale,
                ),
                "fill-extrusion-base": 0,
                "fill-extrusion-color": fill_color,
                "fill-extrusion-opacity": extrusion_opacity,
                "fill-extrusion-vertical-gradient": True,
            },
        }
        if layer.filter:
            extrusion_layer["filter"] = layer.filter
        companions.append(extrusion_layer)
    return companions


def _line_arrow_companion_layer(
    layer: MapLayerResponse,
    source_id: str,
    layer_id: str,
    style_config: dict,
    paint: dict,
) -> dict[str, Any] | None:
    if style_config.get("render_mode") != "arrow":
        return None
    builder = _builder_style_config(style_config)
    line_color = paint.get("line-color", DEFAULT_STROKE_COLOR)
    arrow_color = builder.get("arrowColor") or line_color
    arrow_size = _finite_number(builder.get("arrowSize")) or 14
    arrow_spacing = _finite_number(builder.get("arrowSpacing")) or 80
    arrow_layer: dict[str, Any] = {
        "id": f"{layer_id}-arrow",
        "type": "symbol",
        "source": source_id,
        "source-layer": layer.dataset_table_name,
        "metadata": {
            "geolens": {
                "companion": "arrow",
                "parent_layer_id": str(layer.id),
            }
        },
        "layout": {
            "symbol-placement": "line",
            "symbol-spacing": arrow_spacing,
            "icon-image": _sprite_icon_id(DEFAULT_ARROW_ICON),
            "icon-size": arrow_size / DEFAULT_ARROW_BASE_SIZE,
            "icon-allow-overlap": True,
            "icon-ignore-placement": True,
            "icon-rotation-alignment": "map",
            **_companion_visibility(layer),
        },
        "paint": {
            "icon-color": arrow_color,
            "icon-opacity": layer.opacity,
        },
    }
    if layer.filter:
        arrow_layer["filter"] = layer.filter
    return arrow_layer


def _style_layer_for_map_layer(
    layer: MapLayerResponse,
    source_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    style_config = layer.style_config or {}
    layer_type = _geometry_layer_type(
        layer.dataset_geometry_type,
        style_config,
        is_dem=bool(layer.is_dem),
        layer_type=layer.layer_type,
    )
    layout = _clean_layout(layer.layout)
    paint = _clean_paint(layer.paint)
    # Determine source type to gate line-gradient paint (mirrors _source_for_layer branches).
    if (layer.is_dem is True) and (
        (layer.style_config or {}).get("render_mode") == "hillshade"
    ):
        source_type = "raster-dem"
    elif layer.layer_type == "raster_geolens" or layer.dataset_record_type in {
        "raster_dataset",
        "vrt_dataset",
    }:
        source_type = "raster"
    else:
        source_type = "vector"
    paint = _drop_unsupported_line_gradient(layer, paint, source_type)
    if layer_type == "hillshade":
        paint = {
            key: value for key, value in paint.items() if key in _HILLSHADE_PAINT_KEYS
        }
    layer_id = f"layer-{_safe_id(str(layer.id))}"
    base: dict[str, Any] = {
        "id": layer_id,
        "type": layer_type,
        "source": source_id,
        "metadata": _layer_metadata(layer),
        "layout": layout,
        "paint": paint,
    }
    if layer.layer_type != "raster_geolens" and layer_type not in {
        "raster",
        "hillshade",
    }:
        base["source-layer"] = layer.dataset_table_name
    if layer.filter:
        base["filter"] = layer.filter
    if not layer.visible:
        base["layout"] = {**layout, "visibility": "none"}

    companion_layers: list[dict[str, Any]] = []
    label_config = layer.label_config or {}
    if layer_type == "fill":
        builder = _builder_style_config(style_config)
        if builder.get("strokeDisabled") or (layer.paint or {}).get("_stroke-disabled"):
            base["paint"] = {**base["paint"], "fill-outline-color": "rgba(0,0,0,0)"}
        companion_layers.extend(_fill_companion_layers(layer, source_id, layer_id))
    elif layer_type == "line":
        arrow_layer = _line_arrow_companion_layer(
            layer,
            source_id,
            layer_id,
            style_config,
            paint,
        )
        if arrow_layer:
            companion_layers.append(arrow_layer)

    if layer_type == "symbol":
        base["layout"] = _symbol_layout_from_style(
            base["layout"], style_config, label_config
        )
        base["paint"] = {
            **paint,
            **(_label_paint(label_config) if label_config else {}),
        }
    elif label_config.get("column") and layer_type not in {
        "heatmap",
        "raster",
        "hillshade",
    }:
        label_metadata = _clean_label_metadata(label_config)
        label_layer = {
            "id": f"{layer_id}-label",
            "type": "symbol",
            "source": source_id,
            "source-layer": layer.dataset_table_name,
            "metadata": {
                "geolens": {
                    "companion": "label",
                    "parent_layer_id": str(layer.id),
                    "label_config": label_metadata,
                }
            },
            "layout": _label_layout(label_config),
            "paint": _label_paint(label_config),
        }
        if layer.filter:
            label_layer["filter"] = layer.filter
        companion_layers.append(label_layer)

    return base, companion_layers


def build_maplibre_style(
    map_obj: Map, layers: list[MapLayerResponse]
) -> dict[str, Any]:
    """Build a complete MapLibre style document from saved map data."""

    sources: dict[str, Any] = {}
    style_layers: list[dict[str, Any]] = []
    for layer in sorted(layers, key=lambda item: item.sort_order):
        source_id = f"geolens-{_safe_id(str(layer.dataset_id))}"
        if source_id not in sources:
            sources[source_id] = _source_for_layer(layer)
        else:
            _append_cluster_source_metadata(sources[source_id], layer)
        base_layer, companions = _style_layer_for_map_layer(layer, source_id)
        style_layers.append(base_layer)
        style_layers.extend(companions)

    # Set lineMetrics: true on vector sources whose layers need line-gradient rendering.
    # Per D-01 detection rule, "needs" means paint['line-gradient'] OR builder.lineGradient.
    # Track originating layer for each gradient-needing source so we can emit a precise
    # warning when the backing source type is incompatible.
    gradient_layer_by_source: dict[str, MapLayerResponse] = {}
    for layer in layers:
        if _layer_uses_line_gradient(layer):
            source_id = f"geolens-{_safe_id(str(layer.dataset_id))}"
            # First-wins: the paint-drop path (`_drop_unsupported_line_gradient`) has already
            # warned on layers with paint set. Pick any layer here; we only need ONE for the
            # warning identity. Skip if a layer has already been recorded for this source.
            gradient_layer_by_source.setdefault(source_id, layer)
    for source_id, originating_layer in gradient_layer_by_source.items():
        src = sources.get(source_id)
        if src is None:
            continue
        src_type = src.get("type")
        if src_type in _LINE_GRADIENT_SOURCE_TYPES:
            src["lineMetrics"] = True
        else:
            # WR-03: builder-intent on incompatible source emits no warning otherwise. The
            # paint-drop path warns when paint['line-gradient'] is present, but a builder-
            # intent-only mismatch (e.g. raster layer with style_config.builder.lineGradient)
            # would silently fail without this. Symmetric to _drop_unsupported_line_gradient.
            logger.warning(
                "Skipping lineMetrics on source %s: type %r cannot support line-gradient "
                "(originating layer %s)",
                source_id,
                src_type,
                originating_layer.id,
            )

    terrain_block: dict[str, Any] | None = None
    tc = map_obj.terrain_config if isinstance(map_obj.terrain_config, dict) else None
    if tc and tc.get("enabled") and tc.get("source_dataset_id"):
        terrain_source_id = f"geolens-{_safe_id(str(tc['source_dataset_id']))}"
        if terrain_source_id in sources:
            try:
                exaggeration = float(tc.get("exaggeration", 1.0))
            except (TypeError, ValueError):
                exaggeration = 1.0
            terrain_block = {"source": terrain_source_id, "exaggeration": exaggeration}

    style: dict[str, Any] = {
        "version": STYLE_VERSION,
        "name": map_obj.name,
        "metadata": {
            "geolens": {
                "map_id": str(map_obj.id),
                "description": map_obj.description,
                "basemap_style": map_obj.basemap_style,
                "show_basemap_labels": map_obj.show_basemap_labels,
                "basemap_config": _clean_basemap_config(
                    getattr(map_obj, "basemap_config", None)
                ),
                "terrain_config": map_obj.terrain_config,
            }
        },
        "sprite": [{"id": GEOLENS_SPRITE_ID, "url": SPRITE_URL}],
        "glyphs": GLYPHS_URL,
        "sources": sources,
        "layers": style_layers,
    }
    if map_obj.center_lng is not None and map_obj.center_lat is not None:
        style["center"] = [map_obj.center_lng, map_obj.center_lat]
    if map_obj.zoom is not None:
        style["zoom"] = map_obj.zoom
    style["bearing"] = map_obj.bearing or 0
    style["pitch"] = map_obj.pitch or 0
    if terrain_block:
        style["terrain"] = terrain_block
    return style


def _source_dataset_id(source: dict[str, Any]) -> uuid.UUID | None:
    metadata = source.get("metadata")
    geolens = metadata.get("geolens") if isinstance(metadata, dict) else None
    raw = geolens.get("dataset_id") if isinstance(geolens, dict) else None
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _metadata_dict(layer: dict[str, Any]) -> dict[str, Any]:
    metadata = layer.get("metadata")
    geolens = metadata.get("geolens") if isinstance(metadata, dict) else None
    return geolens if isinstance(geolens, dict) else {}


def _style_config_from_import(style_layer: dict[str, Any]) -> dict[str, Any] | None:
    geolens = _metadata_dict(style_layer)
    style_config = geolens.get("style_config")
    if isinstance(style_config, dict):
        clean_style_config = _clean_style_metadata(style_config)
        if clean_style_config:
            return clean_style_config
    if style_layer.get("type") == "symbol":
        layout = (
            style_layer.get("layout")
            if isinstance(style_layer.get("layout"), dict)
            else {}
        )
        symbol: dict[str, Any] = {
            "iconImage": _stored_icon_id(layout.get("icon-image")),
            "iconSize": layout.get("icon-size"),
            "iconRotation": layout.get("icon-rotate"),
            "iconAnchor": layout.get("icon-anchor"),
            "iconOffset": layout.get("icon-offset"),
        }
        symbol = {key: value for key, value in symbol.items() if value is not None}
        return (
            {"render_mode": "symbol", "symbol": symbol}
            if symbol
            else {"render_mode": "symbol"}
        )
    if style_layer.get("type") == "heatmap":
        return {"render_mode": "heatmap"}
    return None


def _label_config_from_import(style_layer: dict[str, Any]) -> dict[str, Any] | None:
    geolens = _metadata_dict(style_layer)
    label_config = geolens.get("label_config")
    if isinstance(label_config, dict):
        clean_label_config = _clean_label_metadata(label_config)
        if clean_label_config:
            return clean_label_config
    layout = (
        style_layer.get("layout") if isinstance(style_layer.get("layout"), dict) else {}
    )
    text_field = layout.get("text-field")
    if isinstance(text_field, list) and len(text_field) == 2 and text_field[0] == "get":
        return {"column": text_field[1]}
    return None


def _builder_from_outline_companion(
    companion: dict[str, Any], builder: dict[str, Any]
) -> None:
    paint = companion.get("paint") if isinstance(companion.get("paint"), dict) else {}
    layout = (
        companion.get("layout") if isinstance(companion.get("layout"), dict) else {}
    )
    line_color = paint.get("line-color")
    if isinstance(line_color, str) and "outlineColor" not in builder:
        builder["outlineColor"] = line_color
    line_width = paint.get("line-width")
    if isinstance(line_width, (int, float)) and "outlineWidth" not in builder:
        builder["outlineWidth"] = line_width
    if layout.get("visibility") == "none" and "strokeDisabled" not in builder:
        builder["strokeDisabled"] = True


def _builder_from_extrusion_companion(
    companion: dict[str, Any], builder: dict[str, Any]
) -> None:
    paint = companion.get("paint") if isinstance(companion.get("paint"), dict) else {}
    column, height_scale = _extrusion_column_from_expression(
        paint.get("fill-extrusion-height")
    )
    if column and "heightColumn" not in builder:
        builder["heightColumn"] = column
    if height_scale is not None and "heightScale" not in builder:
        builder["heightScale"] = height_scale
    minzoom = _finite_number(companion.get("minzoom"))
    if minzoom is not None and "extrusionMinZoom" not in builder:
        builder["extrusionMinZoom"] = minzoom
    opacity = _finite_number(paint.get("fill-extrusion-opacity"))
    if opacity is not None and "extrusionOpacity" not in builder:
        builder["extrusionOpacity"] = opacity


def _builder_from_arrow_companion(
    companion: dict[str, Any], builder: dict[str, Any]
) -> None:
    layout = (
        companion.get("layout") if isinstance(companion.get("layout"), dict) else {}
    )
    paint = companion.get("paint") if isinstance(companion.get("paint"), dict) else {}
    arrow_color = paint.get("icon-color") or paint.get("text-color")
    if isinstance(arrow_color, str) and "arrowColor" not in builder:
        builder["arrowColor"] = arrow_color
    icon_size = _finite_number(layout.get("icon-size"))
    arrow_size = (
        icon_size * DEFAULT_ARROW_BASE_SIZE
        if icon_size is not None
        else _finite_number(layout.get("text-size"))
    )
    if arrow_size is not None and "arrowSize" not in builder:
        builder["arrowSize"] = arrow_size
    arrow_spacing = _finite_number(layout.get("symbol-spacing"))
    if arrow_spacing is not None and "arrowSpacing" not in builder:
        builder["arrowSpacing"] = arrow_spacing


def parse_maplibre_style_import(style: dict[str, Any]) -> ImportedStyleMap:
    """Normalize a MapLibre style document into GeoLens map/layer inputs."""

    if style.get("version") != STYLE_VERSION:
        raise ValueError("Only MapLibre style version 8 documents are supported")
    raw_sources = style.get("sources")
    raw_layers = style.get("layers")
    if not isinstance(raw_sources, dict) or not isinstance(raw_layers, list):
        raise ValueError("Style JSON must include sources and layers")

    summary = MapStyleImportSummary()
    matched_sources: dict[str, uuid.UUID] = {}
    for source_id, source in raw_sources.items():
        if not isinstance(source, dict):
            continue
        dataset_id = _source_dataset_id(source)
        if dataset_id is None:
            summary.sources_unsupported += 1
            summary.warnings.append(
                MapStyleImportWarning(
                    code="unsupported_source",
                    message="Source has no GeoLens dataset metadata and was not imported.",
                    source_id=str(source_id),
                )
            )
            continue
        matched_sources[str(source_id)] = dataset_id
        summary.sources_matched += 1

    imported_layers: list[MapLayerInput] = []
    companion_labels: dict[str, dict[str, Any]] = {}
    companion_outlines: dict[str, dict[str, Any]] = {}
    companion_extrusions: dict[str, dict[str, Any]] = {}
    companion_arrows: dict[str, dict[str, Any]] = {}
    primary_layers: list[dict[str, Any]] = []
    for style_layer in raw_layers:
        if not isinstance(style_layer, dict):
            continue
        geolens = _metadata_dict(style_layer)
        companion = geolens.get("companion")
        parent_layer_id = geolens.get("parent_layer_id")
        if companion and parent_layer_id:
            key = str(parent_layer_id)
            if companion == "label":
                companion_labels[key] = style_layer
            elif companion == "outline":
                companion_outlines[key] = style_layer
            elif companion == "extrusion":
                companion_extrusions[key] = style_layer
            elif companion == "arrow":
                companion_arrows[key] = style_layer
            continue
        primary_layers.append(style_layer)

    for index, style_layer in enumerate(primary_layers):
        source_id = style_layer.get("source")
        dataset_id = matched_sources.get(str(source_id))
        if dataset_id is None:
            summary.layers_skipped += 1
            summary.warnings.append(
                MapStyleImportWarning(
                    code="skipped_layer",
                    message="Layer source could not be matched to a GeoLens dataset.",
                    source_id=str(source_id) if source_id is not None else None,
                    layer_id=str(style_layer.get("id"))
                    if style_layer.get("id")
                    else None,
                )
            )
            continue

        geolens = _metadata_dict(style_layer)
        label_config = _label_config_from_import(style_layer)
        parent_id = geolens.get("layer_id")
        companion = companion_labels.get(str(parent_id)) if parent_id else None
        if companion and label_config is None:
            label_config = _label_config_from_import(companion)
        style_config = _style_config_from_import(style_layer)
        outline_companion = (
            companion_outlines.get(str(parent_id)) if parent_id else None
        )
        extrusion_companion = (
            companion_extrusions.get(str(parent_id)) if parent_id else None
        )
        arrow_companion = companion_arrows.get(str(parent_id)) if parent_id else None
        if outline_companion or extrusion_companion or arrow_companion:
            style_config = dict(style_config) if isinstance(style_config, dict) else {}
            builder = (
                dict(style_config.get("builder"))
                if isinstance(style_config.get("builder"), dict)
                else {}
            )
            if outline_companion:
                _builder_from_outline_companion(outline_companion, builder)
            if extrusion_companion:
                _builder_from_extrusion_companion(extrusion_companion, builder)
            if arrow_companion:
                style_config["render_mode"] = "arrow"
                _builder_from_arrow_companion(arrow_companion, builder)
            if builder:
                style_config["builder"] = builder
            if not style_config:
                style_config = None
        layer_input = MapLayerInput(
            dataset_id=dataset_id,
            sort_order=int(geolens.get("sort_order", index)),
            visible=((style_layer.get("layout") or {}).get("visibility") != "none")
            if isinstance(style_layer.get("layout"), dict)
            else True,
            opacity=float(geolens.get("opacity", 1) or 1),
            paint=_clean_paint(
                style_layer.get("paint")
                if isinstance(style_layer.get("paint"), dict)
                else {}
            ),
            layout=_clean_layout(
                style_layer.get("layout")
                if isinstance(style_layer.get("layout"), dict)
                else {}
            ),
            display_name=geolens.get("display_name") or style_layer.get("id"),
            filter=style_layer.get("filter")
            if isinstance(style_layer.get("filter"), list)
            else None,
            label_config=label_config,
            style_config=style_config,
            layer_type=geolens.get("layer_type")
            if geolens.get("layer_type")
            in {"vector_geolens", "raster_geolens", "geojson"}
            else None,
            show_in_legend=bool(geolens.get("show_in_legend", True)),
        )
        imported_layers.append(layer_input)
        summary.layers_imported += 1

    terrain_config: dict[str, Any] | None = None
    raw_terrain = style.get("terrain")
    if isinstance(raw_terrain, dict):
        terrain_source = raw_terrain.get("source")
        dataset_id = (
            matched_sources.get(str(terrain_source)) if terrain_source else None
        )
        if dataset_id is not None:
            try:
                exaggeration = float(raw_terrain.get("exaggeration", 1.0))
            except (TypeError, ValueError):
                exaggeration = 1.0
            terrain_config = {
                "enabled": True,
                "source_dataset_id": str(dataset_id),
                "exaggeration": exaggeration,
            }

    center = style.get("center")
    metadata = style.get("metadata") if isinstance(style.get("metadata"), dict) else {}
    geolens_meta = (
        metadata.get("geolens") if isinstance(metadata.get("geolens"), dict) else {}
    )
    if terrain_config is None:
        meta_terrain = geolens_meta.get("terrain_config")
        if (
            isinstance(meta_terrain, dict)
            and meta_terrain.get("enabled")
            and meta_terrain.get("source_dataset_id")
        ):
            try:
                exaggeration = float(meta_terrain.get("exaggeration", 1.0))
            except (TypeError, ValueError):
                exaggeration = 1.0
            terrain_config = {
                "enabled": True,
                "source_dataset_id": str(meta_terrain["source_dataset_id"]),
                "exaggeration": exaggeration,
            }
    basemap_config = _clean_basemap_config(geolens_meta.get("basemap_config"))
    return ImportedStyleMap(
        name=str(style.get("name") or "Imported style"),
        description=geolens_meta.get("description"),
        center_lng=center[0] if isinstance(center, list) and len(center) >= 2 else None,
        center_lat=center[1] if isinstance(center, list) and len(center) >= 2 else None,
        zoom=style.get("zoom") if isinstance(style.get("zoom"), (int, float)) else None,
        bearing=style.get("bearing")
        if isinstance(style.get("bearing"), (int, float))
        else None,
        pitch=style.get("pitch")
        if isinstance(style.get("pitch"), (int, float))
        else None,
        basemap_style=geolens_meta.get("basemap_style"),
        layers=imported_layers,
        summary=summary,
        terrain_config=terrain_config,
        basemap_config=basemap_config,
    )
