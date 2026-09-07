"""MapLibre style import parsing for saved maps."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.modules.catalog.maps.schemas import (
    _MAX_LAYERS_PER_MAP,
    MapLayerInput,
    MapStyleImportSummary,
    MapStyleImportWarning,
    PopupConfig,
    TerrainConfig,
)
from app.modules.catalog.maps.style_sanitizers import (
    clamp_number,
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
# fix(#1626): master `layer.opacity` folds into a per-feature paint key on
# export, for the two types maplibre-gl v6 gave a `-layer-opacity` to (see
# `_fold_master_opacity` in style_json).
FOLDED_OPACITY_KEYS: dict[str, str] = {"fill": "fill-opacity", "line": "line-opacity"}
# fix(#1631): per-feature opacity the builder renders when stored
# paint carries none. Must mirror OPACITY_DEFAULTS in shared.ts, or the
# export fold starts from spec default 1, rendering brighter than the app.
BUILDER_FEATURE_OPACITY_DEFAULTS: dict[str, float] = {"fill": 0.3, "line": 1.0}
# fix(#1778): zoom range the builder substitutes when a layout
# has none, mirroring map-sync.ts. Also imported by style_json for
# export, so both directions of the round trip stay in step.
BUILDER_MIN_ZOOM = 0
BUILDER_MAX_ZOOM = 22


class MapStyleImportLayerLimitError(ValueError):
    """A style document that resolves to more layers than one map may hold.

    fix(#1778): a ValueError subclass so the existing broad
    ``except ValueError`` keeps working, but a distinct type so the import
    route can answer 422 for it (matching the sibling layer-carrying
    schemas) instead of the generic 400 for a malformed document.
    """


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


def _restore_master_opacity(
    style_layer: dict[str, Any],
    geolens: dict[str, Any],
    paint: dict[str, Any],
    summary: MapStyleImportSummary,
) -> float:
    """Recover ``layer.opacity`` for an imported primary layer, un-folding ``paint``.

    fix(#1626): export folds master opacity into ``*-opacity`` (v6's
    ``*-layer-opacity`` aborts style load on maplibre-gl < 6), keeping the
    un-folded value in ``metadata.geolens.feature_opacity`` to undo on import.

    fix(#1625): a v6-authored style may carry ``*-layer-opacity`` instead —
    a number maps onto the master column; an expression is dropped with a warning.
    """
    # fix(#1778): `float(x or 1)` turned a legitimate 0.0 into 1.0, so a
    # fully-transparent layer came back fully opaque; read the master the
    # same explicit way the per-feature reads below do.
    master = finite_number(geolens.get("opacity", 1))
    opacity = 1.0 if master is None else master
    layer_type = style_layer.get("type")
    feature_key = FOLDED_OPACITY_KEYS.get(str(layer_type))
    if feature_key is None:
        return opacity
    if "feature_opacity" in geolens:
        feature_opacity = geolens["feature_opacity"]
        if feature_opacity is None:
            paint.pop(feature_key, None)
        else:
            paint[feature_key] = feature_opacity
    layer_opacity = paint.pop(f"{layer_type}-layer-opacity", None)
    if layer_opacity is not None:
        number = finite_number(layer_opacity)
        if number is None:
            summary.add_warning(
                MapStyleImportWarning(
                    code="unsupported_layer_opacity",
                    message=(
                        f"{layer_type}-layer-opacity must be a number to become "
                        "the layer opacity; an expression was dropped."
                    ),
                    layer_id=str(style_layer.get("id"))
                    if style_layer.get("id")
                    else None,
                )
            )
        else:
            opacity *= number
    return clamp_number(opacity, 0.0, 1.0)


def _zoom_text(value: float) -> str:
    """Render a zoom for a warning without a trailing ``.0`` on whole numbers."""
    return str(int(value)) if value.is_integer() else str(value)


def _restore_zoom_range(
    style_layer: dict[str, Any],
    layout: dict[str, Any],
    summary: MapStyleImportSummary,
) -> None:
    """Put a primary layer's spec ``minzoom``/``maxzoom`` back into the layout.

    fix(#1778): the builder stores zoom range as private layout keys;
    export promotes them to spec-level (fix #526 B-044, since
    ``clean_layout`` strips underscore keys). Import must mirror that or
    a zoom-limited map silently draws at all zooms on re-import.

    fix(#1778): a restored minimum at or above the effective
    maximum is clamped with a warning — MapLibre's visible band is
    ``[minzoom, maxzoom)``, and the builder can't render past
    ``BUILDER_MAX_ZOOM`` to honor a minimum written past it.

    Writes ``raw``, not the parsed number, so an integer zoom stays an integer
    in JSONB. The predicates exclude the builder defaults: export omits them as
    no-ops, so reading them back would write keys the builder treats as unset.
    """
    for spec_key, layout_key, is_meaningful in (
        ("minzoom", "_minzoom", lambda z: BUILDER_MIN_ZOOM < z <= 24),
        ("maxzoom", "_maxzoom", lambda z: BUILDER_MIN_ZOOM <= z < BUILDER_MAX_ZOOM),
    ):
        raw = style_layer.get(spec_key)
        number = finite_number(raw)
        if number is not None and is_meaningful(number):
            layout[layout_key] = raw

    minimum = finite_number(layout.get("_minzoom"))
    if minimum is None:
        return
    effective_max = finite_number(layout.get("_maxzoom"))
    if effective_max is None:
        effective_max = float(BUILDER_MAX_ZOOM)
    if minimum < effective_max:
        return

    clamped = int(max(BUILDER_MIN_ZOOM, effective_max - 1))
    if clamped > BUILDER_MIN_ZOOM:
        layout["_minzoom"] = clamped
    else:
        layout.pop("_minzoom", None)
    summary.add_warning(
        MapStyleImportWarning(
            code="clamped_zoom_range",
            message=(
                f"Layer minzoom {_zoom_text(minimum)} is not below the "
                f"maximum zoom the map builder renders "
                f"({_zoom_text(effective_max)}), which would hide the layer "
                f"at every zoom; the minimum was lowered to {clamped}."
            ),
            layer_id=str(style_layer.get("id")) if style_layer.get("id") else None,
        )
    )


def _popup_config_from_import(geolens: dict[str, Any]) -> dict[str, Any] | None:
    """Recover ``popup_config`` from the layer's GeoLens metadata.

    fix(#1778): export half is new too, so nothing needs compatibility
    tolerance beyond a hand-edited document. A malformed value is dropped
    rather than raised — a ValidationError would 400 the whole import, and
    losing one layer's popup settings isn't worth refusing it.
    """
    raw = geolens.get("popup_config")
    if not isinstance(raw, dict):
        return None
    try:
        return PopupConfig.model_validate(raw).model_dump(mode="json")
    except ValidationError:
        return None


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
            summary.add_warning(
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
            summary.add_warning(
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
        paint = clean_paint(
            style_layer.get("paint")
            if isinstance(style_layer.get("paint"), dict)
            else {}
        )
        opacity = _restore_master_opacity(style_layer, geolens, paint, summary)
        layout = clean_layout(
            style_layer.get("layout")
            if isinstance(style_layer.get("layout"), dict)
            else {}
        )
        _restore_zoom_range(style_layer, layout, summary)
        imported_layers.append(
            MapLayerInput(
                dataset_id=dataset_id,
                sort_order=int(geolens.get("sort_order", index)),
                visible=((style_layer.get("layout") or {}).get("visibility") != "none")
                if isinstance(style_layer.get("layout"), dict)
                else True,
                opacity=opacity,
                paint=paint,
                layout=layout,
                popup_config=_popup_config_from_import(geolens),
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

    # fix(#1778): count belongs to logical layers, not the raw
    # `layers` array — an export emits companions per primary, so import
    # and save must refuse at the same number apply_layer_diff compares.
    if len(imported_layers) > _MAX_LAYERS_PER_MAP:
        raise MapStyleImportLayerLimitError(
            f"Style imports at most {_MAX_LAYERS_PER_MAP} layers per map; "
            f"this document resolves to {len(imported_layers)}"
        )

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
