"""Fences, ceilings and helpers more than one analysis family needs.

Carved out of the single-file ``analysis_sql`` by #1089: what lands here is
what would become a DRIFT SURFACE if each family kept its own copy — the
``OFFSET 0`` pull-up fence and the two aliases built on it, the measured size
ceilings and the benchmark tables that justify them, the antimeridian
helper, and the mask parser. The package ``__init__`` docstring states the
injection boundary; ``render_mask_expr`` below is the half of it that runs.

Import via the ``app.platform.analysis_sql`` façade, never from here — the
whole point of the package is that the preview path and the materialize
worker reach one set of renderers
(``test_no_external_imports_of_analysis_sql_family_modules`` in
``tests/test_layering.py``).
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

# fix(#694): per-operation source-size ceilings, keyed by amplification
# shape. dissolve: ST_Union memory scales with input — ~1M polygons
# OOM-kills a 2 GB db container and takes every connection with it, so 250k
# keeps 4x headroom. buffer: output-amplifying with no byte quota on vector
# datasets, so the source itself is bounded (fix(#956): intersect amplifies
# too, along a different axis — buffer grows each geometry, intersect
# multiplies rows).
# Enforced twice with LIMIT-bounded live counts: at enqueue (fast 422) and
# again in the worker before the CTAS — the queue wait can be long enough
# for a re-upload to cross the cap (fix(#701)).
# fix(#953): spatial_join probes the join layer once per source row (cost =
# source rows x per-row lookup, not buffer's flat per-row expression), so it
# takes dissolve's 250k rather than buffer's 500k.
# fix(#954): measure is the cheapest operation here (one geography cast, two
# accessors, no amplification, no second layer), so its ceiling is the most
# generous.
# fix(#955): select_by_location has spatial_join's cost shape, so it takes
# the same 250k. clip is deliberately absent/uncapped — its mask layer is
# what's bounded (MAX_MASK_LAYER_FEATURES), not its source.
# The router reads this dict with .get() and skips the gate when a key is
# absent, so an operation missing here has NO ceiling, not a default one —
# every operation above needs an explicit entry for that reason.
# fix(#956): intersect's output row count isn't bounded by its source count,
# so its ceiling was measured, not guessed. Benchmarked against a
# 972-polygon/249,804-vertex mask (same yardstick as render_clip_layer_join's
# docstring), varying overlap:
#
#   sources   overlap   output rows      CTAS      output size
#     1,000       4x          4,000     0.26s          3.6 MB
#    10,000       4x         40,000      1.4s           35 MB
#    50,000       4x        200,000     12.4s          174 MB
#   150,000       4x        600,000     22.2s          521 MB
#    10,000      58x        577,453     47.8s        1,235 MB
#    10,000     145x              —      7.2s   ERROR: temp_file_limit (4 GB)
#
# Overlap factor, not source count, is the binding constraint — at 10k
# sources and heavy overlap the output already passes half of
# MAX_OUTPUT_BYTES (roughly doubled again by the 4326 rewrite), so
# _enforce_output_size is what actually catches an amplifying run. Extreme
# overlap dies earlier still, on PostgreSQL's own temp_file_limit.
#
# 100k is sized on the BENIGN case staying comfortably inside both budgets
# (~400k rows, ~350 MB, ~15s, ~700 MB after the rewrite) — half of
# dissolve's 250k because each source row here does more work AND emits
# more than one output row.
#
# Don't lower this to catch the 58x row: no source ceiling separates it
# from the benign 150k run that finishes in 22s, so any value that rejects
# one rejects the other. Leave the amplifying case to _enforce_output_size,
# which measures the thing that actually varies.
MAX_SOURCE_FEATURES = {
    "dissolve": 250_000,
    "buffer": 500_000,
    "spatial_join": 250_000,
    "measure": 1_000_000,
    "select_by_location": 250_000,
    "intersect": 100_000,
}

_CLIP_MASK_TYPES = ("Polygon", "MultiPolygon")

# Alias both callers give the lateral subquery. Qualifying against it is not
# cosmetic: a source dataset can carry an ordinary attribute column named
# "geom_out", and an unqualified reference then becomes a planner-level
# "column reference \"geom_out\" is ambiguous" error that fails the whole
# clip (fix(#719)) — the preview has the same latent fault even
# though it selects no carry columns, since it still joins _src.
LATERAL_ALIAS = "_op"

# Rows an analysis produced nothing for. Both consumers of the lateral shape
# must filter on this: the preview because the sandbox row cap counts raw rows
# (fix(#680)), the materialize worker because the output-size ceiling is
# checked against the CTAS before the NULL/EMPTY cleanup runs (fix(#719
# review)). Naming it once keeps the saved dataset and the approved preview
# from drifting apart.
NOT_EMPTY_PREDICATE = (
    f"{LATERAL_ALIAS}.geom_out IS NOT NULL AND NOT ST_IsEmpty({LATERAL_ALIAS}.geom_out)"
)


# A planar longitude span wider than this means the geometry does not really
# stretch that far — it wraps the antimeridian, since no 4326 geometry can
# legitimately span more than 180° without also enclosing a pole. See
# ``render_dateline_safe`` for why the guard has to be conditional.
DATELINE_WRAP_SPAN_DEG = 180


# A geography buffer projects its WHOLE input into one planar SRID chosen by
# PostGIS's ``_ST_BestSRID``, local to every component only while the input
# fits inside a single UTM zone (6° of longitude). Measured on PostGIS 3.6,
# the switch away from the UTM zone happens exactly at a 6.0° span, so the
# guard in ``render_geodesic_buffer`` tests ``>=``, not ``>``.
# fix(#902): the same constant is the slice width for wider inputs — slicing
# at the number the gate tests keeps one threshold.
#
# fix(#1089): the three BUFFER_SLICE constants stay here, not in
# ``transform`` with their only caller — they're the antimeridian threshold
# set ``render_dateline_safe`` reasons about in the same ±180/one-UTM-zone
# terms and have to be read together. A family that later emits
# seam-crossing geometry needs the same numbers, not a second opinion.
BUFFER_LOCAL_SRID_SPAN_DEG = 6

# fix(#902): before a wide input is sliced into longitude bands, its edges
# are densified along GREAT CIRCLES (``ST_Segmentize`` on geography) at this
# max edge length. Geography edges are geodesics, so cutting the bare planar
# chord buffers a different line: for ``LINESTRING(0 45, 90 45)`` the
# great-circle path (what ``ST_Buffer(geography)`` buffers) yields 134.1e9
# m² vs 141.7e9 m² for the planar chord. 20 km keeps the chord-vs-arc
# deviation under 8 m — noise against the ±1% radius bar — matching the
# issue's piecewise ground truth.
BUFFER_SLICE_SEGMENTIZE_M = 20_000

# fix(#902): POLYGONAL components are densified PLANAR-ly instead —
# geography-segmentizing a ring reinterprets its long planar edges as great
# arcs and moves the region itself (a 0..90 rectangle's lat-45 interior
# point fell outside its own "segmentized" area). Rings keep their stored
# planar shape, densified at 0.1° so the geography buffer of each slice
# treats every sub-edge as a ≤0.1° geodesic — about 1 m of deviation from
# the planar edge.
BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG = 0.1

# fix(#1097): the prefix every INTERNAL column alias in a rendered
# statement carries, and which a carried column may therefore not start
# with. The output-collision guards reserve names that reach the OUTPUT
# (join_count, source_gid) but said nothing about aliases invented along the
# way — an overlay attribute named `_mask_gid`, `g` or `_src_type` collided
# with a query's own alias of that name (`SELECT _o.gid AS _mask_gid,
# "_mask_gid"`), making `_mp._mask_gid` ambiguous and failing the CTAS after
# the queue wait, quoting a name the user never chose.
#
# A reserved PREFIX rather than a list of the three names, because a list is
# only correct for the aliases that exist when it's written — this PR
# already watched two such lists fall behind (provenance redaction, picker
# filters). Reserving the namespace covers an alias added later by
# construction.
#
# fix(#1089): central, not in ``overlay`` with today's only three aliases —
# the rule's whole point is covering an alias added LATER, possibly by
# another family, which an overlay-owned constant couldn't credibly do.
INTERNAL_ALIAS_PREFIX = "_gl_"

# Column types PostgreSQL cannot group by — no equality operator; grouping
# on one fails with SQLSTATE 42883.
#
# Here rather than in either caller: dissolve's by_field guard needs it at
# enqueue (the router) and again after the queue wait (the worker), and the
# worker must not import from the API layer. Intersect used to need it too
# (it grouped by every carried overlay column) until fix(#1099) moved those
# attributes out of the GROUP BY.
#
# fix(#1089): not moved into ``transform`` with dissolve — it's a
# PostgreSQL capability fact with no rendered statement behind it, and its
# consumer set has already crossed a family boundary once inside a single
# release.
NON_GROUPABLE_COLUMN_TYPES = frozenset({"json", "xml"})


def render_dateline_safe(geom_expr: str, *, alias: str = "_dl") -> str:
    """Split antimeridian-wrapping output of ``geom_expr`` at ±180.

    fix(#697): ``ST_Buffer(...::geography, d)::geometry`` normalizes
    longitude into [-180, 180], so a buffer crossing the antimeridian comes
    back as ONE planar polygon with vertices on both sides of the seam.
    Probed on PostGIS 3.6: a 10 km buffer of a point at lon 179.95/lat 45
    returns a self-intersecting POLYGON with a 359.99°-wide planar envelope.
    Registration stores that envelope verbatim into
    ``records.spatial_extent`` (a bare ``ST_Extent``), so the saved dataset
    published a near-global bbox on the datasets API and OGC Features
    collection extent, and the stored geometry matched a bbox query over
    central France — a feature-level false positive ~15,000 km off.

    The split shifts into the 0..360 domain, cuts at x=180, translates the
    far side back by -360, and keeps the polygonal components — a valid
    multipart geometry inside [-180, 180].

    Decided PER POLYGON COMPONENT, not the whole buffer's envelope
    (fix(#883)): one source feature can put components at both seams
    (a MULTIPOINT holding (179.95, 45) and (0, 45) buffers to one
    antimeridian-wrapping polygon plus one Greenwich-straddling polygon),
    and those two want opposite treatment. Sweeping the second point's
    longitude: an envelope-level test declined at lon ±0.05 (leaving the
    antimeridian component self-intersecting, still hitting the France
    bbox) and split at lon 0.0 (blowing the Greenwich component to 6 parts,
    11.6x the correct area, newly hitting a bbox at lon -100 neither input
    was near). Per-component decisions give 3 parts, exact area, no remote
    hit.

    ``ST_Dump`` then ``ST_CollectionHomogenize(ST_Collect(...))`` keeps the
    per-component pass type-preserving: a single-component result collapses
    back to POLYGON rather than a promoted one-part MULTIPOLYGON.

    ``ST_ShiftLongitude`` runs BEFORE ``ST_MakeValid``, and the order is
    load-bearing — a wrapping ring is self-intersecting *in the planar
    domain*, so validating first repairs an artefact of the wrap (nodes the
    seam, emits spurious slivers). Measured on a 10 km buffer at lon 179.95:
    validate-first gives 4 parts holding 97.9% of expected area;
    shift-first gives 2 parts holding 99.3% — the same ratio a
    non-crossing buffer of equal radius reaches (the 0.7% deficit is
    ``ST_Buffer``'s own polygonal approximation of a geodesic circle).
    ``ST_WrapX`` needs valid input too, so validation stays, just after the
    shift.

    Two conditions gate a component's split. The planar span must exceed
    ``DATELINE_WRAP_SPAN_DEG``: skipping this isn't optional, since
    ``ST_ShiftLongitude`` maps negative longitudes to 180..360, so an
    unconditional shift splits ordinary geometry at the PRIME meridian
    instead (a 10 km buffer at lon 0, unguarded, returned 2 parts covering
    49x the correct area). It also keeps the comparison below off a float
    tie, since shifting a geometry wholly west of Greenwich adds 360° to
    every vertex.

    Shifting must also NARROW the span: a pole-encircling geometry occupies
    every longitude, so its span stays wide once shifted and splitting it
    would only cut away area (a 100 km buffer at lat 89.9 measured 347.3°
    planar / 349.9° shifted and is correctly left alone; a span-only test
    would have split it to 93% of its area). A seam-wrapping buffer instead
    collapses — 359.99° planar to 0.25° shifted — which is the signal being
    tested for.

    The same span test also gates entry to the per-component pass, one
    level out: the envelope contains every component, so an envelope
    spanning ≤180° means no component can be wrapping, and the ordinary
    low-longitude buffer is a bare ``ELSE`` with no dump/re-collect on the
    common path.

    ``geom_expr`` runs inside an ``OFFSET 0``-fenced subquery — the same
    pull-up fence ``_wrap_not_empty`` and ``build_preview_sql`` use
    (fix(#700)), since the CASE references the geometry several
    times; the per-component shifted copy is fenced the same way so
    ``ST_ShiftLongitude`` also runs once per component (``EXPLAIN VERBOSE``
    over 2,000 rows keeps ``ST_Buffer`` at one evaluation per row).

    NOT fixed here, deliberately: a dataset genuinely straddling the seam
    still registers a -180..180 ``spatial_extent``. The column isn't what
    stops it — fix(#892) widened the typmod to ``geometry(Geometry, 4326)``
    with ``chk_records_spatial_extent_type`` allowing POLYGON/MULTIPOLYGON
    (the two-ring form RFC 7946 §5.2's west>east bbox corresponds to,
    already used by the STAC harvest path). What flattens the extent is the
    derivation: this path registers one ``ST_Extent`` envelope over
    everything, collapsing a two-lobed result. That predates the analysis
    tools and equally affects directly ingested Fiji-area data — it needs a
    seam-aware extent derivation, not a wider column.
    """
    # Per-component split, innermost first: dump into components, pair each
    # with its shifted copy (OFFSET 0-fenced), decide per component, dump
    # the split results to bare polygons, then re-collect and homogenize.
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


def render_mask_expr(mask: dict[str, Any]) -> str:
    """Render a validated clip mask as a PostGIS geometry expression.

    Raises ValueError on anything that is not a usable Polygon/MultiPolygon.

    fix(#1089): central rather than in ``overlay`` with today's only two
    callers, because this function IS the injection boundary the package
    docstring describes — the one place untrusted GeoJSON becomes SQL text.
    Whoever adds a family that accepts a drawn geometry must reuse it, and a
    reviewer asking "where does caller input reach a statement" should land on
    one file.
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


def render_bbox_predicate(bbox: list[float], *, src: str) -> str:
    """Render a viewport-scope prefilter: ``&&`` against a GIST-indexed column.

    fix(#727): a capped preview's ``ORDER BY gid`` returns the first
    ``PREVIEW_FEATURE_CAP`` rows in ingest order — usually the source file's
    order, usually spatially clustered. A 500-row cap over a 22k-feature
    layer then draws two arbitrary clumps instead of a spatial sample, which
    reads as a failed operation. Scoping source rows to the map's current
    viewport BEFORE the cap applies turns the 500 rows into "the operation
    applied to what is on screen", without touching ``ORDER BY gid`` itself
    (which is what lets the row cap stop the scan early — see the
    ``fix(#700)`` comment on the lateral shape this predicate joins).

    ``&&`` (bounding-box overlap), not ``ST_Intersects`` — callers that need
    exact intersection add their own ``ST_Intersects`` beside their own
    ``&&`` (see ``render_select_by_location_where``); this predicate only
    bounds WHICH rows the cap sees, so the plain index-only operator is
    enough and cheaper.

    Bounds are the caller's responsibility (``AnalysisPreviewRequest``
    validates finiteness and ordering before this runs) — mirrors
    ``render_mask_expr``'s "validate, then format" division of labor.
    """
    minx, miny, maxx, maxy = (float(v) for v in bbox)
    return f"{src}.geom_4326 && ST_MakeEnvelope({minx!r}, {miny!r}, {maxx!r}, {maxy!r}, 4326)"
