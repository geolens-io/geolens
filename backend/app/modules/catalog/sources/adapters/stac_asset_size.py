"""On-demand size lookup for STAC data assets whose item omits ``file:size``.

The asset URLs belong to a catalog the caller chose, so every request goes
through ``make_safe_client()``. Sizes are informational only: any failure
leaves the size unknown rather than failing the review step.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace

import httpx
import structlog

from app.core.service_tokens import (
    STAC_SERVICE_FORMAT,
    ServiceCredential,
    build_credential_header,
)
from app.platform.security import (
    SSRFError,
    make_safe_client,
    same_origin,
    validate_url_for_ssrf,
)

logger = structlog.stdlib.get_logger(__name__)

PROBE_TIMEOUT = 8.0
MAX_CONCURRENT_PROBES = 4

_CONTENT_RANGE_TOTAL = re.compile(r"^bytes\s+\d+-\d+/(\d+)$")


def _length(value: str | None) -> int | None:
    return (
        int(value)
        if value is not None and value.isascii() and value.isdigit()
        else None
    )


def _head_size(response: httpx.Response) -> int | None:
    if not response.is_success:
        return None
    return _length(response.headers.get("content-length"))


def _range_size(response: httpx.Response) -> int | None:
    if response.status_code == 206:
        match = _CONTENT_RANGE_TOTAL.match(response.headers.get("content-range", ""))
        return int(match.group(1)) if match else None
    # A server that ignores Range answers 200 with the whole entity's length.
    if response.status_code == 200:
        return _length(response.headers.get("content-length"))
    return None


async def _probe_size(
    client: httpx.AsyncClient, href: str, headers: dict[str, str]
) -> int | None:
    headers = {**headers, "Accept-Encoding": "identity"}
    size = _head_size(await client.head(href, headers=headers))
    if size is not None:
        return size
    # Streamed and closed unread: only the headers are wanted.
    async with client.stream(
        "GET", href, headers={**headers, "Range": "bytes=0-0"}
    ) as response:
        return _range_size(response)


async def _asset_size(
    href: str,
    catalog_url: str,
    credential_pair: tuple[str, str] | None,
    gate: asyncio.Semaphore,
) -> int | None:
    # The catalog's key goes only to the catalog's own origin; assets usually
    # live on a storage host that has no business receiving it.
    pair = credential_pair if same_origin(catalog_url, href) else None
    headers = {} if pair is None else {pair[0]: pair[1]}
    try:
        await validate_url_for_ssrf(href)
        async with gate, asyncio.timeout(PROBE_TIMEOUT):
            async with make_safe_client(
                timeout=PROBE_TIMEOUT,
                credential_header=None if pair is None else pair[0],
            ) as client:
                return await _probe_size(client, href, headers)
    except (SSRFError, httpx.HTTPError, OSError):
        logger.info("STAC asset size probe failed")
        return None


async def probe_asset_sizes(
    catalog_url: str,
    assets: dict[str, str],
    credential: ServiceCredential | None = None,
) -> dict[str, int | None]:
    """Byte size per key of *assets* (key to asset URL), ``None`` when unknown.

    HEAD first, then a one-byte range request, reading ``Content-Length`` or
    the ``Content-Range`` total. At most ``MAX_CONCURRENT_PROBES`` run at once.
    """
    pair = (
        None
        if credential is None
        else build_credential_header(
            replace(credential, service_format=STAC_SERVICE_FORMAT)
        )
    )
    gate = asyncio.Semaphore(MAX_CONCURRENT_PROBES)
    sizes = await asyncio.gather(
        *(_asset_size(href, catalog_url, pair, gate) for href in assets.values())
    )
    return dict(zip(assets, sizes))
