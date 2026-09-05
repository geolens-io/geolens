"""Feature query service: paginated GeoJSON features from PostGIS data tables."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, NamedTuple

from shapely import to_geojson
from shapely.errors import GEOSException
from shapely.geometry import shape as shapely_shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity
from sqlalchemy import bindparam, func, select, text
from sqlalchemy import types as sa_types
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.pg_ranges import check_int8_range, check_pg_value_range
from app.core.geo import seam_extent_wkt_for_table
from app.platform.extensions import get_catalog_port

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import Dataset

# Column name validation for SQL identifier safety
_COLUMN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _parse_int(raw: str) -> int:
    # The per-type bound is applied by check_pg_value_range, which knows
    # whether the column is int2, int4 or int8 (fix(#1778 review r2)).
    return int(raw)


def _parse_float(raw: str) -> float:
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("must be a finite number")
    return value


def _parse_decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("must be a decimal number") from exc
    if not value.is_finite():
        raise ValueError("must be a finite number")
    return value


_BOOLEAN_LITERALS = {
    "true": True,
    "t": True,
    "yes": True,
    "y": True,
    "1": True,
    "false": False,
    "f": False,
    "no": False,
    "n": False,
    "0": False,
}


def _parse_bool(raw: str) -> bool:
    try:
        return _BOOLEAN_LITERALS[raw.strip().lower()]
    except KeyError as exc:
        raise ValueError("must be true or false") from exc


def _parse_naive_timestamp(raw: str) -> datetime:
    # A `timestamp without time zone` column cannot be compared with an aware
    # value: asyncpg refuses it at bind time. Normalize to UTC, the same
    # narrowing standards/ogc/filtering.py applies to CQL2 literals.
    value = datetime.fromisoformat(raw)
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# fix(#1778): property filters bound the raw query-string value, so SQLAlchemy
# typed every bind VARCHAR and PostgreSQL had no `bigint = character varying`
# operator: EVERY non-text property filter failed with 42883, which the OGC
# items handler then reported as a retryable 503. The queryables document
# (Part 3) advertises these columns as integer/number/boolean/date, so a
# conformant client was led straight into it. Each pg type here therefore
# carries the parser that turns the query-string value into a Python value and
# the database type the bind is compiled with. The families and their database
# types mirror `sa_type_for_pg` in standards/ogc/filtering.py, for the reason
# recorded there: a float8-cast bind against a REAL column promotes the stored
# float4 and stops comparing equal.
#
# The set is exactly the set the queryables document advertises as filterable.
# A column of any other type keeps the raw string bind, and the routers now
# classify the resulting type-shaped sqlstate as the caller's 400.
_PROPERTY_FILTER_BINDS: dict[str, tuple[Callable[[str], Any], Any]] = {
    "text": (str, sa_types.Text()),
    "character varying": (str, sa_types.Text()),
    "character": (str, sa_types.Text()),
    "smallint": (_parse_int, sa_types.BigInteger()),
    "integer": (_parse_int, sa_types.BigInteger()),
    "bigint": (_parse_int, sa_types.BigInteger()),
    "real": (_parse_float, sa_types.REAL()),
    "double precision": (_parse_float, sa_types.Float()),
    "numeric": (_parse_decimal, sa_types.Numeric()),
    "boolean": (_parse_bool, sa_types.Boolean()),
    "date": (date.fromisoformat, sa_types.Date()),
    "timestamp without time zone": (_parse_naive_timestamp, sa_types.DateTime()),
    "timestamp with time zone": (
        datetime.fromisoformat,
        sa_types.DateTime(timezone=True),
    ),
}


def _property_filter_bind(param_name: str, column: str, pg_type: str | None, raw: str):
    """Return a typed BindParameter for one `column = value` filter, or None.

    None means "no mapping for this column type": the caller keeps today's raw
    string bind, and the routers classify whatever the database says about it.
    Raises ValueError, naming the property, when the value does not parse for
    the column's type — the caller's 400, not a database round trip.
    """
    mapping = _PROPERTY_FILTER_BINDS.get(pg_type or "")
    if mapping is None:
        return None
    parse, sa_type = mapping
    try:
        value = parse(raw)
        # fix(#1778 review r2): in range for the COLUMN, not merely parseable
        # as a Python value. 1e100 against a real column and 2147483648 against
        # an integer column are both legal comparisons that no stored value can
        # satisfy, so they used to answer 200 with zero features -- a silently
        # wrong answer to a question the caller did not ask.
        check_pg_value_range(pg_type or "", value)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"Invalid value for property {column!r} (type {pg_type}): {exc}"
        ) from exc
    return bindparam(param_name, value, type_=sa_type)


# Maps GeoJSON geometry type to the set of compatible PostGIS geometry types.
# Single types are allowed into Multi columns (PostGIS promotes implicitly).
GEOJSON_TYPE_MAP: dict[str, set[str]] = {
    "Point": {"Point", "MultiPoint"},
    "MultiPoint": {"MultiPoint"},
    "LineString": {"LineString", "MultiLineString"},
    "MultiLineString": {"MultiLineString"},
    "Polygon": {"Polygon", "MultiPolygon"},
    "MultiPolygon": {"MultiPolygon"},
    # fix(#430 codex r9/r20): a GeometryCollection is storable in a generic
    # GEOMETRY column (the generic branch only requires map presence) and in
    # a typed GEOMETRYCOLLECTION column (ingested GC data — the dataset check
    # constraint allows the type). Every OTHER typed dataset reports a type
    # mismatch. Nested collections are rejected earlier at the schema guard.
    "GeometryCollection": {"GeometryCollection"},
}


_MULTI_TYPES = {"MULTIPOINT", "MULTILINESTRING", "MULTIPOLYGON"}


class UnwritablePropertyError(ValueError):
    """A column that exists but that the feature write path cannot address.

    fix(#1778): two guards disagreed about what a legal column is.
    ``_reject_unknown_properties`` admitted any key present in column_info,
    and the write loops then silently skipped whatever ``_COLUMN_NAME_RE``
    rejected — a strictly narrower pattern than every producer of column_info.
    ``create_empty_dataset`` validated against SAFE_COLUMN_NAME_RE (leading
    underscore allowed, no length bound), ``get_column_info`` copies
    information_schema verbatim, and the READ projection deliberately supports
    names this regex rejects (``live_property_columns`` escapes colons because
    registered Socrata exports ship columns literally named ``:id``).

    So a dataset with a ``_notes`` or ``:id`` column returned that key from GET
    but could not write it: POST and PUT answered 201/200 with the value never
    stored, and on PUT the column was not even NULLed, contradicting the
    documented "Columns not present in properties are set to NULL". Silent
    write loss behind a success response is the worst shape for a data-editing
    API, and it is exactly what an editing UI's read-modify-write round trip
    hits. Refusing names the write path cannot address turns it into a 422.
    """


def is_writable_feature_column(name: str) -> bool:
    """Whether the feature write path can address a column by this name.

    The canonical predicate: ``create_empty_dataset`` refuses to build a column
    that would fail it, and the write guards refuse to half-write one that
    already exists.
    """
    return bool(_COLUMN_NAME_RE.match(name))


def _reject_unknown_properties(
    properties: dict | None,
    column_info: list[dict],
    *,
    replaces_all: bool = False,
) -> None:
    """Raise if a property key names no real attribute column, or an unwritable one.

    fix(#458 E-25): writers used to silently drop unknown keys. On PUT that is a
    footgun — a misspelled key isn't written AND the intended column is nulled
    (replace sets every known column to `properties.get(name)`), all with a 200.
    Rejecting unknown keys up front surfaces the typo as a 400 instead. Reserved
    system columns (gid/geom/…) are absent from column_info, so a write attempt
    against them is correctly reported here too.

    fix(#1778): a key naming a real column the write loop would then skip is
    refused as well (see UnwritablePropertyError). ``replaces_all`` is the PUT
    spelling: replace writes EVERY known column, so one unwritable column in
    column_info makes the whole documented replacement impossible, whether or
    not the request mentions it.
    """
    allowed = {c["name"] for c in column_info}
    if properties:
        unknown = sorted(k for k in properties if k not in allowed)
        if unknown:
            raise ValueError(f"Unknown property columns: {', '.join(unknown)}")
    named = allowed if replaces_all else {k for k in (properties or {}) if k in allowed}
    unwritable = sorted(n for n in named if not is_writable_feature_column(n))
    if unwritable:
        raise UnwritablePropertyError(
            f"Unwritable property columns: {', '.join(unwritable)}. "
            "A writable column name is at most 63 characters, starts with a "
            "lowercase letter, and holds only lowercase letters, digits and "
            "underscores."
        )


def _geometry_sql(dataset_geometry_type: str) -> str:
    """Return the SQL expression for geometry insertion.

    If the dataset column is a Multi* type, wrap with ST_Multi to promote
    single-part geometries. ST_Multi is a no-op on already-multi geometries.
    """
    base = "ST_GeomFromGeoJSON(:geojson)"
    if dataset_geometry_type.strip().upper() in _MULTI_TYPES:
        return f"ST_Multi({base})"
    return base


def _geom_write_exprs(
    dataset_geometry_type: str, dataset_srid: int | None
) -> tuple[str, str]:
    """SQL expressions for the (geom, geom_4326) write pair.

    GeoJSON is WGS84 by spec, so ST_GeomFromGeoJSON yields SRID 4326 — correct
    for geom_4326, but file-ingested layers keep their source CRS in `geom`
    (the file path runs ogr2ogr without -t_srs), so writing 4326 into a
    projected-SRID column violates the typmod and 500s. Transform when the
    dataset SRID differs; dataset.srid mirrors Find_SRID on the live column
    (refresh_dataset_metadata), so it is the column's actual SRID.
    """
    base = _geometry_sql(dataset_geometry_type)
    if dataset_srid and dataset_srid != 4326:
        return f"ST_Transform({base}, {int(dataset_srid)})", base
    return base, base


def parse_bbox(bbox: str | Sequence[float]) -> list[float]:
    """Parse a bbox into a 4-element ``[minx, miny, maxx, maxy]`` list.

    Accepts either a comma-separated string (the query-parameter spelling) or
    an already-split sequence of numbers (the JSON request-body spelling, e.g.
    STAC Item Search POST), so every GeoLens surface answers a given bbox the
    same way.

    Accepts:
      - 4 values: minx, miny, maxx, maxy (2D)
      - 6 values: minx, miny, minz, maxx, maxy, maxz (3D — Z values are
        accepted but ignored for spatial queries)

    Allows antimeridian-crossing bboxes where minx > maxx (e.g. 170,-45,-170,-30).
    Allows degenerate boxes where miny == maxy: OGC API Features and STAC both
    define bbox bounds as lower <= upper, so a zero-height (line) or zero-area
    (point) box is a legal filter.
    Raises ValueError if not 4 or 6 values, or latitude bounds are invalid.
    """
    if isinstance(bbox, str):
        parts = bbox.split(",")
        if len(parts) not in (4, 6):
            raise ValueError("bbox must have 4 or 6 comma-separated values")
        values = [float(p) for p in parts]
    else:
        values = [float(v) for v in bbox]
        if len(values) not in (4, 6):
            raise ValueError("bbox must have 4 or 6 values")
    # SEC-FU-06 (sec-audit-20260519.md): reject NaN/Inf coordinates. Python's float() accepts
    # "nan", "inf", "-inf" (and JSON 1e400 parses to +Inf) — PostGIS handles these
    # inconsistently and they can produce malformed geometries with downstream
    # null-pointer or sequential-scan amplification. This is the single home for the
    # guard: STAC once carried its own copy and the guard had to be re-applied there
    # (#430 BA-12) because the copy existed.
    for i, v in enumerate(values):
        if not math.isfinite(v):
            raise ValueError(
                f"SEC-FU-06: bbox coordinate at index {i} is non-finite ({v!r}); "
                "only finite floats are accepted"
            )
    if len(values) == 6:
        # 3D bbox: extract 2D envelope (minx, miny, maxx, maxy)
        values = [values[0], values[1], values[3], values[4]]
    # Only validate latitude (lon wraps at antimeridian). Equality passes: the
    # spec bound is lower <= upper, and a degenerate box is a legal filter.
    if values[1] > values[3]:
        raise ValueError("bbox miny must be less than or equal to maxy")
    return values


async def live_property_columns(db: AsyncSession, table_name: str) -> str:
    """Quoted select-list of the table's live columns minus gid/geom/geom_4326.

    fix(#1104): feature properties used to be rendered as ``to_jsonb(t.*) -
    'gid' - 'geom' - 'geom_4326'``, which serializes EVERY column before the
    subtraction — and PostGIS's geometry→jsonb cast raises on curved input
    (``lwgeom_to_geojson: 'MultiSurface' geometry type not supported``). The
    original ``geom`` column deliberately preserves the curved source even
    after ingest linearizes ``geom_4326``, so a curved dataset 500'd every
    feature read through a column the response then discarded. Readers now
    project the row to this list first, so the cast never sees ``geom``.

    The live schema is authoritative here on purpose: ``Dataset.column_info``
    can drift from the table on re-upload, and a projected list must match
    the table or the whole query fails. Names are double-quote escaped, and —
    fix(#1113 review), same rule as _sql_quote_ident's fix(#640) — colons are
    backslash-escaped because SQLAlchemy ``text()`` parses ``:name`` as a bind
    parameter even inside double-quoted identifiers, and registered Socrata
    exports ship columns literally named ``:id``. The output is therefore
    only valid inside ``text()``.

    Returns a comma-separated quoted list, or "" when the table has no
    property columns.
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var

    schema = tenant_data_schema(current_tenant_var.get())
    result = await db.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :tn "
            "AND column_name NOT IN ('gid', 'geom', 'geom_4326') "
            "ORDER BY ordinal_position"
        ).bindparams(schema=schema, tn=table_name)
    )
    return ", ".join(
        '"' + name.replace('"', '""').replace(":", "\\:") + '"'
        for (name,) in result.all()
    )


async def feature_table_exists(db: AsyncSession, table_name: str) -> bool:
    """Whether the tenant-schema data table currently exists.

    fix(#1614 codex r2): ``get_column_info`` returns [] both for a table with
    zero attribute columns and for a MISSING table (partial ingest, eviction).
    Queryables/filter callers must distinguish the two — an empty schema is
    authoritative only when the table is really there; a missing table is the
    same retryable 503 the feature query paths report.
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var

    schema = tenant_data_schema(current_tenant_var.get())
    result = await db.execute(
        text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = :tn)"
        ).bindparams(schema=schema, tn=table_name)
    )
    return bool(result.scalar_one())


async def get_feature_queryable_columns(
    db: AsyncSession, table_name: str
) -> list[dict]:
    """Live column name/type rows for Part 3 queryables and CQL2 filtering.

    fix(#1614): same live-schema authority rule as ``live_property_columns`` —
    the filterable set must match the table the SQL runs against, not the
    stored ``Dataset.column_info`` snapshot. The catalog port resolves the
    tenant schema itself when none is passed.
    """
    return await get_catalog_port().get_column_info(db, table_name)


async def _projected_row_source(
    db: AsyncSession, table_name: str, *, with_geometry: bool
) -> str:
    """Render the projected FROM source feature readers serialize from.

    See ``live_property_columns`` for why the row is projected before
    ``to_jsonb``. ``geom_4326`` rides along when the table is spatial so
    bbox predicates and the geometry select keep working; the planner
    flattens the subquery, so index use is unchanged.
    """
    prop_cols = await live_property_columns(db, table_name)
    prop_sel = f", {prop_cols}" if prop_cols else ""
    geom_sel = ", geom_4326" if with_geometry else ""
    return (
        f"(SELECT gid{geom_sel}{prop_sel} "
        f"FROM {get_catalog_port().quote_table(table_name)})"
    )


async def _property_filter_predicates(
    db: AsyncSession,
    table_name: str,
    property_filters: dict,
    allowed_columns: set[str],
) -> tuple[list[str], dict, list]:
    """Compose the `"col" = :prop_col` predicates for the property filters.

    Returns (where_clauses, raw_string_binds, typed_binds). fix(#1778): the
    live schema decides how each value is typed, so the read costs one
    information_schema round trip, and only when a property filter is present.
    A column whose type has no mapping keeps the raw string bind it has always
    had.
    """
    live_types = {
        col["name"]: col.get("type")
        for col in await get_feature_queryable_columns(db, table_name)
        if isinstance(col.get("name"), str)
    }
    clauses: list[str] = []
    raw_binds: dict = {}
    typed_binds: list = []
    for col, val in property_filters.items():
        if col not in allowed_columns or not _COLUMN_NAME_RE.match(col):
            continue
        param_name = f"prop_{col}"
        clauses.append(f'"{col}" = :{param_name}')
        bind = _property_filter_bind(param_name, col, live_types.get(col), val)
        if bind is None:
            raw_binds[param_name] = val
        else:
            typed_binds.append(bind)
    return clauses, raw_binds, typed_binds


# fix(#1778): rows a filtered count will visit before it stops being exact.
#
# The cached feature_count fast path applies only to a COMPLETELY unfiltered
# request, so one bbox, property filter or CQL2 filter put a full filtered
# COUNT(*) on EVERY page — including keyset pages, whose whole point is
# constant-time access. Paging 50 pages of a multi-million-row layer cost 50
# full GiST scans with ST_Intersects rechecks, so the caller saw constant-time
# row fetch and O(N) latency per page.
#
# Counting inside a LIMIT bounds that: the scan stops once the cap is reached,
# so the per-page cost has a ceiling instead of scaling with the match set. The
# count stays EXACT up to the cap, which covers any result set a client would
# actually page through (100 pages at the OGC max page size); past it the
# planner's own row estimate answers, and the response says so with an
# X-GeoLens-Number-Matched: estimated header. The estimate is never reported
# below the rows already counted, so a `next` link driven by
# `offset + limit < total` cannot truncate pagination at the cap.
_FILTERED_COUNT_CAP = 20_000


class FeaturePage(NamedTuple):
    """One page of features plus what the caller needs to paginate it.

    fix(#1778 review r1): ``has_more`` exists because ``total`` may be the
    planner's estimate. A router that decided its `next` link from
    ``offset + limit < total`` would drop the link mid-result-set whenever the
    estimate came back at or below the rows already served, stranding the
    caller with a full page and nowhere to go. Whether another row exists is a
    fact about the rows, so it is answered by over-fetching one and never by
    the count.
    """

    rows: list[dict]
    total: int
    total_is_estimate: bool
    has_more: bool


NUMBER_MATCHED_HEADER = "X-GeoLens-Number-Matched"


def number_matched_headers(total_is_estimate: bool) -> dict[str, str]:
    """Response headers saying how ``numberMatched`` was produced.

    OGC API Features defines no response member for "this count is
    approximate", and the field is not optional in GeoLens's own schemas, so
    the distinction rides on a header. Callers that display the number, or
    compare it against the rows they received, need to know which they got.
    The header is in the CORS expose list, so a browser client can read it.
    """
    return {NUMBER_MATCHED_HEADER: "estimated"} if total_is_estimate else {}


async def _planner_row_estimate(
    db: AsyncSession, quoted_table: str, where_sql: str, binds: dict, apply_binds
) -> int:
    """The planner's row estimate for the filtered predicate, or 0.

    EXPLAIN without ANALYZE plans the statement and does not run it, so this
    costs planning time rather than a scan. It is deliberately NOT wrapped in a
    try/except: it plans the exact predicate the data query just executed
    successfully, so a failure here is the same class the routers already
    classify, and swallowing it would leave the session in a failed
    transaction with the real cause hidden.
    """
    result = await db.execute(
        apply_binds(
            text(
                f"EXPLAIN (FORMAT JSON) SELECT 1 FROM {quoted_table} t {where_sql}"
            ).bindparams(**binds)
        )
    )
    payload = result.scalar_one()
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    return int(payload[0]["Plan"]["Plan Rows"])


async def _bounded_total(
    db: AsyncSession, table_name: str, where_sql: str, binds: dict, apply_binds
) -> tuple[int, bool]:
    """Count the filtered rows, exactly up to `_FILTERED_COUNT_CAP`.

    Returns (total, total_is_estimate).
    """
    quoted = get_catalog_port().quote_table(table_name)
    capped_result = await db.execute(
        apply_binds(
            text(
                f"SELECT COUNT(*) FROM (SELECT 1 FROM {quoted} t {where_sql} "
                f"LIMIT :count_cap) s"
            ).bindparams(**binds, count_cap=_FILTERED_COUNT_CAP + 1)
        )
    )
    counted = int(capped_result.scalar_one())
    if counted <= _FILTERED_COUNT_CAP:
        return counted, False
    estimate = await _planner_row_estimate(db, quoted, where_sql, binds, apply_binds)
    return max(counted, estimate), True


def _floor_estimated_total(
    total: int,
    *,
    total_is_estimate: bool,
    served: int,
    offset: int,
    has_more: bool,
) -> int:
    """Raise an estimated total to the rows the page can prove exist.

    fix(#1778 review r1): an estimate below the rows a page is about to show
    makes numberMatched contradict the features beside it in the same response.

    fix(#1778 review r3): it may only count rows that exist, and only when the
    total is an estimate to begin with.

      - An EXACT count is never raised. It already counted the whole match set,
        so anything above it is fiction.
      - An empty page proves nothing. The r1 form floored by `offset +
        len(rows)` unconditionally, which invented matches out of the offset:
        five features asked for at offset 100 returned an empty page and
        reported numberMatched 100.
      - A keyset page passes `offset=0`, because the query ignores `offset`
        when `after_gid` is set. The rows in hand are all such a page can
        prove, and borrowing an offset the query never applied would invent
        matches the same way.
    """
    if not total_is_estimate or served == 0:
        return total
    floor = offset + served + (1 if has_more else 0)
    return max(total, floor)


async def get_features(
    db: AsyncSession,
    table_name: str,
    *,
    limit: int = 10,
    offset: int = 0,
    bbox: list[float] | None = None,
    property_filters: dict | None = None,
    has_geometry: bool = True,
    allowed_columns: set[str] | None = None,
    include_geometry: bool = True,
    cached_feature_count: int | None = None,
    after_gid: int | None = None,
    cql2_where: str | None = None,
    cql2_binds: Sequence | None = None,
) -> FeaturePage:
    """Fetch paginated features from a data table as GeoJSON-ready dicts.

    Returns a ``FeaturePage`` whose rows each have gid, geometry and
    properties. ``total_is_estimate`` is True when the filtered match set is
    larger than ``_FILTERED_COUNT_CAP`` and ``total`` is the planner's row
    estimate rather than an exact count (fix(#1778)). ``has_more`` says whether
    a further row exists after this page, measured by fetching one more row
    than asked for; pagination links must be built from it and never from
    ``total`` (fix(#1778 review r1)).

    Phase 269 H-24: when ``after_gid`` is provided, uses keyset pagination
    (``WHERE gid > :after_gid``) instead of OFFSET. This avoids the
    ``OFFSET 999000`` deep-paging cost. The ``offset`` parameter remains
    supported as a legacy fallback for clients that have not migrated to
    cursor pagination.

    fix(#1614): ``cql2_where``/``cql2_binds`` carry a pre-compiled CQL2
    fragment from ``app.standards.ogc.filtering`` — the only sanctioned
    producer: it restricts identifiers to live-schema columns and passes
    every value as a typed ``:cql2_N`` BindParameter (collision-free with
    the binds built here, and typed so the asyncpg cast matches the column —
    codex r3). It joins ``where_clauses`` so the data query, count query,
    and cached-count bypass all compose exactly like ``bbox``.

    fix(#1778): ``property_filters`` values arrive as query-string text and are
    bound with the database type of the column they name, read from the live
    schema. A value that does not parse for that type raises ValueError naming
    the property; routers report it as a 400.

    Raises
    ------
    ValueError
        If a property-filter value cannot be parsed for its column's type or
        falls outside that type's range, or if a pagination integer falls
        outside int8 (fix(#1778 review r2)). Routers report all of these as
        400s naming the property or parameter and the bound it broke.
    """
    # fix(#1778 review r2): the pagination integers are caller values that reach
    # the driver untyped, and FastAPI's `int` has no upper bound. A value
    # outside int8 cannot be encoded at all: asyncpg raises a bare
    # sqlalchemy.exc.DBAPIError with SQLSTATE 22000 from inside its encode
    # path, which neither router caught, so `?offset=10**23` was a 500. Refuse
    # it here, where the message can name the parameter.
    check_int8_range("limit", limit)
    check_int8_range("offset", offset)
    if after_gid is not None:
        check_int8_range("after_gid", after_gid)

    # Build SELECT columns over the projected row (see live_property_columns
    # for why geom must never reach to_jsonb).
    if has_geometry and include_geometry:
        select_cols = (
            "gid, ST_AsGeoJSON(geom_4326, 6)::json AS geometry, "
            "to_jsonb(t.*) - 'gid' - 'geom_4326' AS properties"
        )
    elif has_geometry:
        select_cols = (
            "gid, NULL::json AS geometry, "
            "to_jsonb(t.*) - 'gid' - 'geom_4326' AS properties"
        )
    else:
        select_cols = "gid, NULL::json AS geometry, to_jsonb(t.*) - 'gid' AS properties"
    row_source = await _projected_row_source(db, table_name, with_geometry=has_geometry)

    # Build WHERE clauses
    where_clauses: list[str] = []
    bind_values: dict = {}

    if bbox is not None and has_geometry:
        if bbox[0] > bbox[2]:
            # Antimeridian-crossing: split into two envelopes (each with && pre-filter for index)
            where_clauses.append(
                "((geom_4326 && ST_MakeEnvelope(:minx, :miny, 180, :maxy, 4326)"
                " AND ST_Intersects(geom_4326, ST_MakeEnvelope(:minx, :miny, 180, :maxy, 4326)))"
                " OR (geom_4326 && ST_MakeEnvelope(-180, :miny, :maxx, :maxy, 4326)"
                " AND ST_Intersects(geom_4326, ST_MakeEnvelope(-180, :miny, :maxx, :maxy, 4326))))"
            )
        else:
            where_clauses.append(
                "geom_4326 && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)"
                " AND ST_Intersects(geom_4326, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
        bind_values["minx"] = bbox[0]
        bind_values["miny"] = bbox[1]
        bind_values["maxx"] = bbox[2]
        bind_values["maxy"] = bbox[3]

    typed_binds: list = []
    if property_filters and allowed_columns:
        prop_clauses, prop_raw_binds, typed_binds = await _property_filter_predicates(
            db, table_name, property_filters, allowed_columns
        )
        where_clauses.extend(prop_clauses)
        bind_values.update(prop_raw_binds)

    if cql2_where:
        where_clauses.append(cql2_where)

    # H-24: keyset cursor pagination — `gid > :after_gid` short-circuits the
    # OFFSET cost path entirely. Both pagination styles use the same `gid`
    # column, so the existing PRIMARY KEY index on `gid` handles the cursor
    # without any new index.
    use_keyset = after_gid is not None
    if use_keyset:
        where_clauses.append("gid > :after_gid")
        bind_values["after_gid"] = after_gid

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # Data query — keyset uses LIMIT only (no OFFSET); legacy uses LIMIT + OFFSET.
    if use_keyset:
        data_sql = (
            f"SELECT {select_cols} FROM {row_source} t "
            f"{where_sql} ORDER BY gid LIMIT :limit"
        )
    else:
        data_sql = (
            f"SELECT {select_cols} FROM {row_source} t "
            f"{where_sql} ORDER BY gid LIMIT :limit OFFSET :offset"
        )
        bind_values["offset"] = offset
    # One row past the page, so `has_more` is a fact about the rows rather than
    # a comparison against a count that may be estimated (fix(#1778 review r1)).
    bind_values["limit"] = limit + 1

    # Typed BindParameters (codex r3) — see the cql2_binds docstring note — plus
    # the property-filter binds typed from the live schema (fix(#1778)). Both
    # sets name parameters that appear in the data query AND in the count query,
    # so one list serves both.
    extra_binds = [*(cql2_binds or ()), *typed_binds]

    def _with_extra_binds(stmt):
        return stmt.bindparams(*extra_binds) if extra_binds else stmt

    result = await db.execute(
        _with_extra_binds(text(data_sql).bindparams(**bind_values))
    )
    rows = [dict(row._mapping) for row in result.all()]
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    # Count query (same WHERE *minus* the after_gid cursor, no LIMIT/OFFSET).
    # The keyset cursor must be excluded from the count so total reflects the
    # full result set, not "rows remaining after cursor".
    count_where_clauses = [c for c in where_clauses if c != "gid > :after_gid"]
    count_where_sql = ""
    if count_where_clauses:
        count_where_sql = "WHERE " + " AND ".join(count_where_clauses)

    # Use cached feature_count when no filters are active
    if not count_where_clauses and cached_feature_count is not None:
        total, total_is_estimate = cached_feature_count, False
    else:
        count_bind = {
            k: v
            for k, v in bind_values.items()
            if k not in ("limit", "offset", "after_gid")
        }
        total, total_is_estimate = await _bounded_total(
            db, table_name, count_where_sql, count_bind, _with_extra_binds
        )

    total = _floor_estimated_total(
        total,
        total_is_estimate=total_is_estimate,
        served=len(rows),
        offset=0 if use_keyset else offset,
        has_more=has_more,
    )
    return FeaturePage(rows, total, total_is_estimate, has_more)


async def get_features_geojson_z(
    db: AsyncSession,
    table_name: str,
    *,
    cap: int = 5000,
    cached_feature_count: int | None = None,
) -> tuple[list[dict], bool, int]:
    """Fetch up to `cap` features with Z coordinates preserved.

    Returns (rows, truncated, total_count).

    Uses LIMIT cap+1 to detect truncation without a separate COUNT query.
    ST_AsGeoJSON natively preserves Z when the geometry has Z.
    total_count: actual row count when not truncated, COUNT(*) when truncated.
    cached_feature_count is ignored — always uses authoritative count.
    """
    select_cols = (
        "gid, ST_AsGeoJSON(geom_4326, 6)::json AS geometry, "
        "to_jsonb(t.*) - 'gid' - 'geom_4326' AS properties"
    )
    row_source = await _projected_row_source(db, table_name, with_geometry=True)
    # Fetch cap+1 to detect truncation without a separate COUNT query
    data_sql = f"SELECT {select_cols} FROM {row_source} t ORDER BY gid LIMIT :limit"
    result = await db.execute(text(data_sql).bindparams(limit=cap + 1))
    rows = [dict(row._mapping) for row in result.all()]

    truncated = len(rows) > cap
    if truncated:
        rows = rows[:cap]

    if not truncated:
        # All features returned — row count is authoritative
        total_count = len(rows)
    elif cached_feature_count is not None:
        # Use caller-supplied cached count to avoid extra query
        total_count = cached_feature_count
    else:
        count_sql = f"SELECT COUNT(*) FROM {get_catalog_port().quote_table(table_name)}"
        count_result = await db.execute(text(count_sql))
        total_count = count_result.scalar_one()

    return rows, truncated, total_count


async def get_feature_by_id(
    db: AsyncSession,
    table_name: str,
    gid: int,
    *,
    has_geometry: bool = True,
) -> dict | None:
    """Fetch a single feature by gid.

    Returns a dict with gid, geometry, and properties, or None if not found.
    """
    if has_geometry:
        select_cols = (
            "gid, ST_AsGeoJSON(geom_4326, 6)::json AS geometry, "
            "to_jsonb(t.*) - 'gid' - 'geom_4326' AS properties"
        )
    else:
        select_cols = "gid, NULL::json AS geometry, to_jsonb(t.*) - 'gid' AS properties"

    row_source = await _projected_row_source(db, table_name, with_geometry=has_geometry)
    sql = f"SELECT {select_cols} FROM {row_source} t WHERE gid = :gid"
    result = await db.execute(text(sql).bindparams(gid=gid))
    row = result.first()
    if row is None:
        return None
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


class FeatureWrite(NamedTuple):
    """The written feature plus the envelope of the version it overwrote.

    ``prior_bounds`` is None when the overwritten row carried no geometry.
    """

    feature: dict
    prior_bounds: "Bounds | None"


async def _geom_column_is_generic(session: AsyncSession, table_name: str) -> bool:
    """True when the table's geom column is generic geometry (no typmod).

    Authoritative signal from the PostGIS geometry_columns catalog view.
    source_format='created' alone is NOT sufficient: create_empty_dataset
    builds generic geometry(Geometry, 4326) columns, but the layers module
    (layers/service.py) also labels its datasets 'created' while building
    CONCRETELY typed columns that need typed validation + ST_Multi promotion.
    """
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var

    schema = tenant_data_schema(current_tenant_var.get())
    result = await session.execute(
        text(
            "SELECT type FROM geometry_columns "
            "WHERE f_table_schema = :schema AND f_table_name = :t "
            "AND f_geometry_column = 'geom'"
        ).bindparams(schema=schema, t=table_name)
    )
    col_type = result.scalar_one_or_none()
    return col_type is not None and col_type.strip().upper() == "GEOMETRY"


async def effective_geometry_type(session: AsyncSession, dataset) -> str:
    """Geometry type for feature-write validation and insert SQL.

    fix(#430 codex r7): generic-column created datasets must accept ANY
    subtype forever — even after refresh_dataset_metadata derives a concrete
    DISPLAY type from the rows (done so the builder renders the layer instead
    of an invisible fill). Validation therefore keys on the actual column
    genericity, never on the derived type. Typed 'created' tables (layers
    module) keep typed validation.
    """
    if dataset.source_format == "created" and await _geom_column_is_generic(
        session, dataset.table_name
    ):
        return "GEOMETRY"
    return dataset.geometry_type


def _validate_geometry_structure(geometry: dict) -> BaseGeometry:
    """Reject degenerate or topologically invalid geometry before PostGIS.

    fix(#458 E-02): degenerate-but-schema-valid input (2-point polygon rings,
    1-vertex LineStrings, empty coordinate arrays) crashed ST_GeomFromGeoJSON
    into a 500, and well-formed self-intersecting polygons persisted and later
    raised GEOS TopologyException on bbox queries and tile renders — read-path
    500s that hit anonymous viewers of public datasets. Raises ValueError
    (routers map it to 400).

    fix(#1778): return the shapely geometry itself rather than a bare None.
    Shapely repairs some structurally-invalid input it accepts (an unclosed
    polygon ring is auto-closed by `shape()`), but ST_GeomFromGeoJSON does not
    repair the equivalent GeoJSON — it stores the ring open, which later
    crashes any ST_Intersects bbox read with a GEOS "not closed" error.
    Callers must write the returned, shapely-normalized geometry instead of
    re-serializing the client's original dict.
    """
    try:
        geom = shapely_shape(geometry)
    except (GEOSException, ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid geometry: {exc}") from exc
    if geom.is_empty:
        raise ValueError("Invalid geometry: geometry is empty")
    if not geom.is_valid:
        raise ValueError(f"Invalid geometry: {explain_validity(geom)}")
    return geom


def _validate_geometry_type(geojson_type: str, dataset_geometry_type: str) -> None:
    """Check that a GeoJSON geometry type is compatible with the dataset's geometry type.

    The dataset stores geometry_type in UPPERCASE (e.g. "POINT", "MULTIPOLYGON").
    GeoJSON uses mixed case (e.g. "Point", "MultiPolygon"). Normalize both for
    comparison using the GEOJSON_TYPE_MAP.

    Raises ValueError if the types are incompatible.
    """
    # Normalize dataset type (stored UPPERCASE in DB) to GeoJSON mixed case.
    # str.title() fails for compound words: "LINESTRING" -> "Linestring" not "LineString".
    # Use a direct mapping instead.
    # fix(#430 BA-32): a generic-typed dataset (GEOMETRY column) accepts any subtype;
    # only reject genuinely non-geometry GeoJSON.
    if dataset_geometry_type.strip().upper() == "GEOMETRY":
        if GEOJSON_TYPE_MAP.get(geojson_type.strip()) is None:
            raise ValueError(f"Unsupported geometry type: {geojson_type}")
        return
    _UPPER_TO_GEOJSON = {
        "POINT": "Point",
        "MULTIPOINT": "MultiPoint",
        "LINESTRING": "LineString",
        "MULTILINESTRING": "MultiLineString",
        "POLYGON": "Polygon",
        "MULTIPOLYGON": "MultiPolygon",
        # fix(#430 codex r20): without this entry a GEOMETRYCOLLECTION-typed
        # dataset normalized to its raw uppercase name and never matched the
        # mixed-case compatibility set above.
        "GEOMETRYCOLLECTION": "GeometryCollection",
    }
    normalized_dataset = _UPPER_TO_GEOJSON.get(
        dataset_geometry_type.strip().upper(), dataset_geometry_type.strip()
    )
    normalized_geojson = geojson_type.strip()

    compatible = GEOJSON_TYPE_MAP.get(normalized_geojson)
    if compatible is None:
        raise ValueError(f"Unsupported geometry type: {geojson_type}")

    if normalized_dataset not in compatible:
        raise ValueError(
            f"Geometry type mismatch: cannot insert {geojson_type} "
            f"into a {dataset_geometry_type} layer"
        )


async def insert_feature(
    db: AsyncSession,
    table_name: str,
    geometry: dict,
    properties: dict | None,
    column_info: list[dict],
    dataset_geometry_type: str,
    dataset_srid: int | None = None,
) -> dict:
    """Insert a GeoJSON feature into a PostGIS data table.

    Writes both geom and geom_4326 columns. Only inserts property columns
    that exist in column_info. Returns the full inserted feature via
    get_feature_by_id.
    """
    _validate_geometry_type(geometry.get("type", ""), dataset_geometry_type)
    normalized_geom = _validate_geometry_structure(geometry)
    _reject_unknown_properties(properties, column_info)

    geojson_str = to_geojson(normalized_geom)

    geom_expr, geom_4326_expr = _geom_write_exprs(dataset_geometry_type, dataset_srid)
    cols = ["geom", "geom_4326"]
    vals = [geom_expr, geom_4326_expr]
    params: dict = {"geojson": geojson_str}

    if properties:
        allowed = {c["name"] for c in column_info}
        for key, value in properties.items():
            if key in allowed and _COLUMN_NAME_RE.match(key):
                param_name = f"prop_{key}"
                cols.append(f'"{key}"')
                vals.append(f":{param_name}")
                params[param_name] = value

    sql = (
        f"INSERT INTO {get_catalog_port().quote_table(table_name)} ({', '.join(cols)}) "
        f"VALUES ({', '.join(vals)}) RETURNING gid"
    )
    result = await db.execute(text(sql).bindparams(**params))
    gid = result.scalar_one()

    row = await get_feature_by_id(db, table_name, gid)
    if row is None:
        raise RuntimeError(f"Feature {gid} not found immediately after insert")
    return row


async def replace_feature(
    db: AsyncSession,
    table_name: str,
    gid: int,
    geometry: dict,
    properties: dict,
    column_info: list[dict],
    dataset_geometry_type: str,
    dataset_srid: int | None = None,
) -> dict:
    """Full replacement of a feature (PUT semantics).

    Replaces geometry and sets ALL known attribute columns. Columns not
    present in properties are set to NULL.
    """
    _validate_geometry_type(geometry.get("type", ""), dataset_geometry_type)
    normalized_geom = _validate_geometry_structure(geometry)
    # fix(#1778): replace nulls every known column, so an unwritable one makes
    # the documented semantics unachievable even when the request omits it.
    _reject_unknown_properties(properties, column_info, replaces_all=True)

    geojson_str = to_geojson(normalized_geom)
    geom_expr, geom_4326_expr = _geom_write_exprs(dataset_geometry_type, dataset_srid)

    sets = [
        f"geom = {geom_expr}",
        f"geom_4326 = {geom_4326_expr}",
    ]
    params: dict = {"geojson": geojson_str, "gid": gid}

    allowed = {c["name"] for c in column_info}
    for col_name in allowed:
        if _COLUMN_NAME_RE.match(col_name):
            param = f"prop_{col_name}"
            sets.append(f'"{col_name}" = :{param}')
            params[param] = properties.get(col_name)

    sql = _update_capturing_prior_bounds(
        get_catalog_port().quote_table(table_name), sets
    )
    result = await db.execute(text(sql).bindparams(**params))
    prior = result.first()
    if prior is None:
        raise ValueError("Feature not found")

    row = await get_feature_by_id(db, table_name, gid)
    if row is None:
        raise RuntimeError(f"Feature {gid} not found immediately after replace")
    return FeatureWrite(row, _prior_bounds_from_row(prior))


async def update_feature(
    db: AsyncSession,
    table_name: str,
    gid: int,
    geometry: dict | None,
    properties: dict | None,
    column_info: list[dict],
    dataset_geometry_type: str,
    dataset_srid: int | None = None,
) -> dict:
    """Partial update of a feature (PATCH semantics).

    Only modifies fields that are provided. If geometry is given, both geom
    and geom_4326 are updated. If properties is given, only the keys present
    in the dict (and in column_info) are updated.
    """
    sets: list[str] = []
    params: dict = {"gid": gid}

    if geometry is not None:
        _validate_geometry_type(geometry.get("type", ""), dataset_geometry_type)
        normalized_geom = _validate_geometry_structure(geometry)
        geojson_str = to_geojson(normalized_geom)
        geom_expr, geom_4326_expr = _geom_write_exprs(
            dataset_geometry_type, dataset_srid
        )
        sets.append(f"geom = {geom_expr}")
        sets.append(f"geom_4326 = {geom_4326_expr}")
        params["geojson"] = geojson_str

    if properties is not None:
        _reject_unknown_properties(properties, column_info)
        allowed = {c["name"] for c in column_info}
        for key, value in properties.items():
            if key in allowed and _COLUMN_NAME_RE.match(key):
                param = f"prop_{key}"
                sets.append(f'"{key}" = :{param}')
                params[param] = value

    if not sets:
        raise ValueError("Nothing to update")

    sql = _update_capturing_prior_bounds(
        get_catalog_port().quote_table(table_name), sets
    )
    result = await db.execute(text(sql).bindparams(**params))
    prior = result.first()
    if prior is None:
        raise ValueError("Feature not found")

    row = await get_feature_by_id(db, table_name, gid)
    if row is None:
        raise RuntimeError(f"Feature {gid} not found immediately after update")
    return FeatureWrite(row, _prior_bounds_from_row(prior))


async def delete_feature(
    db: AsyncSession,
    table_name: str,
    gid: int,
) -> Bounds | None:
    """Hard-delete a feature by gid, returning the envelope it removed.

    The envelope comes back from the DELETE itself, so it describes the row
    version this statement actually removed even if another transaction moved
    the feature first (see _PRIOR_BOUNDS_COLS). None when the deleted row had
    no geometry.

    Raises ValueError if the feature does not exist.
    """
    result = await db.execute(
        text(
            f"DELETE FROM {get_catalog_port().quote_table(table_name)} "
            f"WHERE gid = :gid RETURNING {_PRIOR_BOUNDS_COLS}"
        ).bindparams(gid=gid)
    )
    row = result.first()
    if row is None:
        raise ValueError("Feature not found")
    return _prior_bounds_from_row(row)


async def _refresh_count_and_extent(
    session: AsyncSession, table_name: str
) -> tuple[int, str | None]:
    """Lightweight count + extent query for feature-write metadata refresh.

    Returns (feature_count, extent_wkt) in a single query instead of the
    5 queries that extract_metadata() runs.
    """
    # fix(#430 BA-18): records.spatial_extent admits only POLYGON or MULTIPOLYGON
    # (fix(#892) widened the typmod to geometry(Geometry, 4326) and moved the type
    # guard into chk_records_spatial_extent_type), but ST_Extent of a single point /
    # axis-collinear points casts to POINT / LINESTRING, which is still rejected
    # (previously the caller silently skipped storing it, leaving a stale/NULL
    # extent). ST_Expand always returns the bounding-box POLYGON, so we pad ONLY the
    # degenerate (non-polygon) cases into a valid sub-mm-padded polygon; genuine
    # polygon extents are returned byte-identical (no epsilon).
    quoted = get_catalog_port().quote_table(table_name)
    result = await session.execute(
        text(
            f"SELECT COUNT(*), "
            f"CASE "
            f"  WHEN ST_Extent(geom_4326) IS NULL THEN NULL "
            f"  WHEN GeometryType(ST_Extent(geom_4326)::geometry) = 'POLYGON' "
            f"    THEN ST_AsText(ST_SetSRID(ST_Extent(geom_4326)::geometry, 4326)) "
            f"  ELSE ST_AsText("
            f"    ST_Expand(ST_SetSRID(ST_Extent(geom_4326)::geometry, 4326), 1e-9)) "
            f"END, "
            f"ST_XMin(ST_Extent(geom_4326)), ST_XMax(ST_Extent(geom_4326)) "
            f"FROM {quoted}"
        )
    )
    row = result.one()
    count, extent_wkt, xmin, xmax = int(row[0]), row[1], row[2], row[3]
    # fix(#934): a table honestly crossing ±180 must not store the naive
    # near-global fold on refresh; emit the two-ring MULTIPOLYGON instead.
    # A crossing dataset's naive width always exceeds 180 degrees (the shifted
    # domain spans 360 - width, so it can only win past 180), which lets the
    # ordinary case skip the second aggregate and stay byte-identical —
    # including the degenerate POINT/LINESTRING padding above.
    if xmin is not None and xmax is not None and float(xmax) - float(xmin) > 180.0:
        # Same tenant data schema the quoted reference above resolves to; the
        # helper quotes identifiers itself (fix(#934 codeql)).
        from app.core.db.tenant_schema import tenant_data_schema
        from app.core.db.tenant_session import current_tenant_var

        crossing = await seam_extent_wkt_for_table(
            session, table_name, schema=tenant_data_schema(current_tenant_var.get())
        )
        if crossing is not None:
            extent_wkt = crossing
    return count, extent_wkt


_CONCRETE_GEOMETRY_TYPES = {
    "POINT",
    "LINESTRING",
    "POLYGON",
    "MULTIPOINT",
    "MULTILINESTRING",
    "MULTIPOLYGON",
    "GEOMETRYCOLLECTION",
}


async def _derive_created_geometry_type(session: AsyncSession, table_name: str) -> str:
    """Concrete display geometry_type for a created (generic-column) dataset.

    fix(#430 codex r7): the 'GEOMETRY' sentinel renders as an invisible fill
    layer in the builder (classifyGeometry -> 'other'). Derive from the rows:
    a homogeneous layer gets its real type, a single-family mix gets the
    MULTI variant, a cross-family mix (or anything unexpected) stays generic —
    the honest fallback, matching how GEOMETRYCOLLECTION datasets render.
    Every return value satisfies chk_datasets_geometry_type by construction.
    """
    result = await session.execute(
        text(
            f"SELECT DISTINCT GeometryType(geom_4326) "
            f"FROM {get_catalog_port().quote_table(table_name)} "
            f"WHERE geom_4326 IS NOT NULL"
        )
    )
    types = {str(row[0]).strip().upper() for row in result.all() if row[0]}
    if not types <= (_CONCRETE_GEOMETRY_TYPES | {"GEOMETRY"}):
        return "GEOMETRY"
    if not types:
        return "GEOMETRY"
    if len(types) == 1:
        (only,) = types
        return only if only in _CONCRETE_GEOMETRY_TYPES else "GEOMETRY"
    families = {t.removeprefix("MULTI") for t in types}
    if len(families) == 1:
        (family,) = families
        if family in ("POINT", "LINESTRING", "POLYGON"):
            return f"MULTI{family}"
    return "GEOMETRY"


Bounds = tuple[float, float, float, float]


def geojson_bounds(geometry: dict | None) -> Bounds | None:
    """The (minx, miny, maxx, maxy) envelope of a GeoJSON geometry, or None.

    GeoJSON is WGS84 by spec, so the result is directly comparable with the
    stored ``geom_4326`` extent even for a dataset whose ``geom`` column keeps
    a projected source CRS.
    """
    if not geometry:
        return None
    try:
        geom = shapely_shape(geometry)
    except (GEOSException, ValueError, TypeError, AttributeError):
        return None
    if geom.is_empty:
        return None
    minx, miny, maxx, maxy = geom.bounds
    return (float(minx), float(miny), float(maxx), float(maxy))


# The envelope of the row version a write is about to overwrite or remove.
#
# fix(#1778 review r1): this used to be a separate unlocked SELECT taken before
# the mutation, which is a read-then-write race: a concurrent edit could move
# the feature out of the stored extent and commit in the gap, leaving the first
# writer holding envelope values that were true when it looked and false when
# it wrote. It would then take the incremental fast path and leave the expanded
# extent behind. The capture is now part of the mutating statement, so the
# envelope is always the version that statement actually replaced or deleted.
_PRIOR_BOUNDS_COLS = (
    "ST_XMin(geom_4326) AS prior_minx, ST_YMin(geom_4326) AS prior_miny, "
    "ST_XMax(geom_4326) AS prior_maxx, ST_YMax(geom_4326) AS prior_maxy"
)


def _prior_bounds_from_row(row) -> Bounds | None:
    """Read the four prior-envelope columns off a RETURNING row."""
    values = (
        row.prior_minx,
        row.prior_miny,
        row.prior_maxx,
        row.prior_maxy,
    )
    if any(v is None for v in values):
        return None
    return (
        float(values[0]),
        float(values[1]),
        float(values[2]),
        float(values[3]),
    )


def _update_capturing_prior_bounds(quoted_table: str, sets: list[str]) -> str:
    """UPDATE that returns the envelope of the row version it overwrote.

    The CTE takes ``FOR UPDATE`` on the target row, so a concurrent writer is
    waited for and the envelope read is the latest committed version rather
    than whatever a separate earlier statement happened to see. The outer
    UPDATE joins the locked row by its primary key, and RETURNING reads the
    prior values out of the CTE, which the UPDATE itself has already
    overwritten.
    """
    return (
        f"WITH prior AS (SELECT gid, {_PRIOR_BOUNDS_COLS} "
        f"FROM {quoted_table} WHERE gid = :gid FOR UPDATE) "
        f"UPDATE {quoted_table} AS t SET {', '.join(sets)} "
        f"FROM prior WHERE t.gid = prior.gid "
        f"RETURNING prior.prior_minx, prior.prior_miny, "
        f"prior.prior_maxx, prior.prior_maxy"
    )


# fix(#1847): the lock budget for a feature write that has to wait for the
# dataset row. Matches `app.platform.jobs.router` and
# `catalog.maps.service_crud`, which spend the same budget on the same question
# for the same reason: a row lock still contended after two seconds is held by
# another live writer, not by latency inside this request, and the caller is
# better served by a retryable conflict than by an open-ended hang.
_LOCK_TIMEOUT = "2s"


async def lock_catalog_rows_for_write(
    session: AsyncSession, dataset: Dataset
) -> Bounds | None:
    """Lock this dataset's catalog rows, then read its stored extent as a box.

    Call this from ANY request path that will dirty the datasets row, the
    records row, or both -- not only from the metadata refresh. Stamping
    `record.updated_by` and rolling `tile_cache_version` is already a write to
    both rows, and the ORM flushes them at commit in records-then-datasets
    order whether or not the caller thought of itself as locking anything.

    LOCK ORDER, for every writer of the (datasets, records) pair: **the
    datasets row first, the records row second.** Cite this docstring from any
    new site that takes both. The two background writers that lock the pair
    explicitly already lead with the datasets row, and neither can be reordered
    to follow this path instead: `processing/ingest/tasks_postgis_refresh.py`
    and `processing/ingest/tasks_stac_refresh.py` both take it to make a
    superseded-content check and the write that depends on it one indivisible
    step, so the lock has to be the first thing the write transaction does.

    The stored extent comes back because the read is FUSED into the records
    lock statement and so costs nothing extra: it is a single-row lookup by
    primary key, not the `ST_Extent` aggregate over the data table. The
    metadata refresh needs it; callers that only need the ordering ignore it.

    fix(#1847): this helper took the records row first, which inverted that
    order and made an ordinary feature edit during a `refresh_postgis` phase 3
    an ABBA deadlock (40P01) -- worker holding datasets and wanting records,
    request holding records and wanting datasets. The record lock is still
    taken, and still before the extent is read; only its position moved. This
    is the same resolution `cancel_job` reached for the VRT asset in
    fix(#1709 review r2 P2): both transactions lead with the lock the worker
    cannot give up, so whoever wins runs alone and the other waits at its first
    acquisition holding nothing.

    None unless the stored extent is a simple POLYGON. An antimeridian-crossing
    dataset stores the two-ring MULTIPOLYGON `seam_extent_wkt_for_table`
    produces (fix(#934)), whose ST_XMin/ST_XMax are -180/180: a longitude in
    the gap would test as inside a box the geometry never occupies.

    fix(#1778 review r1): the lock is taken by BOTH metadata paths before
    either reads the extent. Otherwise two writers on one dataset can interleave
    read-decide-write: one skips the recompute because its geometry is inside
    the extent it read, while the other shrinks that extent from an aggregate
    taken before the first row landed. Every writer here goes on to update the
    dataset row anyway, so it already serialized with its peers at commit; the
    lock only moves that serialization ahead of the decision that depends on it.
    """
    from app.modules.catalog.datasets.domain.models import Dataset as DatasetModel
    from app.modules.catalog.datasets.domain.models import Record

    # `SET LOCAL` takes a literal, not a bind parameter; this interpolates a
    # module constant, never request-supplied data.
    await session.execute(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))

    # `no_autoflush` so the order above is what actually reaches PostgreSQL. An
    # autoflush triggered by either SELECT emits the ORM's own flush order,
    # which is records before datasets (Dataset.record_id makes Record the
    # parent mapper) -- the exact inversion this helper exists to prevent.
    with session.no_autoflush:
        # Single column, on the datasets table alone: reading through a joined
        # relationship would not lock the joined row anyway, and would put this
        # statement on the records row ahead of the lock it is ordering.
        await session.execute(
            select(DatasetModel.id)
            .where(DatasetModel.id == dataset.id)
            .with_for_update()
        )
        result = await session.execute(
            select(
                func.GeometryType(Record.spatial_extent),
                func.ST_XMin(Record.spatial_extent),
                func.ST_YMin(Record.spatial_extent),
                func.ST_XMax(Record.spatial_extent),
                func.ST_YMax(Record.spatial_extent),
            )
            .where(Record.id == dataset.record_id)
            .with_for_update()
        )
    row = result.first()
    if row is None or row[0] != "POLYGON" or any(v is None for v in row[1:]):
        return None
    return (float(row[1]), float(row[2]), float(row[3]), float(row[4]))


def _strictly_inside(inner: Bounds, outer: Bounds) -> bool:
    """True when `inner` sits strictly within `outer` on all four sides.

    Strict on purpose, and the same test for a row being added, removed or
    moved. A row that only touches the boundary may be the row that DEFINES
    that side, so removing or moving it can shrink the extent; a row strictly
    inside cannot change it whichever way it is written.
    """
    return (
        outer[0] < inner[0]
        and outer[1] < inner[1]
        and inner[2] < outer[2]
        and inner[3] < outer[3]
    )


def _merged_created_geometry_type(current: str | None, added: str | None) -> str | None:
    """The display geometry_type after ONE geometry of `added` type is inserted.

    Mirrors `_derive_created_geometry_type`'s rules over the row types it would
    see, without the DISTINCT scan. None when the answer is not decidable from
    the stored value alone, which sends the caller back to the scan.

    Insert only. A delete or a moved geometry can NARROW the derived type (the
    last polygon leaving a mixed layer), and no merge of the stored value can
    see that.
    """
    if not current or not added:
        return None
    current = current.strip().upper()
    added = added.strip().upper()
    if added not in _CONCRETE_GEOMETRY_TYPES:
        return None
    if current == "GEOMETRY":
        # Already the honest fallback for a cross-family mix; one more row
        # cannot make it narrower.
        return "GEOMETRY"
    if current not in _CONCRETE_GEOMETRY_TYPES:
        return None
    if current == added:
        return current
    if current.removeprefix("MULTI") == added.removeprefix("MULTI"):
        family = current.removeprefix("MULTI")
        return (
            f"MULTI{family}" if family in ("POINT", "LINESTRING", "POLYGON") else None
        )
    return "GEOMETRY"


async def _apply_incremental_metadata(
    session: AsyncSession,
    dataset: Dataset,
    *,
    count_delta: int,
    touched_bounds: Sequence[Bounds | None],
    added_geometry_type: str | None,
    stored_box: Bounds | None,
) -> bool:
    """Update feature_count alone when the write provably left the extent alone.

    Returns False when the fast path does not apply, and the caller falls back
    to the full recompute.

    fix(#1778): `_refresh_count_and_extent` runs one unqualified
    COUNT(*) + ST_Extent over the whole table, so every single-feature edit
    seq-scanned the layer inside the request transaction, with a second scan
    over `ST_ShiftLongitude(geom_4326)` whenever the naive extent is wider than
    180 degrees and a third `SELECT DISTINCT GeometryType(...)` for created
    datasets. There is no bulk feature endpoint, so a client digitizing 200
    points issued 200 requests and paid it 200 times.
    """
    from app.modules.catalog.datasets.domain.models import Dataset as DatasetModel

    if not isinstance(dataset.feature_count, int):
        return False
    new_count = dataset.feature_count + count_delta
    # A layer emptied by this write must have its extent nulled, and one whose
    # count was already wrong must be recounted rather than adjusted.
    if new_count < 1:
        return False
    if not touched_bounds or any(b is None for b in touched_bounds):
        return False

    is_created_generic = dataset.source_format == "created" and (
        await _geom_column_is_generic(session, dataset.table_name)
    )
    if is_created_generic:
        # Only an insert can be settled without the DISTINCT scan.
        if count_delta <= 0:
            return False
        if (
            _merged_created_geometry_type(dataset.geometry_type, added_geometry_type)
            != (dataset.geometry_type or "").strip().upper()
        ):
            return False

    if stored_box is None:
        return False
    if not all(
        _strictly_inside(b, stored_box) for b in touched_bounds if b is not None
    ):
        return False

    if count_delta:
        # SQL-side so two concurrent writes cannot both read N and write N+1.
        dataset.feature_count = DatasetModel.feature_count + count_delta
    await session.flush()
    return True


async def refresh_dataset_metadata(
    session: AsyncSession,
    dataset: Dataset,
    *,
    count_delta: int | None = None,
    touched_bounds: Sequence[Bounds | None] | None = None,
    added_geometry_type: str | None = None,
) -> None:
    """Refresh feature_count and extent on a Dataset after write operations.

    Uses a single COUNT(*) + ST_Extent query instead of the full
    extract_metadata pipeline (which runs 5 queries).

    fix(#1778): when the caller can say how many rows the write added or
    removed and where the geometry it touched sits, and every touched envelope
    is strictly inside the stored extent, the extent provably did not change
    and no scan runs at all. Called with no keywords, the full recompute
    behaviour is unchanged.
    """
    # fix(#1778 review r1): taken before EITHER branch reads the extent, so a
    # skip decision cannot be invalidated by a concurrent recompute.
    # fix(#1847): datasets row first, then the records row. See
    # lock_catalog_rows_for_write for the order and why it is that way.
    stored_box = await lock_catalog_rows_for_write(session, dataset)

    if count_delta is not None and await _apply_incremental_metadata(
        session,
        dataset,
        count_delta=count_delta,
        touched_bounds=touched_bounds or (),
        added_geometry_type=added_geometry_type,
        stored_box=stored_box,
    ):
        return

    # fix(#1847): this aggregate runs INSIDE the lock, deliberately, and the
    # bound on what that costs a concurrent writer is the `lock_timeout` above
    # rather than a shorter critical section. Hoisting it above the lock and
    # re-checking a cheap predicate afterwards would reinstate exactly the
    # interleaving fix(#1778 review r1) closed: this transaction's row is
    # already in the table but uncommitted, so a peer's aggregate cannot see
    # it; if that peer measured before taking the lock, it would then write a
    # count and an extent computed as though this row did not exist. Holding
    # the lock across the scan is what makes the loser re-decide against the
    # extent the winner actually stored. The scan only runs when the fast path
    # above declined, which for the digitizing case it was added for is the
    # uncommon branch.
    feature_count, extent_wkt = await _refresh_count_and_extent(
        session, dataset.table_name
    )
    dataset.feature_count = feature_count

    # fix(#430 BA-18): ST_Extent of a single point is a POINT and of axis-collinear
    # points a LINESTRING, not always a POLYGON -- store any non-null extent.
    if extent_wkt:
        dataset.record.spatial_extent = func.ST_GeomFromText(extent_wkt, 4326)
    elif feature_count == 0:
        dataset.record.spatial_extent = None

    # fix(#430 codex r7): keep generic-column created datasets' DISPLAY
    # geometry_type in sync with their rows so the builder renders them (see
    # _derive_created_geometry_type). Validation stays generic via
    # effective_geometry_type(), so this never re-restricts what subtypes the
    # layer accepts. Typed 'created' tables (layers module) are excluded by
    # the genericity probe. Created layers are small (hand-authored), so the
    # extra DISTINCT scan is in the same cost class as the COUNT above.
    if dataset.source_format == "created" and await _geom_column_is_generic(
        session, dataset.table_name
    ):
        dataset.geometry_type = await _derive_created_geometry_type(
            session, dataset.table_name
        )

    await session.flush()
