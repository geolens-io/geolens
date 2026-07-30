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
"""

from __future__ import annotations

import math
from typing import Any

import shapely
from shapely.errors import GEOSException
from shapely.geometry import shape

MAX_BUFFER_METERS = 100_000.0
MAX_MASK_VERTICES = 5_000

# fix(#693): the materialize path unions the mask layer WHOLE, and the
# preview pays a per-request subdivide pass over every mask row — both scale
# with the layer, and neither is bounded by any row limit.
MAX_MASK_LAYER_FEATURES = 1_000

# fix(#694): per-operation source-size ceilings.
# dissolve: ST_Union memory grows with input; ~1M polygons OOM-kills a 2 GB
# db container, taking every connection with it — 250k keeps 4x headroom.
# buffer: the only output-amplifying operation, and vector datasets carry no
# byte quota, so bound the amplification source instead.
# Enforced twice with LIMIT-bounded live counts: at enqueue (router, fast
# 422) and again in the worker right before the CTAS — the queue wait can be
# long enough for a dataset to be re-uploaded past its cap (fix(#701
# review)).
MAX_SOURCE_FEATURES = {
    "dissolve": 250_000,
    "buffer": 500_000,
}

_CLIP_MASK_TYPES = ("Polygon", "MultiPolygon")

# Alias both callers give the lateral subquery. Qualifying against it is not
# cosmetic: a source dataset is free to carry an ordinary attribute column
# named "geom_out", and the materialize CTAS selects the carry columns from
# _src alongside the lateral's output, so an unqualified reference is a
# planner-level "column reference \"geom_out\" is ambiguous" error that fails
# the whole clip (fix(#719 review)). The preview selects no carry columns but
# still joins _src, so it had the same latent fault.
LATERAL_ALIAS = "_op"

# Rows an analysis produced nothing for. Both consumers of the lateral shape
# must filter on this: the preview because the sandbox row cap counts raw rows
# (fix(#680 review)), the materialize worker because the output-size ceiling is
# checked against the CTAS before the NULL/EMPTY cleanup runs (fix(#719
# review)). Naming it once keeps the saved dataset and the approved preview
# from drifting apart.
NOT_EMPTY_PREDICATE = (
    f"{LATERAL_ALIAS}.geom_out IS NOT NULL AND NOT ST_IsEmpty({LATERAL_ALIAS}.geom_out)"
)


# Vertex ceiling per mask piece in the preview shape below. 256 is the
# PostGIS-documented sweet spot where per-piece index rebuild overhead and
# per-pair intersection cost balance.
MASK_SUBDIVIDE_MAX_VERTICES = 256


# A planar longitude span wider than this means the geometry does not really
# stretch that far — it wraps the antimeridian, since no 4326 geometry can
# legitimately span more than 180° without also enclosing a pole. See
# ``render_dateline_safe`` for why the guard has to be conditional.
DATELINE_WRAP_SPAN_DEG = 180


# A geography buffer projects its WHOLE input into one planar SRID chosen by
# PostGIS's ``_ST_BestSRID``, and that choice is local to every component only
# while the input fits inside a single UTM zone — 6° of longitude. Measured on
# PostGIS 3.6, the switch away from the UTM zone happens exactly at a 6.0° span,
# so the guard in ``render_geodesic_buffer`` tests ``>=``, not ``>``.
# fix(#902): the same constant is the slice width for inputs wider than one
# zone — slicing at the number the gate tests keeps one threshold.
BUFFER_LOCAL_SRID_SPAN_DEG = 6

# fix(#902): before a wide input is sliced into longitude bands, its edges are
# densified along GREAT CIRCLES (``ST_Segmentize`` on geography) at this max
# edge length. Geography semantics make every edge a geodesic, so cutting the
# bare planar chord would buffer a different line: for ``LINESTRING(0 45,
# 90 45)`` the great-circle path (what ``ST_Buffer(geography)`` buffers) yields
# 134.1e9 m² while the planar chord yields 141.7e9 m². 20 km keeps the
# chord-vs-arc deviation under 8 m — noise against the ±1% radius bar — and is
# the same step the issue's piecewise ground truth was built with.
BUFFER_SLICE_SEGMENTIZE_M = 20_000


def render_dateline_safe(geom_expr: str, *, alias: str = "_dl") -> str:
    """Split antimeridian-wrapping output of ``geom_expr`` at ±180.

    fix(#697): ``ST_Buffer(...::geography, d)::geometry`` normalizes longitude
    into [-180, 180], so a buffer that reaches across the antimeridian comes
    back as ONE planar polygon carrying vertices on both sides of the seam.
    Probed on PostGIS 3.6, a 10 km buffer of a point at lon 179.95 / lat 45
    returns a self-intersecting POLYGON whose planar envelope is 359.99° wide.
    Registration stores that envelope verbatim into ``records.spatial_extent``
    (``ingest/metadata.py`` computes a bare ``ST_Extent``), so the saved dataset
    published a near-global bbox on the datasets API and the OGC Features
    collection extent, and the stored geometry itself matched a bbox query over
    central France — a feature-level false positive, ~15 000 km off.

    The split shifts into the 0..360 domain so the ring is coherent again, cuts
    at x=180, translates the far side back by -360, and keeps the polygonal
    components. The result is a valid multipart geometry inside [-180, 180].

    The decision is made PER POLYGON COMPONENT, not on the envelope of the whole
    buffer (fix(#883 review)). One source feature can put components at both
    seams — a ``MULTIPOINT`` holding (179.95, 45) and (0, 45) buffers to one
    antimeridian-wrapping polygon plus one Greenwich-straddling polygon — and
    those two want opposite treatment. Deciding once for the pair gets it wrong
    either way, and which way depends on rounding: measured across a sweep of
    the second point's longitude, the envelope test declined at lon ±0.05 and
    left the antimeridian component self-intersecting and still hitting a bbox
    over France, while at lon 0.0 it split the pair and blew the Greenwich
    component up to 6 parts covering 11.6x the correct area, newly intersecting
    a bbox at lon -100 that neither input was anywhere near. Splitting each
    component on its own evidence gives 3 parts, exact area, and no remote hit.

    ``ST_Dump`` then ``ST_CollectionHomogenize(ST_Collect(...))`` is what makes
    that per-component pass type-preserving: the homogenize collapses a
    single-component result back to POLYGON, so a component the guard declines
    to touch comes out byte-identical rather than promoted to a one-part
    MULTIPOLYGON.

    ``ST_ShiftLongitude`` runs BEFORE ``ST_MakeValid``, and the order is
    load-bearing. A wrapping ring is self-intersecting *in the planar domain*,
    so validating first repairs an artefact of the wrap: it nodes the seam and
    emits spurious slivers. Measured on a 10 km buffer at lon 179.95 — validate
    first: 4 parts holding 97.9% of the expected area; shift first: 2 parts
    holding 99.3%, the same ratio a non-crossing buffer of equal radius reaches
    (the 0.7% deficit is ``ST_Buffer``'s own polygonal approximation of a
    geodesic circle). ``ST_WrapX`` splits by intersection and does need valid
    input, so the validation stays, just after the shift.

    Two conditions gate a component's split, and both carry their own weight.

    The planar span must exceed ``DATELINE_WRAP_SPAN_DEG``. A compact geometry
    with vertices just inside +180 and just inside -180 has a planar span near
    360°, so this is what "wraps" looks like from the outside; anything narrower
    cannot be straddling the seam. Skipping the test entirely is not an option —
    ``ST_ShiftLongitude`` maps negative longitudes to 180..360, so shifting
    unconditionally splits ordinary geometry at the PRIME meridian instead: an
    unguarded run over a 10 km buffer at lon 0 returned 2 parts covering 49x the
    correct area. It also keeps the comparison below away from a float tie —
    for a geometry lying wholly west of Greenwich the shift adds 360° to every
    vertex, and the two spans then differ only by rounding.

    Shifting must also NARROW the span. A geometry that encircles a pole
    genuinely occupies every longitude, so its planar span is wide and stays
    wide once shifted, and splitting it at the seam would only cut away area:
    a 100 km buffer at lat 89.9 measured 347.3° planar / 349.9° shifted and is
    correctly left alone, where a span-only test would have split it down to 93%
    of its area. A seam-wrapping buffer collapses instead — 359.99° planar to
    0.25° shifted — which is exactly the signal being tested for.

    The same span test also gates entry to the per-component pass at all, one
    level out. It is a necessary condition: the envelope contains every
    component, so if the envelope spans 180° or less then no component can span
    more, and none can be wrapping. That makes the ordinary low-longitude buffer
    a bare ``ELSE`` returning the geometry untouched, with no dump or re-collect
    on the common path.

    ``geom_expr`` is evaluated inside an ``OFFSET 0``-fenced subquery — the
    same pull-up fence ``_wrap_not_empty`` and ``build_preview_sql`` use
    (fix(#700 review)) — because the CASE references the geometry several
    times, and the per-component shifted copy is fenced the same way so
    ``ST_ShiftLongitude`` also runs once per component. ``EXPLAIN VERBOSE``
    over 2 000 rows keeps ``ST_Buffer`` at one evaluation per row.

    NOT fixed here, and deliberately: a dataset that genuinely straddles the
    seam still registers a -180..180 ``spatial_extent``. The column is no longer
    what stops it — fix(#892) widened the typmod to ``geometry(Geometry, 4326)``
    with ``chk_records_spatial_extent_type`` allowing POLYGON or MULTIPOLYGON,
    which is the two-ring form RFC 7946 § 5.2's west > east bbox corresponds to,
    and the STAC harvest path already stores it. What flattens the extent here
    is the derivation: this path registers ``ST_Extent``, one envelope over
    everything, so a two-lobed result collapses to the full span. That predates
    the analysis tools and equally affects directly ingested Fiji-area data; it
    needs a seam-aware extent derivation, not a wider column.
    """
    # Per-component split, innermost first: dump the buffer into components,
    # pair each with its shifted copy behind an OFFSET 0 fence, decide per
    # component, dump the split results so every collected element is a bare
    # polygon, then re-collect and homogenize.
    parts = (
        f"SELECT (ST_Dump(CASE"
        f" WHEN ST_XMax({alias}_c.c) - ST_XMin({alias}_c.c)"
        f" > {DATELINE_WRAP_SPAN_DEG}"
        f" AND ST_XMax({alias}_c.s) - ST_XMin({alias}_c.s)"
        f" < ST_XMax({alias}_c.c) - ST_XMin({alias}_c.c)"
        " THEN ST_CollectionExtract("
        f"ST_WrapX(ST_MakeValid({alias}_c.s), 180, -360), 3)"
        f" ELSE {alias}_c.c END)).geom AS p"
        f" FROM (SELECT {alias}_d.c, ST_ShiftLongitude({alias}_d.c) AS s"
        f" FROM (SELECT (ST_Dump({alias}.g)).geom AS c) AS {alias}_d"
        f" OFFSET 0) AS {alias}_c"
    )
    split = (
        f"(SELECT ST_CollectionHomogenize(ST_Collect({alias}_p.p))"
        f" FROM ({parts}) AS {alias}_p)"
    )
    return (
        "(SELECT CASE"
        f" WHEN ST_XMax({alias}.g) - ST_XMin({alias}.g) > {DATELINE_WRAP_SPAN_DEG}"
        f" THEN {split}"
        f" ELSE {alias}.g END"
        f" FROM (SELECT {geom_expr} AS g OFFSET 0) AS {alias})"
    )


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
        f"ST_XMin({alias}_g.sg) + {alias}_i.i * {width}, -90,"
        f" ST_XMin({alias}_g.sg) + ({alias}_i.i + 1) * {width}, 90, 4326)"
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
    unwrapped = (
        f"(SELECT ST_CollectionHomogenize(ST_Collect(CASE"
        f" WHEN ST_XMax({alias}_u.c) - ST_XMin({alias}_u.c) > 180"
        f" AND ST_XMax({alias}_u.s) - ST_XMin({alias}_u.s)"
        f" < ST_XMax({alias}_u.c) - ST_XMin({alias}_u.c)"
        f" THEN {alias}_u.s ELSE {alias}_u.c END))"
        f" FROM (SELECT {alias}_d.c, ST_ShiftLongitude({alias}_d.c) AS s"
        f" FROM (SELECT (ST_Dump(ST_Segmentize({alias}.g::geography,"
        f" {BUFFER_SLICE_SEGMENTIZE_M})::geometry)).geom AS c) AS {alias}_d"
        f" OFFSET 0) AS {alias}_u)"
    )
    sliced = (
        f"(SELECT ST_CollectionHomogenize(ST_Collect({alias}_p.p))"
        f" FROM (SELECT (ST_Dump("
        f"ST_Buffer({alias}_c.c::geography, {distance})::geometry)).geom AS p"
        f" FROM (SELECT (ST_Dump({alias}_s.piece)).geom AS c"
        f" FROM (SELECT {unwrapped} AS sg OFFSET 0) AS {alias}_g,"
        # ST_WrapX folds a shifted-domain piece (lon up to ~540) back into
        # [-180, 180] before the ::geography cast, which rejects out-of-range
        # longitudes. A no-op for pieces already in range.
        f" LATERAL (SELECT ST_WrapX(ST_Intersection({alias}_g.sg, {band}),"
        f" 180, -360) AS piece"
        f" FROM generate_series(0, GREATEST(ceil("
        f"(ST_XMax({alias}_g.sg) - ST_XMin({alias}_g.sg)) / {width})::int, 1) - 1)"
        f" AS {alias}_i(i)) AS {alias}_s) AS {alias}_c"
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


def render_mask_expr(mask: dict[str, Any]) -> str:
    """Render a validated clip mask as a PostGIS geometry expression.

    Raises ValueError on anything that is not a usable Polygon/MultiPolygon.
    """
    try:
        geom = shape(mask)
    except (GEOSException, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "mask must be a GeoJSON Polygon or MultiPolygon geometry"
        ) from exc
    if geom.geom_type not in _CLIP_MASK_TYPES:
        raise ValueError("mask must be a GeoJSON Polygon or MultiPolygon geometry")
    if geom.is_empty:
        raise ValueError("mask geometry is empty")
    if shapely.count_coordinates(geom) > MAX_MASK_VERTICES:
        raise ValueError(f"mask exceeds {MAX_MASK_VERTICES} vertices")
    if not all(math.isfinite(v) for v in geom.bounds):
        # NaN/Infinity parse fine as JSON and as shapely coords, then blow up
        # deep inside GEOS as an uncaught exception (a 500, not a 422).
        raise ValueError("mask coordinates must be finite numbers")
    if not geom.is_valid:
        try:
            geom = shapely.make_valid(geom)
        except GEOSException as exc:
            raise ValueError("mask geometry is invalid") from exc
        if geom.geom_type not in _CLIP_MASK_TYPES:
            raise ValueError("mask geometry is invalid")
    rendered = shapely.to_geojson(geom)
    escaped = rendered.replace("'", "''")
    return f"ST_SetSRID(ST_GeomFromGeoJSON('{escaped}'), 4326)"


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
