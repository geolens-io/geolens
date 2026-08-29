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

import asyncio

from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from app.core.async_io import run_in_thread_draining
from app.platform.security import SSRFError, make_safe_client

# Connect fast; the read clock is per-chunk (httpx read timeout is the max
# gap between bytes), so a steadily flowing large download is fine.
FETCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# The edge proxy's ceiling on any /api/ request: frontend/nginx.conf's
# `location /api/` sets `proxy_read_timeout 600s`, and this endpoint sends
# NOTHING until the fetch AND all post-work (content sniff, quota recheck,
# S3 staging copy, final commit) have finished — so the whole synchronous
# path has to fit inside that deadline or nginx severs the response before
# the job id ever reaches the browser (#1708 codex r3). Documented here as a
# constant so the budget arithmetic below is checkable; the structural fix
# for imports that genuinely need longer is the async fetch job (#1710).
EDGE_PROXY_READ_TIMEOUT_SECONDS = 600

# Wall-clock ceiling for one fetch. The per-chunk read timeout above cannot
# bound TOTAL time: a server trickling one chunk every few seconds holds the
# request coroutine open forever while staying inside every socket timeout.
#
# Budgeted INSIDE the proxy deadline: 480s of fetch leaves ~120s for the
# post-work, of which only the S3 staging copy scales with file size — a
# 500 MB copy to same-network MinIO takes seconds, and even a conservative
# 50 Mbps push to remote S3 is ~84s; the sniff reads header/footer bytes and
# the quota recheck and commit are single-row queries. A download that
# cannot finish in 480s could never have completed under the 600s edge
# deadline anyway (500 MB at the old bound's ~7 Mbps floor is ~571s of
# transfer alone, before any post-work) — the budget turns a mid-flight
# severed connection into a prompt, clean 502 with the staged bytes removed.
FETCH_MAX_SECONDS = 480

_CHUNK_SIZE = 65536

# Batch threaded writes, mirroring manifest_service._download_http_source
# (fix #435 there): a thread handoff per 64 KiB httpx chunk is pure overhead,
# so buffer up to 4 MiB between writes.
_WRITE_BUFFER_BYTES = 4 * 1024 * 1024

# Longest filename we stage, measured in ENCODED UTF-8 BYTES — filesystems
# cap name components in bytes (NAME_MAX 255), not characters, so a
# character-count cap admits multibyte names four times too long
# (#1708 codex P2). Budget arithmetic for every downstream construction:
# local staging prepends "{job_id}_" (37 bytes) and resolve_file_path's
# mkstemp builds "{job_id}_<8 random>_{name}" (46 bytes), so 160 keeps the
# worst component at 206 bytes, well under the limit.
_MAX_FILENAME_BYTES = 160


class UrlFetchError(ValueError):
    """The remote file could not be fetched (HTTP error or network failure)."""


class UrlFetchTooLargeError(UrlFetchError):
    """The remote file exceeds the configured maximum upload size."""


def clamp_filename_bytes(name: str) -> str:
    """Trim the STEM so the whole name fits ``_MAX_FILENAME_BYTES`` of UTF-8.

    fix(#1708 codex P2): clamps by encoded byte length, never splitting a
    codepoint, and keeps the suffix — the extension allowlist keys on it, so
    the clamp must not manufacture or destroy an extension. Both name
    sources (URL basename and the request's ``filename`` override) go
    through here before any path is built from them.
    """
    if len(name.encode("utf-8")) <= _MAX_FILENAME_BYTES:
        return name
    suffix = Path(name).suffix
    budget = _MAX_FILENAME_BYTES - len(suffix.encode("utf-8"))
    if budget <= 0:
        # Pathological "suffix" longer than the whole budget: byte-truncate
        # the raw name; the extension allowlist refuses whatever remains.
        return name.encode("utf-8")[:_MAX_FILENAME_BYTES].decode("utf-8", "ignore")
    stem = name[: len(name) - len(suffix)] if suffix else name
    return stem.encode("utf-8")[:budget].decode("utf-8", "ignore") + suffix


