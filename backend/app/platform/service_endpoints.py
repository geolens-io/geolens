"""Refuse a credentialed source whose description names a foreign endpoint,
because GDAL fetches what a description advertises and sends the credential
there. Every read applies ``Accept-Encoding: identity``, a ``Content-Length``
check, a streamed byte cap, a structural-token bound, SSRF revalidation, the
final URL after redirects, and an optional origin-contact callback.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import xml.parsers.expat
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import (
    parse_qsl,
    quote,
    urljoin,
    urlparse,
)

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

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

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

# fix(#1770): only the rels this codebase dereferences, scoped to the
# document type each is read FROM -- `conformance` off the LANDING page,
# `items` off the COLLECTION document. Listing pages and entries read neither.
_LANDING_RELS = frozenset({"conformance"})
_COLLECTION_RELS = frozenset({"items"})

# How far the PROBE follows a paginated collections listing. Reaching it is
# recorded, never treated as a clean pass; the preview and worker paths know
# which collection they are importing and read that document directly.
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

# And what it may cost DECODED. Compact JSON expands 4x to 31x (measured), so
# 32 MiB of landing page is ~1 GiB of objects. Half `service_items`'s items
# figure, because a description is metadata rather than data.
MAX_DOCUMENT_TOKENS = 1_000_000

# And the same bound for XML, because `structural_tokens` counts JSON
# punctuation and answers ~0 for a capabilities document. 500,000 elements is
# ~162 MiB at the worst measured 339 bytes each, ten times any real document.
MAX_DOCUMENT_ELEMENTS = 500_000

# fix(#1770): a single start tag carrying hundreds of thousands of
# attributes counts as ONE `<`, so the per-element budget never sees it while
# expat still allocates one dict entry per attribute. Bounded directly.
MAX_DOCUMENT_ATTRIBUTES = 500_000

# fix(#1770): 256, well under `sys.getrecursionlimit()`'s default of
# 1,000. A budget at that default admits a document deep enough to blow the
# interpreter's own stack in whatever walks the parsed tree next.
MAX_DOCUMENT_DEPTH = 256

# fix(#1770): a service-advertised href's query string is free real estate
# no document budget prices -- its separators live inside one JSON string, so
# `structural_tokens` answers ~0. 8192 is the conventional request-line limit.
MAX_SERVICE_HREF_BYTES = 8192

# fix(#1770): the second, independent bound -- 8192 bytes still packs over
# a thousand `a=1&` pairs, and no real operation link carries a few dozen.
MAX_QUERY_FIELDS = 256


class HrefTooLongError(ValueError):
    """Raised by `bounded_service_url` for an href over the length cap. A
    `ValueError` subclass, so a caller may add `except HrefTooLongError:` ahead
    of an existing `except ValueError:`, and one that does not stays correct."""


def bounded_service_url(href: str, *, what: str) -> str:
    """*href*, refused before any parsing if it is unusually long.

    Raises :class:`HrefTooLongError`, a `ValueError`, so this length check
    flows through each caller's EXISTING `urljoin` refusal with no new except
    clause required.
    """
    if len(href.encode("utf-8", errors="surrogatepass")) > MAX_SERVICE_HREF_BYTES:
        raise HrefTooLongError(f"{what} href exceeds {MAX_SERVICE_HREF_BYTES} bytes")
    return href


def bounded_parse_qsl(query: str) -> list[tuple[str, str]]:
    """`parse_qsl` with `MAX_QUERY_FIELDS` applied.

    The one bounded call site every other read of a service-advertised query
    string should share, so `test_every_parse_qsl_call_bounds_its_field_count`
    has one place to point at instead of one exception per call site.
    """
    return parse_qsl(query, max_num_fields=MAX_QUERY_FIELDS)


# How long an endpoint check may take when the caller has a clock. `None`
# means no caller deadline, which is the direct-call and offline case.
DEFAULT_CHECK_TIMEOUT = 30.0

# What to ask a service for. fix(#1746): content negotiation belongs to the
# read, not to a header a caller may forget -- a service that serves HTML for
# `*/*` answers the probe with a document and the check with a web page.
OGC_JSON_ACCEPT = "application/geo+json, application/json"

# WFS negotiates by query (`service=WFS&request=GetCapabilities`) rather than
# by header, so this states the expectation rather than driving it. No `*/*`
# term: that is exactly what lets a server answer with HTML.
WFS_XML_ACCEPT = "application/xml, text/xml"
# fix(#1828): the check's reads and the driver's requests carry one User-Agent,
# and for WFS one Accept and Accept-Encoding, so a server keyed on them sees one client.
SERVICE_CHECK_USER_AGENT = "GeoLens"


def gdal_transport_env(service_format: str) -> dict[str, str]:
    """The env that makes a GDAL subprocess negotiate as this module's reads do."""
    env = {"GDAL_HTTP_USERAGENT": SERVICE_CHECK_USER_AGENT}
    if service_format == "wfs":
        env["GDAL_HTTP_HEADERS"] = (
            f"Accept: {WFS_XML_ACCEPT}\r\nAccept-Encoding: identity"
        )
    return env


class EndpointCheckFailedError(Exception):
    """A credentialed source's description could not be read, so nothing is
    known. Failing open is not conservative here: the services this protects
    are the ones that refuse an unauthenticated description."""

    def __init__(self, reason: str) -> None:
        self.code = ENDPOINT_CHECK_FAILED_CODE
        self.field = "url"
        self.policy = ENDPOINT_CHECK_FAILED_POLICY
        # Kept off the message: `reason` is an httpx error string, which can
        # carry the URL and therefore anything in its query.
        self.reason = reason
        super().__init__(self.policy)


