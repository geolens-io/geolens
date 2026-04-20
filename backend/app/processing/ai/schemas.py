"""Schemas for AI map generation."""

import re

import structlog
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.stdlib.get_logger(__name__)

# Valid MapLibre paint properties per geometry type
_VALID_PAINT_PROPS: dict[str, set[str]] = {
    "fill": {
        "fill-color",
        "fill-opacity",
        "fill-outline-color",
        "_outline-color",
        "_outline-width",
        "_fill-disabled",
        "_stroke-disabled",
        "fill-antialias",
        "fill-translate",
        "fill-translate-anchor",
        "fill-pattern",
    },
    "line": {
        "line-color",
        "line-opacity",
        "line-width",
        "line-gap-width",
        "line-blur",
        "line-dasharray",
        "line-translate",
        "line-translate-anchor",
        "line-offset",
        "line-gradient",
        "line-pattern",
    },
    "circle": {
        "circle-color",
        "circle-opacity",
        "circle-radius",
        "circle-blur",
        "circle-stroke-color",
        "circle-stroke-opacity",
        "circle-stroke-width",
        "circle-translate",
        "circle-translate-anchor",
        "circle-pitch-scale",
        "circle-pitch-alignment",
    },
    "heatmap": {
        "heatmap-radius",
        "heatmap-weight",
        "heatmap-intensity",
        "heatmap-color",
        "heatmap-opacity",
    },
}

# Color props including heatmap-color
_COLOR_PROPS = {
    "fill-color",
    "fill-outline-color",
    "_outline-color",
    "line-color",
    "circle-color",
    "circle-stroke-color",
    "heatmap-color",
}


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")
_RGBA_RE = re.compile(r"^rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(,\s*[\d.]+\s*)?\)$")


def _is_valid_color(value: object) -> bool:
    """Check if a value is a valid MapLibre color (hex or rgba)."""
    if isinstance(value, list):
        return True  # expression — validated separately
    if not isinstance(value, str):
        return False
    return bool(_HEX_COLOR_RE.match(value) or _RGBA_RE.match(value))


_PAINT_BOUNDS: dict[str, tuple[float, float]] = {
    "fill-opacity": (0.0, 1.0),
    "line-opacity": (0.0, 1.0),
    "line-width": (0.0, 50.0),
    "line-gap-width": (0.0, 50.0),
    "line-blur": (0.0, 50.0),
    "line-offset": (-50.0, 50.0),
    "circle-opacity": (0.0, 1.0),
    "circle-radius": (0.0, 200.0),
    "circle-blur": (0.0, 50.0),
    "circle-stroke-opacity": (0.0, 1.0),
    "circle-stroke-width": (0.0, 20.0),
    "heatmap-radius": (1.0, 200.0),
    "heatmap-weight": (0.0, 10.0),
    "heatmap-intensity": (0.0, 10.0),
    "heatmap-opacity": (0.0, 1.0),
}


def _validate_expression(expr: list) -> bool:
    """Lightweight MapLibre expression syntax check."""
    if not isinstance(expr, list) or len(expr) < 2:
        return False
    op = expr[0]
    if op == "get" and len(expr) == 2 and isinstance(expr[1], str):
        return True
    if op == "match" and len(expr) >= 4:
        return True  # ["match", getter, val1, out1, ..., fallback]
    if op == "step" and len(expr) >= 4:
        # Validate stop values are numeric: ["step", getter, default, stop1, out1, ...]
        # Positions 3, 5, 7... are stop values (must be numeric)
        for i in range(3, len(expr), 2):
            if not isinstance(expr[i], (int, float)):
                return False
        return True
    if op == "interpolate" and len(expr) >= 5:
        # Validate stop values are numeric: ["interpolate", method, getter, stop1, out1, ...]
        # Positions 3, 5, 7... are stop values (must be numeric)
        for i in range(3, len(expr), 2):
            if not isinstance(expr[i], (int, float)):
                return False
        return True
    if op == "case" and len(expr) >= 3:
        return True
    if op in ("literal", "to-string", "to-number", "to-boolean"):
        return True
    if op in (
        "all",
        "any",
        "!",
        "==",
        "!=",
        ">",
        "<",
        ">=",
        "<=",
        "in",
        "!in",
        "has",
        "!has",
    ):
        return True
    if op in ("concat", "downcase", "upcase", "coalesce"):
        return True
    return False


def validate_paint_for_geometry(
    paint: dict | None, geometry_type: str | None
) -> dict | None:
    """Validate and sanitize paint properties for the given geometry type.

    Removes properties that don't match the geometry type (e.g. fill-color on a
    point layer) and logs a warning. Returns the cleaned paint dict.
    """
    cleaned, warnings = validate_paint_with_feedback(paint, geometry_type)
    for msg in warnings:
        logger.warning("paint_validation", message=msg, geometry_type=geometry_type)
    return cleaned


