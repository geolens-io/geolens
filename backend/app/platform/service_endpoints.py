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
import xml.parsers.expat
from collections.abc import Callable
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
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

# The OGC API link relations that name something a client FETCHES, PER
# DOCUMENT TYPE. Deliberately not every rel: `license`, `describedby` and
# `alternate` legitimately point at other origins on ordinary services, and
# refusing those would refuse the web. Deliberately not one set shared by
# every document either, which is what fix(#1770 round 46 P2) closes.
#
# fix(#1770 round 37 P2, `service_endpoints.py:126`): the rule is "only rels
# the probe or materializer dereference FROM THIS DOCUMENT" -- do not re-add
# a rel just because it looks operation-shaped, and do not apply a rel to a
# document type that never advertises the one it is actually read from.
# `self` and `data` were both wrong by the first half of that rule and are
# the reason this note exists: neither is ever GET'd anywhere in this
# codebase. `self` names the document itself and nothing here reads it;
# `data` is checked for PRESENCE only (`has_data_link` in
# `adapters/ogcapi.py`, a classification signal), never for its href, since
# `probe_ogcapi` builds `/collections` from the submitted URL directly rather
# than following the `data` link there.
#
# fix(#1770 round 46 P2, `service_endpoints.py:986`): round 37 got the REL
# right and the SCOPE wrong -- one set applied uniformly to every document
# `_check_ogcapi` reads, when only two rel+document pairs are ever
# dereferenced. A collections LISTING entry carrying a cross-origin
# `rel=conformance` (an ordinary provider-docs link, never read from
# anywhere but the landing page) refused the whole import even though
# nothing here was ever going to GET it. Traced against the actual GET call
# sites, not assumed, and now split into the document type each site reads:
#
#   - `_LANDING_RELS = {"conformance"}`, applied only to the LANDING page
#     (`_check_ogcapi`'s own initial fetch). `_resolve_conformance` in
#     `adapters/ogcapi.py` GETs `conformance` from the LANDING page's own
#     `links`, WITH the credential when the fetch is same-origin (it
#     degrades to "no conformance" rather than sending the credential
#     cross-origin, which is a second, independent guard -- this set exists
#     to refuse the import before that fetch is even attempted, with one
#     consistent error). Nothing ever reads a `conformance` link off a
#     collections listing, a listing entry, or a collection document, so
#     none of those carry this rel.
#   - `_COLLECTION_RELS = {"items"}`, applied only to the COLLECTION
#     document `_check_ogcapi` fetches directly
#     (`/collections/{collection}`, the `collection is not None` branch).
#     `_advertised_items_href` / `_resolve_items_url` in `service_items.py`
#     (`_ITEMS_REL`) GETs `items` from THAT document -- always fetched
#     fresh and directly, never from an inlined copy in a listing page (see
#     `_resolve_items_url`'s own docstring: "the collection document is
#     read first"). A collections LISTING ENTRY's own inlined `items` href
#     is consequently never read by anything -- traced through
#     `service_items.py` end to end -- so entries carry no rels at all,
#     the same as the listing page itself.
#   - The collections LISTING PAGE itself, and each ENTRY in its
#     `collections` array, dereference neither rel: nothing here or in
#     `service_items.py` GETs a `conformance` or an `items` link off either
#     document type. Both pass `frozenset()` explicitly at their call sites
#     below, naming the "dereferences nothing" answer rather than leaving
#     it to be inferred from an absent call.
#
# `next` is deliberately in NEITHER set, and that is a third thing worth not
# re-adding by analogy. `_check_ogcapi` below never reads an items page at
# all -- pagination there is entirely `service_items.py`'s, which already
# refuses a cross-origin `next` on its own
# (`test_a_cross_origin_next_is_refused_before_it_is_fetched`,
# `TestAPagedCollectionCannotWalkOffTheOrigin`). The one place THIS module
# reads a `next` -- the probe's own `/collections` listing walk, via
# `_next_page` -- is credential-free exploration bounded by
# `_MAX_COLLECTION_PAGES`, and r16 deliberately made a cross-origin or
# unparseable `next` there STOP the walk rather than refuse the whole probe
# (`test_a_listing_next_that_will_not_parse_stops_the_walk` pins it). Routing
# that page's `next` through either set as well would turn `_next_page`'s
# soft stop into a hard `CrossOriginEndpointError` and directly contradict
# that test -- confirmed by trying it in round 37 before writing this note,
# and unchanged by round 46's re-scoping.
#
# `test_service_auth_transport_1746.py` is what keeps this from drifting
# apart again, in two tests: `test_each_rel_is_traced_to_the_call_site_
# that_actually_dereferences_it` traces `conformance` to
# `_resolve_conformance` and `items` to `_resolve_items_url`/
# `_advertised_items_href`, the way this comment does above; `test_each_
# document_type_is_scoped_to_only_the_rel_it_reads` asserts `_LANDING_RELS`/
# `_COLLECTION_RELS` hold exactly their one member each and that
# `_check_ogcapi`'s four `_ogcapi_link_hrefs` call sites each pass the set
# (or `frozenset()`) this comment says they should.
_LANDING_RELS = frozenset({"conformance"})
_COLLECTION_RELS = frozenset({"items"})

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

