"""Schemas for AI map generation."""

import re

import structlog
from pydantic import BaseModel, Field

logger = structlog.stdlib.get_logger(__name__)

# Valid MapLibre paint properties per geometry type
_VALID_PAINT_PROPS: dict[str, set[str]] = {
    "fill": {
        "fill-color",
        "fill-opacity",
        "_outline-color",
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
}

_COLOR_PROPS = {
    "fill-color",
    "_outline-color",
    "line-color",
    "circle-color",
    "circle-stroke-color",
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
        return True  # ["step", getter, default, stop1, out1, ...]
    if op == "interpolate" and len(expr) >= 5:
        return True  # ["interpolate", method, getter, stop1, out1, ...]
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
    if not paint or not geometry_type:
        return paint

    gt = geometry_type.lower()
    if "polygon" in gt:
        layer_type = "fill"
    elif "line" in gt:
        layer_type = "line"
    else:
        layer_type = "circle"

    valid_props = _VALID_PAINT_PROPS[layer_type]
    cleaned = {}
    for key, value in paint.items():
        if key not in valid_props:
            logger.warning(
                "Removed invalid paint property for geometry type",
                property=key,
                geometry_type=geometry_type,
                layer_type=layer_type,
            )
            continue

        # Validate color properties
        if key in _COLOR_PROPS and not _is_valid_color(value):
            logger.warning(
                "Invalid color value, removing property",
                property=key,
                value=str(value)[:50],
            )
            continue

        # Clamp numeric properties to valid bounds
        if key in _PAINT_BOUNDS and isinstance(value, (int, float)):
            lo, hi = _PAINT_BOUNDS[key]
            value = max(lo, min(hi, float(value)))

        # Validate expression syntax for color expressions
        if key in _COLOR_PROPS and isinstance(value, list):
            if not _validate_expression(value):
                logger.warning(
                    "Invalid MapLibre expression, removing property",
                    property=key,
                )
                continue

        cleaned[key] = value
    return cleaned or None


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


class ChatAction(BaseModel):
    type: str  # set_filter, set_style, set_data_driven_style, set_label, toggle_visibility, add_layer, remove_layer, show_query_result, set_opacity
    layer_id: str | None = None
    expression: list | None = None  # for set_filter
    paint: dict | None = None  # for set_style / set_data_driven_style
    style_config: dict | None = None  # for set_data_driven_style
    label_config: dict | None = None  # for set_label
    dataset_id: str | None = None  # for add_layer
    visible: bool | None = None  # for toggle_visibility
    opacity: float | None = None  # for set_opacity
    geojson: dict | None = None  # for show_query_result
    bbox: list[float] | None = None  # for show_query_result


class ChatResponse(BaseModel):
    explanation: str
    actions: list[ChatAction]
