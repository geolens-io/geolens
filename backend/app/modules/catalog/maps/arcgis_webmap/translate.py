"""Assemble a GeoLens map from an ArcGIS web map (item data JSON).

Pure: no database access. The caller supplies the layer-to-dataset matches
(already authorized) and the basemap ids it may use.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import ValidationError

from app.modules.catalog.maps.arcgis_webmap.fields import FieldNames
from app.modules.catalog.maps.arcgis_webmap.filter_sql import (
    definition_expression_to_filter,
    is_match_all,
)
from app.modules.catalog.maps.arcgis_webmap.keys import (
    DRAWING_INFO_KEYS,
    BASEMAP_KEYS,
    BASEMAP_LAYER_KEYS,
    GROUP_KEYS,
    INITIAL_STATE_KEYS,
    LAYER_DEFINITION_KEYS,
    LAYER_KEYS,
    VIEWPOINT_KEYS,
    WEBMAP_KEYS,
    report_unknown_keys,
)
from app.modules.catalog.maps.arcgis_webmap.labels import label_config, popup_config
from app.modules.catalog.maps.arcgis_webmap.layout import (
    describe,
    extent_to_view,
    is_web_mercator,
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
    bearing: float | None = None


@dataclass(frozen=True)
class _Group:
    """The top group's folder, plus what every enclosing group imposes on a member."""

    id: str
    name: str
    visible: bool
    opacity: float
    min_zoom: float | None = None
    max_zoom: float | None = None
    show_legend: bool = True


def _enter_group(layer: dict, here: str, parent: _Group | None) -> _Group:
    """The state a group's members inherit; nested groups add to their parent's."""
    own_min = scale_to_zoom(layer.get("minScale"))
    own_max = scale_to_zoom(layer.get("maxScale"))
    visible = layer.get("visibility") is not False
    opacity = _unit(layer.get("opacity"))
    show_legend = layer.get("showLegend") is not False
    if parent is None:
        return _Group(
            id=_text(layer.get("id"), 120) or here,
            name=_text(layer.get("title"), 255) or "Group",
            visible=visible,
            opacity=opacity,
            min_zoom=own_min,
            max_zoom=own_max,
            show_legend=show_legend,
        )
    return replace(
        parent,
        visible=parent.visible and visible,
        opacity=parent.opacity * opacity,
        min_zoom=_tighter(parent.min_zoom, own_min, max),
        max_zoom=_tighter(parent.max_zoom, own_max, min),
        show_legend=parent.show_legend and show_legend,
    )


def _tighter(first: float | None, second: float | None, pick) -> float | None:
    values = [v for v in (first, second) if v is not None]
    return pick(values) if values else None


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
        _layer_extras(layer, here, loss)
        report_unknown_keys([layer], GROUP_KEYS, here, loss)
        if group is not None:
            loss.add(here, "nested_group", _text(layer.get("title"), 80))
        if depth >= _MAX_GROUP_DEPTH:
            loss.add(here, "nested_group", "too deep, layers skipped")
            continue
        out.extend(
            _flatten(
                _l(layer.get("layers")),
                loss,
                f"{here}.layers",
                _enter_group(layer, here, group),
                depth + 1,
            )
        )
    return out


def _layer_extras(layer: dict, path: str, loss: LossReport) -> None:
    """Layer settings that change what renders or what the map shows and aren't carried."""
    definition = _d(layer.get("layerDefinition"))
    if layer.get("blendMode") not in (None, "normal") or layer.get("effect"):
        loss.add(path, "layer_effect", "blend mode or effect")
    if layer.get("featureReduction"):
        loss.add(
            path,
            "feature_reduction",
            describe(_d(layer["featureReduction"]).get("type")),
        )
    if layer.get("timeInfo") or definition.get("timeInfo"):
        loss.add(path, "time", "time-aware layer shown without a time filter")
    display_filter = _d(definition.get("displayFilterInfo"))
    disabled = layer.get("disableDisplayFilter") or definition.get(
        "disableDisplayFilter"
    )
    if display_filter and display_filter.get("enabled") is not False and not disabled:
        loss.add(path, "display_filter", "scale-dependent display filter not applied")
    if (num(layer.get("refreshInterval")) or 0) > 0:
        loss.add(path, "refresh_interval", describe(layer.get("refreshInterval")))
    if layer.get("customParameters"):
        loss.add(
            path,
            "custom_parameters",
            ", ".join(sorted(map(describe, _d(layer["customParameters"])))),
        )


