"""Assemble a GeoLens map from an ArcGIS web map (item data JSON).

Pure: no database access. The caller supplies the layer-to-dataset matches
(already authorized) and the basemap ids it may use.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.modules.catalog.maps.arcgis_webmap.filter_sql import (
    definition_expression_to_filter,
    is_match_all,
)
from app.modules.catalog.maps.arcgis_webmap.labels import label_config, popup_config
from app.modules.catalog.maps.arcgis_webmap.layout import (
    describe,
    extent_to_view,
    num,
    scale_to_zoom,
)
from app.modules.catalog.maps.arcgis_webmap.loss import LossReport
from app.modules.catalog.maps.arcgis_webmap.renderer import translate_renderer
from app.modules.catalog.maps.schemas import _MAX_LAYERS_PER_MAP, MapLayerInput

DEFAULT_MAP_NAME = "Imported ArcGIS web map"
_MAX_GROUP_DEPTH = 16
_FEATURE_LAYER_TYPES = {"ArcGISFeatureLayer", "FeatureLayer"}


@dataclass
class UnmatchedLayer:
    layer_id: str
    title: str
    url: str
    reason: str


@dataclass
class Translation:
    name: str
    layers: list[MapLayerInput] = field(default_factory=list)
    layer_sources: list[str] = field(default_factory=list)
    unmatched: list[UnmatchedLayer] = field(default_factory=list)
    loss: LossReport = field(default_factory=LossReport)
    basemap_style: str | None = None
    center_lng: float | None = None
    center_lat: float | None = None
    zoom: float | None = None


@dataclass
class _Group:
    id: str
    name: str
    visible: bool
    opacity: float


def _d(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _unit(value: Any) -> float:
    number = num(value)
    return 1.0 if number is None else min(1.0, max(0.0, number))


def _flatten(
    layers: list, loss: LossReport, path: str, group: _Group | None, depth: int
) -> list[tuple[dict, str, _Group | None]]:
    """Operational layers in draw order, group members inlined under their top group."""
    out: list[tuple[dict, str, _Group | None]] = []
    for index, raw in enumerate(layers):
        layer = _d(raw)
        here = f"{path}[{index}]"
        if layer.get("layerType") != "GroupLayer":
            out.append((layer, here, group))
            continue
        if group is not None:
            loss.add(here, "nested_group", _text(layer.get("title"), 80))
        if depth >= _MAX_GROUP_DEPTH:
            loss.add(here, "nested_group", "too deep, layers skipped")
            continue
        current = group or _Group(
            id=_text(layer.get("id"), 120) or here,
            name=_text(layer.get("title"), 255) or "Group",
            visible=layer.get("visibility") is not False,
            opacity=_unit(layer.get("opacity")),
        )
        out.extend(
            _flatten(
                _l(layer.get("layers")), loss, f"{here}.layers", current, depth + 1
            )
        )
    return out


def _zoom_range(layer: dict, definition: dict) -> dict:
    """Layer zoom limits; ArcGIS ``minScale`` is the zoomed-out limit."""
    min_zoom = scale_to_zoom(layer.get("minScale", definition.get("minScale")))
    max_zoom = scale_to_zoom(layer.get("maxScale", definition.get("maxScale")))
    layout: dict = {}
    if min_zoom:
        layout["_minzoom"] = min_zoom
    if max_zoom is not None and max_zoom < 24:
        layout["_maxzoom"] = max_zoom
    return layout


def _filter(definition: dict, path: str, loss: LossReport) -> list | None:
    expression = definition.get("definitionExpression")
    if not isinstance(expression, str) or is_match_all(expression):
        return None
    translated = definition_expression_to_filter(expression)
    if translated is None:
        loss.add(
            f"{path}.layerDefinition.definitionExpression",
            "definition_expression",
            expression,
        )
    return translated


def _layer_input(
    layer: dict,
    path: str,
    dataset_id: uuid.UUID,
    group: _Group | None,
    loss: LossReport,
) -> dict:
    definition = _d(layer.get("layerDefinition"))
    drawing = _d(definition.get("drawingInfo"))
    styled = translate_renderer(
        drawing.get("renderer"),
        f"{path}.layerDefinition.drawingInfo.renderer",
        loss,
        definition.get("geometryType"),
    )

    style_config = styled.style_config
    visible = layer.get("visibility") is not False
    opacity = _unit(layer.get("opacity"))
    if group is not None:
        style_config = dict(style_config or {})
        style_config["builder"] = {
            **style_config.get("builder", {}),
            "folder_group_id": group.id,
            "folder_group_name": group.name,
        }
        visible = visible and group.visible
        opacity *= group.opacity

    return {
        "dataset_id": dataset_id,
        "visible": visible,
        "opacity": round(opacity, 3),
        "display_name": _text(layer.get("title"), 255) or None,
        "paint": styled.paint,
        "layout": _zoom_range(layer, definition) or None,
        "filter": _filter(definition, path, loss),
        "label_config": label_config(
            layer, drawing, f"{path}.layerDefinition.drawingInfo", loss
        ),
        "popup_config": popup_config(layer, path, loss),
        "style_config": style_config,
        "show_in_legend": layer.get("showLegend") is not False,
    }


def _unsupported_type(layer: dict) -> str | None:
    """None for a feature layer, else the layer type to report."""
    layer_type = layer.get("layerType")
    if layer.get("featureCollection") is not None:
        return "featureCollection"
    if isinstance(layer_type, str) and layer_type in _FEATURE_LAYER_TYPES:
        return None
    if layer_type is None and "/FeatureServer" in _text(layer.get("url"), 2000):
        return None
    return describe(layer_type) if layer_type else "unknown"


def _basemap(
    webmap: dict,
    basemap_map: Mapping[str, str],
    available: Sequence[str],
    loss: LossReport,
) -> str | None:
    layers = _l(_d(webmap.get("baseMap")).get("baseMapLayers"))
    if len(layers) > 1:
        loss.add(
            "baseMap.baseMapLayers",
            "basemap_reference_layer",
            f"{len(layers) - 1} layers",
        )
    first = _d(layers[0]) if layers else {}
    key = first.get("url") or first.get("styleUrl")
    target = basemap_map.get(key) if isinstance(key, str) else None
    if target is not None and target in available:
        return target
    loss.add(
        "baseMap.baseMapLayers[0]",
        "basemap",
        _text(first.get("title") or key, 200) or "no basemap",
    )
    return available[0] if available else None


def _extras(webmap: dict, loss: LossReport) -> None:
    for item in _l(webmap.get("tables")):
        loss.add("tables", "table_in_map", _text(_d(item).get("title"), 120))
    if webmap.get("bookmarks"):
        loss.add("bookmarks", "bookmarks", str(len(_l(webmap["bookmarks"]))))
    if webmap.get("timeSlider") or _d(webmap.get("widgets")).get("timeSlider"):
        loss.add("timeSlider", "time")
    if webmap.get("widgets") or _d(webmap.get("applicationProperties")).get("viewing"):
        loss.add("widgets", "widget")


def _viewpoint(webmap: dict, result: Translation) -> None:
    viewpoint = _d(_d(webmap.get("initialState")).get("viewpoint"))
    if not viewpoint:
        return
    try:
        view = extent_to_view(_d(viewpoint.get("targetGeometry")))
    except (ArithmeticError, TypeError, ValueError):
        view = None
    if view is None:
        result.loss.add("initialState.viewpoint", "viewpoint", "extent not usable")
        return
    result.center_lng, result.center_lat, result.zoom = view


def _add_layer(
    result: Translation,
    layer: dict,
    path: str,
    dataset_id: uuid.UUID,
    group: _Group | None,
) -> None:
    scratch = LossReport()
    ref = UnmatchedLayer(
        _text(layer.get("id"), 255),
        _text(layer.get("title"), 255),
        _text(layer.get("url"), 2000),
        "invalid",
    )
    try:
        data = _layer_input(layer, path, dataset_id, group, scratch)
        built = MapLayerInput.model_validate(
            {**data, "sort_order": min(len(result.layers), 32767)}
        )
    except ValidationError as exc:
        result.loss.add(path, "layer_invalid", str(exc.errors()[0].get("msg", "")))
    except Exception as exc:  # broad: hostile portal JSON must report a loss, not a 500
        result.loss.add(path, "layer_invalid", type(exc).__name__)
    else:
        result.loss.merge(scratch)
        result.layers.append(built)
        result.layer_sources.append(ref.layer_id)
        return
    result.unmatched.append(ref)


def translate_webmap(
    webmap: dict,
    *,
    name: str | None,
    dataset_matches: Mapping[str, uuid.UUID],
    basemap_map: Mapping[str, str],
    available_basemaps: Sequence[str],
) -> Translation:
    """Translate ``webmap``; unknown or malformed parts become loss items."""
    result = Translation(name=(name or "").strip()[:255] or DEFAULT_MAP_NAME)
    loss = result.loss

    entries = _flatten(
        _l(webmap.get("operationalLayers")), loss, "operationalLayers", None, 0
    )
    seen_ids: set[str] = set()
    for layer, path, group in entries:
        title = _text(layer.get("title"), 255)
        unsupported = _unsupported_type(layer)
        if unsupported is not None:
            loss.add(path, "unsupported_layer_type", unsupported)
            continue
        layer_id = _text(layer.get("id"), 255)
        if layer_id in seen_ids:
            loss.add(path, "duplicate_layer_id", layer_id)
            continue
        seen_ids.add(layer_id)
        dataset_id = dataset_matches.get(layer_id)
        if dataset_id is None:
            result.unmatched.append(
                UnmatchedLayer(
                    layer_id, title, _text(layer.get("url"), 2000), "no_match"
                )
            )
            loss.add(path, "unmatched_layer", title)
        elif len(result.layers) >= _MAX_LAYERS_PER_MAP:
            loss.add(path, "layer_cap", title)
        else:
            _add_layer(result, layer, path, dataset_id, group)

    result.basemap_style = _basemap(webmap, basemap_map, available_basemaps, loss)
    _viewpoint(webmap, result)
    _extras(webmap, loss)
    return result
