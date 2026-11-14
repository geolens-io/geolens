"""Exact aggregates over one dataset's rows, for dashboard and story widgets.

Server-built SQL from a validated request runs through the read-only sandbox
(``execute_safe``) under a statement timeout. A map-view request the planner
expects to read more than ``MAX_VIEW_ROWS`` rows is refused, never
approximated. Results are cached per dataset ``tile_cache_version``, which
rolls on every in-app write to the live table.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import math
from decimal import Decimal
from collections.abc import Sequence
from typing import Any, NamedTuple

from pydantic import BaseModel
from sqlalchemy import BigInteger, bindparam, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import is_query_canceled
from app.core.geo import extent_to_span_bbox
from app.modules.catalog.datasets.domain.column_stats import (
    _NUMERIC_TYPES,
    _json_number,
    _sql_quote_ident,
    value_expr,
)
from app.modules.catalog.datasets.domain.aggregate_rows import (
    DATE_TYPES,
    bucket_sql,
    AFTER_GID_BIND,
    decode_cursor,
    encode_cursor,
    rows_sql,
)
from app.modules.catalog.datasets.domain.aggregate_schemas import (
    AggregateRequest,
    AggregateResponse,
    AggregateRow,
    CountResult,
    GroupByRequest,
    GroupByResult,
    GroupValue,
    HistogramBin,
    HistogramResult,
    RowsRequest,
    RowsResult,
    StatsResult,
    ValueCount,
    ValueCountsResult,
    _respond,
)
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.service import (
    _safe_table_ref,
    compile_layer_filter,
    is_sortable_column,
    preview_slot_bound,
)
from app.modules.catalog.features.service import (
    feature_table_exists,
    planner_row_estimate,
)
from app.platform.analysis_sql import binds_referenced_by, render_filtered_table_ref
from app.platform.dataset_origin import geolens_owns_table
from app.platform.cache import (
    get_cache,
    tenant_cache_context_available,
    tenant_cache_key,
)
from app.platform.extensions import get_catalog_port
from app.platform.sandbox.executor import execute_safe, raise_if_unavailable
from app.platform.sandbox.schemas import SandboxError
from app.platform.timestamptz_text import utc_timestamptz_text

# A 500k-row view took 0.4-0.7 s per aggregate on a 2M-row point table in a
# laptop's Docker PostgreSQL, well inside the timeout. Raise it once a
# measurement on the smallest supported deployment (Azure B1ms) allows.
MAX_VIEW_ROWS = 500_000
AGGREGATE_TIMEOUT_MS = 4_000
# Pydantic stops serializing at 255 levels, and the cache key serializes the
# filter. Filters the builder writes nest a few levels.
_MAX_FILTER_DEPTH = 64
_FLOAT_TYPES = frozenset({"real", "double precision"})
_INTEGER_TYPES = frozenset({"smallint", "integer", "bigint"})
# Integers at or past this lose precision as JavaScript numbers.
_JS_SAFE_INTEGER = 2**53
# Two widgets of one caller may run at once; a third waits for the client's
# retry. More would let a few callers hold every slot on a worker.
_CALLER_CONCURRENCY = 2
# Category keys are column values of any size; numbers need no cap.
_MAX_KEYED_RESULT_BYTES = 1 << 20
_WHOLE_LAYER_TTL = 24 * 3600
# Filters and views are caller-chosen keys. Long-lived entries for them would
# push the rate-limit counters out of a volatile-ttl Valkey, so they live as
# long as a tile and stay small.
_KEYED_TTL = 300
_MAX_CACHED_BYTES = 16 * 1024
# Direct SQL can change a registered table without rolling its version.
_REGISTERED_TTL = 60


# The same pool-derived size as analysis previews, as a separate pool so
# anonymous dashboard traffic cannot hold every preview slot.
_aggregate_slots = asyncio.Semaphore(preview_slot_bound())


class TableUnavailable(Exception):
    """The dataset's backing table is missing."""


class AggregateError(Exception):
    """A request refused before or while it runs; ``code`` is stable for clients."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _covers(bbox: Sequence[float], extent: object | None) -> bool:
    """Whether a non-crossing view contains the dataset's whole extent."""
    bounds = extent_to_span_bbox(extent)
    if bounds is None or bbox[0] > bbox[2]:
        return False
    return (
        bbox[0] <= bounds[0]
        and bbox[1] <= bounds[1]
        and bbox[2] >= bounds[2]
        and bbox[3] >= bounds[3]
    )


