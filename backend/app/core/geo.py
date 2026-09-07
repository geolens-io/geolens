from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import TYPE_CHECKING

from geoalchemy2.shape import to_shape
from sqlalchemy import and_, case, column, func, or_, select
from sqlalchemy import table as sql_table
from sqlalchemy.sql.elements import ColumnElement

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# fix(#892): rings are written by our own code at exact ±180 and round-trip
# through WKB as exact float64, so this tolerance only absorbs serialization
# noise -- deliberately too tight to promote real coordinates near the seam.
_SEAM_TOL = 1e-9


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= _SEAM_TOL


def _seam_split_bbox(shape: object) -> tuple[float, float, float, float] | None:
    """Recognize a two-ring antimeridian-split extent (fix(#892)) and return its
    spec bbox as ``(west, south, east, north)`` with ``west > east``, else None.

    The two parts must share one latitude band; a rollup of crossing extents
    with different bands falls back to the honest, over-broad -180..180 bounds.
    """
    geoms = getattr(shape, "geoms", None)
    if geoms is None or len(geoms) != 2:
        return None
    first, second = (g.bounds for g in geoms)

    # `left` is flush against +180, `right` against -180; else not a seam split.
    if _near(first[2], 180.0) and _near(second[0], -180.0):
        left, right = first, second
    elif _near(second[2], 180.0) and _near(first[0], -180.0):
        left, right = second, first
    else:
        return None

    # Halves must share a latitude band and not overlap in longitude -- the
    # west > east form below is refused unless both hold.
    if not (_near(left[1], right[1]) and _near(left[3], right[3])):
        return None
    if left[0] <= right[2]:
        return None

    return (left[0], left[1], right[2], left[3])


def extent_to_bbox(extent: object | None) -> list[float] | None:
    """Convert a geometry extent to an RFC 7946 §5.2 / STAC bbox.

    Returns ``[west, south, east, north]``; a two-ring antimeridian-crossing
    extent (see :func:`_seam_split_bbox`) yields ``west > east``. Callers
    needing monotonic bounds must use :func:`extent_to_span_bbox` instead.
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

    fix(#892): sibling of :func:`extent_to_bbox` for span arithmetic, planar
    WKT, and tile bounds. A crossing extent reads -180..180: over-broad, never
    inverted.
    """
    if extent is None:
        return None
    try:
        return list(to_shape(extent).bounds)
    except Exception:  # broad: input is user-supplied; any geoalchemy/shapely parse failure should fall back to None
        return None


# fix(#887): shared floor for any float comparison gating a longitude shift,
# re-frame, or domain choice. +/-360 round-trips disagree by ~1e-14 degrees on
# the same edge, and a bare `<` lets that noise move geometry by a third of a
# world (hit in ``_narrower_domain`` #886/#928, the VRT frame chooser/rewrite).
LON_EPSILON_DEGREES = 1e-9


def extent_lon_span(extent: object | None) -> float | None:
    """Longitudinal width of an extent in degrees, honest across ±180.

    fix(#887): companion to :func:`extent_to_span_bbox`, which reports the
    over-broad -180..180 for a crossing extent -- ``maxx - minx`` on that then
    understated a 10°-wide Pacific raster's resolution by 36x and cost it five
    zoom levels. Reads the ``west > east`` pair instead and closes it short way.
    """
    bbox = extent_to_bbox(extent)
    if bbox is None:
        return None
    west, _, east, _ = bbox
    span = east - west
    return span + 360.0 if span < 0 else span


def _ring(x0: float, south: float, x1: float, north: float) -> str:
    return f"({x0} {south},{x1} {south},{x1} {north},{x0} {north},{x0} {south})"


# fix(#944): 1e-9 pad matches the ``ST_Expand`` calls on POINT/LINESTRING
# extents in ``processing/ingest/metadata_extent.py`` and
# ``catalog/features/service.py``, so a padded extent here is the same size.
_DEGENERATE_SPAN = 1e-12
_DEGENERATE_PAD = 1e-9


