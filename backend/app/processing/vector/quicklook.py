"""Generate PNG quicklook thumbnails for vector datasets using Pillow + Shapely."""

from __future__ import annotations

import asyncio
import json
import re
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw
from shapely.geometry import shape
from shapely.validation import make_valid
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Styling constants — light background with blue geometry
_BG_COLOR = (241, 245, 249)  # #f1f5f9 slate-50
_FILL_COLOR = (191, 219, 254)  # #bfdbfe blue-200
_STROKE_COLOR = (59, 130, 246)  # #3b82f6 blue-500
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_GENERATION_TIMEOUT_SECONDS = 10


def _geo_to_pixel(
    x: float,
    y: float,
    bounds: tuple[float, float, float, float],
    size: int,
    padding: int = 6,
) -> tuple[float, float]:
    """Transform WGS84 coordinates to pixel space, aspect-preserved, y-inverted."""
    minx, miny, maxx, maxy = bounds
    effective = size - 2 * padding
    dx = maxx - minx or 1
    dy = maxy - miny or 1
    scale = min(effective / dx, effective / dy)
    cx_offset = padding + (effective - dx * scale) / 2
    cy_offset = padding + (effective - dy * scale) / 2
    px = cx_offset + (x - minx) * scale
    py = cy_offset + (maxy - y) * scale  # y-inverted
    return (px, py)


def _draw_geometry(
    draw: ImageDraw.ImageDraw,
    geom,
    bounds: tuple[float, float, float, float],
    size: int,
    point_radius: float = 3.0,
) -> None:
    """Recursively draw a Shapely geometry onto the canvas."""
    gtype = geom.geom_type

    if gtype == "Point":
        cx, cy = _geo_to_pixel(geom.x, geom.y, bounds, size)
        r = point_radius
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r], fill=_FILL_COLOR, outline=_STROKE_COLOR
        )

    elif gtype == "MultiPoint":
        for pt in geom.geoms:
            _draw_geometry(draw, pt, bounds, size, point_radius)

    elif gtype == "LineString":
        if len(geom.coords) < 2:
            return
        coords = [_geo_to_pixel(x, y, bounds, size) for x, y in geom.coords]
        draw.line(coords, fill=_STROKE_COLOR, width=3)

    elif gtype == "MultiLineString":
        for line in geom.geoms:
            _draw_geometry(draw, line, bounds, size, point_radius)

    elif gtype == "Polygon":
        if geom.is_empty:
            return
        coords = [_geo_to_pixel(x, y, bounds, size) for x, y in geom.exterior.coords]
        draw.polygon(coords, fill=_FILL_COLOR, outline=_STROKE_COLOR)

    elif gtype == "MultiPolygon":
        for poly in geom.geoms:
            _draw_geometry(draw, poly, bounds, size, point_radius)

    elif gtype == "GeometryCollection":
        for sub in geom.geoms:
            _draw_geometry(draw, sub, bounds, size, point_radius)


def _compute_point_radius(num_points: int, size: int) -> float:
    """Scale point radius based on density. More points = smaller dots."""
    if num_points <= 50:
        return 6.0
    elif num_points <= 200:
        return 4.5
    elif num_points <= 1000:
        return 3.0
    else:
        return 2.0


def _blank_canvas(size: int) -> bytes:
    """Return a blank light canvas PNG."""
    canvas = Image.new("RGB", (size, size), _BG_COLOR)
    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


