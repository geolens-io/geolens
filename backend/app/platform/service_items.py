"""Read a protected OGC API collection here, so GDAL never holds the key.

An OAPIF items chain is chosen by the service one page at a time, and
``GDAL_HTTP_HEADER_FILE`` applies to every request the process makes, so a
collection whose first page is same-origin can hand the credential to any
origin named on page two, with no redirect for a redirect hook to see. GDAL
offers no scope to confine it: on 3.10.3 a ``[credentials]`` ``path=``
prefix applies to nothing for http(s) URLs, because ``CPLHTTPFetch``
consults path-specific options only for the ``/vsi*`` handlers.

So the pages are read here instead, with the bounded client that
revalidates SSRF and refuses to leave the origin, streamed to a local
GeoJSON file GDAL is handed in place of the OAPIF source — it follows
nothing, because there's nothing left to follow.

WFS needs none of this: that driver pages by ``STARTINDEX``/``COUNT``
against the GetFeature endpoint ``service_endpoints`` already validates.

What a collection may cost, since the whole chain is the service's to
choose: ``MAX_PAGES`` requests, ``MAX_BYTES`` downloaded and the same
again written to staging, ``MAX_PAGE_BYTES`` on the wire per page, and
``MAX_STRUCTURAL_TOKENS`` values/containers per page once decoded.
Reaching any of them is a refusal, never a short answer — a caller can't
tell a prefix from a collection, and the worker would import one over an
existing dataset.
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

# What one collection may cost. `MAX_BYTES` bounds bytes DOWNLOADED and,
# separately, bytes WRITTEN: a JSON round trip can GROW (`1e15` is four
# bytes on the wire, eighteen written), so neither figure bounds the other.
MAX_PAGES = 10_000
MAX_BYTES = 2 * 1024 * 1024 * 1024

# What one page may cost on the wire, streamed and enforced before decoding.
# A page is held whole in memory to parse, so one oversized response
# exhausts the process before the total above notices.
MAX_PAGE_BYTES = 16 * 1024 * 1024

# What one page may cost DECODED, bounded before `json.loads` runs: compact
# JSON expands to ~96 bytes per structural token, so ~184 MiB. Counted on
# raw bytes, which only ever overcounts what the decoder builds.
MAX_STRUCTURAL_TOKENS = 2_000_000

# What a page fetch asks for. The service may answer with fewer.
PAGE_SIZE = 1000


class MaterialisedCollection(NamedTuple):
    """A local extract, and what is known about the collection behind it.

    ``features`` is the number written to the local extract. May be less
    than ``total`` when the walk stopped at a sample limit; equality is
    not proof no limit was applied.

    ``total`` is the collection's own size when knowable: the service's
    ``numberMatched`` if published, else the features written when the
    walk ran to the end. ``None`` when the walk stopped at a sample limit
    and the service said nothing.
    """

    path: str
    features: int
    total: int | None


class ItemFetchFailedError(EndpointCheckFailedError):
    """A page could not be read, or the chain tried to leave the origin.

    Subclasses the description check's refusal so every door answering that
    one answers this the same way: the URL's collection can't be read
    safely, and the field to change is the same.
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

    Every place a fetched document is interpreted goes through here or
    `_require_feature_page` below, so a 200 answering with something else
    is refused once rather than reinterpreted differently at each site.
    """
    if not isinstance(document, dict):
        raise ItemFetchFailedError(f"malformed {what}")
    return document


def _require_feature_page(document: object, *, first_page: bool) -> list:
    """The features of one items page, or a refusal.

    MALFORMED MEANS REFUSE, NEVER END-OF-COLLECTION. `_has_next`/`_next_href`
    both answer None for a shape they can't read, indistinguishable from
    "no more" — so every shape they'd silently skip is refused first:

    * ``links`` present but not a list — iterating an OBJECT yields its
      string keys, so no link dict is ever found and the chain looks finished.
    * a ``links`` entry that isn't an object — same `isinstance` skip, so a
      ``next`` expressed as a list or bare string disappears.
    * a ``rel=next`` entry whose ``href`` is absent, non-string, or blank —
      a falsy href fails truthiness; a non-string one would be coerced by
      `str()` into an address nobody named.
    * ``links`` missing entirely on a page that is NOT the first — reaching
      it means following a link, so no links is a truncated response.
      Tolerated on the first page, where a single-page collection commonly
      omits them.
    * ``numberMatched`` present and not a non-negative integer — the number
      a preview reports as the collection's size.
    * ``numberReturned`` present and not equal to ``len(features)`` — the
      page can check itself, and claiming a hundred while carrying ten is
      truncated even though everything else reads well formed.
    * ``features`` not a list.

    A legitimately empty page is `{"type": "FeatureCollection", "features":
    []}` and still reads as empty, which is what makes the refusal specific.
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
            # An explicit null is malformed either way; absence is
            # tolerated only on the first page. Whether that absence proves
            # the collection complete is `_walk_pages`'s question, not this.
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

    ``bool`` is excluded explicitly: it's a subclass of ``int``, so ``True``
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
    claiming a hundred while carrying ten is a truncated response nothing
    else in the walk would notice.

    ``numberMatched`` is validated as a count here; cross-page and
    whole-walk comparisons live in `_walk_pages`, the only place that can
    see more than one page.
    """
    _optional_count(page, "numberMatched")
    returned = _optional_count(page, "numberReturned")
    if returned is not None and returned != len(features):
        raise ItemFetchFailedError("page contradicts its own count")


# What a collection document advertises for the features themselves.
# Preferred over the conventional layout, which is a guess, and preferred
# by media type where the service offers more than one representation.
_ITEMS_REL = "items"
_ITEMS_MEDIA_TYPE = "application/geo+json"


def _advertised_items_href(document: dict, base: str) -> str | None:
    """The collection's own ``rel=items`` link, resolved, or None.

    What the document says wins, the same way `service_endpoints` treats
    an advertised link as authoritative; the conventional
    ``/collections/{id}/items`` layout is the fallback if it says nothing.
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
        # fix(#1770): length-gated before `urljoin`, and again inside
        # `_with_page_size` — both raise the SAME ValueError caught below.
        return urljoin(base, bounded_service_url(str(chosen["href"]), what="items"))
    except HrefTooLongError:
        # fix(#1770): own wording, matching service_endpoints.py's
        # _assert_same_origin.
        raise ItemFetchFailedError("items link exceeds the length limit") from None
    except ValueError:
        # Same rule as `next`: an unparseable address can't be shown to
        # stay on the origin, and the href is never echoed.
        raise ItemFetchFailedError("unparseable items link") from None


