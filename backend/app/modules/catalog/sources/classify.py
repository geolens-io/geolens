"""Backend layer-kind classification helper.

Implements the D-09 rule (Phase 1057, CLASS-07): a layer is 'raster' iff any
of adapter_type == 'stac', geometry_type contains 'raster', a truthy
'coverage_format' or 'bands' key, or a links[] entry whose 'type' starts with
'image/'. Everything else, including geometry_type=None (the post-D-05
default), returns 'vector'.

Called at layer-dict construction time in the OGC API and WFS adapters so
every LayerInfo carries a durable 'kind' rather than re-deriving it from
geometry_type string contents downstream.
"""

from __future__ import annotations

from typing import Literal


def classify_layer_kind(
    layer: dict,
    adapter_type: Literal["wfs", "ogcapi", "arcgis", "stac"],
) -> Literal["vector", "raster"]:
    """Classify a probe-response layer dict as 'vector' or 'raster'.

    Returns 'raster' if any D-09 raster signal is present (see module
    docstring), else 'vector'. Invariants tested in
    backend/tests/test_probe_classification.py.
    """
    if adapter_type == "stac":
        return "raster"

    raw_geometry_type = layer.get("geometry_type")
    if raw_geometry_type and "raster" in str(raw_geometry_type).lower():
        return "raster"

    if layer.get("coverage_format"):
        return "raster"

    if layer.get("bands"):
        return "raster"

    links = layer.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict):
                link_type = link.get("type", "")
                if isinstance(link_type, str) and link_type.startswith("image/"):
                    return "raster"

    return "vector"
