"""MapLibre style JSON import/export helpers for saved maps."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from pydantic import ValidationError

from app.modules.catalog.maps.filter_grammar import (
    FilterValidationError,
    validate_filter,
)
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.schemas import (
    BUILDER_SNAKE_TO_CAMEL_KEYS,
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
# builder-audit #338 STYLE-07 / DRY-06: GeoLens default fill/stroke palette and the
# arrow/extrusion magic constants live here as named module constants and are
# re-exported so `service_shared.generate_default_style` imports the same values
# instead of hardcoding bare literals (which silently diverged on export vs
# storage). The frontend mirrors these in `renderAs.ts`/`fill-adapter.ts`.
DEFAULT_FILL_COLOR = "#3b82f6"
DEFAULT_STROKE_COLOR = "#1d4ed8"
DEFAULT_OUTLINE_WIDTH = 1
DEFAULT_ARROW_ICON = "arrow-right"
DEFAULT_ARROW_BASE_SIZE = 14
DEFAULT_ARROW_SPACING = 80
DEFAULT_EXTRUSION_MIN_ZOOM = 14
EXTRUSION_OPACITY_CAP = 0.85
# builder-audit #338 P1-06: backend color-relief companion defaults. Elevation range
# 0-4000 m (mirrors color-relief-sync.ts Assumption A1) with a 7-stop ramp; the
# emitted layer reuses the same ramp name the builder DEM editor authored.
COLOR_RELIEF_DEFAULT_RAMP = "Viridis"
COLOR_RELIEF_DEFAULT_OPACITY = 0.7
COLOR_RELIEF_ELEV_MIN = 0
COLOR_RELIEF_ELEV_MAX = 4000
COLOR_RELIEF_STOP_COUNT = 7
CLUSTER_GEOJSON_FEATURE_LIMIT = 5000
LABEL_FONT_STACK = [
    "Noto Sans Regular",
]

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
    # builder-audit #338 SPEC-03: round-trippable legend/ramp/render-mode UI state that
    # was previously dropped on the style-JSON export/import path (legend titles,
    # reversed-ramp flag, [min,max] size range, and saved heatmap/circle paint used
    # to restore a prior render mode). These already round-trip through the open
    # DB dict; they must also survive build -> parse via metadata.geolens.
    "legendLabel",
    "reversed",
    "sizeRange",
    "sizeLabel",
    "colorLabel",
    "heatmapPaint",
    "savedCirclePaint",
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
# builder-audit #338 STYLE-01: the snake_case->camelCase builder alias table used on
# export is NOT redefined here. It is imported from schemas as the single-source
# `BUILDER_SNAKE_TO_CAMEL_KEYS`, which is derived programmatically as the exact
# inverse of the authoritative `_BUILDER_CAMEL_TO_SNAKE_KEYS` storage map (and is
# therefore exhaustive — it includes the `folder_group_*` keys the old
# hand-written `_BUILDER_KEY_ALIASES` table was missing, which previously leaked
# snake_case into exported style.json metadata). Add a builder key in schemas ONCE
# and both directions stay in sync.
_BUILDER_KEY_ALIASES = BUILDER_SNAKE_TO_CAMEL_KEYS

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
    # builder-audit #338 SPEC-07: preserve GL root `light`/`transition` blocks across the
    # import path so a spec-conformant consumer's lighting/fade state is not silently
    # dropped. There is no dedicated Map column for these yet, so they are captured
    # here for callers/round-trip preservation rather than re-emitted from storage.
    light: dict | None = None
    transition: dict | None = None


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
        if not str(key).startswith("_") and key != "line-dasharray"
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


def _clean_basemap_config(
    value: Any, *, lenient: bool = False
) -> dict[str, Any] | None:
    """Validate stored basemap_config metadata.

    builder-audit #338 STYLE-04: the export/read path passes ``lenient=True`` so a
    stored basemap_config containing a key the running backend's ``BasemapConfig``
    no longer knows about (forward-compat write then rollback, or an out-of-band
    write) does NOT raise and 500 ``GET /maps/{id}/style.json``. In lenient mode
    unknown keys are dropped and a still-invalid config degrades to ``None``
    instead of hard-failing the whole style document. The import path keeps the
    strict behavior (it is already wrapped in try/except at the router boundary).
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        if lenient:
            return None
        raise ValueError("basemap_config must be an object")
    try:
        return BasemapConfig.model_validate(value).model_dump(mode="json")
    except ValidationError as exc:
        if not lenient:
            raise ValueError("Invalid basemap_config metadata") from exc
        # Drop unknown keys (forward/rollback schema skew) and retry once.
        known = {k: v for k, v in value.items() if k in BasemapConfig.model_fields}
        try:
            return BasemapConfig.model_validate(known).model_dump(mode="json")
        except ValidationError:
            logger.warning(
                "Dropping malformed stored basemap_config on style export "
                "(degrading to None rather than 500)"
            )
            return None


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
    """Annotate a cluster source with the resolved render strategy.

    builder-audit #338 STYLE-09 (documentation, the lower-risk option vs dropping):
    ``source.metadata.geolens.cluster_renderers`` is ADVISORY metadata with NO
    backend consumer — ``parse_maplibre_style_import`` does not read it back, and a
    grep across ``frontend/src`` finds no reader either. It is emitted purely so an
    external introspector of the exported style.json can see which cluster fallback
    strategy ('bounded-geojson' / 'server-tile' / 'fallback') was chosen per layer.
    It is intentionally retained (not load-bearing for round-trip); if a future
    cleanup confirms no consumer ever materializes, this whole block can be dropped
    to shrink the cluster path. Kept here, documented, to avoid silently changing
    the exported contract.

    fix(#394) ST-06 (documented limitation, the audit's "or document" option):
    cluster rendering does NOT round-trip through style.json export. The
    exported layer is a plain circle layer over the vector source — no
    ``cluster: true`` source flags and no cluster-circle/cluster-count
    companion layers are emitted, because GeoLens clustering is server-side
    (authenticated cluster tile URLs + per-layer radius/max-zoom the plain
    MapLibre style format cannot express). External consumers of an exported
    style see every point unclustered; this metadata block is the only
    cluster trace. Full fidelity would require emitting the cluster
    companions + a GeoJSON source per layer — revisit only if an external
    consumer materializes.
    """
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


