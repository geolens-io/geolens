"""The maps section of a publish manifest: what a dry run checks and reports.

Each map's key is looked up and its writer checked, each layer's dataset must
be one the caller can read, and each layer's styling goes through the map
layer schema. Nothing is written.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.maps.arcgis_webmap.fields import FieldNames
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.publish_vocabulary import (
    LABEL_METADATA_KEYS,
    STYLE_METADATA_KEYS,
)
from app.modules.catalog.maps.schemas import MapLayerInput
from app.modules.catalog.maps.service import check_map_ownership
from app.modules.settings.basemaps import list_public_basemaps

KEY_NOT_WRITABLE = "A050"
DATASET_NOT_READY = "A052"
STYLE_KEY_DROPPED = "A062"
COLUMN_MISSING = "A063"
OTHER_REFUSAL = "A099"

MAP_KEY_NOT_WRITABLE = "This map key belongs to a map you can't edit."
MAP_CHECK_FAILED = "This map could not be checked. Try again."

log = structlog.get_logger()
# One answer for a dataset that doesn't exist, isn't ready and can't be read,
# so the answer tells a caller nothing about datasets they can't see.
DATASET_UNAVAILABLE = (
    "Layer {layer}: its dataset doesn't exist, hasn't finished publishing, "
    "or you can't read it."
)

# Shape-checks a layer whose dataset didn't resolve; never stored.
_NO_DATASET = uuid.UUID(int=0)
_BUILDER_COLUMN_KEYS = ("heatmap_weight_column", "height_column")
# The builder keys, as stored, that the style export emits as paint values,
# so each may be an expression or a legacy property function.
_BUILDER_STYLE_VALUE_KEYS = ("outline_color", "outline_width", "arrow_color")
# The other builder keys the style export reads. None can name a column: the
# export takes numbers, flags, enum names or a plain colour string from them.
_BUILDER_NON_COLUMN_KEYS = frozenset(
    {
        "stroke_disabled",
        "fill_color_saved",
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
# each may be an expression.
_SYMBOL_LAYOUT_KEYS = (
    "iconImage",
    "icon_image",
    "iconSize",
    "iconRotation",
    "iconAnchor",
    "iconOffset",
)
# Read by the renderer from the feature itself, not from its properties.
_LEGACY_PSEUDO_FIELDS = frozenset({"$type", "$id"})
# The popup title's placeholders, as the viewer substitutes them.
_POPUP_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_MAX_REPORTED_ERRORS = 5
# Names in a message come from the caller, so a message lists only so many.
_MAX_LISTED_NAMES = 20
_MAX_LISTED_NAME_LENGTH = 64
# A schema error may quote the caller's keys too.
_MAX_ERROR_LENGTH = 300


def _short(name: object, limit: int = _MAX_LISTED_NAME_LENGTH) -> str:
    text = str(name)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _problem(error: Mapping[str, Any]) -> str:
    where = ".".join(_short(part) for part in error["loc"]) or "layer"
    return f"{where}: {_short(error['msg'], _MAX_ERROR_LENGTH)}"


def _listed(names: Sequence[str]) -> str:
    shown = ", ".join(_short(name) for name in names[:_MAX_LISTED_NAMES])
    rest = len(names) - _MAX_LISTED_NAMES
    return f"{shown} and {rest} more" if rest > 0 else shown


def _message(
    code: str,
    severity: str,
    message: str,
    *,
    fix: str | None = None,
    layer: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "fix": fix,
        "layer": layer,
    }


async def _readable_columns(
    session: AsyncSession,
    dataset_ids: Iterable[uuid.UUID],
    user: Identity,
) -> dict[uuid.UUID, list[dict[str, Any]] | None]:
    """The stored columns of each dataset the caller can read, in one query.

    None means the dataset's columns were never recorded; an empty list is a
    dataset with no attribute columns, such as a geometry-only table. A
    dataset the caller can't read is left out exactly like a missing one.
    The query runs even with no ids, so a dataset key that resolved costs the
    same queries as one that didn't.
    """
    wanted = sorted(set(dataset_ids))
    stmt = (
        select(Dataset.id, Dataset.column_info)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id.in_(wanted))
    )
    roles = await get_user_roles(session, user)
    stmt = apply_visibility_filter(stmt, user, roles, Record, DatasetGrant)
    rows = await session.execute(stmt)
    return {row[0]: list(row[1]) if isinstance(row[1], list) else None for row in rows}


async def _known_basemap_ids(session: AsyncSession) -> set[str]:
    """The basemap ids ``GET /capabilities`` lists."""
    return {
        basemap.id for basemap in await list_public_basemaps(session) if basemap.enabled
    }


async def _writable_map_id(
    session: AsyncSession, key: str, user: Identity
) -> tuple[uuid.UUID | None, bool]:
    """The map ``key`` names and whether the caller may write it.

    ``(None, True)`` when no map has the key.
    """
    map_obj = (
        await session.execute(select(Map).where(Map.manifest_key == key))
    ).scalar_one_or_none()
    if map_obj is None:
        return None, True
    try:
        await check_map_ownership(map_obj, user, session)
    except HTTPException:
        return None, False
    return map_obj.id, True


def _known_keys(
    value: dict[str, Any] | None, known: frozenset[str]
) -> tuple[dict[str, Any] | None, list[str]]:
    if value is None:
        return None, []
    dropped = sorted(key for key in value if key not in known)
    return {k: v for k, v in value.items() if k in known}, dropped


def _walk_expression(node: Any, names: set[str]) -> None:
    """Collect the feature properties a MapLibre expression reads.

    Operands are walked by position. ``literal``, ``within`` and ``distance``
    operands and ``match`` labels are data. A ``get`` or ``has`` reads the
    feature with one operand or with ``["properties"]`` as the second, and
    another object otherwise. ``semiliteral`` evaluates its array's items, and
    ``format``, ``collator`` and ``number-format`` evaluate the values of
    their option objects; any other object operand is data.
    """
    if not isinstance(node, list) or not node or not isinstance(node[0], str):
        return
    operator, operands = node[0], node[1:]
    if operator in _DATA_OPERATORS:
        return
    if operator in ("get", "has") and operands and isinstance(operands[0], str):
        reads_feature = len(operands) == 1 or operands[1:] == [["properties"]]
        if reads_feature:
            names.add(operands[0])
        operands = operands[1:]
    elif operator == "semiliteral" and operands and isinstance(operands[0], list):
        operands = operands[0]
    elif operator == "match" and operands:
        branches = operands[1:]
        # Label and output pairs, then the fallback.
        operands = [operands[0]] + [
            branch
            for index, branch in enumerate(branches)
            if index % 2 == 1 or index == len(branches) - 1
        ]
    for operand in operands:
        if isinstance(operand, dict) and operator in _OPTION_OBJECT_OPERATORS:
            for value in operand.values():
                _walk_expression(value, names)
        else:
            _walk_expression(operand, names)


def _walk_style_value(value: Any, names: set[str]) -> None:
    """A paint or layout value: an expression, or a legacy property function."""
    if isinstance(value, dict):
        if isinstance(value.get("property"), str) and value["property"]:
            names.add(value["property"])
        return
    _walk_expression(value, names)


def _walk_filter(node: Any, names: set[str]) -> None:
    """Collect the properties a filter reads, in its legacy or expression form.

    A filter is legacy or an expression by the same tests MapLibre's
    ``isExpressionFilter`` applies, so ``["==", ["get", "a"], "b"]`` is an
    expression while ``["==", "a", "b"]`` names the field ``a``.
    """
    if not isinstance(node, list) or not node or not isinstance(node[0], str):
        return
    operator, operands = node[0], node[1:]
    if operator in ("all", "any", "none"):
        for operand in operands:
            _walk_filter(operand, names)
        return
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
        _walk_expression(node, names)
    elif field not in _LEGACY_PSEUDO_FIELDS:
        names.add(field)


def _merged_symbol(style_config: dict[str, Any]) -> dict[str, Any]:
    """The symbol settings, ``symbol`` over ``builder.symbol``, as the style export merges them."""
    builder = style_config.get("builder")
    builder_symbol = builder.get("symbol") if isinstance(builder, dict) else None
    symbol = style_config.get("symbol")
    return {
        **(builder_symbol if isinstance(builder_symbol, dict) else {}),
        **(symbol if isinstance(symbol, dict) else {}),
    }


def _symbol_category_column(style_config: dict[str, Any]) -> Any:
    """The column a symbol layer picks its icons by, read as the style export does."""
    symbol = _merged_symbol(style_config)
    if not isinstance(symbol.get("categories"), list):
        return None
    return symbol.get("categoryColumn") or symbol.get("category_column")


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


def _named_columns(layer: MapLayerInput) -> set[str]:
    """Every column the layer's style, labels, popup and filter name."""
    names: set[str] = set()
    style_config = layer.style_config or {}
    builder = style_config.get("builder")
    popup = layer.popup_config
    candidates = [
        style_config.get("column"),
        _symbol_category_column(style_config),
        (layer.label_config or {}).get("column"),
        *(
            builder.get(key) if isinstance(builder, dict) else None
            for key in _BUILDER_COLUMN_KEYS
        ),
        *((popup.visible_fields or []) if popup else []),
        *(_POPUP_PLACEHOLDER.findall(popup.expression or "") if popup else []),
    ]
    names.update(c for c in candidates if isinstance(c, str) and c)
    builder_values = [
        builder.get(key) if isinstance(builder, dict) else None
        for key in _BUILDER_STYLE_VALUE_KEYS
    ]
    for value in [
        *(layer.paint or {}).values(),
        *(layer.layout or {}).values(),
        *builder_values,
    ]:
        _walk_style_value(value, names)
    token_values = [(layer.layout or {}).get(prop) for prop in _TOKEN_LAYOUT_PROPERTIES]
    symbol = _merged_symbol(style_config)
    for key in _SYMBOL_LAYOUT_KEYS:
        _walk_style_value(symbol.get(key), names)
    # The fallback and category icons are exported into `icon-image`, which
    # expands tokens.
    category_icons = _symbol_category_icons(symbol)
    for icon in category_icons:
        _walk_expression(icon, names)
    token_values += [symbol.get("iconImage") or symbol.get("icon_image")]
    token_values += category_icons
    for value in token_values:
        if isinstance(value, str):
            names.update(_LAYOUT_TOKEN.findall(value))
    for value in (layer.label_config or {}).values():
        _walk_expression(value, names)
    _walk_filter(layer.filter, names)
    return names


