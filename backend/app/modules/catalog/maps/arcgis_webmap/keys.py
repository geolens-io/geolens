"""Keys the translator reads, or deliberately ignores, on each ArcGIS object.

A key outside both sets is reported as ``unsupported_property`` (names only,
never values), so a property the translator doesn't know about can't vanish
silently. The sets below list what each object handles or ignores on purpose.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.modules.catalog.maps.arcgis_webmap.loss import LossReport

_MAX_NAMES = 12


def _set(*names: str) -> frozenset[str]:
    return frozenset(names)


# Identity and bookkeeping that changes neither rendering nor the map's content.
_BOOKKEEPING = _set("id", "itemId", "layerType", "title", "url", "type", "name")

LAYER_KEYS = _BOOKKEEPING | _set(
    "visibility",
    "opacity",
    "minScale",
    "maxScale",
    "layerDefinition",
    "popupInfo",
    "disablePopup",
    "showLabels",
    "showLegend",
    "blendMode",
    "effect",
    "featureReduction",
    "timeInfo",
    "refreshInterval",
    "customParameters",
    "featureCollection",
    "disableDisplayFilter",
)
# A group applies its visibility, opacity, scale range and legend flag to its
# members; popups, labels and layer definitions don't apply to a group.
GROUP_KEYS = _BOOKKEEPING | _set(
    "visibility",
    "opacity",
    "minScale",
    "maxScale",
    "showLegend",
    "layers",
    "blendMode",
    "effect",
    "featureReduction",
    "timeInfo",
    "refreshInterval",
    "customParameters",
)
LAYER_DEFINITION_KEYS = _BOOKKEEPING | _set(
    "definitionExpression",
    "drawingInfo",
    "geometryType",
    "minScale",
    "maxScale",
    "timeInfo",
    "displayFilterInfo",
    "disableDisplayFilter",
    # Schema that the dataset already carries.
    "objectIdField",
    "globalIdField",
    "typeIdField",
    "displayField",
    "templates",
    "fields",
    "hasAttachments",
    "capabilities",
)
DRAWING_INFO_KEYS = _set(
    "renderer",
    "labelingInfo",
    "transparency",
    # Symbol sizing behaviour with map scale, not a style choice.
    "scaleSymbols",
    "fixedSymbolSize",
)

_RENDERER_COMMON = _set(
    "type",
    "visualVariables",
    "rotationType",
    "rotationExpression",
    "authoringInfo",
    "label",
    "description",
)
RENDERER_KEYS: dict[str, frozenset[str]] = {
    "simple": _RENDERER_COMMON | _set("symbol"),
    "uniqueValue": _RENDERER_COMMON
    | _set(
        "field1",
        "field2",
        "field3",
        "fieldDelimiter",
        "valueExpression",
        "valueExpressionTitle",
        "defaultSymbol",
        "defaultLabel",
        "uniqueValueInfos",
    ),
    "classBreaks": _RENDERER_COMMON
    | _set(
        "field",
        "normalizationType",
        "normalizationField",
        "normalizationTotal",
        "classificationMethod",
        "minValue",
        "classBreakInfos",
        "defaultSymbol",
        "defaultLabel",
    ),
    "heatmap": _RENDERER_COMMON
    | _set(
        "field", "blurRadius", "colorStops", "minPixelIntensity", "maxPixelIntensity"
    ),
}
UNIQUE_VALUE_INFO_KEYS = _set("value", "label", "symbol", "description")
CLASS_BREAK_INFO_KEYS = _set(
    "classMinValue", "classMaxValue", "label", "symbol", "description"
)

_OUTLINE = _set("type", "color", "width", "style", "marker")
OUTLINE_KEYS = _OUTLINE
_PICTURE = _set(
    "type", "url", "imageData", "contentType", "width", "height", "angle", "color",
    "xoffset", "yoffset", "xscale", "yscale",
)  # fmt: skip
SYMBOL_KEYS: dict[str, frozenset[str]] = {
    "esriSMS": _set("type", "color", "size", "angle", "xoffset", "yoffset", "style", "outline"),
    "esriSLS": _OUTLINE,
    "esriSFS": _set("type", "color", "style", "outline"),
    "esriPMS": _PICTURE,
    "esriPFS": _PICTURE | _set("outline"),
}  # fmt: skip

LABEL_CLASS_KEYS = _set(
    "labelExpressionInfo",
    "labelExpression",
    "labelPlacement",
    "minScale",
    "maxScale",
    "symbol",
    "where",
    "name",
    "useCodedValues",
)
LABEL_SYMBOL_KEYS = _set(
    "type",
    "color",
    "font",
    "haloColor",
    "haloSize",
    "angle",
    "xoffset",
    "yoffset",
    "backgroundColor",
    "borderLineColor",
    # Alignment is carried by the placement anchor, the rest is text shaping.
    "borderLineSize",
    "horizontalAlignment",
    "verticalAlignment",
    "kerning",
    "rightToLeft",
    "rotated",
    "text",
)
POPUP_INFO_KEYS = _set(
    "title",
    "fieldInfos",
    "description",
    "mediaInfos",
    "showAttachments",
    "popupElements",
    "expressionInfos",
    "relatedRecordsInfo",
)
POPUP_FIELDS_ELEMENT_KEYS = _set("type", "fieldInfos")


WEBMAP_KEYS = _set(
    "operationalLayers",
    "baseMap",
    "initialState",
    "tables",
    "bookmarks",
    "timeSlider",
    "widgets",
    "spatialReference",
    # Authoring metadata and app-level settings that don't change the map's content.
    "version",
    "authoringApp",
    "authoringAppVersion",
    "applicationProperties",
)
INITIAL_STATE_KEYS = _set("viewpoint")
# The extent decides the view, so the scale it implies is not read separately.
VIEWPOINT_KEYS = _set("targetGeometry", "rotation", "scale")
BASEMAP_KEYS = _set("baseMapLayers", "title")
BASEMAP_LAYER_KEYS = _BOOKKEEPING | _set(
    "styleUrl", "opacity", "visibility", "isReference"
)


def report_unknown_keys(
    objects: Iterable[object], known: frozenset[str], path: str, loss: LossReport
) -> None:
    """One ``unsupported_property`` item naming the keys no set above covers."""
    unknown: set[str] = set()
    for obj in objects:
        if isinstance(obj, dict):
            unknown.update(key for key in obj if key not in known)
    if not unknown:
        return
    names = sorted(name[:40] for name in unknown)
    more = len(names) - _MAX_NAMES
    detail = ", ".join(names[:_MAX_NAMES]) + (f" and {more} more" if more > 0 else "")
    loss.add(path, "unsupported_property", detail)
