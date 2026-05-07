from __future__ import annotations

from geoalchemy2.shape import to_shape
from sqlalchemy import and_, func, or_
from sqlalchemy.sql.elements import ColumnElement


def extent_to_bbox(extent: object | None) -> list[float] | None:
    """Convert a GeoAlchemy2 geometry extent to [minx, miny, maxx, maxy]."""
    if extent is None:
        return None
    try:
        shape = to_shape(extent)
        return list(shape.bounds)
    except Exception:  # broad: input is user-supplied; any geoalchemy/shapely parse failure should fall back to None
        return None


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