def _check_layer(
    layer: Any,
    dataset_id: uuid.UUID | None,
    columns: list[dict[str, Any]] | None,
    *,
    readable: bool,
    pending: bool,
) -> list[dict[str, Any]]:
    """The messages for one layer.

    ``columns`` are the readable dataset's stored columns, None when they were
    never recorded, which leaves the names unchecked. A ``pending`` layer
    names a dataset the same request publishes, so an unreadable dataset is
    no error for it, and there are no columns to check.
    """
    messages: list[dict[str, Any]] = []
    if not readable and not pending:
        messages.append(
            _message(
                DATASET_NOT_READY,
                "error",
                DATASET_UNAVAILABLE.format(layer=layer.key),
                fix="Wait for its job.",
                layer=layer.key,
            )
        )
    style_config, dropped_style = _known_keys(layer.style_config, STYLE_METADATA_KEYS)
    label_config, dropped_label = _known_keys(layer.label_config, LABEL_METADATA_KEYS)
    for field, dropped in (
        ("style_config", dropped_style),
        ("label_config", dropped_label),
    ):
        if dropped:
            messages.append(
                _message(
                    STYLE_KEY_DROPPED,
                    "info",
                    f"Unknown {field} keys were dropped: {_listed(dropped)}.",
                    layer=layer.key,
                )
            )
    try:
        checked = MapLayerInput(
            dataset_id=dataset_id or _NO_DATASET,
            visible=layer.visible,
            opacity=layer.opacity,
            paint=layer.paint,
            layout=layer.layout,
            display_name=layer.display_name,
            filter=layer.filter,
            label_config=label_config,
            popup_config=layer.popup_config,
            style_config=style_config,
            show_in_legend=layer.show_in_legend,
        )
        named = _named_columns(checked)
    except ValidationError as exc:
        problems = "; ".join(
            _problem(error)
            for error in exc.errors(include_input=False)[:_MAX_REPORTED_ERRORS]
        )
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"Layer {layer.key} can't be saved: {problems}",
                layer=layer.key,
            )
        )
        return messages
    except RecursionError:
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"Layer {layer.key} can't be saved: its styling is nested too deeply.",
                layer=layer.key,
            )
        )
        return messages
    if not readable or columns is None:
        return messages
    # FieldNames reads an empty list as "columns unknown" and accepts every
    # name; a recorded empty list has none.
    stored = FieldNames(columns)
    missing = sorted(
        name for name in named if not columns or stored.stored(name) is None
    )
    if missing:
        messages.append(
            _message(
                COLUMN_MISSING,
                "warning",
                f"The dataset has no single column named {_listed(missing)}.",
                fix="Fix the field name.",
                layer=layer.key,
            )
        )
    return messages


