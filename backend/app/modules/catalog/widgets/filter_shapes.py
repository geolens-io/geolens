"""The filter shapes a dashboard widget takes: the ones the viewer sends as CQL2.

``widget_filter_cql2`` reads a stored widget filter as the viewer's converter
(``maplibreFilterToCql2`` in ``frontend/src/lib/maplibre-filter-utils.ts``)
does and returns the CQL2 the viewer sends, with its columns, value count and
depth. Any other shape raises ``FilterValidationError``. The cases in
``tests/fixtures/widget_filter_shapes.json`` run against this module and the
frontend's ``widgetFilterShape``.
"""

import datetime
import math
import re
import sys
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any, NamedTuple

from app.modules.catalog.maps.filter_grammar import FilterValidationError

# The aggregate endpoint's ``_MAX_FILTER_DEPTH``; a test pins the two together.
MAX_CQL2_DEPTH = 64
_COLUMN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,62}")
_CQL2_OPS = {"==": "=", "!=": "<>", "<": "<", ">": ">", "<=": "<=", ">=": ">="}
_ORDER = ("<", ">", "<=", ">=")
_LEGACY_NEGATIONS = {"!in": "in", "!=": "==", "!has": "has"}
_PSEUDO = ("$type", "$id")
# The column types and literal spellings ``layerFilterToServerCql2`` sends,
# mirrored from maplibre-filter-utils.ts and column-utils.ts.
_TEXT = ("text", "character varying", "character")
_QUERYABLE = (
    *_TEXT,
    "smallint",
    "integer",
    "bigint",
    "real",
    "double precision",
    "numeric",
    "boolean",
    "date",
    "timestamp without time zone",
    "timestamp with time zone",
    "uuid",
)
_INTEGER_RANGES = {
    "smallint": (-32768, 32767),
    "integer": (-2147483648, 2147483647),
    "bigint": (-(2**63), 2**63 - 1),
}
_FLOAT4_MAX = 3.4028234663852886e38
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIME = r"((?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{0,5}[1-9])?)"
_TIMESTAMP = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}) " + _TIME)
_UTC_TIMESTAMP = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})T" + _TIME + r"\+00:00")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_LOW, _HIGH = -1_000_000_000_000, 1_000_000_000_000
# JSON integers past this reach the browser rounded, so the viewer can't send them.
_MAX_SAFE_INTEGER = 2**53 - 1
# The viewer still sends a layer filter's rounded whole number where the column takes it.
_UNSAFE_INTEGERS: ContextVar[bool] = ContextVar("unsafe_integers", default=False)
_REFUSED = (
    "A widget filter takes only the conditions the filter editor writes: "
    "comparisons, value lists, contains, has and is-empty tests on named "
    "columns, joined by all or any"
)


class WidgetFilter(NamedTuple):
    cql2: dict | None
    columns: frozenset[str]
    values: int
    depth: int


def _unsupported_shape() -> FilterValidationError:
    return FilterValidationError(_REFUSED)


def _op(node: Any) -> str | None:
    """A node's operator, or None when it is not a list headed by a string."""
    if isinstance(node, list) and node and isinstance(node[0], str):
        return node[0]
    return None