LAYER_REQUIRED_CODE = "layer_required"
LAYER_REQUIRED_POLICY = (
    "This request carries a credential and names no WFS layer. A credentialed "
    "WFS import reads the description of the layer it opens before GDAL does, "
    "so the layer has to be named. Choose a layer and try again."
)


class LayerRequiredError(EndpointCheckFailedError):
    """A credentialed WFS reached a GDAL spawn point without a layer name. A
    subclass, so a door that turns `EndpointCheckFailedError` into a coded 422
    or a job failure does the same here; code, field and policy differ."""

    def __init__(self) -> None:
        super().__init__("no layer named")
        self.code = LAYER_REQUIRED_CODE
        self.field = "layer_name"
        self.policy = LAYER_REQUIRED_POLICY
        self.args = (self.policy,)


def require_wfs_layer(
    layer_name: str | None, *, service_format: str | None, credential_line: str | None
) -> None:
    """Refuse a credentialed WFS that names no layer, before GDAL is spawned.

    The schema check reads the description of the layer a door
    opens, and GDAL opened without a layer reads every layer's. Does nothing
    without a credential, for a format whose credential is not a header, or
    for any other format. Raises :class:`LayerRequiredError`.
    """
    if not credential_line or not requires_header_token_policy(service_format):
        return
    if service_format == "wfs" and not (layer_name or "").strip():
        raise LayerRequiredError()


