"""Transform: the operations that REPLACE the source geometry.

Buffer and centroid change the geometry in place rather than combining the
source with a second input. (Dissolve is the third member conceptually, but
its statement is an aggregate with a different query shape and the
materialize worker renders it; only its ``NON_GROUPABLE_COLUMN_TYPES`` guard
reaches this package, and that lives in ``shared``.)

Buffer is also the only operation here that round-trips through
``::geography``, so it's the only one that has to pick a planar working SRID
and the only one that can emit an antimeridian-wrapping geometry its source
never had. The thresholds both turn on are ``shared``'s — the same ±180 /
one-UTM-zone numbers ``render_dateline_safe`` reasons about.

Import via the ``app.platform.analysis_sql`` façade, never from here.
"""

from __future__ import annotations

import math

from app.core.geo import LON_EPSILON_DEGREES

from .shared import (
    BUFFER_LOCAL_SRID_SPAN_DEG,
    BUFFER_SLICE_SEGMENTIZE_M,
    BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG,
    MAX_BUFFER_METERS,
    render_dateline_safe,
)


# This function has a second consumer: NL->SQL expands the model's
# ``geolens_buffer(<geom>, <metres>)`` marker through it
# (``processing/ai/buffer_marker.py``), and the SQL sandbox admits the
# amplification-prone functions below ONLY inside a subtree that is exactly
# what this renderer emits (``_matches_canonical_buffer`` in
# ``platform/sandbox/validator.py`` re-renders and compares). A shape change
# is followed automatically, but any NEW function name used here is exempted
# too, so it must be safe outside the template. A buffer rendered under a
# non-default ``alias`` fails the match and the sandbox refuses it.
def render_geodesic_buffer(
    geom_expr: str, distance: float, *, alias: str = "_pb"
) -> str:
    """Render a metric buffer of ``geom_expr``, per component and dateline-safe.

    ``ST_Buffer(...::geography, d)::geometry`` picks ONE planar
    working SRID for the whole input via ``_ST_BestSRID``, so a multipart
    feature whose components sit far apart in longitude is buffered in a
    projection that suits at most one. Measured on PostGIS 3.6 (two-point
    ``MULTIPOINT`` at lat 45, 10,000 m buffer, geodesic distance from each
    source point to every vertex of its buffer part):

        longitude span    SRID     produced radius (m)
        under 6°          999031   9,997 - 10,004   single UTM zone
        6° - 44.99°       999247   9,904 - 10,097
        45° and up        999000   7,079 - 7,087    <- world Mercator
        about 135° and up 999061   9,240 - 10,824   wide Lambert

    At a 45° span PostGIS falls back to world Mercator, whose scale error is
    1/cos(latitude), so the buffer comes back cos(φ) too small with no error
    and valid output.

    Latitude span is harmless: transverse Mercator holds scale ≈ 1 along its
    central meridian at every latitude. So the guard tests LONGITUDE span
    only, the same quantity ``render_dateline_safe`` tests.

    Three passes, order load-bearing:

    1. Slice the input into longitude bands ``BUFFER_LOCAL_SRID_SPAN_DEG``
       wide (bands, not components: a SINGLE component 90° wide lands in
       world Mercator exactly like a multipart spread does, and there is
       nothing to dump it into). Each band piece is dumped to simple parts and
       buffered on its own ``::geography``, so ``_ST_BestSRID`` sees at most
       a 6° span. Buffering a covering set of slices and dissolving equals
       buffering the whole (a Minkowski sum distributes over union), so
       correctness rides on the dissolve in pass 3. Bands start at the
       geometry's own ``ST_XMin`` so a narrow component never straddles a
       band edge gratuitously. The inner dump keeps every collected element
       a bare polygon: ``ST_Collect`` of a ``POLYGON`` and a
       ``MULTIPOLYGON`` would yield a ``GEOMETRYCOLLECTION``.
    2. ``render_dateline_safe`` splits any component that wraps ±180, BEFORE
       the dissolve: a wrapping component's buffer is self-intersecting in
       the planar domain, and unioning it in that state raises
       ``TopologyException: side location conflict`` and the statement
       aborts.
    3. ``ST_UnaryUnion`` dissolves parts whose buffers overlap; without it
       nearby parts come back overlapping, invalid, with the overlap counted
       twice. ``ST_MakeValid`` is NOT a substitute: it cuts the overlap out
       of one part instead of merging. The union is a no-op where nothing
       overlaps, so it sits unconditionally on this branch.

    One cheap condition on the SOURCE gates all of that, so an ordinary
    narrow buffer takes a bare ``ELSE`` rendering exactly the plain
    expression, with no slicing, re-collect or union: longitude span must
    reach ``BUFFER_LOCAL_SRID_SPAN_DEG``. Below that the whole input fits
    one UTM zone and is already buffered in a projection local to it, while
    a dense source (up to ``MAX_SOURCE_FEATURES``) would otherwise pay a
    slice plus a union per row for nothing.

    Every buffer whose span reaches the threshold, single-part included,
    changes vertex structure but stays valid; narrow inputs remain
    byte-identical, which the tests pin.

    The guard reads the VALIDATED geometry, not the raw column; that's what
    the ``OFFSET 0`` fence buys. ``ST_MakeValid`` can raise the part count (a
    self-intersecting ``POLYGON`` whose lobes sit 90° apart becomes two
    components), so the slice pass works on the validated shape too. The
    fence also matters because the ``CASE`` references the source geometry
    several times.

    Cost: the span guard is free; the common path pays the fence (about
    +20 µs/row on polygons, cheaper on points); the gated path adds the
    per-piece buffers plus the dissolve. Both ``ST_Buffer`` call sites are
    rendered, only one is reached per row.
    """
    # Slice a hair UNDER the constant: the SRID switch away from the local
    # UTM zone happens AT exactly a 6.0° span (why the gate tests >=), so a
    # dense piece filling its band exactly would land in the ±1% fallback
    # SRID instead of the ±0.04% zone. Measured: exact-width slices produced a
    # 9,905 m radius where 5.999° slices hold 9,997 m or more.
    width = f"({BUFFER_LOCAL_SRID_SPAN_DEG} - 0.001)"
    band = (
        f"ST_MakeEnvelope("
        f"ST_XMin({alias}_g.uc) + {alias}_i.i * {width}, -90,"
        f" ST_XMin({alias}_g.uc) + ({alias}_i.i + 1) * {width}, 90, 4326)"
    )
    # A component that itself crosses the antimeridian
    # (LINESTRING(170 0, -170 0)) segmentizes to a vertex jump from ~+180 to
    # ~-180, which a PLANAR band intersection reads as a near-global chord
    # touching every band. Unwrap into the +360-shifted domain only when
    # shifting narrows the planar span (render_dateline_safe's two-condition
    # test), decided PER COMPONENT, since a feature can hold both a
    # seam-crossing and a Greenwich-crossing component. Per-vertex
    # ST_ShiftLongitude is safe within a component since segmentized edges are
    # ~20 km, except edges crossing the PRIME meridian, which shifting tears
    # into ~360° chords; then the shifted span isn't narrower and the guard
    # declines. Bands run over the re-collected domain (up to lon ~540);
    # ST_WrapX folds each piece back before the ::geography cast, and
    # render_dateline_safe splits any re-wrapped output afterwards.
    #
    # A component crossing BOTH meridians is wide in both domains and keeps a
    # planar seam jump. After geography segmentization every genuine edge is
    # ~0.2°, so any planar segment wider than 180° IS the jump. The
    # per-segment fallback is for LINEAL/PUNTAL components only: buffering a
    # POLYGON's boundary segments would discard its interior, so polygonal
    # components always take the band slice in their stored PLANAR semantics.
    has_jump = (
        f"(ST_Dimension({alias}_g.uc) <= 1 AND"
        f" EXISTS (SELECT 1 FROM ST_DumpSegments({alias}_g.uc) AS {alias}_e"
        f" WHERE ST_XMax({alias}_e.geom) - ST_XMin({alias}_e.geom) > 180))"
    )
    # Per-component unwrap (see the passes above): shift into the
    # +360 domain only when it narrows THAT component's span.
    unwrap_components = (
        f"SELECT CASE"
        f" WHEN ST_XMax({alias}_u.c) - ST_XMin({alias}_u.c) > 180"
        # The shifted domain must win by the shared longitude epsilon: a
        # tied span (global or pole-encircling rings) differs only by float
        # noise after the ±360 round-trip, and a bare `<` would let that noise
        # pick the per-vertex shift, tearing a Greenwich-crossing ring.
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
    # Each component either slices into longitude bands or, when it still
    # carries a seam jump, falls back to per-SEGMENT buffering: each ~20 km
    # segment unwraps on its own evidence, gets a local projection, and the
    # dissolve merges the segment buffers into the corridor. ST_WrapX folds
    # shifted-domain pieces back into [-180, 180] before the ::geography
    # cast, which rejects out-of-range longitudes.
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


def render_buffer_expr(distance_meters: float | None) -> tuple[str, str]:
    """A metric buffer's per-row geometry, bounds-checked.

    ``distance_meters`` is re-validated here against ``MAX_BUFFER_METERS``
    even though the API schema bounds it, since the materialize worker
    renders from a stored payload and must not rely on the schema alone —
    see the injection boundary in the package docstring.
    """
    if distance_meters is None:
        raise ValueError("buffer requires distance_meters")
    distance = float(distance_meters)
    if not math.isfinite(distance) or not 0 < distance <= MAX_BUFFER_METERS:
        raise ValueError(
            f"buffer distance must be between 0 and {MAX_BUFFER_METERS:g} meters"
        )
    # Only buffer needs the SRID and antimeridian handling (see the module
    # docstring): clip and dissolve only shrink or merge longitudes already in
    # range, and a planar centroid stays inside its input's envelope.
    return render_geodesic_buffer("ST_MakeValid(geom_4326)", distance), ""


def render_centroid_expr() -> tuple[str, str]:
    """A centroid's per-row geometry. Planar, so it stays inside its envelope."""
    return "ST_Centroid(ST_MakeValid(geom_4326))", ""
