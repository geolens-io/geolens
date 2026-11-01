"""Tile query builder and executor using PostGIS ST_AsMVT."""

import re
from collections.abc import Sequence
from typing import Any, NamedTuple

import asyncpg
import structlog

from app.platform.timestamptz_text import utc_timestamptz_text

logger = structlog.stdlib.get_logger(__name__)

# The one definition of the tile table/column regexes and validator. The
# router imports `_TABLE_NAME_RE` / `_validate_tile_table_name` from here so a
# tightened SQL-injection defense applies in exactly one place.
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")

_EXCLUDED_COLUMNS = {"geom", "geom_4326", "gid"}

# Output property names the cluster tile query itself emits. A user column with
# one of these names must not be projected onto unclustered features or it
# would duplicate an output column name.
_CLUSTER_RESERVED_COLUMNS = {
    "cluster",
    "point_count",
    "point_count_abbreviated",
    "cluster_id",
    "expansion_zoom",
    "source_gid",
}

# Strict column-name validation. ogr2ogr normalizes column names to
# [a-zA-Z0-9_], but names are re-validated before SQL substitution to defend
# against a future allowlist that accepts admin-provided values directly.
_COLUMN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Per-zoom column-projection budget. Below this zoom no attribute columns are
# projected by default, bounding MVT tile size for wide-table datasets (a
# 137-column populated-places table produced 824 KB tiles). An explicit
# `tile_columns` allowlist overrides it. Callers opt specific columns back in
# at every zoom via `additional_columns` (the runtime `cols=` param; see
# `_select_tile_columns`), which are unioned in regardless of this budget but
# never past an explicit `tile_columns` allowlist.
_DEFAULT_NO_ATTR_BELOW_ZOOM = 10

# Hard cap on features per tile to bound query cost: a 332K-row polygon dataset
# took 5.5 s+ per z=2 tile, and a 50K limit bounds tail latency even when
# ST_AsMVTGeom would otherwise walk the table.
_TILE_FEATURE_LIMIT = 50000

# Server-side clusters: caps the candidate features considered inside one tile,
# keeping cluster tiles bounded for dense low-zoom datasets while still
# allowing many more points than client-side GeoJSON.
_CLUSTER_INPUT_LIMIT = 100000

# The order rows meet a feature cap in. A hash of gid spreads the kept rows
# across the tile when the table was loaded sorted by place, date or category,
# where gid order would keep only the first ones. It is deterministic, so
# rebuilds keep the content-hash ETag and every worker caches the same tile;
# gid breaks hash collisions. No index serves this order, so a crowded tile
# reads every row it covers instead of stopping at the cap.
_SAMPLE_ORDER = "hashint8(t.gid::bigint), t.gid"

# MVT tile extent (ST_AsMVTGeom resolution). One MVT coordinate unit spans
# 360/(extent*2^z) degrees of longitude at zoom z.
_MVT_EXTENT = 4096

# cluster_radius arrives in CSS/screen pixels (MapLibre clusterRadius
# semantics). Tiles display at 512 CSS px, so one pixel covers
# _MVT_EXTENT/512 = 8 extent units; without this factor the grid would be ~8x
# finer than requested.
_TILE_DISPLAY_SIZE_PX = 512
_CLUSTER_PX_TO_EXTENT_UNITS = _MVT_EXTENT / _TILE_DISPLAY_SIZE_PX

# Below this zoom the geometry is simplified; at/above it the original geometry
# is served untouched. Distinct from _DEFAULT_NO_ATTR_BELOW_ZOOM, which shares
# the value 10 but governs attribute projection.
_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM = 10

# Sub-pixel factor for the degrees-per-MVT-unit basis. 1.0 is one MVT unit,
# already ~1/16 of a rendered 256px tile pixel, so vertices dropped at this
# tolerance aren't visually distinguishable. One continuous basis for all z<10
# halves smoothly each zoom.
_SIMPLIFY_SUBPIXEL_FACTOR = 1.0


def _validate_tile_table_name(table_name: str) -> None:
    """Validate table name to prevent SQL injection."""
    if not _TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")


def _simplify_tolerance_degrees(z: int) -> float | None:
    """Return the ST_SimplifyPreserveTopology tolerance in EPSG:4326 degrees for zoom ``z``.

    Returns ``None`` at/above ``_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM`` (full detail).
    Below it the tolerance is ``factor * 360/(extent*2^z)``, halving
    continuously each zoom. Mirrors the SQL expression in ``_build_tile_query``
    exactly, so the monotonicity test can assert the schedule without
    executing SQL.
    """
    if z >= _NO_SIMPLIFY_AT_OR_ABOVE_ZOOM:
        return None
    return _SIMPLIFY_SUBPIXEL_FACTOR * 360.0 / (_MVT_EXTENT * (2**z))