# fix(#1770 round 43 P1): `structural_elements`'s worst-measured-cost table
# above priced ONE attribute per element (`<a b="1"/>` at 339 bytes). It
# still cannot undercount `<`, so it still bounds a document whose cost is
# spread across many elements -- but a single start tag carrying hundreds of
# thousands of uniquely named attributes counts as ONE `<` while
# ElementTree/expat still allocates one dict entry per attribute for that
# tag, so the per-ELEMENT budget above never sees it. Bounding the raw
# attribute total directly, at the same order of magnitude, closes that gap
# without asking the element count to answer a question it structurally
# cannot: how many attributes a single tag carries.
MAX_DOCUMENT_ATTRIBUTES = 500_000

# fix(#1770 round 43 P1): a WFS capabilities document nests a handful of
# levels deep (OperationsMetadata > Operation > DCP > HTTP > Get is five). A
# document built to nest one nominal element inside another, over and over,
# stays cheap on every other budget above -- one element and no attributes
# per level -- while still costing one Python object and one parser
# callback per level of depth.
#
# fix(#1770 round 47 P2): the round-43 comment's claim that 1,000 was "well
# under the interpreter's own default recursion ceiling" was the bug, not a
# safety margin: `sys.getrecursionlimit()`'s default IS 1,000, and this
# preflight is not the only thing that ever visits a parsed document's
# depth -- `_wfs_operation_hrefs`'s tree walk did, recursively, with no
# depth check of its own, so a document nested to exactly this budget
# passed the preflight and then blew the interpreter's own stack with an
# uncaught `RecursionError` before that walk (now made iterative, see its
# own docstring) ever got a turn. 256 is still well over an order of
# magnitude past anything a real capabilities or OGC API document nests --
# `OperationsMetadata > Operation > DCP > HTTP > Get` above is five, and the
# deepest measured real document (a WFS capabilities listing five thousand
# feature types) never exceeds a few dozen -- and leaves real headroom
# under the interpreter's ceiling for whatever else is already on the stack
# (this preflight's own caller chain, asyncio, the test runner) by the time
# any code visits a parsed document's depth, iteratively or not.
MAX_DOCUMENT_DEPTH = 256

# fix(#1770 round 47 P1). A service-ADVERTISED href -- an `items`/`next`/
# `conformance` link, a WFS operation endpoint -- sits inside a document
# already bounded by `MAX_DOCUMENT_BYTES`/`MAX_DOCUMENT_TOKENS`/
# `MAX_DOCUMENT_ELEMENTS`, but a query string is free real estate none of
# those budgets price correctly: the separators between millions of short
# `key=value` pairs live INSIDE one JSON string, so `structural_tokens`
# (which counts commas and brackets outside strings) answers ~0 for it, the
# same blind spot that motivated `MAX_DOCUMENT_ELEMENTS` for XML. `parse_qsl`
# has no length bound of its own and materialises every pair it finds before
# a caller's own comprehension or `urlencode()` copies the list again --
# three or more full passes over a value already sitting comfortably under
# every existing cap.
#
# 8192 is the conventional ~8 KiB server/proxy limit on a request line
# (RFC 7230 leaves the number to implementations; Apache's default
# `LimitRequestLine`, nginx's default `large_client_header_buffers`, and most
# CDNs all sit at or below it). Nothing this codebase advertises legitimately
# needs a longer one, so refusing anything over this length BEFORE any
# parsing at all is the real bound -- `MAX_QUERY_FIELDS` below is the second,
# independent one for a query string that slips past this length check by
# packing many SHORT pairs into few bytes.
MAX_SERVICE_HREF_BYTES = 8192

