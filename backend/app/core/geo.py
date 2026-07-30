from __future__ import annotations

from geoalchemy2.shape import to_shape
from sqlalchemy import and_, func, or_
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
    """Classify a CRS WKT as geographic (degree units) or projected.

    fix(#569): the frontend rendered geographic-CRS pixel resolutions as
    meters ("60 arc-second" ETOPO showed "2 cm"). The API has no proj
    library, but the stored WKT's root/inner keyword is enough: a projected
    CRS contains PROJCRS (WKT2) / PROJCS (WKT1) — checked FIRST because
    WKT1 nests a GEOGCS inside every PROJCS — otherwise a GEOGCRS/GEOGCS
    keyword (including inside a COMPOUNDCRS like EPSG:9518) means
    geographic. Engineering/local/unknown CRSs return None.
    """
    if not crs_wkt:
        return None
    head = crs_wkt[:2000].upper()
    if "PROJCRS" in head or "PROJCS" in head:
        return False
    if "GEOGCRS" in head or "GEOGCS" in head:
        return True
    return None
