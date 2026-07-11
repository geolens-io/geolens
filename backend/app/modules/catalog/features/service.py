"""Feature query service: paginated GeoJSON features from PostGIS data tables."""

from __future__ import annotations

import json
import math
import re
from typing import TYPE_CHECKING

from shapely.errors import GEOSException
from shapely.geometry import shape as shapely_shape
from shapely.validation import explain_validity
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.extensions import get_catalog_port

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import Dataset

# Column name validation for SQL identifier safety
_COLUMN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

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


def parse_bbox(bbox_str: str) -> list[float]:
    """Parse a comma-separated bbox string into a 4- or 6-element list.

    Accepts:
      - 4 values: minx, miny, maxx, maxy (2D)
      - 6 values: minx, miny, minz, maxx, maxy, maxz (3D — Z values are
        accepted but ignored for spatial queries)

    Allows antimeridian-crossing bboxes where minx > maxx (e.g. 170,-45,-170,-30).
    Raises ValueError if not 4 or 6 values, or latitude bounds are invalid.
    """
    parts = bbox_str.split(",")
    if len(parts) not in (4, 6):
        raise ValueError("bbox must have 4 or 6 comma-separated values")
    values = [float(p) for p in parts]
    # SEC-FU-06 (sec-audit-20260519.md): reject NaN/Inf coordinates. Python's float() accepts
    # "nan", "inf", "-inf" — PostGIS handles these inconsistently and they can produce
    # malformed geometries with downstream null-pointer or sequential-scan amplification.
    for i, v in enumerate(values):
        if not math.isfinite(v):
            raise ValueError(
                f"SEC-FU-06: bbox coordinate at index {i} is non-finite ({v!r}); "
                "only finite floats are accepted"
            )
    if len(values) == 6:
        # 3D bbox: extract 2D envelope (minx, miny, maxx, maxy)
        values = [values[0], values[1], values[3], values[4]]
    # Only validate latitude (lon wraps at antimeridian)
    if values[1] >= values[3]:
        raise ValueError("bbox miny must be less than maxy")
    return values


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
) -> tuple[list[dict], int]:
    """Fetch paginated features from a data table as GeoJSON-ready dicts.

    Returns (rows, total_count) where each row has gid, geometry, and properties.

    Phase 269 H-24: when ``after_gid`` is provided, uses keyset pagination
    (``WHERE gid > :after_gid``) instead of OFFSET. This avoids the
    ``OFFSET 999000`` deep-paging cost. The ``offset`` parameter remains
    supported as a legacy fallback for clients that have not migrated to
    cursor pagination.
    """
    # Build SELECT columns
    if has_geometry and include_geometry:
        select_cols = (
            "gid, ST_AsGeoJSON(geom_4326, 6)::json AS geometry, "
            "to_jsonb(t.*) - 'gid' - 'geom' - 'geom_4326' AS properties"
        )
    elif has_geometry:
        select_cols = (
            "gid, NULL::json AS geometry, "
            "to_jsonb(t.*) - 'gid' - 'geom' - 'geom_4326' AS properties"
        )
    else:
        select_cols = "gid, NULL::json AS geometry, to_jsonb(t.*) - 'gid' AS properties"

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

    if property_filters and allowed_columns:
        for col, val in property_filters.items():
            if col in allowed_columns and _COLUMN_NAME_RE.match(col):
                param_name = f"prop_{col}"
                where_clauses.append(f'"{col}" = :{param_name}')
                bind_values[param_name] = val

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
            f"SELECT {select_cols} FROM {get_catalog_port().quote_table(table_name)} t "
            f"{where_sql} ORDER BY gid LIMIT :limit"
        )
    else:
        data_sql = (
            f"SELECT {select_cols} FROM {get_catalog_port().quote_table(table_name)} t "
            f"{where_sql} ORDER BY gid LIMIT :limit OFFSET :offset"
        )
        bind_values["offset"] = offset
    bind_values["limit"] = limit

    result = await db.execute(text(data_sql).bindparams(**bind_values))
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
        total = cached_feature_count
    else:
        count_bind = {
            k: v
            for k, v in bind_values.items()
            if k not in ("limit", "offset", "after_gid")
        }
        count_sql = (
            f"SELECT COUNT(*) FROM {get_catalog_port().quote_table(table_name)} "
            f"t {count_where_sql}"
        )
        count_result = await db.execute(text(count_sql).bindparams(**count_bind))
        total = count_result.scalar_one()

    return rows, total


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
        "to_jsonb(t.*) - 'gid' - 'geom' - 'geom_4326' AS properties"
    )
    # Fetch cap+1 to detect truncation without a separate COUNT query
    data_sql = (
        f"SELECT {select_cols} FROM {get_catalog_port().quote_table(table_name)} "
        "t ORDER BY gid LIMIT :limit"
    )
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
            "to_jsonb(t.*) - 'gid' - 'geom' - 'geom_4326' AS properties"
        )
    else:
        select_cols = "gid, NULL::json AS geometry, to_jsonb(t.*) - 'gid' AS properties"

    sql = (
        f"SELECT {select_cols} FROM {get_catalog_port().quote_table(table_name)} "
        "t WHERE gid = :gid"
    )
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
    result = await session.execute(
        text(
            "SELECT type FROM geometry_columns "
            "WHERE f_table_schema = 'data' AND f_table_name = :t "
            "AND f_geometry_column = 'geom'"
        ).bindparams(t=table_name)
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


def _validate_geometry_structure(geometry: dict) -> None:
    """Reject degenerate or topologically invalid geometry before PostGIS.

    fix(#458 E-02): degenerate-but-schema-valid input (2-point polygon rings,
    1-vertex LineStrings, empty coordinate arrays) crashed ST_GeomFromGeoJSON
    into a 500, and well-formed self-intersecting polygons persisted and later
    raised GEOS TopologyException on bbox queries and tile renders — read-path
    500s that hit anonymous viewers of public datasets. Raises ValueError
    (routers map it to 400).
    """
    try:
        geom = shapely_shape(geometry)
    except (GEOSException, ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid geometry: {exc}") from exc
    if geom.is_empty:
        raise ValueError("Invalid geometry: geometry is empty")
    if not geom.is_valid:
        raise ValueError(f"Invalid geometry: {explain_validity(geom)}")


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
    _validate_geometry_structure(geometry)

    geojson_str = json.dumps(geometry)

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
    _validate_geometry_structure(geometry)

    geojson_str = json.dumps(geometry)
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
        _validate_geometry_structure(geometry)
        geojson_str = json.dumps(geometry)
        geom_expr, geom_4326_expr = _geom_write_exprs(
            dataset_geometry_type, dataset_srid
        )
        sets.append(f"geom = {geom_expr}")
        sets.append(f"geom_4326 = {geom_4326_expr}")
        params["geojson"] = geojson_str

    if properties is not None:
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
    # fix(#430 BA-18): records.spatial_extent is a POLYGON column, but ST_Extent of a
    # single point / axis-collinear points casts to POINT / LINESTRING, which the
    # column rejects (previously the caller silently skipped storing it, leaving a
    # stale/NULL extent). ST_Expand always returns the bounding-box POLYGON, so we
    # pad ONLY the degenerate (non-polygon) cases into a valid sub-mm-padded
    # polygon; genuine polygon extents are returned byte-identical (no epsilon).
    result = await session.execute(
        text(
            f"SELECT COUNT(*), "
            f"CASE "
            f"  WHEN ST_Extent(geom_4326) IS NULL THEN NULL "
            f"  WHEN GeometryType(ST_Extent(geom_4326)::geometry) = 'POLYGON' "
            f"    THEN ST_AsText(ST_SetSRID(ST_Extent(geom_4326)::geometry, 4326)) "
            f"  ELSE ST_AsText("
            f"    ST_Expand(ST_SetSRID(ST_Extent(geom_4326)::geometry, 4326), 1e-9)) "
            f"END "
            f"FROM {get_catalog_port().quote_table(table_name)}"
        )
    )
    row = result.one()
    return int(row[0]), row[1]


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
