"""Sanitization helpers for MapLibre style import/export metadata."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.modules.catalog.maps.schemas import (
    BUILDER_SNAKE_TO_CAMEL_KEYS,
    LEGACY_BUILDER_PAINT_KEYS,
    BasemapConfig,
)

logger = logging.getLogger(__name__)

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
    "legendLabel",
    "reversed",
    "sizeRange",
    "sizeLabel",
    "colorLabel",
    "heatmapPaint",
    "savedCirclePaint",
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


def clean_paint(paint: dict[str, Any] | None) -> dict[str, Any]:
    """Return MapLibre paint without private GeoLens builder keys."""
    return {
        key: value
        for key, value in dict(paint or {}).items()
        if key not in LEGACY_BUILDER_PAINT_KEYS and not str(key).startswith("_")
    }


def clean_layout(layout: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(layout or {}).items()
        if not str(key).startswith("_") and key != "line-dasharray"
    }


def clean_label_metadata(
    label_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(label_config, dict):
        return None
    clean = {
        key: value
        for key, value in label_config.items()
        if key in _LABEL_METADATA_KEYS and not str(key).startswith("_")
    }
    return clean or None


def clean_symbol_metadata(symbol: Any) -> dict[str, Any] | None:
    if not isinstance(symbol, dict):
        return None
    clean: dict[str, Any] = {}
    for key, value in symbol.items():
        if key not in _SYMBOL_METADATA_KEYS or str(key).startswith("_"):
            continue
        if key == "categories" and isinstance(value, list):
            clean[key] = [
                {
                    entry_key: entry[entry_key]
                    for entry_key in ("value", "icon")
                    if entry_key in entry
                }
                for entry in value
                if isinstance(entry, dict)
            ]
        else:
            clean[key] = value
    return clean or None


def clean_builder_block(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize public builder keys and drop private flags."""
    cleaned: dict[str, Any] = {}
    for sub_key, sub_value in value.items():
        if isinstance(sub_key, str) and sub_key.startswith("_"):
            continue
        key = BUILDER_SNAKE_TO_CAMEL_KEYS.get(sub_key, sub_key)
        if sub_key in BUILDER_SNAKE_TO_CAMEL_KEYS and key in cleaned:
            continue
        cleaned[key] = sub_value
    return cleaned


def clean_style_metadata(
    style_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(style_config, dict):
        return None
    clean: dict[str, Any] = {}
    for key, value in style_config.items():
        if key not in _STYLE_METADATA_KEYS or str(key).startswith("_"):
            continue
        if key == "symbol":
            symbol = clean_symbol_metadata(value)
            if symbol:
                clean[key] = symbol
        elif key == "builder" and isinstance(value, dict):
            builder = clean_builder_block(value)
            if builder:
                clean[key] = builder
        else:
            clean[key] = value
    return clean or None


def builder_style_config(style_config: dict[str, Any] | None) -> dict[str, Any]:
    builder = (style_config or {}).get("builder")
    return clean_builder_block(builder) if isinstance(builder, dict) else {}


def clean_basemap_config(value: Any, *, lenient: bool = False) -> dict | None:
    """Validate basemap metadata, optionally degrading schema skew to ``None``."""
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
        known = {
            key: item
            for key, item in value.items()
            if key in BasemapConfig.model_fields
        }
        try:
            return BasemapConfig.model_validate(known).model_dump(mode="json")
        except ValidationError:
            logger.warning(
                "Dropping malformed stored basemap_config on style export "
                "(degrading to None rather than 500)"
            )
            return None


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def clamp_number(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)
