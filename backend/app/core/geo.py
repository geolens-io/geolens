from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from geoalchemy2.shape import to_shape
from sqlalchemy import and_, case, func, or_
from sqlalchemy.sql.elements import ColumnElement


# fix(#892): tolerance for recognizing the two-ring seam form. Both rings are
# written by our own code at the literal ±180 and round-trip through WKB as
# exact float64, so this only absorbs serialization noise -- it is deliberately
# far too tight to promote real-world coordinates that merely sit near the seam.
_SEAM_TOL = 1e-9


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= _SEAM_TOL


def _seam_split_bbox(shape: object) -> tuple[float, float, float, float] | None:
    """Recognize a two-ring antimeridian-split extent and return its spec bbox.

    fix(#892): a dataset that straddles the antimeridian is stored as a
    two-part MULTIPOLYGON -- one part running up to +180, the other starting at
    -180, over the same latitude band (see ``0030_records_spatial_extent_type``
    and the STAC import path in ``sources/stac_router.py``). Its planar bounds
    are -180..180, which is the whole globe and not the extent anyone meant.

    Returns ``(west, south, east, north)`` with ``west > east`` -- the RFC 7946
    §5.2 / STAC form -- for exactly that shape, and ``None`` for everything
    else, including a genuine two-part MULTIPOLYGON that merely happens to have
    parts on both sides of the world.

    Contract for future producers: the two halves must share one latitude band.
    A rollup that unions two crossing extents with *different* latitude spans
    produces two parts this function will not recognize, and the caller then
    gets the honest but over-broad -180..180 planar bounds. Fold to a common
    band (or build the two rings from an already-folded bbox via
    :func:`bbox_to_extent_wkt`) if the west > east form is wanted.
    """
    geoms = getattr(shape, "geoms", None)
    if geoms is None or len(geoms) != 2:
        return None
    first, second = (g.bounds for g in geoms)

    # Orient the pair: `left` is the part flush against +180, `right` the part
    # flush against -180. Both flags must hold, or this is not a seam split.
    if _near(first[2], 180.0) and _near(second[0], -180.0):
        left, right = first, second
    elif _near(second[2], 180.0) and _near(first[0], -180.0):
        left, right = second, first
    else:
        return None

    # The two halves must share a latitude band (otherwise the parts are
    # unrelated footprints that happen to touch the seam, not one crossing box)
    # and must not overlap in longitude -- west > east is the defining property
    # of the bbox we are about to emit, so refuse to invent it.
    if not (_near(left[1], right[1]) and _near(left[3], right[3])):
        return None
    if left[0] <= right[2]:
        return None

    return (left[0], left[1], right[2], left[3])


def extent_to_bbox(extent: object | None) -> list[float] | None:
    """Convert a geometry extent to an RFC 7946 §5.2 / STAC bbox.

    Returns ``[west, south, east, north]``. For an antimeridian-crossing extent
    stored in the two-ring form (see :func:`_seam_split_bbox`) that means
    ``west > east`` -- the spec-mandated encoding, and the reason this function
    exists rather than a bare ``.bounds`` read.

    Callers that need monotonic bounds (``west <= east``) because they feed a
    naive span subtraction, a planar WKT ring, or a viewer that cannot express
    a crossing box must use :func:`extent_to_span_bbox` instead.
    """
    if extent is None:
        return None
    try:
        shape = to_shape(extent)
        seam = _seam_split_bbox(shape)
        if seam is not None:
            return list(seam)
        return list(shape.bounds)
    except Exception:  # broad: input is user-supplied; any geoalchemy/shapely parse failure should fall back to None
        return None


def extent_to_span_bbox(extent: object | None) -> list[float] | None:
    """Convert a geometry extent to monotonic planar bounds (``west <= east``).

    fix(#892): the sibling of :func:`extent_to_bbox` for consumers that cannot
    accept a west > east pair -- ``maxx - minx`` span arithmetic, planar WKT
    polygon serialization, tile-source bounds. An antimeridian-crossing extent
    is honestly -180..180 in this form: over-broad, but never inverted.
    """
    if extent is None:
        return None
    try:
        return list(to_shape(extent).bounds)
    except Exception:  # broad: input is user-supplied; any geoalchemy/shapely parse failure should fall back to None
        return None


