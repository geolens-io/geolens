"""The feature columns a manifest map layer's styling names, and their renaming.

A manifest names columns by their source names. One pass finds every place
the style export, the labels, the popup and the filter read a column and
hands each name to a ``rename`` callable: a dry run collects the names to
check them, and an apply writes the stored names in their place. Both use the
same pass, so the names checked are the names rewritten.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

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


def _expression(node: Any, rename: Rename) -> Any:
    """A MapLibre expression with each feature property it reads renamed.

    Operands are walked by position. ``literal``, ``within`` and ``distance``
    operands and ``match`` labels are data. A ``get`` or ``has`` reads the
    feature with one operand or with ``["properties"]`` as the second, and
    another object otherwise; its name may be a string or a literal string.
    ``semiliteral`` evaluates its array's items, and ``format``, ``collator``
    and ``number-format`` evaluate the values of their option objects; any
    other object operand is data.
    """
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
        if len(operands) == 1 or operands[1:] == [["properties"]]:
            operands[0] = ["literal", rename(key)] if literal_key else rename(key)
        walked = range(1, len(operands))
    elif operator == "semiliteral" and operands and isinstance(operands[0], list):
        operands[0] = [_operand(operator, item, rename) for item in operands[0]]
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
        operands[index] = _operand(operator, operands[index], rename)
    return [operator, *operands]


def _operand(operator: str, operand: Any, rename: Rename) -> Any:
    if isinstance(operand, dict) and operator in _OPTION_OBJECT_OPERATORS:
        return {key: _expression(value, rename) for key, value in operand.items()}
    return _expression(operand, rename)


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
    if not isinstance(node, list) or not node or not isinstance(node[0], str):
        return node
    operator, operands = node[0], node[1:]
    if operator in ("all", "any", "none"):
        return [operator, *(_filter(operand, rename) for operand in operands)]
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
            "paint": (
                {key: _style_value(value, rename) for key, value in layer.paint.items()}
                if layer.paint is not None
                else None
            ),
            "layout": layout,
            "label_config": label_config,
            "popup_config": popup,
            "filter": _filter(layer.filter, rename),
        }
    )


def named_columns(layer: MapLayerInput) -> set[str]:
    """Every column the layer's style, labels, popup and filter name."""
    names: set[str] = set()

    def collect(name: str) -> str:
        names.add(name)
        return name

    rename_layer_columns(layer, collect)
    return names
