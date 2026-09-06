"""Read a protected OGC API collection here, so GDAL never holds the key.

An OAPIF items chain is chosen by the service one page at a time, and
``GDAL_HTTP_HEADER_FILE`` applies to every request the process makes, so a
collection whose first page is same-origin can hand the credential to any
origin it names on page two, with no redirect for a redirect hook to see. GDAL
offers no scope that would confine it: on 3.10.3 a ``[credentials]`` ``path=``
prefix applies to nothing at all for http(s) URLs, including the origin it
names, because ``CPLHTTPFetch`` consults path-specific options only for the
``/vsi*`` handlers.

So the pages are read here instead, with the bounded client that revalidates
SSRF and refuses to leave the origin, streamed to a local GeoJSON file that
GDAL is handed in place of the OAPIF source. It follows nothing, because there
is nothing left to follow.

WFS needs none of this: that driver pages by ``STARTINDEX``/``COUNT`` against
the GetFeature endpoint the capabilities advertise, which is the endpoint
``service_endpoints`` already validates.

What a collection may cost, since the whole chain is the service's to choose:
``MAX_PAGES`` requests, ``MAX_BYTES`` downloaded and the same again written to
the staging volume, ``MAX_PAGE_BYTES`` on the wire for any one page, and
``MAX_STRUCTURAL_TOKENS`` values or containers in any one page once decoded.
Reaching any of them is a refusal, never a short answer: a caller cannot tell a
prefix from a collection, and the worker would import one over an existing
dataset.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit

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
    HrefTooLongError,
    OGC_JSON_ACCEPT,
    bounded_parse_qsl,
    bounded_service_url,
    credential_headers,
    deadline_budget,
    fetch_document,
    fire_once,
)

logger = structlog.stdlib.get_logger(__name__)

# What one collection may cost. `MAX_BYTES` bounds the bytes DOWNLOADED and,
# separately, the bytes WRITTEN: a JSON round trip can GROW (`1e15` is four
# bytes on the wire and eighteen written), so neither figure bounds the other.
MAX_PAGES = 10_000
MAX_BYTES = 2 * 1024 * 1024 * 1024

# What one page may cost on the wire, streamed and enforced before anything is
# decoded. A page is held whole in memory to be parsed, so one oversized
# response exhausts the process before the total above notices.
MAX_PAGE_BYTES = 16 * 1024 * 1024

# What one page may cost DECODED, bounded before `json.loads` runs: compact JSON
# expands to ~96 bytes per structural token, so this is ~184 MiB. Counted on the
# RAW bytes, which only ever overcounts what the decoder builds.
MAX_STRUCTURAL_TOKENS = 2_000_000

# What a page fetch asks for. The service may answer with fewer.
PAGE_SIZE = 1000


class MaterialisedCollection(NamedTuple):
    """A local extract, and what is known about the collection behind it.

    ``features`` is the number of features written to the local extract. It may
    be less than ``total`` when the walk stopped at a sample limit; equality is
    not proof that no limit was applied.

    ``total`` is the collection's own size when it can be known: the service's
    ``numberMatched`` if it published one, otherwise the features written when
    the walk ran to the end. ``None`` when the walk stopped at a sample limit
    and the service said nothing.
    """

    path: str
    features: int
    total: int | None


class ItemFetchFailedError(EndpointCheckFailedError):
    """A page could not be read, or the chain tried to leave the origin.

    Subclasses the description check's refusal so every door that answers that
    one answers this the same way: the caller's request named a URL whose
    collection cannot be read safely, and the field to change is the same.
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

    Every place a fetched document is interpreted goes through here or through
    `_require_feature_page` below, so a service that answers 200 with something
    else is refused once rather than reinterpreted differently at each site.
    """
    if not isinstance(document, dict):
        raise ItemFetchFailedError(f"malformed {what}")
    return document


def _require_feature_page(document: object, *, first_page: bool) -> list:
    """The features of one items page, or a refusal.

    MALFORMED MEANS REFUSE, AND NEVER MEANS END-OF-COLLECTION. `_has_next` and
    `_next_href` both answer None for a shape they cannot read, and None is
    indistinguishable from a service saying there is no more, so every shape
    they would silently skip is refused before they are asked:

    * ``links`` present but not a list. Iterating an OBJECT yields its keys,
      which are strings, so no link dict is ever found and the chain looks
      finished.
    * an entry of ``links`` that is not an object, skipped by the same
      `isinstance` test, so a ``next`` expressed as a list or a bare string
      disappears.
    * a ``rel=next`` entry whose ``href`` is absent, not a string, or blank.
      A falsy href fails the truthiness test and the link vanishes; a
      non-string one would be coerced by `str()` into an address nobody named.
    * ``links`` missing entirely on a page that is NOT the first. Reaching that
      page means following a link, so a page that suddenly has none is a
      truncated response. Tolerated on the first page, where a single-page
      collection commonly omits them and nothing is decided from a link.
    * ``numberMatched`` present and not a non-negative integer. It is the
      number a preview reports as the collection's size.
    * ``numberReturned`` present and not equal to the length of ``features``.
      The page carries the means to check itself, and a page claiming a hundred
      while carrying ten is a truncated response everything else reads as well
      formed.
    * ``features`` not a list.

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
    _require_counts(page, features)
    return features


