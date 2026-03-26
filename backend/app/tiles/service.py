"""Tile query builder and executor using PostGIS ST_AsMVT."""

import re

import asyncpg
import structlog

logger = structlog.stdlib.get_logger(__name__)

# Strict table name validation to prevent SQL injection
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# Columns to exclude from MVT attribute selection
_EXCLUDED_COLUMNS = {"geom", "geom_4326", "gid"}


def _validate_tile_table_name(table_name: str) -> None:
    """Validate table name to prevent SQL injection."""
    if not _TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")


def _build_attr_columns(columns: list[dict]) -> str:
    """Build the attribute column list for the MVT query.

    Excludes geometry columns and gid (gid is always included separately
    as the feature ID).
    """
    attr_cols = [
        f"t.{col['name']}" for col in columns if col["name"] not in _EXCLUDED_COLUMNS
    ]
    if attr_cols:
        return ", " + ", ".join(attr_cols)
    return ""


def _build_tile_query(table_name: str, columns: list[dict]) -> str:
    """Build the ST_AsMVT tile query for the given table and columns.

    Applies zoom-dependent simplification to keep vertex counts within
    WebGL's 65535-per-segment limit. The tolerance is in EPSG:4326 degrees
    and shrinks exponentially with zoom so low-zoom tiles stay lightweight
    while high-zoom tiles preserve full detail.
    """
    _validate_tile_table_name(table_name)
    attr_columns = _build_attr_columns(columns)

    return f"""
WITH
bounds AS (
    SELECT
        ST_TileEnvelope($1::integer, $2::integer, $3::integer) AS geom,
        ST_Transform(ST_TileEnvelope($1::integer, $2::integer, $3::integer), 4326) AS geom_4326
),
mvtgeom AS (
    SELECT ST_AsMVTGeom(
        ST_Transform(
            CASE WHEN $1::integer < 6
                THEN ST_SimplifyPreserveTopology(
                    t.geom_4326,
                    360.0 / (4096 * power(2, $1::integer))
                )
                ELSE t.geom_4326
            END,
            3857
        ),
        bounds.geom::box2d,
        4096,
        256,
        true
    ) AS geom,
    t.gid{attr_columns}
    FROM data.{table_name} t, bounds
    WHERE t.geom_4326 && bounds.geom_4326
      AND ST_Intersects(t.geom_4326, bounds.geom_4326)
)
SELECT ST_AsMVT(mvtgeom.*, $4::text, 4096, 'geom', 'gid')
FROM mvtgeom
"""


async def get_tile(
    pool: asyncpg.Pool,
    table_name: str,
    z: int,
    x: int,
    y: int,
    columns: list[dict],
) -> bytes | None:
    """Execute a tile query and return MVT bytes, or None if empty.

    Args:
        pool: asyncpg connection pool
        table_name: PostGIS table name (without schema prefix)
        z: Zoom level
        x: Tile column
        y: Tile row
        columns: Column info list from dataset (dicts with 'name' key)

    Returns:
        MVT binary data, or None if the tile contains no features.
    """
    _validate_tile_table_name(table_name)

    query = _build_tile_query(table_name, columns)
    layer_name = f"data.{table_name}"

    result = await pool.fetchval(query, z, x, y, layer_name)

    if result is None or len(result) == 0:
        return None

    return result