# fix(#887): the shared floor for any float comparison that gates a longitude
# shift, a re-frame, or a domain choice. Adding and subtracting 360, or
# reconstructing an edge from a serialized pixel offset, is not bit-exact, so
# values describing the SAME edge routinely disagree by ~1e-14 degrees. A bare
# `<` then lets that noise decide a branch that moves geometry by a third of a
# world. This batch hit it three times -- ``_narrower_domain`` in the rollup
# folds (#886/#928), the VRT frame chooser, and the VRT frame rewrite -- so the
# constant lives here and every such site imports it instead of inventing a bare
# comparison. 1e-9 degrees is ~0.1 mm: orders of magnitude above the noise,
# orders below any real distinction. ``_SEAM_TOL`` and ``_DOMAIN_MARGIN`` above
# are the same value applied locally.
LON_EPSILON_DEGREES = 1e-9


def extent_lon_span(extent: object | None) -> float | None:
    """Longitudinal width of an extent in degrees, honest across ±180.

    fix(#887): the companion to :func:`extent_to_span_bbox` for consumers that
    need the *width* rather than a monotonic pair. ``extent_to_span_bbox``
    reports -180..180 for a seam-crossing extent, so a caller that derives pixel
    resolution from ``maxx - minx`` reads a 10°-wide Pacific raster as 360° wide
    and understates its native resolution by 36x -- which cost the raster
    tile-source five zoom levels of maxzoom, so it stopped rendering as the user
    zoomed in. Read the RFC 7946 §5.2 ``west > east`` pair instead and close it
    the short way round.
    """
    bbox = extent_to_bbox(extent)
    if bbox is None:
        return None
    west, _, east, _ = bbox
    span = east - west
    return span + 360.0 if span < 0 else span


def _ring(x0: float, south: float, x1: float, north: float) -> str:
    return f"({x0} {south},{x1} {south},{x1} {north},{x0} {north},{x0} {south})"


def bbox_to_extent_wkt(west: float, south: float, east: float, north: float) -> str:
    """Build extent WKT for an RFC 7946 §5.2 bbox, splitting it at ±180.

    fix(#892): the producer side of :func:`extent_to_bbox`. When ``west > east``
    the bbox crosses the antimeridian, and the naive single ring
    ``POLYGON((w s, e s, e n, w n, w s))`` silently becomes the complement: for
    ``[170, -20, -170, -15]`` it is a valid rectangle spanning longitude
    -170..170, so it covers 1700 deg² of the wrong side of the world instead of
    the intended 100 and does not even contain the data it describes. Emit a
    two-part MULTIPOLYGON instead -- ``west..180`` and ``-180..east`` over the
    same latitude band -- which ``catalog.records.spatial_extent`` accepts as of
    migration ``0030_records_spatial_extent_type`` and which
    :func:`extent_to_bbox` reads back as the original ``west > east`` pair.
    """
    if west <= east:
        return f"POLYGON({_ring(west, south, east, north)})"

    # A crossing bbox whose west sits at +180 (or east at -180) has a zero-width
    # half; emitting it anyway would store an invalid ring, which is the class of
    # defect this helper exists to prevent. Keep only the halves with real width,
    # and fall back to the full -180..180 band when neither has any -- an extent
    # must never silently narrow to nothing.
    halves = [
        _ring(x0, south, x1, north)
        for x0, x1 in ((west, 180.0), (-180.0, east))
        if x0 < x1
    ]
    if not halves:
        return f"POLYGON({_ring(-180.0, south, 180.0, north)})"
    if len(halves) == 1:
        return f"POLYGON({halves[0]})"
    return f"MULTIPOLYGON({','.join(f'({h})' for h in halves)})"


# ---------------------------------------------------------------------------
# fix(#886): antimeridian-aware extent rollups
# ---------------------------------------------------------------------------

# The prime meridian, used to detect footprints that ST_ShiftLongitude would
# tear apart (see _shifted_longitude_geom).
_PRIME_MERIDIAN_WKT = "LINESTRING(0 -90,0 90)"

