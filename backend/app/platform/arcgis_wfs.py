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
from urllib.parse import unquote, urlsplit

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
    SSRFResolutionError,
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
    _wfs_capabilities_node,
    _url_add_kvp,
    _url_get_value,
    _wfs_feature_types,
    _wfs_layer_name,
    _wfs_root,
    _xml_value,
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
# The read keys GDAL passes on to the server, which can narrow the features
# an import gets but not the total a hits read states.
SUBSET_KEYS = ("STARTINDEX", "COUNT", "MAXFEATURES")
_DEFAULT_VERSION = "2.0.0"
# xsd:nonNegativeInteger: an optional "+" and leading zeros; more than 19
# significant digits is no feature count, so it reads as unknown.
_COUNT = re.compile(r"\+?0*([0-9]{1,19})")


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
    return _count(root.get("numberMatched") or root.get("numberOfFeatures") or "")


def _count(value: str) -> int | None:
    count = _COUNT.fullmatch(value.strip(" \t\r\n"))
    return int(count.group(1)) if count else None


def url_subset(url: str) -> dict[str, int]:
    """The `SUBSET_KEYS` ``url`` sets to a positive count, by key: the first
    query parameter whose whole name matches without case. A zero or
    unparsable value narrows nothing."""
    values: dict[str, str] = {}
    for pair in url.partition("?")[2].split("&"):
        name, _, value = pair.partition("=")
        if name.isascii() and name.upper() in SUBSET_KEYS:
            values.setdefault(name.upper(), value)
    counts = {key: _count(unquote(value)) for key, value in values.items()}
    return {key: count for key, count in counts.items() if count}


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
    # HTTP 401/403: the service answered, refusing this caller.
    refused: bool = False


async def _read(
    target: str,
    credential_line: str | None,
    on_first_request: Callable[[], None] | None,
) -> _Answer | None:
    """One bounded read that accepts gzip, and the URL it ended on, or None
    when it fails. An HTTP 401 or 403 is an empty answer marked ``refused``.

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
    except httpx.HTTPStatusError as exc:
        logger.warning("arcgis_wfs_read_failed", error_class=type(exc).__name__)
        if exc.response.status_code in (401, 403):
            return _Answer(b"", str(exc.response.url), refused=True)
        return None
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


class WfsService(NamedTuple):
    """What recognised an ArcGIS WFS (None for another server), the WFS
    version its reads speak, and the feature type names it advertises."""

    evidence: EsriEvidence | None
    version: str
    names: tuple[str, ...] = ()

    def type_name(self, requested: str) -> str:
        """The advertised name GDAL opens for ``requested``, else ``requested``."""
        return _wfs_layer_name(list(self.names), requested) or requested


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
) -> WfsService | None:
    """The WFS ``url`` reaches, with ``evidence`` None for any other server.

    A URL naming the service decides on its own. Otherwise GetCapabilities
    does: the URL it ended on after redirects, the operation endpoints it
    advertises, or an output format only ArcGIS lists. Anything that isn't
    a capabilities document (a failed or unresolved read, a status error, a
    body over its bound, an exception report) is retried after each of
    `RECOGNITION_RETRY_DELAYS`, then raises `CapabilitiesUnreadableError`:
    unrecognised, an ArcGIS layer would be imported unchecked. None is
    returned only for an HTTP 401 or 403 or an address the SSRF policy
    refuses on a URL that doesn't name the service: GDAL is refused the
    same way.

    The version is the one GetCapabilities answers in, read as GDAL reads
    it, whatever the URL names. GetCapabilities isn't read when the URL
    names both the service and a version; then, when that read fails, or
    when an ArcGIS WFS states no version, it is the URL's own, else 2.0.0.
    """
    version = _url_version(url)
    evidence = esri_evidence("wfs", url)
    if evidence is not None and version is not None:
        return WfsService(evidence, version)
    if evidence is None:
        try:
            await validate_url_for_ssrf(_capabilities_url(url))
        except SSRFResolutionError:
            # A lookup that failed is no answer; each read below retries it.
            pass
        except SSRFError as exc:
            logger.warning("arcgis_wfs_read_failed", error_class=type(exc).__name__)
            return None
    answer, root = await _read_capabilities(
        url, credential_line, on_first_request, retry=evidence is None
    )
    if evidence is None:
        if answer is not None and answer.refused:
            # GDAL is refused the same way and reports the credential hint.
            return None
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
    if root is None:
        return WfsService(evidence, version or _DEFAULT_VERSION)
    answered, names = _wfs_feature_types(root)
    if evidence is not None and not _xml_value(root, "version"):
        answered = version or _DEFAULT_VERSION
    # GDAL lists only the advertised types a TYPENAME (else TYPENAMES) in the
    # URL selects, matched without case.
    selector = _url_get_value(url, "TYPENAME") or _url_get_value(url, "TYPENAMES")
    if selector:
        selected = {name.lower() for name in unquote(selector).split(",")}
        names = [name for name in names if name.lower() in selected]
    return WfsService(evidence, answered, tuple(names))


async def _read_capabilities(
    url: str,
    credential_line: str | None,
    on_first_request: Callable[[], None] | None,
    *,
    retry: bool,
) -> tuple[_Answer | None, object | None]:
    """GetCapabilities and its ``WFS_Capabilities`` node, either None when
    unread. An exception report or any other document counts as unread."""
    pauses = (*RECOGNITION_RETRY_DELAYS, None) if retry else (None,)
    answer = root = None
    for pause in pauses:
        answer = await _read(_capabilities_url(url), credential_line, on_first_request)
        root = None if answer is None else _root(answer.body)
        root = None if root is None else _wfs_capabilities_node(root)
        if root is not None or pause is None or (answer and answer.refused):
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