# fix(#1770 round 47 P1): the second, independent bound -- a query string
# `MAX_SERVICE_HREF_BYTES` bytes long can still pack over a thousand `a=1&`
# pairs. No real service-advertised URL in this codebase's own vocabulary
# (an OGC API/STAC/WFS/ArcGIS operation link) carries more than a handful to
# a few dozen query parameters; 256 is well past that with room to spare and
# well short of costing real memory or CPU to parse, filter, and re-encode.
MAX_QUERY_FIELDS = 256


class HrefTooLongError(ValueError):
    """Raised by `bounded_service_url` for an href over the length cap.

    fix(#1770 round 47b, low-priority wording fix): a `ValueError` subclass
    rather than a plain one, so a caller that wants distinct wording for
    "too long" versus "unparseable" (an ordinary `urljoin` failure) can add
    ONE specific `except HrefTooLongError:` ahead of its existing
    `except ValueError:`, which still catches this too (a subclass IS its
    parent) -- so a caller that does not bother stays correct with no
    change at all, same as before this class existed.
    """


def bounded_service_url(href: str, *, what: str) -> str:
    """*href*, refused before any parsing if it is unusually long.

    Every caller here already catches `ValueError` from `urljoin` on the
    same href (an unparseable address the document named), so raising a
    `ValueError` subclass lets this length check flow through each
    caller's EXISTING coded refusal with no new except clause required --
    see the call sites in `_next_page`/`_assert_same_origin` below,
    `_advertised_items_href`/`_next_href`/`_with_page_size` in
    `service_items.py`, and `_resolve_conformance` in `adapters/ogcapi.py`.
    """
    if len(href.encode("utf-8", errors="surrogatepass")) > MAX_SERVICE_HREF_BYTES:
        raise HrefTooLongError(f"{what} href exceeds {MAX_SERVICE_HREF_BYTES} bytes")
    return href