def _effective_attr_names(
    columns: list[dict],
    z: int,
    *,
    tile_columns: list[str] | None,
    additional_columns: list[str] | None,
    mode: str,
) -> set[str]:
    """The attribute names this request would actually emit into the MVT.

    ``_select_tile_columns`` resolves the zoom budget and the allowlist, and
    then each query builder drops the names its own output cannot carry:
    ``_build_attr_columns`` drops ``_EXCLUDED_COLUMNS``, and the cluster
    builder drops those plus ``_CLUSTER_RESERVED_COLUMNS``, whose names the
    cluster query emits itself. Mirroring both here makes this the projection
    rather than the request.
    """
    excluded = _EXCLUDED_COLUMNS
    if mode == "cluster":
        excluded = excluded | _CLUSTER_RESERVED_COLUMNS
    selected = _select_tile_columns(
        columns,
        z,
        tile_columns=tile_columns,
        additional_columns=additional_columns,
    )
    return {
        name
        for col in selected
        if isinstance(col, dict)
        and isinstance(name := col.get("name"), str)
        and name not in excluded
        and _COLUMN_NAME_RE.match(name)
    }


def parse_cols_param(
    cols: str | None,
    columns: list[dict] | None,
    z: int,
    *,
    tile_columns: list[str] | None = None,
    mode: str = "vector",
) -> tuple[list[str] | None, str]:
    """Normalize a `cols=` query param into (additional_columns, cache_key).

    The returned list is the caller's request, validated: names that exist
    on this dataset, sorted and deduped. The returned key is not the request
    but what the request adds to the projection the tile would have had
    without it, so two requests producing the same SQL produce one cache
    entry. Three cases collapse:

    * `?cols=<random>`: an unknown name is dropped, so the tile is
      byte-identical to the unfiltered one.
    * `?cols=<any valid subset>` at/above ``_DEFAULT_NO_ATTR_BELOW_ZOOM``,
      where the zoom default already projects every column (or the name is
      already on an explicit ``tile_columns`` allowlist).
    * `?cols=gid`, or a cluster-reserved name on the cluster route, which no
      query builder emits at any zoom.

    Without the collapse, each case costs a full ``ST_AsMVT`` on an anonymous,
    ``@limiter.exempt`` route and then writes the result under a fresh key,
    which with no Valkey in the default stack fills an
    ``LRUCache(maxsize=50_000)`` and evicts legitimate tiles.

    ``z``, ``tile_columns`` and ``mode`` mirror what the caller passes to
    ``get_tile``/``get_cluster_tile``, so the answer is the effective
    projection. ``z`` is required so a third tile endpoint can't quietly key
    on the raw request. The zoom is already its own cache-key segment, so the
    suffix only has to separate requests at one tile; an empty suffix stays
    byte-identical to the no-`cols=` key.
    """
    if not cols:
        return None, ""
    resolved = columns or []
    known = {
        name
        for col in resolved
        if isinstance(col, dict)
        and isinstance(name := col.get("name"), str)
        and _COLUMN_NAME_RE.match(name)
    }
    if not known:
        return None, ""
    # The raw string is bounded by the server's request-line limit and the
    # result by the dataset's column count. Names are compared, never
    # interpolated: the query builders revalidate every name they emit.
    additional = sorted({c.strip() for c in cols.split(",")} & known)
    if not additional:
        return None, ""

    projection = {"tile_columns": tile_columns, "mode": mode}
    baseline = _effective_attr_names(resolved, z, additional_columns=None, **projection)
    effective = _effective_attr_names(
        resolved, z, additional_columns=additional, **projection
    )
    # `additional_columns` only unions into the base selection, so `effective`
    # is a superset of `baseline` and the difference identifies the request for
    # this dataset at this zoom. An empty difference means the request changed
    # nothing (the no-`cols=` entry).
    return additional, ",".join(sorted(effective - baseline))


