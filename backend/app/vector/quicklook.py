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
_LAND_FILL = (226, 232, 240)  # #e2e8f0 slate-200
_LAND_STROKE = (203, 213, 225)  # #cbd5e1 slate-300
_TABLE_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_GENERATION_TIMEOUT_SECONDS = 10

# Simplified world landmass outlines (Natural Earth 10m, simplified to ~460 coords)
# Used as background context so users can see where data sits geographically.
_WORLD_OUTLINE: list[list[list[float]]] = json.loads(
    '[' + ','.join([
        '[[-179.5,68.9],[-169.6,66.1],[-180,65.1],[-179.5,68.9]]',
        '[[-155.8,-84.9],[-174.4,-82.8],[-152.5,-82.5],[-157.1,-81.3],[-147.1,-79.9],[-158.3,-77.1],[-135.4,-74.6],[-68.8,-73.1],[-67.5,-67.1],[-57.3,-63.2],[-65.6,-67.4],[-61,-74.5],[-83.9,-78.4],[-59.5,-83.5],[-22.5,-79.9],[-36.4,-78.6],[-18.3,-75.5],[-10.1,-70.9],[38.9,-70.2],[53.8,-65.8],[69.6,-67.8],[67.2,-73.3],[84.5,-67.1],[135.3,-66.1],[170.3,-71.3],[160.6,-75.4],[167.2,-78.7],[158.2,-80.4],[180,-84.4],[-155.8,-84.9]]',
        '[[-130.1,55.8],[-135.3,59.5],[-152,59.3],[-149.4,61.5],[-163.3,54.8],[-156.8,59.2],[-162.2,58.6],[-166.2,61.6],[-160.8,64.7],[-168.1,65.7],[-160.2,66.4],[-166.8,68.4],[-156.5,71.4],[-95.8,66.6],[-94.5,72],[-87.5,67.1],[-85.6,69.9],[-81.3,69.1],[-83.7,66.2],[-91.5,65.9],[-86.9,65.1],[-93.8,64.2],[-90.6,63.1],[-95,59.1],[-82.3,55.1],[-81,51],[-76.5,56.3],[-77.5,62.6],[-69.5,61.1],[-69.4,57.8],[-64.5,60.3],[-57.4,54.6],[-60.4,53.3],[-55.7,53.3],[-74.4,45.6],[-65.6,49.3],[-61,45.3],[-67.2,45.2],[-75.9,37.1],[-77.1,38.9],[-75.5,35.8],[-81.5,31.4],[-80.4,25.2],[-86.2,30.5],[-97.8,27.5],[-95.9,18.7],[-86.8,21.4],[-88.9,15.9],[-83.1,15],[-82.2,9],[-76.8,7.9],[-71.7,12.5],[-71.6,9],[-70,12.2],[-61.8,10.7],[-57.2,5.5],[-51.2,4.2],[-49.9,1.2],[-52.7,-1.6],[-47.3,-0.6],[-35.2,-5.6],[-41,-22],[-48.7,-25.4],[-54.1,-34.7],[-58.2,-32.4],[-56.7,-36.9],[-65.1,-40.8],[-68.4,-52.4],[-73.2,-53.2],[-75.7,-46.8],[-72.6,-44.5],[-70.1,-21.4],[-81.2,-6],[-77.7,8.1],[-80.9,7.2],[-87.4,13.4],[-103.5,18.3],[-115,32],[-109.5,23.2],[-111.8,24.5],[-124.4,40.3],[-122.9,49.4],[-130.1,55.8]]',
        '[[-13.3,9.1],[-17.5,14.8],[-17,21.8],[-5.9,35.8],[9.7,37.3],[10.3,33.7],[19,30.3],[21.7,33],[33.1,31],[36.2,36.8],[27.4,36.7],[26.2,40],[41.7,41.7],[36.6,45.2],[39.3,47.3],[33.9,44.4],[31.7,47.3],[29,41],[22.6,40.5],[22.5,36.4],[13.1,45.8],[18.5,40.1],[16.1,37.9],[8.8,44.4],[3.2,43.2],[-2.1,36.7],[-9,37],[-9.2,43.2],[-0.5,45],[-4.7,48.6],[9.8,53.5],[8.6,57.1],[14.6,53.6],[30.2,59.9],[21.4,60.6],[25.4,65],[22.7,65.9],[17.3,62.5],[19.1,59.8],[15.9,56.1],[12.8,55.4],[10.7,59.9],[5.6,58.6],[7.7,61.2],[5.1,62.2],[18.2,69.5],[28.2,71.1],[41,67.7],[31.9,67.2],[37.4,63.8],[44.2,65.9],[43.3,68.7],[68.3,68.2],[66.6,71.1],[71.6,72.9],[73.6,68.5],[69,66.8],[72.1,66.2],[74.6,68.8],[79.1,67.6],[73.8,69.2],[74.8,72.8],[83.1,70.1],[80.5,73.6],[104.3,77.7],[113.9,75.9],[105.1,72.8],[124.4,73.8],[131,70.7],[140.7,72.9],[160.8,68.5],[180,69],[180,65.1],[174.4,64.7],[179.6,62.6],[163.6,60],[163.4,56.2],[156.7,50.9],[156.7,57.7],[165.7,62.5],[143.2,59.4],[135.2,54.9],[141.4,53.3],[140.2,48.5],[127.5,39.7],[129,35],[126.5,34.3],[124.4,40.1],[117.7,39.1],[122.7,37.4],[119.2,35],[122,29.3],[116.5,22.9],[106.6,21],[109,11.4],[104.8,8.6],[100,13.3],[99.2,9.3],[104.2,1.3],[98.3,8.2],[97.7,16.6],[94.2,16],[90.6,23.6],[80.3,15.7],[77.5,8.1],[72.9,22.3],[70.5,20.8],[66.4,25.6],[57.8,25.6],[47.9,30.1],[51.3,24.3],[56.5,26.4],[59.8,22.3],[55,17],[43.9,12.6],[32.6,30],[42.5,11.5],[51.4,10.4],[39.2,-4.7],[40.6,-15.5],[34.6,-19.6],[35.5,-24.1],[25.7,-34],[18.4,-34.3],[15.3,-27.3],[9.8,4.1],[3.8,6.6],[-7.7,4.4],[-13.3,9.1]]',
        '[[130.2,-31.6],[115.1,-34.4],[113.9,-22],[126.1,-13.9],[129.7,-15.2],[132,-11.1],[136.6,-11.9],[135.5,-14.9],[140.5,-17.6],[142.5,-10.7],[153.2,-25.9],[150,-37.5],[141.4,-38.4],[136.8,-35.3],[137.8,-32.5],[136,-35],[130.2,-31.6]]',
        '[[133.3,34.3],[130.9,33.9],[141.5,41.4],[140.4,35.2],[133.3,34.3]]',
        '[[172.8,-43.6],[166.5,-46],[172.8,-40.5],[172.8,-43.6]]',
        '[[177.1,-39.7],[174.6,-41.3],[172.7,-34.4],[178.6,-37.7],[177.1,-39.7]]',
        '[[44.5,-19.9],[49.3,-11.9],[50.5,-15.4],[45.5,-25.6],[44.5,-19.9]]',
        '[[100.8,2.2],[105.7,-5.9],[95.2,5.6],[100.8,2.2]]',
        '[[117.4,4.1],[119,1],[116,-3.6],[110.3,-3],[109.3,1.9],[116.8,7],[119.3,5.3],[117.4,4.1]]',
        '[[140.5,-8.6],[131.2,-0.8],[144.5,-3.8],[150.9,-10.2],[140.5,-8.6]]',
    ]) + ']'
)


