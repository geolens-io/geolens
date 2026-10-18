"""Fences, ceilings and helpers more than one analysis family needs.

What lands here would become a drift surface if each family kept its own
copy: the ``OFFSET 0`` pull-up fence and the two aliases built on it, the
measured size ceilings, the antimeridian helper and the mask parser. The
package ``__init__`` docstring states the injection boundary;
``render_mask_expr`` below is the half of it that runs.

Import via the ``app.platform.analysis_sql`` façade, never from here
(``test_no_external_imports_of_analysis_sql_family_modules`` in
``tests/test_layering.py``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from typing import Any

import shapely
from shapely.errors import GEOSException
from shapely.geometry import shape

MAX_BUFFER_METERS = 100_000.0
MAX_MASK_VERTICES = 5_000

# The materialize path unions the mask layer WHOLE, and the
# preview pays a per-request subdivide pass over every mask row — both scale
# with the layer, and neither is bounded by any row limit.
MAX_MASK_LAYER_FEATURES = 1_000

# Per-operation source-size ceilings, keyed by amplification shape.
# - dissolve: ST_Union memory scales with input; ~1M polygons OOM-kills a
#   2 GB db container and every connection with it, so 250k keeps 4x headroom.
# - buffer: output-amplifying with no byte quota on vector datasets, so the
#   source itself is bounded.
# - spatial_join and select_by_location probe the second layer once per
#   source row, so they take dissolve's 250k rather than buffer's 500k.
# - measure: the cheapest operation (one geography cast, no amplification,
#   no second layer), so the most generous ceiling.
# - clip is deliberately absent: its mask layer is what's bounded
#   (MAX_MASK_LAYER_FEATURES), not its source.
# The router reads this dict with .get() and skips the gate when a key is
# absent, so a missing operation has NO ceiling, not a default one.
# Enforced twice with LIMIT-bounded live counts: at enqueue (fast 422) and in
# the worker before the CTAS, since a re-upload can cross the cap during the
# queue wait.
#
# intersect multiplies rows, so its output isn't bounded by its source
# count and its ceiling was measured against a 972-polygon/249,804-vertex
# mask, varying overlap:
#
#   sources   overlap   output rows      CTAS      output size
#     1,000       4x          4,000     0.26s          3.6 MB
#    10,000       4x         40,000      1.4s           35 MB
#    50,000       4x        200,000     12.4s          174 MB
#   150,000       4x        600,000     22.2s          521 MB
#    10,000      58x        577,453     47.8s        1,235 MB
#    10,000     145x              —      7.2s   ERROR: temp_file_limit (4 GB)
#
# Overlap factor, not source count, is the binding constraint: at 10k
# sources and heavy overlap the output already passes half of
# MAX_OUTPUT_BYTES (roughly doubled by the 4326 rewrite), so
# _enforce_output_size catches an amplifying run, and extreme overlap hits
# PostgreSQL's temp_file_limit. 100k keeps the benign case inside both
# budgets (~400k rows, ~350 MB, ~15s, ~700 MB after the rewrite). No source
# ceiling separates the 58x row from the benign 150k run, so lowering this
# can't catch amplification.
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
# clip. The preview needs it too: it selects no carry columns but still
# joins _src.
LATERAL_ALIAS = "_op"

# Rows an analysis produced nothing for. Both consumers of the lateral shape
# filter on this: the preview because the sandbox row cap counts raw rows,
# the materialize worker because the output-size ceiling is checked against
# the CTAS before the NULL/EMPTY cleanup runs.
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
# guard in ``render_geodesic_buffer`` tests ``>=``, not ``>``. The same
# constant is the slice width for wider inputs, so there is one threshold.
# The buffer-slice constants live beside ``render_dateline_safe`` because
# they are the same ±180/one-UTM-zone threshold set.
BUFFER_LOCAL_SRID_SPAN_DEG = 6

# Before a wide input is sliced into longitude bands, its edges
# are densified along GREAT CIRCLES (``ST_Segmentize`` on geography) at this
# max edge length. Geography edges are geodesics, so cutting the bare planar
# chord buffers a different line: for ``LINESTRING(0 45, 90 45)`` the
# great-circle path (what ``ST_Buffer(geography)`` buffers) yields 134.1e9
# m² vs 141.7e9 m² for the planar chord. 20 km keeps the chord-vs-arc
# deviation under 8 m, noise against the ±1% radius bar.
BUFFER_SLICE_SEGMENTIZE_M = 20_000

# POLYGONAL components are densified PLANAR-ly instead:
# geography-segmentizing a ring reinterprets its long planar edges as great
# arcs and moves the region itself. Rings keep their stored
# planar shape, densified at 0.1° so the geography buffer of each slice
# treats every sub-edge as a ≤0.1° geodesic — about 1 m of deviation from
# the planar edge.
BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG = 0.1

# The prefix every INTERNAL column alias in a rendered statement carries,
# and which a carried column may therefore not start with. A carried
# attribute that matches an internal alias makes the reference ambiguous and
# fails the CTAS after the queue wait, quoting a name the user never chose.
# A reserved prefix rather than a list of names covers aliases any family
# adds later.
INTERNAL_ALIAS_PREFIX = "_gl_"

# Column types PostgreSQL cannot group by — no equality operator; grouping
# on one fails with SQLSTATE 42883.
#
# Here rather than in either caller: dissolve's by_field guard needs it at
# enqueue (the router) and again after the queue wait (the worker), and the
# worker must not import from the API layer. Intersect doesn't need it: carried
# overlay attributes stay out of its GROUP BY.
NON_GROUPABLE_COLUMN_TYPES = frozenset({"json", "xml"})


def render_dateline_safe(geom_expr: str, *, alias: str = "_dl") -> str:
    """Split antimeridian-wrapping output of ``geom_expr`` at ±180.

    ``ST_Buffer(...::geography, d)::geometry`` normalizes
    longitude into [-180, 180], so a buffer crossing the antimeridian comes
    back as ONE self-intersecting planar polygon with vertices on both sides
    of the seam and a ~360°-wide envelope. Registration stores that envelope
    verbatim into ``records.spatial_extent`` (a bare ``ST_Extent``), so the
    dataset would publish a near-global bbox and match bbox queries far from
    the feature.

    The split shifts into the 0..360 domain, cuts at x=180, translates the
    far side back by -360, and keeps the polygonal components — a valid
    multipart geometry inside [-180, 180].

    Decided PER POLYGON COMPONENT, not the whole buffer's envelope: one
    source feature can put components at both seams (a MULTIPOINT holding
    (179.95, 45) and (0, 45) buffers to one antimeridian-wrapping polygon
    plus one Greenwich-straddling polygon), and those two want opposite
    treatment. An envelope-level test either leaves the wrapping component
    self-intersecting or shreds the Greenwich one at many times its area.

    ``ST_Dump`` then ``ST_CollectionHomogenize(ST_Collect(...))`` keeps the
    per-component pass type-preserving: a single-component result collapses
    back to POLYGON rather than a promoted one-part MULTIPOLYGON.

    ``ST_ShiftLongitude`` runs BEFORE ``ST_MakeValid``: a wrapping ring is
    self-intersecting *in the planar domain*, so validating first repairs an
    artefact of the wrap (nodes the seam, emits slivers that lose area).
    ``ST_WrapX`` needs valid input, so validation stays, just after the
    shift.

    Two conditions gate a component's split. The planar span must exceed
    ``DATELINE_WRAP_SPAN_DEG``: skipping this isn't optional, since
    ``ST_ShiftLongitude`` maps negative longitudes to 180..360, so an
    unconditional shift splits ordinary geometry at the PRIME meridian
    instead. It also keeps the comparison below off a float
    tie, since shifting a geometry wholly west of Greenwich adds 360° to
    every vertex.

    Shifting must also NARROW the span: a pole-encircling geometry occupies
    every longitude, so its span stays wide once shifted and splitting it
    would only cut away area. A seam-wrapping buffer instead collapses
    (359.99° planar to 0.25° shifted), which is the signal being tested for.

    The same span test also gates entry to the per-component pass, one
    level out: the envelope contains every component, so an envelope
    spanning ≤180° means no component can be wrapping, and the ordinary
    low-longitude buffer is a bare ``ELSE`` with no dump/re-collect on the
    common path.

    ``geom_expr`` runs inside an ``OFFSET 0``-fenced subquery, the same
    pull-up fence ``_wrap_not_empty`` and ``build_preview_sql`` use, since
    the CASE references the geometry several times; the per-component
    shifted copy is fenced the same way so ``ST_ShiftLongitude`` runs once
    per component.

    Out of scope: a dataset genuinely straddling the seam still registers a
    -180..180 ``spatial_extent``. The column already accepts the two-ring
    POLYGON/MULTIPOLYGON form (RFC 7946 §5.2); the flattening comes from
    registering one ``ST_Extent`` envelope over everything, which equally
    affects directly ingested Fiji-area data and needs a seam-aware extent
    derivation.
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

    This is the injection boundary the package docstring describes: the one
    place untrusted GeoJSON becomes SQL text, so every family that accepts a
    drawn geometry goes through it.
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

    A capped preview's ``ORDER BY gid`` returns the first
    ``PREVIEW_FEATURE_CAP`` rows in ingest order, which is usually spatially
    clustered and draws arbitrary clumps. Scoping source rows to the current
    viewport BEFORE the cap applies shows the operation on what is on
    screen, while ``ORDER BY gid`` still lets the row cap stop the scan
    early.

    ``&&``, not ``ST_Intersects``: this only bounds WHICH rows the cap sees;
    callers that need exact intersection add their own ``ST_Intersects``.

    Bounds are the caller's responsibility (``AnalysisPreviewRequest``
    validates finiteness and ordering before this runs).
    """
    minx, miny, maxx, maxy = (float(v) for v in bbox)
    return f"{src}.geom_4326 && ST_MakeEnvelope({minx!r}, {miny!r}, {maxx!r}, {maxy!r}, 4326)"


def render_filtered_table_ref(table_ref: str, where_sql: str | None) -> str:
    """``table_ref`` narrowed to the rows a layer filter keeps.

    ``where_sql`` must come from ``compile_feature_cql2_ast``: unqualified,
    live-schema-vetted column names and bind parameters, never caller text.
    The narrowed form is a subquery, so every FROM that reads it carries an
    alias, which PostgreSQL 15 requires. The planner pulls the subquery up,
    so the table's indexes still serve the outer query.
    """
    if not where_sql:
        return table_ref
    return f"(SELECT * FROM {table_ref} WHERE {where_sql})"


_BIND_NAME = re.compile(r"(?<!:):(\w+)")


def binds_referenced_by(sql: str, binds: Sequence[Any]) -> list[Any]:
    """The bind parameters ``sql`` names, out of ``binds``.

    One request compiles a filter per layer, and not every statement reads
    every layer. ``text().bindparams`` refuses a bind its text never names.
    """
    names = set(_BIND_NAME.findall(sql))
    return [bind for bind in binds if bind.key in names]
