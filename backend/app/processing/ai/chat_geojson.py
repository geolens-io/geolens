"""Geometry detection & GeoJSON helpers for ephemeral chat result layers.

Phase 276 CODE-02 — extracted from chat_service.py.
"""

import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import shapely
import sqlglot
import structlog
from shapely.geometry import shape as shapely_shape
from sqlglot import exp

logger = structlog.stdlib.get_logger(__name__)

_GEOM_NAMES = {"geom_4326", "geom", "geometry", "the_geom", "wkb_geometry"}
_HEX_RE = re.compile(r"^[0-9a-fA-F]{10,}$")

# Aggregate names checked ONLY on exp.Anonymous nodes (see the guard in
# ensure_geometry_selected). In current sqlglot only EVERY parses as Anonymous;
# MODE/PERCENTILE_CONT/PERCENTILE_DISC are exp.AggFunc subclasses already caught
# by isinstance. The others are retained as a version-drift guard — harmless
# because the Anonymous gate keeps them from matching a same-named column.
_ANON_AGG_NAMES = {"every", "mode", "percentile_cont", "percentile_disc"}

# Unaliased calls to these produce an st_*-named output column that
# _detect_geom_column already recognizes as geometry — no append needed.
_GEOM_RETURNING_FUNCS = {
    "st_asgeojson",
    "st_buffer",
    "st_centroid",
    "st_collect",
    "st_makepoint",
    "st_point",
    "st_setsrid",
    "st_transform",
    "st_union",
}


def _func_name(fn: exp.Func) -> str:
    if isinstance(fn, exp.Anonymous):
        return fn.name.lower()
    return fn.sql_name().lower() if hasattr(fn, "sql_name") else ""


def _selects_geometry(item: exp.Expression) -> bool:
    """True when a select item already yields a geometry-valued column.

    Structural, never name-based (#556 review P2): a scalar aliased to a
    geometry-looking name — ``md5(name) AS geometry``, ``ST_X(geom_4326) AS
    st_x`` — must NOT count as selected geometry. If it did, the append is
    skipped and the strict value parser then finds no geometry to overlay,
    reintroducing the missing-map regression. Only the underlying expression
    (a ``geom_4326`` column, or a geometry-returning function) decides.

    Alias and Cast/Paren wrappers are unwrapped first, and — #556 review —
    the unwrap runs for the UNALIASED case too, so a bare
    ``ST_Buffer(...)::geometry`` (no ``AS``) correctly suppresses the append
    instead of getting a redundant second geometry column bolted on.
    """
    if isinstance(item, exp.Alias):
        item = item.this
    while isinstance(item, (exp.Cast, exp.Paren)):
        item = item.this
    if isinstance(item, exp.Column):
        return item.name.lower() in _GEOM_NAMES
    if isinstance(item, exp.Func):
        return _func_name(item) in _GEOM_RETURNING_FUNCS
    return False


