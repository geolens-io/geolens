"""Tile query builder and executor using PostGIS ST_AsMVT."""

import re

import asyncpg
import structlog

logger = structlog.stdlib.get_logger(__name__)

# Strict table name validation to prevent SQL injection
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# Columns to exclude from MVT attribute selection
_EXCLUDED_COLUMNS = {"geom", "geom_4326", "gid"}

# Strict column-name validation. Datasets are loaded by ogr2ogr which
# normalizes column names to [a-zA-Z0-9_], but we re-validate before
# substituting into SQL to defend against any future allowlist that
# accepts admin-provided values directly.
_COLUMN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Phase 269 H-23: per-zoom column-projection budget.
# Below this zoom level we project NO attribute columns by default to
# bound MVT tile size for wide-table datasets (e.g. 137-column
# `populated_places_10m` produced 824 KB tiles before this change).
# Datasets with an explicit `tile_columns` allowlist override this.
_DEFAULT_NO_ATTR_BELOW_ZOOM = 10


def _validate_tile_table_name(table_name: str) -> None:
    """Validate table name to prevent SQL injection."""
    if not _TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")


def _select_tile_columns(
    columns: list[dict],
    z: int,
    *,
    tile_columns: list[str] | None = None,
) -> list[dict]:
    """Apply Phase 269 H-23 column allowlist + per-zoom defaults.

    Resolution rules:
    * `tile_columns is None` (default) → fall back to per-zoom defaults:
      project nothing at z<10, project everything at z>=10.
    * `tile_columns == []`             → never project attributes.
    * `tile_columns` non-empty         → admin-curated allowlist; only the
      listed columns flow into MVT properties at any zoom.
    """
    if tile_columns is not None:
        if not tile_columns:
            return []
        # Filter `columns` by the allowlist while preserving column order
        # and dict shape (dtype, etc.) — also re-validate names.
        allowlist = {name for name in tile_columns if _COLUMN_NAME_RE.match(name)}
        return [c for c in columns if c.get("name") in allowlist]

    # Default behavior: per-zoom budget.
    if z < _DEFAULT_NO_ATTR_BELOW_ZOOM:
        return []
    return columns


def _build_attr_columns(columns: list[dict]) -> str:
    """Build the attribute column list for the MVT query.

    Excludes geometry columns and gid (gid is always included separately
    as the feature ID). All column names are revalidated against
    ``_COLUMN_NAME_RE`` before substitution to defend against a
    misconfigured allowlist.
    """
    attr_cols = [
        f"t.{col['name']}"
        for col in columns
        if col.get("name")
        and col["name"] not in _EXCLUDED_COLUMNS
        and _COLUMN_NAME_RE.match(col["name"])
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

    Phase 269 H-23: callers should pre-filter the ``columns`` list via
    ``_select_tile_columns`` so this function emits the SELECT projection
    straight from the already-pruned column list.
    """
    _validate_tile_table_name(table_name)
    attr_columns = _build_attr_columns(columns)

    return f"""
WITH
_env AS (
    SELECT ST_TileEnvelope($1::integer, $2::integer, $3::integer) AS geom
),
bounds AS (
    SELECT _env.geom, ST_Transform(_env.geom, 4326) AS geom_4326 FROM _env
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
    *,
    tile_columns: list[str] | None = None,
) -> bytes | None:
    """Execute a tile query and return MVT bytes, or None if empty.

    Args:
        pool: asyncpg connection pool
        table_name: PostGIS table name (without schema prefix)
        z: Zoom level
        x: Tile column
        y: Tile row
        columns: Column info list from dataset (dicts with 'name' key)
        tile_columns: Phase 269 H-23 allowlist override (None / [] / list).

    Returns:
        MVT binary data, or None if the tile contains no features.
    """
    _validate_tile_table_name(table_name)

    selected_columns = _select_tile_columns(columns, z, tile_columns=tile_columns)
    query = _build_tile_query(table_name, selected_columns)
    layer_name = f"data.{table_name}"

    result = await pool.fetchval(query, z, x, y, layer_name)

    if result is None or len(result) == 0:
        return None

    return result
