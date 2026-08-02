"""Shared SQL rendering for parameterized PostGIS analysis (M4).

Lives in platform so both the catalog preview path
(``datasets/domain/service_analysis.py``) and the processing materialize
worker (``processing/analysis/tasks.py``) can import it — catalog must not
import processing and vice versa (CATPORT guards in test_layering.py).

Pure string rendering. The injection boundary:
- numbers are bounds-validated floats rendered via ``float()`` formatting
  (re-validated here against ``MAX_BUFFER_METERS`` so worker payloads don't
  rely solely on the API schema's bounds);
- clip masks are parsed and re-serialized by shapely, so the embedded JSON
  is strictly ``{"type": ..., "coordinates": [numbers]}``;
- table identifiers are the callers' responsibility (``_safe_table_ref`` /
  regex-validated names).

Source geometries are wrapped in ``ST_MakeValid``: one invalid ring anywhere
in a dataset would otherwise abort the whole statement with a GEOS
TopologyException, with no user-side workaround.

``geom_4326`` is always LINEAR — ingest applies ``ST_CurveToLine`` when it
builds the column and migration 0034 backfilled existing rows (#1104) — so
nothing rendered here needs to guard against curved input. The per-read
``linearized()`` wrapper the #1097 review added predated that invariant and
is gone.

fix(#1089): one file until it reached 1256 lines, now a package split by
OPERATION FAMILY:

- ``shared`` — the fences, ceilings, antimeridian helper and mask parser more
  than one family needs, and the half of the injection boundary above that
  runs (``render_mask_expr``).
- ``overlay`` — clip, intersect, select by location: a second layer or a drawn
  mask cuts or filters the source. They share the mask handling, the
  ``ST_Dimension = 2`` polygonal guard and the subdivide path.
- ``measure`` — area and length: columns added, geometry untouched.
- ``spatial_join`` — the same "add columns, leave the geometry alone" contract,
  against a join LAYER rather than a measurement.
- ``transform`` — buffer and centroid: the geometry is replaced in place.

Never by CALLER. Before this module existed the preview path and the worker
each carried their own copy of every statement, and they drifted — an approved
preview and the dataset it saved could disagree about what the operation meant.
Giving those two paths their own rendering modules recreates exactly that, so
the proposal is rejected on sight however it is dressed up.

This module is the whole import surface. Nothing outside ``platform/`` imports
a family module directly, and ``test_layering.py`` fails the build if it does.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

from app.core.geo import LON_EPSILON_DEGREES

from .shared import (
    BUFFER_LOCAL_SRID_SPAN_DEG,
    BUFFER_SLICE_SEGMENTIZE_M,
    BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG,
    DATELINE_WRAP_SPAN_DEG,
    INTERNAL_ALIAS_PREFIX,
    LATERAL_ALIAS,
    MAX_BUFFER_METERS,
    MAX_MASK_LAYER_FEATURES,
    MAX_MASK_VERTICES,
    MAX_SOURCE_FEATURES,
    NON_GROUPABLE_COLUMN_TYPES,
    NOT_EMPTY_PREDICATE,
    render_dateline_safe,
    render_mask_expr,
)

# Vertex ceiling per mask piece in the preview shape below. 256 is the
# PostGIS-documented sweet spot where per-piece index rebuild overhead and
# per-pair intersection cost balance.
MASK_SUBDIVIDE_MAX_VERTICES = 256


# fix(#1001): this function has a SECOND consumer that most edits here will
# not have in mind. The NL->SQL prompt embeds its output verbatim
# (``processing/ai/sql_generator.py`` renders it at import time), and the SQL
# sandbox admits the sixteen amplification-prone functions below ONLY inside a
# subtree that is exactly what this renderer emits — ``_matches_canonical_buffer``
# in ``platform/sandbox/validator.py`` re-renders the template and compares.
# The match follows a shape change automatically, because both sides call this
# function; what it cannot follow is a NEW function name that is itself unsafe
# outside the template, since the exemption would then cover it. Weigh that
# before adding one, and keep the default ``alias`` — a buffer rendered under
# any other alias fails the match and the sandbox refuses it.
def render_geodesic_buffer(
    geom_expr: str, distance: float, *, alias: str = "_pb"
) -> str:
    """Render a metric buffer of ``geom_expr``, per component and dateline-safe.

    fix(#891): ``ST_Buffer(...::geography, d)::geometry`` picks ONE planar
    working SRID for the whole input via ``_ST_BestSRID``, so a multipart feature
    whose components sit far apart in longitude is buffered in a projection that
    suits at most one of them. Measured on PostGIS 3.6 over a two-point
    ``MULTIPOINT`` at lat 45 with a 10 000 m buffer, reading the geodesic
    distance from each source point to every vertex of the buffer part
    containing it:

        longitude span    SRID     produced radius (m)
        under 6°          999031   9 997 - 10 004   single UTM zone
        6° - 44.99°       999247   9 904 - 10 097
        45° and up        999000   7 079 - 7 087    <- world Mercator
        about 135° and up 999061   9 240 - 10 824   wide Lambert

    At a 45° span PostGIS falls back to world Mercator, whose scale error is
    1/cos(latitude), so the buffer comes back cos(φ) too small: the two-point
    fixture at lat 45 held 49.9% of the correct area, and a component at lat 60
    measured a 5 009 m radius for a requested 10 000 m — a quarter of its area.
    Nothing errors and the output is valid, so nothing signals it.

    Latitude span is harmless by contrast. Swept to an 80° span with the
    longitude span held at 0, the SRID stayed on the UTM zone and the radius
    stayed within 9 990 - 10 004 m, because transverse Mercator holds scale ≈ 1
    along its central meridian at every latitude. So the guard tests the
    LONGITUDE span only, the same quantity ``render_dateline_safe`` tests.

    Three passes, and the order is load-bearing:

    1. Slice the input into longitude bands ``BUFFER_LOCAL_SRID_SPAN_DEG``
       wide (fix(#902): bands, not components — a SINGLE component 90° wide
       lands in world Mercator exactly like a multipart spread does, and
       per-component dumping cannot touch it because there is nothing to dump
       it into; measured, a 10 km buffer of ``LINESTRING(0 45, 90 45)`` held
       63.7% of its piecewise-truth area). Each band piece is dumped to simple
       parts and buffered on its own ``::geography``, so ``_ST_BestSRID`` sees
       at most a 6° span and picks a projection local to the piece. Buffering
       a covering set of slices and dissolving equals buffering the whole
       (a Minkowski sum distributes over union), so correctness rides on the
       dissolve in pass 3. Bands start at the geometry's own ``ST_XMin``, so
       a narrow component never straddles a band edge gratuitously. The inner
       dump of each piece's buffer keeps every collected element a bare
       polygon: ``ST_Collect`` of a ``POLYGON`` and a ``MULTIPOLYGON`` would
       yield a ``GEOMETRYCOLLECTION``.
    2. ``render_dateline_safe`` splits any component that wraps ±180. It has to
       run BEFORE the dissolve: a wrapping component's buffer is
       self-intersecting in the planar domain, and unioning it in that state
       raises ``TopologyException: side location conflict at
       179.90757318430857 44.915684255255684`` — the statement aborts outright.
       That is the same ordering lesson as fix(#883), where validating before
       shifting noded the seam into 4 slivers holding 97.9% of the area instead
       of 2 parts holding 99.3%.
    3. ``ST_UnaryUnion`` dissolves parts whose buffers overlap. Without it the
       per-component pass regresses geometry that the whole-input buffer used to
       merge: a ``MULTIPOINT`` with two points 0.05° apart plus a third 90° away
       came back as 3 overlapping parts, ``ST_IsValid`` false, area 935 908 947
       m² against a true union of 701 993 608 m² — the overlap counted twice.
       ``ST_MakeValid`` is NOT a substitute; measured on the same input it kept
       3 parts and cut the overlap out of one of them instead of merging,
       landing on 468 078 270 m². The union is a no-op where nothing overlaps
       (the fix(#883) seam fixture measures 623 944 052 m² and 3 parts either
       way), which is why it can sit unconditionally on this branch.

    One cheap condition on the SOURCE gates all of that, so an ordinary
    narrow buffer takes a bare ``ELSE`` rendering exactly the fix(#883)
    expression, with no slicing, no re-collect and no union: the longitude
    span must reach ``BUFFER_LOCAL_SRID_SPAN_DEG``. Below that the whole
    input fits one UTM zone and is already buffered in a projection local to
    it (measured ±0.04%), while a dense source — up to 500 000 rows of it,
    per ``MAX_SOURCE_FEATURES`` — would otherwise pay a slice plus a union
    per row for nothing. The same constant is the slice width, deliberately:
    under 6° the produced radius holds 9 997-10 004 m for a requested
    10 000 m, and slicing at the number the gate tests keeps one threshold to
    reason about.

    fix(#902) blast radius, decided up front: fix(#891) also required
    ``ST_NumGeometries(...) > 1``, which kept every single-part output
    byte-identical at the price of leaving a wide single component in world
    Mercator. Dropping that condition means every buffer whose span reaches
    the threshold — single-part included — changes vertex structure. Output
    stays geometrically correct and ``ST_IsValid``; callers comparing WKT or
    vertex counts for WIDE inputs will see a difference, and narrow inputs
    (under the threshold) remain byte-identical, which the tests pin.

    The guard reads the VALIDATED geometry, not the raw column, and that is what
    the ``OFFSET 0`` fence buys. ``ST_MakeValid`` can raise the part count: a
    self-intersecting ``POLYGON`` whose lobes sit 90° apart is one component as
    stored and two after validation. Gating on the column would have read a
    misleadingly narrow single part in fix(#891); the slice pass now works on
    the validated shape for the same reason.

    ``geom_expr`` is evaluated inside an ``OFFSET 0``-fenced subquery, the same
    pull-up fence the rest of this module uses (fix(#700 review)), because the
    ``CASE`` references the source geometry several times.

    Cost, from the fix(#891) ``EXPLAIN ANALYZE`` baselines over 2 000 rows,
    which the slice pass inherits. The span guard is free (7.34 ms alone over
    2 000 66-vertex polygons, short-circuited before any heavy work). What the
    common path pays is this function's own ``OFFSET 0`` fence: 335 ms ->
    376 ms on those polygons (+20 µs/row), and 53 ms -> 38 ms on 2 000 bare
    points, where materializing ``ST_MakeValid`` once is cheaper than
    re-deriving it. The gated path paid 87 ms -> 116 ms for 2 000
    two-component rows and 586 ms -> 1 316 ms for 200 hundred-part rows, the
    extra time being the per-piece buffers plus the dissolve; slicing swaps
    the per-component dump for a band ``generate_series`` + ``ST_Intersection``
    in the same cost class. Both ``ST_Buffer`` call sites are rendered, only
    one is reached per row.
    """
    # Slice a hair UNDER the constant: the SRID switch away from the local UTM
    # zone happens AT exactly a 6.0° span (the reason the gate tests >=), so a
    # dense piece filling its band exactly would land in the ±1% fallback SRID
    # instead of the ±0.04% zone. Measured: exact-width slices produced a
    # 9 905 m radius (999247's signature) where 5.999° slices hold 9 997+.
    width = f"({BUFFER_LOCAL_SRID_SPAN_DEG} - 0.001)"
    band = (
        f"ST_MakeEnvelope("
        f"ST_XMin({alias}_g.uc) + {alias}_i.i * {width}, -90,"
        f" ST_XMin({alias}_g.uc) + ({alias}_i.i + 1) * {width}, 90, 4326)"
    )
    # fix(#902 codex r1/r2): a geometry component that itself crosses the
    # antimeridian (LINESTRING(170 0, -170 0)) segmentizes to a vertex jump
    # from ~+180 to ~-180, and a PLANAR band intersection then reads that jump
    # as a near-global chord touching every band. Unwrap into the +360-shifted
    # domain first when — and only when — shifting narrows the planar span
    # (the same two-condition test render_dateline_safe applies), decided PER
    # COMPONENT (codex r2): a feature holding both a seam-crossing and a
    # Greenwich-crossing component fails the feature-wide test in both
    # domains, leaving the seam component's chord in place, while each
    # component on its own evidence unwraps exactly the right one.
    # Per-vertex ST_ShiftLongitude is safe within a component because the
    # segmentized edges are ~20 km, except edges crossing the PRIME meridian,
    # which shifting tears into ~360-degree chords — and exactly then that
    # component's shifted span is not narrower, so its guard declines. Bands
    # then run over the re-collected domain (up to lon ~540); ST_WrapX folds
    # each piece back into range before the ::geography cast, and
    # render_dateline_safe splits any re-wrapped output component afterwards.
    # Residual: a single COMPONENT crossing both meridians stays wide in both
    # domains and keeps planar slicing.
    # fix(#902 codex r3): a component can carry a planar seam JUMP even after
    # the per-component shift — a path crossing BOTH the antimeridian and the
    # prime meridian is wide in both domains, so neither representation is a
    # continuous chordless polyline. The jump is detectable exactly: after
    # geography segmentization every genuine edge is ~20 km (~0.2°), so any
    # planar segment wider than 180° IS the seam jump.
    # fix(#902 codex r4): the per-segment fallback is for LINEAL/PUNTAL
    # components only — dumping a POLYGON to boundary segments and buffering
    # those would keep the boundary corridor and discard the interior.
    # Polygonal components always take the band slice, which honors their
    # stored PLANAR semantics (the same reading every other consumer of the
    # column uses).
    has_jump = (
        f"(ST_Dimension({alias}_g.uc) <= 1 AND"
        f" EXISTS (SELECT 1 FROM ST_DumpSegments({alias}_g.uc) AS {alias}_e"
        f" WHERE ST_XMax({alias}_e.geom) - ST_XMin({alias}_e.geom) > 180))"
    )
    # Per-component unwrap (codex r2): shift into the +360 domain when — and
    # only when — shifting narrows THAT component's planar span, the same
    # two-condition evidence rule render_dateline_safe applies. Per-vertex
    # ST_ShiftLongitude is safe within a component because segmentized edges
    # are ~20 km, except Greenwich-crossing edges, which shifting tears — and
    # exactly then the narrowing test declines.
    unwrap_components = (
        f"SELECT CASE"
        f" WHEN ST_XMax({alias}_u.c) - ST_XMin({alias}_u.c) > 180"
        # fix(#902 codex r5): the shifted domain must win by the shared
        # longitude epsilon — a mathematically tied span (global or
        # pole-encircling rings on non-round boundaries) differs only by
        # float noise after the ±360 round-trip, and a bare < would let that
        # noise pick the per-vertex shift, tearing a Greenwich-crossing ring.
        f" AND ST_XMax({alias}_u.s) - ST_XMin({alias}_u.s)"
        f" < ST_XMax({alias}_u.c) - ST_XMin({alias}_u.c) - {LON_EPSILON_DEGREES}"
        f" THEN {alias}_u.s ELSE {alias}_u.c END AS uc"
        f" FROM (SELECT {alias}_d.c, ST_ShiftLongitude({alias}_d.c) AS s"
        f" FROM (SELECT CASE"
        f" WHEN ST_Dimension({alias}_d0.c0) >= 2"
        f" THEN ST_Segmentize({alias}_d0.c0, {BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG})"
        f" ELSE ST_Segmentize({alias}_d0.c0::geography,"
        f" {BUFFER_SLICE_SEGMENTIZE_M})::geometry END AS c"
        f" FROM (SELECT (ST_Dump({alias}.g)).geom AS c0) AS {alias}_d0) AS {alias}_d"
        f" OFFSET 0) AS {alias}_u"
    )
    # Each component either slices into longitude bands (the local-projection
    # pass) or — when it still carries a seam jump (codex r3) — falls back to
    # per-SEGMENT buffering: every segmentized segment is ~20 km, so each one
    # unwraps on its own evidence (the jump segment always narrows when
    # shifted, a Greenwich segment never needs to), gets a local projection,
    # and the dissolve merges the overlapping segment buffers into the
    # corridor. Costlier per row, but confined to this irreducible shape.
    # ST_WrapX folds shifted-domain pieces (lon up to ~540) back into
    # [-180, 180] before the ::geography cast, which rejects out-of-range
    # longitudes; a no-op for pieces already in range.
    seg_unwrap = (
        f"CASE"
        f" WHEN ST_XMax({alias}_e2.geom) - ST_XMin({alias}_e2.geom) > 180"
        f" AND ST_XMax(ST_ShiftLongitude({alias}_e2.geom))"
        f" - ST_XMin(ST_ShiftLongitude({alias}_e2.geom))"
        f" < ST_XMax({alias}_e2.geom) - ST_XMin({alias}_e2.geom)"
        f" - {LON_EPSILON_DEGREES}"
        f" THEN ST_ShiftLongitude({alias}_e2.geom) ELSE {alias}_e2.geom END"
    )
    sliced = (
        f"(SELECT ST_CollectionHomogenize(ST_Collect({alias}_p.p))"
        f" FROM (SELECT (ST_Dump("
        f"ST_Buffer({alias}_c.c::geography, {distance})::geometry)).geom AS p"
        f" FROM (SELECT (ST_Dump({alias}_s.piece)).geom AS c"
        f" FROM ({unwrap_components}) AS {alias}_g,"
        f" LATERAL (SELECT ST_WrapX({seg_unwrap}, 180, -360) AS piece"
        f" FROM ST_DumpSegments({alias}_g.uc) AS {alias}_e2"
        f" WHERE {has_jump}"
        f" UNION ALL"
        f" SELECT ST_WrapX(ST_Intersection({alias}_g.uc, {band}),"
        f" 180, -360) AS piece"
        f" FROM generate_series(0, GREATEST(ceil("
        f"(ST_XMax({alias}_g.uc) - ST_XMin({alias}_g.uc)) / {width})::int, 1) - 1)"
        f" AS {alias}_i(i)"
        f" WHERE NOT {has_jump}) AS {alias}_s) AS {alias}_c"
        f" WHERE NOT ST_IsEmpty({alias}_c.c)) AS {alias}_p)"
    )
    local = render_dateline_safe(sliced, alias=f"{alias}_m")
    whole = render_dateline_safe(
        f"ST_Buffer({alias}.g::geography, {distance})::geometry"
    )
    return (
        "(SELECT CASE"
        f" WHEN ST_XMax({alias}.g) - ST_XMin({alias}.g)"
        f" >= {BUFFER_LOCAL_SRID_SPAN_DEG}"
        f" THEN ST_UnaryUnion({local})"
        f" ELSE {whole} END"
        f" FROM (SELECT {geom_expr} AS g OFFSET 0) AS {alias})"
    )


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
        f" GROUP BY _src.gid, _mp._gl_mask_gid) AS _p"
        f"{mask_join}"
        f" WHERE _p.geom IS NOT NULL AND NOT ST_IsEmpty(_p.geom)"
    )


def render_intersect_preview(
    src_table_ref: str, mask_table_ref: str, *, geojson_precision: int
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
    """
    pairs = render_intersect_pairs(src_table_ref, mask_table_ref)
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
        _, where = render_geometry_expr("select_by_location", mask=mask)
    return (
        f"SELECT count(*)::bigint AS match_count"
        f" FROM {src_table_ref} AS _src{where}"
        f" AND _src.geom_4326 IS NOT NULL AND NOT ST_IsEmpty(_src.geom_4326)"
    )


# fix(#954): the columns a measure adds to the source row. Metres on the wire,
# matching the buffer distance convention the panel's unit picker converts for
# (AnalysisPanel's BUFFER_UNIT_METERS). ST_Area(geography) returns square
# metres and ST_Length(geography) metres, so the SQL converts nothing.
MEASURE_AREA_COLUMN = "area_sqm"
MEASURE_LENGTH_COLUMN = "length_m"
MEASURE_OUTPUT_COLUMNS = (MEASURE_AREA_COLUMN, MEASURE_LENGTH_COLUMN)


def render_measure_columns(*, src: str = "") -> tuple[str, str]:
    """Render the measured columns and the cast that feeds them (fix(#954)).

    Returns ``(select_columns, join_clause)`` in the same shape
    ``render_spatial_join`` uses, so the preview and the CTAS compose them
    identically.

    BOTH columns are emitted for every geometry type, rather than picking one
    from the catalog's ``geometry_type``. That column is classified from the
    dataset's FIRST feature (the same trap fix(#682) documents for clip masks),
    so a table typed POLYGON can legitimately hold line rows, and branching on
    it would silently measure the wrong thing for the rest of the table.
    Emitting both is honest instead: ``ST_Length`` of a polygon is 0 and
    ``ST_Area`` of a line is 0, so each row carries its meaningful measure and a
    zero, and a mixed table measures correctly throughout.

    The ``::geography`` cast is hoisted into its own lateral behind an
    ``OFFSET 0`` fence so it runs ONCE per row and feeds both accessors —
    inlined, the two references cast the geometry twice. Same fix(#700) shape
    the preview's geometry expression and the #953 join predicate use; the cast
    is the expensive part on large inputs, which the issue flags directly.

    geography, not planar: it measures on the spheroid, so an unprojected
    dataset gets a correct answer with none of the projection juggling the
    buffer path needs, and an antimeridian-crossing polygon measures correctly
    where planar area does not.
    """
    prefix = f"{src}." if src else ""
    join = (
        f" CROSS JOIN LATERAL"
        f" (SELECT {prefix}geom_4326::geography AS g"
        f" OFFSET 0) AS _mg"
    )
    columns = (
        f"ST_Area(_mg.g)::double precision AS {MEASURE_AREA_COLUMN},"
        f" ST_Length(_mg.g)::double precision AS {MEASURE_LENGTH_COLUMN}"
    )
    return columns, join


# fix(#953): the columns a spatial join adds to the source row.
SPATIAL_JOIN_COUNT_COLUMN = "join_count"
SPATIAL_JOIN_FIELD_PREFIX = "join_"

# PostgreSQL's NAMEDATALEN - 1. An identifier longer than this is truncated
# with a NOTICE rather than refused, so a guard that compares untruncated names
# is comparing strings the database will never see. Confirmed on the server
# (SELECT current_setting('max_identifier_length')) rather than taken on faith.
#
# Bytes, strictly — but every name this bounds is ASCII, because
# _SAFE_COLUMN_RE gates the join fields that can be named in a request.
MAX_IDENTIFIER_LENGTH = 63

# Transferred fields are capped because each one widens every output row and
# the CTAS has a fixed time budget. Ten is well past the "which district is
# this in" case the operation exists for.
MAX_SPATIAL_JOIN_FIELDS = 10

# Same rule dissolve applies to by_field (_validate_dissolve_by_field): a
# user-selected column name must be identifier-shaped. That is what lets the
# rendering below quote with plain double quotes — the pattern admits no quote
# and no colon, so there is nothing for SQLAlchemy's text() bind-parameter
# parser or for an identifier escape to get wrong. Cost of the rule: a column
# named "Área" cannot be transferred, exactly as it cannot be dissolved on
# today. Source columns are unaffected; they ride the carry-column path, which
# quotes properly and carries every name (fix(#763)).
_SPATIAL_JOIN_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def spatial_join_output_columns(join_fields: list[str] | None) -> list[str]:
    """Names of the columns a spatial join generates, in output order.

    Callers use this to reject a source dataset that already has a column of
    the same name: the CTAS would otherwise fail with "column specified more
    than once" after the queue wait, the same trap ``by_field`` hits on
    dissolve's generated ``source_count``.

    fix(#1097 review): TRUNCATED to PostgreSQL's identifier limit, because that
    is the name the CTAS will actually create. Verified against the server
    rather than assumed: max_identifier_length is 63, and a longer alias is
    silently truncated to it (a NOTICE, not an error), quoted or not.

    Two join fields sharing their first 58 characters therefore prefix to
    strings that differ here and are the SAME column in the output, so the
    uniqueness check below passed and the CTAS failed after the queue wait. One
    overlong alias can also truncate ONTO an existing source column without the
    collision check noticing.

    Truncating here rather than rejecting long names keeps the guards comparing
    what the database will compare, and keeps every consumer — the router's two
    checks, the worker's recheck, and this list's own uniqueness rule — reading
    one set of names. Source columns need no such treatment: they already exist
    in a table, so the server truncated them when it was created.
    """
    return [SPATIAL_JOIN_COUNT_COLUMN] + [
        f"{SPATIAL_JOIN_FIELD_PREFIX}{name}"[:MAX_IDENTIFIER_LENGTH]
        for name in (join_fields or [])
    ]


def render_spatial_join(
    join_table_ref: str,
    *,
    src: str,
    join_fields: list[str] | None = None,
) -> tuple[str, str]:
    """Spatial join against another LAYER (fix(#953)); preview AND materialize.

    Returns ``(select_columns, join_clauses)`` for a source table aliased
    ``src``. The geometry is NOT touched — a spatial join adds columns, so the
    output geometry is the source feature verbatim (see ``render_geometry_expr``
    for why it is not even ST_MakeValid'd).

    Strictly 1:1. Two laterals, because the two halves want opposite things:

    - The count lateral aggregates EVERY match, so it needs no tie-break and
      always returns exactly one row (``CROSS JOIN``).
    - The field lateral takes exactly one match under a stated tie-break —
      **lowest join-layer gid** — via ``ORDER BY _j.gid LIMIT 1``. Without it a
      point inside two overlapping polygons emits two rows for one source
      feature, and materialize then dies on ``ADD PRIMARY KEY (gid)`` with a
      constraint error rather than anything a user could act on. ``LEFT JOIN``
      so a source row matching nothing keeps its row with NULL fields instead
      of vanishing; dropping it would break the 1:1 property that lets
      ``source_feature_count`` mean anything.

    Deterministic beats cartographically ideal here: smallest-containing-polygon
    would pick the city over the county for nested boundaries, but it costs an
    ST_Area per matched pair and nothing in the issue asks for it.

    The match predicate keeps the raw ``&&`` term on the bare columns so the
    GIST index stays usable, then re-tests with ST_Intersects over made-valid
    geometries — the same split ``render_geometry_expr`` uses for clip. Both
    sides are made valid: one invalid ring in EITHER layer would otherwise
    abort the whole statement with a GEOS TopologyException.

    The explicit ``IS NOT NULL`` term is redundant and deliberate: ``&&``
    against a NULL yields NULL, so an ungeometried join row already fails the
    WHERE and cannot reach a count. Removing it changes no result (verified by
    mutation). It stays because an arbitrary join layer IS partly ungeometried
    — #700 made analysis OUTPUTS NULL-free, not arbitrary uploads — and the
    next person to edit this predicate should not have to re-derive
    three-valued logic to convince themselves those rows are handled.
    """
    fields = list(join_fields or [])
    if len(fields) != len(set(fields)):
        raise ValueError("join_fields contains duplicates")
    if len(fields) > MAX_SPATIAL_JOIN_FIELDS:
        raise ValueError(
            f"At most {MAX_SPATIAL_JOIN_FIELDS} join fields may be transferred"
        )
    for name in fields:
        if not _SPATIAL_JOIN_IDENT.match(name):
            raise ValueError(f"Invalid join field name: {name!r}")

    # fix(#953): the JOIN side is tested RAW, deliberately. The module docstring's
    # ST_MakeValid rule exists for OVERLAY operations — measured here, PostGIS
    # 3.6 raises from ST_Intersection over a self-intersecting bowtie but
    # ST_Intersects over the same geometry returns an answer, in either argument
    # position, and the same answer the repaired geometry gives. Wrapping it
    # costs a repair per CANDIDATE ROW, which the source-side hoist above cannot
    # amortise because _j differs every row: on 32,186 meteorite points against
    # 242 Natural Earth country polygons that was 33.68s versus 1.98s raw, both
    # returning 30,712 pairs. Prevalidating the join layer in a MATERIALIZED CTE
    # was tried and is worse — it wins nothing in that direction (5.22s) and
    # loses the GIST index in the other, taking 0.21s to 12.88s.
    match = (
        f"_j.geom_4326 IS NOT NULL"
        f" AND _j.geom_4326 && {src}.geom_4326"
        f" AND ST_Intersects(_j.geom_4326, _sv.g)"
    )
    columns = f"_jc.{SPATIAL_JOIN_COUNT_COLUMN}"
    joins = (
        # fix(#953): the source geometry is made valid ONCE PER SOURCE ROW here,
        # not inside the predicate below. Inlined, it is re-evaluated per
        # CANDIDATE PAIR — the same trap fix(#700) documents for the preview's
        # geometry expression, and the OFFSET 0 fence against subquery pull-up
        # is the same remedy. Measured on real data (242 Natural Earth country
        # polygons x 32,186 meteorite points): inlined 28.36s, hoisted 0.20s,
        # both returning 30,712 matches. The inlined form blew the sandbox's
        # 10s statement timeout, so the preview 422'd on a pairing a user would
        # obviously try.
        f" CROSS JOIN LATERAL"
        f" (SELECT ST_MakeValid({src}.geom_4326) AS g"
        f" OFFSET 0) AS _sv"
        f" CROSS JOIN LATERAL ("
        f"SELECT count(*)::integer AS {SPATIAL_JOIN_COUNT_COLUMN}"
        f" FROM {join_table_ref} AS _j WHERE {match}) AS _jc"
    )
    if fields:
        picked = ", ".join(f'_j."{name}"' for name in fields)
        joins += (
            f" LEFT JOIN LATERAL (SELECT {picked}"
            f" FROM {join_table_ref} AS _j WHERE {match}"
            f" ORDER BY _j.gid LIMIT 1) AS _jf ON TRUE"
        )
        for name in fields:
            columns += f', _jf."{name}" AS "{SPATIAL_JOIN_FIELD_PREFIX}{name}"'
    return columns, joins


def render_spatial_join_match_count(src_table_ref: str, join_table_ref: str) -> str:
    """Count matched PAIRS across the WHOLE source (fix(#953)).

    The geometry preview is capped at ``PREVIEW_FEATURE_CAP`` rows, so summing
    its per-row counts would answer "how many points are in these 500 polygons"
    while the map says nothing about the cap. That number is worse than none:
    it looks like the answer. This runs as its own statement, bounded by the
    sandbox statement timeout rather than by a row cap, since it returns one
    row however large the inputs are.

    Built from ``render_spatial_join`` rather than from a second hand-written
    predicate: a total that disagrees with the per-feature counts on the map is
    the one failure mode this field cannot afford, and one renderer is what
    makes disagreement impossible. It also inherits the per-source-row
    ST_MakeValid hoist, without which this statement has the same 100x+
    blow-up the per-row counts did.
    """
    _, joins = render_spatial_join(join_table_ref, src="_src")
    return (
        f"SELECT COALESCE(sum(_jc.{SPATIAL_JOIN_COUNT_COLUMN}), 0)::bigint"
        f" AS match_count"
        f" FROM {src_table_ref} AS _src{joins}"
        f" WHERE _src.geom_4326 IS NOT NULL"
    )


def render_geometry_expr(
    operation: str,
    *,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(geometry expression, WHERE clause)`` for a per-row operation.

    Operates on the conventional ``geom_4326`` column. The aggregate
    ``dissolve`` operation has a different query shape and is rendered by the
    materialize worker, not here.

    ``clip`` here is the INLINE drawn-mask shape. Clipping against a mask
    LAYER is a join, not an expression — see ``render_clip_layer_join``, which
    both the preview and the materialize worker use.
    """
    if operation == "buffer":
        if distance_meters is None:
            raise ValueError("buffer requires distance_meters")
        distance = float(distance_meters)
        if not math.isfinite(distance) or not 0 < distance <= MAX_BUFFER_METERS:
            raise ValueError(
                f"buffer distance must be between 0 and {MAX_BUFFER_METERS:g} meters"
            )
        # Buffer is the only operation here that round-trips through
        # ::geography, and therefore the only one that has to pick a planar
        # working SRID (fix(#891)) and the only one that can emit an
        # antimeridian-wrapping geometry the source never had (fix(#697)).
        # Both live in render_geodesic_buffer. Intersection (clip) and union
        # (dissolve) can only shrink or merge longitudes that were already in
        # range, and a planar centroid stays inside its input's envelope.
        return render_geodesic_buffer("ST_MakeValid(geom_4326)", distance), ""
    if operation == "centroid":
        return "ST_Centroid(ST_MakeValid(geom_4326))", ""
    if operation == "measure":
        # fix(#954): like spatial_join, measure adds columns and leaves the
        # geometry alone — see the spatial_join note below on why the output is
        # NOT ST_MakeValid'd. The measured columns come from
        # render_measure_columns.
        return "geom_4326", ""
    if operation == "spatial_join":
        # fix(#953): a spatial join adds columns; the geometry is the source
        # feature as stored. Deliberately NOT ST_MakeValid'd, unlike every
        # other operation here — those all transform the geometry anyway, so
        # repairing the input first is free. Here the output IS the input, and
        # silently returning a repaired copy would hand back a geometry the
        # user never asked to change. Validity still gets handled where it
        # actually matters, inside the join predicate (render_spatial_join).
        # The join columns themselves come from render_spatial_join.
        return "geom_4326", ""
    if operation == "select_by_location":
        # fix(#955): the drawn-mask half of select-by-location. The geometry is
        # the source feature verbatim (like spatial_join/measure above, and NOT
        # ST_MakeValid'd for the same reason), so the operation is entirely its
        # WHERE.
        #
        # Unlike clip's inline predicate below, ST_MakeValid is left off the
        # source side. Clip repairs there because its geometry expression feeds
        # ST_Intersection, which RAISES on invalid input, and the filter has to
        # agree with what the expression will compute; a selection computes
        # nothing, and ST_Intersects accepts invalid geometry directly. Leaving
        # it off is also what keeps this path's row set identical to the mask-
        # LAYER path, where the repair is unaffordable (see
        # render_select_by_location_where).
        mask_expr = render_mask_expr(mask or {})
        return (
            "geom_4326",
            f" WHERE geom_4326 && {mask_expr}"
            f" AND ST_Intersects(geom_4326, {mask_expr})",
        )
    if operation == "clip":
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
    raise ValueError(f"Unsupported operation: {operation}")


# The façade's contract, spelled out rather than left to whatever the imports
# above happen to bind. Two reasons it is explicit:
#
# - `ruff check --fix` deletes an unused import, and every re-export here IS an
#   unused import as far as F401 can tell. `__all__` is what marks them as the
#   point of the module. This repo has had façade re-exports stripped that way
#   before; the fix is not "remember not to run --fix".
# - It is the list a reviewer diffs against the pre-split module. A symbol that
#   silently stopped being importable would break `service_analysis.py`,
#   `tasks.py`, `router_analysis.py`, `schemas.py`, the sandbox validator or
#   the NL->SQL prompt at import time — and #1089 leaves all of them untouched
#   on purpose, so nothing else in this PR would catch it.
__all__ = [
    "BUFFER_LOCAL_SRID_SPAN_DEG",
    "BUFFER_SLICE_SEGMENTIZE_M",
    "BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG",
    "DATELINE_WRAP_SPAN_DEG",
    "INTERNAL_ALIAS_PREFIX",
    "INTERSECT_OUTPUT_COLUMNS",
    "INTERSECT_SOURCE_GID_COLUMN",
    "LATERAL_ALIAS",
    "MASK_SUBDIVIDE_MAX_VERTICES",
    "MAX_BUFFER_METERS",
    "MAX_IDENTIFIER_LENGTH",
    "MAX_MASK_LAYER_FEATURES",
    "MAX_MASK_VERTICES",
    "MAX_SOURCE_FEATURES",
    "MAX_SPATIAL_JOIN_FIELDS",
    "MEASURE_AREA_COLUMN",
    "MEASURE_LENGTH_COLUMN",
    "MEASURE_OUTPUT_COLUMNS",
    "NON_GROUPABLE_COLUMN_TYPES",
    "NOT_EMPTY_PREDICATE",
    "SPATIAL_JOIN_COUNT_COLUMN",
    "SPATIAL_JOIN_FIELD_PREFIX",
    "render_clip_layer_join",
    "render_dateline_safe",
    "render_geodesic_buffer",
    "render_geometry_expr",
    "render_intersect_pairs",
    "render_intersect_preview",
    "render_mask_expr",
    "render_measure_columns",
    "render_select_by_location_count",
    "render_select_by_location_where",
    "render_spatial_join",
    "render_spatial_join_match_count",
    "spatial_join_output_columns",
]
