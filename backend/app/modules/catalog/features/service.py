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

_COLUMN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _parse_int(raw: str) -> int:
    # The per-type bound is applied by check_pg_value_range,
    # which knows whether the column is int2, int4 or int8.
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


# Binding raw left SQLAlchemy typing every bind VARCHAR, causing
# 42883 on non-text filters. Each entry pairs a parser with the bind's DB
# type — matches exactly what the queryables document (Part 3) advertises.
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
        # In range for the COLUMN, not merely parseable as a
        # Python value — 1e100 against a real column or 2147483648 against
        # an integer column is a legal comparison no stored value can
        # satisfy, silently answering 200 with zero features otherwise.
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
    # Storable in a generic GEOMETRY column (map presence is
    # enough) and in a typed GEOMETRYCOLLECTION column (the dataset check
    # constraint allows it); every other typed dataset reports a mismatch.
    # Nested collections are rejected earlier at the schema guard.
    "GeometryCollection": {"GeometryCollection"},
}


_MULTI_TYPES = {"MULTIPOINT", "MULTILINESTRING", "MULTIPOLYGON"}


class UnwritablePropertyError(ValueError):
    """A column that exists but that the feature write path cannot address.

    ``_COLUMN_NAME_RE`` is stricter than the read path's regexes,
    so a real ``_notes``/``:id`` column (e.g. Socrata) that GET returns could
    silently fail to write — POST/PUT answered 201/200 with nothing stored.
    Refusing the name up front turns that silent data loss into a 422.
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

    A silently dropped unknown key is a PUT footgun (not
    written, and replace nulls the column) — reject as a 400 instead.

    A real but unwritable column is refused too. ``replaces_all``
    writes EVERY known column, so one unwritable column blocks the whole PUT.
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

    GeoJSON is WGS84, so ST_GeomFromGeoJSON yields SRID 4326 — correct for
    geom_4326, but file-ingested layers keep their source CRS in `geom`, so
    writing 4326 there would violate the typmod. Transform when the
    dataset's actual SRID differs.
    """
    base = _geometry_sql(dataset_geometry_type)
    if dataset_srid and dataset_srid != 4326:
        return f"ST_Transform({base}, {int(dataset_srid)})", base
    return base, base