async def _check_map(
    session: AsyncSession,
    entry: Any,
    user: Identity,
    dataset_ids_by_key: Mapping[str, uuid.UUID],
    pending_dataset_keys: Collection[str],
    columns_by_dataset: Mapping[uuid.UUID, list[dict[str, Any]] | None],
    basemap_ids: set[str],
) -> dict[str, Any]:
    map_id, writable = await _writable_map_id(session, entry.key, user)
    messages: list[dict[str, Any]] = []
    if not writable:
        messages.append(
            _message(
                KEY_NOT_WRITABLE,
                "error",
                MAP_KEY_NOT_WRITABLE,
                fix="Publish as a new map.",
            )
        )
    if entry.basemap_style is not None and entry.basemap_style not in basemap_ids:
        messages.append(
            _message(
                OTHER_REFUSAL,
                "error",
                f"{entry.basemap_style!r} isn't a basemap on this server.",
                fix="Choose a basemap from GET /capabilities.",
            )
        )
    for layer in entry.layers:
        dataset_id = (
            layer.dataset_id
            if layer.dataset_id is not None
            else dataset_ids_by_key.get(layer.dataset_key)
        )
        messages.extend(
            _check_layer(
                layer,
                dataset_id,
                columns_by_dataset.get(dataset_id) if dataset_id else None,
                readable=dataset_id in columns_by_dataset,
                pending=layer.dataset_key in pending_dataset_keys,
            )
        )
    if any(message["severity"] == "error" for message in messages):
        action = "error"
    else:
        action = "create" if map_id is None else "update"
    return {
        "map_key": entry.key,
        "action": action,
        "map_id": map_id,
        "messages": messages,
    }


