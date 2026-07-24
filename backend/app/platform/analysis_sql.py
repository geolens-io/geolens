"""Shared SQL rendering for parameterized PostGIS analysis (M4).

Lives in platform so both the catalog preview path
(``datasets/domain/service_analysis.py``) and the processing materialize
worker (``processing/analysis/tasks.py``) can import it — catalog must not
import processing and vice versa (CATPORT guards in test_layering.py).

Pure string rendering. The injection boundary:
- numbers are bounds-validated floats rendered via ``float()`` formatting;
- clip masks are parsed and re-serialized by shapely, so the embedded JSON
  is strictly ``{"type": ..., "coordinates": [numbers]}``;
- table identifiers are the callers' responsibility (``_safe_table_ref`` /
  regex-validated names).
"""

from __future__ import annotations

from typing import Any

import shapely
from shapely.errors import GEOSException
from shapely.geometry import shape

MAX_BUFFER_METERS = 100_000.0
MAX_MASK_VERTICES = 5_000

_CLIP_MASK_TYPES = ("Polygon", "MultiPolygon")


def render_mask_expr(mask: dict[str, Any]) -> str:
    """Render a validated clip mask as a PostGIS geometry expression.

    Raises ValueError on anything that is not a usable Polygon/MultiPolygon.
    """
    try:
        geom = shape(mask)
    except (GEOSException, AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "mask must be a GeoJSON Polygon or MultiPolygon geometry"
        ) from exc
    if geom.geom_type not in _CLIP_MASK_TYPES:
        raise ValueError("mask must be a GeoJSON Polygon or MultiPolygon geometry")
    if shapely.count_coordinates(geom) > MAX_MASK_VERTICES:
        raise ValueError(f"mask exceeds {MAX_MASK_VERTICES} vertices")
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
        if geom.geom_type not in _CLIP_MASK_TYPES:
            raise ValueError("mask geometry is invalid")
    rendered = shapely.to_geojson(geom)
    escaped = rendered.replace("'", "''")
    return f"ST_SetSRID(ST_GeomFromGeoJSON('{escaped}'), 4326)"


def render_geometry_expr(
    operation: str,
    *,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(geometry expression, WHERE clause)`` for a per-row operation.

    Operates on the conventional ``geom_4326`` column. The aggregate
    ``dissolve`` operation has a different query shape and is rendered by the
    materialize worker, not here.
    """
    if operation == "buffer":
        if distance_meters is None:
            raise ValueError("buffer requires distance_meters")
        distance = float(distance_meters)
        return f"ST_Buffer(geom_4326::geography, {distance})::geometry", ""
    if operation == "centroid":
        return "ST_Centroid(geom_4326)", ""
    if operation == "clip":
        mask_expr = render_mask_expr(mask or {})
        return (
            f"ST_CollectionExtract(ST_Intersection(geom_4326, {mask_expr}))",
            f" WHERE ST_Intersects(geom_4326, {mask_expr})",
        )
    raise ValueError(f"Unsupported operation: {operation}")
