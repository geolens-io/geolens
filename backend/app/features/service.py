"""Feature query service: paginated GeoJSON features from PostGIS data tables."""

import json
import re

from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingest.metadata import extract_metadata

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


def _validate_table_name(table_name: str) -> None:
    """Validate table name to prevent SQL injection."""
    if not re.match(r"^[a-z0-9_]+$", table_name):
        raise ValueError(f"Invalid table name: {table_name}")


def parse_bbox(bbox_str: str) -> list[float]:
    """Parse a comma-separated bbox string into [minx, miny, maxx, maxy].

    Allows antimeridian-crossing bboxes where minx > maxx (e.g. 170,-45,-170,-30).
    Raises ValueError if not exactly 4 values or latitude bounds are invalid.
    """
    parts = bbox_str.split(",")
    if len(parts) != 4:
        raise ValueError("bbox must have exactly 4 comma-separated values")
    values = [float(p) for p in parts]
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
) -> tuple[list[dict], int]:
    """Fetch paginated features from a data table as GeoJSON-ready dicts.

    Returns (rows, total_count) where each row has gid, geometry, and properties.
    """
    _validate_table_name(table_name)

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
            # Antimeridian-crossing: split into two envelopes
            where_clauses.append(
                "(ST_Intersects(geom_4326, ST_MakeEnvelope(:minx, :miny, 180, :maxy, 4326))"
                " OR ST_Intersects(geom_4326, ST_MakeEnvelope(-180, :miny, :maxx, :maxy, 4326)))"
            )
        else:
            where_clauses.append(
                "ST_Intersects(geom_4326, ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326))"
            )
        bind_values["minx"] = bbox[0]
        bind_values["miny"] = bbox[1]
        bind_values["maxx"] = bbox[2]
        bind_values["maxy"] = bbox[3]

    if property_filters and allowed_columns:
        for col, val in property_filters.items():
            if col in allowed_columns:
                param_name = f"prop_{col}"
                where_clauses.append(f'"{col}" = :{param_name}')
                bind_values[param_name] = val

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # Data query
    data_sql = (
        f"SELECT {select_cols} FROM data.{table_name} t "
        f"{where_sql} ORDER BY gid LIMIT :limit OFFSET :offset"
    )
    bind_values["limit"] = limit
    bind_values["offset"] = offset

    result = await db.execute(text(data_sql).bindparams(**bind_values))
    rows = [dict(row._mapping) for row in result.all()]

    # Count query (same WHERE, no LIMIT/OFFSET)
    # Use cached feature_count when no filters are active
    if not where_clauses and cached_feature_count is not None:
        total = cached_feature_count
    else:
        count_bind = {k: v for k, v in bind_values.items() if k not in ("limit", "offset")}
        count_sql = f"SELECT COUNT(*) FROM data.{table_name} t {where_sql}"
        count_result = await db.execute(text(count_sql).bindparams(**count_bind))
        total = count_result.scalar_one()

    return rows, total


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
    _validate_table_name(table_name)

    if has_geometry:
        select_cols = (
            "gid, ST_AsGeoJSON(geom_4326, 6)::json AS geometry, "
            "to_jsonb(t.*) - 'gid' - 'geom' - 'geom_4326' AS properties"
        )
    else:
        select_cols = "gid, NULL::json AS geometry, to_jsonb(t.*) - 'gid' AS properties"

    sql = f"SELECT {select_cols} FROM data.{table_name} t WHERE gid = :gid"
    result = await db.execute(text(sql).bindparams(gid=gid))
    row = result.first()
    if row is None:
        return None
    return dict(row._mapping)


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------


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
    _UPPER_TO_GEOJSON = {
        "POINT": "Point",
        "MULTIPOINT": "MultiPoint",
        "LINESTRING": "LineString",
        "MULTILINESTRING": "MultiLineString",
        "POLYGON": "Polygon",
        "MULTIPOLYGON": "MultiPolygon",
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
) -> dict:
    """Insert a GeoJSON feature into a PostGIS data table.

    Writes both geom and geom_4326 columns. Only inserts property columns
    that exist in column_info. Returns the full inserted feature via
    get_feature_by_id.
    """
    _validate_table_name(table_name)
    _validate_geometry_type(geometry.get("type", ""), dataset_geometry_type)

    geojson_str = json.dumps(geometry)

    geom_expr = _geometry_sql(dataset_geometry_type)
    cols = ["geom", "geom_4326"]
    vals = [geom_expr, geom_expr]
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
        f"INSERT INTO data.{table_name} ({', '.join(cols)}) "
        f"VALUES ({', '.join(vals)}) RETURNING gid"
    )
    result = await db.execute(text(sql).bindparams(**params))
    gid = result.scalar_one()

    return await get_feature_by_id(db, table_name, gid)


