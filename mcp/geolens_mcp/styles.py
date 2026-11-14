# SPDX-License-Identifier: Apache-2.0
"""Layer styles the map authoring tools write, in the map builder's shape.

Hand-maintained port of the builder's style editor (``DataDrivenStyleEditor``,
``lib/color-ramps.ts``, ``lib/classification.ts``), so a map styled here opens
in the builder as if it had been styled there. Pure functions: the caller
fetches column values and statistics and hands them in.
"""

from __future__ import annotations

import copy
import itertools
import math
import re
from dataclasses import dataclass
from typing import Any, Optional

FALLBACK_COLOR = "#cccccc"
DEFAULT_CATEGORY_RAMP = "Set2"
DEFAULT_CLASS_RAMP = "YlOrRd"
DEFAULT_CLASS_COUNT = 5
MIN_CLASS_COUNT = 3
MAX_CLASS_COUNT = 9
CLASS_METHODS = ("equal_interval", "quantile", "jenks", "std_dev")
# The values route serves at most this page by default; one more tells us the
# column has more values than the builder would colour.
MAX_CATEGORIES = 100

# fmt: off
_BREWER_STOPS: dict[str, tuple[str, ...]] = {
    "YlOrRd": ("#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#bd0026", "#800026"),
    "YlGnBu": ("#ffffd9", "#edf8b1", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#253494", "#081d58"),
    "Viridis": ("#440154", "#482777", "#3f4a8a", "#31678e", "#26838f", "#1f9d8a", "#6cce5a", "#b6de2b", "#fee825"),
    "Blues": ("#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"),
    "Greens": ("#f7fcf5", "#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#006d2c", "#00441b"),
    "Oranges": ("#fff5eb", "#fee6ce", "#fdd0a2", "#fdae6b", "#fd8d3c", "#f16913", "#d94801", "#a63603", "#7f2704"),
    "Reds": ("#fff5f0", "#fee0d2", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#a50f15", "#67000d"),
    "Purples": ("#fcfbfd", "#efedf5", "#dadaeb", "#bcbddc", "#9e9ac8", "#807dba", "#6a51a3", "#54278f", "#3f007d"),
    "BuGn": ("#f7fcfd", "#e5f5f9", "#ccece6", "#99d8c9", "#66c2a4", "#41ae76", "#238b45", "#006d2c", "#00441b"),
    "BuPu": ("#f7fcfd", "#e0ecf4", "#bfd3e6", "#9ebcda", "#8c96c6", "#8c6bb1", "#88419d", "#810f7c", "#4d004b"),
    "OrRd": ("#fff7ec", "#fee8c8", "#fdd49e", "#fdbb84", "#fc8d59", "#ef6548", "#d7301f", "#b30000", "#7f0000"),
    "YlGn": ("#ffffe5", "#f7fcb9", "#d9f0a3", "#addd8e", "#78c679", "#41ab5d", "#238443", "#006837", "#004529"),
    "RdYlBu": ("#a50026", "#d73027", "#f46d43", "#fdae61", "#fee090", "#ffffbf", "#e0f3f8", "#abd9e9", "#74add1", "#4575b4", "#313695"),
    "RdYlGn": ("#a50026", "#d73027", "#f46d43", "#fdae61", "#fee08b", "#ffffbf", "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837"),
    "RdBu": ("#67001f", "#b2182b", "#d6604d", "#f4a582", "#fddbc7", "#f7f7f7", "#d1e5f0", "#92c5de", "#4393c3", "#2166ac", "#053061"),
    "BrBG": ("#543005", "#8c510a", "#bf812d", "#dfc27d", "#f6e8c3", "#f5f5f5", "#c7eae5", "#80cdc1", "#35978f", "#01665e", "#003c30"),
    "PiYG": ("#8e0152", "#c51b7d", "#de77ae", "#f1b6da", "#fde0ef", "#f7f7f7", "#e6f5d0", "#b8e186", "#7fbc41", "#4d9221", "#276419"),
    "PRGn": ("#40004b", "#762a83", "#9970ab", "#c2a5cf", "#e7d4e8", "#f7f7f7", "#d9f0d3", "#a6dba0", "#5aae61", "#1b7837", "#00441b"),
    "Spectral": ("#9e0142", "#d53e4f", "#f46d43", "#fdae61", "#fee08b", "#ffffbf", "#e6f598", "#abdda4", "#66c2a5", "#3288bd", "#5e4fa2"),
    "Set1": ("#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00", "#ffff33", "#a65628", "#f781bf", "#999999"),
    "Set2": ("#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854", "#ffd92f", "#e5c494", "#b3b3b3"),
    "Set3": ("#8dd3c7", "#ffffb3", "#bebada", "#fb8072", "#80b1d3", "#fdb462", "#b3de69", "#fccde5", "#d9d9d9", "#bc80bd", "#ccebc5", "#ffed6f"),
    "Paired": ("#a6cee3", "#1f78b4", "#b2df8a", "#33a02c", "#fb9a99", "#e31a1c", "#fdbf6f", "#ff7f00", "#cab2d6", "#6a3d9a", "#ffff99", "#b15928"),
    "Dark2": ("#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d", "#666666"),
    "Accent": ("#7fc97f", "#beaed4", "#fdc086", "#ffff99", "#386cb0", "#f0027f", "#bf5b17", "#666666"),
    "Pastel1": ("#fbb4ae", "#b3cde3", "#ccebc5", "#decbe4", "#fed9a6", "#ffffcc", "#e5d8bd", "#fddaec", "#f2f2f2"),
    "Pastel2": ("#b3e2cd", "#fdcdac", "#cbd5e8", "#f4cae4", "#e6f5c9", "#fff2ae", "#f1e2cc", "#cccccc"),
}
# fmt: on
_QUALITATIVE = frozenset(
    {"set1", "set2", "set3", "paired", "dark2", "accent", "pastel1", "pastel2"}
)
_STOPS_BY_LOWER = {name.lower(): stops for name, stops in _BREWER_STOPS.items()}
RAMP_NAMES = tuple(_BREWER_STOPS)

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
# The style editor's own type tests (DataDrivenStyleEditor and column-utils).
_TEXT_TYPE_PARTS = ("character", "text", "varchar", "char")
_BOOLEAN_TYPES = frozenset({"boolean", "bool"})
_INTEGER_TYPES = frozenset(
    {
        "smallint",
        "integer",
        "bigint",
        "int",
        "int2",
        "int4",
        "int8",
        "serial",
        "smallserial",
        "bigserial",
    }
)
_NUMERIC_TYPES = frozenset(
    {
        "integer",
        "numeric",
        "real",
        "double",
        "float",
        "bigint",
        "smallint",
        "int4",
        "int8",
        "int2",
        "float4",
        "float8",
        "double precision",
        "int",
        "serial",
        "bigserial",
    }
)


def _js_round(value: float) -> int:
    return math.floor(value + 0.5)


def _round2(value: float) -> float:
    rounded = math.floor(value * 100 + 0.5) / 100
    return int(rounded) if rounded == int(rounded) else rounded


def _sample_stops(stops: tuple[str, ...], t: float) -> str:
    n = len(stops)
    if t <= 0:
        return stops[0]
    if t >= 1:
        return stops[-1]
    k = 0
    while t >= (k + 1) / (n - 1):
        k += 1
    k = min(k, n - 2)
    f = (t - k / (n - 1)) / ((k + 1) / (n - 1) - k / (n - 1))
    low = [int(stops[k][i : i + 2], 16) for i in (1, 3, 5)]
    high = [int(stops[k + 1][i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(
        f"{_js_round(a + (b - a) * f):02x}" for a, b in zip(low, high, strict=True)
    )


def ramp_colors(ramp: str, count: int) -> list[str]:
    """``count`` colours of a named ramp, as the builder's ``getRampColors``."""
    lower = ramp.lower()
    stops = _STOPS_BY_LOWER.get(lower, _BREWER_STOPS["YlOrRd"])
    if lower in _QUALITATIVE:
        return [stops[i % len(stops)] for i in range(count)]
    if count == 1:
        return [_sample_stops(stops, 0.5)]
    return [_sample_stops(stops, i / (count - 1)) for i in range(count)]


def equal_interval_breaks(low: float, high: float, count: int) -> list[float]:
    if count < 2:
        return []
    step = (high - low) / count
    return [_round2(low + step * i) for i in range(1, count)]


def std_dev_breaks(mean: float, stddev: float, count: int) -> list[float]:
    if count < 2 or not math.isfinite(stddev) or stddev <= 0:
        return []
    if not math.isfinite(mean):
        return []
    b = count - 1
    return [_round2(mean + stddev * (i - (b - 1) / 2)) for i in range(b)]


def jenks_breaks(values: list[float], count: int) -> list[float]:
    """Fisher-Jenks natural breaks over ``values``, as the builder's ``jenksBreaks``."""
    if count < 2 or not values:
        return []
    ordered = sorted(v for v in values if math.isfinite(v))
    if not ordered:
        return []
    low, high = ordered[0], ordered[-1]
    if len(ordered) < 2 or low == high:
        return equal_interval_breaks(low, high, count)
    k = min(count, len(ordered))
    n = len(ordered)
    lower_limits = [[0] * (k + 1) for _ in range(n + 1)]
    variances = [[0.0] * (k + 1) for _ in range(n + 1)]
    for j in range(1, k + 1):
        lower_limits[1][j] = 1
        variances[1][j] = 0.0
        for i in range(2, n + 1):
            variances[i][j] = math.inf
    for last in range(2, n + 1):
        total = 0.0
        squares = 0.0
        weight = 0
        variance = 0.0
        for m in range(1, last + 1):
            lower = last - m + 1
            value = ordered[lower - 1]
            weight += 1
            total += value
            squares += value * value
            variance = squares - (total * total) / weight
            prior = lower - 1
            if prior != 0:
                for j in range(2, k + 1):
                    if variances[last][j] >= variance + variances[prior][j - 1]:
                        lower_limits[last][j] = lower
                        variances[last][j] = variance + variances[prior][j - 1]
        lower_limits[last][1] = 1
        variances[last][1] = variance
    breaks: list[float] = []
    remaining = n
    for j in range(k, 1, -1):
        breaks.append(_round2(ordered[lower_limits[remaining][j] - 1]))
        remaining = lower_limits[remaining][j] - 1
    breaks.reverse()
    return list(dict.fromkeys(breaks))


def color_property(geometry_type: Optional[str]) -> str:
    """The paint property a layer of this geometry takes its colour from."""
    gt = (geometry_type or "").upper()
    if "POINT" in gt:
        return "circle-color"
    if "LINE" in gt:
        return "line-color"
    return "fill-color"


def _size_properties(geometry_type: Optional[str]) -> dict[str, float]:
    gt = (geometry_type or "").lower().replace("multi", "")
    if "point" in gt:
        return {"circle-radius": 5}
    if "line" in gt:
        return {"line-width": 2}
    return {}


def categorical_expression(
    column: str,
    pairs: list[tuple[Any, str]],
    fallback: str = FALLBACK_COLOR,
    as_string: bool = False,
) -> Any:
    if not pairs:
        return fallback
    source: list[Any] = ["get", column]
    match: list[Any] = ["match", ["to-string", source] if as_string else source]
    for value, color in pairs:
        match.extend((value, color))
    match.append(fallback)
    return ["case", ["==", ["get", column], None], fallback, match]


def graduated_expression(
    column: str, breaks: list[float], outputs: list[Any], null_output: Any
) -> list[Any]:
    step: list[Any] = ["step", ["get", column], outputs[0]]
    for value, output in zip(breaks, outputs[1:], strict=True):
        step.extend((value, output))
    return ["case", ["==", ["get", column], None], null_output, step]


def _is_text(column_type: str) -> bool:
    lowered = column_type.lower()
    return any(part in lowered for part in _TEXT_TYPE_PARTS)


def is_boolean(column_type: str) -> bool:
    return column_type.lower() in _BOOLEAN_TYPES


def suits_categories(column_type: str) -> bool:
    lowered = column_type.lower()
    return _is_text(lowered) or is_boolean(lowered) or lowered in _INTEGER_TYPES


def suits_classes(column_type: str) -> bool:
    return column_type.lower() in _NUMERIC_TYPES


@dataclass(frozen=True)
class StyleRequest:
    """A validated ``style`` argument."""

    type: str
    color: Optional[str] = None
    column: Optional[str] = None
    column_type: Optional[str] = None
    ramp: Optional[str] = None
    colors: Optional[tuple[str, ...]] = None
    method: Optional[str] = None
    count: Optional[int] = None
    breaks: Optional[tuple[float, ...]] = None


def _hex(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _HEX_COLOR.match(value):
        raise ValueError(f"{where} must be a hex colour such as #3388ff: {value!r}")
    return value.lower()


def _colors(value: Any) -> tuple[Optional[str], Optional[tuple[str, ...]]]:
    """Split ``colors`` into a ramp name or an explicit colour list."""
    if value is None:
        return None, None
    if isinstance(value, str):
        canonical = next((n for n in RAMP_NAMES if n.lower() == value.lower()), None)
        if canonical is None:
            raise ValueError(
                f"Unknown colour ramp {value!r}. Use one of: {', '.join(RAMP_NAMES)}, "
                "or a list of hex colours"
            )
        return canonical, None
    if isinstance(value, list) and value:
        return None, tuple(_hex(c, "Each colour") for c in value)
    raise ValueError("colors must be a ramp name or a non-empty list of hex colours")


def _number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


_STYLE_KEYS = {
    "single": {"type", "color"},
    "categories": {"type", "column", "colors"},
    "classes": {"type", "column", "colors", "method", "count", "breaks"},
}


def parse_style(style: dict[str, Any], columns: dict[str, str]) -> StyleRequest:
    """Validate a ``style`` argument against the dataset's columns (name -> type)."""
    kind = style.get("type")
    if kind not in _STYLE_KEYS:
        raise ValueError('style.type must be "single", "categories" or "classes"')
    unknown = sorted(set(style) - _STYLE_KEYS[kind])
    if unknown:
        raise ValueError(f"A {kind} style doesn't take: {', '.join(unknown)}")
    if kind == "single":
        return StyleRequest(type=kind, color=_hex(style.get("color"), "style.color"))

    column = style.get("column")
    if not isinstance(column, str) or column not in columns:
        raise ValueError(
            f"Column {column!r} is not in this dataset. Columns: "
            + ", ".join(sorted(columns))
        )
    column_type = columns[column]
    ramp, colors = _colors(style.get("colors"))
    if kind == "categories":
        if not suits_categories(column_type):
            raise ValueError(
                f"Column {column!r} is {column_type}; categories need a text, "
                "boolean or integer column. Use classes for other numbers."
            )
        return StyleRequest(
            type=kind,
            column=column,
            column_type=column_type,
            ramp=ramp,
            colors=colors,
        )

    if not suits_classes(column_type):
        raise ValueError(
            f"Column {column!r} is {column_type}; classes need a numeric column. "
            "Use categories for text."
        )
    method = style.get("method")
    count = style.get("count")
    breaks = style.get("breaks")
    if breaks is not None:
        if method not in (None, "manual") or count is not None:
            raise ValueError("Give breaks, or a method and count, not both")
        if not isinstance(breaks, list) or not breaks or not all(map(_number, breaks)):
            raise ValueError("breaks must be a non-empty list of numbers")
        if any(b < a for a, b in itertools.pairwise(breaks)):
            raise ValueError("breaks must be in ascending order")
        unique = tuple(dict.fromkeys(breaks))
        return StyleRequest(
            type=kind,
            column=column,
            column_type=column_type,
            ramp=ramp,
            colors=colors,
            method="manual",
            breaks=unique,
        )
    method = method or "equal_interval"
    if method not in CLASS_METHODS:
        raise ValueError(f"method must be one of: {', '.join(CLASS_METHODS)}")
    if count is not None and method == "quantile":
        raise ValueError("quantile always makes five classes; leave out count")
    if count is None:
        count = DEFAULT_CLASS_COUNT
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError("count must be a whole number")
    if not MIN_CLASS_COUNT <= count <= MAX_CLASS_COUNT:
        raise ValueError(f"count must be {MIN_CLASS_COUNT} to {MAX_CLASS_COUNT}")
    return StyleRequest(
        type=kind,
        column=column,
        column_type=column_type,
        ramp=ramp,
        colors=colors,
        method=method,
        count=count,
    )


def _class_breaks(request: StyleRequest, stats: dict[str, Any]) -> list[float]:
    if request.method == "manual":
        return list(request.breaks or ())
    low, high = stats.get("min"), stats.get("max")
    quantiles = stats.get("quantiles")
    if not _number(low) or not _number(high) or not isinstance(quantiles, list):
        raise ValueError(f"Column {request.column!r} has no numeric values to classify")
    count = request.count or DEFAULT_CLASS_COUNT
    if request.method == "quantile" and quantiles:
        breaks = list(quantiles)
    elif request.method == "jenks":
        breaks = jenks_breaks([low, *quantiles, high], count)
    elif request.method == "std_dev":
        mean, stddev = stats.get("mean"), stats.get("stddev")
        if not _number(mean) or not _number(stddev):
            raise ValueError(
                "This column has no standard deviation; use another method"
            )
        breaks = std_dev_breaks(mean, stddev, count)
    else:
        breaks = equal_interval_breaks(low, high, count)
    return list(dict.fromkeys(breaks))


def _pick_colors(
    request: StyleRequest, default_ramp: str, needed: int, what: str
) -> tuple[str, list[str]]:
    if request.colors is not None:
        if len(request.colors) < needed:
            raise ValueError(
                f"This style has {needed} {what}; give at least {needed} colours "
                "or a ramp name"
            )
        return "custom", list(request.colors[:needed])
    ramp = request.ramp or default_ramp
    return ramp, ramp_colors(ramp, needed)


# Builder keys under style_config.builder, in both stored spellings.
_FILL_STASH_KEYS = ("fillColorSaved", "fill_color_saved")
_LINE_GRADIENT_KEYS = ("lineGradient", "line_gradient")


def _without_builder_keys(
    config: Optional[dict[str, Any]], keys: tuple[str, ...]
) -> Optional[dict[str, Any]]:
    builder = (config or {}).get("builder")
    if not isinstance(builder, dict) or not any(k in builder for k in keys):
        return config
    rest = {k: v for k, v in builder.items() if k not in keys}
    out = {k: v for k, v in (config or {}).items() if k != "builder"}
    if rest:
        out["builder"] = rest
    return out or None


def _colour_owned_paint(paint: dict[str, Any]) -> dict[str, Any]:
    """Paint once a colour owns the layer: no pattern and no line gradient.

    MapLibre draws a fill-pattern over fill-color, and a line-pattern or
    line-gradient over line-color, so any of them would hide the new colour.
    """
    return {
        k: v
        for k, v in paint.items()
        if k != "line-gradient"
        and not (k in ("fill-pattern", "line-pattern") and v is not None)
    }


def _carried_config(
    existing: Optional[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    """The builder keeps its builder block and heatmap stash across a restyle,
    less the line gradient and the colour a pattern displaced."""
    merged = dict(config)
    existing = existing or {}
    for key in ("builder", "heatmapPaint"):
        if key not in config and existing.get(key) is not None:
            merged[key] = copy.deepcopy(existing[key])
    trimmed = _without_builder_keys(merged, _LINE_GRADIENT_KEYS + _FILL_STASH_KEYS)
    return trimmed or {}


def single_color(
    request: StyleRequest,
    geometry_type: Optional[str],
    paint: dict[str, Any],
    style_config: Optional[dict[str, Any]],
) -> tuple[dict[str, Any], Optional[dict[str, Any]], dict[str, Any]]:
    """Paint and style_config for one colour, as the builder's Clear then a colour."""
    prop = color_property(geometry_type)
    new_paint = {
        k: v
        for k, v in paint.items()
        if k not in ("fill-pattern", "line-pattern", "line-gradient")
    }
    new_paint[prop] = request.color
    new_paint.update(_size_properties(geometry_type))
    builder = (style_config or {}).get("builder")
    config = None
    if isinstance(builder, dict):
        config = _without_builder_keys(
            {"builder": builder}, _FILL_STASH_KEYS + _LINE_GRADIENT_KEYS
        )
    return new_paint, config, {"type": "single", "color": request.color}


def categories(
    request: StyleRequest,
    values: list[Any],
    geometry_type: Optional[str],
    paint: dict[str, Any],
    style_config: Optional[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Paint and style_config for a colour per value of a column."""
    as_string = is_boolean(request.column_type or "")
    if as_string:
        values = [
            ("true" if v else "false") if isinstance(v, bool) else str(v)
            for v in values
        ]
    else:
        values = [v for v in values if not isinstance(v, bool)]
    if not values:
        raise ValueError(f"Column {request.column!r} has no values to colour")
    if len(values) > MAX_CATEGORIES:
        raise ValueError(
            f"Column {request.column!r} has more than {MAX_CATEGORIES} values; "
            "use classes on a numeric column or a column with fewer values"
        )
    ramp, colors = _pick_colors(request, DEFAULT_CATEGORY_RAMP, len(values), "values")
    pairs = list(zip(values, colors, strict=True))
    prop = color_property(geometry_type)
    new_paint = {
        **_colour_owned_paint(paint),
        prop: categorical_expression(request.column, pairs, as_string=as_string),
    }
    entries = [{"value": v, "color": c} for v, c in pairs]
    config = {
        "mode": "categorical",
        "column": request.column,
        "ramp": ramp,
        "reversed": False,
        "categories": entries,
    }
    summary = {"type": "categories", "column": request.column, "categories": entries}
    return new_paint, _carried_config(style_config, config), summary


def classes(
    request: StyleRequest,
    stats: dict[str, Any],
    geometry_type: Optional[str],
    paint: dict[str, Any],
    style_config: Optional[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Paint and style_config for a colour per range of a numeric column."""
    breaks = _class_breaks(request, stats)
    if not breaks:
        raise ValueError(
            f"Column {request.column!r} has too little spread to split into classes"
        )
    ramp, colors = _pick_colors(request, DEFAULT_CLASS_RAMP, len(breaks) + 1, "classes")
    prop = color_property(geometry_type)
    new_paint = {
        **_colour_owned_paint(paint),
        prop: graduated_expression(request.column, breaks, colors, FALLBACK_COLOR),
    }
    class_count = (
        len(breaks) + 1
        if request.method == "manual"
        else request.count or DEFAULT_CLASS_COUNT
    )
    config = {
        "mode": "graduated",
        "column": request.column,
        "ramp": ramp,
        "reversed": False,
        "classCount": class_count,
        "method": request.method,
        "breaks": breaks,
        "colors": colors,
        "target": "color",
    }
    summary = {
        "type": "classes",
        "column": request.column,
        "method": request.method,
        "breaks": breaks,
        "colors": colors,
    }
    return new_paint, _carried_config(style_config, config), summary


def popup_config(
    fields: list[str], columns: dict[str, str], existing: Optional[dict[str, Any]]
) -> dict[str, Any]:
    """The layer's popup with ``fields`` as its ordered field list."""
    unknown = [f for f in fields if f not in columns]
    if unknown:
        raise ValueError(
            f"Not columns of this dataset: {', '.join(unknown)}. Columns: "
            + ", ".join(sorted(columns))
        )
    if len(set(fields)) != len(fields):
        raise ValueError("popup_fields must not repeat a column")
    base = existing or {"enabled": True, "expression": None, "visible_fields": None}
    return {**base, "visible_fields": list(fields)}