def _with_page_size(href: str) -> str:
    """The advertised link, asking for the page size this module wants.

    Every other parameter the service put on its own link is kept: an
    `f=json` or fixed filter is part of where it said the items are.

    The module's one `parse_qsl` call site on a service-advertised query
    string, so it gates the href's length and bounds the field count
    directly. Raises `ValueError`, caught by `_resolve_items_url`.
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

    Asked when the walk is stopping at the sample limit and won't follow
    the link, so it must not resolve it, judge its origin, or refuse an
    unparseable one — all three would turn "preview complete" into a failure.
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
                # fix(#1770): same length gate service_endpoints.py's
                # _next_page applies, before `urljoin`.
                return urljoin(
                    base, bounded_service_url(str(link["href"]), what="next")
                )
            except HrefTooLongError:
                raise ItemFetchFailedError(
                    "next link exceeds the length limit"
                ) from None
            except ValueError:
                # fix(#1746): an unparseable address can't be shown to stay
                # on the origin, so it's refused rather than read as the
                # end of the chain. Never echoed.
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

    The request itself is `fetch_document` in `service_endpoints`, shared
    with the description reads, so the protections the two paths need
    can't diverge. This adds only what's specific to an items page: the
    caps it's read under, and the decode.
    """
    body, final_url = await fetch_document(
        client,
        url,
        headers,
        # fix(#1746): the same Accept the probe and endpoint check send, so
        # HTML-for-`*/*` can't answer one of the three reads differently.
        accept=OGC_JSON_ACCEPT,
        budget=budget,
        # Read at call time, like `fetch_document` does: a default argument
        # would freeze the constant at definition.
        token_budget=MAX_STRUCTURAL_TOKENS if token_budget is None else token_budget,
        error=ItemFetchFailedError,
        on_first_request=on_first_request,
    )
    try:
        return json.loads(body), len(body), final_url
    except (ValueError, RecursionError) as exc:
        # fix(#1770): a JSON depth bomb is under both the byte cap and
        # MAX_STRUCTURAL_TOKENS (which counts brackets, not depth) and
        # raises RecursionError rather than ValueError.
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

    The collection document is read first and its ``rel=items`` link is
    what the walk follows, judged by the same rules as a ``next``:
    resolved against the URL the document came from, refused if it leaves
    the submitted origin, and revalidated for SSRF by `_fetch_page` before
    it's requested.

    A document that advertises no items link falls back to the
    conventional layout.
    """
    document, size, from_url = await _fetch_page(
        client,
        f"{url.rstrip('/')}/collections/{quote(collection, safe='')}",
        headers,
        budget=MAX_DOCUMENT_BYTES,
        # A collection document is a description, so it gets the
        # description budget rather than an items page's.
        token_budget=MAX_DOCUMENT_TOKENS,
        on_first_request=on_first_request,
    )
    href = _advertised_items_href(
        _require_object(document, "collection document"), from_url
    )
    if href is None:
        return _items_url(url, collection), size
    if not same_origin(url, href):
        # Same rule as the page chain, for the same reason: the document
        # chose this address and doesn't get to choose a different service
        # to be paid with this credential.
        raise ItemFetchFailedError("items link leaves the origin")
    try:
        # fix(#1770): `_with_page_size` re-parses href's query to replace
        # `limit`, bounding both its length and field count.
        return _with_page_size(href), size
    except HrefTooLongError:
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

    `landed_mid_page` needs no further proof: more sits right there, on
    the page just read. Landing exactly on the last feature delegates to
    `_page_proves_complete`, asked with `_has_next` (never raises on an
    unparseable link) rather than `_next_href`, since this link is never
    going to be followed either way. `None` when the page proves neither.
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

    One predicate, used at both places a walk reaches this question: a
    FULL walk's natural end, and a SAMPLED preview landing exactly on a
    page's last feature.

    `has_next` True means definitively more to follow — neither proof
    below can override a service naming a next page. `links` PRESENT (even
    `[]`, even one carrying only `self`/`alternate`) with no `next` is the
    service's own unambiguous terminal-page signal, proving completeness
    on its own. `links` ABSENT ENTIRELY means nothing was said about
    pagination, so the only proof left is `numberMatched` equal to what
    the walk has actually read (`observed`).

    Callers pass `has_next` rather than resolving it here: a full walk has
    it from `_next_href`, which can raise on an unparseable link it's
    about to follow, while a sampled preview uses `_has_next`, which never
    raises — refusing a preview over a link it was never going to use
    would turn "preview complete" into a failure.
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
    EXCEPT for a SAMPLED walk (`feature_limit is not None`) whose chain
    has just genuinely ended (`following is None`, so the loop above
    exhausted the page instead of breaking on the sample limit). There it
    becomes this page's own completeness verdict — `False` where
    `_page_proves_complete` proves it, `None` where it doesn't. The LAST
    page decides, not a value an intermediate one left behind.

    Raises `ItemFetchFailedError` for a `next` that leaves the origin, or
    (full walks only, first page only) one that can't prove it's the last.
    """
    following = _next_href(document, from_url)
    if following is not None and not same_origin(url, following):
        # The page chose the next address; it doesn't get to choose a
        # different service to be paid with this credential.
        raise ItemFetchFailedError("next page leaves the origin")
    if following is None and feature_limit is None and pages == 1:
        # fix(#1770): a FULL walk ending on the FIRST page with no `next`
        # must PROVE it — see `_page_proves_complete`. `has_next=False`:
        # this branch needs `following is None`.
        provably_complete = _page_proves_complete(
            document, has_next=False, observed=observed, number_matched=number_matched
        )
        if not provably_complete:
            raise ItemFetchFailedError("collection may not be complete")
        return following, truncated
    if following is None and feature_limit is not None:
        # fix(#1770): SAMPLED-walk mirror of the branch above. Never
        # refuses (a preview stays usable), but the total it reports is
        # honest only where `_page_proves_complete` proves it.
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
    collection holds, and whether the walk stopped SHORT — `True`,
    `False`, or `None` where the last page proved neither, in which case
    the total is unknown rather than short.

    The count-shaped invariants, complete: the OGC items schema has
    exactly two integer members, ``numberMatched`` and ``numberReturned``,
    so this list is closed rather than the current state of a search.

    1. ``numberReturned == len(features)``, per page (`_require_counts`).
    2. ``numberMatched`` identical on every page that states it — it
       describes the whole query, so two answers describe two queries.
    3. ``observed <= numberMatched``, on EVERY walk — stopping early can
       produce fewer rows than the total; nothing can produce more.
    4. ``observed == numberMatched``, on FULL walks only — a sampled read
       is short by construction, so falling below says nothing there.
    5. A FULL walk ending on the FIRST page with no `next` must PROVE it
       (`_page_proves_complete`). Page length proves nothing either way:
       the server's own page size is its choice, not a floor to assume.

    ``observed`` is the sum of ``len(features)`` across every page read,
    counted before a sample limit truncates what gets written — the size
    the service actually sent, not the size a sample kept.
    ``written <= observed`` always.

    Each is a refusal, never a quiet correction: the walk can't tell a
    finished service from a cut-off one, so anything unverifiable it declines.
    """
    written = 0
    # fix(#1746): every page counted whole, before `feature_limit`
    # truncates what gets written — `written` under-reports a page's real
    # size once a sample cuts it short.
    observed = 0
    pages = 0
    on_disk = 0
    number_matched: int | None = None
    # fix(#1770): whether the walk STOPPED SHORT, tri-state. Only the
    # breaking site knows; a FULL walk never touches it; `None` means the
    # page proved neither, so the total is unknown.
    truncated: bool | None = False
    # fix(#1746): origin contacted HERE, not by the subprocess — the
    # moment a caller dating origin contacts hears about. `fire_once`
    # means no loop tracks which pass it's on.
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
            # fix(#1746): the whole query's match count, read from EVERY
            # page — two pages giving different answers describe two
            # different queries.
            reported = document["numberMatched"]
            if number_matched is None:
                number_matched = reported
            elif reported != number_matched:
                raise ItemFetchFailedError("pages disagree about the size")
        for index, feature in enumerate(features):
            # fix(#1746): ensure_ascii=False on a binary file, so non-Latin
            # text isn't tripled on disk; what's written is then counted
            # rather than inferred from the download.
            try:
                # fix(#1770): a JSON escape for an unpaired surrogate is
                # legal but has no UTF-8 encoding — refuse rather than
                # write bytes GDAL can't read back.
                encoded = json.dumps(
                    feature, separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ItemFetchFailedError(f"unencodable feature: {exc}") from None
            chunk = b"," + encoded if written else encoded
            # fix(#1746): compared BEFORE the write — checking after
            # admits one expanded feature past the cap.
            if on_disk + len(chunk) > MAX_BYTES:
                raise ItemFetchFailedError("collection exceeds the cap on disk")
            out.write(chunk)
            on_disk += len(chunk)
            written += 1
            if feature_limit is not None and written >= feature_limit:
                # fix(#1770): landing exactly on the last feature asks the
                # same completeness predicate a full walk's natural end does.
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
        # fix(#1746): page cap reached with more to come — closing the
        # array here would read as a complete collection, and the worker
        # imports it over a dataset.
        raise ItemFetchFailedError("collection exceeds the page cap")
    if number_matched is not None:
        # fix(#1746): SAMPLING CAN PRODUCE FEWER ROWS THAN THE TOTAL, NEVER
        # MORE, so this half holds on every walk. `observed`, not
        # `written`: a sample masks the page's real size from this check.
        if observed > number_matched:
            raise ItemFetchFailedError("more features than the service reported")
        # fix(#1746): equality is a FULL-walk claim only — a sampled read
        # is short by design, and `truncated` carries that.
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

    The caller hands the returned path to GDAL INSTEAD of the OAPIF
    source, and writes no header file at all — that's what removes the
    credential from everything GDAL does.

    ``feature_limit`` stops early for a preview, which needs a handful of
    rows rather than the collection.

    ``deadline`` is a :func:`time.monotonic` stamp by which the whole
    materialisation must be done, wrapping every page rather than every
    request, since the client's own timeout is per-inactivity and a
    service that answers slowly but never stops would pass it forever.
    ``None`` means no caller deadline (the direct-call/offline case).

    ``on_first_request`` fires once, immediately before the first page is
    requested, for callers that date origin contacts.

    Raises :class:`ItemFetchFailedError` for a page that can't be read, a
    page over the size bound, a ``next`` leaving the submitted origin, the
    deadline, and a chain still offering a ``next`` at ``MAX_PAGES``; the
    file is removed before any of them escape. Every bound refuses rather
    than stopping short, since the caller can't tell a prefix from a
    collection and the worker would import one over an existing dataset.
    """
    headers = credential_headers(credential_line)
    # fix(#1746): prefix/suffix come from the module that sweeps them, so
    # a file this writes is one that sweep recognises.
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
        # Never leave a partial collection behind: it's data read with
        # somebody's credential, and nothing downstream would know it's short.
        _discard(path)
        raise

    logger.info(
        "materialised a protected OGC API collection locally",
        pages=pages,
        features=written,
    )
    if number_matched is None and truncated is not False:
        # fix(#1770): `is not False` — walk stopped short (`True`) or the
        # page proved neither (`None`); neither can name the total, so it
        # stays unknown rather than reporting the sample size.
        total: int | None = None
    else:
        total = number_matched if number_matched is not None else written
    return MaterialisedCollection(path=path, features=written, total=total)
