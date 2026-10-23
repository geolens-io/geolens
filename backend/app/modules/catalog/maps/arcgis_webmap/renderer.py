"""ArcGIS renderers to GeoLens paint and ``style_config``.

``simple`` becomes one paint, ``uniqueValue`` a categorical ``match`` and
``classBreaks`` a graduated ``step``, in the builder's own expression shapes.
Everything else keeps a default paint and is recorded in the loss report.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.catalog.maps.arcgis_webmap.keys import (
    CLASS_BREAK_INFO_KEYS,
    OUTLINE_KEYS,
    RENDERER_KEYS,
    SYMBOL_KEYS,
    UNIQUE_VALUE_INFO_KEYS,
    report_unknown_keys,
)
from app.modules.catalog.maps.arcgis_webmap.layout import (
    describe,
    color_to_hex,
    num,
    points_to_px,
)
from app.modules.catalog.maps.arcgis_webmap.loss import LossReport
from app.modules.catalog.maps.style_json import DEFAULT_FILL_COLOR

NULL_COLOR = "#cccccc"
# ArcGIS leaves features no class or default symbol covers undrawn.
HIDDEN_COLOR = "rgba(0,0,0,0)"
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
    report_unknown_keys([outline], OUTLINE_KEYS, f"{path}.outline", loss)
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
        if color[1] < 1:
            loss.add(f"{path}.outline", "symbol_style", "outline transparency")
    if num(outline.get("width")) is not None:
        builder["outline_width"] = points_to_px(outline.get("width"))
    return builder


def _marker(symbol: dict, result: _Symbol, path: str, loss: LossReport) -> None:
    style = symbol.get("style")
    if style not in (None, "esriSMSCircle"):
        loss.add(path, "symbol_style", f"marker style {describe(style)}")
    result.paint["circle-radius"] = max(
        1.0, round(points_to_px(symbol.get("size"), 6) / 2, 2)
    )
    if any(num(symbol.get(key)) for key in ("angle", "xoffset", "yoffset")):
        loss.add(path, "symbol_style", "marker angle or offset")
    outline = _d(symbol.get("outline"))
    report_unknown_keys([outline], OUTLINE_KEYS, f"{path}.outline", loss)
    outline_style = outline.get("style")
    stroke = color_to_hex(outline.get("color"))
    if stroke:
        result.paint["circle-stroke-color"] = stroke[0]
        result.paint["circle-stroke-opacity"] = stroke[1]
    if outline_style == "esriSLSNull":
        result.paint["circle-stroke-width"] = 0
        return
    if isinstance(outline_style, str) and outline_style != "esriSLSSolid":
        loss.add(
            f"{path}.outline",
            "symbol_style",
            f"outline style {describe(outline_style)}",
        )
    result.paint["circle-stroke-width"] = points_to_px(outline.get("width"))


def _line(symbol: dict, result: _Symbol, path: str, loss: LossReport) -> None:
    style = symbol.get("style")
    if style == "esriSLSNull":
        result.opacity = 0.0
    elif isinstance(style, str) and style in _DASHES:
        result.paint["line-dasharray"] = _DASHES[style]
    elif style not in (None, "esriSLSSolid"):
        loss.add(path, "symbol_style", f"line style {describe(style)}")
    if symbol.get("marker"):
        loss.add(path, "symbol_style", "line end markers")
    result.paint["line-width"] = points_to_px(symbol.get("width"), 1)


def _fill(symbol: dict, result: _Symbol, path: str, loss: LossReport) -> None:
    style = symbol.get("style")
    if symbol.get("type") == "esriPFS":
        loss.add(path, "symbol_style", "picture fill")
    elif style == "esriSFSNull":
        result.builder["fill_disabled"] = True
        result.opacity = 0.0
    elif style not in (None, "esriSFSSolid"):
        loss.add(path, "symbol_style", f"fill style {describe(style)}")
    result.builder.update(_outline(symbol, path, loss))


def _symbol(raw: Any, path: str, loss: LossReport) -> _Symbol | None:
    symbol = _d(raw)
    symbol_type = symbol.get("type")
    kind = _KIND_BY_SYMBOL.get(symbol_type) if isinstance(symbol_type, str) else None
    if kind is None:
        loss.add(path, "symbol_style", f"symbol type {describe(symbol_type)}")
        return None
    report_unknown_keys([symbol], SYMBOL_KEYS[symbol_type], path, loss)
    parsed = color_to_hex(symbol.get("color"))
    result = _Symbol(kind, parsed[0] if parsed else None, parsed[1] if parsed else 1.0)
    if symbol_type == "esriSMS":
        _marker(symbol, result, path, loss)
    elif symbol_type == "esriPMS":
        result.picture = True
        loss.add(path, "picture_marker", "drawn with the built-in marker icon")
        result.paint["circle-radius"] = 5
    elif symbol_type == "esriSLS":
        _line(symbol, result, path, loss)
    else:
        _fill(symbol, result, path, loss)
    return result


def _paint(sym: _Symbol, color: Any, opacity: float | None = None) -> dict:
    paint = dict(sym.paint)
    paint[_COLOR_PROP[sym.kind]] = color
    paint[_OPACITY_PROP[sym.kind]] = sym.opacity if opacity is None else opacity
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
    infos: list, path: str, loss: LossReport, known: frozenset[str]
) -> tuple[list[tuple[dict, _Symbol | None]], int]:
    """Parsed classes, and how many entries past ``MAX_CLASSES`` were never parsed."""
    skipped = max(0, len(infos) - MAX_CLASSES)
    report_unknown_keys(infos[:MAX_CLASSES], known, f"{path}[]", loss)
    out = []
    for index, info in enumerate(infos[:MAX_CLASSES]):
        info = _d(info)
        out.append((info, _symbol(info.get("symbol"), f"{path}[{index}].symbol", loss)))
    return out, skipped


def _class_color(sym: _Symbol | None) -> str:
    return (sym.color if sym and sym.color else None) or NULL_COLOR


def _css_color(sym: _Symbol | None) -> str:
    """A class colour for the paint, carrying the symbol's alpha as rgba."""
    if sym is not None and sym.opacity == 0:
        return HIDDEN_COLOR
    color = _class_color(sym)
    if sym is None or not sym.color or sym.opacity >= 1:
        return color
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({red},{green},{blue},{sym.opacity})"


