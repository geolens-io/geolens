"""Labels and popups from a web map layer."""

from __future__ import annotations

import re
from typing import Any

from app.modules.catalog.maps.arcgis_webmap.layout import (
    describe,
    num,
    points_to_px,
    color_to_hex,
    scale_to_zoom,
)
from app.modules.catalog.maps.arcgis_webmap.loss import LossReport

_SIMPLE_EXPRESSIONS = (
    re.compile(r"^\s*\$feature\.([A-Za-z_][A-Za-z0-9_]*)\s*$"),
    re.compile(r"^\s*\$feature\[\s*[\"']([^\"']+)[\"']\s*\]\s*$"),
    re.compile(r"^\s*\[([^\]]+)\]\s*$"),
    re.compile(r"^\s*\{([A-Za-z_][A-Za-z0-9_]*)\}\s*$"),
)
_ANCHORS = {
    "esriServerPointLabelPlacementAboveCenter": "bottom",
    "esriServerPointLabelPlacementBelowCenter": "top",
    "esriServerPointLabelPlacementCenterCenter": "center",
    "esriServerPointLabelPlacementAboveLeft": "bottom-right",
    "esriServerPointLabelPlacementAboveRight": "bottom-left",
    "esriServerPointLabelPlacementBelowLeft": "top-right",
    "esriServerPointLabelPlacementBelowRight": "top-left",
    "esriServerPointLabelPlacementCenterLeft": "right",
    "esriServerPointLabelPlacementCenterRight": "left",
}
_LINE_PLACEMENTS = {
    "esriServerLinePlacementAboveAlong": "line",
    "esriServerLinePlacementBelowAlong": "line",
    "esriServerLinePlacementCenterAlong": "line-center",
}
_MAX_POPUP_FIELDS = 100


def _d(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> list:
    return value if isinstance(value, list) else []


def _label_column(first: dict) -> str | None:
    info = _d(first.get("labelExpressionInfo"))
    expression = (
        info.get("expression") or info.get("value") or first.get("labelExpression")
    )
    if not isinstance(expression, str):
        return None
    for pattern in _SIMPLE_EXPRESSIONS:
        match = pattern.match(expression)
        if match and len(match.group(1)) <= 255:
            return match.group(1)
    return None


def _label_style(first: dict, path: str, loss: LossReport) -> dict:
    config: dict = {}
    symbol = _d(first.get("symbol"))
    font = _d(symbol.get("font"))
    size = num(font.get("size"))
    if size and size > 0:
        config["fontSize"] = min(512.0, points_to_px(size))
    text = color_to_hex(symbol.get("color"))
    if text:
        config["textColor"] = text[0]
    halo = color_to_hex(symbol.get("haloColor"))
    halo_size = num(symbol.get("haloSize"))
    if halo and halo_size and halo_size > 0:
        config["haloColor"] = halo[0]
        config["haloWidth"] = min(20.0, points_to_px(halo_size))
    # A label's minScale is its zoomed-out limit, like a layer's.
    min_zoom = scale_to_zoom(first.get("minScale"))
    max_zoom = scale_to_zoom(first.get("maxScale"))
    if min_zoom:
        config["minZoom"] = min_zoom
    if max_zoom is not None and max_zoom < 24:
        config["maxZoom"] = max_zoom
    placement = first.get("labelPlacement")
    if isinstance(placement, str) and placement in _ANCHORS:
        config["textAnchor"] = _ANCHORS[placement]
    elif isinstance(placement, str) and placement in _LINE_PLACEMENTS:
        config["placement"] = _LINE_PLACEMENTS[placement]
    if font.get("family"):
        loss.add(path, "label_font", describe(font["family"]))
    return config


def label_config(
    layer: dict, drawing_info: dict, path: str, loss: LossReport
) -> dict | None:
    infos = drawing_info.get("labelingInfo")
    if not isinstance(infos, list) or not infos:
        return None
    base = f"{path}.labelingInfo"
    if layer.get("showLabels") is not True:
        loss.add(base, "labels_hidden", "labels are off in the web map")
        return None
    first = _d(infos[0])
    if len(infos) > 1:
        loss.add(base, "label_class", f"{len(infos) - 1} extra classes")
    if first.get("where"):
        loss.add(f"{base}[0]", "label_class", "label class has a filter")
    column = _label_column(first)
    if column is None:
        loss.add(f"{base}[0]", "label_expression", "not a single field")
        return None
    return {"column": column, **_label_style(first, f"{base}[0]", loss)}


def _popup_fields(info: dict, base: str, loss: LossReport) -> list[str] | None:
    fields = info.get("fieldInfos")
    if not isinstance(fields, list) or not fields:
        return None
    visible: list[str] = []
    seen: set[str] = set()
    overflow = relabeled = formatted = computed = 0
    for item in fields:
        item = _d(item)
        name = item.get("fieldName")
        if item.get("visible") is not True or not isinstance(name, str) or not name:
            continue
        if "/" in name:
            computed += 1
            continue
        if len(name) > 128 or name in seen:
            continue
        seen.add(name)
        if len(visible) >= _MAX_POPUP_FIELDS:
            overflow += 1
            continue
        visible.append(name)
        relabeled += item.get("label") not in (None, name)
        formatted += bool(item.get("format"))
    if overflow:
        loss.add(base, "popup_field_cap", f"{overflow} fields")
    if relabeled:
        loss.add(base, "popup_field_label", f"{relabeled} fields use an alias")
    if formatted:
        loss.add(base, "popup_field_format", f"{formatted} fields")
    if computed:
        loss.add(base, "popup_expression", f"{computed} computed or related fields")
    return visible


def popup_config(layer: dict, path: str, loss: LossReport) -> dict | None:
    if layer.get("disablePopup") is True:
        return {"enabled": False}
    info = layer.get("popupInfo")
    if not isinstance(info, dict):
        return None
    base = f"{path}.popupInfo"
    config: dict = {"enabled": True}

    title = info.get("title")
    if isinstance(title, str) and title:
        if "expression/" in title or len(title) > 500:
            loss.add(base, "popup_expression", "title is not a plain field template")
        else:
            config["expression"] = title
    visible = _popup_fields(info, base, loss)
    if visible is not None:
        config["visible_fields"] = visible

    if info.get("mediaInfos"):
        loss.add(base, "popup_media", f"{len(_l(info['mediaInfos']))} items")
    if info.get("description"):
        loss.add(base, "popup_html", "custom description")
    if info.get("showAttachments"):
        loss.add(base, "popup_attachments")
    return config
