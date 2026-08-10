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


# fix(#944): a span this narrow is degenerate, and the sliver it is widened to.
# Both come from :func:`seam_extent_wkt_for_table`, which hit the same problem
# one caller upstream first; 1e-9 is also the magnitude the ``ST_Expand`` calls
# in ``processing/ingest/metadata.py`` and ``catalog/features/service.py`` use
# on POINT/LINESTRING extents, so a padded extent produced here is
# indistinguishable in size from one produced by ingest.
_DEGENERATE_SPAN = 1e-12
_DEGENERATE_PAD = 1e-9


def _pad_degenerate(low: float, high: float, limit: float) -> tuple[float, float]:
    """Widen a zero-span axis to a sliver, without leaving ``±limit``.

    Padding outward is what the ``ST_Expand`` callers do, but an axis sitting
    exactly on its domain edge (a point on the antimeridian, or at a pole) has
    no room on one side, so the pad is clamped and the sliver grows inward
    instead. Non-degenerate spans are returned untouched, so a genuine bbox
    never moves by an epsilon.

    Callers must reject a non-finite bbox first: NaN compares False against
    everything, so it would fall past the span test into the clamp and
    ``max``/``min`` would quietly substitute the domain edge.
    """
    if high - low >= _DEGENERATE_SPAN:
        return low, high
    return max(-limit, low - _DEGENERATE_PAD), min(limit, high + _DEGENERATE_PAD)


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

    fix(#944): a degenerate axis is padded to a sliver first. A bbox with
    ``south == north`` (a single point, or a run of points on one parallel)
    otherwise yields four collinear vertices -- zero area, and not a valid
    polygon -- and the same applies to a zero-width non-crossing bbox. Only the
    width case was guarded before, and only on the crossing branch. Padding
    rather than rejecting follows the producers, which already ``ST_Expand``
    degenerate POINT/LINESTRING extents by the same 1e-9; rejecting would turn
    a working ingest into a failed one for data the schema stores happily.

    fix(#944 codex r1): a non-finite coordinate is refused outright. NaN
    compares False against every test below, so it reaches the clamp and
    ``max``/``min`` substitute the domain edge; a NaN longitude also fails
    ``west <= east``, then loses both crossing halves to the ``x0 < x1``
    filter and lands on the full -180..180 fallback. Either way a malformed
    bbox (``StacImportItem.bbox`` is an unconstrained float list) would be
    silently recorded as an almost-global extent. "An extent must never
    silently narrow to nothing" has a mirror, and this is it. STAC import
    isolates each item in a savepoint and records the failure per item, so
    raising costs the batch nothing.
    """
    if not all(math.isfinite(v) for v in (west, south, east, north)):
        raise ValueError(f"bbox must be finite, got ({west}, {south}, {east}, {north})")
    south, north = _pad_degenerate(south, north, 90.0)
    if west <= east:
        west, east = _pad_degenerate(west, east, 180.0)
        return f"POLYGON({_ring(west, south, east, north)})"

    # A crossing bbox whose west sits at +180 (or east at -180) has a zero-width
    # half; emitting it anyway would store an invalid ring, which is the class of
    # defect this helper exists to prevent. Keep only the halves with real width,
    # and fall back to the full -180..180 band when neither has any -- an extent
    # must never silently narrow to nothing.
    #
    # fix(#934 codex r2): dropping the zero-width half is right for every caller
    # that passes a CONTINUOUS rectangle -- a raster footprint
    # (``processing/raster/cog.py``) or a STAC item bbox
    # (``catalog/sources/stac_router.py``). A 180..190 raster folds to the single
    # -180..-170 ring and covers every pixel it has; there is nothing at the
    # zero-width half to lose. It is NOT right for a fold over DISCRETE stored
    # features, where a row can sit at the literal planar +180 that the -180 ring
    # does not cover. That case is handled where it belongs, in
    # :func:`seam_extent_wkt_for_table`, which pads the seam edge to a sliver
    # before calling here -- so a degenerate half never reaches this drop.
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


async def seam_extent_wkt_for_table(
    session: AsyncSession,
    table_name: str,
    *,
    schema: str | None = None,
    geom_column: str = "geom_4326",
) -> str | None:
    """Two-ring extent WKT for a data table that honestly crosses ±180, else None.

    fix(#934): the producer-side twin of :func:`rollup_bbox` for the per-dataset
    extent writers (``ingest/metadata.py``, ``catalog/features/service.py``). A
    naive ``ST_Extent`` over a Pacific-crossing table reads near-global
    (150..250 shifted to both sides folds to -170..170, a 340-degree bbox for a
    100-degree footprint); this aggregates the same rows in both longitude
    domains via :func:`rollup_bbox_columns` and, when the shifted domain wins,
    returns the honest two-ring MULTIPOLYGON from :func:`bbox_to_extent_wkt`.

    Returns None for a non-crossing (or empty) table so callers keep their
    existing single-polygon path byte-identical — including the degenerate
    POINT/LINESTRING padding, which can never apply to a crossing extent.

    ``table_name`` / ``schema`` are rendered through SQLAlchemy's identifier
    quoting (``sqlalchemy.table``), never string-interpolated into SQL
    (fix(#934 codeql)); callers still pass names they have validated
    (``_validate_table_name`` / catalog-owned ``Dataset.table_name``).
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
    # fix(#934 codex r3): the mirror of the +180 seam edge. For features at
    # -180 and 170, ST_ShiftLongitude maps the negative seam point to +180,
    # so the winning shifted fold reads as the apparently non-crossing
    # [170..180] — but the feature is STORED at planar -180, which that
    # polygon does not cover. When the shifted domain won (the fold differs
    # from the naive planar bounds) and its east lands on +180, re-express
    # it as the crossing form with east at -180; bbox_to_extent_wkt then
    # pads the -180 lobe to a sliver covering the stored representation.
    if not crossing and east >= 180.0 and (west != values[0] or east != values[2]):
        east = -180.0
        crossing = True
    if not crossing:
        return None
    # fix(#944): the zero-height pad this function used to carry moved into
    # bbox_to_extent_wkt, which now pads both axes for every caller. Keeping a
    # copy here would not double-pad (this one widens the span past the 1e-12
    # trigger, so the helper's would never fire) — it would be worse, leaving
    # the helper's version dead on this path and two copies of one convention
    # to keep in sync.
    # fix(#934 codex r2): a fold whose west lands exactly on +180 (rows at
    # planar 180 and -170), or whose east lands on -180, has a zero-width
    # half. bbox_to_extent_wkt drops such halves, which is correct for its
    # continuous-rectangle callers but wrong here: the dropped half is
    # precisely where a discrete row is stored, so the -180..-170 lobe alone
    # stopped covering the row at planar +180 and the read-back stopped
    # reporting a crossing at all. Widen that seam edge to a sub-mm sliver
    # (the same 1e-9 the ST_Expand degenerate paths use) so both planar
    # representations of the seam meridian stay covered.
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


# Unit semantics live in the conversion factor, never the unit's name.
# fix(#961): this constant had a twin in processing/raster/vrt.py, compared the
# same way against the same tolerance. Both sites now go through
# `crs_has_degree_unit` below, so there is one implementation to keep right.
_RADIANS_PER_DEGREE = math.pi / 180.0


@lru_cache(maxsize=256)
def _parse_crs(crs_wkt: str) -> object | None:
    """Parse stored CRS WKT with PROJ, or None when PROJ will not accept it.

    fix(#939): rounds 1-9 of review on this file were all the same defect in
    different clothes -- a regex reading WKT structure. Every fix narrowed the
    scan window (quoted names, GEODCRS, the WKT2 ``CS[`` section, the BOUNDCRS
    ``SOURCECRS`` window, the target's PRIMEM) and every one was followed by
    another WKT element that legitimately carries an angular unit outside the
    window: PRIMEM, then MERIDIAN, with BEARING and the conversion PARAMETERs
    still unclaimed. That sequence does not terminate, because WKT is a nested
    grammar and a flat scan cannot decide which subtree a unit belongs to.
    So stop scanning and ask the parser: PROJ answers "is this geographic" and
    "what are its axis units" from the actual tree, and gets the whole class
    right at once (a BoundCRS reports its SOURCE's units; a 3D geographic CRS
    reports its axis unit, not its MERIDIAN's).

    The import is function-scope because rasterio pulls in GDAL and ``core`` is
    the lowest layer -- every other rasterio use in the codebase is
    function-scope for the same reason. Results are cached because the callers
    (raster list projections in ``processing/raster/queries.py`` and
    ``catalog/datasets/domain/helpers.py``) run this per row, over a small set
    of distinct CRSs.
    """
    try:
        from rasterio.crs import CRS

        return CRS.from_wkt(crs_wkt)
    except Exception:  # broad: crs_wkt is whatever GDAL wrote at ingest; any parse failure means "PROJ cannot answer", which is a fallback, not an error
        return None


def wkt_is_geographic(crs_wkt: str | None) -> bool | None:
    """Classify a CRS WKT as geographic (lon/lat axes) or projected.

    fix(#569): the frontend rendered geographic-CRS pixel resolutions as
    meters ("60 arc-second" ETOPO showed "2 cm"), so raster metadata has to
    say which class the stored CRS is. Engineering/local/unknown CRSs, and
    anything unclassifiable, return None.

    fix(#939): PROJ decides whenever it can parse the WKT. The keyword sniff
    below is the fallback for WKT that PROJ rejects -- abbreviated, truncated
    or legacy strings that this helper has always accepted, since it
    classifies whatever GDAL happened to write at ingest rather than a
    guaranteed-valid CRS. The sniff checks PROJCRS/PROJCS FIRST because WKT1
    nests a GEOGCS inside every PROJCS, blanks quoted content so a CRS *name*
    or remark mentioning PROJCS cannot misclassify, and reads WKT2:2015's
    GEODCRS as geographic when ellipsoidal / geocentric when Cartesian.

    This is a CLASS test and says nothing about units: a grads GEOGCS (the
    Paris-meridian family, e.g. EPSG:4807) is geographic without its
    resolutions being degrees. Pair it with :func:`wkt_has_degree_unit` when
    "geographic" needs to mean "resolutions are in degrees".
    """
    # isinstance, not truthiness: callers hand this whatever sits on
    # RasterAsset.crs_wkt, including mocks in tests; a non-string is an
    # unknown CRS, not a crash.
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
        # Parsed but neither geographic nor projected -- a geocentric or
        # engineering CRS. The sniff separates those two below.
    # Blank quoted content BEFORE truncating: WKT strings cannot contain the
    # quote character itself (WKT2 escapes it by doubling, which still
    # terminates each pair), so this never eats a structural keyword -- and
    # blanking first means a pathologically long quoted name cannot push the
    # real keywords past the truncation point.
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
    :func:`wkt_has_degree_unit` is this plus the WKT parse; ``_is_degree_based``
    (``processing/raster/vrt.py``) is this plus an ``is_geographic``
    precondition. They used to be two copies of the same comparison against two
    copies of the same constant, kept in step by cross-referencing comments,
    which is the arrangement #961 was filed to end. The CRS-object entry point
    is what makes one implementation possible: ``vrt.py`` holds a live
    ``rasterio.crs.CRS`` and must not be pushed through a WKT round trip to
    reach a shared helper.

    ``rel_tol`` is correct here: this compares two fixed physical constants of
    the same tiny magnitude (0.01745 radians per degree against whatever PROJ
    reports), where proportional agreement is the meaningful test and the
    nearest wrong answer, grads at 0.01571, is 10% away.

    Returns None when there is no CRS or PROJ cannot report a unit factor.
    Callers must read that as "unknown" and decide for themselves — the two
    call sites deliberately differ, see each one.
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

    fix(#939): companion to :func:`wkt_is_geographic`, which is a class test
    and admits grads CRSs. Only meaningful for a WKT already classified as
    geographic, so call that first.

    The answer comes from :func:`crs_has_degree_unit`, which is also what
    ``_is_degree_based`` (processing/raster/vrt.py) calls, so the two unit
    tests in this codebase are one implementation rather than two that must be
    kept in step (fix(#961)). Reading PROJ's ``units_factor`` rather than the
    unit's name means a valid custom spelling
    (``UNIT["arc-degree",0.01745...]``) still reads as degrees, while grads
    sit 10% away and stay excluded.

    Returns None when there is no WKT, or when PROJ cannot parse what is
    stored. Callers must treat None as "unknown", not as "not degrees":
    ``processing/tiles/router.py`` tests ``is not False`` precisely so an
    unparseable CRS keeps the historical degrees assumption instead of
    silently dropping the resolution.
    """
    if not isinstance(crs_wkt, str) or not crs_wkt:
        return None
    return crs_has_degree_unit(_parse_crs(crs_wkt))


def crs_metres_per_unit(crs: object | None) -> float | None:
    """Metres per linear unit of a PROJECTED CRS, or None when that is not a
    question with an answer.

    fix(#1375 review): STAC's ``gsd`` is defined in metres, but a stored
    resolution is in whatever unit its CRS measures. PROJ answers the
    conversion for projected CRSs directly — ``units_factor`` reports
    ``('metre', 1.0)`` for UTM and Web Mercator and ``('US survey foot',
    0.3048006...)`` for the state-plane systems, so a foot-based raster
    converts as readily as a metre-based one.

    Returns None for a GEOGRAPHIC CRS on purpose, rather than a factor.
    ``units_factor`` reports RADIANS per unit there, and an angular
    resolution has no fixed length: a degree of longitude is 111 km at the
    equator and nothing at the pole, so the conversion needs a latitude this
    function is not given. Callers must read None as "cannot be expressed in
    metres" and omit the value rather than publish it unconverted — see
    ``RasterAsset.to_stac_properties``.
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

    Same shape as :func:`wkt_has_degree_unit` over
    :func:`crs_has_degree_unit`: one implementation, two entry points, so a
    caller holding a live ``rasterio.crs.CRS`` need not round-trip through
    WKT to reach it. None covers every uncertainty — no WKT, an unparseable
    one, or a CRS whose units PROJ will not report.
    """
    if not isinstance(crs_wkt, str) or not crs_wkt:
        return None
    return crs_metres_per_unit(_parse_crs(crs_wkt))


def pixel_size_from_affine(
    a: float, b: float, d: float, e: float
) -> tuple[float, float]:
    """Per-pixel ground distances along a raster's OWN axes, from its affine.

    fix(#1375 review): not ``abs(a)``/``abs(e)``. Those are the pixel vectors'
    COMPONENTS on the world axes, which equal the pixel sizes only when the
    raster is axis-aligned. A geotransform maps pixel (col, row) to world
    ``x = a*col + b*row + c``, ``y = d*col + e*row + f``, so one step along the
    column axis moves the world point by the vector ``(a, d)`` and one step
    along the row axis by ``(b, e)``. The LENGTHS of those two vectors are the
    resolutions; ``a`` and ``e`` alone are their projections onto x and y.

    Rotate a 10 m-pixel raster by 30° and the affine reads ``a=8.66, d=5.0``:
    ``abs(a)`` reports 8.66 m for a pixel that is 10 m across, a 13%
    understatement that reaches the UI and STAC's ``gsd``. Confirmed against
    the distance between adjacent pixel centres, which is 10.0.

    For an axis-aligned raster ``b`` and ``d`` are zero and this returns
    exactly ``abs(a)``/``abs(e)`` — it agrees with the old form everywhere the
    old form was right, and differs only where it was wrong. Both raster
    ingest paths call this so a rotated scene reports the same resolution
    whether it was uploaded or imported from a remote catalog.
    """
    return math.hypot(a, d), math.hypot(b, e)