def _report_labels(
    path: str, loss: LossReport, authored: int = 0, default_label: Any = None
) -> None:
    """Legend labels the saved style has no field for; the legend names classes by range."""
    if isinstance(default_label, str) and default_label.strip():
        authored += 1
    if authored:
        loss.add(path, "class_label", f"{authored} authored legend labels not carried")


def _report_class_differences(
    base: _Symbol, symbols: list[_Symbol | None], path: str, loss: LossReport
) -> None:
    """Classes share the base symbol's size, width, dash and outline; say so."""
    shape = (base.kind, base.paint, base.builder, base.picture)
    differing = sum(
        1
        for sym in symbols
        if sym is not None and (sym.kind, sym.paint, sym.builder, sym.picture) != shape
    )
    if differing:
        loss.add(
            path,
            "symbol_style",
            f"{differing} classes differ from the base symbol in size, width, dash or outline",
        )


def _js_string(value: str | int | float) -> str:
    """The text MapLibre's ``to-string`` gives a value, which the paint ``match`` keys on."""
    if isinstance(value, str):
        return value
    if isinstance(value, int) or (value.is_integer() and abs(value) < 2**53):
        return str(int(value))
    text = repr(value)
    if "e" not in text:
        return text.removesuffix(".0")
    if 1e-6 <= abs(value) < 1e21:
        return format(Decimal(text), "f")
    mantissa, _, exponent = text.partition("e")
    return f"{mantissa}e{exponent[0]}{exponent[1:].lstrip('0')}"