def _mvt_source_layer(layer: MapLayerResponse) -> str:
    """Return the MVT ``source-layer`` name for a GeoLens vector layer.

    builder-audit #338 P1-01: the runtime client (``map-sync.ts``) names the vector
    tile layer ``data.<table>`` (matching the ``/tiles/data.<table>/...`` path the
    tile server signs and serves). Style export MUST emit the SAME name or the
    exported MapLibre style loads the source but renders no features because the
    layer name inside the MVT payload does not match the exported ``source-layer``.
    This is the single source of truth for that name; ``_tile_url_for_layer`` signs
    the raw ``dataset_table_name`` as the scope, and the served layer is the
    ``data.``-prefixed name — keep both in lockstep here.
    """
    return f"data.{layer.dataset_table_name}"


def _source_type_for_layer(layer: MapLayerResponse) -> str:
    """Return the MapLibre source ``type`` for a layer: raster-dem / raster / vector.

    builder-audit #338 STYLE-03: this is the SINGLE 3-way branch consumed by both
    ``_source_for_layer`` (which actually constructs the source dict) and the
    line-gradient gating in ``_style_layer_for_map_layer``. Keeping one helper
    prevents the two from silently desyncing when a new raster record_type is
    added (which previously could drop or keep ``line-gradient`` incorrectly).
    """
    if (layer.is_dem is True) and (
        (layer.style_config or {}).get("render_mode") == "hillshade"
    ):
        return "raster-dem"
    if layer.layer_type == "raster_geolens" or layer.dataset_record_type in {
        "raster_dataset",
        "vrt_dataset",
    }:
        return "raster"
    return "vector"


def _walk_get_has_columns(node: Any, cols: set[str]) -> None:
    """Collect ``["get", col]`` / ``["has", col]`` column references from a
    MapLibre expression (paint value or filter), recursing into nested arrays."""
    if not isinstance(node, list) or not node:
        return
    head = node[0]
    if head in {"get", "has"} and len(node) >= 2 and isinstance(node[1], str):
        cols.add(node[1])
        # A ["get", col] inside a larger expression can still nest further refs
        # in later operands, so continue walking the remaining children.
    for child in node:
        _walk_get_has_columns(child, cols)


def _data_driven_columns_for_layer(layer: MapLayerResponse) -> list[str]:
    """Return the SORTED set of feature-property columns a vector layer references.

    builder-audit #338 P1-02 / P1-03: ports the runtime ``getDataDrivenColumnsForLayer``
    collector to the backend so exported tile URLs can request these columns via
    ``cols=``. The tile server projects no attribute columns at z<10 unless asked,
    which otherwise breaks categorical/graduated styling, labels, heatmap weights,
    and 3D heights at low zoom in an exported style. Sources considered:

      * ``style_config.column`` — categorical / graduated styling target;
      * builder ``heatmapWeightColumn`` / ``heightColumn`` (and the legacy
        ``_heatmap-weight-column`` / ``_height_column`` paint keys, in case a layer
        is exported before the paint->builder split has run);
      * ``label_config.column`` — drives the companion label's text-field LAYOUT
        property the paint walk below cannot see;
      * paint expression ``["get", col]`` references (generic catch-all);
      * ``layer.filter`` ``["get"/"has", col]`` references (P1-03 — a filter-only
        column would otherwise be dropped at low zoom).
    """
    cols: set[str] = set()
    style_config = layer.style_config or {}
    style_col = style_config.get("column")
    if isinstance(style_col, str) and style_col:
        cols.add(style_col)

    builder = _builder_style_config(style_config)
    for builder_key in ("heatmapWeightColumn", "heightColumn"):
        value = builder.get(builder_key)
        if isinstance(value, str) and value:
            cols.add(value)

    paint = layer.paint or {}
    for legacy_key in ("_heatmap-weight-column", "_height_column"):
        value = paint.get(legacy_key)
        if isinstance(value, str) and value:
            cols.add(value)

    label_col = (layer.label_config or {}).get("column")
    if isinstance(label_col, str) and label_col:
        cols.add(label_col)

    for value in paint.values():
        _walk_get_has_columns(value, cols)

    # builder-audit #338 P1-03/P1-04: normalize the filter through the SHARED validator
    # first so legacy bare-field comparisons (["==", "field", v]) are rewritten to
    # expression form (["==", ["get", "field"], v]) before the get/has walk — a
    # filter-only column would otherwise be dropped at low zoom.
    try:
        normalized_filter = validate_filter(layer.filter)
    except FilterValidationError:
        normalized_filter = layer.filter
    _walk_get_has_columns(normalized_filter, cols)

    return sorted(cols)


