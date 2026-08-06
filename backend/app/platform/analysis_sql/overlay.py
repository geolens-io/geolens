"""Overlay statements: clip, intersect and select by location.

The family that combines the source with a SECOND input — a mask layer or a
drawn polygon — and cuts or filters the source geometry by it. They share the
mask handling, the ``ST_Dimension = 2`` polygonal guard and the ``_mask_pieces``
subdivide path, which is why #1089 put them in one module.

A spatial join also reads a second layer but belongs in ``spatial_join``: it
adds columns and hands the source geometry back untouched, so it has no mask,
no polygonal guard and nothing to subdivide.

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

    fix(#719): materialize used to keep a single whole-layer ``ST_Union``
    instead, on the theory that one union amortizes over every row in a batch
    job. Measured, that is backwards — per-row ``ST_Intersection`` against one
    giant union geometry is superlinear in mask complexity, so the union shape
    loses at every size. Against 22,324 Manhattan building polygons with a
    972-polygon / 249,804-vertex mask (just under ``MAX_MASK_LAYER_FEATURES``):
    union 33.2s, this shape 3.4s, both yielding the same 12,291 rows. At the
    union shape's rate a ~250k-row source exceeds the 300s CTAS budget, which
    is how a clip whose preview renders in under a second could fail on
    "Create dataset".

    Three cooperating parts (each choice benchmarked on those same masks):

    - ``_mask_pieces`` subdivides the mask's polygonal parts into bounded
      chunks ONCE per statement (MATERIALIZED), so per-row intersection cost
      scales with the local overlap instead of the whole mask — the single
      100k-vertex mask drops 87.9s -> 0.36s. Intersection distributes over
      union, so unioning the per-piece intersections equals clipping against
      the unioned mask.
      Only POLYGONAL components enter it (fix(#682): the catalog's
      geometry_type is classified from the first feature, so a "POLYGON" mask
      layer can still hold point/line rows, and ST_MakeValid can shed line
      remnants from degenerate polygons — either would let point/line source
      features outside every polygon survive the clip). A mask layer with no
      usable polygonal geometry yields no pieces, so nothing intersects and
      callers surface an empty result.
    - The lateral aggregates those piece intersections per source row: one
      output row per gid however many mask rows touch it, evaluated once per
      row (aggregate subqueries cannot be pulled up, so the fix(#700)
      property needs no OFFSET 0 fence here; the inner OFFSET 0 only pins
      the extract/makevalid pass to once per mask row).
      ``ST_LineMerge`` on single-part LineString sources ONLY (fix(#719
      review)): ``ST_Union`` dissolves adjacent polygons back into one, but it
      does not sew line segments, so a LineString crossing a piece or
      mask-row seam came back as an artificially fragmented MultiLineString
      where the whole-mask intersection returned one continuous LineString —
      changing the registered geometry type.

      The test is ``GeometryType(...) = 'LINESTRING'``, NOT
      ``ST_Dimension(...) = 1``. Measured against the whole-mask shape over
      two touching mask polygons (so their union has an interior seam):

        source                      whole-mask   dimension=1   GeometryType
        LineString across seam      LINESTRING/1  LINESTRING/1  LINESTRING/1
        MultiLineString, parts      MULTILINE/2   LINESTRING/1  MULTILINE/2
          touching at a point                     ^^ wrong
        MultiLineString, disjoint   MULTILINE/2   MULTILINE/2   MULTILINE/2
        Polygon across seam         POLYGON/1     POLYGON/1     POLYGON/1
        Point                       POINT/1       POINT/1       POINT/1

      A dimension test merges a multi-part source whose components merely
      touch at an endpoint into one line — a change the mask never asked for,
      and one the whole-mask intersection does not make. Polygons and points
      cannot fragment this way and are left alone either way.
    - The EXISTS row filter probes the RAW mask table, not the CTE: it stays
      index-drivable with real join statistics in either direction (the
      union CTE reached the outer query as an InitPlan Param, blinding the
      selectivity estimator; filtering on the un-indexed piece CTE instead
      costs a linear piece scan per source row — 2.4s vs 0.25s when the mask
      sits at the high end of the gid order).
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


# fix(#956): overlay output rows do not correspond 1:1 to source rows, so the
# source gid cannot be the output key — the CTAS takes a generated one, like
# dissolve. The source gid is carried as an ordinary attribute instead, which
# is what makes an output piece traceable back to the feature it came from
# ("which parcel is this 0.4 acres of flood zone?"). The overlay feature needs
# no equivalent: its own attributes are already carried onto every row.
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

    This is what separates an overlay from a clip. ``render_clip_layer_join``
    aggregates every mask piece back to ONE geometry per source row, so a
    parcel crossing three flood zones clips to a single feature. An overlay
    wants three, each carrying its own zone's attributes, because the question
    is "how many acres of THIS parcel fall in THAT zone".

    ``src_columns`` and ``mask_columns`` must arrive ALREADY QUOTED, per this
    module's rule that identifiers are the caller's responsibility. The caller
    also guarantees they do not collide: the router rejects that at enqueue
    (a duplicate output column fails the CTAS with an opaque "column specified
    more than once"), so nothing here silently prefixes or renames.

    Shape notes, each of which is load-bearing:

    - The mask is subdivided by ``_mask_pieces`` for the reason
      ``render_clip_layer_join`` documents (per-row cost tracks local overlap
      instead of whole-mask complexity), but the grouping is by mask ``gid``,
      NOT collapsed across the layer. Subdividing without re-grouping per mask
      FEATURE would emit one row per PIECE, so a mask polygon that happened to
      split into four would silently quadruple the output.
    - ``ST_MakeValid`` on the source is hoisted into an ``OFFSET 0`` lateral so
      it runs once per source row rather than once per candidate pair. Inlined,
      it is #953's 28.4s-vs-0.2s trap, and worse here: this shape probes every
      piece of every overlapping mask feature.
    - The aggregate groups by the two gids and NOTHING else (fix(#1099)).
      ``_src.gid`` is a real table's primary key, so PostgreSQL licenses the
      other ``_src`` columns by functional dependency; ``_mp`` is a CTE with no
      key, so anything selected from it has to be grouped explicitly. The
      overlay's ATTRIBUTES therefore do not travel through ``_mp`` at all — the
      aggregate carries the overlay gid out and the outer query joins the
      overlay table back on it. Routed through the CTE, each attribute had to
      be named in the GROUP BY, and ``json``/``xml`` have no equality operator
      (SQLSTATE 42883) — so a nested-GeoJSON properties column, which lands as
      ``json`` routinely, made a layer unusable as an overlay rather than
      merely awkward. The outer query does no aggregation, so no type is
      off-limits there.

      The join back cannot change the row count: the aggregate already emits
      one row per (source gid, overlay gid) pair, and ``gid`` is the overlay
      table's primary key, so it matches at most one row. LEFT, not INNER —
      every ``_gl_mask_gid`` was read from that same table in this same
      statement so a miss is impossible, and a join that cannot drop a row
      keeps the count claim structural instead of resting on that argument.
      Rendered only when there are overlay columns to fetch, so the preview
      (which carries none) is the statement it always was.
    - ``ST_LineMerge`` on single-part LineString sources only, for the reason
      spelled out in ``render_clip_layer_join``: ``ST_Union`` re-dissolves
      adjacent polygons but does not sew line segments, so a line crossing a
      piece seam would come back artificially fragmented.
    - ``row_number()`` is evaluated after ``WHERE``, so the generated gids are
      contiguous over the rows that survive the empty-geometry filter rather
      than carrying its holes.

    The cost of the generated key is that neither the preview nor the CTAS can
    stop early: a window function has to see every row. The preview therefore
    pays the full overlay before its cap applies, bounded by the sandbox
    statement timeout rather than by the row limit.

    ``bbox`` (fix(#727 codex round 2)) is PREVIEW-ONLY: it filters which
    ``_src`` rows enter the pair-generating join, so the materialize worker
    (``processing/analysis/tasks.py``) must never pass it — a saved dataset
    is the WHOLE overlay, not whatever was on screen when it was created.
    Applied inside the inner subquery, before ``GROUP BY``, so it also
    shrinks the ``_mask_pieces`` join's candidate set rather than filtering
    the aggregate's output after the expensive part already ran.
    """
    src_sel = "".join(f", _src.{c}" for c in src_columns)
    # The two sides come from different relations now, so the output order that
    # was one comprehension is two: source columns off the aggregate, overlay
    # columns off the joined-back overlay table.
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

    An overlay is a JOIN with a GROUP BY, not a per-row expression, so it does
    not fit the lateral template the other operations share — it renders whole
    and the preview selects from it.

    Only ``gid`` and ``source_gid`` are carried as properties. The preview
    answers "what shape, and how many"; the saved dataset answers "with which
    attributes". Threading both layers' column lists in here would buy
    properties nothing on the map reads.

    ``match_count`` is a WINDOW over this same statement, not a second one.
    ``row_number()`` inside the pairs query has already forced every row to be
    materialized, so ``count(*) OVER ()`` is free, whereas a separate aggregate
    would mean running the most expensive operation twice. It is selected last
    and sits outside the caller's extra-column list, so the positional zip that
    builds properties stops before it and it never lands in one.

    ``bbox`` (fix(#727 codex round 2)) passes straight through to
    ``render_intersect_pairs`` — see its docstring for why this is
    preview-only and where the filter lands in the query shape. Without it,
    intersect was the one operation build_preview_sql's viewport scoping
    silently skipped, even though the frontend sends a bbox for every
    operation uniformly — a capped intersect preview kept clustering in gid
    order exactly like the bug this issue exists to fix.
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

    A selection keeps whole source geometries, so unlike ``render_clip_layer_join``
    there is no intersection lateral downstream. That makes this EXISTS the
    ENTIRE operation, and it has to be exact on its own.

    Clip's row filter is ``&&`` alone, which admits any source row whose
    ENVELOPE overlaps a mask envelope. Clip survives that because rows missing
    the true predicate intersect to NULL/EMPTY and the not-empty filter drops
    them. Copy it verbatim into a selection and an L-shaped or concave mask
    selects the features sitting in its notch, which is this operation's
    signature bug. So ``&&`` stays as the index-drivable prefilter and a real
    ``ST_Intersects`` is added beside it.

    Both operands are RAW columns. ``ST_Intersects`` accepts invalid geometry
    (unlike ``ST_Intersection``, which raises) and agrees with the repaired
    answer, so no ``ST_MakeValid`` is needed — and adding one would be actively
    harmful here rather than merely wasteful: inside a correlated subquery it
    re-evaluates per CANDIDATE PAIR instead of per row, which measured 28.4s
    against 0.2s on #953's join before the ``OFFSET 0`` hoist. Nothing to hoist
    in this shape, because there is no expression left to evaluate.

    Like clip, the probe targets the RAW mask table rather than a subdivided
    CTE: it keeps real join statistics in both directions, where the CTE costs
    a linear piece scan per source row (2.4s vs 0.25s when the mask sits at the
    high end of the gid order).

    ``ST_Dimension(...) = 2`` keeps the mask polygonal per ROW.
    ``_load_mask_dataset`` already rejects a non-polygonal mask DATASET, but the
    catalog classifies ``geometry_type`` from the FIRST feature (fix(#682)), so
    a "POLYGON" layer can still hold point and line rows — and clip drops those
    in ``_mask_pieces``. Without this term, selecting and clipping against one
    layer would disagree about what the mask is. It does NOT chase the narrower
    case of a degenerate polygon that ``ST_MakeValid`` would shed to a line;
    that needs the per-row repair ruled out above.

    NULL geometry on either side falls out of ``&&`` by three-valued logic
    rather than by an explicit guard.
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
    """Exact selected-record total, uncapped by the preview limit (fix(#955)).

    The record list is this operation's deliverable, so its SIZE cannot be the
    500 the geometry preview stops at. This is the second, uncapped statement
    that answers it.

    Rebuilds the row filter by calling the SAME renderer the preview calls for
    whichever mask path is in play, rather than restating the predicate, so the
    number under the map and the features on it cannot describe different sets.
    That is #953's lesson, where a separately written count statement drifted
    from the per-row one.

    The trailing not-NULL/not-empty pair is what ``NOT_EMPTY_PREDICATE`` does
    for the preview, restated against the source column because a selection's
    lateral is the identity. A test pins the total against the feature list
    rather than leaving the agreement to this paragraph.
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
    # A clip that only grazes a boundary intersects at a lower dimension
    # (polygon ∩ polygon edge → LineString). Extract only components
    # matching the source geometry's dimension (type code = dimension + 1)
    # so the output stays homogeneous; grazing rows become EMPTY, which
    # the preview path skips and the materialize worker deletes.
    # The bare `geom_4326 &&` term keeps the GIST index usable — wrapping
    # the column in ST_MakeValid inside ST_Intersects would defeat it.
    return (
        "ST_CollectionExtract("
        f"ST_Intersection(ST_MakeValid(geom_4326), {mask_expr}),"
        " ST_Dimension(geom_4326) + 1)",
        f" WHERE geom_4326 && {mask_expr}"
        f" AND ST_Intersects(ST_MakeValid(geom_4326), {mask_expr})",
    )


def render_select_by_location_expr(mask: dict[str, Any] | None) -> tuple[str, str]:
    """The drawn-mask half of select-by-location (fix(#955)).

    The geometry is the source feature verbatim (like spatial_join and measure,
    and NOT ST_MakeValid'd for the same reason), so the operation is entirely
    its WHERE.

    Unlike clip's inline predicate, ST_MakeValid is left off the source side.
    Clip repairs there because its geometry expression feeds ST_Intersection,
    which RAISES on invalid input, and the filter has to agree with what the
    expression will compute; a selection computes nothing, and ST_Intersects
    accepts invalid geometry directly. Leaving it off is also what keeps this
    path's row set identical to the mask-LAYER path, where the repair is
    unaffordable (see ``render_select_by_location_where``).

    ``render_select_by_location_count`` calls this directly rather than going
    back through ``render_geometry_expr``: the count and the preview have to
    render the same predicate, and the family owning it is the shortest way to
    say so (fix(#1089)).
    """
    mask_expr = render_mask_expr(mask or {})
    return (
        "geom_4326",
        f" WHERE geom_4326 && {mask_expr} AND ST_Intersects(geom_4326, {mask_expr})",
    )