# fix(#886): how much narrower the shifted domain must be before it is preferred.
# Adding and subtracting 360 is not bit-exact, so the two domains disagree by up
# to ~3e-14 degrees on the SAME footprint: `(-4.761789777127049 + 360) - 360`
# comes back as `-4.761789777127035`, and the shifted span of an ordinary
# prime-meridian-crossing extent (Europe, Africa, the UK) measured
# 37.79687178320006 against a normal 37.796871783200075. Without a margin that
# noise wins the comparison and rewrites a non-crossing bbox with drifted edges.
# 1e-9 degrees is ~0.1 mm -- far above the noise, far below any real gain, and
# the same floor _SEAM_TOL already uses.
_DOMAIN_MARGIN = 1e-9


def wrap_longitude(lng: float) -> float:
    """Fold a longitude from the shifted domain back into ``[-180, 180]``.

    fix(#886): the rollup helpers below evaluate a second, ``+360``-shifted
    longitude domain, so their intermediate values run up to ~540. One
    subtraction is enough because a winning shifted range is always narrower
    than 360 degrees. ``180`` stays ``180`` rather than flipping to ``-180``.
    """
    if lng > 180.0:
        return lng - 360.0
    if lng < -180.0:
        return lng + 360.0
    return lng


def _shifted_longitude_geom(geom_col: ColumnElement) -> ColumnElement:
    """Move a footprint into the ``+360``-shifted longitude domain.

    fix(#886): ``ST_ShiftLongitude`` shifts *each vertex* with ``x < 0``, which
    is exactly right for the two-ring seam form (``150..180`` plus
    ``-180..-110`` becomes a contiguous ``150..250``) and exactly wrong for a
    footprint that crosses the prime meridian: Europe's ``-10..30`` becomes the
    vertex pair ``350, 30``, i.e. a claimed span of ``30..350``, and a rollup
    that then wins on span emits a bbox which *excludes the Europe dataset
    itself*. Verified against PostGIS: a Europe/UK/Africa record plus a Fiji
    pair yields ``covers-all-inputs=False`` with a bare ``ST_ShiftLongitude``.

    So shift whole footprints that reach the prime meridian, and only let
    ``ST_ShiftLongitude`` work per-vertex on the ones that do not. Translating
    preserves a footprint's own span, so it can never invent a narrower range
    than the data has; the worst it does is leave the shifted domain wide
    enough to lose, which falls back to the normal domain.

    Requires a 4326 (degree) geometry column.
    """
    return case(
        (
            and_(
                func.ST_XMin(geom_col) < 0,
                func.ST_Intersects(
                    geom_col,
                    func.ST_SetSRID(func.ST_GeomFromText(_PRIME_MERIDIAN_WKT), 4326),
                ),
            ),
            func.ST_Translate(geom_col, 360, 0),
        ),
        else_=func.ST_ShiftLongitude(geom_col),
    )


def rollup_bbox_columns(geom_col: ColumnElement) -> list[ColumnElement]:
    """Six aggregate columns describing an extent rollup in two longitude domains.

    fix(#886): a bare ``ST_Extent`` / ``ST_Envelope(ST_Collect(...))`` fold over
    records on both sides of the antimeridian manufactures a global bbox --- two
    ordinary Fiji datasets at lon 179 and -179 roll up to ``-180..180``. These
    columns aggregate the same rows twice, once as stored and once in the
    ``+360``-shifted domain, so :func:`rollup_bbox` can keep whichever range is
    narrower.

    Returns ``[xmin, ymin, xmax, ymax, shifted_xmin, shifted_xmax]``; splat it
    as the leading columns of a ``select()`` and hand the matching row slice to
    :func:`rollup_bbox` or :func:`rollup_span_bbox`. Latitudes come from the
    unshifted extent because shifting longitudes cannot change them.
    """
    normal = func.ST_Extent(geom_col)
    shifted = func.ST_Extent(_shifted_longitude_geom(geom_col))
    return [
        func.ST_XMin(normal),
        func.ST_YMin(normal),
        func.ST_XMax(normal),
        func.ST_YMax(normal),
        func.ST_XMin(shifted),
        func.ST_XMax(shifted),
    ]


