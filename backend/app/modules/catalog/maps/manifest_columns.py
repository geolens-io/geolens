"""The feature columns a map layer's styling names, and their renaming.

A manifest names columns by their source names. One pass finds every place
the style export, the labels, the popup and the filter read a column and
hands each name to a ``rename`` callable: a dry run collects the names to
check them, and an apply writes the stored names in their place. Both use the
same pass, so the names checked are the names rewritten. The style export
reads the columns its tiles must carry from the layers it emits, with the
same walk.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.modules.catalog.maps.arcgis_webmap.fields import FieldNames
from app.modules.catalog.maps.schemas import MapLayerInput

Rename = Callable[[str], str]

_BUILDER_COLUMN_KEYS = ("heatmap_weight_column", "height_column")
# The builder keys, as stored, that the style export emits or the builder
# restores as paint values, so each may be an expression or a legacy property
# function.
_BUILDER_STYLE_VALUE_KEYS = (
    "outline_color",
    "outline_width",
    "arrow_color",
    "fill_opacity_saved",
    "outline_width_saved",
)
# The style_config paint dictionaries the builder restores as the layer's
# paint when its render mode changes.
_SAVED_PAINT_KEYS = ("heatmapPaint", "savedCirclePaint")
_STYLE_WALKED_KEYS = frozenset({"column", "symbol", "builder", *_SAVED_PAINT_KEYS})
# The other style_config keys a manifest keeps. None names a column: they hold
# mode, method and ramp names, the classes' values, colours, sizes and labels.
_STYLE_NON_COLUMN_KEYS = frozenset(
    {
        "mode",
        "ramp",
        "classCount",
        "method",
        "categories",
        "breaks",
        "colors",
        "target",
        "sizes",
        "render_mode",
        "legendLabel",
        "reversed",
        "sizeRange",
        "sizeLabel",
        "colorLabel",
    }
)
# The other builder keys the style export or the builder reads. None can name
# a column: each is read as a number, a flag, an enum or ramp name, a folder
# name, or a plain colour string, and anything else falls back to a default.
_BUILDER_NON_COLUMN_KEYS = frozenset(
    {
        "stroke_disabled",
        "fill_disabled",
        "fill_color_saved",
        "heatmap_ramp",
        "heatmap_reversed",
        "cluster_radius",
        "cluster_max_zoom",
        "cluster_color",
        "cluster_text_color",
        "cluster_text_size",
        "cluster_color_ramp",
        "cluster_show_counts",
        "folder_group",
        "folder_group_id",
        "folder_group_name",
        "folder_group_expanded",
        "height_scale",
        "extrusion_min_zoom",
        "extrusion_opacity",
        "arrow_size",
        "arrow_spacing",
        "hypso_enabled",
        "hypso_ramp",
        "hypso_reversed",
        # Read in both spellings; the camelCase ones aren't renamed on save.
        "hypsoEnabled",
        "hypsoRamp",
        "hypsoReversed",
        "lineGradient",
    }
)
# Paint keys the builder keeps beside the paint, each holding a column name.
_PAINT_COLUMN_KEYS = ("_heatmap-weight-column", "_height_column")
_COMPARISON_OPERATORS = frozenset({"==", "!=", "<", ">", "<=", ">="})
# The layout properties whose plain strings expand `{name}` tokens from the
# feature, as the style spec marks them `tokens: true`, and MapLibre's token
# pattern.
_TOKEN_LAYOUT_PROPERTIES = ("text-field", "icon-image")
_LAYOUT_TOKEN = re.compile(r"\{([^{}]+)\}")
# Operators whose operands are data, never expressions: a literal value,
# and the GeoJSON `within` and `distance` take.
_DATA_OPERATORS = frozenset({"literal", "within", "distance"})
_OPTION_OBJECT_OPERATORS = frozenset({"format", "collator", "number-format"})
# The symbol settings the style export writes into the layout unchanged, so
# each may be an expression. The icon itself is a name: the viewer reads an
# icon as a sprite name, so ``expression_icons`` refuses any other value.
_SYMBOL_LAYOUT_KEYS = ("iconSize", "iconRotation", "iconAnchor", "iconOffset")
_ICON_IMAGE_KEYS = ("iconImage", "icon_image")
# Read by the renderer from the feature itself, not from its properties.
_LEGACY_PSEUDO_FIELDS = frozenset({"$type", "$id"})
# The popup title's placeholders, as the viewer substitutes them.
_POPUP_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class Collector:
    """A ``rename`` that records the names it is given and keeps them.

    By default it is given what a plain ``rename`` is: the keys a ``get`` or
    ``has`` reads from the feature. With ``every_key`` it is given every
    static ``get`` or ``has`` key, whatever object the read is on, which is
    the set of columns a layer's tiles may need; asking a tile for a column
    the layer doesn't use does no harm.
    """

    def __init__(self, *, every_key: bool = False) -> None:
        self.every_key = every_key
        self.names: set[str] = set()

    def __call__(self, name: str) -> str:
        self.names.add(name)
        return name


# The second operands of a ``get`` or ``has`` that read the feature's own
# properties.
_FEATURE_OBJECTS = ([["properties"]], [["object", ["properties"]]])


_Steps = Generator["_Steps", Any, Any]


def _run(steps: _Steps) -> Any:
    """Run a walk that yields each nested walk it needs, on an explicit stack
    so the nesting depth an expression can have isn't bounded by the call
    stack."""
    stack = [steps]
    value: Any = None
    while stack:
        try:
            stack.append(stack[-1].send(value))
            value = None
        except StopIteration as done:
            stack.pop()
            value = done.value
    return value


def _expression(node: Any, rename: Rename) -> Any:
    """A MapLibre expression with each feature property it reads renamed.

    Operands are walked by position. ``literal``, ``within`` and ``distance``
    operands and ``match`` labels are data. A ``get`` or ``has`` reads the
    feature with one operand or with ``["properties"]`` as the second, and
    another object otherwise, ``["object", ["properties"]]`` being the
    feature's too; its name may be a string or a literal string. A
    ``Collector`` with ``every_key`` takes the key whatever the object.
    ``semiliteral`` evaluates its array's items, and ``format``, ``collator``
    and ``number-format`` evaluate the values of their option objects; any
    other object operand is data.
    """
    return _run(_expression_steps(node, rename))


def _expression_steps(node: Any, rename: Rename) -> _Steps:
    if not isinstance(node, list) or not node or not isinstance(node[0], str):
        return node
    operator, operands = node[0], list(node[1:])
    if operator in _DATA_OPERATORS:
        return node
    key = operands[0] if operands else None
    literal_key = isinstance(key, list) and len(key) == 2 and key[0] == "literal"
    if literal_key:
        key = key[1]
    walked: range | list[int]
    if operator in ("get", "has") and isinstance(key, str):
        if (
            len(operands) == 1
            or operands[1:] in _FEATURE_OBJECTS
            or (isinstance(rename, Collector) and rename.every_key)
        ):
            operands[0] = ["literal", rename(key)] if literal_key else rename(key)
        walked = range(1, len(operands))
    elif operator == "semiliteral" and operands and isinstance(operands[0], list):
        items = []
        for item in operands[0]:
            items.append((yield from _operand_steps(operator, item, rename)))
        operands[0] = items
        walked = []
    elif operator == "match" and operands:
        branches = len(operands) - 1
        # The input, then each output and the fallback, never a label.
        walked = [0] + [
            1 + index
            for index in range(branches)
            if index % 2 == 1 or index == branches - 1
        ]
    else:
        walked = range(len(operands))
    for index in walked:
        operands[index] = yield from _operand_steps(operator, operands[index], rename)
    return [operator, *operands]


def _operand_steps(operator: str, operand: Any, rename: Rename) -> _Steps:
    if isinstance(operand, dict) and operator in _OPTION_OBJECT_OPERATORS:
        walked = {}
        for key, value in operand.items():
            walked[key] = yield _expression_steps(value, rename)
        return walked
    return (yield _expression_steps(operand, rename))


def _style_value(value: Any, rename: Rename) -> Any:
    """A paint or layout value: an expression, or a legacy property function."""
    if isinstance(value, dict):
        if isinstance(value.get("property"), str) and value["property"]:
            return {**value, "property": rename(value["property"])}
        return value
    return _expression(value, rename)


def _filter(node: Any, rename: Rename) -> Any:
    """A filter in its legacy or expression form, with the properties it reads renamed.

    A filter is legacy or an expression by the same tests MapLibre's
    ``isExpressionFilter`` applies, so ``["==", ["get", "a"], "b"]`` is an
    expression while ``["==", "a", "b"]`` names the field ``a``.
    """
    return _run(_filter_steps(node, rename))


def _filter_steps(node: Any, rename: Rename) -> _Steps:
    if not isinstance(node, list) or not node or not isinstance(node[0], str):
        return node
    operator, operands = node[0], node[1:]
    if operator in ("all", "any", "none"):
        groups = []
        for operand in operands:
            groups.append((yield _filter_steps(operand, rename)))
        return [operator, *groups]
    field = operands[0] if operands and isinstance(operands[0], str) else None
    legacy = field is not None and (
        operator in ("!has", "!in")
        or (operator == "has" and field in _LEGACY_PSEUDO_FIELDS)
        or (
            operator == "in"
            and not (len(operands) >= 2 and isinstance(operands[1], list))
        )
        or (
            operator in _COMPARISON_OPERATORS
            and len(operands) == 2
            and not isinstance(operands[1], list)
        )
    )
    if not legacy:
        return _expression(node, rename)
    if field in _LEGACY_PSEUDO_FIELDS:
        return node
    return [operator, rename(field), *operands[1:]]


def _tokens(value: Any, pattern: re.Pattern[str], rename: Rename) -> Any:
    if not isinstance(value, str):
        return value
    return pattern.sub(lambda match: "{" + rename(match.group(1)) + "}", value)


def _symbol_category_icons(symbol: dict[str, Any]) -> list[Any]:
    """The category icons the style export writes into the icon match.

    The export keeps an entry only with a category column, a ``categories``
    list, and an entry whose ``value`` and ``icon`` are both set, and it
    passes the icon through unchanged, an expression included.
    """
    categories = symbol.get("categories")
    if not (symbol.get("categoryColumn") or symbol.get("category_column")):
        return []
    if not isinstance(categories, list):
        return []
    return [
        entry["icon"]
        for entry in categories
        if isinstance(entry, dict)
        and entry.get("icon") is not None
        and entry.get("value") is not None
    ]


def _rename_symbols(
    symbol: dict[str, Any] | None,
    builder_symbol: dict[str, Any] | None,
    rename: Rename,
) -> None:
    """Rename, in place, the symbol values the style export reads.

    ``symbol`` and ``builder_symbol`` are copies of the two dicts the export
    merges, ``symbol`` over ``builder.symbol``; each value is renamed in the
    dict the merge takes it from.
    """

    def owner(key: str) -> dict[str, Any] | None:
        for source in (symbol, builder_symbol):
            if source is not None and key in source:
                return source
        return None

    merged = {**(builder_symbol or {}), **(symbol or {})}
    for key in _SYMBOL_LAYOUT_KEYS:
        if (source := owner(key)) is not None:
            source[key] = _style_value(source[key], rename)
    if not _symbol_category_icons(merged):
        # Tokens expand only in a plain `icon-image` string. With categories
        # the export writes a match, where the icons and the fallback are
        # literal names, and with no surviving category it writes the
        # fallback icon alone.
        key = "iconImage" if merged.get("iconImage") else "icon_image"
        if (source := owner(key)) is not None:
            source[key] = _tokens(source[key], _LAYOUT_TOKEN, rename)
        return
    key = "categoryColumn" if merged.get("categoryColumn") else "category_column"
    source = owner(key)
    if source is not None and isinstance(source[key], str) and source[key]:
        source[key] = rename(source[key])


def expression_icons(style_config: dict[str, Any] | None) -> bool:
    """Whether a symbol icon or a category's icon is something other than an
    icon name, in ``symbol`` or ``builder.symbol``."""
    if not isinstance(style_config, dict):
        return False
    builder = style_config.get("builder")
    for symbol in (
        style_config.get("symbol"),
        builder.get("symbol") if isinstance(builder, dict) else None,
    ):
        if not isinstance(symbol, dict):
            continue
        icons = [symbol.get(key) for key in _ICON_IMAGE_KEYS]
        categories = symbol.get("categories")
        if isinstance(categories, list):
            icons += [
                entry.get("icon") for entry in categories if isinstance(entry, dict)
            ]
        if any(icon is not None and not isinstance(icon, str) for icon in icons):
            return True
    return False


def _style_config(style_config: dict[str, Any] | None, rename: Rename) -> Any:
    if style_config is None:
        return None
    renamed = dict(style_config)
    if isinstance(renamed.get("column"), str) and renamed["column"]:
        renamed["column"] = rename(renamed["column"])
    for key in _SAVED_PAINT_KEYS:
        if isinstance(renamed.get(key), dict):
            renamed[key] = {
                prop: _style_value(value, rename)
                for prop, value in renamed[key].items()
            }
    symbol = renamed.get("symbol")
    if isinstance(symbol, dict):
        symbol = renamed["symbol"] = dict(symbol)
    builder = renamed.get("builder")
    builder_symbol = None
    if isinstance(builder, dict):
        builder = renamed["builder"] = dict(builder)
        for key in _BUILDER_COLUMN_KEYS:
            if isinstance(builder.get(key), str) and builder[key]:
                builder[key] = rename(builder[key])
        for key in _BUILDER_STYLE_VALUE_KEYS:
            if key in builder:
                builder[key] = _style_value(builder[key], rename)
        if isinstance(builder.get("symbol"), dict):
            builder_symbol = builder["symbol"] = dict(builder["symbol"])
    _rename_symbols(
        symbol if isinstance(symbol, dict) else None, builder_symbol, rename
    )
    return renamed


def _paint(paint: dict[str, Any], rename: Rename) -> dict[str, Any]:
    return {
        key: (
            rename(value)
            if key in _PAINT_COLUMN_KEYS and isinstance(value, str) and value
            else _style_value(value, rename)
        )
        for key, value in paint.items()
    }


def rename_layer_columns(layer: MapLayerInput, rename: Rename) -> MapLayerInput:
    """``layer`` with every column its styling, labels, popup and filter name
    passed through ``rename``. ``layer`` itself is left as it was."""
    layout = layer.layout
    if layout is not None:
        layout = {key: _style_value(value, rename) for key, value in layout.items()}
        for prop in _TOKEN_LAYOUT_PROPERTIES:
            if prop in layout:
                layout[prop] = _tokens(layout[prop], _LAYOUT_TOKEN, rename)
    label_config = layer.label_config
    if label_config is not None:
        label_config = {
            key: _expression(value, rename) for key, value in label_config.items()
        }
        if isinstance(label_config.get("column"), str) and label_config["column"]:
            label_config["column"] = rename(label_config["column"])
    popup = layer.popup_config
    if popup is not None:
        popup = popup.model_copy(
            update={
                "visible_fields": (
                    [rename(name) if name else name for name in popup.visible_fields]
                    if popup.visible_fields is not None
                    else None
                ),
                "expression": _tokens(popup.expression, _POPUP_PLACEHOLDER, rename),
            }
        )
    return layer.model_copy(
        update={
            "style_config": _style_config(layer.style_config, rename),
            "paint": _paint(layer.paint, rename) if layer.paint is not None else None,
            "layout": layout,
            "label_config": label_config,
            "popup_config": popup,
            "filter": _filter(layer.filter, rename),
        }
    )


def named_columns(layer: MapLayerInput) -> set[str]:
    """Every column the layer's style, labels, popup and filter name."""
    collector = Collector()
    rename_layer_columns(layer, collector)
    return collector.names