async def apply_manifest_maps(
    session: AsyncSession,
    maps: Sequence[Any],
    user: Identity,
    *,
    dry_run: bool,
    dataset_ids_by_key: Mapping[str, uuid.UUID],
    pending_dataset_keys: Collection[str],
) -> list[dict[str, Any]]:
    """Check each manifest map and report what applying it would do.

    Only a dry run is supported. ``dataset_ids_by_key`` holds the dataset each
    layer's ``dataset_key`` names; an absent key reads like a missing dataset.
    ``pending_dataset_keys`` are the keys of the request's own datasets
    whose entries can supply a dataset: a layer naming one whose dataset it
    can't read is checked without columns instead of refused, since the
    publish provides that dataset. A map whose check fails unexpectedly is
    reported as that map's error alone. Writes nothing; the caller rolls the
    session back.
    """
    if not dry_run:
        raise NotImplementedError("manifest maps apply is not implemented yet")
    layer_dataset_ids = {
        dataset_id
        for entry in maps
        for layer in entry.layers
        if (
            dataset_id := (
                layer.dataset_id
                if layer.dataset_id is not None
                else dataset_ids_by_key.get(layer.dataset_key)
            )
        )
        is not None
    }
    columns_by_dataset = await _readable_columns(session, layer_dataset_ids, user)
    basemap_ids = await _known_basemap_ids(session)
    results = []
    for entry in maps:
        try:
            # A database error inside one map's checks rolls back to here and
            # leaves the transaction usable for the next map.
            async with session.begin_nested():
                result = await _check_map(
                    session,
                    entry,
                    user,
                    dataset_ids_by_key,
                    pending_dataset_keys,
                    columns_by_dataset,
                    basemap_ids,
                )
            results.append(result)
        except Exception:  # broad: one map's failure must not fail the other maps
            log.exception("manifest_map_check_failed", map_key=entry.key)
            results.append(
                {
                    "map_key": entry.key,
                    "action": "error",
                    "map_id": None,
                    "messages": [_message(OTHER_REFUSAL, "error", MAP_CHECK_FAILED)],
                }
            )
    return results
