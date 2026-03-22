"""ArcGIS REST API probing, URL normalization, and service type detection."""

import asyncio
import logging
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Maps esri geometry type strings to simple geometry names
_ESRI_GEOM_TYPE_MAP = {
    "esriGeometryPoint": "Point",
    "esriGeometryMultipoint": "MultiPoint",
    "esriGeometryPolyline": "LineString",
    "esriGeometryPolygon": "Polygon",
    "esriGeometryEnvelope": "Envelope",
}


def _normalize_esri_geom_type(esri_type: str | None) -> str | None:
    """Convert esriGeometryPoint -> Point, etc.

    Returns the original value if not found in the mapping.
    """
    if not esri_type:
        return None
    return _ESRI_GEOM_TYPE_MAP.get(esri_type, esri_type)


def _looks_like_arcgis(url: str) -> bool:
    """Check if a URL looks like an ArcGIS service (FeatureServer or MapServer)."""
    lower = url.lower()
    return "featureserver" in lower or "mapserver" in lower


def _looks_like_wfs(url: str) -> bool:
    """Check if a URL looks like a WFS service."""
    parsed = urlparse(url)
    lower_path = parsed.path.lower()
    lower_query = parsed.query.lower()
    return "/wfs" in lower_path or "service=wfs" in lower_query


def normalize_arcgis_url(url: str) -> tuple[str, int | None]:
    """Normalize an ArcGIS URL to a canonical service root form.

    Strips query parameters, trailing slashes, /query suffix, and extracts
    layer number if present.

    Returns (normalized_base_url, optional_layer_id).
    """
    # Strip query parameters
    parsed = urlparse(url)
    clean_url = parsed._replace(query="", fragment="").geturl()

    # Strip trailing slash
    clean_url = clean_url.rstrip("/")

    # Strip /query suffix
    if clean_url.lower().endswith("/query"):
        clean_url = clean_url[: -len("/query")]
        clean_url = clean_url.rstrip("/")

    # Extract layer number if present (e.g., /FeatureServer/0 or /MapServer/3)
    layer_id = None
    match = re.search(r"/(FeatureServer|MapServer)/(\d+)$", clean_url, re.IGNORECASE)
    if match:
        layer_id = int(match.group(2))
        # Remove the layer number from the URL
        clean_url = clean_url[: match.start() + 1 + len(match.group(1))]

    return clean_url, layer_id


async def probe_arcgis_service(
    base_url: str, client: httpx.AsyncClient, token: str | None = None
) -> dict | None:
    """Probe an ArcGIS FeatureServer/MapServer root and extract layer list.

    Returns a dict with service_type, version, and layers on success,
    or None if not an ArcGIS service.
    """
    try:
        query = f"{base_url}?f=json" + (f"&token={token}" if token else "")
        response = await client.get(query)
        response.raise_for_status()
    except (httpx.HTTPStatusError, httpx.TransportError) as exc:
        logger.debug("ArcGIS probe failed for %s: %s", base_url, exc)
        return None

    try:
        data = response.json()
    except (ValueError, TypeError):
        return None

    # ArcGIS returns HTTP 200 with error in JSON body
    if "error" in data:
        error_info = data["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        logger.warning("ArcGIS error response: url=%s code=%s message=%s", base_url, code, message)
        if code in (498, 499):  # Invalid/expired token
            raise httpx.HTTPStatusError(
                f"ArcGIS token error ({code}): {message}",
                request=response.request,
                response=response,
            )
        return None

    # Validate this is an ArcGIS service
    if "layers" not in data and "tables" not in data:
        return None

    version = data.get("currentVersion")

    # Determine service type from URL
    lower_url = base_url.lower()
    if "featureserver" in lower_url:
        service_type = "ArcGIS FeatureServer"
    elif "mapserver" in lower_url:
        service_type = "ArcGIS MapServer"
    else:
        service_type = "ArcGIS FeatureServer"

    layers = []

    # Service-level objectIdField fallback
    service_oid = data.get("objectIdField")

    for layer in data.get("layers", []):
        layers.append(
            {
                "id": layer["id"],
                "name": layer["name"],
                "geometry_type": _normalize_esri_geom_type(layer.get("geometryType")),
                "type": "layer",
                "object_id_field": layer.get("objectIdField") or service_oid or "OBJECTID",
            }
        )

    for table in data.get("tables", []):
        layers.append(
            {
                "id": table["id"],
                "name": table["name"],
                "geometry_type": None,
                "type": "table",
            }
        )

    return {
        "service_type": service_type,
        "version": str(version) if version else None,
        "layers": layers,
    }


async def enrich_arcgis_feature_counts(
    base_url: str,
    layers: list[dict],
    client: httpx.AsyncClient,
    token: str | None = None,
) -> list[dict]:
    """Enrich ArcGIS layers with feature counts.

    Fetches returnCountOnly=true for each layer. Uses asyncio.Semaphore(5)
    for concurrency limiting. On failure, keeps feature_count=None.
    """
    semaphore = asyncio.Semaphore(5)

    async def _fetch_count(layer: dict) -> dict:
        async with semaphore:
            layer_id = layer.get("id")
            if layer_id is None:
                return {**layer, "feature_count": None}
            url = (
                f"{base_url}/{layer_id}/query?where=1%3D1&returnCountOnly=true&f=json"
            ) + (f"&token={token}" if token else "")
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                return {**layer, "feature_count": data.get("count")}
            except (
                httpx.HTTPStatusError,
                httpx.TransportError,
                ValueError,
                KeyError,
            ):
                return {**layer, "feature_count": None}

    enriched = await asyncio.gather(*[_fetch_count(layer) for layer in layers])
    return list(enriched)