def ensure_geometry_selected(sql: str, layers) -> str:
    """fix(#544): deterministically append geom_4326 to row-level selects.

    The SQL model is free to answer a location-shaped question with attribute
    columns only, which silently drops the map overlay on every chat surface.
    Rather than a model-dependent prompt rule, rewrite the generated SQL: when
    it is a plain single-table SELECT from a layer that has geometry and no
    geometry column in the select list, append the table's geom_4326.

    Conservative by design — any shape where the appended column could change
    results or break the query (aggregates, GROUP BY, DISTINCT, joins, CTEs,
    set operations, SELECT *) is returned unchanged.
    """
    geom_tables = {layer.dataset_table_name for layer in layers if layer.geometry_type}
    if not geom_tables:
        return sql
    try:
        stmt = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:  # broad: unparseable SQL is the sandbox validator's job
        return sql
    if not isinstance(stmt, exp.Select):
        return sql
    if (
        stmt.args.get("group")
        or stmt.args.get("distinct")
        or stmt.find(exp.With)  # any CTE, top-level or nested — stay out
        or stmt.args.get("joins")
        # fix(#556 review P2): HAVING without GROUP BY is still an aggregate
        # (implicit single group), and its COUNT(*) lives outside the SELECT
        # list where the per-item aggregate check can't see it. args.get scopes
        # to THIS query, so a subquery's HAVING doesn't suppress the append.
        or stmt.args.get("having")
    ):
        return sql
    # sqlglot renamed the arg key "from" -> "from_" across versions
    from_clause = stmt.args.get("from") or stmt.args.get("from_")
    if from_clause is None:
        return sql
    table = from_clause.this
    if (
        not isinstance(table, exp.Table)
        or table.db != "data"
        or table.name not in geom_tables
    ):
        return sql
    for item in stmt.expressions:
        # A bare * or table.* already includes the geometry column. fix(#556
        # review P2): match only a genuine all-columns star, NOT a functional
        # star like COUNT(*) — item.find(exp.Star) caught the latter and
        # suppressed the append for windowed COUNT(*) OVER () queries.
        if isinstance(item, exp.Star) or (
            isinstance(item, exp.Column) and isinstance(item.this, exp.Star)
        ):
            return sql
        for fn in item.find_all(exp.Func):
            # fix(#556 review P2): only consult _ANON_AGG_NAMES for exp.Anonymous
            # nodes. On a named Func, fn.name is arg-derived, not the function
            # name — CAST(mode AS TEXT) reports name="mode", which would falsely
            # trip the guard and drop the overlay for any row-level query that
            # casts a column named mode/every/percentile_*. (Mirrors the
            # sandbox validator's Anonymous-vs-named name resolution.)
            is_agg = isinstance(fn, exp.AggFunc) or (
                isinstance(fn, exp.Anonymous) and fn.name.lower() in _ANON_AGG_NAMES
            )
            # A WINDOWED aggregate — COUNT(*) OVER (), RANK() OVER (ORDER BY ...)
            # — is row-level (one row per input row, no GROUP BY), so appending
            # geom_4326 is safe. Only a true, non-windowed aggregate collapses
            # cardinality and must block it.
            if is_agg and fn.find_ancestor(exp.Window) is None:
                return sql
        if _selects_geometry(item):
            return sql
    # fix(#556 review P2): build the qualifier from the alias/table AST
    # identifier (not an f-string) so a quoted alias survives — FROM ... AS "P"
    # must append "P".geom_4326 (unquoted P folds to lowercase and fails), and
    # an alias with spaces must not raise a ParseError inside stmt.select().
    alias_node = table.args.get("alias")
    ref_ident = alias_node.this if alias_node is not None else table.this
    geom_col = exp.Column(this=exp.to_identifier("geom_4326"), table=ref_ident.copy())
    stmt.select(geom_col, copy=False)
    rendered = stmt.sql(dialect="postgres")
    # fix(#556 review P2): sqlglot's postgres dialect does not faithfully
    # round-trip every pgvector/PostGIS distance operator — `<=>` (cosine) is
    # re-serialized as IS NOT DISTINCT FROM, silently turning nearest-neighbor
    # ranking into boolean equality. Re-rendering only happens on the append
    # path, so if it dropped any distance operator the original had, sacrifice
    # the overlay and return the untouched SQL. (`<#>` already fails parse_one
    # above and never reaches here.)
    for op in ("<=>", "<->", "<#>"):
        if sql.count(op) > rendered.count(op):
            return sql
    return rendered


_GEOJSON_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


def _is_geom_value(val: object) -> bool:
    """Strict, parse-verified geometry check.

    A candidate must actually parse — a hex-like attribute (``md5(name)``)
    or a jsonb attribute that merely contains a ``"type"`` key is NOT a
    geometry, and must not shadow the real geometry column (#556 review).
    Used for both name-preferred detection and value-based stripping, so a
    geometry-*named* column holding a non-WKB hash falls through to the
    real column instead of being accepted and failing extraction later.
    """
    if not isinstance(val, str):
        return False
    if val.startswith("{"):
        try:
            obj = json.loads(val)
            return obj.get("type") in _GEOJSON_TYPES and shapely_shape(obj) is not None
        except Exception:  # broad: not parseable GeoJSON — not a geometry cell
            return False
    if len(val) >= 10 and len(val) % 2 == 0 and _HEX_RE.match(val):
        try:
            shapely.from_wkb(bytes.fromhex(val))
            return True
        except Exception:  # broad: hex but not WKB (e.g. a hash column)
            return False
    return False