def _tile_url_for_layer(layer: MapLayerResponse) -> str:
    if layer.layer_type == "raster_geolens" or layer.dataset_record_type in {
        "raster_dataset",
        "vrt_dataset",
    }:
        return f"/raster-tiles/{layer.dataset_id}/tiles/{{z}}/{{x}}/{{y}}.png"
    port = get_catalog_port()
    exp = port.round_tile_expiry()
    params: dict[str, Any] = {
        "sig": port.generate_tile_signature(layer.dataset_table_name, exp),
        "exp": exp,
        "scope": layer.dataset_table_name,
    }
    # builder-audit #338 P1-02/P1-03: opt the referenced attribute columns into the tile
    # so data-driven styling, labels, heatmap weights, 3D heights, and filter refs
    # evaluate against real data at z<10. Stable, sorted to keep the URL determinate.
    cols = _data_driven_columns_for_layer(layer)
    if cols:
        params["cols"] = ",".join(cols)
    query = urlencode(params)
    return f"/tiles/data.{layer.dataset_table_name}/{{z}}/{{x}}/{{y}}.pbf?{query}"


def _raster_dem_source(layer: MapLayerResponse) -> dict[str, Any]:
    """Build a ``raster-dem`` mesh source dict for a DEM layer (terrain/hillshade)."""
    return {
        "type": "raster-dem",
        "tiles": [_tile_url_for_layer(layer)],
        "tileSize": 256,
        "encoding": "mapbox",
    }


