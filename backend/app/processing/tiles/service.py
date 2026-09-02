"""Tile query builder and executor using PostGIS ST_AsMVT."""

import re

import asyncpg
import structlog

logger = structlog.stdlib.get_logger(__name__)

# builder-audit #338 MVT-09: SINGLE SOURCE OF TRUTH for the tile table/column name
# regexes + validator. The router imports `_TABLE_NAME_RE` / `_validate_tile_table_name`
# from here instead of re-declaring its own copy, so a future tightening of the
# SQL-injection defense applies in exactly one place.
# Strict table name validation to prevent SQL injection
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# Columns to exclude from MVT attribute selection
_EXCLUDED_COLUMNS = {"geom", "geom_4326", "gid"}

# fix(#403): output property names the cluster tile query itself emits.
# A user column with one of these names must not be projected onto
# unclustered features or it would duplicate an output column name.
_CLUSTER_RESERVED_COLUMNS = {
    "cluster",
    "point_count",
    "point_count_abbreviated",
    "cluster_id",
    "expansion_zoom",
    "source_gid",
}

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
#
# builder-audit #338 MVT-02: dropping attributes at z<10 is an INTENTIONAL,
# documented perf tradeoff (824 KB -> bounded tiles), not a spec gap, so the
# default is deliberately left unchanged. It is NOT all-or-nothing: callers opt
# specific columns back in at every zoom via `additional_columns` (the runtime
# `cols=` query param) — see `_select_tile_columns`, which UNIONs them in
# regardless of this zoom budget. The frontend already opts in data-driven
# styling columns this way; non-styling popup/identify reads at z<10 are the
# residual tradeoff (export/runtime `cols=` emission is handled separately).
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

# MVT tile extent (ST_AsMVTGeom resolution). One MVT coordinate unit spans
# 360/(extent*2^z) degrees of longitude at zoom z.
_MVT_EXTENT = 4096

# fix(#868): cluster_radius arrives in CSS/screen pixels (MapLibre clusterRadius
# semantics, matching the client-side cluster path). Tiles display at 512 CSS px,
# so one pixel covers _MVT_EXTENT / 512 = 8 extent units. The old bucket math
# divided by the extent without this factor, treating pixels as extent units and
# producing a grid ~8x finer than requested (overlapping cluster circles plus
# unclustered singles leaking at low zoom).
_TILE_DISPLAY_SIZE_PX = 512
_CLUSTER_PX_TO_EXTENT_UNITS = _MVT_EXTENT / _TILE_DISPLAY_SIZE_PX

# builder-audit #338 MVT-07: simplification tolerance schedule. Below this zoom the
# geometry is simplified; at/above it the original geometry is served untouched.
# (Distinct from _DEFAULT_NO_ATTR_BELOW_ZOOM, which happens to share the value 10
# but governs attribute projection, not geometry simplification.)
_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM = 10

# builder-audit #338 MVT-07: sub-pixel factor applied to the degrees-per-MVT-unit
# basis. 1.0 == one MVT coordinate unit, already ~1/16 of a rendered 256px tile
# pixel, so vertices dropped at this tolerance are not visually distinguishable.
# The prior piecewise schedule used this full-unit basis (360/(extent*2^z)) only
# for z<6 and silently dropped the 360 degrees-per-tile factor for z6-9, making
# that band's tolerance ~360x too small (effectively unsimplified). Using a
# single continuous basis for all z<10 makes tolerance halve smoothly each zoom.
_SIMPLIFY_SUBPIXEL_FACTOR = 1.0


def _validate_tile_table_name(table_name: str) -> None:
    """Validate table name to prevent SQL injection."""
    if not _TABLE_NAME_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name}")


