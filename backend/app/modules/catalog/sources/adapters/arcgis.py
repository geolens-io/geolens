"""ArcGIS REST API probing, URL normalization, and service type detection."""

import asyncio
import re
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.stdlib.get_logger(__name__)


class ArcGISTokenError(Exception):
    """Raised when ArcGIS returns a token-related error (codes 498, 499)."""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(f"ArcGIS token error ({code}): {message}")


# Maps esri geometry type strings to simple geometry names
_ESRI_GEOM_TYPE_MAP = {
    "esriGeometryPoint": "Point",
    "esriGeometryMultipoint": "MultiPoint",
    "esriGeometryPolyline": "LineString",
    "esriGeometryPolygon": "Polygon",
    "esriGeometryEnvelope": "Envelope",
}


# Maps ESRI field types to the OGR field-type names the rest of the preview
# pipeline expects (matching the ``type`` strings ogrinfo -json emits for the
# WFS/OGC path). Unknown types fall back to "String".
_ESRI_FIELD_TYPE_MAP = {
    "esriFieldTypeOID": "Integer64",
    "esriFieldTypeInteger": "Integer",
    "esriFieldTypeSmallInteger": "Integer",
    "esriFieldTypeBigInteger": "Integer64",
    "esriFieldTypeDouble": "Real",
    "esriFieldTypeSingle": "Real",
    "esriFieldTypeString": "String",
    "esriFieldTypeDate": "DateTime",
    "esriFieldTypeGUID": "String",
    "esriFieldTypeGlobalID": "String",
}


def _normalize_esri_field_type(esri_type: str | None) -> str:
    """Map an ESRI field type to an OGR field-type name (default "String")."""
    if not esri_type:
        return "String"
    return _ESRI_FIELD_TYPE_MAP.get(esri_type, "String")


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
        logger.warning(
            "ArcGIS error response: url=%s code=%s message=%s", base_url, code, message
        )
        if code in (498, 499):  # Invalid/expired token
            raise ArcGISTokenError(code, message)
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
                "title": layer.get("title"),
                "geometry_type": _normalize_esri_geom_type(layer.get("geometryType")),
                "type": "layer",
                "object_id_field": layer.get("objectIdField")
                or service_oid
                or "OBJECTID",
            }
        )

    for table in data.get("tables", []):
        layers.append(
            {
                "id": table["id"],
                "name": table["name"],
                "title": table.get("title"),
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
                # ArcGIS may return HTTP 200 with error in JSON body
                if "error" in data:
                    return {**layer, "feature_count": None}
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


async def fetch_arcgis_feature_count(
    base_url: str,
    layer_id: int | str,
    client: httpx.AsyncClient,
    token: str | None = None,
) -> int | None:
    """Fetch a layer feature count from ArcGIS REST query metadata."""
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")
    params: dict[str, str] = {
        "where": "1=1",
        "returnCountOnly": "true",
        "f": "json",
    }
    if token:
        params["token"] = token

    resp = await client.get(f"{base}/{safe_layer_id}/query", params=params)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        error_info = data["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        if code in (498, 499):
            raise ArcGISTokenError(code, message)
        return None

    count = data.get("count")
    if isinstance(count, int) and count >= 0:
        return count
    return None


async def fetch_arcgis_max_record_count(
    base_url: str,
    layer_id: int | str,
    client: httpx.AsyncClient,
    token: str | None = None,
) -> int | None:
    """Fetch an ArcGIS layer's advertised maximum page size."""
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")
    params: dict[str, str] = {"f": "json"}
    if token:
        params["token"] = token

    try:
        resp = await client.get(f"{base}/{safe_layer_id}", params=params)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return None

    if "error" in data:
        error_info = data["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        if code in (498, 499):
            raise ArcGISTokenError(code, message)
        return None

    value = data.get("maxRecordCount")
    if isinstance(value, int) and value > 0:
        return value
    return None


async def fetch_arcgis_layer_preview(
    base_url: str,
    layer_id: int | str,
    client: httpx.AsyncClient,
    token: str | None = None,
    sample_limit: int = 5,
) -> dict:
    """Preview an ArcGIS FeatureServer/MapServer layer from REST metadata.

    GDAL's ESRIJSON driver ignores ``resultRecordCount`` and paginates the
    *whole* layer to build an ogrinfo preview, which times out on large
    layers (millions of rows). The native ArcGIS ``?f=json`` layer metadata
    endpoint returns the field list, geometry type, and CRS in a single fast
    call; a second ``/query`` call with ``resultRecordCount`` fetches a small
    sample. This bypasses GDAL entirely for the preview path.

    Returns a dict with the same shape ``run_service_preview`` returns:
    keys ``srid``, ``geometry_type``, ``layer_name``, ``feature_count``,
    ``columns``, ``sample_rows``.

    Raises ``ArcGISTokenError`` on token errors so the router can surface a
    403. Other HTTP/parse failures raise ``httpx.HTTPError``/``ValueError``.
    """
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")

    # --- Layer metadata: fields, geometry type, CRS, name ---
    # Pass query params via httpx so a token containing URL-reserved characters
    # (+, &, %) is percent-encoded instead of corrupting the query string.
    meta_params: dict[str, str] = {"f": "json"}
    if token:
        meta_params["token"] = token
    resp = await client.get(f"{base}/{safe_layer_id}", params=meta_params)
    resp.raise_for_status()
    meta = resp.json()

    if "error" in meta:
        error_info = meta["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        if code in (498, 499):
            raise ArcGISTokenError(code, message)
        raise ValueError(f"ArcGIS layer metadata error ({code}): {message}")

    columns = [
        {
            "name": field.get("name"),
            "type": _normalize_esri_field_type(field.get("type")),
        }
        for field in meta.get("fields", [])
        if field.get("type") != "esriFieldTypeGeometry" and field.get("name")
    ]

    geometry_type = _normalize_esri_geom_type(meta.get("geometryType"))

    # CRS: prefer extent.spatialReference (latestWkid wins over wkid).
    srid: int | None = None
    spatial_ref = (meta.get("extent") or {}).get("spatialReference") or {}
    if isinstance(spatial_ref, dict):
        srid = spatial_ref.get("latestWkid") or spatial_ref.get("wkid")
    if not isinstance(srid, int):
        srid = None

    layer_name = meta.get("name")

    # --- Sample rows: small bounded query ---
    sample_rows: list[dict] = []
    query_params: dict[str, str] = {
        "where": "1=1",
        "outFields": "*",
        "resultRecordCount": str(sample_limit),
        "f": "json",
    }
    if token:
        query_params["token"] = token
    try:
        sample_resp = await client.get(
            f"{base}/{safe_layer_id}/query", params=query_params
        )
        sample_resp.raise_for_status()
        sample_data = sample_resp.json()
        if "error" not in sample_data:
            # ArcGIS query responses carry attributes under ``attributes``.
            sample_rows = [
                feat.get("attributes", {}) for feat in sample_data.get("features", [])
            ]
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug(
            "ArcGIS sample-row fetch failed for %s/%s: %s",
            base,
            safe_layer_id,
            exc,
        )

    return {
        "srid": srid,
        "geometry_type": geometry_type,
        "layer_name": layer_name,
        "feature_count": None,
        "columns": columns,
        "sample_rows": sample_rows,
    }