def _origin_of(url: str) -> str:
    """``scheme://host:port`` for a message, with userinfo and path dropped.

    The port read is guarded. ``urlparse`` defers the port
    until the attribute is read and raises ValueError on a malformed one, which
    runs only while BUILDING a refusal and turns a clean 422 into a 500. The
    raw value is dropped rather than echoed: it is provider-controlled.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        port = ""
    return f"{(parsed.scheme or '').lower()}://{host}{port}"


def _capabilities_url(url: str) -> str:
    """The GetCapabilities URL the driver builds from the submitted URL, byte
    for byte: its own two keys replaced in place with its spelling, the layer
    and query keys removed, every other parameter kept as submitted."""
    request = _url_add_kvp(url, "SERVICE", "WFS")
    request = _url_add_kvp(request, "REQUEST", "GetCapabilities")
    for key in (
        "TYPENAME",
        "TYPENAMES",
        "FILTER",
        "PROPERTYNAME",
        "MAXFEATURES",
        "OUTPUTFORMAT",
    ):
        request = _url_add_kvp(request, key, None)
    return request


# The two ways a WFS capabilities document names an operation endpoint: 1.1/2.0
# `ows:DCP/ows:HTTP/ows:Get` with `xlink:href`, 1.0 `DCPType/HTTP/Get` with an
# `onlineResource` attribute and no xlink (fix(#1746)). Matched by LOCAL name.
_WFS_ENDPOINT_ATTRIBUTES = frozenset({"href", "onlineresource"})

# fix(#1770): the operations the read-only ogr2ogr/OGR_WFS path can ever
# ask for. Transaction, LockFeature and the stored-query operations are never
# requested, so their advertised endpoint is never contacted. Matched lower-cased.
_WFS_READ_OPERATIONS = frozenset(
    {"getcapabilities", "describefeaturetype", "getfeature", "getpropertyvalue"}
)

# fix(#1770): WFS 1.0 has no element naming an operation the way
# `ows:Operation name="..."` does -- the operation IS the element under
# `<Request>`, so this closed vocabulary keeps `Request`/`DCPType`/`HTTP` out.
_WFS_1_0_OPERATION_TAGS = frozenset(
    {
        "GetCapabilities",
        "DescribeFeatureType",
        "GetFeature",
        "GetFeatureWithLock",
        "LockFeature",
        "Transaction",
    }
)


def _local_name(tag: str) -> str:
    """The tag without its ``{namespace}`` prefix."""
    return tag.split("}")[-1] if "}" in tag else tag


def _wfs_root(xml_bytes: bytes) -> Element:
    """Parse an untrusted WFS document: bytes so an encoding declaration is
    honoured, DTD refused."""
    # fix(#1746): `forbid_dtd=True`. defusedxml refuses entity declarations
    # by default but allows a DOCTYPE naming an external subset, which a WFS
    # document has no use for and the element bound cannot see.
    return ET.fromstring(xml_bytes, forbid_dtd=True)


def _wfs_operation_hrefs(xml_bytes: bytes) -> list[str]:
    """`_operation_hrefs` of a capabilities document parsed here."""
    return _operation_hrefs(_wfs_root(xml_bytes))


def _operation_hrefs(root: Element) -> list[str]:
    """The operation endpoints a capabilities document advertises for a read.

    Filtered to :data:`_WFS_READ_OPERATIONS`, so a WFS-T
    deployment proxying its write endpoint separately is not refused for an
    endpoint the read-only path can never reach. An endpoint this walk cannot
    attribute to an operation is KEPT: the set names who is excluded, not who
    is let in. Namespace-agnostic by local name, because 1.0, 1.1 and 2.0
    spell the namespaces differently, and parsed with defusedxml.
    """
    hrefs: list[str] = []
    # fix(#1770): iterative, not recursive. A recursive walk is bounded by
    # `sys.getrecursionlimit()` (default 1,000), not by `MAX_DOCUMENT_DEPTH`,
    # so it can blow the stack on a document the preflight admits.
    stack: list[tuple[object, str | None]] = [(root, None)]
    while stack:
        element, operation = stack.pop()
        tag = _local_name(element.tag)
        if tag == "Operation":
            # 1.1/2.0: a missing or blank name leaves the context unattributed
            # rather than guessing one, which the fail-closed default checks.
            operation = (element.get("name") or "").strip().lower() or None
        elif tag in _WFS_1_0_OPERATION_TAGS:
            # 1.0: the element itself names the operation.
            operation = tag.lower()
        if tag in ("Get", "Post") and (
            operation is None or operation in _WFS_READ_OPERATIONS
        ):
            for name, value in element.attrib.items():
                local = _local_name(name).lower()
                if local in _WFS_ENDPOINT_ATTRIBUTES and value:
                    hrefs.append(value)
        stack.extend((child, operation) for child in reversed(list(element)))

    return hrefs


def _ogcapi_link_hrefs(document: object, rels: frozenset[str]) -> list[str]:
    """The operation endpoints one OGC API document advertises, among *rels*.

    *rels* is the caller's to choose, not one tree-wide set --
    see `_LANDING_RELS`/`_COLLECTION_RELS` for which document type gets which.
    """
    if not isinstance(document, dict):
        return []
    hrefs: list[str] = []
    for link in document.get("links", []) or []:
        if not isinstance(link, dict):
            continue
        if link.get("rel") in rels and link.get("href"):
            hrefs.append(str(link["href"]))
    return hrefs


def _next_page(document: object, base: str) -> str | None:
    """The `next` link of a paginated listing, resolved and same-origin only."""
    if not isinstance(document, dict):
        return None
    for link in document.get("links", []) or []:
        if isinstance(link, dict) and link.get("rel") == "next" and link.get("href"):
            try:
                # fix(#1770): refused before `urljoin` even runs.
                resolved = urljoin(
                    base, bounded_service_url(str(link["href"]), what="next")
                )
            except ValueError as exc:
                # fix(#1746, #1770): an address the parser cannot read
                # is not one to walk to, and the stop is warned rather than
                # silent. The href never reaches the message; it is untrusted.
                logger.warning(
                    "OGC API listing: `next` link could not be resolved, "
                    "stopping the walk",
                    too_long=isinstance(exc, HrefTooLongError),
                )
                return None
            return resolved if same_origin(base, resolved) else None
    return None


def _assert_same_origin(url: str, hrefs: list[str], base: str | None = None) -> None:
    """Refuse the first advertised endpoint that leaves the submitted origin.

    Relative hrefs resolve against the submitted URL, so a service that
    advertises ``/wfs`` is describing itself and passes. An href that cannot be
    parsed at all is refused: an address this cannot read is not one to send a
    credential to.
    """
    for href in hrefs:
        try:
            # fix(#1770): the shared length gate both the OGC API and the
            # WFS href sinks feed into, applied before `urljoin`.
            href = bounded_service_url(href, what="operation")
            # fix(#1746): resolved against the document, which after a
            # canonical redirect is not the URL asked for; the origin compared
            # against is still the submitted one.
            resolved = urljoin(base or url, href)
        except HrefTooLongError:
            # fix(#1770): its own wording -- "unparseable" is true of a
            # malformed address but not of one merely too long to be parsed.
            raise CrossOriginEndpointError("href exceeds the length limit") from None
        except ValueError:
            # fix(#1746): `urljoin` raises on some malformed absolute
            # references. An address that cannot be resolved is not one to send
            # a credential to; the raw href is never echoed.
            raise CrossOriginEndpointError("unparseable") from None
        if not same_origin(url, resolved):
            raise CrossOriginEndpointError(_origin_of(resolved))


def structural_tokens(body: bytes) -> int:
    """An upper bound on the values and containers ``body`` will decode to.

    Every JSON value after the first in a container is preceded by a comma and
    every container opens with a bracket, so this cannot undercount; commas and
    brackets inside strings inflate it, which is the safe direction. Three
    `bytes.count` passes over the raw body, before any decoding.
    """
    return body.count(b",") + body.count(b"[") + body.count(b"{")


def structural_elements(body: bytes) -> int:
    """An upper bound on the elements ``body`` will parse to.

    Every element and processing instruction opens with ``<``, so this cannot
    undercount; a closing tag has one too and CDATA text may contain them, both
    the safe direction. One `bytes.count` pass over the raw body, before any
    parsing.
    """
    return body.count(b"<")


def _wants_xml(accept: str) -> bool:
    return "xml" in accept.lower()


class _XmlPreflightBudgetExceeded(Exception):
    """Internal signal only: a streaming XML preflight budget tripped. Raised
    inside an expat handler and caught by `_xml_preflight` one frame up, so
    `require_decodable` raises `EndpointCheckFailedError`, never this."""


def _xml_preflight(
    body: bytes,
    *,
    element_budget: int,
    attribute_budget: int,
    depth_budget: int,
    text_byte_budget: int,
) -> None:
    """Count elements, attributes, text bytes and nesting depth via a streaming
    parser, aborting the instant any ONE budget trips -- before a single
    `ElementTree` node is built.

    `structural_elements`'s ``body.count(b"<")`` cannot price a
    shape that concentrates its cost: an attribute bomb (one `<`, one dict
    entry per attribute), a deep-nesting bomb (one parser callback and one
    object per level), or one enormous run of character data outside any
    element or attribute count at all. expat calls back per element, per
    attribute and per chunk without building a tree, so each cost is counted
    directly against its own budget. This does not replace the cheap byte-scan
    in `require_decodable`; it closes the gap that scan leaves.

    Malformed XML is not diagnosed here: `ExpatError` is swallowed and left for
    `ET.fromstring`, the real parse that runs next, to raise for.
    """
    elements = 0
    attributes = 0
    text_bytes = 0
    depth = 0

    def start(_name: str, attrs: dict) -> None:
        nonlocal elements, attributes, depth
        elements += 1
        attributes += len(attrs)
        depth += 1
        if (
            elements > element_budget
            or attributes > attribute_budget
            or depth > depth_budget
        ):
            raise _XmlPreflightBudgetExceeded()

    def end(_name: str) -> None:
        nonlocal depth
        depth -= 1

    def chardata(data: str) -> None:
        nonlocal text_bytes
        text_bytes += len(data)
        if text_bytes > text_byte_budget:
            raise _XmlPreflightBudgetExceeded()

    def refuse_entity(*_args: object) -> None:
        # Raw expat, unlike the defusedxml that wraps it, expands internal
        # entities with no bound at all (billion laughs). Refusing at
        # DECLARATION time means the substitution never runs.
        raise _XmlPreflightBudgetExceeded()

    parser = xml.parsers.expat.ParserCreate()
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chardata
    parser.EntityDeclHandler = refuse_entity
    parser.ExternalEntityRefHandler = lambda *_args: 0
    try:
        parser.Parse(body, True)
    except _XmlPreflightBudgetExceeded:
        raise
    except xml.parsers.expat.ExpatError:
        return


def require_decodable(
    body: bytes,
    *,
    accept: str,
    token_budget: int,
    element_budget: int,
    attribute_budget: int = MAX_DOCUMENT_ATTRIBUTES,
    depth_budget: int = MAX_DOCUMENT_DEPTH,
    error: type[EndpointCheckFailedError] = EndpointCheckFailedError,
) -> None:
    """Refuse a document that would cost too much to build.

    A byte cap bounds the wire, not the object graph, and the two document
    kinds expand through completely different structures. The kind is not
    guessed: it is the ``accept`` value the read already negotiated with.
    Called from `fetch_document`, the only place either module makes a request.

    The XML branch runs two passes. The cheap
    `structural_elements` byte-scan short-circuits millions of tiny elements
    with no parser engaged; `_xml_preflight` then catches the shapes that scan
    cannot see, reusing ``token_budget`` as the text-byte ceiling.
    """
    if _wants_xml(accept):
        if structural_elements(body) > element_budget:
            raise error("document is too complex to parse")
        try:
            _xml_preflight(
                body,
                element_budget=element_budget,
                attribute_budget=attribute_budget,
                depth_budget=depth_budget,
                text_byte_budget=token_budget,
            )
        except _XmlPreflightBudgetExceeded:
            raise error("document is too complex to parse") from None
        return
    if structural_tokens(body) > token_budget:
        raise error("document is too complex to decode")


def fire_once(callback: "Callable[[], None] | None") -> "Callable[[], None] | None":
    """Wrap a callback so the first call fires it and later ones do not.

    Moves the once-ness onto the callback, so `fetch_document`
    can fire it unconditionally and no loop has to remember which pass it is on.
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

    The explicit expired check matters: `asyncio.timeout` on a past deadline
    only fires at the first suspension, which a fast enough first response
    never reaches. Shared because the HTTP client's timeout is per inactivity
    on both paths, so a service that answers slowly but never stops passes it
    forever.
    """
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise error("deadline exceeded")
    return remaining


def credential_headers(credential_line: str) -> dict[str, str]:
    """The request headers a credentialed read carries.

    The line is the wire format everything downstream of a door speaks (plan
    D9) and has already been validated by the door that composed it, so this
    splits rather than re-derives.

    ``Accept-Encoding: identity`` is asked for here and enforced by
    `read_bounded_body`; both halves are needed, because refusing an encoded
    body while httpx advertises its default `gzip, deflate` rejects a server
    that honoured the offer. ``Accept`` is NOT set here: it belongs to the
    read rather than to the credential.
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

    The read stops at the bound rather than at the end of the response, so a
    refusal costs one chunk past the budget rather than however much the
    service felt like sending.

    ``aiter_raw`` rather than ``aiter_bytes``: the latter
    transparently inflates a ``Content-Encoding`` body, so a single wire chunk
    could materialise an unbounded ``bytes`` BEFORE this check ran.

    Returns bytes, never text. ``json.loads`` and ``ET.fromstring`` both take
    bytes, and ``ET`` needs them to honour an XML encoding declaration at all.
    """
    encoding = response.headers.get("Content-Encoding", "identity").lower()
    if encoding not in ("", "identity"):
        # Refused rather than decoded: `aiter_raw` hands back the compressed
        # bytes, so the parser would fail on them about the wrong thing.
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
    the only one: everything the contract in the module docstring lists is
    applied here, once.

    Every URL is revalidated immediately before its request even though it is
    same-origin with one already validated: a host that resolved publicly at
    the door can resolve to a private address by the time the worker asks, and
    same-origin says nothing about that (AGENTS.md Rule 2).

    ``on_first_request`` is fired once SSRF validation has succeeded, right
    before the request goes out; wrap it in `fire_once` for the first read
    only. ``accept`` has no default, so every read states which representation
    it wants -- a default would be a guess that is wrong for one of them.
    """
    # Resolved here rather than as default arguments: a default binds the
    # module constant once at definition time, so a caller or test that changes
    # the constant would be silently ignored.
    budget = MAX_DOCUMENT_BYTES if budget is None else budget
    token_budget = MAX_DOCUMENT_TOKENS if token_budget is None else token_budget
    element_budget = MAX_DOCUMENT_ELEMENTS if element_budget is None else element_budget
    # Copied rather than mutated: the caller's dict is reused across the pages
    # of a walk, and the negotiation belongs to this read.
    headers = {**headers, "Accept": accept, "User-Agent": SERVICE_CHECK_USER_AGENT}
    try:
        await validate_url_for_ssrf(url)
        if on_first_request is not None:
            # fix(#1746): only once validation has succeeded.
            on_first_request()
        # The client's transport pins the validated IP and revalidates every
        # redirect hop. The marker below must stay the LAST line before the call.
        # codeql[py/full-ssrf] fix(#1746): Rule 2 posture — validate_url_for_ssrf gates this exact URL immediately above, and make_safe_client's transport re-resolves, validates and pins the IP at connect time and revalidates every redirect hop
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code >= 400:
                # Read nothing: an error body from a service these modules
                # exist to distrust is not worth the bytes.
                raise error(f"HTTP {response.status_code}")
            body = await read_bounded_body(response, budget, error=error)
            # fix(#1746): the URL the representation actually came from. A
            # same-origin canonical redirect changes what a relative href in
            # the body is relative to.
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
    """``json.loads(body)``, or a coded refusal rather than a raw crash.

    A JSON depth bomb -- 900,000 nested `[` at 1.8 bytes each,
    under every byte and token budget, since `structural_tokens` counts
    brackets rather than nesting -- makes `json.loads` raise `RecursionError`,
    a `RuntimeError` subclass rather than a `ValueError`, so it has to be named
    here or it escapes as a bare 500.
    """
    try:
        return json.loads(body)
    except (ValueError, RecursionError) as exc:
        raise EndpointCheckFailedError(str(exc)) from None