def _first_non_null(rows: list[list], i: int) -> object:
    """First non-null value in column i (fix #556 review P2: probing only
    rows[0] made a NULL leading geometry break detection and stripping)."""
    for row in rows:
        val = row[i] if i < len(row) else None
        if val is not None:
            return val
    return None


def strip_geometry_columns(
    columns: list[str], rows: list[list]
) -> tuple[list[str], list[list]]:
    """Drop geometry-valued columns from tabular chat output (fix #544).

    Raw WKB hex / GeoJSON strings are noise in a result table; geometry
    travels via the geojson payload instead. Value-based, not name-based:
    the model may alias geometry to anything (live smoke found
    ``ST_AsGeoJSON(geom_4326) AS location`` surviving a name-only strip).
    """
    if not rows:
        return columns, rows
    kept = [
        i for i in range(len(columns)) if not _is_geom_value(_first_non_null(rows, i))
    ]
    if len(kept) == len(columns):
        return columns, rows
    return (
        [columns[i] for i in kept],
        [[row[i] if i < len(row) else None for i in kept] for row in rows],
    )


def _detect_geom_column(columns: list[str], rows: list[list]) -> int | None:
    """Find the index of a geometry column.

    A geometry-*named* column that actually parses is preferred; otherwise
    fall back to any column whose value parses as geometry (fix #556 review:
    aliased computed geometry such as ``ST_Buffer(...) AS buffer``). Both
    phases use the strict, parse-verified _is_geom_value so a geometry-named
    hash column cannot shadow the real geometry, and values are probed at the
    first non-null row (not row 0) so a NULL leading geometry still detects.
    """
    for i, col in enumerate(columns):
        name = col.lower()
        if name in _GEOM_NAMES or name.startswith("st_"):
            if _is_geom_value(_first_non_null(rows, i)):
                return i
    for i in range(len(columns)):
        if _is_geom_value(_first_non_null(rows, i)):
            return i
    return None


# JavaScript numbers are IEEE-754 doubles, so an integer beyond this magnitude
# cannot round-trip through the browser's JSON.parse.
_JS_MAX_SAFE_INT = 2**53 - 1


def _safe_value(v: object) -> object:
    """Convert values the client cannot represent to str; pass through the rest.

    fix(#1241 codex r5): an integer outside JavaScript's safe range is
    JSON-serializable and still lossy — 9007199254740993 arrives in the browser
    as 9007199254740992, because JSON.parse rounds it to the nearest double.
    That silently wrong id was always on screen; it becomes permanent now that
    the map builder can save a chat preview as a dataset, since the snapshot is
    serialized from the parsed payload. Emitting the exact digits as a string
    is the only shape that survives the trip. Every smaller integer stays a
    number, so ordinary ids keep their type.

    fix(#1778): NaN and +/-Infinity are the other values the client cannot
    represent, and PostgreSQL ``real``/``double precision`` legally hold all
    three. ``json.dumps`` writes them as the bare tokens ``NaN``/``Infinity``,
    which ``JSON.parse`` rejects, so one such cell used to make the whole
    actions frame unparseable: the browser dropped it silently and the
    non-streaming endpoint returned 500 (Starlette renders with
    ``allow_nan=False``). They become null, which the client can hold.
    """
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, int):
        # bool is an int subclass and already returned above.
        return str(v) if abs(v) > _JS_MAX_SAFE_INT else v
    if isinstance(v, (datetime, date, Decimal, bytes, memoryview, UUID)):
        return str(v)
    return str(v)