def _narrower_domain(
    xmin: float, ymin: float, xmax: float, ymax: float, sxmin: float, sxmax: float
) -> list[float]:
    """Keep whichever longitude domain spans less, as an RFC 7946 §5.2 bbox.

    A tie --- or anything inside ``_DOMAIN_MARGIN`` of one --- goes to the
    unshifted domain, so nothing that does not actually cross the seam is ever
    re-expressed, and an ordinary catalog's bbox stays byte-identical.

    Documented ceiling: this is not the true minimal covering range, which
    needs the largest gap anywhere on the circle rather than at one of two cut
    points (-180 and 0). Footprints spanning ``-170..-160``, ``-20..-15``,
    ``20..25`` and ``160..165`` have their largest gap at ``-160..-20`` and
    could be covered in 220 degrees; both cut points fall inside data, so this
    returns 325 (see ``test_documented_ceiling_is_covering_but_not_minimal``).
    Always a valid covering range, sometimes broader than optimal --- never
    inverted, never partial.

    Second, smaller caveat: a winning shifted edge has been through a ``+360``
    then ``-360`` round-trip, which is not bit-exact for an arbitrary mantissa,
    so that edge can land up to ulp(512)/2 --- about 6e-14 degrees, 6
    nanometres --- inside the true union. Not worth epsilon machinery: the
    stored geometries are float64 too, so their own edges are fuzzy at the same
    scale, and no consumer does an exact containment test against a rollup.
    Widening the edge unconditionally would be the only sound correction and it
    would put that noise into every crossing bbox, including the exact ones.
    """
    if sxmax - sxmin < (xmax - xmin) - _DOMAIN_MARGIN:
        return [wrap_longitude(sxmin), ymin, wrap_longitude(sxmax), ymax]
    return [xmin, ymin, xmax, ymax]


def _rollup_floats(values: Sequence[object]) -> list[float] | None:
    """Coerce a :func:`rollup_bbox_columns` row slice to six floats, or None."""
    if values is None or len(values) < 6:
        return None
    if any(v is None for v in values[:6]):
        return None
    try:
        return [float(v) for v in values[:6]]  # type: ignore[arg-type]
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def rollup_bbox(values: Sequence[object]) -> list[float] | None:
    """Fold a :func:`rollup_bbox_columns` row into an RFC 7946 §5.2 bbox.

    Returns ``[west, south, east, north]`` with ``west > east`` when the rollup
    honestly crosses the antimeridian --- the STAC / OGC / GeoJSON encoding.
    Consumers that cannot express a crossing box want
    :func:`rollup_span_bbox`.
    """
    nums = _rollup_floats(values)
    return None if nums is None else _narrower_domain(*nums)


def rollup_span_bbox(values: Sequence[object]) -> list[float] | None:
    """Fold a :func:`rollup_bbox_columns` row into monotonic bounds.

    fix(#886): the sibling of :func:`rollup_bbox` for consumers that feed
    ``maxx - minx`` span arithmetic or a viewer with no antimeridian handling.
    A crossing rollup is honestly ``-180..180`` here: over-broad, never
    inverted.
    """
    nums = _rollup_floats(values)
    if nums is None:
        return None
    west, south, east, north = _narrower_domain(*nums)
    if west > east:
        return [-180.0, south, 180.0, north]
    return [west, south, east, north]


def merge_bboxes(bboxes: Iterable[Sequence[float] | None]) -> list[float] | None:
    """Merge RFC 7946 §5.2 bboxes on the circle, preferring the narrower domain.

    fix(#886): the Python twin of :func:`rollup_bbox`, for folds that already
    hold per-record bboxes (from :func:`extent_to_bbox`) instead of a SQL
    aggregate. Inputs may themselves be ``west > east``; so may the result.
    """
    xmin = ymin = sxmin = float("inf")
    xmax = ymax = sxmax = float("-inf")
    seen = False

    for bbox in bboxes:
        if bbox is None or len(bbox) < 4:
            continue
        west, south, east, north = (float(v) for v in bbox[:4])
        seen = True
        ymin, ymax = min(ymin, south), max(ymax, north)
        if west > east:
            # Crossing: the unshifted domain can only say "the whole world",
            # while the shifted domain holds the real, contiguous range.
            xmin, xmax = min(xmin, -180.0), max(xmax, 180.0)
            shifted = (west, east + 360.0)
        else:
            xmin, xmax = min(xmin, west), max(xmax, east)
            # Shift the whole interval, mirroring _shifted_longitude_geom:
            # a footprint reaching the prime meridian must move as one piece.
            shifted = (west + 360.0, east + 360.0) if west < 0 else (west, east)
        sxmin, sxmax = min(sxmin, shifted[0]), max(sxmax, shifted[1])

    if not seen:
        return None
    return _narrower_domain(xmin, ymin, xmax, ymax, sxmin, sxmax)