# fix(#1828): the DescribeFeatureType reads GDAL's WFS driver makes before any
# GetFeature, mirrored so an `include` naming another origin is refused before
# the driver fetches it with the credential (GDAL 3.10.3, the worker image).
_WFS_SCHEMA_BATCH = 50
_MAX_WFS_SCHEMA_READS = 50
# fix(#1828): aggregate over every document one check parses, two maximum
# documents each; a real schema and its includes sit an order of magnitude below.
_MAX_WFS_SCHEMA_BYTES = 2 * MAX_DOCUMENT_BYTES
_MAX_WFS_SCHEMA_ELEMENTS = 2 * MAX_DOCUMENT_ELEMENTS
_WFS_DEFAULT_VERSION = "1.0.0"
# The driver's HTTP branch is `http://` or `https://`; the scheme's case is not
# part of a URI's identity, so it is folded here.
_HTTP_LOCATION = re.compile(r"https?://", re.IGNORECASE)
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_C_INT_PREFIX = re.compile(r"\s*([+-]?\d+)", re.ASCII)


def _xml_value(element: Element, name: str) -> str | None:
    """``CPLGetXMLValue`` as the driver reads it: the attribute, else a
    text-only child element, matched by lower-cased local name."""
    for key, value in element.attrib.items():
        if _local_name(key).lower() == name:
            return value
    for child in element:
        if (
            isinstance(child.tag, str)
            and _local_name(child.tag).lower() == name
            and len(child) == 0
        ):
            return child.text or ""
    return None


