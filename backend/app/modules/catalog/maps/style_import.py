"""MapLibre style import parsing for saved maps."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.modules.catalog.maps.schemas import (
    MapLayerInput,
    MapStyleImportSummary,
    MapStyleImportWarning,
    TerrainConfig,
)
from app.modules.catalog.maps.style_sanitizers import (
    clean_basemap_config,
    clean_label_metadata,
    clean_layout,
    clean_paint,
    clean_style_metadata,
    finite_number,
)

STYLE_VERSION = 8
GEOLENS_SPRITE_ID = "geolens"
DEFAULT_ARROW_BASE_SIZE = 14


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
    light: dict | None = None
    transition: dict | None = None


def _validated_terrain_config(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Return the normal-write persistence shape for active terrain metadata."""
    try:
        terrain = TerrainConfig.model_validate(raw)
    except ValidationError:
        return None
    if not terrain.enabled or terrain.source_dataset_id is None:
        return None
    return terrain.model_dump(mode="json")


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


def _style_config_from_import(style_layer: dict[str, Any]) -> dict[str, Any] | None:
    geolens = _metadata_dict(style_layer)
    style_config = geolens.get("style_config")
    if isinstance(style_config, dict):
        clean_style_config = clean_style_metadata(style_config)
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
        clean_label_config = clean_label_metadata(label_config)
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
    companion: dict[str, Any],
    _style_config: dict[str, Any],
    builder: dict[str, Any],
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


def _builder_from_extrusion_companion(
    companion: dict[str, Any],
    _style_config: dict[str, Any],
    builder: dict[str, Any],
) -> None:
    paint = companion.get("paint") if isinstance(companion.get("paint"), dict) else {}
    column, height_scale = _extrusion_column_from_expression(
        paint.get("fill-extrusion-height")
    )
    if column and "heightColumn" not in builder:
        builder["heightColumn"] = column
    if height_scale is not None and "heightScale" not in builder:
        builder["heightScale"] = height_scale
    minzoom = finite_number(companion.get("minzoom"))
    if minzoom is not None and "extrusionMinZoom" not in builder:
        builder["extrusionMinZoom"] = minzoom
    opacity = finite_number(paint.get("fill-extrusion-opacity"))
    if opacity is not None and "extrusionOpacity" not in builder:
        builder["extrusionOpacity"] = opacity


def _builder_from_arrow_companion(
    companion: dict[str, Any],
    style_config: dict[str, Any],
    builder: dict[str, Any],
) -> None:
    style_config["render_mode"] = "arrow"
    layout = (
        companion.get("layout") if isinstance(companion.get("layout"), dict) else {}
    )
    paint = companion.get("paint") if isinstance(companion.get("paint"), dict) else {}
    arrow_color = paint.get("icon-color") or paint.get("text-color")
    if isinstance(arrow_color, str) and "arrowColor" not in builder:
        builder["arrowColor"] = arrow_color
    icon_size = finite_number(layout.get("icon-size"))
    arrow_size = (
        icon_size * DEFAULT_ARROW_BASE_SIZE
        if icon_size is not None
        else finite_number(layout.get("text-size"))
    )
    if arrow_size is not None and "arrowSize" not in builder:
        builder["arrowSize"] = arrow_size
    arrow_spacing = finite_number(layout.get("symbol-spacing"))
    if arrow_spacing is not None and "arrowSpacing" not in builder:
        builder["arrowSpacing"] = arrow_spacing


def _builder_from_color_relief_companion(
    companion: dict[str, Any],
    _style_config: dict[str, Any],
    builder: dict[str, Any],
) -> None:
    if "hypso_enabled" not in builder and "hypsoEnabled" not in builder:
        builder["hypso_enabled"] = True
    geolens = _metadata_dict(companion)
    ramp = geolens.get("ramp")
    if (
        isinstance(ramp, str)
        and ramp
        and "hypso_ramp" not in builder
        and "hypsoRamp" not in builder
    ):
        builder["hypso_ramp"] = ramp


_BUILDER_COMPANION_PARSERS = {
    "outline": _builder_from_outline_companion,
    "extrusion": _builder_from_extrusion_companion,
    "arrow": _builder_from_arrow_companion,
    "color-relief": _builder_from_color_relief_companion,
}


def parse_maplibre_style_import(  # noqa: C901 - coordinates independent parsers
    style: dict[str, Any],
) -> ImportedStyleMap:
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
    companions_by_parent: dict[str, dict[str, dict[str, Any]]] = {}
    primary_layers: list[dict[str, Any]] = []
    for style_layer in raw_layers:
        if not isinstance(style_layer, dict):
            continue
        geolens = _metadata_dict(style_layer)
        companion = geolens.get("companion")
        parent_layer_id = geolens.get("parent_layer_id")
        if companion and parent_layer_id:
            companions_by_parent.setdefault(str(parent_layer_id), {})[
                str(companion)
            ] = style_layer
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
        layer_companions = (
            companions_by_parent.get(str(parent_id), {}) if parent_id else {}
        )
        label_companion = layer_companions.get("label")
        if label_companion and label_config is None:
            label_config = _label_config_from_import(label_companion)
        style_config = _style_config_from_import(style_layer)
        builder_companions = {
            name: companion
            for name, companion in layer_companions.items()
            if name in _BUILDER_COMPANION_PARSERS
        }
        if builder_companions:
            style_config = dict(style_config) if isinstance(style_config, dict) else {}
            builder = (
                dict(style_config.get("builder"))
                if isinstance(style_config.get("builder"), dict)
                else {}
            )
            for name, parse in _BUILDER_COMPANION_PARSERS.items():
                companion = builder_companions.get(name)
                if companion is not None:
                    parse(companion, style_config, builder)
            if builder:
                style_config["builder"] = builder
            if not style_config:
                style_config = None
        imported_layers.append(
            MapLayerInput(
                dataset_id=dataset_id,
                sort_order=int(geolens.get("sort_order", index)),
                visible=((style_layer.get("layout") or {}).get("visibility") != "none")
                if isinstance(style_layer.get("layout"), dict)
                else True,
                opacity=float(geolens.get("opacity", 1) or 1),
                paint=clean_paint(
                    style_layer.get("paint")
                    if isinstance(style_layer.get("paint"), dict)
                    else {}
                ),
                layout=clean_layout(
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
        )
        summary.layers_imported += 1

    terrain_config: dict[str, Any] | None = None
    raw_terrain = style.get("terrain")
    if isinstance(raw_terrain, dict):
        terrain_source = raw_terrain.get("source")
        dataset_id = (
            matched_sources.get(str(terrain_source)) if terrain_source else None
        )
        if dataset_id is not None:
            terrain_config = _validated_terrain_config(
                {
                    "enabled": True,
                    "source_dataset_id": dataset_id,
                    "exaggeration": raw_terrain.get("exaggeration", 1.0),
                }
            )

    center = style.get("center")
    metadata = style.get("metadata") if isinstance(style.get("metadata"), dict) else {}
    geolens_meta = (
        metadata.get("geolens") if isinstance(metadata.get("geolens"), dict) else {}
    )
    if terrain_config is None:
        meta_terrain = geolens_meta.get("terrain_config")
        if isinstance(meta_terrain, dict):
            terrain_config = _validated_terrain_config(meta_terrain)
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
        basemap_config=clean_basemap_config(geolens_meta.get("basemap_config")),
        light=style.get("light") if isinstance(style.get("light"), dict) else None,
        transition=style.get("transition")
        if isinstance(style.get("transition"), dict)
        else None,
    )