def _bbox_predicate(bbox: Sequence[float], alias: str) -> str:
    """Exact intersection with the view; a crossing view is two envelopes."""
    west, south, east, north = (float(v) for v in bbox)
    envelopes = [(west, east)] if west <= east else [(west, 180.0), (-180.0, east)]
    parts = [
        f"ST_Intersects({alias}.geom_4326, "
        f"ST_MakeEnvelope({x0!r}, {south!r}, {x1!r}, {north!r}, 4326))"
        for x0, x1 in envelopes
    ]
    return parts[0] if len(parts) == 1 else f"({' OR '.join(parts)})"


def _column_type(columns: dict[str, str], name: str, *, numeric: bool) -> str:
    data_type = columns.get(name)
    if data_type is None:
        raise AggregateError("invalid_column", f"Unknown column: {name!r}")
    if numeric and data_type not in _NUMERIC_TYPES:
        raise AggregateError(
            "invalid_column", f"Column {name!r} is not numeric ({data_type})"
        )
    return data_type


def _number_sql(column: str, data_type: str) -> str:
    """A numeric column as a number to aggregate, without losing a stored digit.

    float8 holds every real and double exactly, where a numeric cast keeps 15
    digits of one. money needs numeric to aggregate at all.
    """
    cast = "float8" if data_type in _FLOAT_TYPES else "numeric"
    return f"{_sql_quote_ident(column)}::{cast}"


def _view_predicates(bbox: Sequence[float] | None, *, covered: bool) -> list[str]:
    if bbox is not None:
        return [_bbox_predicate(bbox, "_t")]
    if covered:
        return ["_t.geom_4326 IS NOT NULL AND NOT ST_IsEmpty(_t.geom_4326)"]
    return []


# char(n) is left out: it pads an empty string, which the map filter can not match.
_UNPADDED_TEXT_TYPES = frozenset({"text", "character varying"})


def _key_sql(
    column: str,
    data_type: str,
    bucket: str | None = None,
    *,
    blank_as_null: bool = False,
) -> tuple[str, str]:
    """What a category groups on, and its returned key over the grouped ``_g._k``.

    A timestamptz groups on its value and is written afterwards in UTC text
    with the full year, since the tile text folds every year past 9999 into
    ``infinity``. Other types group on their JSON-ready form. A ``bucket``
    groups a date column by its UTC day, week, month or year. With
    ``blank_as_null``, a text column's empty strings group with its NULLs.
    """
    quoted = _sql_quote_ident(column)
    if bucket is not None:
        if data_type not in DATE_TYPES:
            raise AggregateError(
                "invalid_column", f"Column {column!r} is not a date ({data_type})"
            )
        return bucket_sql(quoted, data_type, bucket)
    if blank_as_null and data_type in _UNPADDED_TEXT_TYPES:
        return f"NULLIF({quoted}, '')", "_g._k"
    if data_type != "timestamp with time zone":
        return value_expr(quoted, data_type), "_g._k"
    return quoted, _full_year_utc_text("_g._k")


def _full_year_utc_text(ref: str) -> str:
    """A timestamptz as UTC text, keeping the year past 9999 the tile text drops."""
    utc = f"({ref} AT TIME ZONE 'UTC')"
    far_future = (
        f"to_char({utc}, 'YYYY-MM-DD\"T\"HH24:MI:SS')"
        f" || rtrim(rtrim(to_char({utc}, '.US'), '0'), '.') || '+00:00'"
    )
    return (
        f"CASE WHEN isfinite({ref}) AND {utc} >= '10000-01-01' THEN {far_future}"
        f" ELSE {utc_timestamptz_text(ref)} END"
    )


def _stat_sql(stat: str, column: str | None, columns: dict) -> str:
    """A statistic over ``column``, or a count of rows without one."""
    if column is None:
        return "count(*)"
    data_type = _column_type(columns, column, numeric=stat != "count")
    if stat == "count":
        return f"count({_sql_quote_ident(column)})"
    return f"{stat}({_number_sql(column, data_type)})"


def _stat_value(stat: str, value: Any) -> Any:
    """Counts as integers, averages as floats, and sums and extremes exactly."""
    if value is None:
        return None
    if stat == "count":
        return int(value)
    if stat == "avg" and isinstance(value, Decimal):
        return _json_number(value)
    return _exact(value)