def _require_links(page: dict, *, first_page: bool) -> None:
    """Refuse a ``links`` member the pagination walk could misread."""
    links = page.get("links")
    if links is None:
        if "links" in page or not first_page:
            # An explicit null is malformed either way; an absent one is
            # tolerated on the first page only. Whether that absence proves the
            # collection complete is `_walk_pages`'s question, not this one.
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


def _optional_count(page: dict, member: str) -> int | None:
    """One of the OGC count members, or None when absent. Refuses a non-count.

    ``bool`` is excluded explicitly: it is a subclass of ``int``, so ``True``
    would otherwise pass as the count 1.
    """
    if member not in page:
        return None
    candidate = page[member]
    if not isinstance(candidate, int) or isinstance(candidate, bool) or candidate < 0:
        raise ItemFetchFailedError("malformed items page")
    return candidate


def _require_counts(page: dict, features: list) -> None:
    """Refuse the count members a page can contradict itself with.

    ``numberReturned`` is the count of features IN THIS RESPONSE, so a page
    saying it returned a hundred while carrying ten is a truncated response
    nothing else in the walk would notice.

    ``numberMatched`` is validated as a count here; the cross-page and
    whole-walk comparisons live in `_walk_pages`, which is the only place that
    can see more than one page.
    """
    _optional_count(page, "numberMatched")
    returned = _optional_count(page, "numberReturned")
    if returned is not None and returned != len(features):
        raise ItemFetchFailedError("page contradicts its own count")


# What a collection document advertises for the features themselves. Preferred
# over the conventional layout, which is a guess, and preferred by media type
# where the service offers more than one representation.
_ITEMS_REL = "items"
_ITEMS_MEDIA_TYPE = "application/geo+json"


