"""Geometry detection & GeoJSON helpers for ephemeral chat result layers.

Phase 276 CODE-02 — extracted from chat_service.py.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import shapely
from shapely.geometry import shape as shapely_shape

_GEOM_NAMES = {"geom_4326", "geom", "geometry", "the_geom", "wkb_geometry"}
_HEX_RE = re.compile(r"^[0-9a-fA-F]{10,}$")


def _is_geom_value(val: object) -> bool:
    """Check if a value looks like WKB hex or ST_AsGeoJSON output."""
    if not isinstance(val, str):
        return False
    # WKB hex: long even-length hex string
    if len(val) >= 10 and len(val) % 2 == 0 and _HEX_RE.match(val):
        return True
    # ST_AsGeoJSON: JSON string containing geometry type
    if val.startswith("{") and '"type"' in val:
        return True
    return False


def _detect_geom_column(columns: list[str], first_row: list) -> int | None:
    """Find the index of a geometry column by name + value check."""
    for i, col in enumerate(columns):
        name = col.lower()
        if name in _GEOM_NAMES or name.startswith("st_"):
            if i < len(first_row) and _is_geom_value(first_row[i]):
                return i
    return None


def _safe_value(v: object) -> object:
    """Convert non-JSON-serializable types to str; pass through primitives."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (datetime, date, Decimal, bytes, memoryview, UUID)):
        return str(v)
    return str(v)


def _extract_geojson(
    columns: list[str], rows: list[list]
) -> tuple[dict, list[float]] | None:
    """Build a GeoJSON FeatureCollection + bbox from query rows."""
    if not rows:
        return None

    geom_idx = _detect_geom_column(columns, rows[0])
    if geom_idx is None:
        return None

    prop_indices = [(i, col) for i, col in enumerate(columns) if i != geom_idx]
    features: list[dict] = []
    min_x, min_y, max_x, max_y = (
        float("inf"),
        float("inf"),
        float("-inf"),
        float("-inf"),
    )

    for row in rows:
        raw = row[geom_idx] if geom_idx < len(row) else None
        if raw is None:
            continue

        # Parse geometry
        try:
            if isinstance(raw, str) and raw.startswith("{"):
                geom_dict = json.loads(raw)
                shape = shapely_shape(geom_dict)
                geometry = geom_dict
            else:
                shape = shapely.from_wkb(bytes.fromhex(raw))
                geometry = json.loads(shapely.to_geojson(shape))
        except Exception:  # broad: per-row geometry parse — JSON/WKB/Shapely can throw varied errors; skip bad rows
            continue

        # Build properties
        props = {}
        for idx, col_name in prop_indices:
            props[col_name] = _safe_value(row[idx] if idx < len(row) else None)

        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": props,
            }
        )

        # Update bbox
        bx = shape.bounds  # (minx, miny, maxx, maxy)
        if bx[0] < min_x:
            min_x = bx[0]
        if bx[1] < min_y:
            min_y = bx[1]
        if bx[2] > max_x:
            max_x = bx[2]
        if bx[3] > max_y:
            max_y = bx[3]

    if not features:
        return None

    fc = {"type": "FeatureCollection", "features": features}
    bbox = [min_x, min_y, max_x, max_y]
    return fc, bbox
