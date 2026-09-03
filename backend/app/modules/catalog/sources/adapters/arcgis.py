"""ArcGIS REST API probing, URL normalization, and service type detection."""

import asyncio
import json
import re
from urllib.parse import quote, urlencode, urlparse

import httpx
import structlog

from app.core.url_redaction import redact_exception_text
from app.platform.probe_bounds import bounded_probe_read
from app.platform.service_endpoints import (
    DEFAULT_CHECK_TIMEOUT,
    OGC_JSON_ACCEPT,
    EndpointCheckFailedError,
)

logger = structlog.stdlib.get_logger(__name__)

# What this adapter is, in the vocabulary ``build_credential_header`` reads.
# Deliberately absent from ``HEADER_AUTH_SERVICE_FORMATS``: an ArcGIS token is
# percent-encoded into the service URL, so the builder answers None for it and
# no header is ever composed for this transport (plan D9).
ARCGIS_SERVICE_FORMAT = "arcgis_featureserver"


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


def _extract_arcgis_object_id_field(data: dict) -> str | None:
    value = data.get("objectIdField")
    if isinstance(value, str) and value.strip():
        return value.strip()

    fields = data.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if not isinstance(field, dict):
                continue
            if field.get("type") != "esriFieldTypeOID":
                continue
            name = field.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()

    unique_id_field = data.get("uniqueIdField")
    if isinstance(unique_id_field, dict):
        name = unique_id_field.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()

    return None


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

    fix(#1770 round 41 P1): the whole function runs under
    ``DEFAULT_CHECK_TIMEOUT``, same reasoning as ``probe_ogcapi``.
    """
    try:
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            return await _probe_arcgis_service_within_deadline(base_url, client, token)
    except TimeoutError:
        logger.debug("ArcGIS probe: deadline exceeded for %s", base_url)
        return None


async def _probe_arcgis_service_within_deadline(
    base_url: str, client: httpx.AsyncClient, token: str | None
) -> dict | None:
    """``probe_arcgis_service``'s body, split out so the deadline wraps all
    of it. ``ArcGISTokenError`` still propagates through the deadline
    unchanged: it is not a `TimeoutError`, so the wrapper's `except
    TimeoutError` does not intercept it.
    """
    try:
        # fix(#1746 codex r7): percent-encode the token before concatenating it
        # into the URL -- a URL-reserved character in a raw token (', #, &)
        # can change what the request means and, in a log line, end the
        # URL_LIKE_RE match early enough to escape the redactor entirely.
        query = f"{base_url}?f=json" + (
            f"&token={quote(token, safe='')}" if token else ""
        )
        # fix(#1770 round 41 P1): bounded read, not a plain `client.get` --
        # see `bounded_probe_read`'s docstring. `EndpointCheckFailedError`
        # joins the two httpx types this already caught: whatever the cause,
        # this degrades to "not an ArcGIS service" the same way.
        body, _ = await bounded_probe_read(
            client, query, headers={}, accept=OGC_JSON_ACCEPT
        )
    except (
        httpx.HTTPStatusError,
        httpx.TransportError,
        EndpointCheckFailedError,
    ) as exc:
        # fix(#1770 round 39): this request embeds OUR OWN token in the URL
        # (see the fix(#1746 codex r7) comment above) -- an HTTPStatusError's
        # message quotes that whole URL back, so the caught exception's text
        # must be redacted, not just the href a response body carries.
        logger.debug(
            "ArcGIS probe failed for %s: %s", base_url, redact_exception_text(exc)
        )
        return None

    try:
        data = json.loads(body)
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
            # fix(#1746 codex r7): same percent-encoding as probe_arcgis_service
            # above -- see its comment.
            url = (
                f"{base_url}/{layer_id}/query?where=1%3D1&returnCountOnly=true&f=json"
            ) + (f"&token={quote(token, safe='')}" if token else "")
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


def build_arcgis_count_query_url(layer_url: str, token: str | None = None) -> str:
    """The bounded count query for one FeatureServer layer.

    ``<layer>/query?where=1=1&returnCountOnly=true&f=json`` — the smallest
    request that exercises the QUERY operation, which is the operation
    ``build_gdal_source`` composes and the worker actually reads. It returns a
    single integer no matter how large the layer is, so it is safe to issue
    against anything.

    fix(#1746 codex r6): extracted so the health probe can ask the same
    question this function asks. A deployment that serves layer METADATA
    publicly while gating ``/query`` is ordinary, and a probe of the layer
    document would call it healthy and then fail in the worker. One builder,
    so the probe and the count fetcher cannot drift into probing one endpoint
    and depending on another.
    """
    # A stored origin_uri is provenance, not a curated endpoint: it can carry
    # a query string, a fragment, or an already-appended /query. Strip all
    # three before composing, the same way `normalize_arcgis_url` does, so the
    # result is an endpoint rather than `.../0?f=html/query?...`.
    clean = urlparse(layer_url)._replace(query="", fragment="").geturl().rstrip("/")
    if clean.lower().endswith("/query"):
        clean = clean[: -len("/query")].rstrip("/")
    params: dict[str, str] = {
        "where": "1=1",
        "returnCountOnly": "true",
        "f": "json",
    }
    if token:
        params["token"] = token
    return f"{clean}/query?{urlencode(params)}"


async def fetch_arcgis_feature_count(
    base_url: str,
    layer_id: int | str,
    client: httpx.AsyncClient,
    token: str | None = None,
) -> int | None:
    """Fetch a layer feature count from ArcGIS REST query metadata."""
    base = base_url.rstrip("/")
    safe_layer_id = str(layer_id).strip("/")

    resp = await client.get(
        build_arcgis_count_query_url(f"{base}/{safe_layer_id}", token)
    )
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


async def fetch_arcgis_pagination_info(
    base_url: str,
    layer_id: int | str,
    client: httpx.AsyncClient,
    token: str | None = None,
) -> tuple[int | None, bool, str | None]:
    """Fetch ArcGIS pagination support, page size, and stable order field."""
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
        return None, False, None

    if "error" in data:
        error_info = data["error"]
        code = error_info.get("code", 0)
        message = error_info.get("message", "Unknown ArcGIS error")
        if code in (498, 499):
            raise ArcGISTokenError(code, message)
        return None, False, None

    value = data.get("maxRecordCount")
    max_record_count = value if isinstance(value, int) and value > 0 else None
    advanced = data.get("advancedQueryCapabilities") or {}
    supports_pagination = (
        isinstance(advanced, dict) and advanced.get("supportsPagination") is True
    )
    return max_record_count, supports_pagination, _extract_arcgis_object_id_field(data)


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
            redact_exception_text(exc),
        )

    # fix(#1746): the preview previously always returned feature_count=None;
    # reuse the existing returnCountOnly=true helper (same safe client, one
    # extra request) so the preview matches the count the probe already shows.
    # A count failure degrades to None rather than failing the whole preview.
    feature_count: int | None = None
    try:
        feature_count = await fetch_arcgis_feature_count(
            base, safe_layer_id, client, token=token
        )
    except (httpx.HTTPError, ValueError, ArcGISTokenError) as exc:
        logger.debug(
            "ArcGIS feature-count fetch failed for %s/%s: %s",
            base,
            safe_layer_id,
            redact_exception_text(exc),
        )

    return {
        "srid": srid,
        "geometry_type": geometry_type,
        "layer_name": layer_name,
        "feature_count": feature_count,
        "columns": columns,
        "sample_rows": sample_rows,
    }