def _pad_degenerate(low: float, high: float, limit: float) -> tuple[float, float]:
    """Widen a zero-span axis to a sliver, without leaving ``±limit``.

    An axis on its domain edge (antimeridian, pole) has no room on one side,
    so the sliver grows inward there instead. Non-degenerate spans pass
    through untouched.

    Callers must reject a non-finite bbox first: NaN passes the span test and
    ``max``/``min`` would quietly substitute the domain edge.
    """
    if high - low >= _DEGENERATE_SPAN:
        return low, high
    return max(-limit, low - _DEGENERATE_PAD), min(limit, high + _DEGENERATE_PAD)


def bbox_to_extent_wkt(west: float, south: float, east: float, north: float) -> str:
    """Build extent WKT for an RFC 7946 §5.2 bbox, splitting it at ±180.

    fix(#892): producer side of :func:`extent_to_bbox`. A naive single ring
    silently becomes the complement when ``west > east`` -- ``[170,-20,-170,-15]``
    would emit a valid 1700 deg² rectangle covering the wrong side of the
    world instead of the intended 100. Emits a two-part MULTIPOLYGON instead
    (``west..180`` plus ``-180..east``), which :func:`extent_to_bbox` reads
    back as the original pair.

    fix(#944): a degenerate axis (``south == north``, or zero-width) is padded
    to a sliver first -- else it yields collinear vertices, not a valid
    polygon. Padding matches the ``ST_Expand`` producers rather than
    rejecting, so data the schema stores happily still ingests.

    fix(#944): a non-finite coordinate is refused outright, else NaN
    passes every test below and silently records an almost-global extent for
    a malformed ``StacImportItem.bbox``. STAC import isolates each item in a
    savepoint, so raising costs the batch nothing.
    """
    if not all(math.isfinite(v) for v in (west, south, east, north)):
        raise ValueError(f"bbox must be finite, got ({west}, {south}, {east}, {north})")
    south, north = _pad_degenerate(south, north, 90.0)
    if west <= east:
        west, east = _pad_degenerate(west, east, 180.0)
        return f"POLYGON({_ring(west, south, east, north)})"

    # fix(#934): drop a zero-width half (west at +180, or east at
    # -180) -- right for a continuous rectangle caller (raster/STAC bbox),
    # which loses nothing at that half. Wrong for discrete stored features, so
    # seam_extent_wkt_for_table pads the seam edge before calling here.
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


# fix(#886): antimeridian-aware extent rollups.

# Used to detect footprints ST_ShiftLongitude would tear apart (see
# _shifted_longitude_geom).
_PRIME_MERIDIAN_WKT = "LINESTRING(0 -90,0 90)"

# fix(#886): margin before the shifted domain is preferred. +/-360 round-trips
# disagree by ~3e-14 degrees on the same footprint, and without a margin that
# noise wins the comparison and rewrites a non-crossing bbox with drifted
# edges. Same floor as _SEAM_TOL.
_DOMAIN_MARGIN = 1e-9


def wrap_longitude(lng: float) -> float:
    """Fold a longitude from the shifted domain back into ``[-180, 180]``.

    fix(#886): intermediate values from the ``+360``-shifted domain run up to
    ~540; one subtraction suffices since a winning shifted range is always
    narrower than 360 degrees. ``180`` stays ``180``, never flips to ``-180``.
    """
    if lng > 180.0:
        return lng - 360.0
    if lng < -180.0:
        return lng + 360.0
    return lng