async def replace_feature(
    db: AsyncSession,
    table_name: str,
    gid: int,
    geometry: dict,
    properties: dict,
    column_info: list[dict],
    dataset_geometry_type: str,
) -> dict:
    """Full replacement of a feature (PUT semantics).

    Replaces geometry and sets ALL known attribute columns. Columns not
    present in properties are set to NULL.
    """
    _validate_table_name(table_name)
    _validate_geometry_type(geometry.get("type", ""), dataset_geometry_type)

    geojson_str = json.dumps(geometry)
    geom_expr = _geometry_sql(dataset_geometry_type)

    sets = [
        f"geom = {geom_expr}",
        f"geom_4326 = {geom_expr}",
    ]
    params: dict = {"geojson": geojson_str, "gid": gid}

    allowed = {c["name"] for c in column_info}
    for col_name in allowed:
        if _COLUMN_NAME_RE.match(col_name):
            param = f"prop_{col_name}"
            sets.append(f'"{col_name}" = :{param}')
            params[param] = properties.get(col_name)

    sql = f"UPDATE data.{table_name} SET {', '.join(sets)} WHERE gid = :gid"
    result = await db.execute(text(sql).bindparams(**params))
    if result.rowcount == 0:
        raise ValueError("Feature not found")

    return await get_feature_by_id(db, table_name, gid)


async def update_feature(
    db: AsyncSession,
    table_name: str,
    gid: int,
    geometry: dict | None,
    properties: dict | None,
    column_info: list[dict],
    dataset_geometry_type: str,
) -> dict:
    """Partial update of a feature (PATCH semantics).

    Only modifies fields that are provided. If geometry is given, both geom
    and geom_4326 are updated. If properties is given, only the keys present
    in the dict (and in column_info) are updated.
    """
    _validate_table_name(table_name)

    sets: list[str] = []
    params: dict = {"gid": gid}

    if geometry is not None:
        _validate_geometry_type(geometry.get("type", ""), dataset_geometry_type)
        geojson_str = json.dumps(geometry)
        geom_expr = _geometry_sql(dataset_geometry_type)
        sets.append(f"geom = {geom_expr}")
        sets.append(f"geom_4326 = {geom_expr}")
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

    sql = f"UPDATE data.{table_name} SET {', '.join(sets)} WHERE gid = :gid"
    result = await db.execute(text(sql).bindparams(**params))
    if result.rowcount == 0:
        raise ValueError("Feature not found")

    return await get_feature_by_id(db, table_name, gid)


async def delete_feature(
    db: AsyncSession,
    table_name: str,
    gid: int,
) -> None:
    """Hard-delete a feature by gid.

    Raises ValueError if the feature does not exist.
    """
    _validate_table_name(table_name)
    result = await db.execute(
        text(f"DELETE FROM data.{table_name} WHERE gid = :gid").bindparams(gid=gid)
    )
    if result.rowcount == 0:
        raise ValueError("Feature not found")


async def refresh_dataset_metadata(session: AsyncSession, dataset) -> None:
    """Refresh feature_count and extent on a Dataset after write operations.

    Calls extract_metadata to get the current count and extent from PostGIS,
    then updates the dataset record in-place and flushes.
    """
    metadata = await extract_metadata(session, dataset.table_name)
    dataset.feature_count = metadata["feature_count"]

    extent_wkt = metadata.get("extent_wkt")
    if extent_wkt and extent_wkt.startswith("POLYGON"):
        dataset.record.spatial_extent = func.ST_GeomFromText(extent_wkt, 4326)
    elif metadata["feature_count"] == 0:
        dataset.record.spatial_extent = None

    await session.flush()
