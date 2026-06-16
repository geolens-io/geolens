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

# Phase 269 C-02: hard cap on features per tile to bound query cost.
# Single-feature datasets see no impact; 332K-row polygon datasets had
# 5,583 ms+ z=2 tiles before this. With 50K limit, tail latency is bounded
# even when ST_AsMVTGeom would otherwise walk the full table.
_TILE_FEATURE_LIMIT = 50000

# v1006 server-side clusters: cap the number of candidate features considered
# inside one tile. This keeps cluster tiles bounded even for dense low-zoom
# datasets while still allowing many more points than client-side GeoJSON.
_CLUSTER_INPUT_LIMIT = 100000


def _validate_tile_table_name(table_name: str) -> None:
    """Validate table name to prevent SQL injection."""
    if not _TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")


def _select_tile_columns(
    columns: list[dict],
    z: int,
    *,
    tile_columns: list[str] | None = None,
    additional_columns: list[str] | None = None,
) -> list[dict]:
    """Apply Phase 269 H-23 column allowlist + per-zoom defaults.

    Resolution rules:
    * `tile_columns is None` (default) → fall back to per-zoom defaults:
      project nothing at z<10, project everything at z>=10.
    * `tile_columns == []`             → never project attributes.
    * `tile_columns` non-empty         → admin-curated allowlist; only the
      listed columns flow into MVT properties at any zoom.

    `additional_columns` (2026-05-18): runtime opt-in for columns the
    requesting client knows it needs — typically data-driven styling
    columns (e.g. `style_config.column`) that must be present at every
    zoom to drive categorical / graduated paint expressions. These are
    UNIONED into the result regardless of the zoom budget or allowlist,
    but still validated against `columns` so callers cannot project
    arbitrary attributes that don't exist on the table. Names that fail
    `_COLUMN_NAME_RE` or aren't in `columns` are silently dropped.
    """
    if tile_columns is not None:
        if not tile_columns:
            base = []
        else:
            # Filter `columns` by the allowlist while preserving column
            # order and dict shape (dtype, etc.) — also re-validate names.
            allowlist = {name for name in tile_columns if _COLUMN_NAME_RE.match(name)}
            base = [c for c in columns if c.get("name") in allowlist]
    elif z < _DEFAULT_NO_ATTR_BELOW_ZOOM:
        base = []
    else:
        base = columns

    if additional_columns:
        valid_extra = {
            name
            for name in additional_columns
            if isinstance(name, str) and _COLUMN_NAME_RE.match(name)
        }
        if valid_extra:
            already = {c.get("name") for c in base}
            for col in columns:
                name = col.get("name")
                if name in valid_extra and name not in already:
                    base.append(col)
    return base


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


def _build_tile_query(
    table_name: str, columns: list[dict], schema: str = "data"
) -> str:
    """Build the ST_AsMVT tile query for the given table and columns.

    Phase 269 C-02: simplification now applies at all zooms below z=10
    (was z<6) with a piecewise tolerance schedule, and the inner CTE has
    a 50K-feature LIMIT to bound query cost on wide low-zoom tiles. The
    tolerance is in EPSG:4326 degrees and shrinks exponentially with zoom
    so low-zoom tiles stay lightweight while high-zoom tiles preserve
    full detail (z>=10 still uses the original geometry untouched).

    Phase 269 H-23: callers should pre-filter the ``columns`` list via
    ``_select_tile_columns`` so this function emits the SELECT projection
    straight from the already-pruned column list.

    DP-02 (Phase 1209-03): ``schema`` defaults to ``"data"`` (single_tenant
    unchanged).  In multi_tenant callers pass ``tenant_data_schema(tid)`` so
    the FROM clause is ALWAYS explicitly schema-qualified — we do NOT rely on
    search_path alone as the primary isolation control (T-1209-11).
    """
    _validate_tile_table_name(table_name)
    attr_columns = _build_attr_columns(columns)
    # Schema name derives from validated-UUID tenant_data_schema() — safe to quote.
    qualified_table = f'"{schema}"."{table_name}"'

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
            CASE
                WHEN $1::integer < 6 THEN ST_SimplifyPreserveTopology(
                    t.geom_4326,
                    360.0 / (4096 * power(2, $1::integer))
                )
                WHEN $1::integer < 10 THEN ST_SimplifyPreserveTopology(
                    t.geom_4326,
                    1.0 / (4096 * power(2, $1::integer))
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
    FROM {qualified_table} t, bounds
    WHERE t.geom_4326 && bounds.geom_4326
    LIMIT {_TILE_FEATURE_LIMIT}
)
SELECT ST_AsMVT(mvtgeom.*, $4::text, 4096, 'geom', 'gid')
FROM mvtgeom
"""


def _build_cluster_tile_query(table_name: str, schema: str = "data") -> str:
    """Build a bounded server-side cluster MVT query for point datasets.

    Parameters at execution time:
    $1=z, $2=x, $3=y, $4=source layer name, $5=cluster max zoom,
    $6=cluster radius in tile pixels.

    Cluster output follows the MapLibre client-side cluster property shape:
    clustered features carry ``point_count`` and ``point_count_abbreviated``;
    unclustered features omit those properties and carry ``source_gid``.

    DP-02 (Phase 1209-03): ``schema`` defaults to ``"data"`` (single_tenant
    unchanged).  In multi_tenant callers pass ``tenant_data_schema(tid)`` so
    the FROM clause is ALWAYS explicitly schema-qualified (T-1209-11).
    """
    _validate_tile_table_name(table_name)
    # Schema name derives from validated-UUID tenant_data_schema() — safe to quote.
    qualified_table = f'"{schema}"."{table_name}"'

    return f"""
