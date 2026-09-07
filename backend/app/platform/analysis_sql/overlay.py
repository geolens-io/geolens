"""Overlay statements: clip, intersect and select by location.

The family that combines the source with a SECOND input — a mask layer or a
drawn polygon — and cuts or filters the source geometry by it. They share
mask handling, the ``ST_Dimension = 2`` polygonal guard and the
``_mask_pieces`` subdivide path.

A spatial join also reads a second layer but belongs in ``spatial_join``: it
adds columns and hands the source geometry back untouched, so it has no
mask, no polygonal guard and nothing to subdivide.

Import via the ``app.platform.analysis_sql`` façade, never from here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .shared import render_bbox_predicate, render_mask_expr

# Vertex ceiling per mask piece in the preview shape below. 256 is the
# PostGIS-documented sweet spot where per-piece index rebuild overhead and
# per-pair intersection cost balance.
MASK_SUBDIVIDE_MAX_VERTICES = 256


def render_clip_layer_join(mask_table_ref: str, *, src: str) -> tuple[str, str, str]:
    """Clip against a mask LAYER (fix(#693)); used by preview AND materialize.

    Returns ``(cte, lateral_subquery, where_clause)`` for a source table
    aliased ``src``.

    fix(#719): a single whole-layer ``ST_Union`` loses to per-row
    ``ST_Intersection`` against subdivided mask pieces — per-row intersection
    against one giant union is superlinear in mask complexity. Benchmark
    (22,324 Manhattan buildings vs a 972-polygon/249,804-vertex mask, same
    12,291-row result): union 33.2s, this shape 3.4s. At the union rate a
    ~250k-row source exceeds the 300s CTAS timeout, which is how a
    sub-second preview clip could fail on "Create dataset".

    Three parts, each benchmarked on the same masks:

    - ``_mask_pieces`` subdivides the mask's polygonal parts into bounded
      chunks ONCE (MATERIALIZED): a 100k-vertex mask drops 87.9s -> 0.36s.
      Polygonal-only (fix(#682)): the catalog's ``geometry_type`` is
      classified from the first feature, so a "POLYGON" mask can still hold
      point/line rows, and ``ST_MakeValid`` can shed line remnants from
      degenerate polygons — either would let point/line source features
      outside every polygon survive the clip. No usable polygonal geometry
      means no pieces, so nothing intersects and callers see an empty
      result.
    - The lateral aggregates piece intersections per source row (once per
      row; aggregate subqueries cannot be pulled up, so this needs no
      OFFSET 0 fence — the inner one only pins extract/makevalid to once
      per mask row). ``ST_LineMerge`` on single-part LineString sources
      ONLY (fix(#719)): ``ST_Union`` re-dissolves adjacent polygons
      but does not sew line segments, so a LineString crossing a piece or
      mask-row seam fragments where the whole-mask intersection stayed one
      continuous LineString. The test is ``GeometryType(...) = 'LINESTRING'``,
      NOT ``ST_Dimension(...) = 1``: over two touching mask polygons, a
      MultiLineString whose parts only touch at a point wrongly merges to
      LINESTRING under a dimension test but stays MULTILINE (matching the
      whole-mask reference) under GeometryType. Polygons and points can't
      fragment this way.
    - The EXISTS row filter probes the RAW mask table, not the CTE: the
      union CTE reaches the outer query as an InitPlan Param and blinds the
      selectivity estimator; the un-indexed piece CTE costs a linear scan
      per source row (2.4s vs 0.25s when the mask sits at the high end of
      the gid order).
    """
    cte = (
        f"WITH _mask_pieces AS MATERIALIZED ("
        f"SELECT ST_Subdivide(geom, {MASK_SUBDIVIDE_MAX_VERTICES}) AS geom"
        f" FROM (SELECT ST_CollectionExtract(ST_MakeValid(geom_4326), 3) AS geom"
        f" FROM {mask_table_ref} WHERE geom_4326 IS NOT NULL OFFSET 0) AS _p"
        f" WHERE NOT ST_IsEmpty(geom))"
    )
    lateral = (
        f"(SELECT CASE WHEN GeometryType({src}.geom_4326) = 'LINESTRING'"
        f" THEN ST_LineMerge(_agg.geom) ELSE _agg.geom END AS geom_out"
        f" FROM (SELECT ST_Union(ST_CollectionExtract("
        f"ST_Intersection(ST_MakeValid({src}.geom_4326), _m.geom),"
        f" ST_Dimension({src}.geom_4326) + 1)) AS geom"
        f" FROM _mask_pieces AS _m"
        f" WHERE _m.geom && {src}.geom_4326"
        f" AND ST_Intersects(_m.geom, ST_MakeValid({src}.geom_4326))) AS _agg)"
    )
    where = (
        f" WHERE EXISTS (SELECT 1 FROM {mask_table_ref}"
        f" WHERE geom_4326 && {src}.geom_4326)"
    )
    return cte, lateral, where


# fix(#956): overlay rows don't map 1:1 to source rows, so the CTAS uses a
# generated gid (like dissolve) and carries the source gid as an ordinary
# attribute, traceable back to the source feature it came from.
INTERSECT_SOURCE_GID_COLUMN = "source_gid"
INTERSECT_OUTPUT_COLUMNS = (INTERSECT_SOURCE_GID_COLUMN,)


def render_intersect_pairs(
    src_table_ref: str,
    mask_table_ref: str,
    *,
    src_columns: Sequence[str] = (),
    mask_columns: Sequence[str] = (),
    bbox: list[float] | None = None,
) -> str:
    """One row per intersecting (source feature, overlay feature) PAIR (#956).

    This is what separates an overlay from a clip: ``render_clip_layer_join``
    aggregates every mask piece back to ONE geometry per source row, but an
    overlay wants one row per zone crossed, each carrying that zone's
    attributes ("how many acres of THIS parcel fall in THAT zone").

    ``src_columns``/``mask_columns`` arrive ALREADY QUOTED (caller's
    responsibility per this module's rule) and are guaranteed non-colliding —
    the router rejects a collision at enqueue (duplicate column fails the
    CTAS with an opaque "column specified more than once").

    Load-bearing shape notes:

    - The mask is subdivided by ``_mask_pieces`` as in
      ``render_clip_layer_join``, but grouped by mask ``gid``, not collapsed
      across the layer — grouping by piece instead of feature would
      quadruple output for a mask polygon split into four pieces.
    - ``ST_MakeValid`` on the source is hoisted into an ``OFFSET 0`` lateral
      to run once per source row, not once per candidate pair — inlined it
      is #953's 28.4s-vs-0.2s trap, worse here since this shape probes every
      piece of every overlapping mask feature.
    - The aggregate groups by the two gids only (fix(#1099)). ``_src.gid`` is
      a real primary key, so Postgres licenses the other ``_src`` columns by
      functional dependency; ``_mp`` is a keyless CTE, so its columns need
      explicit GROUP BY. Routing overlay attributes through the CTE would
      require naming each in GROUP BY, and ``json``/``xml`` have no equality
      operator (SQLSTATE 42883) — a nested-GeoJSON properties column (which
      lands as ``json``) would make a layer unusable as an overlay. So
      overlay attributes travel via a LEFT JOIN back to the overlay table
      after aggregation instead (LEFT is safe: every ``_gl_mask_gid`` came
      from that same table in this statement, so a miss is impossible, and
      ``gid`` is its primary key so the join can't multiply rows). Rendered
      only when overlay columns are requested, so the columnless preview is
      unchanged.
    - ``ST_LineMerge`` on single-part LineString sources only, for the same
      reason as ``render_clip_layer_join``.
    - ``row_number()`` runs after ``WHERE``, so generated gids stay
      contiguous over the surviving rows.

    Cost: the generated key means neither the preview nor the CTAS can stop
    early — a window function must see every row, so the preview pays the
    full overlay before its cap applies, bounded by the sandbox statement
    timeout rather than the row limit.

    ``bbox`` (fix(#727)) is PREVIEW-ONLY: it filters which
    ``_src`` rows enter the join, so the materialize worker must never pass
    it — a saved dataset is the whole overlay, not what was on screen.
    Applied inside the inner subquery before ``GROUP BY``, so it also
    shrinks the ``_mask_pieces`` join's candidate set.
    """
    src_sel = "".join(f", _src.{c}" for c in src_columns)
    outer_cols = "".join(f", _p.{c}" for c in src_columns)
    outer_cols += "".join(f", _mo.{c}" for c in mask_columns)
    mask_join = (
        f" LEFT JOIN {mask_table_ref} AS _mo ON _mo.gid = _p._gl_mask_gid"
        if mask_columns
        else ""
    )
    bbox_where = f" WHERE {render_bbox_predicate(bbox, src='_src')}" if bbox else ""
    return (
        f"WITH _mask_pieces AS MATERIALIZED ("
        f"SELECT _o.gid AS _gl_mask_gid,"
        f" ST_Subdivide(_o._gl_g, {MASK_SUBDIVIDE_MAX_VERTICES}) AS geom"
        f" FROM (SELECT gid,"
        f" ST_CollectionExtract(ST_MakeValid(geom_4326), 3) AS _gl_g"
        f" FROM {mask_table_ref} WHERE geom_4326 IS NOT NULL OFFSET 0) AS _o"
        f" WHERE NOT ST_IsEmpty(_o._gl_g))"
        f" SELECT (row_number() OVER ())::integer AS gid,"
        f" _p.{INTERSECT_SOURCE_GID_COLUMN}{outer_cols},"
        f" CASE WHEN _p._gl_src_type = 'LINESTRING'"
        f" THEN ST_LineMerge(_p.geom) ELSE _p.geom END AS geom"
        f" FROM (SELECT _src.gid AS {INTERSECT_SOURCE_GID_COLUMN},"
        f" GeometryType(_src.geom_4326) AS _gl_src_type,"
        f" _mp._gl_mask_gid{src_sel},"
        f" ST_Union(ST_CollectionExtract("
        f"ST_Intersection(_sv.g, _mp.geom),"
        f" ST_Dimension(_src.geom_4326) + 1)) AS geom"
        f" FROM {src_table_ref} AS _src"
        f" CROSS JOIN LATERAL (SELECT"
        f" ST_MakeValid(_src.geom_4326) AS g"
        f" OFFSET 0) AS _sv"
        f" JOIN _mask_pieces AS _mp"
        f" ON _mp.geom && _src.geom_4326"
        f" AND ST_Intersects(_mp.geom, _sv.g)"
        f"{bbox_where}"
        f" GROUP BY _src.gid, _mp._gl_mask_gid) AS _p"
        f"{mask_join}"
        f" WHERE _p.geom IS NOT NULL AND NOT ST_IsEmpty(_p.geom)"
    )


def render_intersect_preview(
    src_table_ref: str,
    mask_table_ref: str,
    *,
    geojson_precision: int,
    bbox: list[float] | None = None,
) -> str:
    """The preview projection over ``render_intersect_pairs`` (fix(#956)).

    An overlay is a JOIN with a GROUP BY, not a per-row expression, so it
    doesn't fit the lateral template the other operations share — it renders
    whole and the preview selects from it.

    Only ``gid`` and ``source_gid`` are carried as properties; the saved
    dataset carries the full attributes.

    ``match_count`` is a WINDOW over this same statement, not a second one:
    ``row_number()`` in the pairs query already forces every row to
    materialize, so ``count(*) OVER ()`` is free versus running the
    expensive part twice. Selected last, outside the caller's extra-column
    list, so it never lands in the properties zip.

    ``bbox`` (fix(#727)) passes through to
    ``render_intersect_pairs`` (preview-only there). Without it, intersect
    was the one operation ``build_preview_sql``'s viewport scoping silently
    skipped, so a capped preview kept clustering in gid order.
    """
    pairs = render_intersect_pairs(src_table_ref, mask_table_ref, bbox=bbox)
    return (
        f"SELECT gid,"
        f" ST_AsGeoJSON(geom, {geojson_precision}) AS geometry_json,"
        f" {INTERSECT_SOURCE_GID_COLUMN},"
        f" count(*) OVER () AS match_count"
        f" FROM ({pairs}) AS _ov"
        f" ORDER BY gid"
    )


def render_select_by_location_where(mask_table_ref: str, *, src: str) -> str:
    """Row filter for select-by-location against a mask LAYER (fix(#955)).

    A selection keeps whole source geometries — no intersection lateral
    downstream — so this EXISTS is the entire operation and has to be exact
    on its own.

    Clip's ``&&``-only filter works there because rows missing the true
    predicate intersect to NULL/EMPTY and get dropped downstream; copied
    verbatim into a selection (no downstream filter), an L-shaped or concave
    mask would select features sitting in its notch. So ``&&`` stays as the
    index-drivable prefilter and a real ``ST_Intersects`` is added beside it.

    Both operands are RAW columns: ``ST_Intersects`` accepts invalid geometry
    (unlike ``ST_Intersection``) and agrees with the repaired answer, so no
    ``ST_MakeValid`` is needed — and adding one would be actively harmful
    here, since inside a correlated subquery it re-evaluates per candidate
    pair (measured 28.4s vs 0.2s on #953's join before that hoist), with
    nothing here to hoist it to.

    Like clip, the probe targets the RAW mask table rather than a subdivided
    CTE, for the same indexing/statistics reason (2.4s vs 0.25s when the
    mask sits at the high end of the gid order).

    ``ST_Dimension(...) = 2`` keeps the mask polygonal per ROW. Though
    ``_load_mask_dataset`` already rejects a non-polygonal mask DATASET, the
    catalog classifies ``geometry_type`` from the first feature (fix(#682)),
    so a "POLYGON" layer can still hold point/line rows, which clip drops in
    ``_mask_pieces``. Without this term, select and clip would disagree
    about what the mask is. It does not catch a degenerate polygon
    ``ST_MakeValid`` would shed to a line — that needs the per-row repair
    ruled out above.

    NULL geometry on either side falls out of ``&&`` by three-valued logic,
    not an explicit guard.
    """
    return (
        f" WHERE EXISTS (SELECT 1 FROM {mask_table_ref} AS _sel"
        f" WHERE _sel.geom_4326 && {src}.geom_4326"
        f" AND ST_Intersects(_sel.geom_4326, {src}.geom_4326)"
        f" AND ST_Dimension(_sel.geom_4326) = 2)"
    )


def render_select_by_location_count(
    src_table_ref: str, *, mask_table_ref: str | None, mask: dict[str, Any] | None
) -> str:
    """Exact selected-record total, uncapped by the preview's 500-row limit
    (fix(#955)).

    Rebuilds the filter by calling the SAME renderer the preview uses for
    whichever mask path is in play, rather than restating the predicate, so
    the count and the features on the map can't describe different sets —
    #953's lesson, where a separately written count statement drifted.

    The trailing not-NULL/not-empty pair mirrors ``NOT_EMPTY_PREDICATE``,
    restated against the source column since a selection's lateral is the
    identity. A test pins the total against the feature list directly.
    """
    if mask_table_ref is not None:
        where = render_select_by_location_where(mask_table_ref, src="_src")
    else:
        _, where = render_select_by_location_expr(mask)
    return (
        f"SELECT count(*)::bigint AS match_count"
        f" FROM {src_table_ref} AS _src{where}"
        f" AND _src.geom_4326 IS NOT NULL AND NOT ST_IsEmpty(_src.geom_4326)"
    )


def render_clip_expr(mask: dict[str, Any] | None) -> tuple[str, str]:
    """The INLINE drawn-mask clip: ``(geometry expression, WHERE clause)``.

    Clipping against a mask LAYER is a join, not an expression — see
    ``render_clip_layer_join``, which both the preview and the materialize
    worker use.
    """
    mask_expr = render_mask_expr(mask or {})
    # A boundary-grazing clip intersects at a lower dimension (polygon ∩
    # polygon edge -> LineString); extracting only components matching the
    # source's dimension keeps output homogeneous — grazing rows become
    # EMPTY, dropped by the preview and deleted by the materialize worker.
    # Bare `geom_4326 &&` keeps the GIST index usable; wrapping it in
    # ST_MakeValid inside ST_Intersects would defeat the index.
    return (
        "ST_CollectionExtract("
        f"ST_Intersection(ST_MakeValid(geom_4326), {mask_expr}),"
        " ST_Dimension(geom_4326) + 1)",
        f" WHERE geom_4326 && {mask_expr}"
        f" AND ST_Intersects(ST_MakeValid(geom_4326), {mask_expr})",
    )


def render_select_by_location_expr(mask: dict[str, Any] | None) -> tuple[str, str]:
    """The drawn-mask half of select-by-location (fix(#955)).

    Geometry is the source feature verbatim (NOT ST_MakeValid'd, like
    spatial_join and measure), so the operation is entirely its WHERE.

    Unlike clip, ST_MakeValid is left off the source side: clip needs it
    because its expression feeds ``ST_Intersection``, which raises on
    invalid input, but a selection computes nothing and ``ST_Intersects``
    accepts invalid geometry directly. This also keeps this path's row set
    identical to the mask-LAYER path, where the repair is unaffordable (see
    ``render_select_by_location_where``).

    ``render_select_by_location_count`` calls this directly rather than
    through ``render_geometry_expr``, so count and preview render the same
    predicate via the family that owns it (fix(#1089)).
    """
    mask_expr = render_mask_expr(mask or {})
    return (
        "geom_4326",
        f" WHERE geom_4326 && {mask_expr} AND ST_Intersects(geom_4326, {mask_expr})",
    )