def _select_tile_columns(
    columns: list[dict],
    z: int,
    *,
    tile_columns: list[str] | None = None,
    additional_columns: list[str] | None = None,
) -> list[dict]:
    """Apply the column allowlist + per-zoom defaults.

    Resolution rules:
    * `tile_columns is None` (default) → per-zoom defaults: nothing at
      z<10, everything at z>=10.
    * `tile_columns == []` → never project attributes.
    * `tile_columns` non-empty → admin-curated allowlist; only listed
      columns flow into MVT properties at any zoom.

    `additional_columns`: runtime opt-in for columns the client needs at every
    zoom (typically data-driven styling columns). Unioned into the result
    regardless of the zoom budget and validated against `columns`; names
    failing `_COLUMN_NAME_RE` or absent from `columns` are dropped.

    When `tile_columns` is set, `additional_columns` is also intersected with
    it, so the three rules above hold for a `cols=` request too: the zoom
    budget is a default the caller may override; the allowlist is not.
    """
    allowlist: set[str] | None = None
    if tile_columns is not None:
        # Validated once: the allowlist bounds both the base selection and
        # the `cols=` opt-in.
        allowlist = {name for name in tile_columns if _COLUMN_NAME_RE.match(name)}
        if not allowlist:
            base = []
        else:
            # Preserves column order and dict shape (dtype, etc.).
            base = [c for c in columns if c.get("name") in allowlist]
    elif z < _DEFAULT_NO_ATTR_BELOW_ZOOM:
        base = []
    else:
        base = columns

    if additional_columns:
        # The `cols=` opt-in projects the requested columns at every zoom,
        # including z<_DEFAULT_NO_ATTR_BELOW_ZOOM where `base` is otherwise
        # empty, so data-driven styling survives the low-zoom attribute budget.
        valid_extra = {
            name
            for name in additional_columns
            if isinstance(name, str) and _COLUMN_NAME_RE.match(name)
        }
        if allowlist is not None:
            # `cols=` overrides the zoom budget, never the admin allowlist.
            # Unioning past `tile_columns` would make the per-dataset
            # attribute-exposure control advisory: any client appending `cols=`
            # would get every other column, including an anonymous holder of a
            # signed tile template or embed token for a non-public dataset. The
            # REST reads an embed token authorizes keep to the same allowlist.
            valid_extra &= allowlist
        if valid_extra:
            already = {c.get("name") for c in base}
            for col in columns:
                name = col.get("name")
                if name in valid_extra and name not in already:
                    base.append(col)
    return base


def _attr_select(alias: str, col: dict) -> str:
    """One attribute's projection, named after the column."""
    ref = f'{alias}."{col["name"]}"'
    if str(col.get("type") or "").lower() == "timestamp with time zone":
        ref = utc_timestamptz_text(ref)
    return f'{ref} AS "{col["name"]}"'


