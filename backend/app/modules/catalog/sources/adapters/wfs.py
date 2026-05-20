"""WFS GetCapabilities fetching and parsing with safe XML handling.

# XML safety
# ----------
# All parsing uses `defusedxml.ElementTree`, NOT stdlib `xml.etree`. defusedxml
# blocks the well-known XML attacks (billion laughs, XXE, external entity
# expansion, decompression bombs). Never replace this import — the WFS service
# probe accepts user-supplied URLs, so the response is always untrusted.
#
# Namespace handling
# ------------------
# WFS 1.0, 1.1, and 2.0 each use slightly different XML namespaces and element
# names for FeatureType discovery. The parser walks the tree namespace-agnostic
# (matching by local-name) so the same code path supports all three versions.
#
# Phase 1057 PROBE-05 + D-05 (ogrinfo enrichment dropped from probe phase)
# -------------------------------------------------------------------------
# enrich_wfs_layers() was removed in Phase 1057. The per-layer ogrinfo
# subprocess (Semaphore(5) x N layers x ~3-4s each) was the latency
# bottleneck. Dropping it makes the ≤5s probe target trivially achievable.
#
# geometry_type and feature_count now return None at probe time. When the user
# selects a specific layer, the preview path at preview.py runs ogrinfo for
# that single layer. WFS layers always have kind='vector' (WFS is a vector
# feature service by OGC spec — raster sources use STAC instead).
"""

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import defusedxml.ElementTree as ET
import httpx
import structlog

logger = structlog.stdlib.get_logger(__name__)


def parse_wfs_capabilities(xml_text: str) -> tuple[str, list[dict]]:
    """Parse WFS GetCapabilities XML.

    Uses defusedxml for safe parsing (blocks XXE, billion laughs, etc.).
    Handles namespace variations across WFS 1.0, 1.1, and 2.0.

    Returns (version_string, layers_list) where each layer dict has
    keys: name, title, crs.
    """
    root = ET.fromstring(xml_text)

    # Extract WFS version from root element
    version = root.get("version", "unknown")

    layers = []

    # Namespace-agnostic iteration
    for element in root.iter():
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "FeatureType":
            name = None
            title = None
            crs = None

            for child in element:
                child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_tag == "Name":
                    name = child.text
                elif child_tag == "Title":
                    title = child.text
                elif child_tag in ("DefaultCRS", "DefaultSRS", "SRS"):
                    crs = child.text

            if name:
                layers.append(
                    {
                        "name": name,
                        "title": title or name,
                        "crs": crs,
                        # D-09: WFS is a vector feature service by OGC spec.
                        # geometry_type and feature_count are None at probe time
                        # (D-05: ogrinfo enrichment dropped from probe phase).
                        "geometry_type": None,
                        "feature_count": None,
                        "kind": "vector",
                    }
                )

    return version, layers


def _build_capabilities_url(url: str) -> str:
    """Build a GetCapabilities URL, preserving existing query params."""
    parsed = urlparse(url)
    existing_params = parse_qs(parsed.query)

    # Merge required WFS params (overwrite if present)
    existing_params["service"] = ["WFS"]
    existing_params["request"] = ["GetCapabilities"]

    new_query = urlencode(
        {k: v[0] for k, v in existing_params.items()},
    )
    return urlunparse(parsed._replace(query=new_query))


async def probe_wfs(
    url: str, client: httpx.AsyncClient, token: str | None = None
) -> dict | None:
    """Probe a URL as a WFS service.

    Fetches GetCapabilities and parses the response. Returns a dict with
    service_type and layers on success, or None if not a WFS service.
    """
    capabilities_url = _build_capabilities_url(url)
    request_headers = {}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"

    try:
        response = await client.get(capabilities_url, headers=request_headers)
        response.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        logger.debug("WFS probe failed for %s: %s", url, exc)
        return None

    # Check Content-Type is XML (not HTML error page)
    content_type = response.headers.get("content-type", "")
    if "text/html" in content_type and "xml" not in content_type:
        return None

    xml_text = response.text
    try:
        version, layers = parse_wfs_capabilities(xml_text)
    except ET.ParseError:
        logger.debug("WFS XML parse failed for %s", url)
        return None

    if not layers:
        return None

    return {
        "service_type": f"WFS {version}",
        "layers": layers,
    }
