"""Server-side fetch of a user-supplied HTTP(S) file URL into local staging.

feat(#1705): the URL variant of upload. Rule 2 (AGENTS.md security checklist)
shapes everything here — GDAL/ogr2ogr/rasterio NEVER see the caller's URL:

1. ``validate_url_for_ssrf`` gates the URL at submission time (router).
2. The fetch itself goes through ``make_safe_client()`` from
   ``app.platform.security`` — the IP-pinning transport re-resolves and
   re-validates at connect time, and the ``_revalidate_redirect`` hook
   re-runs SSRF validation against every 3xx ``Location`` per hop.
3. The body streams to a staging file under a hard byte cap enforced
   PER CHUNK (a missing or lying ``Content-Length`` cannot bypass it).
4. The staged file then enters the normal upload pipeline unchanged:
   extension allowlist, magic-byte content sniff, preview, commit.

This module deliberately imports nothing from ``app.modules.*`` — the
PROCESS-02/04 burndown lists in ``tests/test_layering.py`` may only shrink,
so all domain wiring (auth, quota, job rows) stays in the router, which
already owns those edges.
"""

import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from app.core.async_io import run_in_thread_draining
from app.platform.security import SSRFError, make_safe_client

# Connect fast; the read clock is per-chunk (httpx read timeout is the max
# gap between bytes), so a steadily flowing large download is fine.
FETCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# Wall-clock ceiling for one fetch. The per-chunk read timeout above cannot
# bound TOTAL time: a server trickling one chunk every few seconds holds the
# request coroutine open forever while staying inside every socket timeout.
# 10 minutes admits a full 500 MB default-cap file at ~7 Mbps and turns a
# slow-loris origin into a clean 502 instead of a leaked request.
FETCH_MAX_SECONDS = 600

_CHUNK_SIZE = 65536

# Batch threaded writes, mirroring manifest_service._download_http_source
# (fix #435 there): a thread handoff per 64 KiB httpx chunk is pure overhead,
# so buffer up to 4 MiB between writes.
_WRITE_BUFFER_BYTES = 4 * 1024 * 1024

# Longest filename we stage from a URL. Filesystem name components cap at
# 255 bytes and the staging layout prepends "{job_id}_" (37 chars), so trim
# the stem — never the suffix, which the extension allowlist keys on.
_MAX_FILENAME_CHARS = 160


class UrlFetchError(ValueError):
    """The remote file could not be fetched (HTTP error or network failure)."""


class UrlFetchTooLargeError(UrlFetchError):
    """The remote file exceeds the configured maximum upload size."""


def filename_from_url(url: str) -> str:
    """Derive a staging filename from the URL path's percent-decoded basename.

    Returns ``""`` when the path carries no usable name (e.g. ``https://host/``
    or ``https://host/download?id=3``) — the router then requires an explicit
    ``filename`` in the request body instead of guessing.
    """
    name = Path(unquote(urlparse(url).path or "")).name
    if len(name) <= _MAX_FILENAME_CHARS:
        return name
    suffix = Path(name).suffix
    return name[: _MAX_FILENAME_CHARS - len(suffix)] + suffix


def _size_cap_error(max_size_bytes: int) -> UrlFetchTooLargeError:
    return UrlFetchTooLargeError(
        f"The remote file exceeds the maximum allowed size "
        f"({max_size_bytes / (1024 * 1024):.1f} MB)."
    )


async def fetch_url_to_path(url: str, dest: Path, max_size_bytes: int) -> int:
    """Stream ``url`` into ``dest`` under a hard size cap. Returns total bytes.

    The cap is enforced twice: a declared ``Content-Length`` above the cap is
    refused before any body byte is read, and the chunk loop counts what
    actually arrives so an absent or dishonest header changes nothing.

    On ANY failure the partial ``dest`` is removed before the exception
    propagates. Raises:

    - ``UrlFetchTooLargeError`` — size cap exceeded (declared or streamed).
    - ``SSRFError`` — a redirect hop or connect-time re-resolution targeted a
      blocked address (propagated from the safe client untouched, so the
      router's submission-time handler covers both moments identically).
    - ``UrlFetchError`` — non-2xx status, timeout, wall-clock deadline, or any
      other transport failure.
    """
    total = 0
    deadline = time.monotonic() + FETCH_MAX_SECONDS
    # Synchronous open, mirroring save_upload_file: no cancellation point
    # between acquiring the descriptor and owning it.
    f = open(dest, "wb")
    try:
        try:
            try:
                async with make_safe_client(timeout=FETCH_TIMEOUT) as client:
                    async with client.stream("GET", url) as response:
                        if response.status_code >= 400:
                            raise UrlFetchError(
                                f"The server returned HTTP {response.status_code} "
                                f"for this URL."
                            )
                        declared = response.headers.get("Content-Length", "")
                        if declared.isdigit() and int(declared) > max_size_bytes:
                            raise _size_cap_error(max_size_bytes)
                        # Drained threaded writes (so a cancelled request
                        # cannot leave a worker thread writing through an
                        # unlinked descriptor), batched through a buffer so
                        # the handoff is not paid per httpx chunk.
                        # `bytes(buffer)` snapshots before the thread reads
                        # it, so the following `clear()` is safe.
                        buffer = bytearray()
                        async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                            total += len(chunk)
                            if total > max_size_bytes:
                                raise _size_cap_error(max_size_bytes)
                            if time.monotonic() > deadline:
                                raise UrlFetchError(
                                    "The download did not finish within "
                                    f"{FETCH_MAX_SECONDS // 60} minutes."
                                )
                            buffer.extend(chunk)
                            if len(buffer) >= _WRITE_BUFFER_BYTES:
                                await run_in_thread_draining(f.write, bytes(buffer))
                                buffer.clear()
                        if buffer:
                            await run_in_thread_draining(f.write, bytes(buffer))
            except SSRFError:
                # A redirect hop or connect-time re-resolution was refused.
                # Keep the class: the router maps it exactly like the
                # submission-time refusal.
                raise
            except httpx.HTTPError as exc:
                # Timeouts, DNS failures once past validation, TLS errors,
                # protocol violations, too many redirects — all origin-side.
                raise UrlFetchError(f"Could not download the file: {exc}") from exc
        finally:
            await run_in_thread_draining(f.close)
    except BaseException:
        # Partial or refused download: remove the file before propagating.
        # Ordering matters — the descriptor was drained and closed above.
        dest.unlink(missing_ok=True)
        raise
    return total


__all__ = [
    "FETCH_MAX_SECONDS",
    "FETCH_TIMEOUT",
    "SSRFError",
    "UrlFetchError",
    "UrlFetchTooLargeError",
    "fetch_url_to_path",
    "filename_from_url",
]