def _build_attr_columns(columns: list[dict]) -> str:
    """Build the attribute column list for the MVT query.

    Excludes geometry columns and gid (gid is always included separately
    as the feature ID). All column names are revalidated against
    ``_COLUMN_NAME_RE`` before substitution to defend against a
    misconfigured allowlist, then quoted so a mixed-case name reaches its
    column and keeps its case as the MVT property name.
    """
    attr_cols = [
        _attr_select("t", col)
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

    Simplification applies below z=10, and a 50K-feature cap bounds query
    cost on wide low-zoom tiles. Past the cap the tile holds a sample taken in
    ``_SAMPLE_ORDER``, and the query's second column says so. The tolerance is in
    EPSG:4326 degrees and follows one continuous schedule
    (``_simplify_tolerance_degrees``) that halves each zoom (z>=10 uses the
    original geometry untouched).

    Callers should pre-filter ``columns`` via ``_select_tile_columns`` so this
    emits the SELECT projection straight from the already-pruned list.

    ``schema`` defaults to ``"data"``. multi_tenant callers pass
    ``tenant_data_schema(tid)`` so the FROM clause is always explicitly
    schema-qualified; search_path alone is not the primary isolation control.
    """
    _validate_tile_table_name(table_name)
    attr_columns = _build_attr_columns(columns)
    # The schema name derives from the validated-UUID tenant_data_schema(), so
    # it is safe to quote.
    qualified_table = f'"{schema}"."{table_name}"'

    return f"""
WITH
_env AS (
    SELECT ST_TileEnvelope($1::integer, $2::integer, $3::integer) AS geom
),
bounds AS (
    SELECT _env.geom, ST_Transform(_env.geom, 4326) AS geom_4326 FROM _env
),
sampled AS (
    SELECT ST_AsMVTGeom(
        ST_Transform(
            -- Single continuous tolerance schedule for all
            -- z<{_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM}. tolerance = factor*360/(extent*2^z)
            -- degrees (mirrors _simplify_tolerance_degrees) so it halves smoothly
            -- each zoom instead of dropping ~360x across the old z5->z6 boundary.
            -- ST_MakeValid guards the simplify input — ingest does
            -- not guarantee validity, and one invalid geometry raising a GEOS
            -- TopologyException inside the simplify call 503s the whole tile.
            -- Valid geometries pass through ST_MakeValid unchanged; the
            -- z>={_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM} branch stays untouched because
            -- ST_AsMVTGeom's clipper tolerates invalid input.
            CASE
                WHEN $1::integer < {_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM} THEN ST_SimplifyPreserveTopology(
                    ST_MakeValid(t.geom_4326),
                    {_SIMPLIFY_SUBPIXEL_FACTOR} * 360.0 / ({_MVT_EXTENT} * power(2, $1::integer))
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
    ORDER BY {_SAMPLE_ORDER}
    LIMIT {_TILE_FEATURE_LIMIT + 1}
),
-- The row past the cap only marks the tile sampled; keeping the sample's
-- lowest gids drops it. Encoding in gid order keeps a tile under the cap
-- byte-identical whatever the sample order.
mvtgeom AS (
    SELECT * FROM sampled ORDER BY gid LIMIT {_TILE_FEATURE_LIMIT}
)
SELECT
    ST_AsMVT(mvtgeom.*, $4::text, 4096, 'geom', 'gid'),
    (SELECT count(*) FROM sampled) > {_TILE_FEATURE_LIMIT}
FROM mvtgeom
-- ST_AsMVTGeom returns NULL for features clipped away or
-- degenerate at this zoom; without this WHERE those rows are encoded as
-- geometry-less attribute-only MVT features (dead bytes). Matches the
-- cluster query's existing `WHERE geom IS NOT NULL`.
WHERE mvtgeom.geom IS NOT NULL
"""


# MVT feature id for cluster features. ST_AsMVT silently drops non-positive
# ids, so a negated row_number would leave clusters with no id (breaking
# promoteId/feature-state on cluster layers). Clusters share the layer with
# unclustered features whose ids are real `gid`s, so the per-tile row number is
# offset by 2^40 to stay disjoint from realistic serial gids while remaining
# exactly representable as a JS double (< 2^53).
_CLUSTER_FEATURE_ID_OFFSET = 1 << 40


def _build_cluster_tile_query(
    table_name: str,
    schema: str = "data",
    attr_columns: list[dict] | None = None,
    filter_sql: str | None = None,
) -> str:
    """Build a bounded server-side cluster MVT query for point datasets.

    Parameters at execution time:
    $1=z, $2=x, $3=y, $4=source layer name, $5=cluster max zoom,
    $6=cluster radius in CSS/screen pixels (MapLibre ``clusterRadius``
    semantics; converted to MVT extent units in-query via
    ``_CLUSTER_PX_TO_EXTENT_UNITS``).

    ``filter_sql`` narrows the points before they are grouped, so cluster
    counts match the features a layer filter keeps. It must come from
    ``compile_filter`` (vetted column names, values as ``$7`` and up).

    The bucket grid anchors to the world minimum in absolute EPSG:3857
    coordinates, not the tile's own minx/miny, so adjacent tiles' grids line
    up. A 0-anchored grid would put the origin of a cell straddling the
    world's west/south edge outside the world, so no tile would own it and
    points near lon -180 would vanish.

    An anchored cell can straddle a tile border, so at clustering zooms the
    candidate scan covers the tile envelope expanded by one full bucket
    (clamped to the world envelope before the 4326 transform, since past the
    world edge the projection wraps longitude and the transformed bbox
    inverts). No expansion past cluster max zoom: no cross-tile cells exist
    there, and ring candidates would only consume the input cap before
    ownership discards them, starving the tile of its own points.

    Each cell is emitted by exactly one tile, the one whose envelope contains
    the cell's ownership anchor: the cell origin (``world_min + bucket index *
    bucket size``; the point itself past cluster max zoom). The anchor is pure
    grid geometry, independent of which candidates a tile scanned, so under
    input-cap saturation the worst case is an undercounted cluster from the
    owner tile, never a cross-tile double- or zero-emit (a data-dependent
    anchor, like a centroid, could land in either tile). World-min anchoring
    keeps every anchor inside [world_min, world_max]: inclusive lower bounds
    cover the west/south world edges, and the east/north edge tiles use
    inclusive upper bounds since an anchor can land exactly on the world
    maximum; internal borders stay half-open. ``_SAMPLE_ORDER`` keeps candidate
    membership deterministic per envelope, and the query's second column says
    whether the input cap or the feature cap left anything out.

    Ownership filters before the feature cap (in the ``cells`` CTE), so
    neighbor-owned cells can never consume the output budget and displace
    owned cells. A cell owned via its anchor can have its centroid up to one
    bucket inside the neighbor tile, where a client whose viewport covers the
    centroid but not the owner tile would never see it (no MVT buffer helps a
    tile the client never requests), so the emitted geometry is clamped into
    the owning tile, one MVT extent unit inside each edge. Maximum positional
    error: one bucket, i.e. the cluster radius in CSS px (48 by default); zero
    for geometry already inside the tile.

    ``expansion_zoom`` is derived per cluster. The bucket grid halves per
    zoom, so the split zoom is the smallest zoom at which the cell's extreme
    members fall in different cells of the same world-min-anchored grid.
    Clamped to ``cluster_max_zoom + 1`` and to MapLibre's ceiling of 22. Under
    input-cap saturation the value can land later than the true split zoom,
    never earlier.

    Cluster output follows the MapLibre client-side cluster property shape:
    clustered features carry ``point_count`` and ``point_count_abbreviated``;
    unclustered features omit those and carry ``source_gid``.

    ``attr_columns`` (pre-filtered via ``_select_tile_columns``, same rules as
    the plain vector path) are projected onto unclustered features via a join
    back to the source row. Cluster features keep NULLs for these columns,
    which ST_AsMVT omits per feature, so cluster properties stay exactly
    MapLibre-shaped.

    ``schema`` defaults to ``"data"``; multi_tenant callers pass
    ``tenant_data_schema(tid)`` so the FROM clause is always explicitly
    schema-qualified.
    """
    _validate_tile_table_name(table_name)
    # The schema name derives from the validated-UUID tenant_data_schema(), so
    # it is safe to quote.
    qualified_table = f'"{schema}"."{table_name}"'

    # Mirrors _build_attr_columns' exclusion, revalidation and quoting rules,
    # projecting from the joined source row for unclustered features only.
    unclustered_attr_select = "".join(
        f",\n        {_attr_select('src', col)}"
        for col in (attr_columns or [])
        if col.get("name")
        and col["name"] not in _EXCLUDED_COLUMNS
        and col["name"] not in _CLUSTER_RESERVED_COLUMNS
        and _COLUMN_NAME_RE.match(col["name"])
    )
    unclustered_attr_join = (
        f"""
    LEFT JOIN {qualified_table} src
        ON src.gid = grouped.source_gid
        AND (grouped.raw_point_count = 1 OR $1::integer > $5::integer)"""
        if unclustered_attr_select
        else ""
    )

    filter_clause = f"\n      AND ({filter_sql})" if filter_sql else ""

    return f"""
WITH
_env AS (
    SELECT ST_TileEnvelope($1::integer, $2::integer, $3::integer) AS geom
),
bounds AS (
    SELECT
        _env.geom,
        GREATEST(ST_XMax(_env.geom) - ST_XMin(_env.geom), 1.0) AS width,
        GREATEST(ST_YMax(_env.geom) - ST_YMin(_env.geom), 1.0) AS height
    FROM _env
),
-- Bucket sizes in 3857 meters. $6 (CSS px) converts to extent
-- units before scaling by tile width. The grid anchors to the WORLD MINIMUM:
-- every tile at a zoom shares one grid, and any
-- in-world point yields an in-world cell origin. A grid anchored at 0 put
-- the origin of a cell straddling the world's west/south edge OUTSIDE the
-- world, so no tile owned it and points near lon -180 vanished.
grid AS (
    SELECT
        GREATEST(bounds.width * $6::float8 * {_CLUSTER_PX_TO_EXTENT_UNITS} / {_MVT_EXTENT}.0, 1.0) AS bucket_w,
        GREATEST(bounds.height * $6::float8 * {_CLUSTER_PX_TO_EXTENT_UNITS} / {_MVT_EXTENT}.0, 1.0) AS bucket_h,
        ST_XMin(ST_TileEnvelope(0, 0, 0)) AS world_min_x,
        ST_YMin(ST_TileEnvelope(0, 0, 0)) AS world_min_y
    FROM bounds
),
-- Scan envelope = tile + one full bucket, so
-- a cell straddling the tile border is seen with its COMPLETE membership.
-- Expansion applies at clustering zooms ONLY: past cluster
-- max zoom no cross-tile cells exist, and ring candidates would
-- just consume the input cap before ownership discards them, starving the
-- tile of its own points. Clamped to the world envelope BEFORE the 4326
-- transform: past the world edge proj wraps longitude and the transformed
-- bbox inverts, dropping candidates. No data exists outside the world
-- envelope, so the clamp loses nothing.
scan AS (
    SELECT ST_Transform(
        ST_Intersection(
            ST_Expand(
                bounds.geom,
                CASE WHEN $1::integer <= $5::integer
                    THEN GREATEST(grid.bucket_w, grid.bucket_h)
                    ELSE 0.0
                END
            ),
            ST_TileEnvelope(0, 0, 0)
        ),
        4326
    ) AS geom_4326
    FROM bounds, grid
),
sampled AS (
    SELECT
        t.gid,
        ST_Transform(ST_PointOnSurface(t.geom_4326), 3857) AS geom_3857
    FROM {qualified_table} t, scan
    WHERE t.geom_4326 && scan.geom_4326
      AND NOT ST_IsEmpty(t.geom_4326){filter_clause}
    -- Deterministic under the input cap, so neighboring tiles
    -- that both see a straddling cell agree on membership and centroid.
    ORDER BY {_SAMPLE_ORDER}
    LIMIT {_CLUSTER_INPUT_LIMIT + 1}
),
-- The candidate past the cap only marks the tile sampled.
candidates AS (
    SELECT * FROM sampled ORDER BY gid LIMIT {_CLUSTER_INPUT_LIMIT}
),
bucketed AS (
    SELECT
        candidates.gid,
        candidates.geom_3857,
        CASE
            WHEN $1::integer <= $5::integer THEN floor(
                (ST_X(candidates.geom_3857) - grid.world_min_x) / grid.bucket_w
            )::integer
            ELSE candidates.gid
        END AS bucket_x,
        CASE
            WHEN $1::integer <= $5::integer THEN floor(
                (ST_Y(candidates.geom_3857) - grid.world_min_y) / grid.bucket_h
            )::integer
            ELSE candidates.gid
        END AS bucket_y
    FROM candidates, grid
),
-- The ownership anchor is the cell
-- ORIGIN (world_min + bucket index * bucket size) — pure grid geometry,
-- independent of which points were scanned. Under input-cap saturation
-- neighboring tiles can see different subsets of a shared cell; a
-- data-dependent anchor (the cell centroid) could then land in either
-- tile (double- or zero-emit). With the origin anchor the worst case
-- degrades to an undercounted cluster in the owner tile, the same class
-- any capped per-tile grid has. Past cluster max zoom the buckets are
-- per-point, so the anchor is the point itself. Every member of a cell
-- shares the cell's anchor, so the per-row anchor equals the per-cell one.
anchored AS (
    SELECT
        bucketed.*,
        CASE WHEN $1::integer <= $5::integer
            THEN grid.world_min_x + bucketed.bucket_x * grid.bucket_w
            ELSE ST_X(bucketed.geom_3857)
        END AS anchor_x,
        CASE WHEN $1::integer <= $5::integer
            THEN grid.world_min_y + bucketed.bucket_y * grid.bucket_h
            ELSE ST_Y(bucketed.geom_3857)
        END AS anchor_y
    FROM bucketed, grid
),
cells AS (
    SELECT
        bucket_x,
        bucket_y,
        count(*)::integer AS raw_point_count,
        min(gid)::bigint AS source_gid,
        -- Member spread, in exact double precision (ST_Extent would
        -- return a float4-rounded box). Feeds the expansion_zoom derivation.
        min(ST_X(geom_3857)) AS min_x,
        max(ST_X(geom_3857)) AS max_x,
        min(ST_Y(geom_3857)) AS min_y,
        max(ST_Y(geom_3857)) AS max_y,
        ST_Centroid(ST_Collect(geom_3857)) AS geom_3857
    FROM anchored, bounds
    -- Ownership applies BEFORE the
    -- feature cap. A cell is emitted by exactly ONE tile, the one whose
    -- envelope contains the cell's ownership anchor — filtering here means
    -- neighbor-owned cells can never consume the output budget and displace
    -- owned cells. Half-open bounds on internal borders; inclusive upper
    -- bounds on the world's east (x = 2^z - 1) and north (y = 0) edge
    -- tiles, which have no neighbor to own an anchor sitting exactly on
    -- the world boundary. Ring-only rows drop here too.
    WHERE anchored.anchor_x >= ST_XMin(bounds.geom)
      AND (
        anchored.anchor_x < ST_XMax(bounds.geom)
        OR ($2::integer = (1 << $1::integer) - 1
            AND anchored.anchor_x <= ST_XMax(bounds.geom))
      )
      AND anchored.anchor_y >= ST_YMin(bounds.geom)
      AND (
        anchored.anchor_y < ST_YMax(bounds.geom)
        OR ($3::integer = 0 AND anchored.anchor_y <= ST_YMax(bounds.geom))
      )
    GROUP BY bucket_x, bucket_y
    -- Same sample rule as the candidates, on each cell's source gid. Past
    -- cluster max zoom every point is its own cell, so this cap samples too.
    ORDER BY hashint8(min(gid)::bigint), min(gid)
    LIMIT {_TILE_FEATURE_LIMIT + 1}
),
-- The cell past the cap only marks the tile sampled.
grouped AS (
    SELECT * FROM cells ORDER BY bucket_x, bucket_y LIMIT {_TILE_FEATURE_LIMIT}
),
features AS (
    SELECT
        CASE
            WHEN grouped.raw_point_count > 1 AND $1::integer <= $5::integer
                THEN {_CLUSTER_FEATURE_ID_OFFSET}::bigint + row_number() OVER (ORDER BY grouped.bucket_x, grouped.bucket_y)::bigint
            ELSE grouped.source_gid
        END AS gid,
        CASE
            WHEN grouped.raw_point_count > 1 AND $1::integer <= $5::integer
                THEN true
            ELSE NULL
        END AS cluster,
        CASE
            WHEN grouped.raw_point_count > 1 AND $1::integer <= $5::integer
                THEN grouped.raw_point_count
            ELSE NULL
        END AS point_count,
        CASE
            WHEN grouped.raw_point_count > 1 AND $1::integer <= $5::integer THEN
                CASE
                    WHEN grouped.raw_point_count >= 1000000 THEN floor(grouped.raw_point_count / 1000000)::text || 'M'
                    WHEN grouped.raw_point_count >= 1000 THEN floor(grouped.raw_point_count / 1000)::text || 'k'
                    ELSE grouped.raw_point_count::text
                END
            ELSE NULL
        END AS point_count_abbreviated,
        CASE
            WHEN grouped.raw_point_count > 1 AND $1::integer <= $5::integer
                THEN md5($1::text || ':' || $2::text || ':' || $3::text || ':' || grouped.bucket_x::text || ':' || grouped.bucket_y::text)
            ELSE NULL
        END AS cluster_id,
        -- The zoom at which THIS cell actually splits, not a
        -- constant. Bucket size halves per zoom, so the cell at zoom zz uses
        -- bucket / 2^(zz - z) on the same world-min-anchored grid as the
        -- `bucketed` CTE: the split zoom is the smallest zz where the cell's
        -- extreme members no longer share one cell in x or in y. Nothing
        -- clusters past cluster max zoom, so a cell that still holds together
        -- there expands to raw points at $5 + 1; 22 is the MapLibre ceiling.
        CASE
            WHEN grouped.raw_point_count > 1 AND $1::integer <= $5::integer
                THEN LEAST(COALESCE((
                    SELECT min(zz)
                    FROM generate_series($1::integer + 1, $5::integer) AS zz,
                        LATERAL (SELECT
                            GREATEST(grid.bucket_w / power(2::float8, zz - $1::integer), 1.0) AS bw,
                            GREATEST(grid.bucket_h / power(2::float8, zz - $1::integer), 1.0) AS bh
                        ) split
                    WHERE floor((grouped.min_x - grid.world_min_x) / split.bw)
                            <> floor((grouped.max_x - grid.world_min_x) / split.bw)
                       OR floor((grouped.min_y - grid.world_min_y) / split.bh)
                            <> floor((grouped.max_y - grid.world_min_y) / split.bh)
                ), $5::integer + 1), 22)
            ELSE NULL
        END AS expansion_zoom,
        grouped.source_gid{unclustered_attr_select},
        ST_AsMVTGeom(
            -- Clamp the emitted point
            -- into the owning tile, one MVT extent unit inside each edge.
            -- Anchor ownership lets a cell's centroid fall up to one bucket
            -- inside the NEIGHBOR tile; a viewport that covers the centroid
            -- but not the owner tile never requests the owner tile, so
            -- geometry left outside the tile would be invisible there (no
            -- MVT buffer can fix an unrequested tile). Max positional
            -- error: one bucket = the cluster radius in CSS px. This
            -- replaces a radius-scaled buffer — the emitted
            -- geometry is always in-tile.
            ST_SetSRID(ST_MakePoint(
                LEAST(GREATEST(ST_X(grouped.geom_3857), ST_XMin(bounds.geom) + bounds.width / {_MVT_EXTENT}.0), ST_XMax(bounds.geom) - bounds.width / {_MVT_EXTENT}.0),
                LEAST(GREATEST(ST_Y(grouped.geom_3857), ST_YMin(bounds.geom) + bounds.height / {_MVT_EXTENT}.0), ST_YMax(bounds.geom) - bounds.height / {_MVT_EXTENT}.0)
            ), 3857),
            bounds.geom::box2d,
            4096,
            256,
            true
        ) AS geom
    FROM grouped{unclustered_attr_join}, bounds, grid
)
SELECT
    ST_AsMVT(features.*, $4::text, 4096, 'geom', 'gid'),
    (SELECT count(*) FROM sampled) > {_CLUSTER_INPUT_LIMIT}
        OR (SELECT count(*) FROM cells) > {_TILE_FEATURE_LIMIT}
FROM features
WHERE geom IS NOT NULL
"""


class RenderedTile(NamedTuple):
    """An MVT tile and whether a feature cap left features out of it."""

    mvt: bytes
    sampled: bool


async def _fetch_rendered_tile(
    executor: asyncpg.Pool | asyncpg.Connection, query: str, *args: Any
) -> RenderedTile | None:
    row = await executor.fetchrow(query, *args)
    if row is None or not row[0]:
        return None
    return RenderedTile(bytes(row[0]), bool(row[1]))


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
) -> RenderedTile | None:
    """Execute a tile query and return the rendered tile, or None if empty.

    Args:
        pool: asyncpg connection pool (used only when ``conn`` is None).
        table_name: PostGIS table name (without schema prefix).
        z: Zoom level
        x: Tile column
        y: Tile row
        columns: Column info list from dataset (dicts with 'name' key).
        tile_columns: Allowlist override (None / [] / list).
        additional_columns: Runtime opt-in columns the caller needs at all
            zooms (e.g. data-driven styling columns). Unioned with the
            base selection; validated against ``columns``.
        conn: Optional already-acquired asyncpg connection to reuse. Pass one
            that already had ``set_tenant_role_for_tile_request`` called inside
            an open transaction so the per-tenant role/search_path survive.
            None uses a transient connection from the pool.
        schema: Data schema name; defaults to ``"data"`` (single_tenant). In
            multi_tenant, pass ``tenant_data_schema(tid)`` so the FROM
            clause is explicitly schema-qualified.

    Returns:
        The MVT bytes and whether the feature cap sampled them, or None if
        the tile contains no features.
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
    # it. In multi_tenant the tile-config contract exposes the resolved tenant
    # schema as ``mvt_source_layer_prefix``, while ``data.{table}`` still signs
    # URLs. The physical schema qualification is required for tenant isolation.
    layer_name = f"{schema}.{table_name}"

    return await _fetch_rendered_tile(
        conn if conn is not None else pool, query, z, x, y, layer_name
    )


async def get_cluster_tile(
    pool: asyncpg.Pool,
    table_name: str,
    z: int,
    x: int,
    y: int,
    columns: list[dict] | None = None,
    *,
    tile_columns: list[str] | None = None,
    additional_columns: list[str] | None = None,
    cluster_radius: int = 48,
    cluster_max_zoom: int = 14,
    conn: asyncpg.Connection | None = None,
    schema: str = "data",
    filter_sql: str | None = None,
    filter_params: Sequence[Any] = (),
) -> RenderedTile | None:
    """Execute a server-side point-cluster MVT query.

    Emits MapLibre-compatible cluster properties while keeping the source
    as an authenticated vector tile, avoiding a full-table GeoJSON load in
    the browser.

    Args:
        pool: asyncpg connection pool (used only when ``conn`` is None).
        table_name: PostGIS table name (without schema prefix).
        z, x, y: Tile coordinates.
        columns: Column info list from the dataset. Resolved
            through ``_select_tile_columns`` (identical rules to ``get_tile``:
            per-zoom defaults, ``tile_columns`` allowlist, ``cols=`` opt-in)
            and projected onto UNCLUSTERED features so data-driven styling
            and popups work past cluster max zoom.
        tile_columns: Allowlist override (None / [] / list).
        additional_columns: Runtime opt-in columns (the ``cols=`` param).
        cluster_radius: Cluster radius in CSS/screen pixels (MapLibre
            ``clusterRadius`` semantics; converted to MVT extent units
            inside the query).
        cluster_max_zoom: Maximum zoom level at which clustering is active.
        conn: Optional already-acquired asyncpg connection (see ``get_tile``
            docstring for details).
        schema: Data schema name; defaults to ``"data"`` (single_tenant).
        filter_sql: Compiled layer filter, see ``_build_cluster_tile_query``. A query the database refuses for the filter's types raises HTTP 400.
        filter_params: Values for the filter's ``$7`` and up.
    """
    _validate_tile_table_name(table_name)

    attr_columns = _select_tile_columns(
        columns or [],
        z,
        tile_columns=tile_columns,
        additional_columns=additional_columns,
    )
    query = _build_cluster_tile_query(
        table_name, schema=schema, attr_columns=attr_columns, filter_sql=filter_sql
    )
    layer_name = f"{schema}.{table_name}"

    try:
        return await _fetch_rendered_tile(
            conn if conn is not None else pool,
            query,
            z,
            x,
            y,
            layer_name,
            cluster_max_zoom,
            cluster_radius,
            *filter_params,
        )
    except asyncpg.PostgresError as exc:
        if filter_sql:
            from app.processing.tiles.cluster_filter import refuse_type_fault

            refuse_type_fault(exc)
        raise
