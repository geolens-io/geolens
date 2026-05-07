"""Feature query service: paginated GeoJSON features from PostGIS data tables."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

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
) -> dict:
    """Full replacement of a feature (PUT semantics).

    Replaces geometry and sets ALL known attribute columns. Columns not
    present in properties are set to NULL.
    """
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
    result = await session.execute(
        text(
            f"SELECT COUNT(*), "
            f"CASE WHEN ST_Extent(geom_4326) IS NULL THEN NULL "
            f"ELSE ST_AsText(ST_SetSRID(ST_Extent(geom_4326)::geometry, 4326)) END "
            f"FROM {get_catalog_port().quote_table(table_name)}"
        )
    )
    row = result.one()
    return int(row[0]), row[1]


async def refresh_dataset_metadata(session: AsyncSession, dataset: Dataset) -> None:
    """Refresh feature_count and extent on a Dataset after write operations.

    Uses a single COUNT(*) + ST_Extent query instead of the full
    extract_metadata pipeline (which runs 5 queries).
    """
    feature_count, extent_wkt = await _refresh_count_and_extent(
        session, dataset.table_name
    )
    dataset.feature_count = feature_count

    if extent_wkt and extent_wkt.startswith("POLYGON"):
        dataset.record.spatial_extent = func.ST_GeomFromText(extent_wkt, 4326)
    elif feature_count == 0:
        dataset.record.spatial_extent = None

    await session.flush()
