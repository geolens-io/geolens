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
from urllib.parse import quote, urljoin

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
from app.platform.service_endpoints import EndpointCheckFailedError

logger = structlog.stdlib.get_logger(__name__)

# What one collection may cost. A page chain is chosen by the service, so it is
# bounded here rather than trusted: an endpoint that keeps answering `next`
# forever would otherwise be an unbounded fetch holding a credential.
#
# fix(#1746 B2b review r17): `MAX_BYTES` counts the bytes READ, not the bytes
# written. Counting the output measured the wrong thing, because a page is
# decoded before any feature of it is written and the decode is where the
# memory goes.
# Reaching either is a refusal, never a short answer: see `_walk_pages`.
MAX_PAGES = 10_000
MAX_BYTES = 2 * 1024 * 1024 * 1024

# What one page may cost, enforced while it streams and before anything is
# decoded. A page is held whole in memory to be parsed, so this is the real
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


async def _read_bounded(response: httpx.Response, budget: int) -> bytes:
    """The body, or a refusal once more than ``budget`` bytes have arrived.

    fix(#1746 B2b review r17): the read stops at the bound rather than at the
    end of the response, so the refusal costs one chunk past the budget instead
    of however much the service felt like sending.

    ``aiter_raw`` rather than ``aiter_bytes``, for the reason #1708 r11
    recorded on the URL-import path: ``aiter_bytes`` transparently inflates a
    ``Content-Encoding`` body, so a single wire chunk could materialise an
    unbounded ``bytes`` BEFORE this check ran, which is a compression bomb
    against the exact memory the bound exists to protect.
    """
    encoding = response.headers.get("Content-Encoding", "identity").lower()
    if encoding not in ("", "identity"):
        # Refused rather than decoded. `aiter_raw` would hand back the
        # compressed bytes and `json.loads` would fail on them with a message
        # about the wrong thing, so the cause is named here instead.
        raise ItemFetchFailedError("compressed page")
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > budget:
        # Free when the service is honest; no help when it is not, which is
        # what the running count below is for.
        raise ItemFetchFailedError("page exceeds the cap")
    read = 0
    chunks: list[bytes] = []
    async for chunk in response.aiter_raw():
        read += len(chunk)
        if read > budget:
            raise ItemFetchFailedError("page exceeds the cap")
        chunks.append(chunk)
    return b"".join(chunks)


async def _fetch_page(
    client: httpx.AsyncClient, url: str, headers: dict, *, budget: int
) -> tuple[object, int]:
    """One items page and its wire size, or a refusal. THE request site here.

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
            body = await _read_bounded(response, budget)
        return json.loads(body), len(body)
    except (httpx.HTTPError, SSRFError, ValueError) as exc:
        raise ItemFetchFailedError(str(exc)) from None


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
    downloaded = 0
    out.write('{"type": "FeatureCollection", "features": [')
    page_url: str | None = _items_url(url, collection)
    while page_url is not None and pages < MAX_PAGES:
        pages += 1
        if pages == 1 and on_first_request is not None:
            # fix(#1746 B2b review r17): the origin is contacted HERE now, not
            # by the subprocess, so this is the moment a caller that dates
            # origin contacts has to hear about. A materialisation that fails
            # on its first page has still reached the service, and leaving the
            # source's `last_checked_at` stale would report the opposite.
            on_first_request()
        document, size = await _fetch_page(
            client,
            page_url,
            headers,
            budget=min(MAX_PAGE_BYTES, MAX_BYTES - downloaded),
        )
        downloaded += size
        features = document.get("features") if isinstance(document, dict) else None
        for feature in features or []:
            encoded = json.dumps(feature, separators=(",", ":"))
            out.write(("," if written else "") + encoded)
            written += 1
            if feature_limit is not None and written >= feature_limit:
                page_url = None
                break
        else:
            following = _next_href(document, page_url)
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
    out.write("]}")
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
                with open(path, "w", encoding="utf-8") as out:
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
