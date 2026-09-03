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

The contract for reading anything from an untrusted service
------------------------------------------------------------------

fix(#1746 B2b review r23). This module and ``service_items`` both read
documents a caller-named service chose, into the same process, holding the same
credential. They had grown different subsets of the same protections, and
closing that by hand was costing a review round per protection per site. There
is now ONE request function, :func:`fetch_document`, and every read in both
modules goes through it. ``test_service_auth_transport_1746`` asserts that
structurally, so a second call site fails there rather than in a review weeks
later.

What it applies, and what each one is for:

* ``Accept-Encoding: identity`` on the request, and a refusal of any
  ``Content-Encoding`` that comes back. Asking without enforcing lets a
  compression bomb through; enforcing without asking rejects an honest server
  that took httpx's default offer of ``gzip, deflate``. Both halves, or
  neither.
* A declared ``Content-Length`` over the budget refused before the body is
  read. Free when the service is honest.
* A streamed byte cap that stops at the bound rather than at the end of the
  response, over ``aiter_raw`` so nothing is inflated on the way past.
* A structural-token bound applied to the raw bytes BEFORE decoding, because a
  byte cap bounds the wire and not the object graph.
* SSRF revalidation of every URL immediately before its request, including one
  that a previous document named, because a host that resolved publicly a
  moment ago can resolve privately now.
* The final URL after redirects returned alongside the body, so a relative
  link resolves against the document it came from.
* An optional origin-contact callback, fired before the request, so a caller
  that dates contacts hears about the first one even if it fails.

Two things it deliberately does NOT do, because they belong to the whole
operation rather than to one read: the monotonic caller deadline, which each
entry point wraps around all of its reads, and the same-origin rule, which is
about what a document is allowed to name rather than about how it is fetched.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlparse, urlunparse

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
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


# What one description document may cost. Read into memory whole to be parsed,
# so this is the real per-request bound; the service chooses the size.
MAX_DOCUMENT_BYTES = 32 * 1024 * 1024

# And what it may cost DECODED. fix(#1746 B2b review r23): the sibling of
# `service_items.MAX_STRUCTURAL_TOKENS`, which r22 added on the items path
# while the description reads beside it kept only a byte cap. Compact JSON
# expands 4x to 31x (measured; the figures are in `service_items`), so 32 MiB
# of landing page was ~1 GiB of objects. Half the items figure because a
# description is metadata rather than data: 1,000,000 tokens is ~92 MiB
# decoded at the worst measured cost, and a collections listing of 1,000
# entries costs about 20,000.
MAX_DOCUMENT_TOKENS = 1_000_000

# And the same bound for XML, because `structural_tokens` counts JSON
# punctuation and answers ~0 for a capabilities document. fix(#1746 B2b review
# r26): a 32 MiB body of millions of tiny elements sailed past every bound this
# module had and built the whole ElementTree in the API and worker processes.
#
# Measured the same way as the JSON figure, `tracemalloc` peak over 1 MiB
# bodies:
#
#     <a/>          21.0x     84.1 bytes per `<`
#     <a></a>       12.6x     44.0 bytes per `<`
#     <a><b/></a>   20.7x     75.9 bytes per `<`
#     <a b="1"/>    33.9x    339.0 bytes per `<`   <- worst, attributes cost a dict
#
# 500,000 elements at the worst measured 339 bytes is ~162 MiB, which is the
# figure this is chosen for and the same ceiling `MAX_DOCUMENT_TOKENS` targets.
# A WFS capabilities document listing five thousand feature types costs on the
# order of 40,000 elements, so this is more than ten times anything real.
MAX_DOCUMENT_ELEMENTS = 500_000

# How long an endpoint check may take when the caller has a clock. `None`
# means no caller deadline, which is the direct-call and offline case.
DEFAULT_CHECK_TIMEOUT = 30.0

# What to ask a service for. fix(#1746 B2b review r25): content negotiation is
# part of the read rather than a header a caller may or may not remember.
# `probe_ogcapi` asks for JSON and the check did not, so a service that serves
# HTML for `*/*` answered the probe with a document and answered the check with
# a web page: `_parsed_json` then refused a perfectly valid service and
# `/probe` reported `endpoint_check_failed` about nothing the caller could fix.
#
# The OGC value is the superset of what the probe and the items path ask for,
# so all three reads negotiate identically and cannot disagree about which
# representation they are looking at.
OGC_JSON_ACCEPT = "application/geo+json, application/json"

# WFS negotiates by query (`service=WFS&request=GetCapabilities`) rather than
# by header, so this states the expectation rather than driving it. No `*/*`
# term: that is exactly what lets a server answer with HTML.
WFS_XML_ACCEPT = "application/xml, text/xml"


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


# The two ways a WFS capabilities document names an operation endpoint.
# 1.1 and 2.0 use `ows:DCP/ows:HTTP/ows:Get` with `xlink:href`; 1.0 uses
# `DCPType/HTTP/Get` with an `onlineResource` attribute and no xlink at all
# (fix(#1746 B2b review r15): reading only `href` let a 1.0 service advertise a
# cross-origin GetFeature and pass the guard, which is the whole thing this
# check exists to catch). Compared by LOCAL name, because the namespaces and
# the prefixes bound to them differ across the three versions.
_WFS_ENDPOINT_ATTRIBUTES = frozenset({"href", "onlineresource"})


def _wfs_operation_hrefs(xml_bytes: bytes) -> list[str]:
    """Every operation endpoint a capabilities document advertises.

    Namespace-agnostic by local name, the way ``parse_wfs_capabilities`` walks
    the same document, because WFS 1.0, 1.1 and 2.0 spell the namespaces
    differently. Parsed with defusedxml: this document is untrusted by
    definition, and it is the document the whole check exists to distrust.
    """
    hrefs: list[str] = []
    # Bytes rather than str: `ET` refuses a `str` carrying an XML encoding
    # declaration outright, and reads the declaration correctly from bytes.
    #
    # fix(#1746 B2b review r26): `forbid_dtd=True`. defusedxml already refuses
    # entity declarations by default (`forbid_entities`), which is the billion
    # laughs case, but it allows a DOCTYPE, including one naming an external
    # subset. A WFS capabilities document has no use for either, and the
    # element bound above only counts what is in the body -- it cannot see a
    # tree the doctype would have expanded.
    root = ET.fromstring(xml_bytes, forbid_dtd=True)
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


def _assert_same_origin(url: str, hrefs: list[str], base: str | None = None) -> None:
    """Refuse the first advertised endpoint that leaves the submitted origin.

    Relative hrefs resolve against the submitted URL, so a service that
    advertises ``/wfs`` or ``collections/x/items`` is describing itself and
    passes. An href that cannot be parsed at all is refused, because
    ``same_origin`` answers False for it and an address this cannot read is not
    one to send a credential to.
    """
    for href in hrefs:
        try:
            # fix(#1746 B2b review r19): relative to the document, which after
            # a canonical redirect is not the URL that was asked for. The
            # origin compared against is still the submitted one.
            resolved = urljoin(base or url, href)
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


def structural_tokens(body: bytes) -> int:
    """An upper bound on the values and containers ``body`` will decode to.

    Every JSON value after the first in a container is preceded by a comma and
    every container opens with a bracket, so this cannot undercount. Commas and
    brackets inside strings inflate it, which is the safe direction: the bound
    refuses a document it could have accepted rather than accepting one it
    could not hold.

    Three `bytes.count` passes over the raw body, before any decoding, which is
    the point: whatever the answer, nothing has been built yet.
    """
    return body.count(b",") + body.count(b"[") + body.count(b"{")


def structural_elements(body: bytes) -> int:
    """An upper bound on the elements ``body`` will parse to.

    fix(#1746 B2b review r26). Every element and every processing instruction
    opens with ``<``, so this cannot undercount. It overcounts freely: a
    closing tag has one too, and text inside CDATA may contain them. Both are
    the safe direction, and neither can hide an element.

    ``<`` cannot appear in element text or in an attribute value in a
    well-formed document -- it has to be escaped -- so outside CDATA the count
    is close to twice the element count rather than unboundedly above it.

    One `bytes.count` pass over the raw body, before any parsing.
    """
    return body.count(b"<")


def _wants_xml(accept: str) -> bool:
    return "xml" in accept.lower()


def require_decodable(
    body: bytes,
    *,
    accept: str,
    token_budget: int,
    element_budget: int,
    error: type[EndpointCheckFailedError] = EndpointCheckFailedError,
) -> None:
    """Refuse a document that would cost too much to build. fix(#1746 r22/r23/r26).

    A byte cap bounds the wire, not the object graph, and the two document
    kinds this reads expand through completely different structures. The kind
    is not guessed: it is the ``accept`` value the read already negotiated
    with, so a document is bounded by the parser it is actually going to.

    Called from `fetch_document` below, which is the only place either module
    makes a request, so it covers every document either one reads.
    """
    if _wants_xml(accept):
        if structural_elements(body) > element_budget:
            raise error("document is too complex to parse")
        return
    if structural_tokens(body) > token_budget:
        raise error("document is too complex to decode")


def fire_once(callback: "Callable[[], None] | None") -> "Callable[[], None] | None":
    """Wrap a callback so the first call fires it and later ones do not.

    fix(#1746 B2b review r23): both modules have to tell a caller that dates
    origin contacts when the origin was first reached, and both used to do it
    by special-casing the first iteration of their own loop. This moves the
    once-ness to the callback, so `fetch_document` can fire it unconditionally
    and no loop has to remember which pass it is on.
    """
    if callback is None:
        return None
    fired = False

    def _fire() -> None:
        nonlocal fired
        if not fired:
            fired = True
            callback()

    return _fire


def deadline_budget(
    deadline: float | None,
    *,
    error: type[EndpointCheckFailedError] = EndpointCheckFailedError,
) -> float | None:
    """Seconds left before ``deadline``, or a refusal if it has passed.

    fix(#1746 B2b review r23): shared, because the HTTP client's timeout is per
    inactivity rather than per operation on both paths, and a service that
    answers slowly but never stops answering passes it forever. The explicit
    expired check matters because `asyncio.timeout` on a past deadline only
    fires at the first suspension, which a fast enough first response never
    reaches.
    """
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise error("deadline exceeded")
    return remaining


def credential_headers(credential_line: str) -> dict[str, str]:
    """The request headers a credentialed read carries. fix(#1746 r23).

    The line is the wire format everything downstream of a door speaks (plan
    D9) and it has already been validated by the door that composed it, so
    this splits rather than re-derives. It is the only place the line is split
    for sending, and it sends to the submitted origin alone: the client refuses
    a cross-origin redirect carrying this header, and the checks themselves
    refuse a cross-origin endpoint before GDAL ever sees one.

    ``Accept-Encoding: identity`` is asked for and enforced by
    `read_bounded_body`. Both halves are needed and r23 is where the
    description path got the first of them: refusing an encoded body while
    letting httpx advertise its default `gzip, deflate` meant a server that
    honoured the offer had its answer rejected as unreadable.

    ``Accept`` is NOT set here. fix(#1746 B2b review r25): it belongs to the
    read rather than to the credential, because which representation is wanted
    is a property of the document being fetched, and leaving it to callers is
    how the check came to negotiate differently from the probe.
    """
    name, _, value = credential_line.partition(HEADER_LINE_SEPARATOR)
    return {name: value, "Accept-Encoding": "identity"}


async def read_bounded_body(
    response: httpx.Response,
    budget: int,
    *,
    error: type[EndpointCheckFailedError] = EndpointCheckFailedError,
) -> bytes:
    """The body, or a refusal once more than ``budget`` bytes have arrived.

    fix(#1746 B2b review r19): shared with `service_items`, which grew this in
    r17 for item pages while the description reads beside it stayed buffered.
    Both read documents chosen by the same untrusted service into the same
    process, so they get the same bound from the same code.

    The read stops at the bound rather than at the end of the response, so a
    refusal costs one chunk past the budget instead of however much the service
    felt like sending.

    ``aiter_raw`` rather than ``aiter_bytes``, for the reason #1708 r11
    recorded on the URL-import path: ``aiter_bytes`` transparently inflates a
    ``Content-Encoding`` body, so a single wire chunk could materialise an
    unbounded ``bytes`` BEFORE this check ran, which is a compression bomb
    against the exact memory the bound exists to protect.

    Returns bytes, never text. The callers hand them straight to a parser:
    ``json.loads`` and ``ET.fromstring`` both take bytes, decoding once
    internally, and ``ET`` needs them to honour an XML encoding declaration at
    all. Decoding to ``str`` first would make the second full copy this exists
    to avoid.
    """
    encoding = response.headers.get("Content-Encoding", "identity").lower()
    if encoding not in ("", "identity"):
        # Refused rather than decoded. `aiter_raw` hands back the compressed
        # bytes, so the parser would fail on them with a message about the
        # wrong thing.
        raise error("compressed document")
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > budget:
        # Free when the service is honest; no help when it is not, which is
        # what the running count below is for.
        raise error("document exceeds the cap")
    read = 0
    chunks: list[bytes] = []
    async for chunk in response.aiter_raw():
        read += len(chunk)
        if read > budget:
            raise error("document exceeds the cap")
        chunks.append(chunk)
    return b"".join(chunks)


async def fetch_document(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    *,
    accept: str,
    budget: int | None = None,
    token_budget: int | None = None,
    element_budget: int | None = None,
    error: type[EndpointCheckFailedError] = EndpointCheckFailedError,
    on_first_request: "Callable[[], None] | None" = None,
) -> tuple[bytes, str]:
    """One document from an untrusted service, and the URL it came from.

    THE request site for BOTH this module and `service_items`, and deliberately
    the only one. fix(#1746 B2b review r23): the two modules had grown
    different sets of protections around near-identical reads, and closing that
    by hand would have cost a review round per protection per site. Everything
    the contract in the module docstring lists is applied here, once.

    Every URL is revalidated immediately before the request even though it is
    same-origin with one already validated: a host that resolved publicly at
    the door can resolve to a private address by the time the worker asks, and
    same-origin says nothing about that (AGENTS.md Rule 2).

    ``on_first_request`` is fired before the request. Wrap it in `fire_once` if
    it should fire for the first read only, which is what a caller dating
    origin contacts wants.

    ``accept`` has no default, so every read states which representation it
    wants: `OGC_JSON_ACCEPT` for an OGC API document, `WFS_XML_ACCEPT` for
    capabilities. A default would be a guess that is wrong for one of them.
    """
    # Resolved here rather than as default arguments: a default binds the
    # module constant once at definition time, so a caller (or a test) that
    # changes the constant would be silently ignored.
    budget = MAX_DOCUMENT_BYTES if budget is None else budget
    token_budget = MAX_DOCUMENT_TOKENS if token_budget is None else token_budget
    element_budget = MAX_DOCUMENT_ELEMENTS if element_budget is None else element_budget
    # Copied rather than mutated: the caller's dict is reused across the pages
    # of a walk, and the negotiation belongs to this read.
    headers = {**headers, "Accept": accept}
    if on_first_request is not None:
        # Outside the guard below: a callback failure is this process's bug,
        # not the service's, and must not be reported as an unreadable
        # document.
        on_first_request()
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
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code >= 400:
                # Read nothing: an error body from a service these modules
                # exist to distrust is not worth the bytes, and the status is
                # the whole of what the refusal says.
                raise error(f"HTTP {response.status_code}")
            body = await read_bounded_body(response, budget, error=error)
            # fix(#1746 B2b review r19): the URL the representation actually
            # came from. A same-origin canonical redirect (`/wfs` to `/wfs/`)
            # changes what a relative href in the body is relative to, and
            # resolving against the pre-redirect URL asks for the wrong path.
            final_url = str(response.url)
        require_decodable(
            body,
            accept=accept,
            token_budget=token_budget,
            element_budget=element_budget,
            error=error,
        )
        return body, final_url
    except (httpx.HTTPError, SSRFError, ValueError) as exc:
        raise error(str(exc)) from None


async def _fetch(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    on_first_request: "Callable[[], None] | None" = None,
    *,
    accept: str = OGC_JSON_ACCEPT,
) -> tuple[bytes, str]:
    """This module's reads, with its own caps and exception.

    Defaults to the OGC value because four of the five reads here are OGC API
    documents; the capabilities read passes `WFS_XML_ACCEPT` explicitly.
    """
    return await fetch_document(
        client, url, headers, accept=accept, on_first_request=on_first_request
    )


def _parsed_json(body: bytes) -> object:
    try:
        return json.loads(body)
    except ValueError as exc:
        raise EndpointCheckFailedError(str(exc)) from None


async def _check_wfs(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    on_first_request: "Callable[[], None] | None" = None,
) -> None:
    xml_bytes, from_url = await _fetch(
        client,
        _capabilities_url(url),
        headers,
        on_first_request,
        accept=WFS_XML_ACCEPT,
    )
    try:
        hrefs = _wfs_operation_hrefs(xml_bytes)
    except (ET.ParseError, DefusedXmlException) as exc:
        # fix(#1746 B2b review r26): `DefusedXmlException` is a `ValueError`,
        # NOT a `ParseError`, so catching only the latter let a capabilities
        # document carrying an entity declaration escape as an uncaught
        # exception and surface as a 500. It is a refusal like any other
        # unreadable description.
        raise EndpointCheckFailedError(str(exc)) from None
    _assert_same_origin(url, hrefs, from_url)


async def _check_ogcapi(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    collection: str | None,
    on_first_request: "Callable[[], None] | None" = None,
) -> None:
    body, from_url = await _fetch(client, url, headers, on_first_request)
    _assert_same_origin(url, _ogcapi_link_hrefs(_parsed_json(body)), from_url)

    if collection is not None:
        # fix(#1746 B2b review r14): the collection this import will actually
        # read, fetched directly. A listing is paginated and can be longer than
        # anything worth walking, so a check that only ever saw the first page
        # missed exactly the collection a user selected from a later one. This
        # path knows which one it is, so it does not need the listing at all.
        body, from_url = await _fetch(
            client,
            f"{url.rstrip('/')}/collections/{quote(collection, safe='')}",
            headers,
        )
        document = _parsed_json(body)
        _assert_same_origin(url, _ogcapi_link_hrefs(document), from_url)
        return

    # The probe has no collection yet, so it walks the listing. Bounded, and
    # reaching the bound is recorded rather than treated as a clean pass: the
    # complete check is the per-collection one above, which runs on the two
    # paths that spend the credential.
    page_url: str | None = f"{url.rstrip('/')}/collections"
    for _page in range(_MAX_COLLECTION_PAGES):
        if page_url is None:
            return
        body, from_url = await _fetch(client, page_url, headers)
        listing = _parsed_json(body)
        _assert_same_origin(url, _ogcapi_link_hrefs(listing), from_url)
        collections = listing.get("collections") if isinstance(listing, dict) else None
        for entry in collections or []:
            _assert_same_origin(url, _ogcapi_link_hrefs(entry), from_url)
        # Resolved against the document's own URL as well, for the same reason.
        page_url = _next_page(listing, from_url)
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
    deadline: float | None,
    on_first_request: "Callable[[], None] | None" = None,
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

    ``deadline`` is a :func:`time.monotonic` stamp by which the whole check
    must be done, covering every read rather than the gaps between them.

    fix(#1746 B2b review r24): it has NO default. `/probe` omitted it and ran
    under `asyncio.timeout(None)`, and since the client bounds only inactivity
    and the OGC API check reads up to twenty listing pages, a slow-trickling
    authenticated description held an API request open for as long as it liked.
    A keyword with no default is the difference between forgetting it and not
    being able to. ``None`` is still accepted and still means no clock, but a
    caller has to say so; `DEFAULT_CHECK_TIMEOUT` is what a caller with no
    budget of its own should use.
    ``on_first_request`` fires once, before the first request, for a caller
    that dates origin contacts. fix(#1746 B2b review r23) for both.
    """
    if not credential_line or not requires_header_token_policy(service_format):
        return
    headers = credential_headers(credential_line)
    # The check has to fit inside the caller's clock: the client's timeout is
    # per inactivity, so a service that trickles a 32 MiB capabilities document
    # would otherwise hold a preview request or an ingest worker indefinitely
    # before the work it precedes had started.
    try:
        async with asyncio.timeout(deadline_budget(deadline)):
            async with make_safe_client(
                timeout=PROBE_TIMEOUT, credential_header=next(iter(headers))
            ) as client:
                arm = fire_once(on_first_request)
                if service_format == "wfs":
                    await _check_wfs(client, url, headers, arm)
                else:
                    await _check_ogcapi(client, url, headers, collection, arm)
    except TimeoutError:
        # Translated, not propagated. Every caller of this function handles
        # `EndpointCheckFailedError` and turns it into a coded 422; a bare
        # `TimeoutError` would escape those handlers as a 500 about nothing the
        # caller can act on.
        raise EndpointCheckFailedError("deadline exceeded") from None