def bounded_parse_qsl(query: str) -> list[tuple[str, str]]:
    """`parse_qsl`, with `max_num_fields` applied -- the one bounded call
    site every other read of a service-advertised query string should
    share, so `test_every_parse_qsl_call_bounds_its_field_count` has one
    place to point at instead of one exception to write per call site.
    """
    return parse_qsl(query, max_num_fields=MAX_QUERY_FIELDS)


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

    fix(#1770 round 47b P2 class): `max_num_fields=MAX_QUERY_FIELDS`, the
    same bound `bounded_parse_qsl` applies to a service-advertised query.
    `url` here is the caller's own submitted service URL, not the live
    shape the finding named, but closing it costs nothing.
    """
    parsed = urlparse(url)
    params = {
        k: v[0]
        for k, v in parse_qs(parsed.query, max_num_fields=MAX_QUERY_FIELDS).items()
    }
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

# fix(#1770 round 36 P2): the operations the read-only ogr2ogr/OGR_WFS path can
# ever ask for. GetCapabilities and DescribeFeatureType are the discovery
# reads; GetFeature is the data read, paged by STARTINDEX/COUNT; GetPropertyValue
# is WFS 2.0's single-property fetch, which the driver can issue for the same
# reads. Nothing in this codebase runs ogr2ogr against a WFS source with
# ``-t transaction`` or with a lock held, so Transaction, LockFeature,
# GetFeatureWithLock and the 2.0 stored-query management operations
# (CreateStoredQuery / DropStoredQuery / ListStoredQueries /
# DescribeStoredQueries) are never requested and their advertised endpoint,
# on-origin or not, is never contacted with the credential.
#
# Matched lower-cased, the same normalisation `_WFS_ENDPOINT_ATTRIBUTES`
# already applies to the attribute name, since WFS 1.1/2.0 spells the name in
# the ``ows:Operation`` ``name`` attribute and 1.0 spells it as the element's
# own tag -- both PascalCase per spec, neither guaranteed by anything this
# parser enforces.
_WFS_READ_OPERATIONS = frozenset(
    {"getcapabilities", "describefeaturetype", "getfeature", "getpropertyvalue"}
)

# fix(#1770 round 36 P2): WFS 1.0 has no wrapping element that names an
# operation the way 1.1/2.0's ``ows:Operation name="..."`` does -- the
# operation IS the element, one level under ``<Request>``
# (``<GetFeature><DCPType>...``). This is the closed vocabulary of what that
# element can be, so a 1.0 document's OWN structural tags (``Request``,
# ``DCPType``, ``HTTP``) never get mistaken for an operation name. Per the
# WFS 1.0 schema, the same six names 1.1/2.0 use as ``ows:Operation`` values.
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


def _wfs_operation_hrefs(xml_bytes: bytes) -> list[str]:
    """The operation endpoints a capabilities document advertises for a read.

    fix(#1770 round 36 P2): filtered to the operations
    :data:`_WFS_READ_OPERATIONS` names, because the earlier version collected
    every ``Get``/``Post`` in the document regardless of which operation
    advertised it -- a service hosting ``Transaction`` or ``LockFeature`` on
    another origin (ordinary for a WFS-T deployment whose write endpoint is
    proxied separately from its read one) was refused for an endpoint the
    read-only ogr2ogr path this check protects can never reach.

    An endpoint this walk cannot attribute to a specific operation is kept
    rather than dropped: the set above is who is EXCLUDED from, not
    who is let in by default, so a document shape this parser does not
    recognise fails closed the way every other unreadable shape here does.

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

    def _local(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    # fix(#1770 round 47 P2): iterative, not recursive. `_xml_preflight`
    # (`require_decodable`'s XML branch, which runs before this ever does)
    # only bounds NESTING depth to `MAX_DOCUMENT_DEPTH` -- a document AT that
    # depth still reaches here, and it was Python's OWN call-stack limit,
    # not this module's budget, that decided whether walking it recursively
    # blew up: `MAX_DOCUMENT_DEPTH` used to be 1,000, `sys.
    # getrecursionlimit()`'s default IS 1,000, and this walk's own frames
    # were not the only ones already on the stack by the time it ran. An
    # explicit stack has no recursion limit of its own to hit, so this is
    # unconditionally safe at any depth `_xml_preflight` admits, independent
    # of how low `MAX_DOCUMENT_DEPTH` is or ever needs to be. Preserves the
    # same pre-order traversal the recursive version walked in: a LIFO stack
    # visits document order when children are pushed in reverse.
    #
    # fix(#1770 round 47b, low-priority): this is not a pure upside. The
    # recursive version's OWN call stack was bounded by DEPTH, one frame per
    # level; this explicit stack is bounded by the WIDEST single level's
    # BREADTH instead, since every child of a level is pushed before any of
    # them is popped. `MAX_DOCUMENT_ELEMENTS` (500,000) still bounds the
    # total regardless of shape, so a document built to be one enormous flat
    # level rather than one long chain can put on the order of 500,000
    # `(Element, str | None)` tuples on this stack at once -- tens of bytes
    # each, so tens of MB, not unbounded, but a real memory cost this walk's
    # OWN docstring did not previously name.
    stack: list[tuple[object, str | None]] = [(root, None)]
    while stack:
        element, operation = stack.pop()
        tag = _local(element.tag)
        if tag == "Operation":
            # 1.1/2.0: `ows:Operation name="GetFeature"`. A missing or blank
            # name leaves the context unattributed rather than guessing one,
            # which the fail-closed default above still checks.
            operation = (element.get("name") or "").strip().lower() or None
        elif tag in _WFS_1_0_OPERATION_TAGS:
            # 1.0: the element itself names the operation.
            operation = tag.lower()
        if tag in ("Get", "Post") and (
            operation is None or operation in _WFS_READ_OPERATIONS
        ):
            for name, value in element.attrib.items():
                local = _local(name).lower()
                if local in _WFS_ENDPOINT_ATTRIBUTES and value:
                    hrefs.append(value)
        stack.extend((child, operation) for child in reversed(list(element)))

    return hrefs


def _ogcapi_link_hrefs(document: object, rels: frozenset[str]) -> list[str]:
    """The operation endpoints one OGC API document advertises, among *rels*.

    fix(#1770 round 46 P2): *rels* is the caller's to choose, not a single
    tree-wide set -- see `_LANDING_RELS`/`_COLLECTION_RELS`'s own comment
    for which document type gets which rels, and why a rel this codebase
    never dereferences FROM a given document type must not be checked
    against it.
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
                # fix(#1770 round 47 P1): refused before `urljoin` even runs,
                # not just before whatever eventually calls `parse_qsl` on
                # the result -- see `bounded_service_url`'s own docstring.
                resolved = urljoin(
                    base, bounded_service_url(str(link["href"]), what="next")
                )
            except ValueError as exc:
                # fix(#1746 B2b review r16): same guard as `_assert_same_origin`
                # below, and the sibling of the site the review named. An
                # address the parser cannot read is not one to walk to, and the
                # walk already stops rather than refuses when `next` leaves the
                # origin.
                #
                # fix(#1770 round 47b, low-priority): warned now, same as the
                # sibling stop at `_MAX_COLLECTION_PAGES` below -- this used
                # to end the walk with no signal at all, indistinguishable
                # from an ordinary last page. `isinstance` rather than a
                # second `except`, so the log line and the return both stay
                # in one place. The href is never in the message, same
                # reason as `_assert_same_origin`.
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
    advertises ``/wfs`` or ``collections/x/items`` is describing itself and
    passes. An href that cannot be parsed at all is refused, because
    ``same_origin`` answers False for it and an address this cannot read is not
    one to send a credential to.
    """
    for href in hrefs:
        try:
            # fix(#1770 round 47 P1): the same length gate `_next_page`
            # applies, before `urljoin` -- this is the shared sink both
            # `_ogcapi_link_hrefs` (OGC API) and `_wfs_operation_hrefs`
            # (WFS, including its 1.0 `onlineResource` spelling) feed into,
            # so gating it here closes the class for both formats in one
            # place.
            href = bounded_service_url(href, what="operation")
            # fix(#1746 B2b review r19): relative to the document, which after
            # a canonical redirect is not the URL that was asked for. The
            # origin compared against is still the submitted one.
            resolved = urljoin(base or url, href)
        except HrefTooLongError:
            # fix(#1770 round 47b, low-priority): its own wording, distinct
            # from the generic `urljoin` failure below -- both used to say
            # "unparseable", which is true of a malformed address but not of
            # one that is merely too long to have been parsed at all. The
            # raw href is never echoed either way.
            raise CrossOriginEndpointError("href exceeds the length limit") from None
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


class _XmlPreflightBudgetExceeded(Exception):
    """Internal signal only: a streaming XML preflight budget tripped.

    Raised inside an ``xml.parsers.expat`` handler and caught immediately by
    ``_xml_preflight`` itself, one frame up -- it never crosses that
    function's own boundary, so it is not part of `require_decodable`'s
    public contract (`EndpointCheckFailedError` is).
    """


def _xml_preflight(
    body: bytes,
    *,
    element_budget: int,
    attribute_budget: int,
    depth_budget: int,
    text_byte_budget: int,
) -> None:
    """Count elements, attributes, text bytes and nesting depth via a
    streaming parser, aborting the instant any ONE budget trips -- before a
    single `ElementTree` node is ever built.

    fix(#1770 round 43 P1). `structural_elements`'s ``body.count(b"<")``
    bounds the case its own worst-measured-cost table was calibrated
    against -- cost spread across many elements, roughly one attribute
    each. It cannot see a DIFFERENT shape of the same class: a single start
    tag carrying hundreds of thousands of uniquely named attributes counts
    as one ``<``, comfortably under `MAX_DOCUMENT_ELEMENTS`, while
    ElementTree/expat still allocates one dict entry per attribute for that
    tag -- an "attribute bomb" the per-element proxy structurally cannot
    price. Nor can it price a document built to nest one element inside
    another thousands of times over (a "deep-nesting bomb": cheap on every
    byte-scan proxy, one parser callback and one Python object per level of
    depth), or a document that concentrates its entire byte budget into one
    enormous run of character data outside any element/attribute count at
    all (a "text bomb").

    `xml.parsers.expat` calls back per element, per attribute, and per
    chunk of character data as it lexes -- without ever building a tree --
    so each of the four costs is counted directly, against its own budget,
    and refused the moment ANY ONE is crossed, rather than inferred from a
    proxy a concentrated shape can defeat. This does not replace the cheap
    `structural_elements` byte-scan in `require_decodable` below -- that
    scan still short-circuits the common egregious case (millions of tiny
    elements) without engaging a parser at all -- it closes the gap that
    scan leaves.

    Malformed XML is not this preflight's problem to diagnose: a body that
    cannot be lexed at all raises `xml.parsers.expat.ExpatError`, which is
    swallowed here and left for `ET.fromstring` (the real parse, which runs
    next on a body that passed every budget) to raise its own, more
    specific error for.
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
        # `xml.parsers.expat` on its own -- unlike `defusedxml`, which wraps
        # it -- expands internal entities during parsing with no bound at
        # all: the classic "billion laughs" shape. This preflight uses raw
        # expat for the callbacks `defusedxml.ElementTree` does not expose,
        # so it has to refuse the same class itself rather than inherit the
        # protection from a wrapper it is not going through. Refusing at
        # entity DECLARATION time means the substitution this handler exists
        # to prevent never runs at all -- there is no bounded amount of
        # expansion to allow, since a real capabilities document has no use
        # for a custom entity in the first place.
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
    """Refuse a document that would cost too much to build. fix(#1746 r22/r23/r26).

    A byte cap bounds the wire, not the object graph, and the two document
    kinds this reads expand through completely different structures. The kind
    is not guessed: it is the ``accept`` value the read already negotiated
    with, so a document is bounded by the parser it is actually going to.

    Called from `fetch_document` below, which is the only place either module
    makes a request, so it covers every document either one reads.

    fix(#1770 round 43 P1): the XML branch now runs TWO passes. The cheap
    `structural_elements` byte-scan still short-circuits the common
    egregious case first, with no parser engaged at all. `_xml_preflight`
    then runs a real streaming parse to catch the shapes that scan cannot
    see -- an attribute bomb, a deep-nesting bomb, a text bomb -- reusing
    `token_budget`'s number as the text-byte ceiling (the "same order of
    decoded content" bound `MAX_DOCUMENT_TOKENS` already represents, on a
    different unit of measure: JSON punctuation there, raw text bytes
    here), and `element_budget` again for the exact count expat gives
    directly rather than the byte-scan's approximation.
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

    ``on_first_request`` is fired once SSRF validation has succeeded, right
    before the request goes out. Wrap it in `fire_once` if it should fire for
    the first read only, which is what a caller dating origin contacts wants.
    fix(#1746 B2b round 34): it used to fire before `validate_url_for_ssrf`,
    so a rejection (a host that resolved publicly at the door and privately by
    the time the worker asked) still dated a contact that never happened.

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
    try:
        await validate_url_for_ssrf(url)
        if on_first_request is not None:
            # fix(#1746 B2b round 34): only once validation has succeeded.
            on_first_request()
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
    """``json.loads(body)``, or a coded refusal rather than a raw crash.

    fix(#1770 round 44 P2): a JSON depth bomb -- 900,000 nested `[` is 1.8
    bytes each, well under both `MAX_DOCUMENT_BYTES` and
    `MAX_DOCUMENT_TOKENS` (`structural_tokens` counts brackets, not nesting
    depth, so it cannot see this shape at all) -- makes `json.loads` raise
    `RecursionError`, not `ValueError`. Uncaught, that escaped `/probe`'s own
    except chain as a bare 500 rather than the coded `endpoint_check_failed`
    every other unreadable description gets, and in a worker OAPIF walk it
    killed the job unclassified. `RecursionError` is a `RuntimeError`
    subclass, not a `ValueError`, so it needed naming here explicitly rather
    than falling out of the existing catch.
    """
    try:
        return json.loads(body)
    except (ValueError, RecursionError) as exc:
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
    except RecursionError as exc:
        # fix(#1770 round 47 P2): last line of defense, not the primary fix
        # -- `_wfs_operation_hrefs`'s own walk is iterative now and cannot
        # raise this itself. Kept because `ET.fromstring` (defusedxml) is
        # not this module's code, and this is the one place a document that
        # passed every other budget still reaches an unhandled exception if
        # something in that dependency ever does recurse. Translated to the
        # same coded refusal every other unreadable description gets, same
        # as `_parsed_json`'s own `RecursionError` handling (round 44).
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
    # fix(#1770 round 46 P2): `_LANDING_RELS` -- this is the landing page,
    # the only document type `conformance` is ever read from.
    _assert_same_origin(
        url, _ogcapi_link_hrefs(_parsed_json(body), _LANDING_RELS), from_url
    )

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
        # fix(#1770 round 46 P2): `_COLLECTION_RELS` -- this is the
        # collection document, the only document type `items` is ever read
        # from.
        _assert_same_origin(
            url, _ogcapi_link_hrefs(document, _COLLECTION_RELS), from_url
        )
        return

    # The probe has no collection yet, so it walks the listing. Bounded, and
    # reaching the bound is recorded rather than treated as a clean pass.
    #
    # fix(#1770 round 46b P2): the per-collection branch above (`_COLLECTION_
    # RELS`) is NOT reached by the two paths that spend the credential, and
    # this comment used to claim it was. `assert_endpoints_stay_on_origin`'s
    # only LIVE caller for `ogcapi_features` is this probe route
    # (`sources/router.py`'s `/probe` handler), which never passes a
    # `collection` -- the `collection is not None` branch is currently
    # unreachable in production. Preview (`preview.py::_localise_protected_
    # oapif`) and the worker (`ogr.py`) both materialise a protected OAPIF
    # collection IN-PROCESS first and hand GDAL a local file with the
    # credential/token already nulled out, so the `if credential/token`
    # guard on THEIR `assert_endpoints_stay_on_origin` call is false and
    # `_check_ogcapi` never runs for them at all -- the `items` guard those
    # two paths actually rely on is `_resolve_items_url`'s own `same_origin`
    # check in `service_items.py`, independent of this module. Traced end to
    # end, not assumed: see `test_a_late_collections_items_link_is_allowed_
    # at_the_probe`'s docstring in `test_service_auth_transport_1746.py`.
    page_url: str | None = f"{url.rstrip('/')}/collections"
    for _page in range(_MAX_COLLECTION_PAGES):
        if page_url is None:
            return
        body, from_url = await _fetch(client, page_url, headers)
        listing = _parsed_json(body)
        # fix(#1770 round 46 P2): the listing page dereferences neither rel
        # -- `frozenset()` names that explicitly rather than skipping the
        # call. `next` is still handled separately below, by `_next_page`,
        # unchanged by this round.
        # fix(#1770 round 46b P3): a deliberate no-op -- `_ogcapi_link_hrefs`
        # returns `[]` for any document given `frozenset()`, so this can
        # never refuse. Kept, rather than dropped, so `test_each_document_
        # type_is_scoped_to_only_the_rel_it_reads` has a real call site to
        # pin the scoping against.
        _assert_same_origin(url, _ogcapi_link_hrefs(listing, frozenset()), from_url)
        collections = listing.get("collections") if isinstance(listing, dict) else None
        for entry in collections or []:
            # fix(#1770 round 46 P2): a listing ENTRY's inlined `items` href
            # is never read either -- `_resolve_items_url` always re-fetches
            # the collection document directly and reads ITS `items` link
            # (see `_COLLECTION_RELS`'s comment). Entries therefore
            # dereference nothing, the same as the listing page itself, and
            # a cross-origin `conformance` link on an entry -- an ordinary
            # provider-docs link nothing here ever follows -- no longer
            # refuses the whole import.
            # fix(#1770 round 46b P3): also a deliberate no-op, for the same
            # reason as the listing-page call above -- kept for the same
            # structural test to pin.
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