def _zoom_range(
    layer: dict, definition: dict, group: _Group | None, path: str, loss: LossReport
) -> dict | None:
    """Layer zoom limits within every enclosing group's; ArcGIS ``minScale`` is the zoomed-out limit.

    None when the limits leave no zoom at which the layer can show.
    """
    min_zoom = scale_to_zoom(layer.get("minScale", definition.get("minScale")))
    max_zoom = scale_to_zoom(layer.get("maxScale", definition.get("maxScale")))
    if group is not None:
        min_zoom = _tighter(min_zoom, group.min_zoom, max)
        max_zoom = _tighter(max_zoom, group.max_zoom, min)
    if min_zoom is not None and max_zoom is not None and min_zoom >= max_zoom:
        loss.add(
            path,
            "scale_range_empty",
            "the layer's and its groups' scale limits never overlap",
        )
        return None
    layout: dict = {}
    if min_zoom:
        layout["_minzoom"] = min_zoom
    if max_zoom is not None and max_zoom < 24:
        layout["_maxzoom"] = max_zoom
    return layout


def _filter(
    definition: dict, path: str, loss: LossReport, fields: FieldNames
) -> list | None:
    expression = definition.get("definitionExpression")
    if not isinstance(expression, str) or is_match_all(expression):
        return None
    translated = definition_expression_to_filter(expression, fields)
    if translated is None:
        loss.add(
            f"{path}.layerDefinition.definitionExpression",
            "definition_expression",
            expression,
        )
    return translated


_NUMERIC_FIELD_KINDS = {
    "esriFieldTypeSmallInteger": "integer",
    "esriFieldTypeInteger": "integer",
    "esriFieldTypeBigInteger": "integer",
    "esriFieldTypeOID": "integer",
    "esriFieldTypeSingle": "single",
    "esriFieldTypeDouble": "float",
}


_NUMERIC_COLUMN_KINDS = {
    "smallint": "integer",
    "integer": "integer",
    "bigint": "integer",
    "numeric": "numeric",
    "real": "single",
    "double precision": "float",
}


def _numeric_fields(
    definition: dict, columns: Sequence[Mapping[str, Any]] | None, fields: FieldNames
) -> dict[str, str]:
    """Numeric kind by column name; the web map's field types win over the
    dataset's, except on a numeric column, whose values read back as decimals."""
    kinds = {
        column["name"]: _NUMERIC_COLUMN_KINDS[column["type"]]
        for column in columns or ()
        if isinstance(column.get("name"), str)
        and column.get("type") in _NUMERIC_COLUMN_KINDS
    }
    for esri in _l(definition.get("fields")):
        if (
            not isinstance(esri, dict)
            or not isinstance(esri.get("name"), str)
            or esri.get("type") not in _NUMERIC_FIELD_KINDS
        ):
            continue
        column = fields.stored(esri["name"]) or esri["name"]
        if kinds.get(column) != "numeric":
            kinds[column] = _NUMERIC_FIELD_KINDS[esri["type"]]
    return kinds