def _is_number(value: Any) -> bool:
    """A finite number the viewer reads exactly: an integer within JavaScript's safe range."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        # Past the double range the browser reads Infinity, which it doesn't send.
        bound = sys.float_info.max if _UNSAFE_INTEGERS.get() else _MAX_SAFE_INTEGER
        return abs(value) <= bound
    if isinstance(value, float):
        return math.isfinite(value) and (
            not (value.is_integer() and abs(value) > _MAX_SAFE_INTEGER)
            or _UNSAFE_INTEGERS.get()
        )
    return False


def _is_scalar(value: Any) -> bool:
    return isinstance(value, str | bool) or _is_number(value)


def _calendar_date(day: str) -> bool:
    try:
        return datetime.date.fromisoformat(day).isoformat() == day
    except ValueError:
        return False


def _cql2_literal(value: Any, pg_type: str | None) -> Any:
    """``value`` as the CQL2 literal the viewer writes for ``pg_type``, or None."""
    if pg_type == "date":
        if isinstance(value, str) and _DATE.fullmatch(value) and _calendar_date(value):
            return {"date": value}
        return None
    if pg_type in ("timestamp without time zone", "timestamp with time zone"):
        pattern = (
            _TIMESTAMP if pg_type == "timestamp without time zone" else _UTC_TIMESTAMP
        )
        m = pattern.fullmatch(value) if isinstance(value, str) else None
        if m and _calendar_date(m[1]):
            return {"timestamp": f"{m[1]}T{m[2]}Z"}
        return None
    if pg_type == "uuid":
        return value if isinstance(value, str) and _UUID.fullmatch(value) else None
    return value


def _compatible(value: Any, pg_type: str | None) -> bool:
    """``isCql2LiteralCompatible``: whether the viewer sends ``value`` for ``pg_type``."""
    if not _is_scalar(value) or _cql2_literal(value, pg_type) is None:
        return False
    if pg_type in _TEXT:
        return isinstance(value, str)
    if pg_type in _INTEGER_RANGES:
        low, high = _INTEGER_RANGES[pg_type]
        whole = _is_number(value) and float(value).is_integer()
        return whole and abs(value) <= _MAX_SAFE_INTEGER and low <= value <= high
    if pg_type == "real":
        return _is_number(value) and abs(value) <= _FLOAT4_MAX
    if pg_type in ("double precision", "numeric"):
        return _is_number(value)
    if pg_type == "boolean":
        return isinstance(value, bool)
    return True


def _get(node: Any) -> str | None:
    """The column of ``["get", name]``, else None."""
    if _op(node) == "get" and len(node) == 2 and isinstance(node[1], str):
        return node[1]
    return None


def _typeof(field: str, kind: str, op: str) -> list:
    return [op, ["typeof", ["get", field]], kind]


def _scalar_guard(field: str) -> list:
    kinds = ("null", "boolean", "number", "string")
    return ["any", *(_typeof(field, kind, "==") for kind in kinds)]


def _fallback(op: str, value: Any) -> int:
    if op in ("<", "<="):
        return _HIGH
    return _HIGH if value == _LOW else _LOW


def _compare(a: float, op: str, b: float) -> bool:
    return {
        "==": a == b,
        "!=": a != b,
        "<": a < b,
        ">": a > b,
        "<=": a <= b,
        ">=": a >= b,
    }[op]


def _cmp(node: Any) -> bool:
    """``[op, ["get", f], value]`` with a comparison operator."""
    return _op(node) in _CQL2_OPS and len(node) == 3 and _get(node[1]) is not None


def _to_number(node: Any) -> tuple[str, Any] | None:
    """The column and fallback of ``[op, ["to-number", ["get", f], fallback], n]``."""
    if _op(node) not in _CQL2_OPS or len(node) != 3 or not _is_number(node[2]):
        return None
    accessor = node[1]
    if _op(accessor) != "to-number" or len(accessor) != 3:
        return None
    field = _get(accessor[1])
    if field is None or not _is_number(accessor[2]):
        return None
    return field, accessor[2]


def _guarded(node: Any) -> tuple[str, str, Any] | None:
    """A to-number comparison with the editor's fallback behind a null check.

    A leading number check, which a legacy order comparison carries, is read
    through.
    """
    if _op(node) != "all" or len(node) != 3:
        return None
    inner = _guarded(node[2])
    if inner is not None and node[1] == _typeof(inner[0], "number", "=="):
        return inner
    guard, test = node[1], node[2]
    if _op(guard) != "!=" or len(guard) != 3 or guard[2] != "null":
        return None
    typeof = guard[1]
    field = _get(typeof[1]) if _op(typeof) == "typeof" and len(typeof) == 2 else None
    accessor = _to_number(test)
    if field is None or accessor is None or accessor[0] != field:
        return None
    op, value = test[0], test[2]
    return (field, op, value) if accessor[1] == _fallback(op, value) else None


def _members(node: Any) -> tuple[str, list] | None:
    """The column and values of ``["in", ["get", f], ["literal", [...]]]``."""
    if _op(node) != "in" or len(node) != 3:
        return None
    field, listed = _get(node[1]), node[2]
    if field is None or _op(listed) != "literal" or len(listed) != 2:
        return None
    return (field, listed[1]) if isinstance(listed[1], list) else None


def _without_scalar_guard(node: Any) -> Any:
    if _op(node) == "all" and len(node) == 3:
        members = _members(node[2])
        if members is not None and node[1] == _scalar_guard(members[0]):
            return node[2]
    return node


class _Builder:
    """Builds the CQL2 for one filter, recording the columns it reads."""

    def __init__(self, types: Mapping[str, str] | None) -> None:
        self.types = types or {}
        self.columns: set[str] = set()

    def type_of(self, field: str) -> str | None:
        """The column's type; None when unknown, which the viewer leaves to the server."""
        return self.types.get(field) or None

    def prop(self, field: str) -> dict:
        if not _COLUMN.fullmatch(field):
            raise _unsupported_shape()
        pg_type = self.type_of(field)
        if pg_type is not None and pg_type not in _QUERYABLE:
            raise _unsupported_shape()
        self.columns.add(field)
        return {"property": field}

    def literal(self, field: str, value: Any) -> Any:
        pg_type = self.type_of(field)
        if not _compatible(value, pg_type):
            raise _unsupported_shape()
        return _cql2_literal(value, pg_type)

    def number(self, field: str, value: Any) -> Any:
        """A number compared through ``to-number``, which must still suit the column."""
        if not _compatible(value, self.type_of(field)):
            raise _unsupported_shape()
        return value

    def is_null(self, field: str) -> dict:
        return {"op": "isNull", "args": [self.prop(field)]}

    def or_null(self, field: str, expr: dict) -> dict:
        return {"op": "or", "args": [self.is_null(field), expr]}

    def compare(self, op: str, field: str, value: Any) -> dict:
        return {"op": _CQL2_OPS[op], "args": [self.prop(field), value]}

    def members(self, field: str, values: list) -> dict:
        if not values:
            raise _unsupported_shape()
        literals = [self.literal(field, value) for value in values]
        return {"op": "in", "args": [self.prop(field), literals]}

    def comparison(self, op: str, field: str, value: Any) -> dict:
        # A bare number is drawn null-safe, as sanitizeNullableNumericFilter does.
        if _is_number(value):
            return self.compare(op, field, self.number(field, value))
        if value is None:
            if op == "==":
                return self.is_null(field)
            if op == "!=":
                return {"op": "not", "args": [self.is_null(field)]}
            raise _unsupported_shape()
        comparison = self.compare(op, field, self.literal(field, value))
        return self.or_null(field, comparison) if op == "!=" else comparison

    def condition(self, node: Any) -> dict | None:
        """One editor condition as CQL2, or None when ``node`` is not one."""
        negated = _op(node) == "!" and len(node) == 2
        e = (
            ["!", _without_scalar_guard(node[1])]
            if negated
            else _without_scalar_guard(node)
        )
        op = _op(e)
        if op == "any" and len(e) == 3 and _cmp(e[2]) and e[2][0] == "==":
            field = _get(e[2][1])
            if e[2][2] is None and e[1] == ["!", ["has", field]]:
                return self.is_null(field)
        if op == "!":
            if len(e) != 2:
                return None
            inner = e[1]
            if _op(inner) == "has" and len(inner) == 2 and isinstance(inner[1], str):
                return self.is_null(inner[1])
            members = _members(inner)
            if members is None:
                return None
            listed = self.members(*members)
            return self.or_null(members[0], {"op": "not", "args": [listed]})
        members = _members(e)
        if members is not None:
            return self.members(*members)
        if op == "in" and len(e) == 3 and _get(e[2]) is not None:
            pg_type = self.type_of(_get(e[2]))
            if not isinstance(e[1], str) or (
                pg_type is not None and pg_type not in _TEXT
            ):
                raise _unsupported_shape()
            pattern = re.sub(r"([\\%_])", r"\\\1", e[1])
            return {"op": "like", "args": [self.prop(_get(e[2])), f"%{pattern}%"]}
        if op == "has" and len(e) == 2 and isinstance(e[1], str):
            return {"op": "not", "args": [self.is_null(e[1])]}
        guarded = _guarded(e)
        if guarded is not None:
            field, guarded_op, value = guarded
            return self.compare(guarded_op, field, self.number(field, value))
        if _cmp(e):
            return self.comparison(op, _get(e[1]), e[2])
        accessor = _to_number(e)
        if accessor is None:
            return None
        field, fallback = accessor
        comparison = self.compare(op, field, self.number(field, e[2]))
        if fallback == _fallback(op, e[2]) or not _compare(0, op, e[2]):
            return comparison
        return self.or_null(field, comparison)

    def tree(self, node: Any) -> dict | None:
        """``node`` as CQL2; None when it keeps every feature."""
        condition = self.condition(node)
        if condition is not None:
            return condition
        if _op(node) not in ("all", "any"):
            raise _unsupported_shape()
        parts = []
        keeps_all = False
        for child in node[1:]:
            if not isinstance(child, list):
                raise _unsupported_shape()
            # Every branch is read, after one that keeps every feature too.
            part = self.tree(child)
            if part is None:
                keeps_all = True
            else:
                parts.append(part)
        if node[0] == "any" and keeps_all:
            return None
        if not parts:
            if node[0] == "any":
                raise _unsupported_shape()
            return None
        if len(parts) == 1:
            return parts[0]
        return {"op": "and" if node[0] == "all" else "or", "args": parts}