def _simplify_tolerance_degrees(z: int) -> float | None:
    """Return the ST_SimplifyPreserveTopology tolerance in EPSG:4326 degrees for zoom ``z``.

    builder-audit #338 MVT-07: returns ``None`` at/above
    ``_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM`` (full detail). Below it the tolerance is
    ``factor * 360/(extent*2^z)``, so it shrinks continuously — halving each zoom
    — with no discontinuity at the old z5->z6 boundary. This Python helper mirrors
    the SQL expression emitted by ``_build_tile_query`` exactly, so the
    monotonicity test can assert the schedule without executing SQL.
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
    cluster query emits itself. Mirroring both here is what makes this the
    projection rather than the request.
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

    The returned list is the caller's request, validated: the names that exist
    on this dataset, sorted and deduped. The returned key is not the request at
    all. It is what the request ADDS to the projection the tile would have had
    without it, so two requests that produce the same SQL produce one cache
    entry (fix(#403) asked only for the sorted-and-deduped half of that).

    fix(#1778): both halves used to be the caller's own string, which meant the
    key varied on input the projection ignores. Three ways that happened, and
    the key now collapses all three:

    * `?cols=<random>`. ``_select_tile_columns`` drops an unknown name
      silently, so the tile was byte-identical to the unfiltered one under a
      fresh key.
    * `?cols=<any valid subset>` at or above ``_DEFAULT_NO_ATTR_BELOW_ZOOM``,
      where the zoom default already projects EVERY column. Every subset of a
      wide table produced the same bytes under a different key, which is
      exponentially many keys per tile rather than one bogus name at a time.
      A name already on an explicit ``tile_columns`` allowlist is the same
      case at any zoom.
    * `?cols=gid`, or a cluster-reserved name on the cluster route, which no
      query builder emits at any zoom.

    Each of those cost a full ``ST_AsMVT`` on an anonymous, ``@limiter.exempt``
    route serving public datasets, and then WROTE the result. The default
    production stack has no Valkey, so the writes land in an
    ``LRUCache(maxsize=50_000)`` and evict legitimate tiles.

    ``z``, ``tile_columns`` and ``mode`` are what make the answer the effective
    projection; the caller passes what it will pass to ``get_tile`` or
    ``get_cluster_tile``. ``z`` is positional and required so a third tile
    endpoint cannot quietly go back to keying on the request. The zoom is
    already a cache-key segment of its own, so this suffix only has to
    separate requests at ONE tile, which is why it carries the difference
    rather than the whole projection: an empty suffix keeps meaning "whatever
    this tile projects by default" and stays byte-identical to the key a
    no-`cols=` request has always used.
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
    # The raw string is bounded by the server's request-line limit, and the
    # result by the dataset's column count, so neither side of this is caller-
    # chosen. Names are compared, never interpolated: the query builders
    # revalidate every name they emit regardless of what reaches them.
    additional = sorted({c.strip() for c in cols.split(",")} & known)
    if not additional:
        return None, ""

    projection = {"tile_columns": tile_columns, "mode": mode}
    baseline = _effective_attr_names(resolved, z, additional_columns=None, **projection)
    effective = _effective_attr_names(
        resolved, z, additional_columns=additional, **projection
    )
    # `additional_columns` only ever UNIONS into the base selection, so
    # `effective` is a superset of `baseline` and the difference identifies it
    # uniquely for this dataset at this zoom. An empty difference means the
    # request changed nothing, which is the no-`cols=` entry.
    return additional, ",".join(sorted(effective - baseline))


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
        # builder-audit #338 MVT-02: the `cols=` opt-in projects the requested columns
        # at EVERY zoom, including z<_DEFAULT_NO_ATTR_BELOW_ZOOM where `base` is
        # otherwise empty — this is what lets data-driven styling (and any column
        # a caller explicitly requests) survive the low-zoom attribute budget.
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

    Phase 269 C-02: simplification applies at all zooms below z=10 (was z<6),
    and the inner CTE has a 50K-feature LIMIT to bound query cost on wide
    low-zoom tiles. builder-audit #338 MVT-07: the tolerance is in EPSG:4326 degrees
    and follows one continuous schedule (``_simplify_tolerance_degrees``) that
    halves each zoom, so low/mid-zoom tiles stay lightweight while high-zoom
    tiles preserve full detail (z>=10 uses the original geometry untouched).

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
            -- builder-audit #338 MVT-07: single continuous tolerance schedule for all
            -- z<{_NO_SIMPLIFY_AT_OR_ABOVE_ZOOM}. tolerance = factor*360/(extent*2^z)
            -- degrees (mirrors _simplify_tolerance_degrees) so it halves smoothly
            -- each zoom instead of dropping ~360x across the old z5->z6 boundary.
            -- fix(#394) VT-05: ST_MakeValid guards the simplify input — ingest does
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
    LIMIT {_TILE_FEATURE_LIMIT}
)
SELECT ST_AsMVT(mvtgeom.*, $4::text, 4096, 'geom', 'gid')
FROM mvtgeom
-- fix(#394) VT-06: ST_AsMVTGeom returns NULL for features clipped away or
-- degenerate at this zoom; without this WHERE those rows are encoded as
-- geometry-less attribute-only MVT features (dead bytes). Matches the
-- cluster query's existing `WHERE geom IS NOT NULL`.
WHERE mvtgeom.geom IS NOT NULL
"""