def _source_for_layer(layer: MapLayerResponse) -> dict[str, Any]:
    source: dict[str, Any]
    source_type = _source_type_for_layer(layer)
    if source_type == "raster-dem":
        source = _raster_dem_source(layer)
    elif source_type == "raster":
        source = {
            "type": "raster",
            "tiles": [_tile_url_for_layer(layer)],
            "tileSize": 256,
        }
    else:
        # fix(#394): source maxzoom mirrors the live builder (map-sync.ts) —
        # 14 for plain vector sources so exported styles OVERZOOM z15+ instead
        # of hammering the backend at deep zooms, and 22 for server-cluster
        # sources because the backend only unclusters for z > cluster_max_zoom
        # (default 14), so cluster clients must be able to fetch z15+ tiles.
        is_cluster = (layer.style_config or {}).get("render_mode") == "cluster"
        source = {
            "type": "vector",
            "tiles": [_tile_url_for_layer(layer)],
            "minzoom": 1,
            "maxzoom": 22 if is_cluster else 14,
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
    layout["text-font"] = list(LABEL_FONT_STACK)
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


def _symbol_match_label(value: Any) -> str:
    """Stringify a category value the way JS ``String()`` does.

    fix(#394) ST-04: match labels are compared against a
    ``["to-string", ["get", col]]`` input (below), so every label must be a
    string and integral floats must drop their ``.0`` (MapLibre's to-string
    renders 4.0 as "4") to stay byte-parity with the frontend adapter.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _symbol_icon_expression(symbol: dict[str, Any]) -> Any:
    fallback = symbol.get("iconImage") or symbol.get("icon_image") or "marker"
    category_column = symbol.get("categoryColumn") or symbol.get("category_column")
    categories = symbol.get("categories")
    if category_column and isinstance(categories, list):
        pairs: list[Any] = []
        for entry in categories:
            # fix(#394) ST-04: skip null category values too — the to-string
            # input renders null as "" so a "None"/null label could never match.
            if (
                not isinstance(entry, dict)
                or entry.get("icon") is None
                or entry.get("value") is None
            ):
                continue
            pairs.append(_symbol_match_label(entry.get("value")))
            pairs.append(_sprite_icon_id(entry["icon"]))
        if not pairs:
            # fix(#394) ST-01: zero surviving pairs would emit
            # ["match", input, fallback] (length 3 < the spec minimum 5) —
            # MapLibre addLayer throws and the symbol layer silently never
            # renders. Mirror of the frontend symbol-adapter guard.
            return _sprite_icon_id(fallback)
        # fix(#394) ST-04: to-string the input so numeric MVT values match the
        # stringified sample values the editor stores (numeric columns always
        # fell through to the fallback icon before).
        expression: list[Any] = [
            "match",
            ["to-string", ["get", category_column]],
            *pairs,
            _sprite_icon_id(fallback),
        ]
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
        or DEFAULT_OUTLINE_WIDTH
    )
    companions: list[dict[str, Any]] = [
        {
            "id": f"{layer_id}-outline",
            "type": "line",
            "source": source_id,
            "source-layer": _mvt_source_layer(layer),
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
        extrusion_min_zoom = (
            _finite_number(builder.get("extrusionMinZoom"))
            or DEFAULT_EXTRUSION_MIN_ZOOM
        )
        configured_opacity = _finite_number(builder.get("extrusionOpacity"))
        extrusion_opacity = (
            min(layer.opacity, EXTRUSION_OPACITY_CAP)
            if configured_opacity is None
            else _clamp_number(configured_opacity, 0, 1)
        )
        extrusion_layer: dict[str, Any] = {
            "id": f"{layer_id}-extrusion",
            "type": "fill-extrusion",
            "source": source_id,
            "source-layer": _mvt_source_layer(layer),
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
    arrow_size = _finite_number(builder.get("arrowSize")) or DEFAULT_ARROW_BASE_SIZE
    arrow_spacing = _finite_number(builder.get("arrowSpacing")) or DEFAULT_ARROW_SPACING
    arrow_layer: dict[str, Any] = {
        "id": f"{layer_id}-arrow",
        "type": "symbol",
        "source": source_id,
        "source-layer": _mvt_source_layer(layer),
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


# builder-audit #338 P1-06: backend color-relief (hypsometric tint) companion support.
# Representative 7-stop ramps mirroring the frontend chroma-js palettes used by
# `color-relief-sync.ts`. Exact hex parity with chroma is not required (external
# consumers render whatever stops we emit); unknown ramp names fall back to YlOrRd,
# matching the frontend `getRampColors` fallback (threat T-1140-05).
_COLOR_RELIEF_RAMPS: dict[str, list[str]] = {
    "Viridis": [
        "#440154",
        "#443983",
        "#31688e",
        "#21918c",
        "#35b779",
        "#90d743",
        "#fde725",
    ],
    "Inferno": [
        "#000004",
        "#320a5e",
        "#781c6d",
        "#bb3754",
        "#ed6925",
        "#fcb519",
        "#fcffa4",
    ],
    "Plasma": [
        "#0d0887",
        "#5302a3",
        "#8b0aa5",
        "#b83289",
        "#db5c68",
        "#f48849",
        "#f0f921",
    ],
    "Magma": [
        "#000004",
        "#2c115f",
        "#721f81",
        "#b5367a",
        "#f1605d",
        "#feae77",
        "#fcfdbf",
    ],
    "Cividis": [
        "#00204d",
        "#00336f",
        "#39486b",
        "#575d6d",
        "#707173",
        "#a99d59",
        "#ffea46",
    ],
    "YlOrRd": [
        "#ffffcc",
        "#ffeda0",
        "#fed976",
        "#feb24c",
        "#fd8d3c",
        "#f03b20",
        "#bd0026",
    ],
    "Blues": [
        "#f7fbff",
        "#deebf7",
        "#c6dbef",
        "#9ecae1",
        "#6baed6",
        "#3182bd",
        "#08519c",
    ],
    "Greens": [
        "#f7fcf5",
        "#e5f5e0",
        "#c7e9c0",
        "#a1d99b",
        "#74c476",
        "#31a354",
        "#006d2c",
    ],
    "Spectral": [
        "#9e0142",
        "#f46d43",
        "#fdae61",
        "#ffffbf",
        "#abdda4",
        "#66c2a5",
        "#3288bd",
    ],
    "Turbo": [
        "#30123b",
        "#4145ab",
        "#4675ed",
        "#39a2fc",
        "#1bcfd4",
        "#62fc6b",
        "#d2e935",
    ],
}


def _color_relief_color_expression(ramp_name: str) -> list[Any]:
    """Build a MapLibre ``color-relief-color`` interpolate-over-elevation expression."""
    colors = _COLOR_RELIEF_RAMPS.get(ramp_name, _COLOR_RELIEF_RAMPS["YlOrRd"])
    step = (COLOR_RELIEF_ELEV_MAX - COLOR_RELIEF_ELEV_MIN) / (len(colors) - 1)
    expr: list[Any] = ["interpolate", ["linear"], ["elevation"]]
    for index, color in enumerate(colors):
        expr.append(COLOR_RELIEF_ELEV_MIN + index * step)
        expr.append(color)
    return expr


def _hypso_config_for_layer(layer: MapLayerResponse) -> tuple[bool, str]:
    """Resolve (enabled, ramp_name) for a DEM layer's color-relief companion.

    Reads the builder-private hypsometric flags from either the builder block
    (snake_case ``hypso_enabled``/``hypso_ramp`` after the paint->builder split,
    or camelCase if a client sent it that way) or the raw ``_hypso-*`` paint keys.
    """
    builder = _builder_style_config(layer.style_config)
    paint = layer.paint or {}
    enabled = bool(
        builder.get("hypso_enabled")
        or builder.get("hypsoEnabled")
        or paint.get("_hypso-enabled")
    )
    ramp = (
        builder.get("hypso_ramp")
        or builder.get("hypsoRamp")
        or paint.get("_hypso-ramp")
        or COLOR_RELIEF_DEFAULT_RAMP
    )
    if not isinstance(ramp, str) or not ramp:
        ramp = COLOR_RELIEF_DEFAULT_RAMP
    return enabled, ramp


def _color_relief_companion_layer(
    layer: MapLayerResponse,
    source_id: str,
    layer_id: str,
) -> dict[str, Any] | None:
    """Emit a native ``color-relief`` companion for a hypsometric-tinted DEM layer.

    builder-audit #338 P1-06: a map that shows hypsometric tint in the builder/viewer
    previously exported WITHOUT that visual layer. The builder-internal ``_hypso-*``
    paint keys are already stripped from the primary paint by ``_clean_paint``; this
    reconstructs the visible tint as a spec-valid layer that re-imports cleanly.
    """
    enabled, ramp = _hypso_config_for_layer(layer)
    if not enabled:
        return None
    return {
        "id": f"{layer_id}-colorrelief",
        # `color-relief` is a native MapLibre 5.24 layer type.
        "type": "color-relief",
        "source": source_id,
        "metadata": {
            "geolens": {
                "companion": "color-relief",
                "parent_layer_id": str(layer.id),
                "ramp": ramp,
            }
        },
        "layout": _companion_visibility(layer),
        "paint": {
            "color-relief-color": _color_relief_color_expression(ramp),
            "color-relief-opacity": COLOR_RELIEF_DEFAULT_OPACITY,
        },
    }


def _style_layer_for_map_layer(
    layer: MapLayerResponse,
    source_id: str,
) -> list[dict[str, Any]]:
    style_config = layer.style_config or {}
    # Codex P2 (#338): a DEM saved in "terrain" render mode is mesh-only — the
    # builder/viewer suppress its visual raster and use it solely as the 3D
    # terrain source. Emitting a visible `raster` layer here would put a flat DEM
    # image on top of the map alongside the `terrain` block, contradicting the
    # suppression and changing the exported appearance. The dedicated raster-dem
    # mesh source is still added by the terrain block in build_maplibre_style.
    if bool(layer.is_dem) and style_config.get("render_mode") == "terrain":
        return []
    layer_type = _geometry_layer_type(
        layer.dataset_geometry_type,
        style_config,
        is_dem=bool(layer.is_dem),
        layer_type=layer.layer_type,
    )
    layout = _clean_layout(layer.layout)
    paint = _clean_paint(layer.paint)
    if layer_type == "line":
        legacy_dasharray = dict(layer.layout or {}).get("line-dasharray")
        if legacy_dasharray is not None and "line-dasharray" not in paint:
            paint["line-dasharray"] = legacy_dasharray
    # builder-audit #338 STYLE-03: source type gates line-gradient paint; reuse the single
    # `_source_type_for_layer` helper instead of recomputing the 3-way branch here.
    source_type = _source_type_for_layer(layer)
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
        base["source-layer"] = _mvt_source_layer(layer)
    if layer.filter:
        base["filter"] = layer.filter
    if not layer.visible:
        base["layout"] = {**layout, "visibility": "none"}

    # Companions emitted BELOW the primary in painter order (drawn first / underneath).
    below_companions: list[dict[str, Any]] = []
    # Companions emitted ABOVE the primary (outline/extrusion/arrow/label).
    above_companions: list[dict[str, Any]] = []
    label_config = layer.label_config or {}
    if layer_type == "fill":
        builder = _builder_style_config(style_config)
        if builder.get("strokeDisabled") or (layer.paint or {}).get("_stroke-disabled"):
            base["paint"] = {**base["paint"], "fill-outline-color": "rgba(0,0,0,0)"}
        above_companions.extend(_fill_companion_layers(layer, source_id, layer_id))
    elif layer_type == "line":
        arrow_layer = _line_arrow_companion_layer(
            layer,
            source_id,
            layer_id,
            style_config,
            paint,
        )
        if arrow_layer:
            above_companions.append(arrow_layer)
    elif layer_type == "hillshade":
        # builder-audit #338 P1-06: color-relief renders BELOW the hillshade so the
        # shading sits on top of the tint (mirrors color-relief-sync.ts beforeId).
        relief = _color_relief_companion_layer(layer, source_id, layer_id)
        if relief is not None:
            below_companions.append(relief)

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
            "source-layer": _mvt_source_layer(layer),
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
        above_companions.append(label_layer)

    return [*below_companions, base, *above_companions]


# builder-audit #338 SPEC-01: per-layer-type MapLibre paint/layout property allow-lists.
# `build_maplibre_style` copies stored paint/layout into the output verbatim (minus
# `_`-prefixed builder keys), so without this a misspelled ('fill-colour') or
# wrong-surface property would be persisted and re-emitted, producing a document
# MapLibre's own validator rejects at load. We STRIP (rather than raise on) unknown
# keys per layer type so a single bad property degrades gracefully instead of
# 500-ing GET style.json. Unknown layer types are left untouched (forward-compat).
_COMMON_LAYOUT_PROPERTIES = frozenset({"visibility"})
_PAINT_PROPERTIES_BY_TYPE: dict[str, frozenset[str]] = {
    "background": frozenset(
        {"background-color", "background-pattern", "background-opacity"}
    ),
    "fill": frozenset(
        {
            "fill-antialias",
            "fill-opacity",
            "fill-color",
            "fill-outline-color",
            "fill-translate",
            "fill-translate-anchor",
            "fill-pattern",
        }
    ),
    "line": frozenset(
        {
            "line-opacity",
            "line-color",
            "line-translate",
            "line-translate-anchor",
            "line-width",
            "line-gap-width",
            "line-offset",
            "line-blur",
            "line-dasharray",
            "line-pattern",
            "line-gradient",
        }
    ),
    "symbol": frozenset(
        {
            "icon-opacity",
            "icon-color",
            "icon-halo-color",
            "icon-halo-width",
            "icon-halo-blur",
            "icon-translate",
            "icon-translate-anchor",
            "text-opacity",
            "text-color",
            "text-halo-color",
            "text-halo-width",
            "text-halo-blur",
            "text-translate",
            "text-translate-anchor",
        }
    ),
    "circle": frozenset(
        {
            "circle-radius",
            "circle-color",
            "circle-blur",
            "circle-opacity",
            "circle-translate",
            "circle-translate-anchor",
            "circle-pitch-scale",
            "circle-pitch-alignment",
            "circle-stroke-width",
            "circle-stroke-color",
            "circle-stroke-opacity",
        }
    ),
    "heatmap": frozenset(
        {
            "heatmap-radius",
            "heatmap-weight",
            "heatmap-intensity",
            "heatmap-color",
            "heatmap-opacity",
        }
    ),
    "fill-extrusion": frozenset(
        {
            "fill-extrusion-opacity",
            "fill-extrusion-color",
            "fill-extrusion-translate",
            "fill-extrusion-translate-anchor",
            "fill-extrusion-pattern",
            "fill-extrusion-height",
            "fill-extrusion-base",
            "fill-extrusion-vertical-gradient",
        }
    ),
    "raster": frozenset(
        {
            "raster-opacity",
            "raster-hue-rotate",
            "raster-brightness-min",
            "raster-brightness-max",
            "raster-saturation",
            "raster-contrast",
            "raster-resampling",
            "raster-fade-duration",
        }
    ),
    "hillshade": frozenset(_HILLSHADE_PAINT_KEYS),
    "color-relief": frozenset({"color-relief-color", "color-relief-opacity"}),
}
_LAYOUT_PROPERTIES_BY_TYPE: dict[str, frozenset[str]] = {
    "background": _COMMON_LAYOUT_PROPERTIES,
    "fill": _COMMON_LAYOUT_PROPERTIES | frozenset({"fill-sort-key"}),
    "circle": _COMMON_LAYOUT_PROPERTIES | frozenset({"circle-sort-key"}),
    "heatmap": _COMMON_LAYOUT_PROPERTIES,
    "fill-extrusion": _COMMON_LAYOUT_PROPERTIES,
    "raster": _COMMON_LAYOUT_PROPERTIES,
    "hillshade": _COMMON_LAYOUT_PROPERTIES,
    "color-relief": _COMMON_LAYOUT_PROPERTIES,
    "line": _COMMON_LAYOUT_PROPERTIES
    | frozenset(
        {
            "line-cap",
            "line-join",
            "line-miter-limit",
            "line-round-limit",
            "line-sort-key",
        }
    ),
    "symbol": _COMMON_LAYOUT_PROPERTIES
    | frozenset(
        {
            "symbol-placement",
            "symbol-spacing",
            "symbol-avoid-edges",
            "symbol-sort-key",
            "symbol-z-order",
            "icon-allow-overlap",
            "icon-overlap",
            "icon-ignore-placement",
            "icon-optional",
            "icon-rotation-alignment",
            "icon-size",
            "icon-text-fit",
            "icon-text-fit-padding",
            "icon-image",
            "icon-rotate",
            "icon-padding",
            "icon-keep-upright",
            "icon-offset",
            "icon-anchor",
            "icon-pitch-alignment",
            "text-pitch-alignment",
            "text-rotation-alignment",
            "text-field",
            "text-font",
            "text-size",
            "text-max-width",
            "text-line-height",
            "text-letter-spacing",
            "text-justify",
            "text-radial-offset",
            "text-variable-anchor",
            "text-anchor",
            "text-max-angle",
            "text-writing-mode",
            "text-rotate",
            "text-padding",
            "text-keep-upright",
            "text-transform",
            "text-offset",
            "text-allow-overlap",
            "text-overlap",
            "text-ignore-placement",
            "text-optional",
        }
    ),
}


def _strip_unknown_properties(
    layer: dict[str, Any],
    key: str,
    allowed: frozenset[str],
) -> None:
    block = layer.get(key)
    if not isinstance(block, dict):
        return
    unknown = [name for name in block if name not in allowed]
    if not unknown:
        return
    for name in unknown:
        block.pop(name, None)
    logger.warning(
        "Stripping unknown %s propert%s on emitted %r layer %s: %s",
        key,
        "y" if len(unknown) == 1 else "ies",
        layer.get("type"),
        layer.get("id"),
        ", ".join(sorted(unknown)),
    )


def _strip_wrong_typed_values(layer: dict[str, Any], key: str) -> None:
    """Strip paint/layout values whose scalar type violates the GL spec contract.

    builder-audit #338 SPEC-01: the property-name allowlist catches misspelled keys,
    but not a wrong-typed value (e.g. a string where ``*-opacity`` expects a
    number — the source of the NaN-opacity math flagged in ADAPT-11). Expressions
    (lists) are validated at runtime by MapLibre, so they are passed through; only
    plainly mistyped scalars are dropped (graceful, never a 500 on stored data).
    """
    block = layer.get(key)
    if not isinstance(block, dict):
        return
    bad: list[str] = []
    for name, value in block.items():
        if value is None or isinstance(value, list):
            continue  # None == default; list == expression (runtime-validated)
        if name.endswith("-color"):
            if not isinstance(value, str):
                bad.append(name)
        elif name.endswith("-opacity"):
            # bool is an int subclass — reject it explicitly.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                bad.append(name)
    for name in bad:
        block.pop(name, None)
    if bad:
        logger.warning(
            "Stripping wrong-typed %s value%s on emitted %r layer %s: %s",
            key,
            "" if len(bad) == 1 else "s",
            layer.get("type"),
            layer.get("id"),
            ", ".join(sorted(bad)),
        )


def _validate_emitted_style(style: dict[str, Any]) -> None:
    """Strip non-spec paint/layout properties from every emitted layer in place."""
    layers = style.get("layers")
    if not isinstance(layers, list):
        return
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        layer_type = layer.get("type")
        paint_allowed = _PAINT_PROPERTIES_BY_TYPE.get(layer_type)
        if paint_allowed is not None:
            _strip_unknown_properties(layer, "paint", paint_allowed)
        layout_allowed = _LAYOUT_PROPERTIES_BY_TYPE.get(layer_type)
        if layout_allowed is not None:
            _strip_unknown_properties(layer, "layout", layout_allowed)
        # Type-contract check runs after the name allowlist on every typed layer.
        _strip_wrong_typed_values(layer, "paint")


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
        style_layers.extend(_style_layer_for_map_layer(layer, source_id))

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
            # Phase 20260526-builder-audit #338 BLD-20260526-11: builder-intent on incompatible source emits no warning otherwise. The
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
        try:
            exaggeration = float(tc.get("exaggeration", 1.0))
        except (TypeError, ValueError):
            exaggeration = 1.0
        terrain_dataset_id = str(tc["source_dataset_id"])
        terrain_source_id = f"geolens-{_safe_id(terrain_dataset_id)}"
        existing = sources.get(terrain_source_id)
        if isinstance(existing, dict) and existing.get("type") == "raster-dem":
            # The visible DEM is already a raster-dem mesh (hillshade mode) — point
            # the terrain root straight at it.
            terrain_block = {"source": terrain_source_id, "exaggeration": exaggeration}
        else:
            # builder-audit #338 P1-05: the DEM dataset is rendered as a plain raster (e.g.
            # the "image" DEM render mode) or has no visible layer, so the existing
            # source is NOT a valid `raster-dem` for the MapLibre terrain root. Emit a
            # DEDICATED raster-dem mesh source for the terrain dataset regardless of
            # the visible render mode, so the exported terrain never points at a raster
            # source. Visual terrain-mode layers stay suppressed; only the mesh is added.
            terrain_layer = next(
                (
                    layer
                    for layer in layers
                    if str(layer.dataset_id) == terrain_dataset_id
                ),
                None,
            )
            if terrain_layer is not None:
                mesh_source_id = f"geolens-terrain-{_safe_id(terrain_dataset_id)}"
                if mesh_source_id not in sources:
                    mesh_source = _raster_dem_source(terrain_layer)
                    mesh_source["metadata"] = {
                        "geolens": {
                            "dataset_id": terrain_dataset_id,
                            "table_name": terrain_layer.dataset_table_name,
                            "geometry_type": terrain_layer.dataset_geometry_type,
                            "record_type": terrain_layer.dataset_record_type,
                            "terrain_mesh": True,
                        }
                    }
                    sources[mesh_source_id] = mesh_source
                terrain_block = {
                    "source": mesh_source_id,
                    "exaggeration": exaggeration,
                }

    style: dict[str, Any] = {
        "version": STYLE_VERSION,
        "name": map_obj.name,
        "metadata": {
            "geolens": {
                "map_id": str(map_obj.id),
                "description": map_obj.description,
                "basemap_style": map_obj.basemap_style,
                "show_basemap_labels": map_obj.show_basemap_labels,
                # builder-audit #338 STYLE-04: lenient on the read/export path so stored
                # schema skew degrades instead of 500-ing GET style.json.
                "basemap_config": _clean_basemap_config(
                    getattr(map_obj, "basemap_config", None), lenient=True
                ),
                "terrain_config": map_obj.terrain_config,
            }
        },
        "sprite": [{"id": GEOLENS_SPRITE_ID, "url": SPRITE_URL}],
        "glyphs": GLYPHS_URL,
        "sources": sources,
        "layers": style_layers,
    }
    # builder-audit #338 SPEC-07: emit `projection` at the GL style root from
    # basemap_config so a spec-conformant consumer honors it in spec position
    # (not only inside the private basemap_config metadata namespace).
    basemap_config = style["metadata"]["geolens"]["basemap_config"]
    if isinstance(basemap_config, dict) and basemap_config.get("projection"):
        style["projection"] = {"type": basemap_config["projection"]}
    # builder-audit #338 SPEC-07: root `light`/`sky`/`fog`/`transition` are a
    # documented non-goal — the Map model has no column to persist them, so there
    # is nothing to round-trip. The inert getattr-based pass-through (Codex P2) was
    # removed; emitting them would require a schema migration (deferred).
    if map_obj.center_lng is not None and map_obj.center_lat is not None:
        style["center"] = [map_obj.center_lng, map_obj.center_lat]
    if map_obj.zoom is not None:
        style["zoom"] = map_obj.zoom
    style["bearing"] = map_obj.bearing or 0
    style["pitch"] = map_obj.pitch or 0
    if terrain_block:
        style["terrain"] = terrain_block
    # builder-audit #338 SPEC-01: validate the produced document against a per-layer
    # paint/layout property allow-list before returning, so a misspelled or
    # wrong-surface property cannot be emitted in the MapLibre style JSON.
    _validate_emitted_style(style)
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
    companion: dict[str, Any],
    style_config: dict[str, Any],
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


def _builder_from_extrusion_companion(
    companion: dict[str, Any],
    style_config: dict[str, Any],
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
    minzoom = _finite_number(companion.get("minzoom"))
    if minzoom is not None and "extrusionMinZoom" not in builder:
        builder["extrusionMinZoom"] = minzoom
    opacity = _finite_number(paint.get("fill-extrusion-opacity"))
    if opacity is not None and "extrusionOpacity" not in builder:
        builder["extrusionOpacity"] = opacity


def _builder_from_arrow_companion(
    companion: dict[str, Any],
    style_config: dict[str, Any],
    builder: dict[str, Any],
) -> None:
    # An arrow companion implies the primary line was authored in arrow render mode.
    style_config["render_mode"] = "arrow"
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


def _builder_from_color_relief_companion(
    companion: dict[str, Any],
    style_config: dict[str, Any],
    builder: dict[str, Any],
) -> None:
    # builder-audit #338 P1-06: reconstruct the DEM hypsometric-tint builder flags from
    # the color-relief companion (the ramp name is carried in companion metadata).
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


# builder-audit #338 STYLE-02: per-companion-type parse registry. Paired with the emit
# helpers above (`_fill_companion_layers` / `_line_arrow_companion_layer` /
# `_color_relief_companion_layer`), this keeps export and import for each builder
# companion type discoverable together and makes adding a type a single entry rather
# than threading a new collection bucket plus reconstruction branch by hand. The
# `label` companion is handled separately because it reconstructs `label_config`
# rather than the builder block.
_BUILDER_COMPANION_PARSERS = {
    "outline": _builder_from_outline_companion,
    "extrusion": _builder_from_extrusion_companion,
    "arrow": _builder_from_arrow_companion,
    "color-relief": _builder_from_color_relief_companion,
}


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
    # builder-audit #338 STYLE-02: one companion bucket keyed by parent layer id, then by
    # companion type — instead of N parallel dicts that must each be remembered when
    # a new companion type is added.
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
        # builder-audit #338 SPEC-07: preserve GL root light/transition across import.
        light=style.get("light") if isinstance(style.get("light"), dict) else None,
        transition=style.get("transition")
        if isinstance(style.get("transition"), dict)
        else None,
    )
