"""Fences, ceilings and helpers more than one analysis family needs.

Carved out of the single-file ``analysis_sql`` by #1089. What lands here is
what would become a DRIFT SURFACE if each family kept its own copy: the
``OFFSET 0`` pull-up fence and the two aliases built on it, the measured size
ceilings and the benchmark tables that justify them, the antimeridian helper,
and the mask parser. The package ``__init__`` docstring states the injection
boundary; ``render_mask_expr`` below is the half of it that runs.

Import via the ``app.platform.analysis_sql`` façade, never from here — the
whole point of the package is that the preview path and the materialize worker
reach one set of renderers (``test_no_external_imports_of_analysis_sql_family_
modules`` in ``tests/test_layering.py``).
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
# buffer: an output-amplifying operation, and vector datasets carry no byte
# quota, so bound the amplification source instead. (fix(#956): buffer was
# described here as the ONLY amplifying operation. Intersect amplifies too,
# and along a different axis — buffer grows each geometry, intersect
# multiplies ROWS.)
# Enforced twice with LIMIT-bounded live counts: at enqueue (router, fast
# 422) and again in the worker right before the CTAS — the queue wait can be
# long enough for a dataset to be re-uploaded past its cap (fix(#701
# review)).
# fix(#953): spatial_join probes the join layer once per source row, so its
# cost is source rows x per-row index lookup rather than buffer's flat per-row
# expression. 250k matches dissolve rather than buffer's 500k for that reason.
# Note the router reads this with .get() and skips the gate when the key is
# absent, so an operation missing here has NO ceiling, not a default one.
# fix(#954): measure is the cheapest operation here — one geography cast and
# two accessor calls per row, no output amplification and no second layer — so
# its ceiling is the most generous. It exists at all because the router reads
# this dict with .get() and skips the gate when a key is absent, which would
# leave the operation with NO ceiling rather than a default one.
# fix(#955): select_by_location has spatial_join's cost shape — one GIST probe
# into a second layer per source row — so it takes the same 250k. Note clip is
# deliberately absent and therefore uncapped: its mask layer is what is bounded
# (MAX_MASK_LAYER_FEATURES), not its source.
# fix(#956): intersect is the only operation whose OUTPUT ROW COUNT is not
# bounded by its source count, so its ceiling was measured rather than guessed.
# Benchmarked against a 972-polygon / 249,804-vertex mask (the same yardstick
# render_clip_layer_join's docstring uses, reproduced synthetically), varying
# how many mask features each source overlaps:
#
#   sources   overlap   output rows      CTAS      output size
#     1,000       4x          4,000     0.26s          3.6 MB
#    10,000       4x         40,000      1.4s           35 MB
#    50,000       4x        200,000     12.4s          174 MB
#   150,000       4x        600,000     22.2s          521 MB
#    10,000      58x        577,453     47.8s        1,235 MB
#    10,000     145x              —      7.2s   ERROR: temp_file_limit (4 GB)
#
# The source count is NOT the binding constraint; the overlap factor is. At
# 10k sources and heavy overlap the output already passes half of
# MAX_OUTPUT_BYTES, and the 4326 rewrite roughly doubles the payload again, so
# _enforce_output_size is what actually catches an amplifying run — no source
# ceiling could. Extreme overlap dies earlier still, on PostgreSQL's own
# temp_file_limit.
#
# 100k is therefore sized on the BENIGN case staying comfortably inside both
# budgets (~400k rows, ~350 MB, ~15s, roughly 700 MB after the rewrite), while
# anything pathological hits the 300s MATERIALIZE_TIMEOUT or the output check
# instead of the box's memory. Half of dissolve's 250k because each source row
# here does more work AND emits more than one output row.
#
# The obvious next suggestion is to lower this until it catches the 58x row.
# Don't: no source ceiling separates those two runs, so the only value that
# rejects the 47.8s job also rejects the benign 150k one that finishes in 22s.
# That trades a cheap early-out for a false refusal. Leave the amplifying case
# to _enforce_output_size, which measures the thing that actually varies.
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
#
# fix(#1089): the three BUFFER_SLICE constants stay here rather than moving to
# ``transform`` with their only caller. They are the antimeridian threshold set:
# each one is a number ``render_dateline_safe`` above reasons about in the same
# ±180 / one-UTM-zone terms, and the pair has to be read together to see why the
# buffer gate tests >= at exactly the width it slices at. A family that later
# emits seam-crossing geometry needs the same numbers, not a second opinion.
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

# fix(#902 codex r4): POLYGONAL components are densified PLANAR-ly instead —
# geography-segmentizing a ring reinterprets its long planar edges as great
# arcs and moves the region itself (a 0..90 rectangle's lat-45 interior point
# fell outside its own "segmentized" area). Rings keep their stored planar
# shape, densified at 0.1° so the geography buffer of each slice treats every
# sub-edge as a ≤0.1° geodesic — about 1 m of deviation from the planar edge.
BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG = 0.1

# fix(#1097 review): the prefix every INTERNAL column alias in a rendered
# statement carries, and which a carried column may therefore not start with.
#
# The output-collision guards reserve names that reach the OUTPUT — join_count,
# source_gid. They said nothing about the aliases a query invents on the way
# there, so an overlay attribute named `_mask_gid`, `g` or `_src_type` landed in
# the same select list as the alias of that name: `SELECT _o.gid AS _mask_gid,
# "_mask_gid"`. The later `_mp._mask_gid` is then ambiguous and the CTAS fails,
# after the queue wait, quoting a name the user never chose.
#
# A reserved PREFIX rather than a list of the three names. A list is correct
# only for the aliases that exist when it is written, and this PR has already
# watched two such lists fall behind (the provenance redaction, the picker
# filters). Renaming the aliases into a namespace and reserving the namespace
# means an alias added later is covered by construction, with no second place
# to remember to update.
#
# fix(#1089): central, not in ``overlay`` with today's only three aliases. The
# whole design of the rule is that it covers an alias added LATER, and an alias
# added by another family would read as out of scope from an overlay-owned
# constant — which is the list-falls-behind failure again, wearing the split as
# its excuse.
INTERNAL_ALIAS_PREFIX = "_gl_"

# Column types PostgreSQL cannot group by, because they have no equality
# operator. Grouping on one fails with SQLSTATE 42883.
#
# Here rather than in either caller: dissolve's by_field guard needs it at
# enqueue (the router) and again after the queue wait (the worker), and the
# worker must not import from the API layer. Intersect used to be the other
# caller — it grouped by every carried overlay column, so it inherited the same
# limit. fix(#1099) moved those attributes out of the GROUP BY and the intersect
# guards came out with them; only the operation that really groups by a
# user-chosen column is left.
#
# fix(#1089): that history is also why it did not follow dissolve into
# ``transform``. It is a PostgreSQL capability fact with no rendered statement
# behind it, and its consumer set has already crossed a family boundary once
# inside a single release.
NON_GROUPABLE_COLUMN_TYPES = frozenset({"json", "xml"})


def render_dateline_safe(geom_expr: str, *, alias: str = "_dl") -> str:
    """Split antimeridian-wrapping output of ``geom_expr`` at ±180.

    fix(#697): ``ST_Buffer(...::geography, d)::geometry`` normalizes longitude
    into [-180, 180], so a buffer that reaches across the antimeridian comes
    back as ONE planar polygon carrying vertices on both sides of the seam.
    Probed on PostGIS 3.6, a 10 km buffer of a point at lon 179.95 / lat 45
    returns a self-intersecting POLYGON whose planar envelope is 359.99° wide.
    Registration stores that envelope verbatim into ``records.spatial_extent``
    (``ingest/metadata_extent.py`` computes a bare ``ST_Extent``), so the saved
    dataset published a near-global bbox on the datasets API and the OGC
    Features collection extent, and the stored geometry itself matched a bbox
    query over central France — a feature-level false positive, ~15 000 km off.

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
    ``PREVIEW_FEATURE_CAP`` rows in ingest order, which for a file-sourced
    dataset is usually the source file's order — usually spatially clustered.
    A 500-row cap over a 22k-feature layer then draws two arbitrary clumps
    instead of a spatial sample, which reads as a failed operation rather than
    a capped one. Scoping the source rows to the map's current viewport BEFORE
    the cap applies turns the 500 rows into "the operation applied to what is
    on screen" — an honest preview — without touching ``ORDER BY gid`` itself,
    which is what lets the row cap stop the scan early (see the ``fix(#700
    review)`` comment on the lateral shape this predicate joins).

    ``&&`` (bounding-box overlap), not ``ST_Intersects`` — the callers that
    need exact intersection already add their own ``ST_Intersects`` beside
    their own ``&&`` (see ``render_select_by_location_where``); this predicate
    exists only to bound WHICH rows the cap sees, not to filter with pixel
    accuracy, so the plain index-only operator is enough and cheaper.

    Bounds are the caller's responsibility (``AnalysisPreviewRequest``
    validates finiteness and ordering at the request boundary before this
    ever runs) — mirrors ``render_mask_expr``'s division of labor, where the
    injection boundary is "validate, then format", not "format defensively".
    """
    minx, miny, maxx, maxy = (float(v) for v in bbox)
    return f"{src}.geom_4326 && ST_MakeEnvelope({minx!r}, {miny!r}, {maxx!r}, {maxy!r}, 4326)"
