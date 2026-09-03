"""Read a protected OGC API collection ourselves, so GDAL never holds the key.

fix(#1746 B2b review r16). An OGC API items response chooses the next one: each
page carries a ``rel=next`` link, and GDAL's OAPIF driver follows it. Because
``GDAL_HTTP_HEADER_FILE`` applies to every request the process makes, a
collection whose first page is same-origin can hand the credential to any origin
it likes on page two, with no redirect and nothing for a redirect hook to see.

Validating the description up front cannot bound that, because the chain is
chosen at run time, one page at a time. Two ways out, and the first was measured
before the second was written.

GDAL 3.10.3, the version in the worker image, was tested for a path-scoped
header option: two local servers, the credential configured for the first only,
`ogr2ogr` run against an OAPIF endpoint whose `next` pointed at the second. A
``[configoptions]`` section of a ``GDAL_CONFIG_FILE`` applied the option and
proved the file is read; every ``[credentials]`` ``path=`` prefix applied it to
nothing at all, including the origin it named. ``CPLHTTPFetch``, which both the
WFS and OAPIF drivers use, does not consult path-specific options for http(s)
URLs; that section serves the ``/vsi*`` handlers. So the scope does not exist
and the credential cannot be confined inside GDAL.

Therefore GDAL is not given the credential for this path at all. The pages are
read here, with the bounded client that revalidates SSRF and refuses to leave
the origin, streamed to a local GeoJSON file, and GDAL is handed that file. It
follows nothing, because there is nothing left to follow.

WFS needs none of this, and that was measured too rather than assumed: served a
``wfs:FeatureCollection`` carrying ``next="http://other-origin/"``, GDAL fetched
it never. The WFS driver pages by ``STARTINDEX``/``COUNT`` against the
GetFeature endpoint the capabilities advertise, which is exactly the endpoint
``service_endpoints`` validates, so that driver is bounded by the description
check already.

What a service is allowed to cost, since the whole chain is its to choose:

``MAX_PAGES`` (10,000) requests, ``MAX_BYTES`` (2 GiB) downloaded and the same
again written to the staging volume, ``MAX_PAGE_BYTES`` (16 MiB) on the wire
for any one page, and ``MAX_STRUCTURAL_TOKENS`` (2,000,000) values or
containers in any one page once decoded. Reaching any of them is a refusal,
never a short answer: a caller cannot tell a prefix from a collection, and the
worker would import one over an existing dataset.

The last of those is the least obvious and the reason the others are not
enough. A byte cap bounds the wire, not the object graph, and compact JSON
expands 4x to 31x depending on shape (measured; the figures are beside the
constant). The token bound is counted on the raw bytes before anything is
decoded, so it costs three ``bytes.count`` passes and refuses before the
memory would have been spent.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
import structlog

from app.core.runtime.staging import (
    OAPIF_ITEMS_SCRATCH_PREFIX,
    OAPIF_ITEMS_SCRATCH_SUFFIX,
)
from app.platform.security import (
    PROBE_TIMEOUT,
    make_safe_client,
    same_origin,
)
from app.platform.service_endpoints import (
    MAX_DOCUMENT_BYTES,
    MAX_DOCUMENT_TOKENS,
    EndpointCheckFailedError,
    OGC_JSON_ACCEPT,
    credential_headers,
    deadline_budget,
    fetch_document,
    fire_once,
)

logger = structlog.stdlib.get_logger(__name__)

# What one collection may cost. A page chain is chosen by the service, so it is
# bounded here rather than trusted: an endpoint that keeps answering `next`
# forever would otherwise be an unbounded fetch holding a credential.
#
# Reaching either is a refusal, never a short answer: see `_walk_pages`.
#
# `MAX_BYTES` bounds the bytes DOWNLOADED and, separately, the bytes WRITTEN.
# r17 added the first because a page is decoded before any feature of it is
# written, so counting the output missed where the memory goes. r19 then
# removed a written-bytes counter on the reasoning that compact UTF-8 output
# is a subset of the pages it came from and so cannot be larger. That was
# wrong, and r20 caught it: a JSON round trip can GROW. `1e15` is four bytes
# on the wire and parses to a float whose repr is `1000000000000000.0`, which
# is eighteen. Python only switches to exponent notation at 1e16, so a page of
# such numbers expands by more than four times on the way to disk, and a chain
# comfortably inside the download cap could leave many gigabytes on a staging
# volume shared with every other import. Both counters exist now, and the
# written one is a real bound on disk rather than an inference from the wire.
MAX_PAGES = 10_000
MAX_BYTES = 2 * 1024 * 1024 * 1024

# What one page may cost on the wire, enforced by the shared reader in
# `service_endpoints` while it streams and before anything is decoded. A page
# is held whole in memory to be parsed, so this is a per-request bound the
# total above cannot substitute for: one oversized response would exhaust the
# process long before a running total noticed.
#
# fix(#1746 B2b review r22): 64 MiB down to 16 MiB. The page size is ours
# (`limit=`), so a well-behaved service never approaches either figure, and
# the total budget is on disk rather than in memory. 16 MiB against
# `PAGE_SIZE` features is ~16 KiB of JSON per feature, still far past any
# honest geometry, and a service wanting more can paginate.
MAX_PAGE_BYTES = 16 * 1024 * 1024

# What one page may cost DECODED, bounded before `json.loads` runs.
#
# fix(#1746 B2b review r22): the wire cap bounds bytes, not the object graph,
# and compact JSON expands enormously. Measured on this interpreter against
# 1 MiB pages:
#
#     [1.5,1.5,...]     8.2x    (32.8 bytes per structural token)
#     [1,1,...]         4.5x    ( 8.9 bytes per token)
#     [{"a":1},...]    24.1x    (96.4 bytes per token)
#     [[[1]],...]      30.7x    (61.4 bytes per token)
#
# So one 16 MiB page of the worst shape is ~490 MiB decoded, and 64 MiB was
# ~2 GiB: the whole API container, from a single page, with concurrent
# previews making it worse.
#
# `_structural_tokens` counts commas and opening brackets on the RAW bytes,
# which is an upper bound on the number of values and containers the decoder
# will build: every value after the first is preceded by a comma, every
# container opens with a bracket, and commas inside strings only overcount,
# which is the safe direction. At the worst measured cost of ~96 bytes per
# token, two million tokens is ~184 MiB decoded, which is the figure this
# constant is chosen for. A full page of `PAGE_SIZE` polygon features costs
# about 22,000 tokens (measured, and pinned in the suite), so the bound is
# roughly ninety times what an honest service asking for the page size it was
# given would ever produce.
MAX_STRUCTURAL_TOKENS = 2_000_000

# What a page fetch asks for. The service may answer with fewer.
PAGE_SIZE = 1000


class MaterialisedCollection(NamedTuple):
    """A local extract, and what is known about the collection behind it.

    fix(#1746 B2b review r24): the path alone was not enough. A preview asks
    for a handful of features and gets a file holding exactly that many, so
    everything downstream read the sample size as the collection's row count:
    the import preview showed it, and re-upload's schema diff turned it into a
    row-count delta against the real dataset.

    ``total`` is the collection's own size when it can be known: the service's
    ``numberMatched`` if it published one, otherwise the features written when
    the walk ran to the end. ``None`` when the walk stopped at a sample limit
    and the service said nothing, which is the case that was being guessed at.
    """

    path: str
    features: int
    total: int | None


class ItemFetchFailedError(EndpointCheckFailedError):
    """A page could not be read, or the chain tried to leave the origin.

    Subclasses the description check's refusal so every door that already
    answers that one answers this the same way: the caller's request named a
    URL whose collection cannot be read safely, and the field to change is the
    same.
    """


def _discard(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _items_url(url: str, collection: str) -> str:
    return (
        f"{url.rstrip('/')}/collections/{quote(collection, safe='')}"
        f"/items?limit={PAGE_SIZE}"
    )


def _require_object(document: object, what: str) -> dict:
    """The document, or a refusal. Never echoes what came back.

    fix(#1746 B2b review r21): every place a fetched document is interpreted
    goes through here or through `_require_feature_page` below, so a service
    that answers 200 with something else is refused once rather than
    reinterpreted differently at each site.
    """
    if not isinstance(document, dict):
        raise ItemFetchFailedError(f"malformed {what}")
    return document


def _require_feature_page(document: object, *, first_page: bool) -> list:
    """The features of one items page, or a refusal.

    fix(#1746 B2b review r21): `features or []` read an HTTP 200 JSON error
    envelope as an empty page, and read `"features": null` and
    `"features": {}` the same way. A preview then succeeded with zero rows and
    a refresh or re-upload handed an empty FeatureCollection to ogr2ogr, which
    replaced existing data with nothing: the silent-truncation class of r18,
    one level up. A page that does not say what it is does not get to say it
    is empty.

    fix(#1746 B2b review r29): the same rule, applied to every shape the walker
    could otherwise read as "this was the last page". MALFORMED MEANS REFUSE,
    AND NEVER MEANS END-OF-COLLECTION. `_has_next` and `_next_href` both answer
    None for a shape they cannot read, and None is indistinguishable from a
    service saying there is no more, so anything they would skip has to be
    refused before they are asked. Enumerated, because the class is what
    matters and not the instance:

    * ``links`` present but not a list. Iterating an OBJECT yields its keys,
      which are strings, so no link dict is ever found and the chain looks
      finished. This is the one r29 reported.
    * an entry of ``links`` that is not an object. Skipped by the same
      `isinstance` test, so a ``next`` expressed as a list or a bare string
      disappears.
    * a ``rel=next`` entry whose ``href`` is absent, not a string, or blank.
      A falsy href fails the truthiness test and the link vanishes; a
      non-string one would be coerced by `str()` into an address nobody named.
    * ``links`` missing entirely on a page that is NOT the first. Reaching that
      page means following a link, so the service does emit them; a page that
      suddenly has none is a truncated response rather than a last page. OGC
      API Features requires links on every items response, so this is
      spec-aligned, but it is only enforced from the second page because a
      single-page collection that omits them is common and harmless -- nothing
      is being decided from a link there.
    * ``numberMatched`` present and not a non-negative integer. Not a
      truncation risk on its own, but it is the number a preview reports as the
      collection's size and re-upload turns into a row-count delta, so a
      service that cannot spell it is not one to take counts from.
    * ``features`` not a list, from r21.

    A legitimately empty page is `{"type": "FeatureCollection", "features": []}`
    and still reads as empty, which is what makes the refusal specific.
    """
    page = _require_object(document, "items page")
    if page.get("type") != "FeatureCollection":
        raise ItemFetchFailedError("malformed items page")
    features = page.get("features")
    if not isinstance(features, list):
        raise ItemFetchFailedError("malformed items page")
    _require_links(page, first_page=first_page)
    _require_number_matched(page)
    return features


def _require_links(page: dict, *, first_page: bool) -> None:
    """Refuse a ``links`` member the pagination walk could misread."""
    links = page.get("links")
    if links is None:
        if "links" in page or not first_page:
            # An explicit null is malformed either way; an absent one is only
            # tolerated on the first page, where nothing was followed to get
            # here and nothing is decided from a link.
            raise ItemFetchFailedError("malformed items page")
        return
    if not isinstance(links, list):
        raise ItemFetchFailedError("malformed items page")
    for link in links:
        if not isinstance(link, dict):
            raise ItemFetchFailedError("malformed items page")
        if link.get("rel") != "next":
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            raise ItemFetchFailedError("malformed items page")


def _require_number_matched(page: dict) -> None:
    """Refuse a ``numberMatched`` that is present and not a count."""
    if "numberMatched" not in page:
        return
    candidate = page["numberMatched"]
    if not isinstance(candidate, int) or isinstance(candidate, bool) or candidate < 0:
        raise ItemFetchFailedError("malformed items page")


# What a collection document advertises for the features themselves. Preferred
# over the conventional layout, which is a guess, and preferred by media type
# where the service offers more than one representation.
_ITEMS_REL = "items"
_ITEMS_MEDIA_TYPE = "application/geo+json"


def _advertised_items_href(document: dict, base: str) -> str | None:
    """The collection's own ``rel=items`` link, resolved, or None.

    fix(#1746 B2b review r20): fabricating ``/collections/{id}/items`` was a
    regression against the path this replaced. GDAL followed the advertised
    link, and `service_endpoints` still treats advertised links as the
    authoritative statement of where a service keeps things, so a valid service
    with a non-conventional layout passed the probe and then 404ed at preview
    and import. What the document says wins; the convention is the fallback for
    a document that says nothing.
    """
    candidates = [
        link
        for link in document.get("links", []) or []
        if isinstance(link, dict) and link.get("rel") == _ITEMS_REL and link.get("href")
    ]
    if not candidates:
        return None
    chosen = next(
        (
            link
            for link in candidates
            if str(link.get("type", "")).lower().startswith(_ITEMS_MEDIA_TYPE)
        ),
        candidates[0],
    )
    try:
        return urljoin(base, str(chosen["href"]))
    except ValueError:
        # Same rule as `next`: an address that will not parse cannot be shown
        # to stay on the origin, and the href is never echoed.
        raise ItemFetchFailedError("unparseable items link") from None


def _with_page_size(href: str) -> str:
    """The advertised link, asking for the page size this module wants.

    Every other parameter the service put on its own link is kept: a
    `f=json` or a fixed filter is part of where it said the items are.
    """
    parts = urlsplit(href)
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "limit"]
    query.append(("limit", str(PAGE_SIZE)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _has_next(document: object) -> bool:
    """Whether the page offers another one, without resolving where.

    fix(#1746 B2b review r28): asked when the walk is stopping at the sample
    limit and is not going to follow the link, so it must not resolve it, must
    not judge its origin, and must not refuse an unparseable one -- all three
    would turn "your preview is complete" into a failure. It answers only the
    question that decides whether the extract is the whole collection.
    """
    if not isinstance(document, dict):
        return False
    return any(
        isinstance(link, dict) and link.get("rel") == "next" and link.get("href")
        for link in document.get("links", []) or []
    )


def _next_href(document: object, base: str) -> str | None:
    if not isinstance(document, dict):
        return None
    for link in document.get("links", []) or []:
        if isinstance(link, dict) and link.get("rel") == "next" and link.get("href"):
            try:
                return urljoin(base, str(link["href"]))
            except ValueError:
                # fix(#1746 B2b review r16): the page that named this address
                # is the one this module exists to distrust, and an address
                # that will not parse cannot be shown to stay on the origin.
                # Refused rather than treated as the end of the chain, so a
                # short read is never mistaken for a complete one. The href is
                # never echoed.
                raise ItemFetchFailedError("unparseable next page") from None
    return None


async def _fetch_page(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    *,
    budget: int,
    token_budget: int | None = None,
    on_first_request: "Callable[[], None] | None" = None,
) -> tuple[object, int, str]:
    """One items page, its wire size and its URL, or a refusal.

    fix(#1746 B2b review r23): the request itself is `fetch_document` in
    `service_endpoints`, shared with the description reads, so the protections
    the two paths need cannot diverge again. This adds only what is specific to
    an items page: the caps it is read under, and the decode.
    """
    body, final_url = await fetch_document(
        client,
        url,
        headers,
        # fix(#1746 B2b review r25): the same value the probe and the endpoint
        # check ask for. An items page is an OGC API document like the rest,
        # and a service that serves HTML for `*/*` must not be able to answer
        # one of the three reads differently from the other two.
        accept=OGC_JSON_ACCEPT,
        budget=budget,
        # Read at call time for the same reason `fetch_document` does it: a
        # default argument would freeze the constant at definition.
        token_budget=MAX_STRUCTURAL_TOKENS if token_budget is None else token_budget,
        error=ItemFetchFailedError,
        on_first_request=on_first_request,
    )
    try:
        return json.loads(body), len(body), final_url
    except ValueError as exc:
        raise ItemFetchFailedError(str(exc)) from None


async def _resolve_items_url(
    client: httpx.AsyncClient,
    *,
    url: str,
    collection: str,
    headers: dict,
    on_first_request: "Callable[[], None] | None" = None,
) -> tuple[str, int]:
    """Where this collection actually keeps its items, and what asking cost.

    The collection document is read first and its ``rel=items`` link is what
    the walk follows, judged by the same rules as a ``next``: resolved against
    the URL the document came from, refused if it leaves the submitted origin,
    and revalidated for SSRF by `_fetch_page` before it is requested.

    A document that advertises no items link falls back to the conventional
    layout, which is what a service following the usual shape would have
    advertised anyway.
    """
    document, size, from_url = await _fetch_page(
        client,
        f"{url.rstrip('/')}/collections/{quote(collection, safe='')}",
        headers,
        budget=MAX_DOCUMENT_BYTES,
        # A collection document is a description, so it gets the description
        # budget rather than an items page's.
        token_budget=MAX_DOCUMENT_TOKENS,
        on_first_request=on_first_request,
    )
    href = _advertised_items_href(
        _require_object(document, "collection document"), from_url
    )
    if href is None:
        return _items_url(url, collection), size
    if not same_origin(url, href):
        # The same rule the page chain gets, for the same reason: the document
        # chose this address and does not get to choose a different service to
        # be paid with this credential.
        raise ItemFetchFailedError("items link leaves the origin")
    return _with_page_size(href), size


async def _walk_pages(
    client: httpx.AsyncClient,
    out,
    *,
    url: str,
    collection: str,
    headers: dict,
    feature_limit: int | None,
    on_first_request: Callable[[], None] | None,
) -> tuple[int, int, int | None, bool]:
    """Follow the chain, writing features.

    Returns pages read, features written, what the service said the whole
    collection holds (fix(#1746 B2b review r24): a preview writes
    ``feature_limit`` features and nothing downstream could tell that apart
    from a collection that small), and whether the walk stopped SHORT
    (fix(#1746 B2b review r28): a collection holding exactly the sample size is
    complete, and counting features could not say so).
    """
    written = 0
    pages = 0
    on_disk = 0
    number_matched: int | None = None
    # fix(#1746 B2b review r28): whether the walk STOPPED SHORT, as opposed to
    # having written as many features as there are. `written >= feature_limit`
    # cannot tell those apart: a collection holding exactly the sample size
    # satisfies it while being complete, and r24 then reported its total as
    # unknown. Only the site that breaks out of the loop knows which happened.
    truncated = False
    # fix(#1746 B2b review r17, moved r20, made once-ness r23): the origin is
    # contacted HERE, not by the subprocess, so this is the moment a caller
    # that dates origin contacts has to hear about. `fire_once` means the
    # request function can fire it on every read and only the first one lands,
    # so no loop has to remember which pass it is on.
    arm = fire_once(on_first_request)
    first_page, downloaded = await _resolve_items_url(
        client, url=url, collection=collection, headers=headers, on_first_request=arm
    )
    out.write(b'{"type": "FeatureCollection", "features": [')
    page_url: str | None = first_page
    while page_url is not None and pages < MAX_PAGES:
        pages += 1
        document, size, from_url = await _fetch_page(
            client,
            page_url,
            headers,
            budget=min(MAX_PAGE_BYTES, MAX_BYTES - downloaded),
            on_first_request=arm,
        )
        downloaded += size
        # Both the first page and every page a `next` named. One rule, one
        # site, so a malformed page cannot mean different things depending on
        # where in the chain it arrived.
        features = _require_feature_page(document, first_page=pages == 1)
        if "numberMatched" in document:
            # OGC API Features part 1: the number of features the whole query
            # matches, as opposed to the number this page returned. Optional,
            # and already validated as a non-negative integer by
            # `_require_feature_page` when it is present at all (r29).
            #
            # fix(#1746 B2b review r30): read from EVERY page, not just the
            # first. It is a statement about the whole query, so two pages
            # giving different answers means the service is describing two
            # different queries and neither can be checked against the walk.
            reported = document["numberMatched"]
            if number_matched is None:
                number_matched = reported
            elif reported != number_matched:
                raise ItemFetchFailedError("pages disagree about the size")
        for index, feature in enumerate(features):
            # fix(#1746 B2b review r19): `ensure_ascii=False`, and the file
            # opened in binary. The default escapes every non-ASCII character
            # to `\uXXXX`, so a collection of non-Latin text wrote roughly
            # three bytes on disk for each one counted against the download
            # cap: a chain just under 2 GiB downloaded could leave ~6 GiB on a
            # staging volume shared with every other import.
            #
            # fix(#1746 B2b review r20): and counted, because r19 concluded
            # from this that the file could not exceed the download and that
            # was wrong. A JSON round trip can grow: `1e15` is four bytes on
            # the wire and eighteen written. The bound on disk is measured now
            # rather than inferred.
            encoded = json.dumps(
                feature, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            chunk = b"," + encoded if written else encoded
            # fix(#1746 B2b review r21): compared BEFORE the write. Checking
            # afterwards let the extract exceed the cap by one expanded
            # feature, which on this path is exactly the value that expands
            # unboundedly, so the bound was one feature short of being one.
            if on_disk + len(chunk) > MAX_BYTES:
                raise ItemFetchFailedError("collection exceeds the cap on disk")
            out.write(chunk)
            on_disk += len(chunk)
            written += 1
            if feature_limit is not None and written >= feature_limit:
                # Short only if something was left: more features on this page,
                # or another page on offer. Landing exactly on the last feature
                # of the last page is a complete read that happens to be the
                # size of the sample.
                truncated = index + 1 < len(features) or _has_next(document)
                page_url = None
                break
        else:
            following = _next_href(document, from_url)
            if following is not None and not same_origin(url, following):
                # The whole reason this module exists. The page chose the next
                # address; it does not get to choose a different service to be
                # paid with this credential.
                raise ItemFetchFailedError("next page leaves the origin")
            page_url = following
    if page_url is not None:
        # fix(#1746 B2b review r18): the page cap was reached and the service
        # still had more to give. Closing the array here would return a prefix
        # that reads as a complete collection, and the worker would import it
        # over an existing dataset: a silent truncation nothing downstream
        # could detect. A preview that reached its sample size has already set
        # `page_url` to None, so this only fires on a genuinely short read.
        raise ItemFetchFailedError("collection exceeds the page cap")
    if (
        feature_limit is None
        and number_matched is not None
        and written != number_matched
    ):
        # fix(#1746 B2b review r30): the chain ran out, and the service's own
        # count says it should not have. A `next` link that is missing when
        # there are more features to come is exactly the truncation r18 and
        # r29 refuse in their own ways, and this is the form of it the response
        # itself proves: nothing about the document is malformed, the walk just
        # ended early. Accepting it handed a re-upload ten features to replace
        # a hundred with.
        #
        # Both directions. More than reported is not a happier outcome, it is a
        # service whose count cannot be trusted, and that count is what a
        # preview reports and re-upload turns into a row-count delta.
        #
        # FULL walks only, which is the path where getting this wrong destroys
        # data: the worker imports the extract over an existing dataset. A
        # sampled read is expected to be short by construction, so the count
        # says nothing about whether the chain ended early, and `truncated`
        # from r28 is what carries that judgement there. `feature_limit is
        # None` also implies `not truncated`, since only the sample limit
        # breaks out of the loop.
        raise ItemFetchFailedError("collection is shorter than reported")
    out.write(b"]}")
    return pages, written, number_matched, truncated


async def materialise_oapif_items(
    url: str,
    collection: str,
    *,
    credential_line: str,
    staging_dir: str | Path,
    feature_limit: int | None = None,
    deadline: float | None = None,
    on_first_request: Callable[[], None] | None = None,
) -> MaterialisedCollection:
    """Write a protected collection to a local GeoJSON file and describe it.

    The caller hands the returned path to GDAL INSTEAD of the OAPIF source, and
    writes no header file at all, which is what removes the credential from
    everything GDAL does.

    ``feature_limit`` stops early for a preview, which needs a handful of rows
    rather than the collection.

    ``deadline`` is a :func:`time.monotonic` stamp by which the whole
    materialisation must be done, and it wraps every page rather than every
    request. fix(#1746 B2b review r17): the client's own timeout is per
    inactivity, so a service that answers slowly but never stops answering
    passes it forever, and this loop ran BEFORE the caller's own clock started
    in both callers. Ten thousand pages of a service trickling inside the read
    timeout is hours of an API request or an ingest worker. ``None`` means no
    caller deadline, which is the direct-call and offline case.

    ``on_first_request`` fires once, immediately before the first page is
    requested, for callers that date origin contacts.

    Raises :class:`ItemFetchFailedError` for a page that cannot be read, a page
    that exceeds the size bound, a ``next`` that leaves the submitted origin,
    the deadline, and a chain still offering a ``next`` at ``MAX_PAGES``; the
    file is removed before any of them escape, so a failure leaves nothing
    behind. Every bound here refuses rather than stopping short, because the
    caller cannot tell a prefix from a collection and the worker would import
    one over an existing dataset.
    """
    headers = credential_headers(credential_line)
    # fix(#1746 B2b review r28): the prefix and suffix come from the module
    # that sweeps them, so a file this writes is a file that sweep recognises.
    handle, path = tempfile.mkstemp(
        prefix=OAPIF_ITEMS_SCRATCH_PREFIX,
        suffix=OAPIF_ITEMS_SCRATCH_SUFFIX,
        dir=str(staging_dir),
    )
    os.close(handle)
    os.chmod(path, 0o600)

    try:
        # Refused before a client is opened when the deadline has already
        # passed: `asyncio.timeout` on a past deadline only fires at the first
        # suspension, which a fast enough first page never reaches. Shared with
        # the endpoint check, which has the same clock and the same trap.
        budget = deadline_budget(deadline, error=ItemFetchFailedError)
    except ItemFetchFailedError:
        _discard(path)
        raise
    try:
        # `asyncio.timeout` wraps the whole walk — DNS, connect, headers and
        # body of every page — rather than the gaps between reads, which is
        # the same outer-deadline shape `url_fetch` uses for the same reason.
        async with asyncio.timeout(budget):
            async with make_safe_client(
                timeout=PROBE_TIMEOUT, credential_header=next(iter(headers))
            ) as client:
                # Binary: the features are encoded once, and the count that
                # bounds the file is then the count that is written.
                with open(path, "wb") as out:
                    pages, written, number_matched, truncated = await _walk_pages(
                        client,
                        out,
                        url=url,
                        collection=collection,
                        headers=headers,
                        feature_limit=feature_limit,
                        on_first_request=on_first_request,
                    )
    except TimeoutError:
        _discard(path)
        raise ItemFetchFailedError("deadline exceeded") from None
    except BaseException:
        # Never leave a partial collection behind: it is data read with
        # somebody's credential, and nothing downstream would know it is short.
        _discard(path)
        raise

    logger.info(
        "materialised a protected OGC API collection locally",
        pages=pages,
        features=written,
    )
    if number_matched is None and truncated:
        # fix(#1746 B2b review r24): the walk stopped short and the service did
        # not say how many features there are, so the only honest answer is
        # that the total is unknown. `written` would be the sample size, which
        # a preview then showed as the collection's row count and re-upload
        # turned into a delta against the real dataset.
        #
        # fix(#1746 B2b review r28): `truncated` rather than
        # `written >= feature_limit`. The latter is also true of a collection
        # that holds exactly the sample size and ended, which is a complete
        # read: its total is known, and it is `written`.
        total: int | None = None
    else:
        total = number_matched if number_matched is not None else written
    return MaterialisedCollection(path=path, features=written, total=total)
