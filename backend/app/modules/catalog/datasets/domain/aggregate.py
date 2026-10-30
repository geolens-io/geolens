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
from typing import Annotated, Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import sqlstate
from app.core.geo import extent_to_span_bbox
from app.modules.catalog.datasets.domain.column_stats import (
    _NUMERIC_TYPES,
    _json_number,
    _sql_quote_ident,
    value_expr,
)
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.service import (
    _safe_table_ref,
    compile_layer_filter,
    preview_slot_bound,
)
from app.modules.catalog.features.service import (
    feature_table_exists,
    parse_bbox,
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
from app.platform.sandbox.executor import execute_safe
from app.platform.sandbox.schemas import SandboxError
from app.platform.timestamptz_text import utc_timestamptz_text

# A 500k-row view took 0.4-0.7 s per aggregate on a 2M-row point table in a
# laptop's Docker PostgreSQL, well inside the timeout. Raise it once a
# measurement on the smallest supported deployment (Azure B1ms) allows.
MAX_VIEW_ROWS = 500_000
AGGREGATE_TIMEOUT_MS = 4_000
_MAX_ITEMS = 50
# Pydantic stops serializing at 255 levels, and the cache key serializes the
# filter. Filters the builder writes nest a few levels.
_MAX_FILTER_DEPTH = 64
_FLOAT_TYPES = frozenset({"real", "double precision"})
_INTEGER_TYPES = frozenset({"smallint", "integer", "bigint"})
# Integers at or past this lose precision as JavaScript numbers.
_JS_SAFE_INTEGER = 2**53
_QUERY_CANCELED = "57014"
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

StatName = Literal["count", "sum", "avg", "min", "max"]
ColumnName = Annotated[str, Field(min_length=1, max_length=63)]
Scalar = str | int | float | bool | None


class _AggregateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: dict[str, Any] | None = Field(
        None,
        description="CQL2-JSON filter, as the OGC API Features `filter` accepts.",
    )
    bbox: list[float] | None = Field(
        None,
        min_length=4,
        max_length=4,
        description=(
            "Map view `[west, south, east, north]` in WGS 84; west greater than "
            "east crosses the antimeridian. Omit for the whole layer."
        ),
    )

    @field_validator("bbox")
    @classmethod
    def _valid_bbox(cls, value: list[float] | None) -> list[float] | None:
        return None if value is None else parse_bbox(value)


class CountRequest(_AggregateBase):
    op: Literal["count"]


class StatsRequest(_AggregateBase):
    op: Literal["stats"]
    column: ColumnName
    stats: list[StatName] = Field(min_length=1, max_length=5)

    @field_validator("stats")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ValueCountsRequest(_AggregateBase):
    op: Literal["value_counts"]
    column: ColumnName
    limit: int = Field(10, ge=1, le=_MAX_ITEMS)


class HistogramRequest(_AggregateBase):
    op: Literal["histogram"]
    column: ColumnName
    bins: int = Field(10, ge=1, le=_MAX_ITEMS)


class GroupByRequest(_AggregateBase):
    op: Literal["group_by"]
    group_column: ColumnName
    stat: StatName
    column: ColumnName | None = Field(
        None, description="The numeric column `stat` reads; omit for `count`."
    )
    limit: int = Field(10, ge=1, le=_MAX_ITEMS)

    @model_validator(mode="after")
    def _column_for_stat(self) -> GroupByRequest:
        if self.stat != "count" and self.column is None:
            raise ValueError(f"group_by with stat {self.stat!r} needs a column")
        return self


AggregateRequest = Annotated[
    CountRequest
    | StatsRequest
    | ValueCountsRequest
    | HistogramRequest
    | GroupByRequest,
    Field(discriminator="op"),
]


class CountResult(BaseModel):
    count: int


class StatsResult(BaseModel):
    """The requested statistics; one over no rows is null.

    ``sum``, ``min`` and ``max`` are exact: a number when JSON can carry it
    exactly, else text. ``avg`` is a float, or text for NaN and infinity.
    """

    count: int | None = None
    sum: int | float | str | None = None
    avg: float | str | None = None
    min: int | float | str | None = None
    max: int | float | str | None = None


_EXACT_KEY = (
    "The column's value. A number JSON cannot carry exactly, such as an integer "
    "beyond 2^53 or NaN, comes back as text."
)


class ValueCount(BaseModel):
    value: Scalar = Field(description=_EXACT_KEY)
    count: int


class ValueCountsResult(BaseModel):
    values: list[ValueCount] = Field(description="Most frequent first.")
    other_count: int = Field(description="Rows whose value is not listed.")


class HistogramBin(BaseModel):
    lower: float
    upper: float
    count: int


class HistogramResult(BaseModel):
    bins: list[HistogramBin] = Field(
        description=(
            "Equal-width bins over the finite values, empty with none. Unless"
            " whole_numbers is true, a bin holds its lower edge but not its upper"
            " one, and the last bin holds both."
        )
    )
    whole_numbers: bool = Field(
        False,
        description=(
            "Whether each bin holds the whole numbers from its lower edge to one"
            " below its upper edge. Only an integer column has whole-number bins,"
            " and only while every edge is a safe JavaScript integer; they may"
            " then number fewer than requested, and the last may be narrower."
        ),
    )


class GroupValue(BaseModel):
    key: Scalar = Field(description=_EXACT_KEY)
    value: float | int | str | None = Field(
        description="Exact for count, sum, min and max, as for a key; avg is a float."
    )


class GroupByResult(BaseModel):
    groups: list[GroupValue] = Field(description="Largest value first.")


class _ResponseBase(BaseModel):
    approximate: Literal[False] = Field(
        False, description="Always false: a view too wide to count exactly is refused."
    )
    cached: bool


class CountResponse(_ResponseBase):
    op: Literal["count"]
    result: CountResult


class StatsResponse(_ResponseBase):
    op: Literal["stats"]
    result: StatsResult


class ValueCountsResponse(_ResponseBase):
    op: Literal["value_counts"]
    result: ValueCountsResult


class HistogramResponse(_ResponseBase):
    op: Literal["histogram"]
    result: HistogramResult


class GroupByResponse(_ResponseBase):
    op: Literal["group_by"]
    result: GroupByResult


# Keyed on ``op`` so a client's generated parser picks the result by operation.
AggregateResponse = Annotated[
    CountResponse
    | StatsResponse
    | ValueCountsResponse
    | HistogramResponse
    | GroupByResponse,
    Field(discriminator="op"),
]
_RESPONSES: dict[str, type[_ResponseBase]] = {
    "count": CountResponse,
    "stats": StatsResponse,
    "value_counts": ValueCountsResponse,
    "histogram": HistogramResponse,
    "group_by": GroupByResponse,
}


def _respond(op: str, result: Any, *, cached: bool) -> AggregateResponse:
    return _RESPONSES[op].model_validate({"op": op, "result": result, "cached": cached})


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


def _key_sql(column: str, data_type: str) -> tuple[str, str]:
    """What a category groups on, and its returned key over the grouped ``_g._k``.

    A timestamptz groups on its value and is written afterwards in UTC text
    with the full year, since the tile text folds every year past 9999 into
    ``infinity``. Other types group on their JSON-ready form.
    """
    quoted = _sql_quote_ident(column)
    if data_type != "timestamp with time zone":
        return value_expr(quoted, data_type), "_g._k"
    utc = "(_g._k AT TIME ZONE 'UTC')"
    far_future = (
        f"to_char({utc}, 'YYYY-MM-DD\"T\"HH24:MI:SS')"
        f" || rtrim(rtrim(to_char({utc}, '.US'), '0'), '.') || '+00:00'"
    )
    return quoted, (
        f"CASE WHEN isfinite(_g._k) AND {utc} >= '10000-01-01' THEN {far_future}"
        f" ELSE {utc_timestamptz_text('_g._k')} END"
    )


def _stat_sql(stat: str, column: str, data_type: str) -> str:
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
    request: AggregateRequest, source: str, predicates: list[str], columns: dict
) -> str:
    """The aggregate SELECT for one request, reading ``source AS _t``.

    ``source`` comes from ``_safe_table_ref`` (narrowed by the compiled layer
    filter) and every column has been checked against the live table.
    """

    def from_where(*extra: str) -> str:
        preds = [*predicates, *extra]
        where = f" WHERE {' AND '.join(preds)}" if preds else ""
        return f" FROM {source} AS _t{where}"

    if request.op == "count":
        return f"SELECT count(*) AS _n{from_where()}"
    if request.op == "stats":
        data_type = _column_type(columns, request.column, numeric=True)
        selects = ", ".join(
            f"{_stat_sql(stat, request.column, data_type)} AS _s{i}"
            for i, stat in enumerate(request.stats)
        )
        return f"SELECT {selects}{from_where()}"
    if request.op == "value_counts":
        group, key = _key_sql(
            request.column, _column_type(columns, request.column, numeric=False)
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
        head = (
            f"WITH _v AS (SELECT {number}::float8 AS x"
            f"{from_where(f'{quoted} IS NOT NULL')}),"
            " _f AS (SELECT x FROM _v"
            " WHERE x > '-Infinity'::float8 AND x < 'Infinity'::float8),"
        )
        return (
            f"{head} _r AS (SELECT min(x) AS lo, max(x) AS hi FROM _f)"
            " SELECT _r.lo AS _lo, _r.hi AS _hi, CASE WHEN _r.hi = _r.lo THEN 1"
            f" ELSE least(width_bucket(_f.x, _r.lo, _r.hi, {bins}), {bins}) END AS _b,"
            " count(*) AS _n FROM _f CROSS JOIN _r GROUP BY 1, 2, 3 ORDER BY 3"
        )
    group, key = _key_sql(
        request.group_column,
        _column_type(columns, request.group_column, numeric=False),
    )
    if request.stat == "count":
        value = "count(*)"
    else:
        data_type = _column_type(columns, request.column, numeric=True)
        value = _stat_sql(request.stat, request.column, data_type)
    return (
        f"SELECT {key} AS _k, _g._v FROM ("
        f"SELECT {group} AS _k, {value} AS _v{from_where()}"
        f" GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1 NULLS LAST LIMIT {request.limit}"
        ") AS _g ORDER BY _g._v DESC NULLS LAST, _g._k NULLS LAST"
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
    if not rows:
        return HistogramResult(bins=[])
    # An integer column's rows carry a fifth value, the width of its
    # whole-number bins, or NULL when it was binned as floats.
    if len(rows[0]) == 5 and rows[0][4] is not None:
        return _whole_number_histogram(rows)
    low, high = float(rows[0][0]), float(rows[0][1])
    if low == high:
        return HistogramResult(
            bins=[HistogramBin(lower=low, upper=high, count=int(rows[0][3]))]
        )
    counts = {int(row[2]): int(row[3]) for row in rows}
    # A weighted mean of the ends stays finite where high - low would overflow.
    edges = [low * (1 - i / bins) + high * (i / bins) for i in range(bins + 1)]
    # Rounding over adjacent doubles can step an edge backwards.
    for i in range(1, len(edges)):
        edges[i] = max(edges[i], edges[i - 1])
    return HistogramResult(
        bins=[
            HistogramBin(lower=edges[i], upper=edges[i + 1], count=counts.get(i + 1, 0))
            for i in range(bins)
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


def _result(request: AggregateRequest, rows: Sequence[Sequence[Any]]) -> BaseModel:
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
    return GroupByResult(
        groups=[
            GroupValue(
                key=_exact(r[0]),
                value=_stat_value(request.stat, r[1]),
            )
            for r in rows
        ]
    )


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
            lambda stmt: stmt.bindparams(*binds) if binds else stmt,
        )
    except DBAPIError as exc:
        if sqlstate(exc) == _QUERY_CANCELED:
            raise SandboxError("query_timeout", "Query timed out") from exc
        raise


async def _aggregate_rows(
    db: AsyncSession,
    request: AggregateRequest,
    sql: str,
    binds: list[Any],
    caller_key: str,
) -> list:
    keyed = request.op in ("value_counts", "group_by")
    result = await _sandboxed(
        db,
        sql,
        binds,
        caller_key,
        row_limit=_MAX_ITEMS,
        max_result_bytes=_MAX_KEYED_RESULT_BYTES if keyed else None,
    )
    # Only the byte cap can cut rows here (the SQL LIMIT is within the row
    # limit), and a cut list is not an exact answer.
    if result.truncated:
        raise SandboxError(
            "result_too_large",
            "These values are too large to return together. Choose a smaller limit.",
        )
    return result.rows


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
# another result format; at 3, a histogram says whether its bins are whole numbers.
_RESULT_FORMAT = 3


def _cache_key(prefix: str, dataset: Dataset, body: dict) -> str | None:
    if not tenant_cache_context_available():
        return None
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return tenant_cache_key(
        f"{prefix}:{dataset.id}:{dataset.tile_cache_version}:{digest}"
    )


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
    return _Compiled(
        build_aggregate_sql(request, source, predicates, columns),
        binds,
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
        "too_wide", "This view holds too many features to summarize exactly. Zoom in."
    )


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
        | {"bbox": bbox, "covered": covered, "format": _RESULT_FORMAT},
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
                probe = (
                    f"SELECT count(*) FROM (SELECT 1 FROM {source} AS _t"
                    f" WHERE {predicates[0]} LIMIT {MAX_VIEW_ROWS + 1}) AS _n"
                )
                counted = await _sandboxed(db, probe, binds, caller_key, row_limit=1)
                too_wide = int(counted.rows[0][0]) > MAX_VIEW_ROWS
            if verdict_key is not None:
                await get_cache().set(verdict_key, too_wide, ttl=keyed_ttl)
            if too_wide:
                raise _too_wide()
        rows = await _aggregate_rows(db, request, sql, binds, caller_key)

    payload = _result(request, rows)
    encoded = payload.model_dump(mode="json")
    if cache_key is not None and len(json.dumps(encoded)) <= _MAX_CACHED_BYTES:
        await get_cache().set(
            cache_key, encoded, ttl=_WHOLE_LAYER_TTL if whole_layer else keyed_ttl
        )
    return _respond(request.op, payload, cached=False)
