"""How many features an ArcGIS WFS layer holds, asked before an import.

ArcGIS WFS reads ``COUNT`` as an end index rather than a page size, so
GDAL's paged reads stop after the first page. Imports read it unpaged
instead, and compare what arrived with the ``resultType=hits`` total so a
server-side cap can't pass for the whole layer.
"""

import asyncio
from urllib.parse import urlencode, urlsplit, urlunsplit

import defusedxml.ElementTree as ET
import httpx
import structlog

from app.platform.probe_bounds import bounded_probe_read
from app.platform.security import (
    PROBE_TIMEOUT,
    SSRFError,
    make_safe_client,
    validate_url_for_ssrf,
)
from app.platform.service_endpoints import (
    DEFAULT_CHECK_TIMEOUT,
    WFS_XML_ACCEPT,
    EndpointCheckFailedError,
    bounded_parse_qsl,
    credential_headers,
)

logger = structlog.stdlib.get_logger(__name__)

# The request a hits read defines for itself; the caller's other parameters,
# such as a `token`, stay on the URL.
_OWN_PARAMETERS = frozenset(
    {
        "service",
        "version",
        "request",
        "typename",
        "typenames",
        "resulttype",
        "count",
        "maxfeatures",
        "startindex",
        "outputformat",
    }
)


def is_arcgis_wfs(url: str | None) -> bool:
    """Whether a WFS URL is an ArcGIS ``WFSServer`` endpoint."""
    return bool(url) and urlsplit(url).path.lower().endswith("/wfsserver")


def hits_url(url: str, layer: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in bounded_parse_qsl(parts.query)
        if key.lower() not in _OWN_PARAMETERS
    ]
    query += [
        ("SERVICE", "WFS"),
        ("VERSION", "2.0.0"),
        ("REQUEST", "GetFeature"),
        ("TYPENAMES", layer),
        ("RESULTTYPE", "hits"),
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def number_matched(body: bytes) -> int | None:
    """The response's ``numberMatched``, or None when it is absent or not a count."""
    try:
        value = ET.fromstring(body).get("numberMatched", "")
    except (
        Exception
    ):  # broad: defusedxml raises parse and policy errors alike; no count
        return None
    return int(value) if value.isdigit() else None


async def fetch_arcgis_wfs_hits(
    url: str, layer: str, *, credential_line: str | None
) -> int | None:
    """The layer's total from a ``resultType=hits`` read, or None when the
    service doesn't say. Never raises for the service's answer: the import
    goes ahead without a count to check."""
    headers = credential_headers(credential_line) if credential_line else {}
    try:
        target = hits_url(url, layer)
        await validate_url_for_ssrf(target)
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            async with make_safe_client(
                timeout=PROBE_TIMEOUT, credential_header=next(iter(headers), None)
            ) as client:
                body, _ = await bounded_probe_read(
                    client, target, headers=headers, accept=WFS_XML_ACCEPT
                )
    except (
        TimeoutError,
        httpx.HTTPError,
        SSRFError,
        EndpointCheckFailedError,
        ValueError,
    ) as exc:
        logger.warning("arcgis_wfs_hits_unavailable", error_class=type(exc).__name__)
        return None
    return number_matched(body)