def _wfs_capabilities_node(root: Element) -> Element | None:
    """``WFSFindNode``: the root, else its first direct child, whose local name
    is ``WFS_Capabilities`` in any case; the driver opens nothing else."""
    for node in (root, *root):
        if (
            isinstance(node.tag, str)
            and _local_name(node.tag).lower() == "wfs_capabilities"
        ):
            return node
    return None


def _wfs_feature_type_nodes(capabilities: Element) -> list[Element]:
    """The direct ``FeatureType`` children of the first direct
    ``FeatureTypeList``, the only ones the driver turns into layers."""
    for child in capabilities:
        if (
            isinstance(child.tag, str)
            and _local_name(child.tag).lower() == "featuretypelist"
        ):
            return [
                node
                for node in child
                if isinstance(node.tag, str) and _local_name(node.tag) == "FeatureType"
            ]
    return []


def _wfs_feature_types(root: Element) -> tuple[str, list[str]]:
    """The WFS version and the advertised feature type names, in document order.

    Read the way the driver reads them: the ``version`` of the capabilities
    node (1.0.0 when absent; an empty value stays empty, as the driver sends
    it) and the ``Name`` of each ``FeatureType`` the driver lists, once.
    """
    capabilities = _wfs_capabilities_node(root)
    if capabilities is None:
        return _WFS_DEFAULT_VERSION, []
    version = _xml_value(capabilities, "version")
    names: list[str] = []
    seen: set[str] = set()
    for element in _wfs_feature_type_nodes(capabilities):
        name = (_xml_value(element, "name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return _WFS_DEFAULT_VERSION if version is None else version, names


def _wfs_required_output_formats(root: Element, version: str) -> dict[str, str]:
    """The ``OUTPUTFORMAT`` the driver adds to a feature type's
    DescribeFeatureType: on 1.1.0 exactly, the first ``Format`` under its
    first ``OutputFormats`` when none of them mentions ``3.1``; else none."""
    required: dict[str, str] = {}
    capabilities = _wfs_capabilities_node(root)
    if version != "1.1.0" or capabilities is None:
        return required
    seen: set[str] = set()
    for element in _wfs_feature_type_nodes(capabilities):
        name = (_xml_value(element, "name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        outputs = next(
            (
                child
                for child in element
                if isinstance(child.tag, str)
                and _local_name(child.tag) == "OutputFormats"
            ),
            None,
        )
        if outputs is None:
            continue
        formats = [
            fmt.text
            for fmt in outputs
            if isinstance(fmt.tag, str)
            and _local_name(fmt.tag) == "Format"
            and fmt.text
            and fmt.text.strip()
        ]
        if formats and not any("3.1" in fmt for fmt in formats):
            required[name] = formats[0]
    return required


def _wfs_prefix(name: str) -> str:
    return name.split(":", 1)[0] if ":" in name else ""


def _wfs_batch(names: list[str], first: str, required: dict[str, str]) -> list[str]:
    """The names one DescribeFeatureType carries: *first*, then the other
    members of its prefix that share its required output format, in order,
    fifty at most, as the driver batches."""
    prefix = _wfs_prefix(first)
    output_format = required.get(first)
    siblings = [
        n
        for n in names
        if n != first and _wfs_prefix(n) == prefix and required.get(n) == output_format
    ]
    return [first, *siblings[: _WFS_SCHEMA_BATCH - 1]]


def _wfs_layer_name(names: list[str], requested: str) -> str | None:
    """The advertised name the driver opens for *requested*, or None.

    Exact first, then case-insensitive, then the part after the prefix when
    the request carries none and no two advertised short names collide.
    """
    if requested in names:
        return requested
    folded = requested.lower()
    for name in names:
        if name.lower() == folded:
            return name
    shorts = [name.split(":", 1)[-1] for name in names]
    if ":" in requested or len(set(shorts)) < len(shorts):
        return None
    for name, short in zip(names, shorts):
        if ":" in name and short.lower() == folded:
            return name
    return None


def _url_get_value(url: str, key: str) -> str:
    """``CPLURLGetValue`` (GDAL 3.10.3): the raw value of the first
    case-insensitive ``KEY=`` that follows ``?`` or ``&``, else empty."""
    needle = f"{key}=".translate(_ASCII_LOWER)
    position = url.translate(_ASCII_LOWER).find(needle)
    if position > 0 and url[position - 1] in "?&":
        value = url[position + len(needle) :]
        separator = value.find("&")
        return value if separator == -1 else value[:separator]
    return ""


def _url_add_kvp(url: str, key: str, value: str | None) -> str:
    """``CPLURLAddKVP`` (GDAL 3.10.3), byte for byte.

    The first case-insensitive ``KEY=`` that follows ``?`` or ``&`` is
    replaced in place with the driver's own spelling, or removed when
    ``value`` is None; an absent key is appended. Every other byte of the
    URL is left as submitted, and a URL with no query gains its ``?``.
    """
    if "?" not in url:
        url += "?"
    needle = f"{key}=".translate(_ASCII_LOWER)
    position = url.translate(_ASCII_LOWER).find(needle)
    if position > 0 and url[position - 1] in "?&":
        rebuilt = url[:position]
        if value is not None:
            rebuilt += f"{key}={value}"
        separator = url.find("&", position)
        if separator != -1:
            rest = url[separator:]
            rebuilt += rest[1:] if rebuilt[-1] in "&?" else rest
        return rebuilt
    if value is None:
        return url
    if url[-1] not in "&?":
        url += "&"
    return f"{url}{key}={value}"


def _wfs_escape(value: str) -> str:
    """``WFS_EscapeURL``: ASCII letters and digits, ``_``, ``.``, ``:`` and
    ``,`` pass; every other byte is percent-encoded."""
    escaped: list[str] = []
    for byte in value.encode("utf-8"):
        char = chr(byte)
        if (byte < 128 and char.isalnum()) or char in "_.:,":
            escaped.append(char)
        else:
            escaped.append(f"%{byte:02X}")
    return "".join(escaped)


_LONG_MAX = (1 << 63) - 1
_LONG_MIN = -(1 << 63)


def _c_atoi(text: str) -> int:
    """``atoi`` as the worker's C library computes it: ASCII whitespace and
    sign, digits saturated to a 64-bit ``long``, then truncated to a signed
    32-bit ``int``. A digit run of any length is handled without conversion."""
    match = _C_INT_PREFIX.match(text)
    if match is None:
        return 0
    literal = match.group(1)
    negative = literal[0] == "-"
    digits = literal.lstrip("+-").lstrip("0")
    if len(digits) > 19:
        value = _LONG_MIN if negative else _LONG_MAX
    else:
        value = int(digits or "0")
        value = max(_LONG_MIN, min(_LONG_MAX, -value if negative else value))
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value >= (1 << 31) else value


def _wfs_version_is_two_or_more(version: str) -> bool:
    """``atoi(version) >= 2``, the driver's WFS 2 test."""
    return _c_atoi(version) >= 2


def _wfs_base_url(url: str, version: str) -> str:
    """The base URL the driver holds after opening a WFS: for a version whose
    leading integer is 2 or more, a ``MAXFEATURES`` with no ``COUNT`` beside it
    is rewritten to ``COUNT``; everything else is the submitted URL."""
    if not _wfs_version_is_two_or_more(version) or _url_get_value(url, "COUNT"):
        return url
    max_features = _url_get_value(url, "MAXFEATURES")
    if not max_features:
        return url
    url = _url_add_kvp(url, "MAXFEATURES", None)
    return _url_add_kvp(url, "COUNT", max_features)


def _describe_feature_type_url(
    url: str,
    version: str,
    names: list[str],
    *,
    single: bool,
    output_format: str | None = None,
) -> str:
    """The DescribeFeatureType URL the driver builds from the submitted URL,
    byte for byte: the driver's own keys replaced or removed in place, the
    type names escaped as the driver escapes them, every other parameter
    kept as submitted. ``single`` is the one-layer request, which also
    drops ``COUNT``; the batch request keeps it. ``output_format`` is the
    driver's required ``OUTPUTFORMAT``, added escaped; absent, the key goes.
    """
    request = _wfs_base_url(url, version)
    steps: list[tuple[str, str | None]] = [
        ("SERVICE", "WFS"),
        ("VERSION", version),
        ("REQUEST", "DescribeFeatureType"),
        ("TYPENAME", _wfs_escape(",".join(names))),
        ("PROPERTYNAME", None),
        ("MAXFEATURES", None),
    ]
    if single:
        steps.append(("COUNT", None))
    steps.append(("FILTER", None))
    steps.append(
        ("OUTPUTFORMAT", _wfs_escape(output_format) if output_format else None)
    )
    for key, value in steps:
        request = _url_add_kvp(request, key, value)
    return request


def _gdal_relative_filename(name: str) -> bool:
    """``CPLIsFilenameRelative`` (GDAL 3.10.3). A relative include resolves under
    the driver's in-memory directory and never leaves the process; anything
    else is opened as a VSI path."""
    if not name:
        return True
    if name[0] in "/\\" or name[1:3] in (":\\", ":/"):
        return False
    return "://" not in name[1:]


def _schema_include_locations(root: Element) -> list[str]:
    """Every ``include`` location in the tree, read as the driver reads it."""
    locations: list[str] = []
    for element in root.iter():
        if (
            isinstance(element.tag, str)
            and _local_name(element.tag).lower() == "include"
        ):
            location = _xml_value(element, "schemalocation")
            if location is not None:
                locations.append(location)
    return locations


def _schema_location_label(location: str) -> str:
    """What a refusal names: the location's origin when it has a host."""
    try:
        netloc = urlparse(location).netloc
    except ValueError:
        return "unparseable"
    return _origin_of(location) if netloc else "a local path"


def _wfs_schema(body: bytes) -> Element | None:
    """The schema element the driver would parse out of a DescribeFeatureType
    body, or None where the driver sees no schema and falls back.

    Raises `EndpointCheckFailedError` for a body that does not parse: the
    driver's own parser is more lenient, so what it would read is unknown.
    """
    if b"<ServiceExceptionReport" in body:
        return None
    try:
        root = _wfs_root(body)
    except (ET.ParseError, DefusedXmlException, RecursionError) as exc:
        raise EndpointCheckFailedError(str(exc)) from None
    if _local_name(root.tag).lower() == "schema":
        return root
    for child in root:
        if isinstance(child.tag, str) and _local_name(child.tag).lower() == "schema":
            return child
    return None


class _WfsSchemaReads:
    """The bounded DescribeFeatureType and include reads of one check: `check`
    refuses the first include the driver would fetch off-origin or open as a
    path, and walks a same-origin include once, depth first, within budget."""

    def __init__(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str]
    ) -> None:
        self._client = client
        self._url = url
        self._headers = headers
        self._reads = 0
        self._bytes = 0
        self._elements = 0
        self._visited: set[str] = set()

    async def _read(self, request_url: str, *, what: str) -> bytes:
        self._reads += 1
        if self._reads > _MAX_WFS_SCHEMA_READS:
            raise EndpointCheckFailedError("schema read budget exceeded")
        try:
            request_url = bounded_service_url(request_url, what=what)
        except HrefTooLongError as exc:
            raise EndpointCheckFailedError(str(exc)) from None
        body, _from_url = await _fetch(
            self._client, request_url, self._headers, accept=WFS_XML_ACCEPT
        )
        self._bytes += len(body)
        if self._bytes > _MAX_WFS_SCHEMA_BYTES:
            raise EndpointCheckFailedError("schema byte budget exceeded")
        return body

    def _counted(self, tree: Element) -> Element:
        self._elements += sum(1 for _ in tree.iter())
        if self._elements > _MAX_WFS_SCHEMA_ELEMENTS:
            raise EndpointCheckFailedError("schema element budget exceeded")
        return tree

    async def _describe(
        self,
        version: str,
        names: list[str],
        *,
        single: bool,
        output_format: str | None,
    ):
        request_url = _describe_feature_type_url(
            self._url, version, names, single=single, output_format=output_format
        )
        schema = _wfs_schema(await self._read(request_url, what="DescribeFeatureType"))
        return None if schema is None else self._counted(schema)

    async def batch(
        self, version: str, names: list[str], *, output_format: str | None = None
    ) -> Element | None:
        return await self._describe(
            version, names, single=False, output_format=output_format
        )

    async def single(
        self, version: str, name: str, *, output_format: str | None = None
    ) -> Element:
        schema = await self._describe(
            version, [name], single=True, output_format=output_format
        )
        if schema is None:
            raise EndpointCheckFailedError("DescribeFeatureType is not a schema")
        return schema

    async def check(self, schema: Element) -> None:
        pending = [iter(_schema_include_locations(schema))]
        while pending:
            location = next(pending[-1], None)
            if location is None:
                pending.pop()
                continue
            if _HTTP_LOCATION.match(location):
                if not same_origin(self._url, location):
                    raise CrossOriginEndpointError(_schema_location_label(location))
                if location not in self._visited:
                    self._visited.add(location)
                    included = await self._include(location)
                    pending.append(iter(_schema_include_locations(included)))
                    del included
            elif not _gdal_relative_filename(location):
                raise CrossOriginEndpointError(_schema_location_label(location))

    async def _include(self, location: str) -> Element:
        try:
            tree = _wfs_root(await self._read(location, what="schemaLocation"))
        except (ET.ParseError, DefusedXmlException, RecursionError) as exc:
            raise EndpointCheckFailedError(str(exc)) from None
        return self._counted(tree)


async def _check_wfs_schemas(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    root: Element,
    collection: str | None,
) -> None:
    """Refuse the first schema include the driver would fetch off the origin.

    Reads what the driver reads for the layer it is about to open: one
    DescribeFeatureType naming the layer and then its prefix siblings, fifty at
    most, then one naming the layer alone, which the driver issues whenever the
    first answer does not cover it. With no layer, or one the driver would not
    resolve, nothing is read.
    """
    version, names = _wfs_feature_types(root)
    target = _wfs_layer_name(names, collection) if collection else None
    if target is None:
        return
    reads = _WfsSchemaReads(client, url, headers)
    required = _wfs_required_output_formats(root, version)
    output_format = required.get(target)
    batch = _wfs_batch(names, target, required)
    schema = await reads.batch(version, batch, output_format=output_format)
    if schema is not None:
        await reads.check(schema)
    # fix(#1828): the driver retries the layer alone whenever the batch answer
    # does not cover it; the check reads that request unless it is the same URL.
    single_url = _describe_feature_type_url(
        url, version, [target], single=True, output_format=output_format
    )
    batch_url = _describe_feature_type_url(
        url, version, batch, single=False, output_format=output_format
    )
    if schema is None or single_url != batch_url:
        await reads.check(
            await reads.single(version, target, output_format=output_format)
        )


async def _check_wfs(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    collection: str | None,
    on_first_request: "Callable[[], None] | None" = None,
) -> None:
    """Refuse a credentialed WFS whose description or schemas name another origin.

    Reads the capabilities and every DescribeFeatureType the driver would,
    with the credential, on the submitted origin only. Raises
    `CrossOriginEndpointError` for a foreign endpoint or schema location and
    `EndpointCheckFailedError` for a document that cannot be read.
    """
    xml_bytes, from_url = await _fetch(
        client,
        _capabilities_url(url),
        headers,
        on_first_request,
        accept=WFS_XML_ACCEPT,
    )
    try:
        root = _wfs_root(xml_bytes)
        hrefs = _operation_hrefs(root)
    except (ET.ParseError, DefusedXmlException) as exc:
        # fix(#1746): `DefusedXmlException` is a `ValueError`, NOT a
        # `ParseError`, so catching only the latter lets a document carrying an
        # entity declaration escape as a 500.
        raise EndpointCheckFailedError(str(exc)) from None
    except RecursionError as exc:
        # fix(#1770): last line of defense -- the walk above is iterative
        # now, but `ET.fromstring` is not this module's code. Translated to the
        # coded refusal every other unreadable description gets.
        raise EndpointCheckFailedError(str(exc)) from None
    _assert_same_origin(url, hrefs, from_url)
    await _check_wfs_schemas(client, url, headers, root, collection)


async def _check_ogcapi(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    collection: str | None,
    on_first_request: "Callable[[], None] | None" = None,
) -> None:
    body, from_url = await _fetch(client, url, headers, on_first_request)
    # fix(#1770): the landing page, the only document type `conformance` is
    # ever read from.
    _assert_same_origin(
        url, _ogcapi_link_hrefs(_parsed_json(body), _LANDING_RELS), from_url
    )

    if collection is not None:
        # fix(#1746): the collection this import will actually read,
        # fetched directly -- a listing is paginated, so a check that reads
        # only the first page misses a collection chosen from a later one.
        body, from_url = await _fetch(
            client,
            f"{url.rstrip('/')}/collections/{quote(collection, safe='')}",
            headers,
        )
        document = _parsed_json(body)
        # fix(#1770): the collection document, the only document type
        # `items` is ever read from.
        _assert_same_origin(
            url, _ogcapi_link_hrefs(document, _COLLECTION_RELS), from_url
        )
        return

    # The probe has no collection yet, so it walks the listing. Bounded, and
    # reaching the bound is recorded rather than treated as a clean pass. The
    # `collection is not None` branch above has no live caller (fix(#1770)).
    page_url: str | None = f"{url.rstrip('/')}/collections"
    for _page in range(_MAX_COLLECTION_PAGES):
        if page_url is None:
            return
        body, from_url = await _fetch(client, page_url, headers)
        listing = _parsed_json(body)
        # fix(#1770): the listing page dereferences neither rel, and
        # `frozenset()` names that at a call site a structural test pins. A
        # deliberate no-op: `_ogcapi_link_hrefs` returns `[]` for any document.
        _assert_same_origin(url, _ogcapi_link_hrefs(listing, frozenset()), from_url)
        collections = listing.get("collections") if isinstance(listing, dict) else None
        for entry in collections or []:
            # fix(#1770): an entry's inlined `items` href is never
            # read either -- `_resolve_items_url` re-fetches the collection
            # document. Kept as a call site for the same structural test.
            _assert_same_origin(url, _ogcapi_link_hrefs(entry, frozenset()), from_url)
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

    ``deadline`` is a :func:`time.monotonic` stamp covering every read, and it
    has NO default: the client bounds only inactivity, so with
    no clock a slow-trickling description holds an API request open
    indefinitely. ``None`` still means no clock.
    ``on_first_request`` fires once, before the first request.
    """
    if not credential_line or not requires_header_token_policy(service_format):
        return
    headers = credential_headers(credential_line)
    # The check has to fit inside the caller's clock: the client's timeout is
    # per inactivity, so a trickled 32 MiB capabilities document would hold a
    # preview request or an ingest worker indefinitely.
    try:
        async with asyncio.timeout(deadline_budget(deadline)):
            async with make_safe_client(
                timeout=PROBE_TIMEOUT, credential_header=next(iter(headers))
            ) as client:
                arm = fire_once(on_first_request)
                if service_format == "wfs":
                    await _check_wfs(client, url, headers, collection, arm)
                else:
                    await _check_ogcapi(client, url, headers, collection, arm)
    except TimeoutError:
        # Translated, not propagated: every caller handles
        # `EndpointCheckFailedError`, and a bare `TimeoutError` would escape
        # those handlers as a 500 about nothing the caller can act on.
        raise EndpointCheckFailedError("deadline exceeded") from None