def _classify(node: Any) -> str:
    """MapLibre's ``classifyFilter``: ``legacy``, ``expression`` or ``neutral``."""
    if isinstance(node, bool):
        return "neutral"
    if not isinstance(node, list) or not node:
        return "legacy"
    op = _op(node)
    if op == "has":
        if len(node) < 2 or node[1] in _PSEUDO:
            return "legacy"
        return "neutral" if len(node) == 2 else "expression"
    if op == "in":
        expression = len(node) >= 3 and (
            not isinstance(node[1], str) or isinstance(node[2], list)
        )
        return "expression" if expression else "legacy"
    if op in ("!in", "!has", "none"):
        return "legacy"
    if op in _CQL2_OPS:
        operands = node[1:3]
        expression = len(node) != 3 or any(isinstance(o, list) for o in operands)
        return "expression" if expression else "legacy"
    if op in ("any", "all"):
        saw_legacy = False
        for child in node[1:]:
            kind = _classify(child)
            if kind == "expression":
                return "expression"
            saw_legacy = saw_legacy or kind == "legacy"
        return "legacy" if saw_legacy else "neutral"
    return "expression"


def _legacy(node: Any) -> list:
    """A legacy-syntax filter in the expression forms the converter gives it."""
    op = _op(node)
    if op is None:
        raise _unsupported_shape()
    key, values = node[1] if len(node) > 1 else None, node[2:]
    if op in ("all", "any"):
        return [op, *(_legacy(child) for child in node[1:])]
    if op in _LEGACY_NEGATIONS:
        return ["!", _legacy([_LEGACY_NEGATIONS[op], *node[1:]])]
    if not isinstance(key, str) or key in _PSEUDO:
        raise _unsupported_shape()
    if op == "in":
        return ["in", ["get", key], ["literal", values]]
    if op == "has":
        if values:
            raise _unsupported_shape()
        return ["has", key]
    if len(values) != 1 or not _is_scalar(values[0]):
        raise _unsupported_shape()
    value = values[0]
    if op == "==":
        return ["in", ["get", key], ["literal", [value]]]
    if op not in _ORDER or not _is_number(value):
        raise _unsupported_shape()
    comparison = [op, ["to-number", ["get", key], _fallback(op, value)], value]
    guarded = ["all", _typeof(key, "null", "!="), comparison]
    return ["all", _typeof(key, "number", "=="), guarded]