def parse_bbox(bbox: str | Sequence[float]) -> list[float]:
    """Parse a bbox into a 4-element ``[minx, miny, maxx, maxy]`` list.

    Accepts a comma-separated string or an already-split sequence (e.g. STAC
    POST bodies), 4 values (2D) or 6 (3D, Z ignored). Allows
    antimeridian-crossing boxes (minx > maxx) and degenerate ones
    (miny == maxy), per OGC/STAC's lower <= upper bbox convention. Raises
    ValueError on a bad value count or invalid latitude bounds.
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
    # Reject NaN/Inf coordinates. Python's float() accepts "nan",
    # "inf", "-inf" (and JSON 1e400 parses to +Inf) — PostGIS handles these
    # inconsistently, risking malformed geometries. This is the single home
    # for the guard; do not let another copy grow elsewhere.
    for i, v in enumerate(values):
        if not math.isfinite(v):
            raise ValueError(
                f"bbox coordinate at index {i} is non-finite ({v!r}); "
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

    To_jsonb serializes EVERY column first, and the
    geometry→jsonb cast raises on curved input in `geom` — projecting here
    keeps the cast from ever seeing it. Queries live schema, not
    `Dataset.column_info`, which can drift on re-upload. Colons
    are backslash-escaped too (`text()` parses `:name` as a bind param even
    quoted; Socrata ships columns named `:id`). Valid only inside `text()`.
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

    ``get_column_info`` returns [] both for zero attribute
    columns and a MISSING table — callers need to tell those apart, since a
    missing table is the same retryable 503 the feature query paths report.
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

    Same live-schema authority rule as ``live_property_columns`` —
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

    Returns (where_clauses, raw_string_binds, typed_binds). The
    live schema decides how each value is typed, costing one
    information_schema round trip only when a filter is present.
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


# Counting inside a LIMIT caps filtered-count cost instead of
# scaling O(N) per page. Exact up to this cap (100 OGC max-size pages);
# past it the planner's estimate answers (X-GeoLens-Number-Matched header).
_FILTERED_COUNT_CAP = 20_000


class FeaturePage(NamedTuple):
    """One page of features plus what the caller needs to paginate it.

    ``has_more`` exists because ``total`` may be the planner's
    estimate — a `next` link decided from ``offset + limit < total`` could
    drop mid-result-set. Answered by over-fetching one row, never the count.
    """

    rows: list[dict]
    total: int
    total_is_estimate: bool
    has_more: bool


NUMBER_MATCHED_HEADER = "X-GeoLens-Number-Matched"


def number_matched_headers(total_is_estimate: bool) -> dict[str, str]:
    """Response headers saying how ``numberMatched`` was produced.

    OGC API Features has no response member for "this count is approximate",
    so the distinction rides on a header (in the CORS expose list).
    """
    return {NUMBER_MATCHED_HEADER: "estimated"} if total_is_estimate else {}


async def _planner_row_estimate(
    db: AsyncSession, quoted_table: str, where_sql: str, binds: dict, apply_binds
) -> int:
    """The planner's row estimate for the filtered predicate, or 0.

    EXPLAIN without ANALYZE plans but does not run the statement, so this
    costs planning time, not a scan. Deliberately not wrapped in try/except:
    it plans the same predicate the data query just ran successfully, so a
    failure here belongs to the routers' existing error classes.
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

    Only when the total started as an estimate, and only to
    rows proven to exist — an EXACT count is never raised, an empty page
    proves nothing (flooring by offset + len(rows) would invent matches out
    of the offset alone), and a keyset page passes offset=0 since the query
    ignores it when after_gid is set.
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

    ``total_is_estimate`` is True past ``_FILTERED_COUNT_CAP``,
    and ``has_more`` (not ``total``) must drive pagination links.
    ``cql2_where``/``cql2_binds`` must come from
    ``app.standards.ogc.filtering``, the only sanctioned
    producer of typed CQL2 binds. Raises ValueError (400) on a bad property
    filter or an out-of-int8 pagination integer.
    """
    # Pagination integers reach the driver untyped, and FastAPI's
    # `int` has no upper bound. A value outside int8 can't be encoded at all
    # — asyncpg raises a bare DBAPIError (SQLSTATE 22000) from its encode
    # path — so refuse it here, where the message can name the parameter.
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

    # `gid > :after_gid` short-circuits the OFFSET cost path entirely, and
    # reuses the existing PRIMARY KEY index on `gid` — no new index needed.
    use_keyset = after_gid is not None
    if use_keyset:
        where_clauses.append("gid > :after_gid")
        bind_values["after_gid"] = after_gid

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

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
    # One row past the page, so `has_more` is a fact about the
    # rows rather than a comparison against a count that may be estimated.
    bind_values["limit"] = limit + 1

    # cql2_binds plus the property-filter binds typed from the live schema
    # Both name parameters in the data query and the count query
    # query, so one list serves both.
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

    # The keyset cursor is excluded from the count (no LIMIT/OFFSET either),
    # so total reflects the full result set, not "rows remaining after cursor".
    count_where_clauses = [c for c in where_clauses if c != "gid > :after_gid"]
    count_where_sql = ""
    if count_where_clauses:
        count_where_sql = "WHERE " + " AND ".join(count_where_clauses)

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
    data_sql = f"SELECT {select_cols} FROM {row_source} t ORDER BY gid LIMIT :limit"
    result = await db.execute(text(data_sql).bindparams(limit=cap + 1))
    rows = [dict(row._mapping) for row in result.all()]

    truncated = len(rows) > cap
    if truncated:
        rows = rows[:cap]

    if not truncated:
        total_count = len(rows)
    elif cached_feature_count is not None:
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

    Generic-column created datasets must accept ANY subtype
    forever, even after refresh_dataset_metadata derives a concrete DISPLAY
    type from the rows (so the builder renders the layer instead of an
    invisible fill). Validation keys on the actual column genericity, never
    on the derived type. Typed 'created' tables (layers module) keep typed
    validation.
    """
    if dataset.source_format == "created" and await _geom_column_is_generic(
        session, dataset.table_name
    ):
        return "GEOMETRY"
    return dataset.geometry_type


