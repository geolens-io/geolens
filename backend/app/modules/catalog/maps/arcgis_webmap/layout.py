"""Unit conversions shared by the web map translator."""

from __future__ import annotations

import math
from typing import Any

_SCALE_AT_ZOOM_ONE = 591657550.5
_WORLD_METERS = 40075016.685578496
_POINT_TO_PX = 96 / 72
_VIEWPORT_W, _VIEWPORT_H = 1280, 800
_TILE_PX = 512
_WEB_MERCATOR_WKIDS = {102100, 102113, 3857, 3785}
_MAX_POINTS = 1000.0


def num(value: Any) -> float | None:
    """A finite number, or None. Booleans are not numbers here."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def scale_to_zoom(scale: Any) -> float | None:
    """MapLibre zoom for an ArcGIS map scale denominator; None for 0 (no limit)."""
    value = num(scale)
    if value is None or value <= 0:
        return None
    zoom = math.log2(_SCALE_AT_ZOOM_ONE / value) - 1
    return round(min(24.0, max(0.0, zoom)), 1)


def points_to_px(points: Any, default: float = 0.0) -> float:
    """Points as pixels, bounded so a hostile size can't become infinity."""
    value = num(points)
    bounded = min(max(default if value is None else value, 0.0), _MAX_POINTS)
    return round(bounded * _POINT_TO_PX, 2)


def describe(value: Any) -> str:
    """A short printable form of a portal value, without recursing into it."""
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return str(value)[:80]
    return type(value).__name__


def color_to_hex(color: Any) -> tuple[str, float] | None:
    """``[r, g, b, a]`` (a in 0-255) as ``("#rrggbb", opacity)``."""
    if not isinstance(color, (list, tuple)) or len(color) < 3:
        return None
    channels = [num(c) for c in color[:3]]
    if any(c is None for c in channels):
        return None
    alpha = num(color[3]) if len(color) > 3 else 255.0
    rgb = "".join(f"{min(255, max(0, round(c))):02x}" for c in channels)  # type: ignore[arg-type]
    opacity = 1.0 if alpha is None else min(1.0, max(0.0, alpha / 255))
    return f"#{rgb}", round(opacity, 3)


def is_web_mercator(spatial_reference: Any) -> bool:
    ref = spatial_reference if isinstance(spatial_reference, dict) else {}
    wkid = ref.get("latestWkid", ref.get("wkid"))
    return isinstance(wkid, int) and wkid in _WEB_MERCATOR_WKIDS


def _to_meters(x: float, y: float, wkid: Any) -> tuple[float, float] | None:
    if wkid in _WEB_MERCATOR_WKIDS:
        return x, y
    if wkid == 4326 and abs(y) < 85.05:
        mx = x / 360 * _WORLD_METERS
        my = math.log(math.tan(math.pi / 4 + math.radians(y) / 2)) * (
            _WORLD_METERS / (2 * math.pi)
        )
        return mx, my
    return None


def extent_to_view(extent: Any) -> tuple[float, float, float] | None:
    """``(center_lng, center_lat, zoom)`` fitting an extent in a 1280 x 800 viewport."""
    if not isinstance(extent, dict):
        return None
    ref = extent.get("spatialReference")
    wkid = ref.get("latestWkid", ref.get("wkid")) if isinstance(ref, dict) else None
    if not isinstance(wkid, int):
        return None
    raw = [num(extent.get(k)) for k in ("xmin", "ymin", "xmax", "ymax")]
    if any(v is None for v in raw):
        return None
    if any(abs(v) > 1e9 for v in raw):  # type: ignore[arg-type]
        return None
    low = _to_meters(raw[0], raw[1], wkid)  # type: ignore[arg-type]
    high = _to_meters(raw[2], raw[3], wkid)  # type: ignore[arg-type]
    if low is None or high is None:
        return None
    dx, dy = abs(high[0] - low[0]), abs(high[1] - low[1])
    fits = [
        math.log2(size / _TILE_PX * _WORLD_METERS / span)
        for size, span in ((_VIEWPORT_W, dx), (_VIEWPORT_H, dy))
        if span > 0
    ]
    zoom = round(min(24.0, max(0.0, min(fits))), 1) if fits else 14.0
    cx, cy = (low[0] + high[0]) / 2, (low[1] + high[1]) / 2
    lng = cx / _WORLD_METERS * 360
    lat = math.degrees(
        2 * math.atan(math.exp(cy / (_WORLD_METERS / (2 * math.pi)))) - math.pi / 2
    )
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return round(lng, 6), round(lat, 6), zoom