# fix(#394) VT-07: MVT feature id for CLUSTER features. ST_AsMVT silently drops
# non-positive ids, so the previous `-row_number()` left clusters with no id at
# all (breaks any future promoteId/feature-state on cluster layers). Clusters
# share the layer with unclustered features whose ids are real `gid`s, so the
# per-tile row number is offset by 2^40 to stay disjoint from realistic serial
# gids while remaining exactly representable as a JS double (< 2^53).
_CLUSTER_FEATURE_ID_OFFSET = 1 << 40


def _build_cluster_tile_query(
    table_name: str,
    schema: str = "data",
    attr_columns: list[dict] | None = None,
) -> str:
    """Build a bounded server-side cluster MVT query for point datasets.

    Parameters at execution time:
    $1=z, $2=x, $3=y, $4=source layer name, $5=cluster max zoom,
    $6=cluster radius in CSS/screen pixels (MapLibre ``clusterRadius``
    semantics; converted to MVT extent units in-query via
    ``_CLUSTER_PX_TO_EXTENT_UNITS`` — fix(#868)).

    fix(#868): the bucket grid is anchored to the WORLD MINIMUM in absolute
    EPSG:3857 coordinates (``floor((ST_X(geom) - world_min) / bucket_size)``),
    not to the tile's own minx/miny. Bucket size at a fixed zoom is identical
    for every tile, so absolute anchoring makes the grids of adjacent tiles
    line up instead of drifting by each tile's origin offset (a seam artifact
    at tile borders). Anchoring at the world minimum (codex round 3) means
    every in-world point yields an in-world cell origin: a 0-anchored grid
    put the origin of a cell straddling the world's west/south edge outside
    the world, so no tile owned that cell and points near lon -180 vanished.

    fix(#868, codex P2 rounds on PR #872): an anchored cell can straddle a
    tile border, so at clustering zooms the candidate scan covers the tile
    envelope EXPANDED by one full bucket (clamped to the world envelope; see
    the scan CTE) and each cell is emitted by exactly one tile — the tile
    whose envelope contains the cell's ownership anchor, the cell ORIGIN
    (``world_min + bucket index * bucket size``; the point itself past
    cluster max zoom). The anchor is pure grid geometry, so ownership never
    depends on which candidates a tile scanned: when the input cap
    saturates and neighbors see different subsets of a shared cell, the
    worst case is an undercounted (or missing) cluster from the owner tile
    — the degradation class any capped per-tile grid has — never a
    cross-tile double- or zero-emit. World-min anchoring keeps every anchor
    inside [world_min, world_max], so the inclusive lower bounds already
    cover the west/south world edges; the east/north edge tiles use
    inclusive UPPER bounds because an anchor can still land exactly on the
    world maximum (a point at lon 180 past max zoom, or a bucket size that
    divides the world width exactly). Internal borders stay half-open.
    Past cluster max zoom the scan uses NO expansion (codex round 3): no
    cross-tile cells exist there, and ring candidates would only consume
    the input cap before ownership discards them, starving the tile of its
    own points. Singles that only enter via the expanded ring drop out
    through the ownership filter. ``ORDER BY gid`` keeps candidate
    membership deterministic per envelope.

    fix(#868, codex round 4 on PR #872): ownership filters BEFORE the
    feature cap (in the ``grouped`` CTE), so neighbor-owned cells can never
    consume the output budget and displace owned cells. And because a cell
    owned via its anchor can have its centroid up to one bucket inside the
    NEIGHBOR tile — where a client whose viewport covers the centroid but
    not the owner tile would never see it (no MVT buffer helps a tile the
    client never requests) — the emitted geometry is CLAMPED into the
    owning tile, one MVT extent unit inside each edge. Maximum positional
    error from the clamp: one bucket, i.e. the cluster radius in CSS px
    (48 by default), deterministic, and zero for geometry already inside
    the tile (all past-max-zoom points; every cell whose centroid is
    in-tile).

    fix(#874): ``expansion_zoom`` is derived per cluster instead of shipping
    ``cluster_max_zoom + 1`` for every one of them. The bucket grid halves per
    zoom, so the split zoom is the smallest zoom at which the cell's extreme
    members fall in different cells of the same world-min-anchored grid —
    exactly where this query would stop grouping them. Clamped to
    ``cluster_max_zoom + 1`` (a cell that still holds together there expands
    to raw points at the next zoom) and to MapLibre's ceiling of 22. Under
    input-cap saturation the spread comes from the visible members only, so
    the value can land later than the true split zoom — the pre-#874
    behaviour — never earlier.

    Cluster output follows the MapLibre client-side cluster property shape:
    clustered features carry ``point_count`` and ``point_count_abbreviated``;
    unclustered features omit those properties and carry ``source_gid``.

    fix(#403): ``attr_columns`` (pre-filtered via ``_select_tile_columns``,
    same rules as the plain vector path) are projected onto UNCLUSTERED
    features — single-point buckets and everything past cluster max zoom —
    via a join back to the source row. Cluster features keep NULLs for these
    columns, which ST_AsMVT omits per feature, so cluster properties stay
    exactly MapLibre-shaped. Without this, data-driven styling and popups
    silently broke for any dataset on the server-cluster path.

    DP-02 (Phase 1209-03): ``schema`` defaults to ``"data"`` (single_tenant
    unchanged).  In multi_tenant callers pass ``tenant_data_schema(tid)`` so
    the FROM clause is ALWAYS explicitly schema-qualified (T-1209-11).
    """
    _validate_tile_table_name(table_name)
    # Schema name derives from validated-UUID tenant_data_schema() — safe to quote.
    qualified_table = f'"{schema}"."{table_name}"'

    # Mirror _build_attr_columns' exclusion + revalidation rules, but project
    # from the joined source row and only for unclustered features.
    unclustered_attr_select = "".join(
        f",\n        src.{col['name']} AS {col['name']}"
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
-- fix(#868): bucket sizes in 3857 meters. $6 (CSS px) converts to extent
-- units before scaling by tile width. The grid anchors to the WORLD MINIMUM
-- (codex round 3 on PR #872): every tile at a zoom shares one grid, and any
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
-- fix(#868, codex P2 on PR #872): scan envelope = tile + one full bucket, so
-- a cell straddling the tile border is seen with its COMPLETE membership.
-- Expansion applies at clustering zooms ONLY (codex round 3): past cluster
-- max zoom no cross-tile cells exist, and lower-gid ring candidates would
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
candidates AS (
    SELECT
        t.gid,
        ST_Transform(ST_PointOnSurface(t.geom_4326), 3857) AS geom_3857
    FROM {qualified_table} t, scan
    WHERE t.geom_4326 && scan.geom_4326
      AND NOT ST_IsEmpty(t.geom_4326)
    -- fix(#868): deterministic under the input cap, so neighboring tiles
    -- that both see a straddling cell agree on membership and centroid.
    ORDER BY t.gid
    LIMIT {_CLUSTER_INPUT_LIMIT}
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
-- fix(#868, codex round 2 on PR #872): the ownership anchor is the cell
-- ORIGIN (world_min + bucket index * bucket size) — pure grid geometry,
-- independent of which points were scanned. Under input-cap saturation
-- neighboring tiles can see different subsets of a shared cell; a
-- data-dependent anchor (the round-1 centroid) could then land in either
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
grouped AS (
    SELECT
        bucket_x,
        bucket_y,
        count(*)::integer AS raw_point_count,
        min(gid)::bigint AS source_gid,
        -- fix(#874): member spread, in exact double precision (ST_Extent would
        -- return a float4-rounded box). Feeds the expansion_zoom derivation.
        min(ST_X(geom_3857)) AS min_x,
        max(ST_X(geom_3857)) AS max_x,
        min(ST_Y(geom_3857)) AS min_y,
        max(ST_Y(geom_3857)) AS max_y,
        ST_Centroid(ST_Collect(geom_3857)) AS geom_3857
    FROM anchored, bounds
    -- fix(#868, codex round 4 on PR #872): ownership applies BEFORE the
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
    LIMIT {_TILE_FEATURE_LIMIT}
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
        -- fix(#874): the zoom at which THIS cell actually splits, not a
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
            -- fix(#868, codex round 4 on PR #872): clamp the emitted point
            -- into the owning tile, one MVT extent unit inside each edge.
            -- Anchor ownership lets a cell's centroid fall up to one bucket
            -- inside the NEIGHBOR tile; a viewport that covers the centroid
            -- but not the owner tile never requests the owner tile, so
            -- geometry left outside the tile would be invisible there (no
            -- MVT buffer can fix an unrequested tile). Max positional
            -- error: one bucket = the cluster radius in CSS px. This
            -- supersedes the round-2 radius-scaled buffer — the emitted
            -- geometry is now always in-tile.
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
    # layer_name must match the schema-qualified table so clients can identify it.
    # In single_tenant schema=="data"; in multi_tenant the tile-config contract
    # exposes the resolved tenant schema as ``mvt_source_layer_prefix``. Frontend
    # consumers use that prefix for MapLibre's source-layer while keeping the
    # logical ``data.{table}`` route used to sign tile URLs. The server must retain
    # physical schema qualification here for dormant-tenancy isolation.
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
    columns: list[dict] | None = None,
    *,
    tile_columns: list[str] | None = None,
    additional_columns: list[str] | None = None,
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
        columns: Column info list from the dataset. fix(#403): resolved
            through ``_select_tile_columns`` (identical rules to ``get_tile``:
            per-zoom defaults, ``tile_columns`` allowlist, ``cols=`` opt-in)
            and projected onto UNCLUSTERED features so data-driven styling
            and popups work past cluster max zoom.
        tile_columns: Phase 269 H-23 allowlist override (None / [] / list).
        additional_columns: Runtime opt-in columns (the ``cols=`` param).
        cluster_radius: Cluster radius in CSS/screen pixels (MapLibre
            ``clusterRadius`` semantics; converted to MVT extent units
            inside the query — fix(#868)).
        cluster_max_zoom: Maximum zoom level at which clustering is active.
        conn: Optional already-acquired asyncpg connection (see ``get_tile``
            docstring for DP-02 details; T-1209-10).
        schema: Data schema name; defaults to ``"data"`` (single_tenant).
    """
    _validate_tile_table_name(table_name)

    attr_columns = _select_tile_columns(
        columns or [],
        z,
        tile_columns=tile_columns,
        additional_columns=additional_columns,
    )
    query = _build_cluster_tile_query(
        table_name, schema=schema, attr_columns=attr_columns
    )
    # Schema-qualified (single_tenant => "data.{table}"); see MVT-01 note above.
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