def make_bbox_filter(
    geom_col: ColumnElement, bbox: list[float], *, predicate: str = "intersects"
):
    """Build a SQLAlchemy spatial filter from a bbox, handling antimeridian crossing.

    When ``bbox[0] > bbox[2]`` (minx > maxx), the bbox crosses the antimeridian
    and is split into two envelopes ORed together.

    Args:
        geom_col: SQLAlchemy column with geometry (e.g. ``Record.spatial_extent``).
        bbox: ``[west, south, east, north]`` floats.
        predicate: ``"intersects"`` or ``"within"``.

    Returns:
        A SQLAlchemy filter clause.
    """
    spatial_fn = func.ST_Within if predicate == "within" else func.ST_Intersects
    west, south, east, north = bbox

    if west > east:
        # Antimeridian-crossing: split into [west..180] and [-180..east]
        env_left = func.ST_MakeEnvelope(west, south, 180, north, 4326)
        env_right = func.ST_MakeEnvelope(-180, south, east, north, 4326)
        return or_(
            and_(geom_col.op("&&")(env_left), spatial_fn(geom_col, env_left)),
            and_(geom_col.op("&&")(env_right), spatial_fn(geom_col, env_right)),
        )
    else:
        envelope = func.ST_MakeEnvelope(west, south, east, north, 4326)
        return and_(geom_col.op("&&")(envelope), spatial_fn(geom_col, envelope))


def wkt_is_geographic(crs_wkt: str | None) -> bool | None:
    """Classify a CRS WKT as geographic (lon/lat axes) or projected.

    fix(#569): the frontend rendered geographic-CRS pixel resolutions as
    meters ("60 arc-second" ETOPO showed "2 cm"). The API has no proj
    library, but the stored WKT's root/inner keyword is enough: a projected
    CRS contains PROJCRS (WKT2) / PROJCS (WKT1) — checked FIRST because
    WKT1 nests a GEOGCS inside every PROJCS — otherwise a GEOGCRS/GEOGCS
    keyword (including inside a COMPOUNDCRS like EPSG:9518) means
    geographic. Engineering/local/unknown CRSs return None.

    fix(#939): this is a keyword test only — it does NOT check the angular
    unit, so a grads-based GEOGCS (the Paris-meridian family, e.g. EPSG:4807)
    also returns True. When "geographic" needs to mean "resolutions are in
    degrees", pair this with :func:`wkt_has_degree_unit`. The codebase's
    other unit tests are catalogued in #939 — don't invent a fifth.

    fix(#939 codex r1): quoted strings are blanked before the keyword scan,
    so a CRS *name* or remark that merely mentions PROJCS/GEOGCS (e.g.
    ``GEOGCRS["adjusted from PROJCS ..."]``) cannot misclassify the WKT.
    """
    if not crs_wkt:
        return None
    # Blank quoted content: WKT strings cannot contain the quote character
    # itself (WKT2 escapes it by doubling, which still terminates each pair),
    # so this never eats a structural keyword.
    head = re.sub(r'"[^"]*"', '""', crs_wkt[:2000]).upper()
    if "PROJCRS" in head or "PROJCS" in head:
        return False
    if "GEOGCRS" in head or "GEOGCS" in head:
        return True
    return None


# fix(#939): covers WKT1 (`UNIT["degree"`) and WKT2 (`ANGLEUNIT["degree"`) in
# one pattern, since the WKT2 spelling contains the WKT1 substring. Mirrors
# _DEGREE_UNIT_SRTEXT_RE in processing/ingest/metadata.py, which does the same
# test in SQL against spatial_ref_sys.srtext.
_WKT_DEGREE_UNIT_RE = re.compile(r'UNIT\["degree', re.IGNORECASE)


def wkt_has_degree_unit(crs_wkt: str | None) -> bool | None:
    """Whether a CRS WKT declares a degree angular unit anywhere.

    fix(#939): companion to :func:`wkt_is_geographic`, which is keyword-only
    and admits grads CRSs. Only meaningful for a WKT already classified as
    geographic — every projected WKT1 nests a GEOGCS whose UNIT is degrees,
    so call :func:`wkt_is_geographic` first. Returns None when no WKT is
    stored.
    """
    if not crs_wkt:
        return None
    return _WKT_DEGREE_UNIT_RE.search(crs_wkt) is not None