WITH
_env AS (
    SELECT ST_TileEnvelope($1::integer, $2::integer, $3::integer) AS geom
),
bounds AS (
    SELECT
        _env.geom,
        ST_Transform(_env.geom, 4326) AS geom_4326,
        ST_XMin(_env.geom) AS minx,
        ST_YMin(_env.geom) AS miny,
        GREATEST(ST_XMax(_env.geom) - ST_XMin(_env.geom), 1.0) AS width,
        GREATEST(ST_YMax(_env.geom) - ST_YMin(_env.geom), 1.0) AS height
    FROM _env
),
candidates AS (
    SELECT
        t.gid,
        ST_Transform(ST_PointOnSurface(t.geom_4326), 3857) AS geom_3857
    FROM {qualified_table} t, bounds
    WHERE t.geom_4326 && bounds.geom_4326
      AND NOT ST_IsEmpty(t.geom_4326)
    LIMIT {_CLUSTER_INPUT_LIMIT}
),
bucketed AS (
    SELECT
        candidates.gid,
        candidates.geom_3857,
        CASE
            WHEN $1::integer <= $5::integer THEN floor(
                (ST_X(candidates.geom_3857) - bounds.minx)
                / GREATEST(bounds.width * $6::float8 / 4096.0, 1.0)
            )::integer
            ELSE candidates.gid
        END AS bucket_x,
        CASE
            WHEN $1::integer <= $5::integer THEN floor(
                (ST_Y(candidates.geom_3857) - bounds.miny)
                / GREATEST(bounds.height * $6::float8 / 4096.0, 1.0)
            )::integer
            ELSE candidates.gid
        END AS bucket_y
    FROM candidates, bounds
),
grouped AS (
    SELECT
        bucket_x,
        bucket_y,
        count(*)::integer AS raw_point_count,
        min(gid)::bigint AS source_gid,
        ST_Centroid(ST_Collect(geom_3857)) AS geom_3857
    FROM bucketed
    GROUP BY bucket_x, bucket_y
    LIMIT {_TILE_FEATURE_LIMIT}
),
features AS (
    SELECT
        CASE
            WHEN raw_point_count > 1 AND $1::integer <= $5::integer
                THEN -row_number() OVER (ORDER BY bucket_x, bucket_y)::bigint
            ELSE source_gid
        END AS gid,
        CASE
            WHEN raw_point_count > 1 AND $1::integer <= $5::integer
                THEN true
            ELSE NULL
        END AS cluster,
        CASE
            WHEN raw_point_count > 1 AND $1::integer <= $5::integer
                THEN raw_point_count
            ELSE NULL
        END AS point_count,
        CASE
            WHEN raw_point_count > 1 AND $1::integer <= $5::integer THEN
                CASE
                    WHEN raw_point_count >= 1000000 THEN floor(raw_point_count / 1000000)::text || 'M'
                    WHEN raw_point_count >= 1000 THEN floor(raw_point_count / 1000)::text || 'k'
                    ELSE raw_point_count::text
                END
            ELSE NULL
        END AS point_count_abbreviated,
        CASE
            WHEN raw_point_count > 1 AND $1::integer <= $5::integer
                THEN md5($1::text || ':' || $2::text || ':' || $3::text || ':' || bucket_x::text || ':' || bucket_y::text)
            ELSE NULL
        END AS cluster_id,
        CASE
            WHEN raw_point_count > 1 AND $1::integer <= $5::integer
                THEN LEAST($5::integer + 1, 22)
            ELSE NULL
        END AS expansion_zoom,
        source_gid,
        ST_AsMVTGeom(
            geom_3857,
            bounds.geom::box2d,
            4096,
            256,
            true
        ) AS geom
    FROM grouped, bounds
)
SELECT ST_AsMVT(features.*, $4::text, 4096, 'geom', 'gid')
FROM features
WHERE geom IS NOT NULL
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
    additional_columns: list[str] | None = None,
    conn: asyncpg.Connection | None = None,
    schema: str = "data",
) -> bytes | None:
    """Execute a tile query and return MVT bytes, or None if empty.

    Args:
        pool: asyncpg connection pool (used only when ``conn`` is None).
        table_name: PostGIS table name (without schema prefix).
        z: Zoom level
        x: Tile column
        y: Tile row
        columns: Column info list from dataset (dicts with 'name' key).
        tile_columns: Phase 269 H-23 allowlist override (None / [] / list).
        additional_columns: Runtime opt-in columns the caller needs at all
            zooms (e.g. data-driven styling columns). Unioned with the
            base selection; validated against ``columns``.
        conn: Optional already-acquired asyncpg connection to reuse.
            DP-02 (Phase 1209-03): pass a connection that has already had
            ``set_tenant_role_for_tile_request`` called inside an open
            transaction so the per-tenant role + search_path survive for
            this query (T-1209-10).  When None, ``pool.fetchval`` acquires
            a transient connection (single_tenant / legacy behaviour).
        schema: Data schema name.  Defaults to ``"data"`` (single_tenant).
            In multi_tenant callers pass ``tenant_data_schema(tid)`` so the
            FROM clause is explicitly schema-qualified (T-1209-11).

    Returns:
        MVT binary data, or None if the tile contains no features.
    """
    _validate_tile_table_name(table_name)

    selected_columns = _select_tile_columns(
        columns,
        z,
        tile_columns=tile_columns,
        additional_columns=additional_columns,
    )
    query = _build_tile_query(table_name, selected_columns, schema=schema)
    # layer_name must match the schema-qualified table so clients can identify
    # the MVT layer; mirrors the qualified table reference in the query.
    layer_name = f"{schema}.{table_name}"

    if conn is not None:
        result = await conn.fetchval(query, z, x, y, layer_name)
    else:
        result = await pool.fetchval(query, z, x, y, layer_name)

    if result is None or len(result) == 0:
        return None

    return result