def validate_paint_with_feedback(
    paint: dict | None, geometry_type: str | None
) -> tuple[dict | None, list[str]]:
    """Like validate_paint_for_geometry but also returns a list of warning strings.

    Used by the chat service to feed validation feedback back to the LLM.
    """
    if not paint or not geometry_type:
        return paint, []

    gt = geometry_type.lower()
    if "polygon" in gt:
        layer_type = "fill"
    elif "line" in gt:
        layer_type = "line"
    elif "heatmap" in gt:
        layer_type = "heatmap"
    else:
        layer_type = "circle"

    valid_props = _VALID_PAINT_PROPS.get(layer_type, _VALID_PAINT_PROPS["circle"])
    cleaned = {}
    warnings: list[str] = []
    for key, value in paint.items():
        if key not in valid_props:
            warnings.append(f"Removed '{key}': not valid for {layer_type} layers")
            continue
        if key in _COLOR_PROPS and not _is_valid_color(value):
            warnings.append(f"Removed '{key}': invalid color value")
            continue
        if key in _PAINT_BOUNDS and isinstance(value, (int, float)):
            lo, hi = _PAINT_BOUNDS[key]
            value = max(lo, min(hi, float(value)))
        if key in _COLOR_PROPS and isinstance(value, list):
            if not _validate_expression(value):
                warnings.append(f"Removed '{key}': invalid MapLibre expression")
                continue
        cleaned[key] = value
    return cleaned or None, warnings


class MapGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=1000)
    language: str | None = None  # e.g. "en", "es", "fr", "de"


class MapGenerateResponse(BaseModel):
    map_id: str
    map_name: str
    explanation: str
    datasets_used: list[str]


# Internal — structured output the LLM produces
class LLMLayerSpec(BaseModel):
    dataset_id: str
    sort_order: int = 0
    visible: bool = True
    opacity: float = 1.0
    paint: dict | None = None
    layout: dict | None = None


class LLMMapSpec(BaseModel):
    name: str
    description: str | None = None
    center_lng: float = 0.0
    center_lat: float = 0.0
    zoom: float = 2.0
    basemap_style: str = "openfreemap-positron"
    layers: list[LLMLayerSpec]
    explanation: str = ""


# --- Chat-based map editing schemas ---


class ChatHistoryMessage(BaseModel):
    """A single message in the conversation history."""

    role: str  # "user" or "assistant"
    content: str


def history_to_dicts(
    history: list[ChatHistoryMessage] | None,
) -> list[dict] | None:
    """Convert ChatHistoryMessage list to plain dicts for the LLM loop."""
    if not history:
        return None
    return [{"role": h.role, "content": h.content} for h in history]


class ChatMapLayer(BaseModel):
    """Layer state sent from frontend for chat context."""

    id: str
    name: str
    dataset_id: str
    dataset_table_name: str
    geometry_type: str | None = None
    layer_type: str | None = None  # 'raster_geolens' or 'vector_geolens'
    column_info: list[dict] | None = None
    dataset_title: str | None = None
    feature_count: int | None = None
    sample_values: dict | None = None
    visible: bool = True
    filter: list | dict | None = None
    label_config: dict | None = None
    style_config: dict | None = None
    paint: dict | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    map_id: str
    layers: list[ChatMapLayer]
    language: str | None = None  # e.g. "en", "es", "fr", "de"
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=20)


class GeoJSONFeature(BaseModel):
    """A GeoJSON Feature."""

    model_config = ConfigDict(extra="allow")

    type: str = "Feature"
    geometry: dict | None = None
    properties: dict | None = None


class GeoJSONFeatureCollection(BaseModel):
    """A GeoJSON FeatureCollection."""

    model_config = ConfigDict(extra="allow")

    type: str = "FeatureCollection"
    features: list[GeoJSONFeature] = []


class ChatAction(BaseModel):
    type: str  # set_filter, set_style, set_data_driven_style, set_label, toggle_visibility, add_layer, remove_layer, show_query_result, set_opacity
    layer_id: str | None = None
    expression: list | None = None  # for set_filter
    paint: dict | None = None  # for set_style / set_data_driven_style
    style_config: dict | None = None  # for set_data_driven_style
    label_config: dict | None = None  # for set_label
    dataset_id: str | None = None  # for add_layer
    visible: bool | None = None  # for toggle_visibility
    opacity: float | None = Field(None, ge=0.0, le=1.0)  # for set_opacity
    geojson: GeoJSONFeatureCollection | None = None  # for show_query_result
    bbox: list[float] | None = None  # for show_query_result


class ChatResponse(BaseModel):
    explanation: str
    actions: list[ChatAction]
