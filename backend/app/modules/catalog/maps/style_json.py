"""MapLibre style JSON import/export helpers for saved maps."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import (
    LEGACY_BUILDER_PAINT_KEYS,
    MapLayerInput,
    MapLayerResponse,
    MapStyleImportSummary,
    MapStyleImportWarning,
)
from app.processing.tiles.signing import generate_tile_signature, round_expiry

STYLE_VERSION = 8
GEOLENS_SPRITE_ID = "geolens"
SPRITE_URL = "/maps/sprites/geolens"
GLYPHS_URL = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf"
DEFAULT_FILL_COLOR = "#3b82f6"
DEFAULT_STROKE_COLOR = "#1d4ed8"

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
_SYMBOL_METADATA_KEYS = {
    "iconImage",
    "iconSize",
    "iconRotation",
    "iconAnchor",
    "iconOffset",
    "categoryColumn",
    "categories",
}


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


def _safe_id(value: str) -> str:
    safe = _SAFE_ID_RE.sub("-", value).strip("-")
    return safe or "layer"


def _clean_paint(paint: dict[str, Any] | None) -> dict[str, Any]:
    """Return MapLibre paint without known/private GeoLens builder keys."""

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
        cleaned[sub_key] = sub_value
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
    return dict(builder) if isinstance(builder, dict) else {}


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
    exp = round_expiry()
    params = urlencode(
        {
            "sig": generate_tile_signature(layer.dataset_table_name, exp),
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
            "minzoom": 14,
            "paint": {
                "fill-extrusion-height": [
                    "coalesce",
                    ["to-number", ["get", height_column], 0],
                    0,
                ],
                "fill-extrusion-base": 0,
                "fill-extrusion-color": fill_color,
                "fill-extrusion-opacity": min(layer.opacity, 0.85),
                "fill-extrusion-vertical-gradient": True,
            },
        }
        if layer.filter:
            extrusion_layer["filter"] = layer.filter
        companions.append(extrusion_layer)
    return companions


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
        sources.setdefault(source_id, _source_for_layer(layer))
        base_layer, companions = _style_layer_for_map_layer(layer, source_id)
        style_layers.append(base_layer)
        style_layers.extend(companions)

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
    primary_layers: list[dict[str, Any]] = []
    for style_layer in raw_layers:
        if not isinstance(style_layer, dict):
            continue
        geolens = _metadata_dict(style_layer)
        companion = geolens.get("companion")
        parent_layer_id = geolens.get("parent_layer_id")
        if companion and parent_layer_id:
            if companion == "label":
                companion_labels[str(parent_layer_id)] = style_layer
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
            style_config=_style_config_from_import(style_layer),
            layer_type=geolens.get("layer_type")
            if geolens.get("layer_type")
            in {"vector_geolens", "raster_geolens", "geojson"}
            else None,
            show_in_legend=bool(geolens.get("show_in_legend", True)),
        )
        imported_layers.append(layer_input)
        summary.layers_imported += 1

    center = style.get("center")
    metadata = style.get("metadata") if isinstance(style.get("metadata"), dict) else {}
    geolens_meta = (
        metadata.get("geolens") if isinstance(metadata.get("geolens"), dict) else {}
    )
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
    )
