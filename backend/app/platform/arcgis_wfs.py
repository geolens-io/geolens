"""What an ArcGIS WFS layer holds and how it pages, asked before an import.

Some ArcGIS WFS services read ``COUNT`` as an end index rather than a page
size, so GDAL's paged reads stop after the first page. A one-feature probe
tells the two apart, and those imports read unpaged. Every import is
compared with the ``resultType=hits`` total, so neither a server-side cap
nor a repeated page can pass for the whole layer.
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


def wfs_url(url: str, layer: str, **params: str) -> str:
    """A GetFeature request for ``layer`` on the caller's URL, keeping its
    other parameters (such as a ``token``)."""
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
        *params.items(),
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def _root(body: bytes):
    try:
        return ET.fromstring(body)
    except Exception:  # broad: defusedxml raises parse and policy errors alike
        return None


def number_matched(body: bytes) -> int | None:
    """The response's ``numberMatched``, or None when it is absent or not a count."""
    root = _root(body)
    value = "" if root is None else root.get("numberMatched", "")
    return int(value) if value.isdigit() else None


def features_returned(body: bytes) -> int | None:
    """How many ``member`` features a WFS 2.0 response carries, or None
    when it can't be read."""
    root = _root(body)
    if root is None:
        return None
    return sum(1 for child in root if str(child.tag).rsplit("}", 1)[-1] == "member")


async def _read(target: str, credential_line: str | None) -> bytes | None:
    """One bounded, identity-encoded read, or None when it fails."""
    headers = credential_headers(credential_line) if credential_line else {}
    try:
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
        logger.warning("arcgis_wfs_read_failed", error_class=type(exc).__name__)
        return None
    return body


async def fetch_arcgis_wfs_hits(
    url: str, layer: str, *, credential_line: str | None
) -> int | None:
    """The layer's total from a ``resultType=hits`` read, or None when the
    service doesn't say. Never raises for the service's answer: the import
    goes ahead without a count to check."""
    try:
        target = wfs_url(url, layer, RESULTTYPE="hits")
    except ValueError:
        return None
    body = await _read(target, credential_line)
    return None if body is None else number_matched(body)


async def arcgis_wfs_pages_by_count(
    url: str, layer: str, *, credential_line: str | None
) -> bool:
    """Whether ``COUNT`` is a page size here: ``STARTINDEX=1&COUNT=1``
    returns exactly one feature. A server that reads it as an end index
    returns none; any failure also answers False, so paging goes off."""
    try:
        target = wfs_url(url, layer, STARTINDEX="1", COUNT="1")
    except ValueError:
        return False
    body = await _read(target, credential_line)
    return body is not None and features_returned(body) == 1