def _shifted_longitude_geom(geom_col: ColumnElement) -> ColumnElement:
    """Move a footprint into the ``+360``-shifted longitude domain.

    fix(#886): ``ST_ShiftLongitude`` shifts each vertex with ``x < 0``, right
    for the two-ring seam form but wrong for a prime-meridian-crossing
    footprint: Europe's ``-10..30`` becomes vertices ``350, 30``, claiming
    span ``30..350`` and excluding Europe from a rollup that wins on that
    span (verified false-covering in PostGIS). So whole footprints reaching
    the prime meridian are translated instead; that preserves their own span,
    so the shifted domain can only lose the comparison, never invent a
    narrower range than the data has.

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

    fix(#886): a bare ``ST_Extent`` fold over records on both sides of the
    antimeridian manufactures a global bbox -- two Fiji datasets at lon 179
    and -179 roll up to ``-180..180``. These columns aggregate the rows both
    as stored and in the ``+360``-shifted domain, so :func:`rollup_bbox` can
    keep whichever is narrower.

    Returns ``[xmin, ymin, xmax, ymax, shifted_xmin, shifted_xmax]``; splat as
    the leading columns of a ``select()`` for :func:`rollup_bbox` /
    :func:`rollup_span_bbox`. Latitudes come from the unshifted extent since
    shifting longitude cannot change them.
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

    A tie, or anything inside ``_DOMAIN_MARGIN``, goes to the unshifted
    domain, so an ordinary catalog's bbox stays byte-identical.

    Documented ceiling, not the true minimal covering range: only the two cut
    points (-180, 0) are tried, so a footprint whose largest gap falls
    elsewhere (e.g. four bands spanning -170..165 with the real gap at
    -160..-20) returns a valid but non-minimal cover (see
    ``test_documented_ceiling_is_covering_but_not_minimal``). Always covering,
    never inverted or partial.

    A winning shifted edge can also land up to ~6e-14 degrees inside the true
    union from the ``+360``/``-360`` round-trip -- not worth correcting, since
    stored float64 geometry edges are fuzzy at the same scale already.
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

    fix(#886): sibling of :func:`rollup_bbox` for span arithmetic or a viewer
    with no antimeridian handling. A crossing rollup reads -180..180: over-
    broad, never inverted.
    """
    nums = _rollup_floats(values)
    if nums is None:
        return None
    west, south, east, north = _narrower_domain(*nums)
    if west > east:
        return [-180.0, south, 180.0, north]
    return [west, south, east, north]


async def seam_extent_wkt_for_table(
    session: AsyncSession,
    table_name: str,
    *,
    schema: str | None = None,
    geom_column: str = "geom_4326",
) -> str | None:
    """Two-ring extent WKT for a data table that honestly crosses ±180, else None.

    fix(#934): producer-side twin of :func:`rollup_bbox` for the per-dataset
    extent writers. A naive ``ST_Extent`` over a Pacific-crossing table reads
    near-global (150..250 shifted folds to -170..170, 340 degrees for a
    100-degree footprint); this aggregates both longitude domains via
    :func:`rollup_bbox_columns` and returns the honest two-ring MULTIPOLYGON
    when the shifted domain wins. Returns None for a non-crossing/empty table.

    ``table_name``/``schema`` go through SQLAlchemy identifier quoting, never
    string-interpolated into SQL (fix(#934)); callers still pass
    validated names (``_validate_table_name`` / ``Dataset.table_name``).
    """
    tbl = sql_table(table_name, column(geom_column), schema=schema)
    stmt = select(*rollup_bbox_columns(tbl.columns[geom_column])).select_from(tbl)
    row = (await session.execute(stmt)).first()
    values = _rollup_floats(row) if row is not None else None
    if values is None:
        return None
    bbox = _narrower_domain(*values)
    west, south, east, north = bbox
    crossing = west > east
    # fix(#934): mirror of the +180 seam edge. Features at -180/170
    # can win the shifted fold as apparently non-crossing [170..180], but the
    # feature is STORED at planar -180, uncovered by that polygon. Re-express
    # as crossing with east at -180 so bbox_to_extent_wkt pads that lobe.
    if not crossing and east >= 180.0 and (west != values[0] or east != values[2]):
        east = -180.0
        crossing = True
    if not crossing:
        return None
    # fix(#934): a fold with west at +180 or east at -180 has a
    # zero-width half; bbox_to_extent_wkt drops it, right for a continuous
    # rectangle but wrong here, since that half is exactly where the discrete
    # row is stored. Widen the seam edge to a sub-mm sliver (same 1e-9 as the
    # ST_Expand degenerate paths) so both planar reps of the seam stay covered.
    if west >= 180.0:
        west = 180.0 - 1e-9
    if east <= -180.0:
        east = -180.0 + 1e-9
    return bbox_to_extent_wkt(west, south, east, north)


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


# fix(#961): had a twin in processing/raster/vrt.py; both sites now go
# through `crs_has_degree_unit` below, so there is one implementation.
_RADIANS_PER_DEGREE = math.pi / 180.0