def _validate_geometry_structure(geometry: dict) -> BaseGeometry:
    """Reject degenerate or topologically invalid geometry before PostGIS.

    Degenerate-but-valid input (2-point rings, empty arrays)
    crashed ST_GeomFromGeoJSON into a 500; raises ValueError instead (400).

    Returns the shapely geometry itself, not None — Shapely
    auto-closes an unclosed ring but ST_GeomFromGeoJSON does not, so callers
    must write the returned, normalized geometry, not the client's dict.
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
    # A generic-typed dataset (GEOMETRY column) accepts any subtype;
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
        # Without this entry a GEOMETRYCOLLECTION-typed dataset
        # normalizes to its raw uppercase name and never matches the
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
    # Replace nulls every known column, so an unwritable one makes
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
    # codeql[py/sql-injection] every assigned column is an existing column_info name matching _COLUMN_NAME_RE; values travel as bound params; table via quote_table
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
    # Records.spatial_extent admits only POLYGON or
    # MULTIPOLYGON (chk_records_spatial_extent_type, ), but
    # ST_Extent of a single point / axis-collinear points casts to POINT /
    # LINESTRING and would be rejected. ST_Expand always returns the
    # bounding-box POLYGON, so only the degenerate cases get padded;
    # genuine polygon extents come back byte-identical (no epsilon).
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
    # A table honestly crossing ±180 must not store the naive
    # near-global fold on refresh; emit the two-ring MULTIPOLYGON instead. A
    # crossing dataset's naive width always exceeds 180 degrees, so the
    # ordinary case skips the second aggregate and stays byte-identical.
    if xmin is not None and xmax is not None and float(xmax) - float(xmin) > 180.0:
        # Same tenant data schema the quoted reference above resolves to;
        # the helper quotes identifiers itself.
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

    The 'GEOMETRY' sentinel renders as an invisible fill layer in
    the builder (classifyGeometry -> 'other'). Derive from the rows:
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
# Captured as part of the mutating statement, not a separate
# unlocked SELECT before it — a concurrent edit could otherwise move the
# feature out of the stored extent and commit in the gap, leaving envelope
# values that were true when read but false by the time of the write, and
# the incremental fast path leaving the expanded extent behind.
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


async def lock_catalog_rows_for_write(
    session: AsyncSession, dataset: Dataset, *, with_raster_asset: bool = False
) -> Bounds | None:
    """Take this dataset's catalog rows in the house order, then read its extent.

    Entry point to `platform.catalog_locks.lock_catalog_rows` — call from
    ANY request path that dirties either row. Returns None unless the extent
    is a simple POLYGON: an antimeridian-crossing dataset stores a
    two-ring MULTIPOLYGON whose ST_XMin/ST_XMax are -180/180, so a longitude
    in the gap would test inside a box the geometry never occupies.
    The lock must be taken before either metadata path reads the
    extent, or interleaved read-decide-write could shrink it from a stale
    aggregate.
    """
    from app.modules.catalog.datasets.domain.models import Dataset as DatasetModel
    from app.modules.catalog.datasets.domain.models import Record
    from app.platform.catalog_locks import lock_catalog_rows

    # Through the port: `catalog/` may not import `app.processing.*`
    # as enforced by the layering test.
    raster_asset_cls = (
        get_catalog_port().raster_asset_orm_class() if with_raster_asset else None
    )

    await lock_catalog_rows(
        session,
        dataset_cls=DatasetModel,
        record_cls=Record,
        dataset_id=dataset.id,
        record_id=dataset.record_id,
        raster_asset_cls=raster_asset_cls,
    )

    # Both rows are held now, so this is an ordinary read.
    result = await session.execute(
        select(
            func.GeometryType(Record.spatial_extent),
            func.ST_XMin(Record.spatial_extent),
            func.ST_YMin(Record.spatial_extent),
            func.ST_XMax(Record.spatial_extent),
            func.ST_YMax(Record.spatial_extent),
        ).where(Record.id == dataset.record_id)
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

    Mirrors `_derive_created_geometry_type`'s rules without the DISTINCT
    scan; None sends the caller back to the scan. Insert only — a delete or
    moved geometry can NARROW the derived type, which no merge can see.
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

    Returns False when the fast path does not apply, falling back to a full
    recompute. `_refresh_count_and_extent` runs a full-table
    COUNT + ST_Extent on every write, so a client digitizing 200 points
    paid that cost 200 times with no bulk feature endpoint.
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

    Uses one COUNT(*) + ST_Extent query instead of the 5-query
    extract_metadata pipeline. When every touched envelope is
    strictly inside the stored extent, it provably did not change and no
    scan runs at all; called with no keywords, the full recompute is
    unchanged.
    """
    # Taken before EITHER branch reads the extent, so a skip
    # decision cannot be invalidated by a concurrent recompute.
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

    # INSIDE the lock, deliberately. A peer that measured before
    # taking the lock cannot see this transaction's uncommitted row, and would
    # write a count and extent computed as though it did not exist.
    feature_count, extent_wkt = await _refresh_count_and_extent(
        session, dataset.table_name
    )
    dataset.feature_count = feature_count

    # ST_Extent of a single point is a POINT and of axis-collinear
    # points a LINESTRING, not always a POLYGON -- store any non-null extent.
    if extent_wkt:
        dataset.record.spatial_extent = func.ST_GeomFromText(extent_wkt, 4326)
    elif feature_count == 0:
        dataset.record.spatial_extent = None

    # Keep generic-column created datasets' DISPLAY
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
