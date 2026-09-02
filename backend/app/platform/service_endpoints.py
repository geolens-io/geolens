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

fix(#1746 B2b review r14): the check reads the description WITH the credential,
and fails CLOSED. Reading it anonymously was worse than not reading it at all
on exactly the services this protects: a protected origin answers 401, the
anonymous read learned nothing, the guard approved the source, and GDAL then
authenticated, received the real document, and followed whatever cross-origin
endpoint it advertised. So the same header line the worker will hand GDAL is
sent here first, to the submitted origin and to nothing else, and a description
that cannot be read, does not answer 2xx, or does not parse is a refusal rather
than a pass. A credential-free source is still not checked at all: a public
federated service advertising another origin is ordinary, and the credential is
what makes it a problem.

Lives in ``platform/`` because both callers are in layers that may not import
each other: ``modules/catalog`` for the probe and preview doors, and
``processing/ingest`` for the worker that runs the same source through ogr2ogr
minutes later. Both check, because the document can change in between.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse

import defusedxml.ElementTree as ET
import httpx
import structlog

from app.core.service_tokens import HEADER_LINE_SEPARATOR, requires_header_token_policy
from app.platform.security import (
    PROBE_TIMEOUT,
    SSRFError,
    make_safe_client,
    same_origin,
    validate_url_for_ssrf,
)

logger = structlog.stdlib.get_logger(__name__)

CROSS_ORIGIN_ENDPOINT_CODE = "cross_origin_endpoint"
ENDPOINT_CHECK_FAILED_CODE = "endpoint_check_failed"

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

ENDPOINT_CHECK_FAILED_POLICY = (
    "This service did not return a description GeoLens could read, so where it "
    "sends an authenticated request cannot be established. A credentialed "
    "import is refused rather than guessed at. Check that the URL is the "
    "service endpoint and that the credential is the one it expects, then try "
    "again."
)

# The OGC API link relations that name something a client FETCHES. Deliberately
# not every rel: `license`, `describedby` and `alternate` legitimately point at
# other origins on ordinary services, and refusing those would refuse the web.
_OGCAPI_OPERATION_RELS = frozenset({"conformance", "data", "items", "self"})

# How far the PROBE follows a paginated collections listing. The probe has no
# collection to check, so it walks the listing; the bound is what keeps a
# catalogue with thousands of collections from turning one probe into thousands
# of requests. Reaching it is recorded, never treated as a clean pass, and the
# preview and worker paths do not rely on it: they know which collection they
# are importing and read that document directly.
_MAX_COLLECTION_PAGES = 20


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


class EndpointCheckFailedError(Exception):
    """A credentialed source's description could not be read, so nothing is known.

    fix(#1746 B2b review r14). Failing open here was the reported hole and not
    a conservative default: the services this protects are exactly the ones
    that refuse an unauthenticated description, so "could not read it" was the
    normal answer for them and it approved every one.
    """

    def __init__(self, reason: str) -> None:
        self.code = ENDPOINT_CHECK_FAILED_CODE
        self.field = "url"
        self.policy = ENDPOINT_CHECK_FAILED_POLICY
        # Kept off the message: `reason` is an httpx error string, which can
        # carry the URL and therefore anything in its query.
        self.reason = reason
        super().__init__(self.policy)


def _origin_of(url: str) -> str:
    """``scheme://host:port`` for a message, with userinfo and path dropped.

    fix(#1746 B2b review r15): the port read is guarded. ``urlparse`` defers
    parsing the port until the attribute is read, and raises ValueError on
    something like ``http://example.com:notaport/wfs`` -- which
    ``same_origin`` had already correctly refused, so this ran only while
    BUILDING the refusal and turned a clean 422 into a 500. The URL is
    provider-controlled, so a malformed port is dropped rather than echoed:
    the host and scheme are what the operator needs, and the raw value is not
    something to put in a message or a log line.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        port = ""
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


def _credential_headers(credential_line: str) -> dict[str, str]:
    """The one header the description fetch carries, from the finished line.

    The line is the wire format everything downstream of a door speaks (plan
    D9) and it has already been validated by the door that composed it, so
    this splits rather than re-derives. It is the only place the line is split
    for sending, and it sends to the submitted origin alone: the client refuses
    a cross-origin redirect carrying this header, and the check itself refuses
    a cross-origin endpoint before GDAL ever sees one.
    """
    name, _, value = credential_line.partition(HEADER_LINE_SEPARATOR)
    return {name: value}


# The two ways a WFS capabilities document names an operation endpoint.
# 1.1 and 2.0 use `ows:DCP/ows:HTTP/ows:Get` with `xlink:href`; 1.0 uses
# `DCPType/HTTP/Get` with an `onlineResource` attribute and no xlink at all
# (fix(#1746 B2b review r15): reading only `href` let a 1.0 service advertise a
# cross-origin GetFeature and pass the guard, which is the whole thing this
# check exists to catch). Compared by LOCAL name, because the namespaces and
# the prefixes bound to them differ across the three versions.
_WFS_ENDPOINT_ATTRIBUTES = frozenset({"href", "onlineresource"})


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
            local = name.split("}")[-1].lower()
            if local in _WFS_ENDPOINT_ATTRIBUTES and value:
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


def _next_page(document: object, base: str) -> str | None:
    """The `next` link of a paginated listing, resolved and same-origin only."""
    if not isinstance(document, dict):
        return None
    for link in document.get("links", []) or []:
        if isinstance(link, dict) and link.get("rel") == "next" and link.get("href"):
            try:
                resolved = urljoin(base, str(link["href"]))
            except ValueError:
                # fix(#1746 B2b review r16): same guard as `_assert_same_origin`
                # below, and the sibling of the site the review named. An
                # address the parser cannot read is not one to walk to, and the
                # walk already stops rather than refuses when `next` leaves the
                # origin.
                return None
            return resolved if same_origin(base, resolved) else None
    return None


def _assert_same_origin(url: str, hrefs: list[str]) -> None:
    """Refuse the first advertised endpoint that leaves the submitted origin.

    Relative hrefs resolve against the submitted URL, so a service that
    advertises ``/wfs`` or ``collections/x/items`` is describing itself and
    passes. An href that cannot be parsed at all is refused, because
    ``same_origin`` answers False for it and an address this cannot read is not
    one to send a credential to.
    """
    for href in hrefs:
        try:
            resolved = urljoin(url, href)
        except ValueError:
            # fix(#1746 B2b review r16): `urljoin` raises on some malformed
            # absolute references, and the href comes out of a document this
            # check exists to distrust. An address that cannot even be resolved
            # is not one to send a credential to, so it is refused with the
            # same coded outcome; the raw href is never echoed, because it is
            # provider-controlled and reaches a message and a log line.
            raise CrossOriginEndpointError("unparseable") from None
        if not same_origin(url, resolved):
            raise CrossOriginEndpointError(_origin_of(resolved))


async def _fetch(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> str:
    """One description document, or a refusal.

    THE request site for this module, and deliberately the only one: every
    document the validator reads goes through here, so the SSRF revalidation
    below cannot be forgotten at a new call site and there is exactly one
    suppression marker to keep correct. ``test_service_auth_transport_1746``
    asserts both counts (fix(#1746 B2b review r15)).

    Every URL is revalidated immediately before the request even though it is
    same-origin with one already validated: a host that resolved publicly at
    the door can resolve to a private address by the time the worker asks, and
    same-origin says nothing about that (AGENTS.md Rule 2).
    """
    try:
        await validate_url_for_ssrf(url)
        # The client comes from `make_safe_client`, whose transport re-resolves
        # and pins the validated IP at connect time and revalidates every
        # redirect hop, and which refuses a cross-origin hop carrying this
        # header. CodeQL models none of that.
        #
        # The marker below must stay the LAST line before the call: the
        # suppression query binds a marker to the line that follows it, so an
        # explanatory comment inserted between the two silently disarms it.
        # codeql[py/full-ssrf] fix(#1746): Rule 2 posture — validate_url_for_ssrf gates this exact URL immediately above, and make_safe_client's transport re-resolves, validates and pins the IP at connect time and revalidates every redirect hop
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except (httpx.HTTPError, SSRFError, ValueError) as exc:
        raise EndpointCheckFailedError(str(exc)) from None


def _parsed_json(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise EndpointCheckFailedError(str(exc)) from None


async def _check_wfs(
    client: httpx.AsyncClient, url: str, headers: dict[str, str]
) -> None:
    xml_text = await _fetch(client, _capabilities_url(url), headers)
    try:
        hrefs = _wfs_operation_hrefs(xml_text)
    except ET.ParseError as exc:
        raise EndpointCheckFailedError(str(exc)) from None
    _assert_same_origin(url, hrefs)


async def _check_ogcapi(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    collection: str | None,
) -> None:
    _assert_same_origin(
        url, _ogcapi_link_hrefs(_parsed_json(await _fetch(client, url, headers)))
    )

    if collection is not None:
        # fix(#1746 B2b review r14): the collection this import will actually
        # read, fetched directly. A listing is paginated and can be longer than
        # anything worth walking, so a check that only ever saw the first page
        # missed exactly the collection a user selected from a later one. This
        # path knows which one it is, so it does not need the listing at all.
        document = _parsed_json(
            await _fetch(
                client,
                f"{url.rstrip('/')}/collections/{quote(collection, safe='')}",
                headers,
            )
        )
        _assert_same_origin(url, _ogcapi_link_hrefs(document))
        return

    # The probe has no collection yet, so it walks the listing. Bounded, and
    # reaching the bound is recorded rather than treated as a clean pass: the
    # complete check is the per-collection one above, which runs on the two
    # paths that spend the credential.
    page_url: str | None = f"{url.rstrip('/')}/collections"
    for _page in range(_MAX_COLLECTION_PAGES):
        if page_url is None:
            return
        listing = _parsed_json(await _fetch(client, page_url, headers))
        _assert_same_origin(url, _ogcapi_link_hrefs(listing))
        collections = listing.get("collections") if isinstance(listing, dict) else None
        for entry in collections or []:
            _assert_same_origin(url, _ogcapi_link_hrefs(entry))
        page_url = _next_page(listing, page_url)
    if page_url is not None:
        logger.warning(
            "service endpoint check stopped at the collections page bound",
            pages=_MAX_COLLECTION_PAGES,
        )


async def assert_endpoints_stay_on_origin(
    url: str,
    *,
    service_format: str | None,
    credential_line: str | None,
    collection: str | None = None,
) -> None:
    """Refuse a credentialed source that advertises a foreign operation endpoint.

    Does nothing without a credential, and nothing for a service format whose
    credential does not travel to GDAL as a header. Raises
    :class:`CrossOriginEndpointError` for a description that names another
    origin and :class:`EndpointCheckFailedError` for one that cannot be read;
    every caller turns both into a coded refusal naming the URL field.

    ``credential_line`` is the finished header line the worker will hand GDAL,
    sent here to the submitted origin so a protected service answers with the
    document GDAL will act on rather than a 401. ``collection`` is the
    collection an OGC API import will read, which the preview and worker paths
    know and the probe does not.
    """
    if not credential_line or not requires_header_token_policy(service_format):
        return
    headers = _credential_headers(credential_line)
    async with make_safe_client(
        timeout=PROBE_TIMEOUT, credential_header=next(iter(headers))
    ) as client:
        if service_format == "wfs":
            await _check_wfs(client, url, headers)
        else:
            await _check_ogcapi(client, url, headers, collection)