@lru_cache(maxsize=256)
def _parse_crs(crs_wkt: str) -> object | None:
    """Parse stored CRS WKT with PROJ, or None when PROJ will not accept it.

    fix(#939): a regex scan of WKT structure cannot reliably answer "is this
    geographic" or "what are its axis units" -- WKT is a nested grammar, so a
    flat scan can't tell which subtree a unit belongs to (PRIMEM, MERIDIAN,
    BEARING, conversion PARAMETERs all carry angular units). Ask PROJ instead,
    which reads the actual tree and handles a BoundCRS's SOURCE units or a 3D
    geographic CRS's axis unit correctly.

    Import is function-scope because rasterio pulls in GDAL and ``core`` is
    the lowest layer. Results are cached: callers run this per row over a
    small set of distinct CRSs.
    """
    try:
        from rasterio.crs import CRS

        return CRS.from_wkt(crs_wkt)
    except Exception:  # broad: crs_wkt is whatever GDAL wrote at ingest; any parse failure means "PROJ cannot answer", which is a fallback, not an error
        return None


def wkt_is_geographic(crs_wkt: str | None) -> bool | None:
    """Classify a CRS WKT as geographic (lon/lat axes) or projected.

    fix(#569): the frontend rendered geographic-CRS pixel resolutions as
    meters ("60 arc-second" ETOPO showed "2 cm"). Unclassifiable/engineering/
    local/unknown CRSs return None.

    fix(#939): PROJ decides whenever it can parse the WKT. The keyword sniff
    below is the fallback for WKT PROJ rejects (abbreviated/truncated/legacy).
    It checks PROJCRS/PROJCS first since WKT1 nests a GEOGCS inside every
    PROJCS, and blanks quoted content first so a CRS name mentioning PROJCS
    can't misclassify.

    This is a CLASS test, not a units test: a grads GEOGCS (e.g. EPSG:4807) is
    geographic without its resolutions being degrees. Pair with
    :func:`wkt_has_degree_unit` when "geographic" must mean "in degrees".
    """
    # isinstance not truthiness: callers hand this RasterAsset.crs_wkt or test
    # mocks; a non-string is an unknown CRS, not a crash.
    if not isinstance(crs_wkt, str) or not crs_wkt:
        return None
    crs = _parse_crs(crs_wkt)
    if crs is not None:
        try:
            if crs.is_geographic:
                return True
            if crs.is_projected:
                return False
        except Exception:  # broad: exotic CRSs raise from PROJ rather than answering; fall through to the sniff
            pass
        # Parsed but neither geographic nor projected: geocentric/engineering.
    # Blank quoted content BEFORE truncating: a pathologically long quoted
    # name could otherwise push a real keyword past the truncation point.
    head = re.sub(r'"[^"]*"', '""', crs_wkt)[:2000].upper()
    if "PROJCRS" in head or "PROJCS" in head:
        return False
    if "GEOGCRS" in head or "GEOGCS" in head:
        return True
    if "GEODCRS" in head or "GEODETICCRS" in head:
        if "ELLIPSOIDAL" in head:
            return True
        if "CARTESIAN" in head:
            return False
        return None
    return None


def crs_has_degree_unit(crs: object | None) -> bool | None:
    """Whether a PARSED CRS's coordinate axes are measured in degrees.

    fix(#961): the one implementation of the radians-per-unit test.
    :func:`wkt_has_degree_unit` is this plus a WKT parse; ``_is_degree_based``
    (``processing/raster/vrt.py``) is this plus an ``is_geographic``
    precondition -- it takes a CRS object because ``vrt.py`` holds a live
    ``rasterio.crs.CRS`` and must not round-trip through WKT to reach here.

    ``rel_tol`` is correct: this compares two fixed physical constants of the
    same tiny magnitude (0.01745 rad/degree vs whatever PROJ reports), and the
    nearest wrong answer, grads at 0.01571, is 10% away.

    Returns None when there is no CRS or PROJ cannot report a unit factor;
    callers read that as "unknown" and decide for themselves.
    """
    if crs is None:
        return None
    try:
        _, radians_per_unit = crs.units_factor
    except Exception:  # broad: units_factor raises CRSError on exotic/!undefined CRSs, which are exactly the ones we cannot answer for
        return None
    return math.isclose(radians_per_unit, _RADIANS_PER_DEGREE, rel_tol=1e-9)