def _layer_input(
    layer: dict,
    path: str,
    dataset_id: uuid.UUID,
    group: _Group | None,
    loss: LossReport,
    columns: Sequence[Mapping[str, Any]] | None = None,
) -> dict:
    definition = _d(layer.get("layerDefinition"))
    drawing = _d(definition.get("drawingInfo"))
    fields = FieldNames(columns, path, loss)
    report_unknown_keys([layer], LAYER_KEYS, path, loss)
    report_unknown_keys(
        [definition], LAYER_DEFINITION_KEYS, f"{path}.layerDefinition", loss
    )
    report_unknown_keys(
        [drawing], DRAWING_INFO_KEYS, f"{path}.layerDefinition.drawingInfo", loss
    )
    styled = translate_renderer(
        drawing.get("renderer"),
        f"{path}.layerDefinition.drawingInfo.renderer",
        loss,
        definition.get("geometryType"),
        _numeric_fields(definition, columns, fields),
        fields,
    )

    style_config = styled.style_config
    visible = layer.get("visibility") is not False
    opacity = _unit(layer.get("opacity"))
    transparency = num(drawing.get("transparency"))
    if transparency:
        opacity *= 1 - min(100.0, max(0.0, transparency)) / 100
    _layer_extras(layer, path, loss)
    if group is not None:
        style_config = dict(style_config or {})
        style_config["builder"] = {
            **style_config.get("builder", {}),
            "folder_group_id": group.id,
            "folder_group_name": group.name,
        }
        visible = visible and group.visible
        opacity *= group.opacity

    zoom_layout = _zoom_range(layer, definition, group, path, loss)
    if zoom_layout is None:
        visible, zoom_layout = False, {}
    return {
        "dataset_id": dataset_id,
        "visible": visible,
        "opacity": round(opacity, 3),
        "display_name": _text(layer.get("title"), 255) or None,
        "paint": styled.paint,
        "layout": zoom_layout or None,
        "filter": _filter(definition, path, loss, fields),
        "label_config": label_config(
            layer, drawing, f"{path}.layerDefinition.drawingInfo", loss, fields
        ),
        "popup_config": popup_config(layer, path, loss, fields),
        "style_config": style_config,
        "show_in_legend": layer.get("showLegend") is not False
        and (group is None or group.show_legend),
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
    base_map = _d(webmap.get("baseMap"))
    layers = _l(base_map.get("baseMapLayers"))
    report_unknown_keys([base_map], BASEMAP_KEYS, "baseMap", loss)
    report_unknown_keys(layers, BASEMAP_LAYER_KEYS, "baseMap.baseMapLayers[]", loss)
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
        opacity = num(first.get("opacity"))
        if first.get("visibility") is False or (opacity is not None and opacity < 1):
            loss.add("baseMap.baseMapLayers[0]", "basemap", "opacity or visibility")
        return target
    loss.add(
        "baseMap.baseMapLayers[0]",
        "basemap",
        _text(first.get("title") or key, 200) or "no basemap",
    )
    return available[0] if available else None


def _extras(webmap: dict, loss: LossReport) -> None:
    reference = webmap.get("spatialReference")
    if reference and not is_web_mercator(reference):
        loss.add("spatialReference", "spatial_reference", "drawn in Web Mercator")
    for item in _l(webmap.get("tables")):
        loss.add("tables", "table_in_map", _text(_d(item).get("title"), 120))
    if webmap.get("bookmarks"):
        loss.add("bookmarks", "bookmarks", str(len(_l(webmap["bookmarks"]))))
    if webmap.get("timeSlider") or _d(webmap.get("widgets")).get("timeSlider"):
        loss.add("timeSlider", "time")
    if webmap.get("widgets") or _d(webmap.get("applicationProperties")).get("viewing"):
        loss.add("widgets", "widget")


def _viewpoint(webmap: dict, result: Translation) -> None:
    state = _d(webmap.get("initialState"))
    report_unknown_keys([state], INITIAL_STATE_KEYS, "initialState", result.loss)
    viewpoint = _d(state.get("viewpoint"))
    if not viewpoint:
        return
    report_unknown_keys(
        [viewpoint], VIEWPOINT_KEYS, "initialState.viewpoint", result.loss
    )
    try:
        view = extent_to_view(_d(viewpoint.get("targetGeometry")))
    except (ArithmeticError, TypeError, ValueError):
        view = None
    if view is None:
        result.loss.add("initialState.viewpoint", "viewpoint", "extent not usable")
        return
    result.center_lng, result.center_lat, result.zoom = view
    rotation = num(viewpoint.get("rotation"))
    if rotation:
        # ArcGIS rotates due north clockwise from the top; a MapLibre bearing is
        # the compass direction at the top, so the two have opposite signs.
        bearing = (-rotation) % 360
        result.bearing = round(bearing - 360 if bearing > 180 else bearing, 2)


def _add_layer(
    result: Translation,
    layer: dict,
    path: str,
    dataset_id: uuid.UUID,
    group: _Group | None,
    columns: Sequence[Mapping[str, Any]] | None,
) -> None:
    scratch = LossReport()
    ref = UnmatchedLayer(
        _text(layer.get("id"), 255),
        _text(layer.get("title"), 255),
        _text(layer.get("url"), 2000),
        "invalid",
    )
    try:
        data = _layer_input(layer, path, dataset_id, group, scratch, columns)
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
    dataset_columns: Mapping[uuid.UUID, Sequence[Mapping[str, Any]]] | None = None,
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
            _add_layer(
                result,
                layer,
                path,
                dataset_id,
                group,
                (dataset_columns or {}).get(dataset_id),
            )

    result.basemap_style = _basemap(webmap, basemap_map, available_basemaps, loss)
    report_unknown_keys([webmap], WEBMAP_KEYS, "webmap", loss)
    _viewpoint(webmap, result)
    _extras(webmap, loss)
    return result
