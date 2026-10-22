"""ArcGIS renderers to GeoLens paint and ``style_config``.

``simple`` becomes one paint, ``uniqueValue`` a categorical ``match`` and
``classBreaks`` a graduated ``step``, in the builder's own expression shapes.
Everything else keeps a default paint and is recorded in the loss report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.catalog.maps.arcgis_webmap.layout import (
    describe,
    color_to_hex,
    num,
    points_to_px,
)
from app.modules.catalog.maps.arcgis_webmap.loss import LossReport
from app.modules.catalog.maps.style_json import DEFAULT_FILL_COLOR

NULL_COLOR = "#cccccc"
MAX_CLASSES = 250
_HEATMAP_RAMP = "YlOrRd"

_KIND_BY_SYMBOL = {
    "esriSMS": "point",
    "esriPMS": "point",
    "esriSLS": "line",
    "esriSFS": "fill",
    "esriPFS": "fill",
}
_KIND_BY_GEOMETRY = {
    "esriGeometryPoint": "point",
    "esriGeometryMultipoint": "point",
    "esriGeometryPolyline": "line",
    "esriGeometryPolygon": "fill",
    "esriGeometryEnvelope": "fill",
}
_COLOR_PROP = {"point": "circle-color", "line": "line-color", "fill": "fill-color"}
_OPACITY_PROP = {
    "point": "circle-opacity",
    "line": "line-opacity",
    "fill": "fill-opacity",
}
_DASHES = {
    "esriSLSDash": [4, 2],
    "esriSLSDot": [1, 2],
    "esriSLSDashDot": [4, 2, 1, 2],
}


def _d(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> list:
    return value if isinstance(value, list) else []


@dataclass
class Styled:
    paint: dict | None = None
    style_config: dict | None = None
    geometry: str | None = None


@dataclass
class _Symbol:
    kind: str
    color: str | None
    opacity: float
    paint: dict = field(default_factory=dict)
    builder: dict = field(default_factory=dict)
    picture: bool = False


def geometry_kind(geometry_type: Any) -> str | None:
    return (
        _KIND_BY_GEOMETRY.get(geometry_type) if isinstance(geometry_type, str) else None
    )


def _outline(symbol: dict, path: str, loss: LossReport) -> dict:
    outline = _d(symbol.get("outline"))
    builder: dict = {}
    style = outline.get("style")
    if style == "esriSLSNull":
        builder["stroke_disabled"] = True
        return builder
    if isinstance(style, str) and style != "esriSLSSolid":
        loss.add(f"{path}.outline", "symbol_style", f"outline style {describe(style)}")
    color = color_to_hex(outline.get("color"))
    if color:
        builder["outline_color"] = color[0]
    if num(outline.get("width")) is not None:
        builder["outline_width"] = points_to_px(outline.get("width"))
    return builder


def _symbol(raw: Any, path: str, loss: LossReport) -> _Symbol | None:
    symbol = _d(raw)
    symbol_type = symbol.get("type")
    kind = _KIND_BY_SYMBOL.get(symbol_type) if isinstance(symbol_type, str) else None
    if kind is None:
        loss.add(path, "symbol_style", f"symbol type {describe(symbol_type)}")
        return None
    parsed = color_to_hex(symbol.get("color"))
    result = _Symbol(kind, parsed[0] if parsed else None, parsed[1] if parsed else 1.0)
    style = symbol.get("style")

    if symbol_type == "esriSMS":
        if style not in (None, "esriSMSCircle"):
            loss.add(path, "symbol_style", f"marker style {describe(style)}")
        result.paint["circle-radius"] = max(
            1.0, round(points_to_px(symbol.get("size"), 6) / 2, 2)
        )
        outline = _d(symbol.get("outline"))
        stroke = color_to_hex(outline.get("color"))
        if stroke:
            result.paint["circle-stroke-color"] = stroke[0]
            result.paint["circle-stroke-opacity"] = stroke[1]
        result.paint["circle-stroke-width"] = points_to_px(outline.get("width"))
    elif symbol_type == "esriPMS":
        result.picture = True
        loss.add(path, "picture_marker", "drawn with the built-in marker icon")
        result.paint["circle-radius"] = 5
    elif symbol_type == "esriSLS":
        if style == "esriSLSNull":
            result.opacity = 0.0
        elif isinstance(style, str) and style in _DASHES:
            result.paint["line-dasharray"] = _DASHES[style]
        elif style not in (None, "esriSLSSolid"):
            loss.add(path, "symbol_style", f"line style {describe(style)}")
        result.paint["line-width"] = points_to_px(symbol.get("width"), 1)
    else:
        if symbol_type == "esriPFS":
            loss.add(path, "symbol_style", "picture fill")
        elif style == "esriSFSNull":
            result.builder["fill_disabled"] = True
        elif style not in (None, "esriSFSSolid"):
            loss.add(path, "symbol_style", f"fill style {describe(style)}")
        result.builder.update(_outline(symbol, path, loss))
    return result


def _paint(sym: _Symbol, color: Any) -> dict:
    paint = dict(sym.paint)
    paint[_COLOR_PROP[sym.kind]] = color
    paint[_OPACITY_PROP[sym.kind]] = sym.opacity
    return paint


def _style_config(sym: _Symbol, extra: dict | None = None) -> dict | None:
    config: dict = dict(extra or {})
    if sym.builder:
        config["builder"] = dict(sym.builder)
    if sym.picture:
        config["render_mode"] = "symbol"
        config["symbol"] = {"iconImage": "marker", "iconSize": 1}
    return config or None


def _simple(sym: _Symbol | None, hint: str | None) -> Styled:
    if sym is None:
        return Styled(geometry=hint)
    return Styled(
        _paint(sym, sym.color or DEFAULT_FILL_COLOR), _style_config(sym), sym.kind
    )


def _classes(
    infos: list, path: str, loss: LossReport
) -> tuple[list[tuple[dict, _Symbol | None]], int]:
    """Parsed classes, and how many entries past ``MAX_CLASSES`` were never parsed."""
    skipped = max(0, len(infos) - MAX_CLASSES)
    out = []
    for index, info in enumerate(infos[:MAX_CLASSES]):
        info = _d(info)
        out.append((info, _symbol(info.get("symbol"), f"{path}[{index}].symbol", loss)))
    return out, skipped


def _class_color(sym: _Symbol | None) -> str:
    return (sym.color if sym and sym.color else None) or NULL_COLOR


def _categorical(r: dict, path: str, loss: LossReport, hint: str | None) -> Styled:
    field_name = r.get("field1")
    infos = _l(r.get("uniqueValueInfos"))
    classes, dropped = _classes(infos, f"{path}.uniqueValueInfos", loss)
    default_sym = (
        _symbol(r.get("defaultSymbol"), f"{path}.defaultSymbol", loss)
        if r.get("defaultSymbol")
        else None
    )
    base = default_sym or next((s for _, s in classes if s), None)

    if r.get("field2") or r.get("field3"):
        loss.add(path, "multi_field_renderer", "only field1 is supported")
        return _simple(base, hint)
    if r.get("valueExpression"):
        loss.add(path, "arcade", "valueExpression")
        return _simple(base, hint)
    if not isinstance(field_name, str) or not field_name or base is None:
        loss.add(path, "unsupported_renderer", "uniqueValue without a field or symbols")
        return _simple(base, hint)

    fallback = _class_color(default_sym) if default_sym else NULL_COLOR
    categories: list[dict] = []
    seen: set[str] = set()
    for info, sym in classes:
        value = info.get("value")
        key = None if value is None else str(value)
        if key is None or key in seen or len(categories) >= MAX_CLASSES:
            dropped += 1
            continue
        seen.add(key)
        label = info.get("label")
        categories.append(
            {
                "value": key,
                "label": label if isinstance(label, str) and label else key,
                "color": _class_color(sym),
            }
        )
    if dropped:
        loss.add(path, "renderer_class_dropped", f"{dropped} classes")
    if not categories:
        return _simple(base, hint)

    pairs = [item for c in categories for item in (c["value"], c["color"])]
    expression = [
        "case",
        ["==", ["get", field_name], None],
        fallback,
        ["match", ["to-string", ["get", field_name]], *pairs, fallback],
    ]
    config = _style_config(
        base,
        {"mode": "categorical", "column": field_name, "categories": categories},
    )
    return Styled(_paint(base, expression), config, base.kind)


def _graduated(r: dict, path: str, loss: LossReport, hint: str | None) -> Styled:
    field_name = r.get("field")
    classes, skipped = _classes(
        _l(r.get("classBreakInfos")), f"{path}.classBreakInfos", loss
    )
    ranked = sorted(
        ((num(i.get("classMaxValue")), s) for i, s in classes),
        key=lambda pair: (pair[0] is None, pair[0] or 0.0),
    )
    usable = [(m, s) for m, s in ranked if m is not None]
    base = next((s for _, s in usable if s), None)

    if r.get("normalizationType"):
        loss.add(path, "normalization", describe(r.get("normalizationType")))
        return _simple(next((s for _, s in ranked if s), None), hint)
    if not isinstance(field_name, str) or not field_name or base is None:
        loss.add(path, "unsupported_renderer", "classBreaks without a field or symbols")
        return _simple(next((s for _, s in ranked if s), None), hint)
    if skipped or len(usable) != len(ranked):
        dropped = skipped + len(ranked) - len(usable)
        loss.add(path, "renderer_class_dropped", f"{dropped} classes")
    if len(usable) < 2:
        return _simple(base, hint)

    breaks = [m for m, _ in usable[:-1]]
    colors = [_class_color(s) for _, s in usable]
    step: list = ["step", ["get", field_name], colors[0]]
    for stop, color in zip(breaks, colors[1:]):
        step.extend([stop, color])
    expression = ["case", ["==", ["get", field_name], None], NULL_COLOR, step]
    config = _style_config(
        base,
        {
            "mode": "graduated",
            "column": field_name,
            "method": "manual",
            "classCount": len(colors),
            "breaks": breaks,
            "colors": colors,
        },
    )
    return Styled(_paint(base, expression), config, base.kind)


def _heatmap(r: dict, path: str, loss: LossReport) -> Styled:
    if r.get("colorStops"):
        loss.add(path, "heatmap_ramp", "colour stops replaced by the default ramp")
    radius = num(r.get("blurRadius"))
    paint: dict = {
        "heatmap-radius": max(1.0, points_to_px(radius)) if radius else 30,
        "heatmap-weight": 1,
        "heatmap-intensity": 1,
        "heatmap-opacity": 0.8,
    }
    builder: dict = {"heatmap_ramp": _HEATMAP_RAMP}
    weight = r.get("field")
    if isinstance(weight, str) and weight:
        paint["heatmap-weight"] = ["get", weight]
        builder["heatmap_weight_column"] = weight
    config = {"render_mode": "heatmap", "ramp": _HEATMAP_RAMP, "builder": builder}
    return Styled(paint, config, "point")


def translate_renderer(
    renderer: Any, path: str, loss: LossReport, geometry_type: Any = None
) -> Styled:
    """Paint and style for a layer's renderer; empty when GeoLens defaults apply."""
    hint = geometry_kind(geometry_type)
    r = _d(renderer)
    kind = r.get("type")
    if not r:
        loss.add(path, "renderer_missing", "styling is defined by the service")
        return Styled(geometry=hint)

    if _l(r.get("visualVariables")):
        loss.add(path, "visual_variable", str(len(r["visualVariables"])))

    if kind == "simple":
        return _simple(_symbol(r.get("symbol"), f"{path}.symbol", loss), hint)
    if kind == "uniqueValue":
        return _categorical(r, path, loss, hint)
    if kind == "classBreaks":
        return _graduated(r, path, loss, hint)
    if kind == "heatmap":
        return _heatmap(r, path, loss)
    loss.add(path, "unsupported_renderer", f"renderer type {describe(kind)}")
    return Styled(geometry=hint)