def wkt_has_degree_unit(crs_wkt: str | None) -> bool | None:
    """Whether a CRS WKT's coordinate axes are measured in degrees.

    fix(#939): companion to :func:`wkt_is_geographic`, a class test that
    admits grads CRSs -- only meaningful for a WKT already classed geographic.
    Delegates to :func:`crs_has_degree_unit` (fix(#961)), so reading PROJ's
    ``units_factor`` rather than the unit's name means a custom spelling like
    ``UNIT["arc-degree",0.01745...]`` still reads as degrees.

    Returns None when there is no WKT or PROJ cannot parse it. Callers must
    treat None as "unknown", not "not degrees": ``processing/tiles/router.py``
    tests ``is not False`` so an unparseable CRS keeps the historical degrees
    assumption instead of silently dropping the resolution.
    """
    if not isinstance(crs_wkt, str) or not crs_wkt:
        return None
    return crs_has_degree_unit(_parse_crs(crs_wkt))


def crs_metres_per_unit(crs: object | None) -> float | None:
    """Metres per linear unit of a PROJECTED CRS, or None when that is not a
    question with an answer.

    fix(#1375): STAC's ``gsd`` is in metres, but a stored resolution is
    in whatever unit its CRS measures. ``units_factor`` reports ``('metre',
    1.0)`` for UTM/Web Mercator and ``('US survey foot', 0.3048006...)`` for
    state-plane systems.

    Returns None for a GEOGRAPHIC CRS on purpose: ``units_factor`` reports
    RADIANS per unit there, and an angular resolution has no fixed length (a
    degree of longitude is 111 km at the equator, 0 at the pole) without a
    latitude this function isn't given. Callers must omit the value rather
    than publish it unconverted -- see ``RasterAsset.to_stac_properties``.
    """
    if crs is None:
        return None
    try:
        if not crs.is_projected:
            return None
        _, metres_per_unit = crs.units_factor
    except Exception:  # broad: exotic CRSs raise from PROJ rather than answering, and "no answer" is exactly the None case
        return None
    if not metres_per_unit or metres_per_unit <= 0:
        return None
    return float(metres_per_unit)


def wkt_metres_per_unit(crs_wkt: str | None) -> float | None:
    """:func:`crs_metres_per_unit` plus the WKT parse.

    Same shape as :func:`wkt_has_degree_unit` over :func:`crs_has_degree_unit`.
    None covers every uncertainty: no WKT, an unparseable one, or a CRS whose
    units PROJ won't report.
    """
    if not isinstance(crs_wkt, str) or not crs_wkt:
        return None
    return crs_metres_per_unit(_parse_crs(crs_wkt))


def pixel_size_from_affine(
    a: float, b: float, d: float, e: float
) -> tuple[float, float]:
    """Per-pixel ground distances along a raster's OWN axes, from its affine.

    fix(#1375): not ``abs(a)``/``abs(e)``. Those are the pixel vectors'
    COMPONENTS on the world axes, which equal the pixel sizes only when the
    raster is axis-aligned. A geotransform maps pixel (col, row) to world
    ``x = a*col + b*row + c``, ``y = d*col + e*row + f``, so one step along the
    column axis moves the world point by the vector ``(a, d)`` and one step
    along the row axis by ``(b, e)``. The LENGTHS of those two vectors are the
    resolutions; ``a`` and ``e`` alone are their projections onto x and y.

    Rotate a 10 m-pixel raster by 30° and the affine reads ``a=8.66, d=5.0``:
    ``abs(a)`` reports 8.66 m, a 13% understatement that reaches the UI and
    STAC's ``gsd``. Confirmed against the distance between adjacent pixel
    centres, which is 10.0.

    For an axis-aligned raster ``b`` and ``d`` are zero and this returns
    exactly ``abs(a)``/``abs(e)``. Both raster ingest paths call this so a
    rotated scene reports the same resolution whether uploaded or imported
    from a remote catalog.
    """
    return math.hypot(a, d), math.hypot(b, e)