def filename_from_url(url: str) -> str:
    """Derive a staging filename from the URL path's percent-decoded basename.

    Returns ``""`` when the path carries no usable name (e.g. ``https://host/``
    or ``https://host/download?id=3``) — the router then requires an explicit
    ``filename`` in the request body instead of guessing.
    """
    return clamp_filename_bytes(Path(unquote(urlparse(url).path or "")).name)


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
    # Synchronous open, mirroring save_upload_file: no cancellation point
    # between acquiring the descriptor and owning it.
    # codeql[py/path-injection] fix(#1708): dest's caller-influenced component is basename-stripped and byte-clamped (clamp_filename_bytes), rooted under upload_staging_dir
    f = open(dest, "wb")
    try:
        try:
            try:
                # fix(#1708 codex r5): the wall clock wraps the ENTIRE
                # request — connect-time DNS, TLS, headers, every redirect
                # hop, and the body — not just the gaps between body chunks.
                # The previous per-chunk elapsed check never ran while an
                # origin stalled DNS or trickled headers under httpx's
                # per-read timeout, so such an origin could hold the request
                # past the edge proxy's 600s deadline. asyncio.timeout
                # cancels the scope at the deadline (the drained threaded
                # writes finish their in-flight chunk first, so no thread
                # outlives the descriptor) and raises TimeoutError at exit,
                # translated below. Same outer-deadline pattern as
                # origin_probe.py, whose comment records that unlike httpx's
                # phase timeouts it can expire during DNS resolution.
                async with asyncio.timeout(FETCH_MAX_SECONDS):
                    async with make_safe_client(timeout=FETCH_TIMEOUT) as client:
                        # codeql[py/full-ssrf] fix(#1708): Rule 2 posture — validate_url_for_ssrf gates the URL at submission, and make_safe_client's transport re-resolves, validates, and pins the IP at connect time plus revalidates every redirect hop
                        async with client.stream("GET", url) as response:
                            if response.status_code >= 400:
                                raise UrlFetchError(
                                    f"The server returned HTTP "
                                    f"{response.status_code} for this URL."
                                )
                            declared = response.headers.get("Content-Length", "")
                            if declared.isdigit() and int(declared) > max_size_bytes:
                                raise _size_cap_error(max_size_bytes)
                            # Drained threaded writes (so a cancelled request
                            # cannot leave a worker thread writing through an
                            # unlinked descriptor), batched through a buffer
                            # so the handoff is not paid per httpx chunk.
                            # `bytes(buffer)` snapshots before the thread
                            # reads it, so the following `clear()` is safe.
                            buffer = bytearray()
                            async for chunk in response.aiter_bytes(_CHUNK_SIZE):
                                total += len(chunk)
                                if total > max_size_bytes:
                                    raise _size_cap_error(max_size_bytes)
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
            except TimeoutError as exc:
                # The outer wall clock above. Not an httpx class: httpx's
                # phase timeouts subclass httpx.HTTPError and are translated
                # below; this one can fire during DNS or header acquisition
                # where no httpx timeout is running down.
                raise UrlFetchError(
                    "The download did not finish within "
                    f"{FETCH_MAX_SECONDS // 60} minutes."
                ) from exc
            except httpx.HTTPError as exc:
                # Timeouts, DNS failures once past validation, TLS errors,
                # protocol violations, too many redirects — all origin-side.
                raise UrlFetchError(f"Could not download the file: {exc}") from exc
        finally:
            await run_in_thread_draining(f.close)
    except BaseException:
        # Partial or refused download: remove the file before propagating.
        # Ordering matters — the descriptor was drained and closed above.
        # fix(#1708 codex r5): best-effort, so a path the filesystem refuses
        # (or a transient FS error) cannot replace the real failure on its
        # way to the caller's cleanup-then-stamp sequence.
        try:
            # codeql[py/path-injection] fix(#1708): same clamped, staging-rooted path as the open above
            dest.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        raise
    return total


__all__ = [
    "EDGE_PROXY_READ_TIMEOUT_SECONDS",
    "FETCH_MAX_SECONDS",
    "FETCH_TIMEOUT",
    "SSRFError",
    "UrlFetchError",
    "UrlFetchTooLargeError",
    "clamp_filename_bytes",
    "fetch_url_to_path",
    "filename_from_url",
]
