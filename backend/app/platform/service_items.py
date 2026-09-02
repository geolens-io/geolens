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
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
import structlog

from app.core.service_tokens import HEADER_LINE_SEPARATOR
from app.platform.security import (
    PROBE_TIMEOUT,
    SSRFError,
    make_safe_client,
    same_origin,
    validate_url_for_ssrf,
)
from app.platform.service_endpoints import (
    MAX_DOCUMENT_BYTES,
    EndpointCheckFailedError,
    read_bounded_body,
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

# What one page may cost, enforced by the shared reader in `service_endpoints`
# while it streams and before anything is decoded. A page is held whole in memory to be parsed, so this is the real
# per-request memory bound and the total above cannot substitute for it: one
# oversized response would exhaust the process long before a running total
# noticed. 64 MiB against `PAGE_SIZE` features is ~64 KiB of JSON per feature,
# far past any honest geometry, and a service wanting more can paginate.
MAX_PAGE_BYTES = 64 * 1024 * 1024

# What a page fetch asks for. The service may answer with fewer.
PAGE_SIZE = 1000


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


def _credential_headers(credential_line: str) -> dict[str, str]:
    name, _, value = credential_line.partition(HEADER_LINE_SEPARATOR)
    return {
        name: value,
        "Accept": "application/geo+json, application/json",
        # fix(#1746 B2b review r17): identity asked for, and enforced below.
        # The bytes counted against the page bound have to be the bytes read.
        "Accept-Encoding": "identity",
    }


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


def _require_feature_page(document: object) -> list:
    """The features of one items page, or a refusal.

    fix(#1746 B2b review r21): `features or []` read an HTTP 200 JSON error
    envelope as an empty page, and read `"features": null` and
    `"features": {}` the same way. A preview then succeeded with zero rows and
    a refresh or re-upload handed an empty FeatureCollection to ogr2ogr, which
    replaced existing data with nothing: the silent-truncation class of r18,
    one level up. A page that does not say what it is does not get to say it
    is empty.

    A legitimately empty page is `{"type": "FeatureCollection", "features": []}`
    and still reads as empty, which is what makes the refusal specific.
    """
    page = _require_object(document, "items page")
    if page.get("type") != "FeatureCollection":
        raise ItemFetchFailedError("malformed items page")
    features = page.get("features")
    if not isinstance(features, list):
        raise ItemFetchFailedError("malformed items page")
    return features


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
    client: httpx.AsyncClient, url: str, headers: dict, *, budget: int
) -> tuple[object, int, str]:
    """One items page, its wire size and its URL, or a refusal.

    THE request site for this module.

    Every page is revalidated immediately before the request, including pages
    the previous one named: a chain the service controls is exactly where a
    host that resolved publicly a moment ago can start resolving to a private
    address (AGENTS.md Rule 2).

    Streamed rather than buffered, and refused at ``budget`` bytes before
    anything is decoded. The decoded object is the memory high-water mark of
    this whole module, so the bound has to be on the input.
    """
    try:
        await validate_url_for_ssrf(url)
        # The client is `make_safe_client`, whose transport re-resolves,
        # validates and pins the IP at connect time and revalidates every
        # redirect hop, and the caller has already refused any `next` that
        # leaves the origin. CodeQL models none of that.
        #
        # The marker below must stay the LAST line before the call: the
        # suppression query binds a marker to the line that follows it, so an
        # explanatory comment inserted between the two silently disarms it.
        # codeql[py/full-ssrf] fix(#1746): Rule 2 posture — validate_url_for_ssrf gates this exact URL immediately above, same_origin has already bounded it to the submitted origin, and make_safe_client's transport re-resolves, validates and pins the IP at connect time
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code >= 400:
                # Read nothing: the body of an error from a service this module
                # distrusts is not worth the bytes, and the status is the whole
                # of what the refusal says.
                raise ItemFetchFailedError(f"HTTP {response.status_code}")
            body = await read_bounded_body(response, budget, error=ItemFetchFailedError)
            # fix(#1746 B2b review r19): the URL this page actually came from.
            # A same-origin canonical redirect (`/items` to `/items/`) changes
            # what a relative `next` is relative to, so resolving against the
            # URL that was asked for requests the wrong path. The safe client
            # revalidated every hop and refuses a cross-origin one carrying
            # this header, so the final URL is bounded before it is used.
            final_url = str(response.url)
        return json.loads(body), len(body), final_url
    except (httpx.HTTPError, SSRFError, ValueError) as exc:
        raise ItemFetchFailedError(str(exc)) from None


async def _resolve_items_url(
    client: httpx.AsyncClient,
    *,
    url: str,
    collection: str,
    headers: dict,
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
) -> tuple[int, int]:
    """Follow the chain, writing features. Returns pages read and features written."""
    written = 0
    pages = 0
    on_disk = 0
    if on_first_request is not None:
        # fix(#1746 B2b review r17, moved r20): the origin is contacted HERE,
        # not by the subprocess, so this is the moment a caller that dates
        # origin contacts has to hear about. It fires before the collection
        # document is read rather than before the first page, because that
        # read is now the first request and a failure in it has still reached
        # the service; leaving `last_checked_at` stale would report otherwise.
        on_first_request()
    first_page, downloaded = await _resolve_items_url(
        client, url=url, collection=collection, headers=headers
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
        )
        downloaded += size
        # Both the first page and every page a `next` named. One rule, one
        # site, so a malformed page cannot mean different things depending on
        # where in the chain it arrived.
        features = _require_feature_page(document)
        for feature in features:
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
    out.write(b"]}")
    return pages, written


async def materialise_oapif_items(
    url: str,
    collection: str,
    *,
    credential_line: str,
    staging_dir: str | Path,
    feature_limit: int | None = None,
    deadline: float | None = None,
    on_first_request: Callable[[], None] | None = None,
) -> str:
    """Write a protected collection to a local GeoJSON file and return its path.

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
    headers = _credential_headers(credential_line)
    handle, path = tempfile.mkstemp(
        prefix="oapif_items_", suffix=".geojson", dir=str(staging_dir)
    )
    os.close(handle)
    os.chmod(path, 0o600)

    budget = None if deadline is None else deadline - time.monotonic()
    if budget is not None and budget <= 0:
        # Refused before a client is opened. `asyncio.timeout` with an expired
        # deadline only fires at the first suspension, which a fast enough
        # first page never reaches, so the guard is explicit rather than
        # inferred from the timer's semantics.
        _discard(path)
        raise ItemFetchFailedError("deadline exceeded")
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
                    pages, written = await _walk_pages(
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
    return path
