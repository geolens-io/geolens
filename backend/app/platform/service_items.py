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

import json
import os
import tempfile
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
MAX_PAGES = 10_000
MAX_BYTES = 2 * 1024 * 1024 * 1024

# What a page fetch asks for. The service may answer with fewer.
PAGE_SIZE = 1000


class ItemFetchFailedError(EndpointCheckFailedError):
    """A page could not be read, or the chain tried to leave the origin.

    Subclasses the description check's refusal so every door that already
    answers that one answers this the same way: the caller's request named a
    URL whose collection cannot be read safely, and the field to change is the
    same.
    """


def _credential_headers(credential_line: str) -> dict[str, str]:
    name, _, value = credential_line.partition(HEADER_LINE_SEPARATOR)
    return {name: value, "Accept": "application/geo+json, application/json"}


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
            return urljoin(base, str(link["href"]))
    return None


async def _fetch_page(client: httpx.AsyncClient, url: str, headers: dict) -> object:
    """One items page, or a refusal. THE request site for this module.

    Every page is revalidated immediately before the request, including pages
    the previous one named: a chain the service controls is exactly where a
    host that resolved publicly a moment ago can start resolving to a private
    address (AGENTS.md Rule 2).
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
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, SSRFError, ValueError) as exc:
        raise ItemFetchFailedError(str(exc)) from None


async def materialise_oapif_items(
    url: str,
    collection: str,
    *,
    credential_line: str,
    staging_dir: str | Path,
    feature_limit: int | None = None,
) -> str:
    """Write a protected collection to a local GeoJSON file and return its path.

    The caller hands the returned path to GDAL INSTEAD of the OAPIF source, and
    writes no header file at all, which is what removes the credential from
    everything GDAL does.

    ``feature_limit`` stops early for a preview, which needs a handful of rows
    rather than the collection.

    Raises :class:`ItemFetchFailedError` for a page that cannot be read and for
    a ``next`` that leaves the submitted origin; the file is removed before
    either escapes, so a failure leaves nothing behind.
    """
    headers = _credential_headers(credential_line)
    handle, path = tempfile.mkstemp(
        prefix="oapif_items_", suffix=".geojson", dir=str(staging_dir)
    )
    os.close(handle)
    os.chmod(path, 0o600)

    written = 0
    pages = 0
    try:
        async with make_safe_client(
            timeout=PROBE_TIMEOUT, credential_header=next(iter(headers))
        ) as client:
            with open(path, "w", encoding="utf-8") as out:
                out.write('{"type": "FeatureCollection", "features": [')
                page_url: str | None = _items_url(url, collection)
                while page_url is not None and pages < MAX_PAGES:
                    pages += 1
                    document = await _fetch_page(client, page_url, headers)
                    features = (
                        document.get("features") if isinstance(document, dict) else None
                    )
                    for feature in features or []:
                        encoded = json.dumps(feature, separators=(",", ":"))
                        out.write(("," if written else "") + encoded)
                        written += 1
                        if out.tell() > MAX_BYTES:
                            raise ItemFetchFailedError("collection exceeds the cap")
                        if feature_limit is not None and written >= feature_limit:
                            page_url = None
                            break
                    else:
                        following = _next_href(document, page_url)
                        if following is not None and not same_origin(url, following):
                            # The whole reason this module exists. The page
                            # chose the next address; it does not get to choose
                            # a different service to be paid with this
                            # credential.
                            raise ItemFetchFailedError("next page leaves the origin")
                        page_url = following
                out.write("]}")
    except BaseException:
        # Never leave a partial collection behind: it is data read with
        # somebody's credential, and nothing downstream would know it is short.
        try:
            os.unlink(path)
        except OSError:
            pass
        raise

    logger.info(
        "materialised a protected OGC API collection locally",
        pages=pages,
        features=written,
    )
    return path