# A symbol draws one icon and a heatmap its density; the classification of
# the circles either replaced stays for switching back. Only a symbol draws
# with the symbol settings, which other modes keep for the same reason.
_CLASSIFICATION = ("mode", "column")
_SYMBOL_SETTINGS = "symbol"


def live_styling(layer: MapLayerInput) -> MapLayerInput:
    """``layer`` as the viewer draws it, for judging what it reads: without
    the styling the builder keeps only to restore later (the saved heatmap and
    circle paints, the heatmap weight outside heatmap mode, the circle paint
    and classification under a symbol, the classification and labels under
    a heatmap, and the symbol settings under any mode but a symbol, which
    neither the viewer nor the style export draws), and without a disabled
    popup's fields. Never stored or used to rename."""
    style = layer.style_config if isinstance(layer.style_config, dict) else None
    mode = (style or {}).get("render_mode")
    live = None
    if style is not None:
        classified = mode not in ("symbol", "heatmap")
        unread = {
            *_SAVED_PAINT_KEYS,
            *(() if classified else _CLASSIFICATION),
            *(() if mode == "symbol" else (_SYMBOL_SETTINGS,)),
        }
        live = {key: value for key, value in style.items() if key not in unread}
        if isinstance(live.get("builder"), dict):
            live["builder"] = {
                key: value
                for key, value in live["builder"].items()
                if not (key == "heatmap_weight_column" and mode != "heatmap")
                and not (key == _SYMBOL_SETTINGS and mode != "symbol")
            }
    paint = {
        key: value
        for key, value in (layer.paint or {}).items()
        if not (key == "_heatmap-weight-column" and mode != "heatmap")
        and not (key.startswith("circle-") and mode == "symbol")
    }
    popup = layer.popup_config
    return layer.model_copy(
        update={
            "style_config": live,
            "paint": paint if layer.paint is not None else None,
            "popup_config": popup if popup is None or popup.enabled else None,
            "label_config": None if mode == "heatmap" else layer.label_config,
        }
    )