def _geo_to_pixel(
    x: float, y: float, bounds: tuple[float, float, float, float], size: int, padding: int = 16
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


def _draw_world_outline(
    draw: ImageDraw.ImageDraw, bounds: tuple[float, float, float, float], size: int
) -> None:
    """Draw simplified world landmass outlines as background context."""
    for ring in _WORLD_OUTLINE:
        pixels = [_geo_to_pixel(x, y, bounds, size) for x, y in ring]
        if len(pixels) >= 3:
            draw.polygon(pixels, fill=_LAND_FILL, outline=_LAND_STROKE)


def _draw_geometry(
    draw: ImageDraw.ImageDraw, geom, bounds: tuple[float, float, float, float],
    size: int, point_radius: float = 3.0,
) -> None:
    """Recursively draw a Shapely geometry onto the canvas."""
    gtype = geom.geom_type

    if gtype == "Point":
        cx, cy = _geo_to_pixel(geom.x, geom.y, bounds, size)
        r = point_radius
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_FILL_COLOR, outline=_STROKE_COLOR)

    elif gtype == "MultiPoint":
        for pt in geom.geoms:
            _draw_geometry(draw, pt, bounds, size, point_radius)

    elif gtype == "LineString":
        if len(geom.coords) < 2:
            return
        coords = [_geo_to_pixel(x, y, bounds, size) for x, y in geom.coords]
        draw.line(coords, fill=_STROKE_COLOR, width=2)

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
        return 4.0
    elif num_points <= 200:
        return 3.0
    elif num_points <= 1000:
        return 2.0
    else:
        return 1.5


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
        f"       (SELECT reltuples::bigint FROM pg_class WHERE relname = '{table_name}') AS est_rows "
        f"FROM (SELECT ST_Extent(geom_4326) AS e FROM data.{table_name} WHERE geom_4326 IS NOT NULL) sub"
    )
    bounds_result = await db.execute(bounds_sql)
    bounds_row = bounds_result.fetchone()

    if bounds_row is None or bounds_row.minx is None:
        return _blank_canvas(size)

    minx, miny, maxx, maxy = bounds_row.minx, bounds_row.miny, bounds_row.maxx, bounds_row.maxy
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

    # Add margin around data extent for context (10% on each side, min 1 degree)
    dx = maxx - minx
    dy = maxy - miny
    margin_x = max(dx * 0.1, 1.0)
    margin_y = max(dy * 0.1, 1.0)
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
                    num_points += (
                        1 if geom.geom_type == "Point" else len(geom.geoms)
                    )
        except Exception:
            continue

    if not geometries:
        return _blank_canvas(size)

    # Create canvas, draw world outline, then data geometry
    canvas = Image.new("RGB", (size, size), _BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    _draw_world_outline(draw, view_bounds, size)

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