async def get_cluster_tile(
    pool: asyncpg.Pool,
    table_name: str,
    z: int,
    x: int,
    y: int,
    *,
    cluster_radius: int = 48,
    cluster_max_zoom: int = 14,
    conn: asyncpg.Connection | None = None,
    schema: str = "data",
) -> bytes | None:
    """Execute a server-side point-cluster MVT query.

    The query emits MapLibre-compatible cluster properties while keeping the
    source as an authenticated vector tile, which avoids loading large datasets
    as full-table GeoJSON in the browser.

    Args:
        pool: asyncpg connection pool (used only when ``conn`` is None).
        table_name: PostGIS table name (without schema prefix).
        z, x, y: Tile coordinates.
        cluster_radius: Cluster radius in tile pixels.
        cluster_max_zoom: Maximum zoom level at which clustering is active.
        conn: Optional already-acquired asyncpg connection (see ``get_tile``
            docstring for DP-02 details; T-1209-10).
        schema: Data schema name; defaults to ``"data"`` (single_tenant).
    """
    _validate_tile_table_name(table_name)

    query = _build_cluster_tile_query(table_name, schema=schema)
    layer_name = f"{schema}.{table_name}"

    if conn is not None:
        result = await conn.fetchval(
            query,
            z,
            x,
            y,
            layer_name,
            cluster_max_zoom,
            cluster_radius,
        )
    else:
        result = await pool.fetchval(
            query,
            z,
            x,
            y,
            layer_name,
            cluster_max_zoom,
            cluster_radius,
        )

    if result is None or len(result) == 0:
        return None

    return result