def build_aggregate_sql(
    request: AggregateRequest,
    source: str,
    predicates: list[str],
    columns: dict,
    *,
    geometry: bool = False,
) -> str:
    """The aggregate SELECT for one request, reading ``source AS _t``.

    ``source`` comes from ``_safe_table_ref`` (narrowed by the compiled layer
    filter) and every column has been checked against the live table. Rows
    carry their envelope when the dataset has ``geometry``.
    """

    def from_where(*extra: str) -> str:
        preds = [*predicates, *extra]
        where = f" WHERE {' AND '.join(preds)}" if preds else ""
        return f" FROM {source} AS _t{where}"

    if request.op == "count":
        return f"SELECT count(*) AS _n{from_where()}"
    if request.op == "stats":
        _column_type(columns, request.column, numeric=True)
        selects = ", ".join(
            f"{_stat_sql(stat, request.column, columns)} AS _s{i}"
            for i, stat in enumerate(request.stats)
        )
        return f"SELECT {selects}{from_where()}"
    if request.op == "value_counts":
        group, key = _key_sql(
            request.column,
            _column_type(columns, request.column, numeric=False),
            blank_as_null=request.blank_text_as_null,
        )
        return (
            f"SELECT {key} AS _k, _g._n, _g._total FROM ("
            f"SELECT {group} AS _k, count(*) AS _n, sum(count(*)) OVER () AS _total"
            f"{from_where()}"
            f" GROUP BY 1 ORDER BY 2 DESC, 1 NULLS LAST LIMIT {request.limit}"
            ") AS _g ORDER BY _g._n DESC, _g._k NULLS LAST"
        )
    if request.op == "histogram":
        data_type = _column_type(columns, request.column, numeric=True)
        number = _number_sql(request.column, data_type)
        quoted = _sql_quote_ident(request.column)
        bins = request.bins
        if data_type in _INTEGER_TYPES:
            # [a, a + w) holds a .. a + w - 1, by integer division on numeric
            # since float8 rounds a bigint. Edges lie in [lo, hi + 1]; when JSON
            # can't hold them exactly, w is NULL and the values take float bins.
            safe = _JS_SAFE_INTEGER - 1
            return (
                f"WITH _f AS (SELECT {number} AS x"
                f"{from_where(f'{quoted} IS NOT NULL')}),"
                " _r AS (SELECT min(x) AS lo, max(x) AS hi FROM _f),"
                f" _s AS (SELECT lo, hi, CASE WHEN lo >= -{safe} AND hi < {safe}"
                f" THEN greatest(1, div(hi - lo + {bins}, {bins})) END AS w FROM _r)"
                " SELECT _s.lo AS _lo, _s.hi AS _hi, CASE"
                " WHEN _s.w IS NOT NULL THEN div(_f.x - _s.lo, _s.w)::int"
                " WHEN _s.hi::float8 = _s.lo::float8 THEN 1 ELSE least(width_bucket("
                f"_f.x::float8, _s.lo::float8, _s.hi::float8, {bins}), {bins}) END AS _b,"
                " count(*) AS _n, _s.w AS _w"
                " FROM _f CROSS JOIN _s GROUP BY 1, 2, 3, 5 ORDER BY 3"
            )
        native = data_type == "numeric"
        cast = "" if native else "::float8"
        finite = (
            "x <> 'NaN'::numeric AND x <> 'Infinity'::numeric"
            " AND x <> '-Infinity'::numeric"
            if native
            else "x > '-Infinity'::float8 AND x < 'Infinity'::float8"
        )
        # Values enter the decimal arithmetic as their shortest round-trip text.
        dec = "" if native else "::text::numeric"
        limit = (
            "3.4028234663852886e38" if data_type == "real" else "1.7976931348623157e308"
        )
        # money has no float or numeric pick filter to agree with.
        rounded = native or data_type in _FLOAT_TYPES

        def edge(i: str) -> str:
            return f"(_t.start + ({i}) * _t.st){cast}"

        # s1 is the 1-2-5 step nearest above (hi - lo) / bins; one bump to the
        # next step keeps the bin count in range. Rounded edges are used only
        # when they are distinct and finite in the comparison's arithmetic
        # (mode 0); otherwise the request is binned equal-width (mode 2).
        return (
            f"WITH _v AS (SELECT {number}{cast} AS x"
            f"{from_where(f'{quoted} IS NOT NULL')}),"
            f" _f AS (SELECT x FROM _v WHERE {finite}),"
            " _r AS (SELECT min(x) AS flo, max(x) AS fhi FROM _f),"
            f" _p AS (SELECT flo{dec} AS lo, fhi{dec} AS hi,"
            f" (fhi{dec} - flo{dec}) / {bins} AS raw FROM _r"
            f" WHERE fhi{dec} > flo{dec}),"
            " _m AS (SELECT lo, hi, raw, power(10::numeric, floor(log(raw))) AS mag"
            " FROM _p),"
            " _k AS (SELECT lo, hi, mag, CASE WHEN raw <= mag THEN 1"
            " WHEN raw <= 2 * mag THEN 2 WHEN raw <= 5 * mag THEN 5 ELSE 10 END AS k"
            " FROM _m),"
            " _s1 AS (SELECT lo, hi, k, mag * k AS s1 FROM _k),"
            " _s AS (SELECT lo, hi, CASE WHEN ceil(hi / s1) - floor(lo / s1) > "
            f"{bins} THEN s1 * CASE k WHEN 2 THEN 2.5 ELSE 2 END ELSE s1 END AS st"
            " FROM _s1),"
            " _g AS (SELECT lo, hi, st, floor(lo / st) * st AS start,"
            " ceil(hi / st) - floor(lo / st) AS nb FROM _s),"
            " _e AS (SELECT st, start, nb, CASE WHEN "
            f"{'true' if rounded else 'false'}"
            " AND st >= 1e-300 AND greatest(abs(start), abs(start + nb * st)) <= "
            f"'{limit}'::numeric AND st >= 1e-15 * greatest(abs(start),"
            " abs(start + nb * st)) THEN 0 ELSE 2 END AS mode FROM _g),"
            " _t AS (SELECT _f.x, _r.flo, _r.fhi, _e.start, _e.st, _e.nb, _e.mode,"
            f" least(greatest(floor((_f.x{dec} - _e.start) / _e.st), 0), _e.nb - 1)"
            " AS b0 FROM _f CROSS JOIN _r LEFT JOIN _e ON true)"
            " SELECT _t.flo AS _lo, _t.fhi AS _hi, CASE WHEN _t.mode IS NULL THEN 1"
            " WHEN _t.mode = 2 THEN least(width_bucket(_t.x::float8, _t.flo::float8,"
            f" _t.fhi::float8, {bins}), {bins})"
            " ELSE greatest(0, least(_t.nb - 1,"
            f" _t.b0 + CASE WHEN _t.x < {edge('_t.b0')} THEN -1"
            f" WHEN _t.b0 < _t.nb - 1 AND _t.x >= {edge('_t.b0 + 1')} THEN 1"
            " ELSE 0 END))::int END AS _b,"
            " count(*) AS _n, _t.start AS _start, _t.st AS _step, _t.nb AS _nb,"
            " _t.mode AS _mode"
            " FROM _t GROUP BY 1, 2, 3, 5, 6, 7, 8 ORDER BY 3"
        )
    if request.op == "rows":
        return _rows_sql(request, source, predicates, columns, geometry=geometry)
    return _group_by_sql(request, columns, from_where())