async def generate_vector_quicklook(
    db: "AsyncSession",
    table_name: str,
    geometry_type: str,
    size: int = 256,
) -> bytes:
    """Query simplified geometries from PostGIS and render a PNG thumbnail.

    Renders a world outline for geographic context, then overlays the actual
    dataset geometry in blue. Point sizes scale with density.
    """
    if not _TABLE_NAME_RE.match(table_name):
        return _blank_canvas(size)

    # Get bounds via ST_Extent (cheap aggregate) and row count for sampling decision
    bounds_sql = text(
        f"SELECT ST_XMin(e) AS minx, ST_YMin(e) AS miny, "
        f"       ST_XMax(e) AS maxx, ST_YMax(e) AS maxy, "
        f"       (SELECT reltuples::bigint FROM pg_class WHERE relname = :tname) AS est_rows "
        f"FROM (SELECT ST_Extent(geom_4326) AS e FROM data.{table_name} WHERE geom_4326 IS NOT NULL) sub"
    ).bindparams(tname=table_name)
    bounds_result = await db.execute(bounds_sql)
    bounds_row = bounds_result.fetchone()

    if bounds_row is None or bounds_row.minx is None:
        return _blank_canvas(size)

    minx, miny, maxx, maxy = (
        bounds_row.minx,
        bounds_row.miny,
        bounds_row.maxx,
        bounds_row.maxy,
    )
    est_rows = bounds_row.est_rows or 0

    # For large tables, use TABLESAMPLE to avoid scanning all rows
    max_features = 2000
    if est_rows > max_features * 2:
        sample_pct = min(100.0, (max_features / max(est_rows, 1)) * 100 * 1.5)
        geom_sql = text(
            f"SELECT ST_AsGeoJSON(ST_Simplify(ST_MakeValid(geom_4326), 0.01)) AS geojson "
            f"FROM data.{table_name} TABLESAMPLE SYSTEM ({sample_pct:.2f}) "
            f"WHERE geom_4326 IS NOT NULL LIMIT {max_features}"
        )
    else:
        geom_sql = text(
            f"SELECT ST_AsGeoJSON(ST_Simplify(ST_MakeValid(geom_4326), 0.01)) AS geojson "
            f"FROM data.{table_name} WHERE geom_4326 IS NOT NULL LIMIT {max_features}"
        )

    result = await db.execute(geom_sql)
    rows = result.fetchall()

    if not rows:
        return _blank_canvas(size)

    # Handle zero-extent (single point or collinear points)
    if maxx - minx < 1e-9:
        minx -= 0.01
        maxx += 0.01
    if maxy - miny < 1e-9:
        miny -= 0.01
        maxy += 0.01

    # Tight margin around data extent — just enough to avoid clipping edges
    dx = maxx - minx
    dy = maxy - miny
    margin_x = dx * 0.08
    margin_y = dy * 0.08
    view_bounds = (
        max(minx - margin_x, -180),
        max(miny - margin_y, -90),
        min(maxx + margin_x, 180),
        min(maxy + margin_y, 90),
    )

    # Parse geometries
    geometries = []
    num_points = 0
    for row in rows:
        if row.geojson is None:
            continue
        try:
            geom = shape(json.loads(row.geojson))
            if not geom.is_valid:
                geom = make_valid(geom)
            if not geom.is_empty:
                geometries.append(geom)
                if geom.geom_type in ("Point", "MultiPoint"):
                    num_points += 1 if geom.geom_type == "Point" else len(geom.geoms)
        except Exception:  # broad: per-row geometry — Shapely make_valid can throw varied errors; skip bad rows
            continue

    if not geometries:
        return _blank_canvas(size)

    # Create canvas and draw data geometry (no world outline — too noisy at thumbnail scale)
    canvas = Image.new("RGB", (size, size), _BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    point_radius = _compute_point_radius(num_points, size)
    for geom in geometries:
        _draw_geometry(draw, geom, view_bounds, size, point_radius)

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


async def generate_vector_quicklook_with_timeout(
    db: "AsyncSession",
    table_name: str,
    geometry_type: str,
    size: int = 256,
    timeout: float = _GENERATION_TIMEOUT_SECONDS,
) -> bytes:
    """Wrapper with timeout protection. Returns blank canvas on timeout."""
    try:
        return await asyncio.wait_for(
            generate_vector_quicklook(db, table_name, geometry_type, size),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return _blank_canvas(size)