def _typed_value(value: Any, field_kind: str | None) -> str | int | float:
    """A category value as the column stores it; ArcGIS writes numbers as strings.

    A number is used only when it survives the round trip, so values past 2**53
    stay distinct strings.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return str(value)
    if not isinstance(value, str) or field_kind is None:
        return value
    try:
        exact = Decimal(value)
    except InvalidOperation:
        return value
    if not exact.is_finite():
        return value
    if field_kind == "integer":
        if exact.copy_abs() < 2**53 and exact == exact.to_integral_value():
            return int(exact)
        return value
    number = float(exact)
    if field_kind == "numeric":
        # The distinct values endpoint sends a numeric column as a float.
        if not math.isfinite(number):
            return value
    elif field_kind == "single":
        try:
            number = struct.unpack("f", struct.pack("f", number))[0]
        except OverflowError:
            return value
        if not math.isfinite(number):
            return value
    elif Decimal(repr(number)) != exact:
        return value
    return int(number) if number.is_integer() and abs(number) < 2**53 else number


def _categorical(
    r: dict,
    path: str,
    loss: LossReport,
    hint: str | None,
    numeric_fields: dict[str, str] | None = None,
) -> Styled:
    field_name = r.get("field1")
    infos = _l(r.get("uniqueValueInfos"))
    classes, dropped = _classes(
        infos, f"{path}.uniqueValueInfos", loss, UNIQUE_VALUE_INFO_KEYS
    )
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

    fallback = _css_color(default_sym) if default_sym else HIDDEN_COLOR
    if default_sym:
        _report_labels(path, loss, default_label=r.get("defaultLabel"))
    _report_class_differences(
        base, [sym for _, sym in classes] + [default_sym], path, loss
    )
    categories: list[dict] = []
    pairs: list[str] = []
    seen: set[str] = set()
    for info, sym in classes:
        value = info.get("value")
        key = None if value is None else str(value)
        if key is None or len(categories) >= MAX_CLASSES:
            dropped += 1
            continue
        typed = _typed_value(value, (numeric_fields or {}).get(field_name))
        paint_key = _js_string(typed)
        if paint_key in seen:
            dropped += 1
            continue
        seen.add(paint_key)
        label = info.get("label")
        categories.append(
            {
                "value": typed,
                "label": label if isinstance(label, str) and label else key,
                "color": _class_color(sym),
            }
        )
        pairs += [paint_key, _css_color(sym)]
    if dropped:
        loss.add(path, "renderer_class_dropped", f"{dropped} classes")
    if not categories:
        return _simple(base, hint)

    expression = [
        "case",
        ["==", ["get", field_name], None],
        fallback,
        ["match", ["to-string", ["get", field_name]], *pairs, fallback],
    ]
    config = _style_config(
        base,
        {
            "mode": "categorical",
            "column": field_name,
            "categories": categories,
            "ramp": "custom",
        },
    )
    return Styled(_paint(base, expression, 1.0), config, base.kind)


def _has_gap(usable: list) -> bool:
    return any(
        low is not None and low > previous
        for (previous, _, _), (_, low, _) in zip(usable, usable[1:])
    )


def _graduated_expression(
    field_name: str, breaks: list[float], colors: list[str], fallback: str
) -> list:
    """The builder's null-guarded colour step, which its editor and legend read."""
    step: list = ["step", ["get", field_name], colors[0]]
    for stop, color in zip(breaks, colors[1:]):
        step.extend([stop, color])
    return ["case", ["==", ["get", field_name], None], fallback, step]


def _single_class(field_name: str, only: tuple, base: _Symbol, fallback: str) -> Styled:
    """One class: its colour inside its range, the default (or nothing) elsewhere."""
    high, low, symbol = only
    value = ["get", field_name]
    inside: list = ["<=", value, high]
    if low is not None:
        inside = ["all", [">=", value, low], inside]
    expression = [
        "case",
        ["==", value, None],
        fallback,
        inside,
        _css_color(symbol),
        fallback,
    ]
    return Styled(_paint(base, expression, 1.0), _style_config(base), base.kind)


def _tighten_separators(label: str) -> str:
    """``label`` without whitespace next to ``-``, ``<`` or ``<=``, in one pass."""
    out: list[str] = []
    i = 0
    while i < len(label):
        if not label[i].isspace():
            out.append(label[i])
            i += 1
            continue
        j = i
        while j < len(label) and label[j].isspace():
            j += 1
        after_separator = bool(out) and (
            out[-1] in "<-" or (out[-1] == "=" and len(out) > 1 and out[-2] == "<")
        )
        if not after_separator and not (j < len(label) and label[j] in "<-"):
            out.append(label[i:j])
        i = j
    return "".join(out)


def _authored_break_labels(classes: list, renderer_min: float | None) -> int:
    """Class-break labels that differ from the range ArcGIS generates for the class."""
    ordered = sorted(
        (
            (num(info.get("classMaxValue")), num(info.get("classMinValue")), info)
            for info, _ in classes
        ),
        key=lambda item: (item[0] is None, item[0] or 0.0),
    )
    authored = 0
    previous = renderer_min
    for index, (high, low, info) in enumerate(ordered):
        label = info.get("label")
        low = previous if low is None else low
        previous = high
        if not isinstance(label, str) or not label.strip():
            continue
        generated = set()
        if high is not None:
            if index == 0:
                generated = {f"<{high:g}", f"<={high:g}"}
            if low is not None:
                generated.add(f"{low:g}-{high:g}")
        if _tighten_separators(label.strip()) not in generated:
            authored += 1
    return authored


