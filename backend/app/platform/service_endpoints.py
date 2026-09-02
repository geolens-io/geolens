"""Where a service says its own operations live, and whether we may believe it.

fix(#1746 B2b review r13). GDAL applies ``GDAL_HTTP_HEADER_FILE`` to every
request it makes, and for WFS and OGC API Features it does not only fetch the
URL it was given. It reads the service's own description and then fetches the
operation endpoints that description advertises. A WFS capabilities document
names its ``GetFeature`` endpoint in ``OperationsMetadata``, and an OGC API
landing page and collection document name theirs in ``links``. Those are fresh
requests, so nothing about redirects covers them:
``CPL_VSIL_CURL_AUTHORIZATION_HEADER_ALLOWED_IF_REDIRECT`` never applies, and
it would not cover a service-chosen header name even if it did.

So a service that answers its capabilities honestly and advertises
``https://collector.example/wfs`` as its GetFeature endpoint is handed the
caller's basic credential or named API key by GDAL, without a redirect, without
a 3xx, and without anything in this codebase having decided to send it there.
That is the same question ``make_safe_client`` refuses on a redirect hop and
``_resolve_conformance`` refuses for a link the document chose, asked once more
about a document GDAL reads rather than one we do.

The check is only run for a CREDENTIALED source. A public service advertising a
cross-origin endpoint is an ordinary federated deployment and is left alone;
what makes it a problem is a credential following the advertisement.

Failing open when the document cannot be read is deliberate, and it is the same
trade ``_require_service_token_if_marked`` records for its probe: this is one
request against a third party, and turning its bad day into a refused import
would be worse than the exposure it closes. What it refuses is a document that
was read and DOES advertise a foreign origin. The residual is a service that
can serve a different document to this client than to GDAL, which is bounded
operationally like the rest of the GDAL path (AGENTS.md Rule 2).

Lives in ``platform/`` because both callers are in layers that may not import
each other: ``modules/catalog`` for the probe and preview doors, and
``processing/ingest`` for the worker that runs the same source through ogr2ogr
minutes later. Both check, because the document can change in between.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import defusedxml.ElementTree as ET
import httpx
import structlog

from app.core.service_tokens import requires_header_token_policy
from app.platform.security import (
    PROBE_TIMEOUT,
    SSRFError,
    make_safe_client,
    same_origin,
    validate_url_for_ssrf,
)

logger = structlog.stdlib.get_logger(__name__)

CROSS_ORIGIN_ENDPOINT_CODE = "cross_origin_endpoint"

# Describes the policy and never a credential. The offending ORIGIN is appended
# by the exception, which is safe: an origin is a scheme, a host and a port,
# and the parser drops any userinfo before it gets here.
CROSS_ORIGIN_ENDPOINT_POLICY = (
    "This service advertises an operation endpoint on a different origin, and "
    "this request carries a credential. GDAL sends the credential to whichever "
    "address the service names, so a credentialed import is refused rather "
    "than handing it to a host you did not point at. Import it without a "
    "credential, or ask the service operator why it advertises another origin."
)

# The OGC API link relations that name something a client FETCHES. Deliberately
# not every rel: `license`, `describedby` and `alternate` legitimately point at
# other origins on ordinary services, and refusing those would refuse the web.
_OGCAPI_OPERATION_RELS = frozenset({"conformance", "data", "items", "self"})

# One collections page is enough to see how a service addresses its items; a
# catalogue with hundreds of collections should not cost hundreds of parses.
_MAX_COLLECTIONS_INSPECTED = 50


class CrossOriginEndpointError(Exception):
    """A credentialed source advertises an operation endpoint somewhere else."""

    def __init__(self, origin: str) -> None:
        self.origin = origin
        self.code = CROSS_ORIGIN_ENDPOINT_CODE
        # Which half of the request the caller has to change, for a door that
        # renders errors against the URL field rather than the credential one.
        self.field = "url"
        self.policy = f"{CROSS_ORIGIN_ENDPOINT_POLICY} Advertised origin: {origin}"
        super().__init__(self.policy)


def _origin_of(url: str) -> str:
    """``scheme://host:port`` for a message, with userinfo and path dropped."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port else ""
    return f"{(parsed.scheme or '').lower()}://{host}{port}"