def _advertised_items_href(document: dict, base: str) -> str | None:
    """The collection's own ``rel=items`` link, resolved, or None.

    What the document says wins, the same way `service_endpoints` treats an
    advertised link as authoritative; the conventional
    ``/collections/{id}/items`` layout is the fallback for a document that says
    nothing.
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
        # fix(#1770): length-gated before `urljoin`, and again inside `_with_page_size`,
        # both raising the SAME `ValueError` this except clause already exists to catch.
        return urljoin(base, bounded_service_url(str(chosen["href"]), what="items"))
    except HrefTooLongError:
        # fix(#1770): its own wording, matching
        # `service_endpoints.py::_assert_same_origin`.
        raise ItemFetchFailedError("items link exceeds the length limit") from None
    except ValueError:
        # Same rule as `next`: an address that will not parse cannot be shown
        # to stay on the origin, and the href is never echoed.
        raise ItemFetchFailedError("unparseable items link") from None


def _with_page_size(href: str) -> str:
    """The advertised link, asking for the page size this module wants.

    Every other parameter the service put on its own link is kept: a `f=json`
    or a fixed filter is part of where it said the items are.

    This is the module's one `parse_qsl` call site on a service-advertised
    query string, so it gates the href's length itself and bounds the field
    count directly. Raises `ValueError`, which `_resolve_items_url` catches.
    """
    href = bounded_service_url(href, what="items")
    parts = urlsplit(href)
    query = [
        (key, value) for key, value in bounded_parse_qsl(parts.query) if key != "limit"
    ]
    query.append(("limit", str(PAGE_SIZE)))
    return urlunsplit(parts._replace(query=urlencode(query)))


def _has_next(document: object) -> bool:
    """Whether the page offers another one, without resolving where.

    Asked when the walk is stopping at the sample limit and will not follow the
    link, so it must not resolve it, judge its origin, or refuse an unparseable
    one -- all three would turn "your preview is complete" into a failure.
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
                # fix(#1770): the same length gate `service_endpoints.py::_next_page`
                # applies, before `urljoin`.
                return urljoin(
                    base, bounded_service_url(str(link["href"]), what="next")
                )
            except HrefTooLongError:
                # fix(#1770): its own wording.
                raise ItemFetchFailedError(
                    "next link exceeds the length limit"
                ) from None
            except ValueError:
                # fix(#1746): an address that will not parse cannot be shown to stay on
                # the origin, so it is refused rather than read as the end of the chain.
                # Never echoed.
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

    The request itself is `fetch_document` in `service_endpoints`, shared with
    the description reads, so the protections the two paths need cannot
    diverge. This adds only what is specific to an items page: the caps it is
    read under, and the decode.
    """
    body, final_url = await fetch_document(
        client,
        url,
        headers,
        # fix(#1746): the same Accept the probe and the endpoint check send, so a
        # service serving HTML for `*/*` cannot answer one of the three reads
        # differently from the other two.
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
    except (ValueError, RecursionError) as exc:
        # fix(#1770): a JSON depth bomb is under both the byte cap and
        # MAX_STRUCTURAL_TOKENS (which counts brackets, not depth) and raises
        # RecursionError rather than ValueError.
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
    layout.
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
    try:
        # fix(#1770): `_with_page_size` re-parses `href`'s query to replace `limit`, and
        # bounds both its length and its field count; only a query packed with many
        # short pairs reaches this except in practice.
        return _with_page_size(href), size
    except HrefTooLongError:
        # fix(#1770): its own wording, kept for the same reason that check is defence in
        # depth rather than trusted alone.
        raise ItemFetchFailedError("items link exceeds the length limit") from None
    except ValueError:
        raise ItemFetchFailedError("unparseable items link") from None


def _sample_truncated(
    document: dict,
    *,
    landed_mid_page: bool,
    observed: int,
    number_matched: int | None,
) -> bool | None:
    """Whether a SAMPLED read that just broke out of its loop stopped short.

    `landed_mid_page` needs no further proof: more sits right there, on the
    page just read. Landing exactly on the page's last feature delegates to
    `_page_proves_complete`, asked with `_has_next` (never raises on an
    unparseable link) rather than `_next_href`, since this link is never going
    to be followed either way. `None` when the page proves neither.
    """
    if landed_mid_page:
        return True
    complete = _page_proves_complete(
        document,
        has_next=_has_next(document),
        observed=observed,
        number_matched=number_matched,
    )
    return False if complete else None


def _page_proves_complete(
    document: dict,
    *,
    has_next: bool,
    observed: int,
    number_matched: int | None,
) -> bool:
    """Whether THIS page, with no next page left to follow, proves the walk
    has reached the true end of the collection.

    One predicate, used at both places a walk reaches this question: a FULL
    walk's natural end, and a SAMPLED preview landing exactly on a page's last
    feature.

    `has_next` True means there is more to follow, definitively -- neither
    proof below can override a service that names a next page. `links`
    PRESENT (even `[]`, even one carrying only `self`/`alternate`) with no
    `next` in it is the service's own, unambiguous terminal-page signal, so
    that proves completeness on its own. `links` ABSENT ENTIRELY means
    nothing was said about pagination at all, so the only proof left is
    `numberMatched` equal to what the walk has actually read (`observed`).

    Callers pass `has_next` rather than resolving it here: a full walk has it
    from `_next_href`, which can raise on an unparseable link it is about to
    follow, while a sampled preview uses `_has_next`, which never raises --
    refusing a preview over a link it was never going to use would turn "your
    preview is complete" into a failure.
    """
    if has_next:
        return False
    if "links" in document:
        return True
    return number_matched is not None and number_matched == observed


def _end_of_chain(
    document: dict,
    *,
    from_url: str,
    url: str,
    feature_limit: int | None,
    pages: int,
    observed: int,
    number_matched: int | None,
    truncated: bool | None,
) -> tuple[str | None, bool | None]:
    """The page this walk's `for ... else` reaches without breaking early:
    either another page to fetch, or the genuine end of the chain.

    Returns `(page_url, truncated)`. `truncated` passes straight through
    EXCEPT for a SAMPLED walk (`feature_limit is not None`) whose chain has
    just genuinely ended (`following is None`, so the loop above exhausted the
    page instead of breaking on the sample limit). There it becomes this page's
    own completeness verdict -- `False` where `_page_proves_complete` proves
    it, `None` where it does not. The LAST page decides, not a value an
    intermediate one left behind.

    Raises `ItemFetchFailedError` for a `next` that leaves the origin, or
    (full walks only, first page only) one that cannot prove it is the last.
    """
    following = _next_href(document, from_url)
    if following is not None and not same_origin(url, following):
        # The page chose the next address; it does not get to choose a
        # different service to be paid with this credential.
        raise ItemFetchFailedError("next page leaves the origin")
    if following is None and feature_limit is None and pages == 1:
        # fix(#1770): a FULL walk ending on the FIRST page with no `next` must be able
        # to PROVE it -- see `_page_proves_complete`. `has_next=False`: this branch
        # needs `following is None`.
        provably_complete = _page_proves_complete(
            document, has_next=False, observed=observed, number_matched=number_matched
        )
        if not provably_complete:
            raise ItemFetchFailedError("collection may not be complete")
        return following, truncated
    if following is None and feature_limit is not None:
        # fix(#1770): the SAMPLED-walk mirror of the branch above. Never refuses -- a
        # preview stays usable -- but the total it reports is honest only where
        # `_page_proves_complete` proves it.
        return following, _sample_truncated(
            document,
            landed_mid_page=False,
            observed=observed,
            number_matched=number_matched,
        )
    return following, truncated


async def _walk_pages(
    client: httpx.AsyncClient,
    out,
    *,
    url: str,
    collection: str,
    headers: dict,
    feature_limit: int | None,
    on_first_request: Callable[[], None] | None,
) -> tuple[int, int, int | None, bool | None]:
    """Follow the chain, writing features.

    Returns pages read, features written, what the service said the whole
    collection holds, and whether the walk stopped SHORT -- `True`, `False`, or
    `None` where the last page proved neither, in which case the total is
    unknown rather than short.

    The count-shaped invariants, complete
    -------------------------------------

    The OGC items schema has exactly two integer members, ``numberMatched`` and
    ``numberReturned``, so this list is closed rather than the current state of
    a search:

    1. ``numberReturned == len(features)``, per page. The page's claim about
       itself, checked in `_require_counts`.
    2. ``numberMatched`` identical on every page that states it. It describes
       the whole query, so two answers describe two queries and neither can be
       checked against anything.
    3. ``observed <= numberMatched``, on EVERY walk. Stopping early can
       produce fewer rows than the total; nothing can produce more.
    4. ``observed == numberMatched``, on FULL walks only. A sampled read is
       short by construction, so falling below says nothing there.
    5. A FULL walk ending on the FIRST page with no `next` must be able to
       PROVE it -- see `_page_proves_complete` for the two shapes that do.
       Page length proves nothing on either side of that check: the server's
       own page size is its choice, not a floor this module gets to assume.

    ``observed`` is the sum of ``len(features)`` across every page this walk
    read, counted before a sample limit truncates what gets written, so it is
    the size the service actually sent rather than the size a sample kept.
    ``written <= observed`` always.

    Each is a refusal, never a quiet correction: the walk cannot tell a service
    that has finished from one that has been cut off, so anything it cannot
    verify it declines.
    """
    written = 0
    # fix(#1746): every page counted whole, before `feature_limit` truncates what gets
    # written -- `written` under-reports a page's real size once a sample cuts it short.
    observed = 0
    pages = 0
    on_disk = 0
    number_matched: int | None = None
    # fix(#1770): whether the walk STOPPED SHORT, tri-state. Only the site that breaks
    # out of the loop knows, a FULL walk never touches it, and `None` means the page
    # proved neither, so the total is unknown.
    truncated: bool | None = False
    # fix(#1746): the origin is contacted HERE, not by the subprocess, so this is the
    # moment a caller that dates origin contacts hears about. `fire_once` means no loop
    # tracks which pass it is on.
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
        # One rule, one site, so a malformed page cannot mean different
        # things depending on where in the chain it arrived.
        features = _require_feature_page(document, first_page=pages == 1)
        # The page's own claim about its size, before the sample loop below
        # may stop partway through it.
        observed += len(features)
        if "numberMatched" in document:
            # fix(#1746): the whole query's match count, read from EVERY page. Two pages
            # giving different answers describe two different queries and neither can be
            # checked against the walk.
            reported = document["numberMatched"]
            if number_matched is None:
                number_matched = reported
            elif reported != number_matched:
                raise ItemFetchFailedError("pages disagree about the size")
        for index, feature in enumerate(features):
            # fix(#1746): `ensure_ascii=False` and a binary file, so non-Latin text is
            # not tripled on disk; what is written is then counted rather than inferred
            # from the download.
            try:
                # fix(#1770): a JSON escape for an unpaired surrogate is legal and has
                # no UTF-8 encoding, so this refuses rather than writing bytes GDAL
                # cannot read back.
                encoded = json.dumps(
                    feature, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ItemFetchFailedError(f"unencodable feature: {exc}") from None
            chunk = b"," + encoded if written else encoded
            # fix(#1746): compared BEFORE the write. Checking after admits one expanded
            # feature past the cap, which on this path is the value that expands
            # unboundedly.
            if on_disk + len(chunk) > MAX_BYTES:
                raise ItemFetchFailedError("collection exceeds the cap on disk")
            out.write(chunk)
            on_disk += len(chunk)
            written += 1
            if feature_limit is not None and written >= feature_limit:
                # fix(#1770): landing exactly on the page's last feature asks the same
                # completeness predicate a full walk's natural end does.
                truncated = _sample_truncated(
                    document,
                    landed_mid_page=index + 1 < len(features),
                    observed=observed,
                    number_matched=number_matched,
                )
                page_url = None
                break
        else:
            page_url, truncated = _end_of_chain(
                document,
                from_url=from_url,
                url=url,
                feature_limit=feature_limit,
                pages=pages,
                observed=observed,
                number_matched=number_matched,
                truncated=truncated,
            )
    if page_url is not None:
        # fix(#1746): the page cap is reached with more to come. Closing the array here
        # returns a prefix that reads as a complete collection, and the worker imports
        # it over a dataset.
        raise ItemFetchFailedError("collection exceeds the page cap")
    if number_matched is not None:
        # fix(#1746): SAMPLING CAN PRODUCE FEWER ROWS THAN THE TOTAL, NEVER MORE, so
        # this half holds on every walk. `observed`, not `written`: a sample masks the
        # page's real size from this check.
        if observed > number_matched:
            raise ItemFetchFailedError("more features than the service reported")
        # fix(#1746): the chain ends short of the count the service gives for itself.
        # Equality is a FULL-walk claim only -- a sampled read is short by design, and
        # `truncated` carries that.
        if feature_limit is None and observed != number_matched:
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
    request, because the client's own timeout is per inactivity and a service
    that answers slowly but never stops answering passes that forever. ``None``
    means no caller deadline, which is the direct-call and offline case.

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
    # fix(#1746): prefix and suffix come from the module that sweeps them, so a file
    # this writes is one that sweep recognises.
    handle, path = tempfile.mkstemp(
        prefix=OAPIF_ITEMS_SCRATCH_PREFIX,
        suffix=OAPIF_ITEMS_SCRATCH_SUFFIX,
        dir=str(staging_dir),
    )
    os.close(handle)
    os.chmod(path, 0o600)

    try:
        # Refused before a client is opened: `asyncio.timeout` on a past
        # deadline only fires at the first suspension, which a fast enough
        # first page never reaches. Shared with the endpoint check.
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
                # Binary: the features are encoded once, so the count that
                # bounds the file is the count that is written.
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
    if number_matched is None and truncated is not False:
        # fix(#1770): `is not False`. The walk stopped short (`True`) or the page proved
        # neither (`None`), and neither can name the total, so it stays unknown rather
        # than reporting the sample size.
        total: int | None = None
    else:
        total = number_matched if number_matched is not None else written
    return MaterialisedCollection(path=path, features=written, total=total)