def number_columns(layer: MapLayerInput) -> set[str]:
    """The columns among ``named_columns`` that the layer's styling reads as
    numbers: a graduated style's column, a heatmap weight and an extrusion
    height."""
    style = layer.style_config if isinstance(layer.style_config, dict) else {}
    builder = style.get("builder") if isinstance(style.get("builder"), dict) else {}
    candidates = [
        style.get("column") if style.get("mode") == "graduated" else None,
        *(builder.get(key) for key in _BUILDER_COLUMN_KEYS),
        *((layer.paint or {}).get(key) for key in _PAINT_COLUMN_KEYS),
    ]
    return {name for name in candidates if isinstance(name, str) and name}


def emitted_columns(style_layer: dict[str, Any]) -> set[str]:
    """The columns a layer of an exported style document reads: every static
    ``get`` or ``has`` key in its paint, layout and filter, and the ``{name}``
    tokens of its text field and icon."""
    collector = Collector(every_key=True)
    for value in (style_layer.get("paint") or {}).values():
        _style_value(value, collector)
    for key, value in (style_layer.get("layout") or {}).items():
        _style_value(value, collector)
        if key in _TOKEN_LAYOUT_PROPERTIES:
            _tokens(value, _LAYOUT_TOKEN, collector)
    _filter(style_layer.get("filter"), collector)
    return collector.names


