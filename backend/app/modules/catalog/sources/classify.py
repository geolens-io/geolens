"""Backend layer-kind classification helper.

Implements the D-09 classification rule from Phase 1057, CLASS-07:

  A layer is 'raster' IFF any of:
    1. adapter_type == 'stac'  (STAC adapter always yields raster/imagery)
    2. geometry_type (lowercased) contains 'raster'
    3. layer dict has a truthy 'coverage_format' key
    4. layer dict has a truthy 'bands' key
    5. any entry in layer['links'] (must be a list) has a 'type' starting with 'image/'

  Everything else — including geometry_type=None (the post-D-05 default after ogrinfo
  enrichment is dropped from the probe phase) — returns 'vector'.

This helper is called at layer-dict construction time in the OGC API and WFS adapters
so that every LayerInfo in a ProbeResponse carries a durable 'kind' classification
that the frontend (and future ingest UIs) can consume directly, rather than re-deriving
the rule from geometry_type string contents.

Phase 1057 CLASS-07  — D-09 specification
"""

from __future__ import annotations

from typing import Literal


def classify_layer_kind(
    layer: dict,
    adapter_type: Literal["wfs", "ogcapi", "arcgis", "stac"],
) -> Literal["vector", "raster"]:
    """Classify a probe-response layer dict as 'vector' or 'raster'.

    Args:
        layer: Raw layer dict as built by the adapter probe function (probe_ogcapi,
               probe_wfs, probe_arcgis_service) — may contain any subset of the
               keys listed under the D-09 raster signals.
        adapter_type: The adapter that produced this layer. One of 'wfs', 'ogcapi',
                      'arcgis', or 'stac'.

    Returns:
        'raster' if any D-09 raster signal is present; 'vector' otherwise.

    D-09 invariants (tested in backend/tests/test_probe_classification.py):
      - WFS layers are always 'vector' (WFS is a vector feature service by OGC spec).
      - OGC API Features layers default to 'vector' unless explicit raster signals fire.
      - STAC adapter layers are always 'raster'.
      - ArcGIS FeatureServer layers are 'vector' absent raster signals.
    """
    # Rule 1: STAC adapter is exclusively raster/imagery.
    if adapter_type == "stac":
        return "raster"

    # Rule 2: geometry_type string containing 'raster' (e.g. 'Raster', 'rasterBand').
    raw_geometry_type = layer.get("geometry_type")
    if raw_geometry_type and "raster" in str(raw_geometry_type).lower():
        return "raster"

    # Rule 3: OGC API Coverage / STAC Coverage format signal.
    if layer.get("coverage_format"):
        return "raster"

    # Rule 4: Band-metadata signal (STAC-derived or coverage collections).
    if layer.get("bands"):
        return "raster"

    # Rule 5: Any link with a mediaType starting with 'image/'.
    links = layer.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict):
                link_type = link.get("type", "")
                if isinstance(link_type, str) and link_type.startswith("image/"):
                    return "raster"

    return "vector"