def _parse_row_geometry(raw: object) -> tuple[object, dict] | None:
    """Parse one row's geometry cell into (shapely geometry, GeoJSON dict).

    Returns None for a cell that is neither GeoJSON text nor WKB hex, so the
    caller can skip that row.
    """
    try:
        if isinstance(raw, str) and raw.startswith("{"):
            geom_dict = json.loads(raw)
            return shapely_shape(geom_dict), geom_dict
        shape = shapely.from_wkb(bytes.fromhex(raw))  # type: ignore[arg-type]
        return shape, json.loads(shapely.to_geojson(shape))
    except Exception:  # broad: per-row geometry parse — JSON/WKB/Shapely can throw varied errors; skip bad rows
        return None


def _row_properties(row: list, prop_indices: list[tuple[int, str]]) -> tuple[dict, int]:
    """Build one Feature's properties, counting non-finite float cells.

    The count feeds the single warning `_extract_geojson` emits per result
    (fix(#1778)); logging per cell would be unusable on a wide table.
    """
    props: dict = {}
    non_finite = 0
    for idx, col_name in prop_indices:
        raw_prop = row[idx] if idx < len(row) else None
        if isinstance(raw_prop, float) and not math.isfinite(raw_prop):
            non_finite += 1
        props[col_name] = _safe_value(raw_prop)
    return props, non_finite


def _extract_geojson(
    columns: list[str], rows: list[list]
) -> tuple[dict, list[float] | None] | None:
    """Build a GeoJSON FeatureCollection + bbox from query rows.

    The bbox is ``None`` when no row contributed finite bounds (fix(#1778)).
    Callers must omit the bbox from their payload in that case rather than
    forwarding a non-finite one.
    """
    if not rows:
        return None

    geom_idx = _detect_geom_column(columns, rows)
    if geom_idx is None:
        return None

    prop_indices = [(i, col) for i, col in enumerate(columns) if i != geom_idx]
    features: list[dict] = []
    non_finite_props = 0
    non_finite_bounds = 0
    min_x, min_y, max_x, max_y = (
        float("inf"),
        float("inf"),
        float("-inf"),
        float("-inf"),
    )

    for row in rows:
        raw = row[geom_idx] if geom_idx < len(row) else None
        if raw is None:
            continue

        # Parse geometry
        parsed = _parse_row_geometry(raw)
        if parsed is None:
            continue
        shape, geometry = parsed

        # Build properties
        props, row_non_finite = _row_properties(row, prop_indices)
        non_finite_props += row_non_finite

        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": props,
            }
        )

        # Update bbox
        bx = shape.bounds  # (minx, miny, maxx, maxy)
        # fix(#1778): Shapely returns (nan, nan, nan, nan) for an EMPTY
        # geometry, and an EMPTY geometry parses, so the row above already
        # became a Feature while every comparison here is False against NaN.
        # A result whose geometries are all EMPTY (ST_Buffer(<point>, 0) yields
        # one for every row, and a dataset may legitimately store them) left
        # the infinite seeds untouched and shipped [inf, inf, -inf, -inf].
        if not all(math.isfinite(c) for c in bx):
            non_finite_bounds += 1
            continue
        if bx[0] < min_x:
            min_x = bx[0]
        if bx[1] < min_y:
            min_y = bx[1]
        if bx[2] > max_x:
            max_x = bx[2]
        if bx[3] > max_y:
            max_y = bx[3]

    if non_finite_props or non_finite_bounds:
        logger.warning(
            "chat.geojson_non_finite_values",
            non_finite_properties=non_finite_props,
            non_finite_bounds=non_finite_bounds,
            row_count=len(rows),
        )

    if not features:
        return None

    fc = {"type": "FeatureCollection", "features": features}
    if not all(math.isfinite(c) for c in (min_x, min_y, max_x, max_y)):
        # No row contributed finite bounds. Degrade to a table with no overlay
        # rather than a frame the browser cannot parse.
        return fc, None
    bbox = [min_x, min_y, max_x, max_y]
    return fc, bbox