@dataclass(frozen=True)
class ColumnRepair:
    """What repairing a layer's column references against stored columns did.

    ``repaired`` maps each referenced name that changed to the stored name it
    now reads. ``unrepaired`` maps each referenced name left as it was to why
    it stayed: ``"missing"`` when no stored column resolves it, ``"ambiguous"``
    when more than one stored column matches it ignoring case.
    """

    repaired: dict[str, str]
    unrepaired: dict[str, str]


def repair_layer_columns(
    layer: MapLayerInput,
    columns: Sequence[Mapping[str, Any]] | None,
) -> tuple[MapLayerInput, ColumnRepair]:
    """``layer`` with each column reference rewritten to the stored name.

    A reference is rewritten to the stored column ``FieldNames`` resolves it
    to from the dataset's ``column_info``: the column whose recorded
    ``source_name`` it is first, then the exact name, then the laundered
    name, then the one column equal to it ignoring case. A reference that
    already names a stored column stays, even when another column records
    that name as its source field: the layer already reads a real column,
    and moving it would point it at a different column. Two columns that
    name each other would swap the reference on every run without that
    rule. A reference that resolves to nothing is kept and reported
    ``"missing"``, unless more than one stored column matches it ignoring
    case, when it is ``"ambiguous"``, so a repair never guesses between two
    columns. With no columns recorded the names cannot be judged, so the
    layer is left as it was. ``layer`` itself is left as it was.
    """
    if not columns:
        return layer, ColumnRepair(repaired={}, unrepaired={})
    stored = FieldNames(columns)
    by_folded: dict[str, set[str]] = {}
    stored_names: set[str] = set()
    for column in columns:
        if not isinstance(column, Mapping):
            continue
        name = column.get("name")
        if isinstance(name, str):
            by_folded.setdefault(name.casefold(), set()).add(name)
            stored_names.add(name)
    repaired: dict[str, str] = {}
    unrepaired: dict[str, str] = {}

    def rename(name: str) -> str:
        if not name:
            return name
        if name in stored_names:
            return name
        resolved = stored.stored(name)
        if resolved is not None:
            if resolved != name:
                repaired[name] = resolved
            return resolved
        if name not in unrepaired:
            unrepaired[name] = (
                "ambiguous"
                if len(by_folded.get(name.casefold(), set())) > 1
                else "missing"
            )
        return name

    return rename_layer_columns(layer, rename), ColumnRepair(
        repaired=repaired, unrepaired=unrepaired
    )
