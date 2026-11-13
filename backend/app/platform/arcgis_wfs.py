"""Whether a WFS is ArcGIS's, what its layer holds and how it pages, asked
before an import.

Some ArcGIS WFS services read ``COUNT`` as an end index rather than a page
size, so GDAL's paged reads stop after the first page. A one-feature probe
tells the two apart, and those imports read unpaged. Every import is
compared with the ``resultType=hits`` total, so neither a server-side cap
nor a repeated page can pass for the whole layer.
"""

import asyncio
import re
from collections.abc import Callable
from typing import NamedTuple
from urllib.parse import urlsplit

import httpx
import structlog

from app.platform.egress_proxy import pinned_origin
from app.platform.esri_services import (
    RECOGNITION_RETRY_DELAYS,
    EsriEvidence,
    esri_evidence,
    wfs_format_is_esri,
)
from app.platform.probe_bounds import bounded_probe_exchange
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
    _local_name,
    _operation_hrefs,
    _url_add_kvp,
    _wfs_root,
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
        return _wfs_root(body)
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


class _Answer(NamedTuple):
    body: bytes
    final_url: str


async def _read(
    target: str,
    credential_line: str | None,
    on_first_request: Callable[[], None] | None,
) -> _Answer | None:
    """One bounded read that accepts gzip, and the URL it ended on, or None
    when it fails.

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
                body, response = await bounded_probe_exchange(
                    client,
                    "GET",
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
    return _Answer(body, str(response.url))


class CapabilitiesUnreadableError(Exception):
    """GetCapabilities couldn't be read, so whether ArcGIS serves a WFS whose
    URL doesn't say is unknown."""


class ArcGISWfs(NamedTuple):
    """What recognised an ArcGIS WFS, and the WFS version its reads speak."""

    evidence: EsriEvidence
    version: str


def _url_version(url: str) -> str | None:
    try:
        pairs = bounded_parse_qsl(urlsplit(url).query)
    except ValueError:
        return _DEFAULT_VERSION
    return next((v for k, v in pairs if k.lower() == "version" and v), None)


def _lists_esri_format(root) -> bool:
    return any(
        _local_name(str(element.tag)) == "Value" and wfs_format_is_esri(element.text)
        for element in root.iter()
    )


async def recognise_arcgis_wfs(
    url: str,
    *,
    credential_line: str | None,
    on_first_request: Callable[[], None] | None = None,
) -> ArcGISWfs | None:
    """The ArcGIS WFS ``url`` reaches, or None for any other WFS.

    A URL naming the service decides on its own. Otherwise GetCapabilities
    does: the URL it ended on after redirects, the operation endpoints it
    advertises, or an output format only ArcGIS lists. A read that fails
    or doesn't parse is retried after each of `RECOGNITION_RETRY_DELAYS`,
    then raises `CapabilitiesUnreadableError`: unrecognised, an ArcGIS
    layer would be imported unchecked. An address the SSRF check refuses
    answers None, since GDAL's egress proxy refuses it too.

    The version is the URL's own, else the one GetCapabilities answers in,
    as GDAL settles on it, else 2.0.0; GetCapabilities isn't read when the
    URL names both the service and a version.
    """
    version = _url_version(url)
    evidence = esri_evidence("wfs", url)
    if evidence is not None and version is not None:
        return ArcGISWfs(evidence, version)
    if evidence is None:
        try:
            await validate_url_for_ssrf(_capabilities_url(url))
        except SSRFError as exc:
            logger.warning("arcgis_wfs_read_failed", error_class=type(exc).__name__)
            return None
    answer, root = await _read_capabilities(
        url, credential_line, on_first_request, retry=evidence is None
    )
    if evidence is None:
        if answer is None or root is None:
            raise CapabilitiesUnreadableError()
        evidence = esri_evidence(
            "wfs",
            url,
            final_url=answer.final_url,
            advertised=_operation_hrefs(root),
            marker=_lists_esri_format(root),
        )
        if evidence is not None:
            logger.info("arcgis_wfs_recognised", evidence=evidence)
    if evidence is None:
        return None
    answered = None if root is None else root.get("version")
    return ArcGISWfs(evidence, version or answered or _DEFAULT_VERSION)


async def _read_capabilities(
    url: str,
    credential_line: str | None,
    on_first_request: Callable[[], None] | None,
    *,
    retry: bool,
) -> tuple[_Answer | None, object | None]:
    """GetCapabilities and its parsed root, either None when unread."""
    pauses = (*RECOGNITION_RETRY_DELAYS, None) if retry else (None,)
    answer = root = None
    for pause in pauses:
        answer = await _read(_capabilities_url(url), credential_line, on_first_request)
        root = None if answer is None else _root(answer.body)
        if root is not None or pause is None:
            break
        await asyncio.sleep(pause)
    return answer, root


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
    answer = await _read(target, credential_line, on_first_request)
    return None if answer is None else number_matched(answer.body)


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
    answer = await _read(target, credential_line, on_first_request)
    return answer is not None and features_returned(answer.body) == 1
