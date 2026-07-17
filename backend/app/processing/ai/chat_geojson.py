"""Geometry detection & GeoJSON helpers for ephemeral chat result layers.

Phase 276 CODE-02 — extracted from chat_service.py.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import shapely
import sqlglot
from shapely.geometry import shape as shapely_shape
from sqlglot import exp

_GEOM_NAMES = {"geom_4326", "geom", "geometry", "the_geom", "wkb_geometry"}
_HEX_RE = re.compile(r"^[0-9a-fA-F]{10,}$")

# Anonymous-func aggregates the isinstance(exp.AggFunc) check misses (sqlglot
# parses them as exp.Anonymous — see the sandbox validator's allowlist notes).
# Appending a bare column beside one of these without GROUP BY would make the
# query invalid, so their presence disables the geometry append.
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


def _selects_geometry(item: exp.Expression) -> bool:
    """True when a select item already yields a geometry-detectable column."""
    if isinstance(item, exp.Alias):
        name = item.alias.lower()
        return name in _GEOM_NAMES or name.startswith("st_")
    if isinstance(item, exp.Column):
        return item.name.lower() in _GEOM_NAMES
    if isinstance(item, exp.Func):
        return item.name.lower() in _GEOM_RETURNING_FUNCS
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
        if item.find(exp.Star):
            return sql  # SELECT * already includes the geometry column
        for fn in item.find_all(exp.Func):
            if isinstance(fn, exp.AggFunc) or fn.name.lower() in _ANON_AGG_NAMES:
                return sql
        if _selects_geometry(item):
            return sql
    stmt.select(f"{table.alias_or_name}.geom_4326", copy=False)
    return stmt.sql(dialect="postgres")


_GEOJSON_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


def _is_geometry_cell(val: object) -> bool:
    """Value-based geometry check for column stripping.

    Like _is_geom_value but the JSON branch requires an actual GeoJSON
    geometry type, so a jsonb attribute column that merely contains a
    "type" key is not misclassified.
    """
    if not isinstance(val, str):
        return False
    if len(val) >= 10 and len(val) % 2 == 0 and _HEX_RE.match(val):
        return True
    if val.startswith("{"):
        try:
            return json.loads(val).get("type") in _GEOJSON_TYPES
        except Exception:  # broad: not JSON — then not a geometry cell
            return False
    return False


def strip_geometry_columns(
    columns: list[str], rows: list[list]
) -> tuple[list[str], list[list]]:
    """Drop geometry-valued columns from tabular chat output (fix #544).

    Raw WKB hex / GeoJSON strings are noise in a result table; geometry
    travels via the geojson payload instead. Value-based (first row), not
    name-based: the model may alias geometry to anything (live smoke found
    ``ST_AsGeoJSON(geom_4326) AS location`` surviving a name-only strip).
    """
    if not rows:
        return columns, rows
    first = rows[0]
    kept = [
        i
        for i in range(len(columns))
        if not _is_geometry_cell(first[i] if i < len(first) else None)
    ]
    if len(kept) == len(columns):
        return columns, rows
    return (
        [columns[i] for i in kept],
        [[row[i] if i < len(row) else None for i in kept] for row in rows],
    )


def _is_geom_value(val: object) -> bool:
    """Check if a value looks like WKB hex or ST_AsGeoJSON output."""
    if not isinstance(val, str):
        return False
    # WKB hex: long even-length hex string
    if len(val) >= 10 and len(val) % 2 == 0 and _HEX_RE.match(val):
        return True
    # ST_AsGeoJSON: JSON string containing geometry type
    if val.startswith("{") and '"type"' in val:
        return True
    return False


def _detect_geom_column(columns: list[str], first_row: list) -> int | None:
    """Find the index of a geometry column by name + value check."""
    for i, col in enumerate(columns):
        name = col.lower()
        if name in _GEOM_NAMES or name.startswith("st_"):
            if i < len(first_row) and _is_geom_value(first_row[i]):
                return i
    return None


def _safe_value(v: object) -> object:
    """Convert non-JSON-serializable types to str; pass through primitives."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (datetime, date, Decimal, bytes, memoryview, UUID)):
        return str(v)
    return str(v)


def _extract_geojson(
    columns: list[str], rows: list[list]
) -> tuple[dict, list[float]] | None:
    """Build a GeoJSON FeatureCollection + bbox from query rows."""
    if not rows:
        return None

    geom_idx = _detect_geom_column(columns, rows[0])
    if geom_idx is None:
        return None

    prop_indices = [(i, col) for i, col in enumerate(columns) if i != geom_idx]
    features: list[dict] = []
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
        try:
            if isinstance(raw, str) and raw.startswith("{"):
                geom_dict = json.loads(raw)
                shape = shapely_shape(geom_dict)
                geometry = geom_dict
            else:
                shape = shapely.from_wkb(bytes.fromhex(raw))
                geometry = json.loads(shapely.to_geojson(shape))
        except Exception:  # broad: per-row geometry parse — JSON/WKB/Shapely can throw varied errors; skip bad rows
            continue

        # Build properties
        props = {}
        for idx, col_name in prop_indices:
            props[col_name] = _safe_value(row[idx] if idx < len(row) else None)

        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": props,
            }
        )

        # Update bbox
        bx = shape.bounds  # (minx, miny, maxx, maxy)
        if bx[0] < min_x:
            min_x = bx[0]
        if bx[1] < min_y:
            min_y = bx[1]
        if bx[2] > max_x:
            max_x = bx[2]
        if bx[3] > max_y:
            max_y = bx[3]

    if not features:
        return None

    fc = {"type": "FeatureCollection", "features": features}
    bbox = [min_x, min_y, max_x, max_y]
    return fc, bbox