def _group_by_sql(request: GroupByRequest, columns: dict, from_where: str) -> str:
    group, key = _key_sql(
        request.group_column,
        _column_type(columns, request.group_column, numeric=False),
        request.date_bucket,
        blank_as_null=request.blank_text_as_null,
    )
    values = [_stat_sql(s.stat, s.column, columns) for s in request.stats]
    names = [f"_v{i}" for i in range(len(values))]
    direction = request.sort.upper()
    # The inner query orders by position (1 is the group), the outer by name.
    if request.sort_by == "group":
        inner = f"1 {direction} NULLS LAST"
        outer = f"_g._k {direction} NULLS LAST"
    else:
        inner = f"{request.sort_by + 2} {direction} NULLS LAST, 1 NULLS LAST"
        outer = f"_g.{names[request.sort_by]} {direction} NULLS LAST, _g._k NULLS LAST"
    selects = ", ".join(f"{v} AS {n}" for v, n in zip(values, names))
    # One group past the limit tells whether any were left out.
    return (
        f"SELECT {key} AS _k, {', '.join(f'_g.{n}' for n in names)}"
        f" FROM (SELECT {group} AS _k, {selects}{from_where}"
        f" GROUP BY 1 ORDER BY {inner} LIMIT {request.limit + 1})"
        f" AS _g ORDER BY {outer}"
    )


def _rows_sql(
    request: RowsRequest,
    source: str,
    predicates: list[str],
    columns: dict,
    *,
    geometry: bool,
) -> str:
    def ref(name: str) -> str:
        return f"_t.{_sql_quote_ident(name)}"

    values = []
    for name in request.columns:
        data_type = _column_type(columns, name, numeric=False)
        # Geometry and other extension types, as the rows endpoint leaves out.
        if data_type == "user-defined":
            raise AggregateError(
                "invalid_column", f"Column {name!r} cannot be listed ({data_type})"
            )
        values.append(
            _full_year_utc_text(ref(name))
            if data_type == "timestamp with time zone"
            else value_expr(ref(name), data_type)
        )
    sort = None
    if request.sort_column is not None:
        data_type = _column_type(columns, request.sort_column, numeric=False)
        if not is_sortable_column(request.sort_column, data_type):
            raise AggregateError(
                "invalid_column",
                f"Column {request.sort_column!r} cannot be sorted ({data_type})",
            )
        sort = ref(request.sort_column)
    return rows_sql(
        source,
        predicates,
        values,
        sort=sort,
        descending=request.sort == "desc",
        paged=request.cursor is not None,
        limit=request.limit,
        with_bbox=geometry,
    )


