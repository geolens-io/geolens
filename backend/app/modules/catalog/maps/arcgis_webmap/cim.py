"""Map Viewer and Pro CIM symbol references as the classic symbols they draw like.

A solid fill, a solid stroke and a single vector marker become the
``esriSFS``, ``esriSLS`` and ``esriSMS`` the renderer already translates. A
symbol layer or effect with no classic equivalent is reported, and a symbol
left with nothing drawable is not translated.
"""

from __future__ import annotations

import math
from typing import Any

from app.modules.catalog.maps.arcgis_webmap.layout import describe, num
from app.modules.catalog.maps.arcgis_webmap.loss import LossReport

_MAX_SYMBOL_LAYERS = 50
_SUPPORTED_LAYERS = {
    "CIMPolygonSymbol": ("CIMSolidFill", "CIMSolidStroke"),
    "CIMLineSymbol": ("CIMSolidStroke",),
    "CIMPointSymbol": ("CIMVectorMarker",),
}
# A ring this close to equidistant from its centre, with enough vertices,
# draws as a circle; Map Viewer writes its circle marker as such a ring.
_CIRCLE_TOLERANCE = 0.1
_CIRCLE_MIN_VERTICES = 8


def _d(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _l(value: Any) -> list:
    return value if isinstance(value, list) else []


def _color(value: Any, path: str, loss: LossReport) -> list | None:
    """``[r, g, b, a]`` with alpha in 0-255; ``CIMRGBColor`` carries alpha in 0-100."""
    if isinstance(value, list):
        return value
    color = _d(value)
    values = _l(color.get("values"))
    if color.get("type") == "CIMRGBColor" and len(values) >= 3:
        alpha = num(values[3]) if len(values) > 3 else 100.0
        return [*values[:3], 255 * (100.0 if alpha is None else alpha) / 100]
    if value is not None:
        loss.add(path, "symbol_style", f"colour {describe(color.get('type'))}")
    return None


def _layers(symbol: dict, path: str, loss: LossReport) -> dict[str, dict]:
    """The first enabled layer of each supported type; the rest are reported."""
    supported = _SUPPORTED_LAYERS[symbol["type"]]
    found: dict[str, dict] = {}
    if _l(symbol.get("effects")):
        loss.add(path, "symbol_style", "CIM symbol effects")
    for raw in _l(symbol.get("symbolLayers"))[:_MAX_SYMBOL_LAYERS]:
        layer = _d(raw)
        if layer.get("enable") is False:
            continue
        kind = layer.get("type")
        if kind not in supported:
            loss.add(path, "symbol_style", f"CIM symbol layer {describe(kind)}")
        elif kind in found:
            loss.add(path, "symbol_style", f"more than one {kind} layer")
        else:
            if _l(layer.get("effects")):
                loss.add(path, "symbol_style", f"{kind} effects")
            found[kind] = layer
    return found


def _outline(stroke: dict | None, path: str, loss: LossReport) -> dict:
    if stroke is None:
        return {"type": "esriSLS", "style": "esriSLSNull"}
    return {
        "type": "esriSLS",
        "style": "esriSLSSolid",
        "color": _color(stroke.get("color"), path, loss),
        "width": stroke.get("width"),
    }


def _polygon(symbol: dict, path: str, loss: LossReport) -> dict | None:
    layers = _layers(symbol, path, loss)
    fill, stroke = layers.get("CIMSolidFill"), layers.get("CIMSolidStroke")
    if fill is None and stroke is None:
        return None
    return {
        "type": "esriSFS",
        "style": "esriSFSSolid" if fill else "esriSFSNull",
        "color": _color(fill.get("color"), path, loss) if fill else None,
        "outline": _outline(stroke, path, loss),
    }


def _line(symbol: dict, path: str, loss: LossReport) -> dict | None:
    stroke = _layers(symbol, path, loss).get("CIMSolidStroke")
    return None if stroke is None else _outline(stroke, path, loss)


def _is_circle(geometry: dict) -> bool:
    if geometry.get("curveRings"):
        return True
    rings = _l(geometry.get("rings"))
    if len(rings) != 1:
        return False
    points = [
        (num(p[0]), num(p[1]))
        for p in _l(rings[0])[:1000]
        if isinstance(p, list) and len(p) >= 2
    ]
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < _CIRCLE_MIN_VERTICES or any(None in p for p in points):
        return False
    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    radii = [math.hypot(x - cx, y - cy) for x, y in points]
    mean = sum(radii) / len(radii)
    return mean > 0 and all(abs(r - mean) <= mean * _CIRCLE_TOLERANCE for r in radii)


def _point(symbol: dict, path: str, loss: LossReport) -> dict | None:
    marker = _layers(symbol, path, loss).get("CIMVectorMarker")
    if marker is None:
        return None
    graphics = _l(marker.get("markerGraphics"))
    graphic = _d(graphics[0]) if graphics else {}
    inner = _d(graphic.get("symbol"))
    if len(graphics) != 1 or inner.get("type") != "CIMPolygonSymbol":
        loss.add(path, "symbol_style", "vector marker graphics")
        return None
    if not _is_circle(_d(graphic.get("geometry"))):
        loss.add(path, "symbol_style", "vector marker shape drawn as a circle")
    shape = _polygon(inner, f"{path}.markerGraphics[0].symbol", loss) or {}
    return {
        "type": "esriSMS",
        "style": "esriSMSCircle",
        "color": shape.get("color")
        if shape.get("style") == "esriSFSSolid"
        else [0, 0, 0, 0],
        "size": marker.get("size"),
        "angle": marker.get("rotation"),
        "xoffset": marker.get("offsetX"),
        "yoffset": marker.get("offsetY"),
        "outline": shape.get("outline") or {},
    }


def classic_symbol(reference: dict, path: str, loss: LossReport) -> dict | None:
    """The classic symbol a ``CIMSymbolReference`` draws like, or None (reported)."""
    symbol = _d(reference.get("symbol"))
    kind = symbol.get("type")
    if kind == "CIMPolygonSymbol":
        classic = _polygon(symbol, path, loss)
    elif kind == "CIMLineSymbol":
        classic = _line(symbol, path, loss)
    elif kind == "CIMPointSymbol":
        classic = _point(symbol, path, loss)
    else:
        loss.add(path, "symbol_style", f"CIM symbol type {describe(kind)}")
        return None
    if classic is None:
        loss.add(path, "symbol_style", f"{kind} with nothing that could be drawn")
    return classic