def _capabilities_url(url: str) -> str:
    """The GetCapabilities form of a WFS URL, preserving existing parameters.

    Built here rather than imported from the probe adapter, which is in a layer
    this module may not reach. The two agree on the only thing that matters,
    which is that the service and request parameters win over whatever the
    caller's URL carried.
    """
    parsed = urlparse(url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    params["service"] = "WFS"
    params["request"] = "GetCapabilities"
    return urlunparse(parsed._replace(query=urlencode(params)))


def _wfs_operation_hrefs(xml_text: str) -> list[str]:
    """Every operation endpoint a capabilities document advertises.

    Namespace-agnostic by local name, the way ``parse_wfs_capabilities`` walks
    the same document, because WFS 1.0, 1.1 and 2.0 spell the namespaces
    differently. Parsed with defusedxml: this document is untrusted by
    definition, and it is the document the whole check exists to distrust.
    """
    hrefs: list[str] = []
    root = ET.fromstring(xml_text)
    for element in root.iter():
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
        if tag not in ("Get", "Post"):
            continue
        for name, value in element.attrib.items():
            # `xlink:href`, whatever prefix the document bound xlink to.
            if name.split("}")[-1] == "href" and value:
                hrefs.append(value)
    return hrefs


def _ogcapi_link_hrefs(document: object) -> list[str]:
    """The operation endpoints one OGC API document advertises."""
    if not isinstance(document, dict):
        return []
    hrefs: list[str] = []
    for link in document.get("links", []) or []:
        if not isinstance(link, dict):
            continue
        if link.get("rel") in _OGCAPI_OPERATION_RELS and link.get("href"):
            hrefs.append(str(link["href"]))
    return hrefs


def _assert_same_origin(url: str, hrefs: list[str]) -> None:
    """Refuse the first advertised endpoint that leaves the submitted origin.

    Relative hrefs resolve against the submitted URL, so a service that
    advertises ``/wfs`` or ``collections/x/items`` is describing itself and
    passes. An href that cannot be parsed at all is refused, because
    ``same_origin`` answers False for it and an address this cannot read is not
    one to send a credential to.
    """
    for href in hrefs:
        resolved = urljoin(url, href)
        if not same_origin(url, resolved):
            raise CrossOriginEndpointError(_origin_of(resolved))


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        await validate_url_for_ssrf(url)
        response = await client.get(url)
        response.raise_for_status()
        return response.text
    except (httpx.HTTPError, SSRFError, ValueError) as exc:
        logger.debug("service endpoint check could not read a document", error=str(exc))
        return None


async def _check_wfs(client: httpx.AsyncClient, url: str) -> None:
    xml_text = await _fetch_text(client, _capabilities_url(url))
    if xml_text is None:
        return
    try:
        hrefs = _wfs_operation_hrefs(xml_text)
    except ET.ParseError:
        return
    _assert_same_origin(url, hrefs)


async def _check_ogcapi(client: httpx.AsyncClient, url: str) -> None:
    landing = await _fetch_text(client, url)
    if landing is None:
        return
    try:
        document = json.loads(landing)
    except ValueError:
        return
    _assert_same_origin(url, _ogcapi_link_hrefs(document))

    collections_text = await _fetch_text(client, url.rstrip("/") + "/collections")
    if collections_text is None:
        return
    try:
        collections_doc = json.loads(collections_text)
    except ValueError:
        return
    if not isinstance(collections_doc, dict):
        return
    _assert_same_origin(url, _ogcapi_link_hrefs(collections_doc))
    collections = collections_doc.get("collections") or []
    if not isinstance(collections, list):
        return
    for collection in collections[:_MAX_COLLECTIONS_INSPECTED]:
        _assert_same_origin(url, _ogcapi_link_hrefs(collection))


async def assert_endpoints_stay_on_origin(
    url: str,
    *,
    service_format: str | None,
    has_credential: bool,
    credential_header: str | None = None,
) -> None:
    """Refuse a credentialed source that advertises a foreign operation endpoint.

    Does nothing without a credential, and nothing for a service format whose
    credential does not travel to GDAL as a header. Raises
    :class:`CrossOriginEndpointError`, which every caller turns into a coded
    refusal naming the URL field.

    ``credential_header`` is declared to the client for the same reason every
    other credentialed fetch declares it, even though this one sends no
    credential: it costs nothing and it keeps the rule that a client which
    could carry one is built the same way everywhere.
    """
    if not has_credential or not requires_header_token_policy(service_format):
        return
    async with make_safe_client(
        timeout=PROBE_TIMEOUT, credential_header=credential_header
    ) as client:
        if service_format == "wfs":
            await _check_wfs(client, url)
        else:
            await _check_ogcapi(client, url)