def _whole_number_histogram(rows: Sequence[Sequence[Any]]) -> HistogramResult:
    """Bins of ``w`` whole numbers from the minimum; the last stops after the maximum."""
    low, high, width = int(rows[0][0]), int(rows[0][1]), int(rows[0][4])
    counts = {int(row[2]): int(row[3]) for row in rows}
    count = -(-(high - low + 1) // width)
    return HistogramResult(
        bins=[
            HistogramBin(
                lower=low + i * width,
                upper=min(low + (i + 1) * width, high + 1),
                count=counts.get(i, 0),
            )
            for i in range(count)
        ],
        whole_numbers=True,
    )


def _histogram(rows: Sequence[Sequence[Any]], bins: int) -> HistogramResult:
    """Bins of a non-integer column, with rounded edges.

    The step is the smallest of 1, 2, 5 times a power of ten that covers the
    range in at most ``bins`` bins; the first edge is the multiple of the step
    at or below the minimum, the last at or above the maximum. A maximum on the
    last edge counts in the last bin. Rounded edges are used only while they
    are finite and distinct in the column's own arithmetic (a double for
    ``real`` and ``double precision``, decimal for ``numeric``); otherwise,
    and for other types, the bins are equal-width with repeated edges merged.
    All values equal give one bin; one requested bin whose rounded edges need
    two spans them both.
    """
    if not rows:
        return HistogramResult(bins=[])
    # An integer column's rows carry a fifth value, the width of its
    # whole-number bins, or NULL when it was binned as floats.
    if len(rows[0]) == 5 and rows[0][4] is not None:
        return _whole_number_histogram(rows)
    low, high = float(rows[0][0]), float(rows[0][1])
    if len(rows[0]) == 5 or rows[0][7] == 2:
        return _float_fallback_histogram(rows, low, high, bins)
    if rows[0][7] is None:
        return HistogramResult(
            bins=[
                HistogramBin(lower=low, upper=high, count=sum(int(r[3]) for r in rows))
            ]
        )
    start, step = Decimal(str(rows[0][4])), Decimal(str(rows[0][5]))
    count = int(rows[0][6])
    counts: dict[int, int] = {}
    for row in rows:
        counts[int(row[2])] = counts.get(int(row[2]), 0) + int(row[3])
    if count > bins:
        # One bin can't be rounded on both sides without straddling a multiple.
        return HistogramResult(
            bins=[
                HistogramBin(
                    lower=float(start),
                    upper=float(start + count * step),
                    count=sum(counts.values()),
                )
            ]
        )
    return HistogramResult(
        bins=[
            HistogramBin(
                lower=float(start + i * step),
                upper=float(start + (i + 1) * step),
                count=counts.get(i, 0),
            )
            for i in range(count)
        ]
    )


def _float_fallback_histogram(
    rows: Sequence[Sequence[Any]], low: float, high: float, bins: int
) -> HistogramResult:
    """Equal-width bins, with edges that do not repeat.

    Values that sit on a repeated edge belong to the bin that starts there.
    """
    if low == high:
        return HistogramResult(
            bins=[
                HistogramBin(lower=low, upper=high, count=sum(int(r[3]) for r in rows))
            ]
        )
    counts = {int(row[2]): int(row[3]) for row in rows}
    # A weighted mean of the ends stays finite where high - low would overflow.
    edges = [low * (1 - i / bins) + high * (i / bins) for i in range(bins + 1)]
    # Rounding over adjacent doubles can step an edge backwards.
    for i in range(1, len(edges)):
        edges[i] = max(edges[i], edges[i - 1])
    distinct = sorted(set(edges))
    merged = [0] * (len(distinct) - 1)
    for i in range(bins):
        merged[min(distinct.index(edges[i]), len(merged) - 1)] += counts.get(i + 1, 0)
    return HistogramResult(
        bins=[
            HistogramBin(lower=distinct[i], upper=distinct[i + 1], count=merged[i])
            for i in range(len(merged))
        ]
    )


def _exact(value: Any) -> Any:
    """A value as JSON without losing precision.

    An integer within JavaScript's safe range, a float that reads back as the
    same number, or else PostgreSQL's text for it.
    """
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return (
            "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
        )
    if isinstance(value, int) and not isinstance(value, bool):
        return value if abs(value) < _JS_SAFE_INTEGER else str(value)
    if not isinstance(value, Decimal):
        return value
    if not value.is_finite():
        return str(value)
    integral = value.to_integral_value()
    if value == integral:
        # format, not str(int(...)): Python refuses int-to-str past 4,300 digits.
        return (
            int(integral) if abs(integral) < _JS_SAFE_INTEGER else format(integral, "f")
        )
    as_float = float(value)
    return as_float if Decimal(repr(as_float)) == value else str(value)


def _rows_result(
    request: RowsRequest, rows: Sequence[Sequence[Any]], *, more: bool
) -> RowsResult:
    page = rows[: request.limit]
    width = 1 + len(request.columns)
    listed = []
    for row in page:
        entry = {
            "gid": _exact(row[0]),
            "values": {
                name: _exact(value)
                for name, value in zip(request.columns, row[1:width])
            },
        }
        if len(row) > width:
            entry["bbox"] = row[width]
        listed.append(AggregateRow.model_validate(entry))
    has_more = more or len(rows) > request.limit
    return RowsResult(
        rows=listed,
        has_more=has_more,
        next_cursor=(
            encode_cursor(page[-1][0], request.sort_column, request.sort)
            if has_more
            else None
        ),
    )


def _result(
    request: AggregateRequest, rows: Sequence[Sequence[Any]], *, more: bool = False
) -> BaseModel:
    """The result of ``rows``; ``more`` says the byte cap cut a row past the limit."""
    if request.op == "count":
        return CountResult(count=int(rows[0][0]))
    if request.op == "stats":
        return StatsResult(
            **{
                stat: _stat_value(stat, value)
                for stat, value in zip(request.stats, rows[0])
            }
        )
    if request.op == "value_counts":
        listed = [ValueCount(value=_exact(r[0]), count=int(r[1])) for r in rows]
        total = int(rows[0][2]) if rows else 0
        return ValueCountsResult(
            values=listed, other_count=total - sum(v.count for v in listed)
        )
    if request.op == "histogram":
        return _histogram(rows, request.bins)
    if request.op == "rows":
        return _rows_result(request, rows, more=more)
    groups = []
    for r in rows[: request.limit]:
        values = [_stat_value(s.stat, v) for s, v in zip(request.stats, r[1:])]
        multi = {} if request._single else {"values": values}
        groups.append(GroupValue(key=_exact(r[0]), value=values[0], **multi))
    return GroupByResult(groups=groups, truncated=more or len(rows) > request.limit)


async def _sandboxed(
    db: AsyncSession,
    sql: str,
    binds: list[Any],
    caller_key: str,
    *,
    row_limit: int,
    max_result_bytes: int | None = None,
):
    """Run under one of the caller's lock keys; ``query_busy`` once all are held."""
    run = functools.partial(
        execute_safe,
        db,
        sql,
        row_limit=row_limit,
        timeout_ms=AGGREGATE_TIMEOUT_MS,
        require_reader_role=True,
        max_result_bytes=max_result_bytes,
        binds=binds_referenced_by(sql, binds),
    )
    keys = [f"aggregate:{caller_key}:{slot}" for slot in range(_CALLER_CONCURRENCY)]
    for key in keys[:-1]:
        try:
            return await run(concurrency_key=key)
        except SandboxError as exc:
            if exc.category != "query_busy":
                raise
    return await run(concurrency_key=keys[-1])


async def _planned_rows(
    db: AsyncSession, planned_source: str, bbox: Sequence[float], binds: list[Any]
) -> int:
    """The planner's row estimate for a view, under the aggregate timeout."""
    await db.execute(text(f"SET LOCAL statement_timeout = {AGGREGATE_TIMEOUT_MS}"))
    try:
        return await planner_row_estimate(
            db,
            planned_source,
            f"WHERE {_bbox_predicate(bbox, 't')}",
            {},
            lambda stmt: stmt.bindparams(*binds_referenced_by(planned_source, binds)),
        )
    except DBAPIError as exc:
        if is_query_canceled(exc):
            raise SandboxError("query_timeout", "Query timed out") from exc
        raise_if_unavailable(exc)
        raise


def _row_limit(request: AggregateRequest) -> int:
    """The most rows a request's SQL returns: one past its limit, when it has one."""
    if request.op == "histogram":
        return request.bins + 1
    limit = getattr(request, "limit", None)
    return 1 if limit is None else limit + 1


async def _aggregate_rows(
    db: AsyncSession,
    request: AggregateRequest,
    sql: str,
    binds: list[Any],
    caller_key: str,
) -> tuple[list, bool]:
    """The rows, and whether the byte cap cut only the row past the limit."""
    keyed = request.op in ("value_counts", "group_by", "rows")
    result = await _sandboxed(
        db,
        sql,
        binds,
        caller_key,
        row_limit=_row_limit(request),
        max_result_bytes=_MAX_KEYED_RESULT_BYTES if keyed else None,
    )
    # Only the byte cap can cut rows here (the SQL LIMIT is within the row
    # limit). Losing the row past the limit loses nothing but the sign that more
    # follow; any other cut list is not an exact answer.
    probe_cut = (
        result.truncated
        and request.op in ("group_by", "rows")
        and len(result.rows) == request.limit
    )
    if result.truncated and not probe_cut:
        raise SandboxError(
            "result_too_large",
            "These values are too large to return together. Choose a smaller limit.",
        )
    return result.rows, probe_cut


def _check_filter_depth(cql2: Any) -> None:
    """Refuse a filter nested past ``_MAX_FILTER_DEPTH``, without recursing."""
    pending = [(cql2, 1)]
    while pending:
        node, depth = pending.pop()
        if depth > _MAX_FILTER_DEPTH:
            raise AggregateError(
                "invalid_filter", "Invalid CQL2 expression: filter nests too deeply"
            )
        children = node.values() if isinstance(node, dict) else node
        if isinstance(node, (dict, list)):
            pending.extend((child, depth + 1) for child in children)


# Part of each result's cache key, so a server never reads an answer cached in
# another result format; at 4, a group_by says whether it left groups out.
_RESULT_FORMAT = 4


def _cache_key(prefix: str, dataset: Dataset, body: dict) -> str | None:
    if not tenant_cache_context_available():
        return None
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return tenant_cache_key(
        f"{prefix}:{dataset.id}:{dataset.tile_cache_version}:{digest}"
    )


def _cursor_binds(request: AggregateRequest) -> list[Any]:
    """The gid a page of rows continues after, or none for a first page."""
    if request.op != "rows" or request.cursor is None:
        return []
    try:
        gid = decode_cursor(request.cursor, request.sort_column, request.sort)
    except ValueError as exc:
        raise AggregateError(
            "invalid_cursor", "This cursor does not continue this list."
        ) from exc
    return [bindparam(AFTER_GID_BIND, gid, type_=BigInteger)]


class _Compiled(NamedTuple):
    sql: str
    binds: list[Any]
    source: str
    planned_source: str
    predicates: list[str]


async def _compile(
    db: AsyncSession,
    dataset: Dataset,
    request: AggregateRequest,
    bbox: Sequence[float] | None,
    *,
    covered: bool,
    allowed_columns: list[str] | None,
) -> _Compiled:
    """Build the request's SQL over the live columns the caller may read.

    A column outside ``allowed_columns`` is refused exactly as a missing one.
    """
    live = await get_catalog_port().get_column_info(db, dataset.table_name)
    if allowed_columns is not None:
        allowed = set(allowed_columns)
        live = [col for col in live if col["name"] in allowed]
    try:
        layer_filter = await compile_layer_filter(
            db, dataset, request.filter, bind_prefix="agg_filter", live_columns=live
        )
    except ValueError as exc:
        raise AggregateError("invalid_filter", str(exc)) from exc
    where_sql, binds = layer_filter if layer_filter else (None, [])
    columns = {col["name"]: str(col["type"]).lower() for col in live}
    source = render_filtered_table_ref(_safe_table_ref(dataset.table_name), where_sql)
    predicates = _view_predicates(bbox, covered=covered)
    # The request session has no tenant schema rewrite, so EXPLAIN reads the
    # resolved table rather than the sandbox's logical reference.
    planned_source = render_filtered_table_ref(
        get_catalog_port().quote_table(dataset.table_name), where_sql
    )
    sql = build_aggregate_sql(
        request, source, predicates, columns, geometry=bool(dataset.geometry_type)
    )
    return _Compiled(
        sql,
        [*binds, *_cursor_binds(request)],
        source,
        planned_source,
        predicates,
    )


async def _compile_narrowed(
    db: AsyncSession,
    dataset: Dataset,
    request: AggregateRequest,
    bbox: Sequence[float] | None,
    *,
    covered: bool,
    allowed_columns: list[str] | None,
) -> _Compiled | None:
    """Compile a narrowed caller's request before the caches are read.

    The caches hold answers computed for callers who may read every column.
    Returns None for a caller who may read every column.
    """
    if allowed_columns is None:
        return None
    return await _compile(
        db, dataset, request, bbox, covered=covered, allowed_columns=allowed_columns
    )


def _too_wide() -> AggregateError:
    return AggregateError(
        "too_wide",
        "This view holds too many features to summarize exactly, or counting "
        "them took too long. Zoom in, or try again later.",
    )


async def _count_exceeds_view_limit(
    db: AsyncSession, source: str, predicate: str, binds: list[Any], caller_key: str
) -> bool:
    """Whether the view holds more than ``MAX_VIEW_ROWS`` rows, counted exactly."""
    probe = (
        f"SELECT count(*) FROM (SELECT 1 FROM {source} AS _t"
        f" WHERE {predicate} LIMIT {MAX_VIEW_ROWS + 1}) AS _n"
    )
    try:
        counted = await _sandboxed(db, probe, binds, caller_key, row_limit=1)
    except SandboxError as exc:
        # A view that cannot be counted to the limit in time cannot be
        # aggregated exactly either.
        if exc.category != "query_timeout":
            raise
        return True
    return int(counted.rows[0][0]) > MAX_VIEW_ROWS


async def run_aggregate(
    db: AsyncSession,
    dataset: Dataset,
    request: AggregateRequest,
    *,
    caller_key: str,
    allowed_columns: list[str] | None = None,
) -> AggregateResponse:
    """Compute one aggregate exactly, from the cache when it holds the answer.

    The caller has already authorized ``dataset`` and checked it has a feature
    table. ``caller_key`` names the caller for its concurrency lock.
    ``allowed_columns``, when given, are the only columns the request may read.
    Raises ``AggregateError`` for a request it refuses and ``SandboxError``
    when the query cannot run. Releases ``db``'s connection before the query,
    so the caller must not read ORM state from it afterwards.
    """
    _check_filter_depth(request.filter)
    bbox = request.bbox
    if bbox is not None and not dataset.geometry_type:
        raise AggregateError("no_geometry", "This dataset has no geometry to bound")
    # A registered table's stored count and extent can be stale.
    owned = geolens_owns_table(
        dataset.source_format, dataset.record.record_type, dataset.origin_ref
    )
    # A view around the whole extent skips the view limit, but still leaves
    # out the rows with no geometry, which no view contains.
    covered = (
        owned and bbox is not None and _covers(bbox, dataset.record.spatial_extent)
    )
    if covered:
        bbox = None
    whole_layer = owned and bbox is None and request.filter is None
    if not await feature_table_exists(db, dataset.table_name):
        raise TableUnavailable(dataset.table_name)
    if (
        whole_layer
        and not covered
        and request.op == "count"
        and dataset.feature_count is not None
    ):
        return _respond("count", {"count": dataset.feature_count}, cached=False)

    compiled = await _compile_narrowed(
        db, dataset, request, bbox, covered=covered, allowed_columns=allowed_columns
    )
    cache_key = _cache_key(
        "aggregate",
        dataset,
        request.model_dump(mode="json")
        | {
            "bbox": bbox,
            "covered": covered,
            "format": _RESULT_FORMAT,
            # Both group_by forms read as one `stats` list but answer in two shapes.
            "single": request.op == "group_by" and request._single,
        },
    )
    cached = await get_cache().get(cache_key) if cache_key is not None else None
    if cached is not None:
        return _respond(request.op, cached, cached=True)
    keyed_ttl = _KEYED_TTL if owned else _REGISTERED_TTL
    # Whether a view is too wide depends on the filter and the view, not the
    # op, so every widget on a layer shares one verdict.
    verdict_key = (
        _cache_key("aggregate-view", dataset, {"filter": request.filter, "bbox": bbox})
        if bbox is not None
        else None
    )
    verdict = await get_cache().get(verdict_key) if verdict_key is not None else None
    if verdict:
        raise _too_wide()
    judge_view = bbox is not None and verdict is None

    if compiled is None:
        compiled = await _compile(
            db, dataset, request, bbox, covered=covered, allowed_columns=allowed_columns
        )
    sql, binds, source, planned_source, predicates = compiled

    if _aggregate_slots.locked():
        raise SandboxError(
            "query_at_capacity",
            "The server is running its maximum number of aggregates. "
            "Try again in a moment.",
        )
    async with _aggregate_slots:
        over_estimate = False
        if judge_view:
            estimate = await _planned_rows(db, planned_source, bbox, binds)
            over_estimate = estimate > MAX_VIEW_ROWS
        # Detached first: the rollback that returns the pooled connection
        # would expire every loaded instance, the caller's user included.
        db.expunge_all()
        await db.rollback()

        if judge_view:
            too_wide = False
            if over_estimate:
                # Statistics can overstate a view; count it exactly, up to the
                # limit, before telling the reader to zoom in.
                too_wide = await _count_exceeds_view_limit(
                    db, source, predicates[0], binds, caller_key
                )
            if verdict_key is not None:
                await get_cache().set(verdict_key, too_wide, ttl=keyed_ttl)
            if too_wide:
                raise _too_wide()
        rows, more = await _aggregate_rows(db, request, sql, binds, caller_key)

    payload = _result(request, rows, more=more)
    encoded = payload.model_dump(mode="json")
    if cache_key is not None and len(json.dumps(encoded)) <= _MAX_CACHED_BYTES:
        await get_cache().set(
            cache_key, encoded, ttl=_WHOLE_LAYER_TTL if whole_layer else keyed_ttl
        )
    return _respond(request.op, payload, cached=False)