def _graduated(r: dict, path: str, loss: LossReport, hint: str | None) -> Styled:
    field_name = r.get("field")
    classes, skipped = _classes(
        _l(r.get("classBreakInfos")),
        f"{path}.classBreakInfos",
        loss,
        CLASS_BREAK_INFO_KEYS,
    )
    ranked = sorted(
        (
            (num(i.get("classMaxValue")), num(i.get("classMinValue")), s)
            for i, s in classes
        ),
        key=lambda item: (item[0] is None, item[0] or 0.0),
    )
    if ranked and ranked[0][1] is None:
        first = ranked[0]
        ranked[0] = (first[0], num(r.get("minValue")), first[2])
    usable = [item for item in ranked if item[0] is not None]
    base = next((s for _, _, s in usable if s), None)

    if r.get("normalizationType"):
        loss.add(path, "normalization", describe(r.get("normalizationType")))
        return _simple(next((s for _, _, s in ranked if s), None), hint)
    if not isinstance(field_name, str) or not field_name or base is None:
        loss.add(path, "unsupported_renderer", "classBreaks without a field or symbols")
        return _simple(next((s for _, _, s in ranked if s), None), hint)
    distinct = [
        item
        for index, item in enumerate(usable)
        if index == 0 or item[0] != usable[index - 1][0]
    ]
    if skipped or len(distinct) != len(ranked):
        dropped = skipped + len(ranked) - len(distinct)
        loss.add(path, "renderer_class_dropped", f"{dropped} classes")
    usable = distinct
    default = (
        _symbol(r["defaultSymbol"], f"{path}.defaultSymbol", loss)
        if r.get("defaultSymbol")
        else None
    )
    fallback = _css_color(default) if default else HIDDEN_COLOR
    authored = _authored_break_labels(classes, num(r.get("minValue")))
    _report_labels(path, loss, authored, r.get("defaultLabel") if default else None)
    _report_class_differences(
        base, [sym for _, _, sym in usable] + [default], path, loss
    )
    if len(usable) < 2:
        loss.add(
            path,
            "class_single",
            "one class is drawn as a fixed rule, not as editable class breaks",
        )
        return _single_class(field_name, usable[0], base, fallback)
    colors = [_class_color(s) for _, _, s in usable]
    paint_colors = [_css_color(s) for _, _, s in usable]
    breaks = [m for m, _, _ in usable[:-1]]
    expression = _graduated_expression(
        field_name,
        breaks,
        paint_colors,
        fallback,
    )
    loss.add(
        path,
        "class_range",
        "values outside the class ranges take the first or last class colour",
    )
    # A step starts each class at its break, so a value equal to a class maximum
    # takes the next class, and gaps between classes take the following colour.
    loss.add(
        path, "class_boundary", "a value equal to a class maximum takes the next class"
    )
    if _has_gap(usable):
        loss.add(
            path, "class_gap", "values between classes take the next class's colour"
        )
    config = _style_config(
        base,
        {
            "mode": "graduated",
            "column": field_name,
            "method": "manual",
            "classCount": len(colors),
            "breaks": breaks,
            "colors": colors,
            "ramp": "custom",
            "nullColor": fallback,
        },
    )
    return Styled(_paint(base, expression, 1.0), config, base.kind)


def _heatmap(r: dict, path: str, loss: LossReport) -> Styled:
    if r.get("colorStops"):
        loss.add(path, "heatmap_ramp", "colour stops replaced by the default ramp")
    if r.get("minPixelIntensity") or r.get("maxPixelIntensity"):
        loss.add(path, "heatmap_ramp", "pixel intensity range not carried")
    radius = num(r.get("blurRadius"))
    paint: dict = {
        "heatmap-radius": max(1.0, radius) if radius else 30,
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
    renderer: Any,
    path: str,
    loss: LossReport,
    geometry_type: Any = None,
    numeric_fields: dict[str, str] | None = None,
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
    if isinstance(kind, str) and kind in RENDERER_KEYS:
        report_unknown_keys([r], RENDERER_KEYS[kind], path, loss)
    if r.get("rotationType") or r.get("rotationExpression"):
        loss.add(path, "visual_variable", "rotation")

    if kind == "simple":
        _report_labels(path, loss, default_label=r.get("label"))
        return _simple(_symbol(r.get("symbol"), f"{path}.symbol", loss), hint)
    if kind == "uniqueValue":
        return _categorical(r, path, loss, hint, numeric_fields)
    if kind == "classBreaks":
        return _graduated(r, path, loss, hint)
    if kind == "heatmap":
        return _heatmap(r, path, loss)
    loss.add(path, "unsupported_renderer", f"renderer type {describe(kind)}")
    return Styled(geometry=hint)
