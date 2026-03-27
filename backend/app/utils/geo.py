from geoalchemy2.shape import to_shape


def extent_to_bbox(extent) -> list[float] | None:
    """Convert a GeoAlchemy2 geometry extent to [minx, miny, maxx, maxy]."""
    if extent is None:
        return None
    try:
        shape = to_shape(extent)
        return list(shape.bounds)
    except Exception:
        return None
