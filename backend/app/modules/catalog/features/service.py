"""Feature query service: paginated GeoJSON features from PostGIS data tables."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from shapely import to_geojson
from shapely.errors import GEOSException
from shapely.geometry import shape as shapely_shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity
from sqlalchemy import bindparam, func, text
from sqlalchemy import types as sa_types
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import seam_extent_wkt_for_table
from app.platform.extensions import get_catalog_port

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import Dataset

# Column name validation for SQL identifier safety
_COLUMN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# Widest signed integer PostgreSQL will compare against a bigint bind.
_INT8_MIN = -(2**63)
_INT8_MAX = 2**63


def _parse_int(raw: str) -> int:
    value = int(raw)
    if not _INT8_MIN <= value < _INT8_MAX:
        raise ValueError("out of range for an integer column")
    return value


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


def _reject_unknown_properties(
    properties: dict | None, column_info: list[dict]
) -> None:
    """Raise ValueError if a property key names no real attribute column.

    fix(#458 E-25): writers used to silently drop unknown keys. On PUT that is a
    footgun — a misspelled key isn't written AND the intended column is nulled
    (replace sets every known column to `properties.get(name)`), all with a 200.
    Rejecting unknown keys up front surfaces the typo as a 400 instead. Reserved
    system columns (gid/geom/…) are absent from column_info, so a write attempt
    against them is correctly reported here too.
    """
    if not properties:
        return
    allowed = {c["name"] for c in column_info}
    unknown = sorted(k for k in properties if k not in allowed)
    if unknown:
        raise ValueError(f"Unknown property columns: {', '.join(unknown)}")


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
) -> tuple[list[dict], int, bool]:
    """Fetch paginated features from a data table as GeoJSON-ready dicts.

    Returns (rows, total_count, total_is_estimate) where each row has gid,
    geometry, and properties. ``total_is_estimate`` is True when the filtered
    match set is larger than ``_FILTERED_COUNT_CAP`` and ``total_count`` is the
    planner's row estimate rather than an exact count (fix(#1778)).

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
        If a property-filter value cannot be parsed for its column's type.
    """
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
    bind_values["limit"] = limit

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

    # Count query (same WHERE *minus* the after_gid cursor, no LIMIT/OFFSET).
    # The keyset cursor must be excluded from the count so total reflects the
    # full result set, not "rows remaining after cursor".
    count_where_clauses = [c for c in where_clauses if c != "gid > :after_gid"]
    count_where_sql = ""
    if count_where_clauses:
        count_where_sql = "WHERE " + " AND ".join(count_where_clauses)

    # Use cached feature_count when no filters are active
    if not count_where_clauses and cached_feature_count is not None:
        return rows, cached_feature_count, False

    count_bind = {
        k: v
        for k, v in bind_values.items()
        if k not in ("limit", "offset", "after_gid")
    }
    total, total_is_estimate = await _bounded_total(
        db, table_name, count_where_sql, count_bind, _with_extra_binds
    )
    return rows, total, total_is_estimate


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
    _reject_unknown_properties(properties, column_info)

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

    sql = (
        f"UPDATE {get_catalog_port().quote_table(table_name)} "
        f"SET {', '.join(sets)} WHERE gid = :gid"
    )
    result = await db.execute(text(sql).bindparams(**params))
    if result.rowcount == 0:
        raise ValueError("Feature not found")

    row = await get_feature_by_id(db, table_name, gid)
    if row is None:
        raise RuntimeError(f"Feature {gid} not found immediately after replace")
    return row


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

    sql = (
        f"UPDATE {get_catalog_port().quote_table(table_name)} "
        f"SET {', '.join(sets)} WHERE gid = :gid"
    )
    result = await db.execute(text(sql).bindparams(**params))
    if result.rowcount == 0:
        raise ValueError("Feature not found")

    row = await get_feature_by_id(db, table_name, gid)
    if row is None:
        raise RuntimeError(f"Feature {gid} not found immediately after update")
    return row


async def delete_feature(
    db: AsyncSession,
    table_name: str,
    gid: int,
) -> None:
    """Hard-delete a feature by gid.

    Raises ValueError if the feature does not exist.
    """
    result = await db.execute(
        text(
            f"DELETE FROM {get_catalog_port().quote_table(table_name)} WHERE gid = :gid"
        ).bindparams(gid=gid)
    )
    if result.rowcount == 0:
        raise ValueError("Feature not found")


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


async def refresh_dataset_metadata(session: AsyncSession, dataset: Dataset) -> None:
    """Refresh feature_count and extent on a Dataset after write operations.

    Uses a single COUNT(*) + ST_Extent query instead of the full
    extract_metadata pipeline (which runs 5 queries).
    """
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
