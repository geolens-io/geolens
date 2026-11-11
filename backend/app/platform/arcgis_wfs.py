"""What an ArcGIS WFS layer holds and how it pages, asked before an import.

Some ArcGIS WFS services read ``COUNT`` as an end index rather than a page
size, so GDAL's paged reads stop after the first page. A one-feature probe
tells the two apart, and those imports read unpaged. Every import is
compared with the ``resultType=hits`` total, so neither a server-side cap
nor a repeated page can pass for the whole layer.
"""

import asyncio
import re
from collections.abc import Callable
from urllib.parse import urlsplit

import defusedxml.ElementTree as ET
import httpx
import structlog

from app.platform.egress_proxy import pinned_origin
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
    _capabilities_url,
    _url_add_kvp,
    bounded_parse_qsl,
    credential_headers,
)

logger = structlog.stdlib.get_logger(__name__)

# The keys a read sets or must not carry; every other parameter of the
# caller's URL, such as a `token`, stays as submitted.
_READ_KEYS = (
    "TYPENAME",
    "TYPENAMES",
    "RESULTTYPE",
    "COUNT",
    "MAXFEATURES",
    "STARTINDEX",
    "OUTPUTFORMAT",
)
_DEFAULT_VERSION = "2.0.0"
_COUNT = re.compile("[0-9]+")


def wfs_url(url: str, layer: str, *, version: str, **params: str) -> str:
    """A GetFeature request for ``layer`` in WFS ``version`` on the caller's
    URL, spelled as GDAL's WFS driver spells its own requests."""
    request = url
    for key in _READ_KEYS:
        request = _url_add_kvp(request, key, None)
    type_names = "TYPENAMES" if version.startswith("2") else "TYPENAME"
    for key, value in (
        ("SERVICE", "WFS"),
        ("VERSION", version),
        ("REQUEST", "GetFeature"),
        (type_names, layer),
        *params.items(),
    ):
        request = _url_add_kvp(request, key, value)
    return request


def _root(body: bytes):
    try:
        return ET.fromstring(body)
    except Exception:  # broad: defusedxml raises parse and policy errors alike
        return None


def number_matched(body: bytes) -> int | None:
    """A hits response's total: ``numberMatched`` (WFS 2.0) or
    ``numberOfFeatures`` (1.1), or None when absent or not a count."""
    root = _root(body)
    if root is None:
        return None
    value = root.get("numberMatched") or root.get("numberOfFeatures") or ""
    return int(value) if _COUNT.fullmatch(value) else None


def features_returned(body: bytes) -> int | None:
    """How many features a GetFeature response carries (``member`` in 2.0,
    ``featureMember`` in 1.1), or None when it can't be read."""
    root = _root(body)
    if root is None:
        return None
    return sum(
        1
        for child in root
        if str(child.tag).rsplit("}", 1)[-1] in ("member", "featureMember")
    )


async def _read(
    target: str,
    credential_line: str | None,
    on_first_request: Callable[[], None] | None,
) -> bytes | None:
    """One bounded, identity-encoded read, or None when it fails.

    ``on_first_request`` fires once the target has passed SSRF validation,
    right before the request, as `fetch_document` does. A ``token`` in the
    query holds every hop to the origin, as it does the GDAL run.
    """
    headers = credential_headers(credential_line) if credential_line else {}
    try:
        await validate_url_for_ssrf(target)
        if on_first_request is not None:
            on_first_request()
        async with asyncio.timeout(DEFAULT_CHECK_TIMEOUT):
            async with make_safe_client(
                timeout=PROBE_TIMEOUT, credential_header=next(iter(headers), None)
            ) as client:
                body, _ = await bounded_probe_read(
                    client,
                    target,
                    headers=headers,
                    accept=WFS_XML_ACCEPT,
                    credential_in_query=pinned_origin(target, credential=False)
                    is not None,
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


async def arcgis_wfs_version(
    url: str,
    *,
    credential_line: str | None,
    on_first_request: Callable[[], None] | None = None,
) -> str:
    """The WFS version the import's reads speak: the URL's own ``version``,
    else the one GetCapabilities answers in, as GDAL settles on it, else
    2.0.0."""
    try:
        pairs = bounded_parse_qsl(urlsplit(url).query)
    except ValueError:
        return _DEFAULT_VERSION
    version = next((v for k, v in pairs if k.lower() == "version" and v), None)
    if version is not None:
        return version
    body = await _read(_capabilities_url(url), credential_line, on_first_request)
    root = None if body is None else _root(body)
    answered = None if root is None else root.get("version")
    return answered or _DEFAULT_VERSION


async def fetch_arcgis_wfs_hits(
    url: str,
    layer: str,
    *,
    credential_line: str | None,
    version: str = _DEFAULT_VERSION,
    on_first_request: Callable[[], None] | None = None,
) -> int | None:
    """The layer's total from a ``resultType=hits`` read, or None when the
    service doesn't say. Never raises for the service's answer."""
    target = wfs_url(url, layer, version=version, RESULTTYPE="hits")
    body = await _read(target, credential_line, on_first_request)
    return None if body is None else number_matched(body)


async def arcgis_wfs_pages_by_count(
    url: str,
    layer: str,
    *,
    credential_line: str | None,
    version: str = _DEFAULT_VERSION,
    on_first_request: Callable[[], None] | None = None,
) -> bool:
    """Whether ``COUNT`` is a page size here: ``STARTINDEX=1&COUNT=1``
    returns exactly one feature. A server that reads it as an end index
    returns none; any failure, and any version before 2.0, which has no
    ``STARTINDEX``, also answer False, so paging goes off."""
    if not version.startswith("2"):
        return False
    target = wfs_url(url, layer, version=version, STARTINDEX="1", COUNT="1")
    body = await _read(target, credential_line, on_first_request)
    return body is not None and features_returned(body) == 1