def measure_cql2(cql2: Any) -> tuple[int, int]:
    """Values (one bind each once compiled) and depth, as the aggregate counts them."""
    values, deepest = 0, 0
    pending: list[tuple[Any, int, str | None]] = [(cql2, 1, None)]
    while pending:
        node, depth, key = pending.pop()
        deepest = max(deepest, depth)
        if isinstance(node, dict):
            pending.extend((v, depth + 1, k) for k, v in node.items())
        elif isinstance(node, list):
            pending.extend((v, depth + 1, None) for v in node)
        elif key not in ("property", "op"):
            values += 1
    return values, deepest


def widget_filter_cql2(
    value: Any,
    types: Mapping[str, str] | None = None,
    *,
    unsafe_integers: bool = False,
) -> WidgetFilter:
    """The CQL2 the viewer sends for a normalized widget filter.

    ``types`` maps the layer's columns to their types, which decide how a
    date or timestamp literal is written. Raises ``FilterValidationError``
    for any shape the converter would not send. ``unsafe_integers`` accepts a
    whole number past JavaScript's safe range where its column's type allows
    one, as the viewer's layer-filter converter does.
    """
    if value is None:
        return WidgetFilter(None, frozenset(), 0, 0)
    token = _UNSAFE_INTEGERS.set(unsafe_integers)
    try:
        builder = _Builder(types)
        expression = _legacy(value) if _classify(value) == "legacy" else value
        cql2 = builder.tree(expression)
    finally:
        _UNSAFE_INTEGERS.reset(token)
    values, depth = measure_cql2(cql2) if cql2 is not None else (0, 0)
    return WidgetFilter(cql2, frozenset(builder.columns), values, depth)
