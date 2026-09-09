"""Worker-side fetch of a user-supplied HTTP(S) file URL into local staging.

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
import structlog

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.platform.security import SSRFError, make_safe_client

logger = structlog.get_logger(__name__)

# Connect fast; the read clock is per-chunk (httpx read timeout is the max
# gap between bytes), so a steadily flowing large download is fine.
FETCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# The edge proxy's ceiling on any /api/ request: frontend/nginx.conf's
# `location /api/` sets `proxy_read_timeout 600s`. feat(#1710) took the URL
# import off that clock — the download is a worker job now — but the
# constant stays here, where it is documented, for the request-scoped
# consumers that still budget against it (processing/export/ogr.py and
# export/router.py, and the statement-timeout bound in core config).
EDGE_PROXY_READ_TIMEOUT_SECONDS = 600

# Bound on the submission-time SSRF preflight (validate_url_for_ssrf's
# getaddrinfo). fix(#1708): stalled DNS has no bound of its own and would
# pile up executor resolver threads under load. Bounded AT THE CALL SITE
# (platform/security.py stays untouched): asyncio.wait_for cancels the
# to_thread wrapper, which returns immediately while the resolver thread
# runs on until the OS resolver gives up. 30s dwarfs any healthy
# resolution, and this is now the ONLY long operation on the request path
# — feat(#1710) moved the download itself to the worker.
PREFLIGHT_DNS_MAX_SECONDS = 30

_CHUNK_SIZE = 65536

# Batch threaded writes, mirroring manifest_service._download_http_source
# (fix(#435)): a thread handoff per 64 KiB httpx chunk is pure overhead, so
# buffer up to 4 MiB between writes.
_WRITE_BUFFER_BYTES = 4 * 1024 * 1024

# Longest filename we stage, in ENCODED UTF-8 BYTES — filesystems cap name
# components in bytes (NAME_MAX 255), not characters, so a character-count
# cap admits multibyte names four times too long (#1708 codex P2). Local
# staging prepends "{job_id}_" (37 bytes) and resolve_file_path's mkstemp
# builds "{job_id}_<8 random>_{name}" (46 bytes), so 160 keeps the worst
# component at 206 bytes, under the limit.
_MAX_FILENAME_BYTES = 160


class UrlFetchError(ValueError):
    """The remote file could not be fetched (HTTP error or network failure)."""


class UrlFetchTooLargeError(UrlFetchError):
    """The remote file exceeds the configured maximum upload size."""


def clamp_filename_bytes(name: str) -> str:
    """Trim the STEM so the whole name fits ``_MAX_FILENAME_BYTES`` of UTF-8.

    fix(#1708): clamps by encoded byte length, never splitting a
    codepoint, and keeps the suffix — the extension allowlist keys on it.
    Both name sources (URL basename, the request's ``filename`` override)
    go through here before any path is built.
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


def _size_cap_error(
    max_size_bytes: int, cap_error_detail: str | None = None
) -> UrlFetchTooLargeError:
    # fix(#1708): when the effective cap is the caller's quota
    # rather than the instance limit, the refusal should say so — the caller
    # passes the quota-shaped detail and both refusal sites speak with one voice.
    if cap_error_detail is not None:
        return UrlFetchTooLargeError(cap_error_detail)
    return UrlFetchTooLargeError(
        f"The remote file exceeds the maximum allowed size "
        f"({max_size_bytes / (1024 * 1024):.1f} MB)."
    )


async def fetch_url_to_path(
    url: str,
    dest: Path,
    max_size_bytes: int,
    *,
    cap_error_detail: str | None = None,
    timeout_seconds: float | None = None,
) -> int:
    """Stream ``url`` into ``dest`` under a hard size cap. Returns total bytes.

    The cap is enforced twice: a declared ``Content-Length`` above the cap is
    refused before any body byte is read, and the chunk loop counts what
    actually arrives so an absent or dishonest header changes nothing.

    On ANY failure the partial ``dest`` is removed before the exception
    propagates. Raises:

    - ``UrlFetchTooLargeError`` — size cap exceeded (declared or streamed).
    - ``SSRFError`` — a redirect hop or connect-time re-resolution targeted a
      blocked address (propagated from the safe client untouched).
    - ``UrlFetchError`` — non-2xx status, timeout, wall-clock deadline, or any
      other transport failure.
    """
    total = 0
    # feat(#1710): the operator's ceiling, no longer a share of a request
    # budget — the download runs on the worker under a heartbeat-renewed
    # lease, so nothing upstream of it expires while it transfers.
    fetch_timeout = (
        float(settings.url_import_fetch_max_seconds)
        if timeout_seconds is None
        else timeout_seconds
    )
    # Synchronous open, mirroring save_upload_file: no cancellation point
    # between acquiring the descriptor and owning it.
    # codeql[py/path-injection] fix(#1708): dest's caller-influenced component is basename-stripped and byte-clamped (clamp_filename_bytes), rooted under upload_staging_dir
    f = open(dest, "wb")
    try:
        try:
            try:
                # fix(#1708): the wall clock wraps the ENTIRE fetch — DNS,
                # TLS, headers, every redirect hop, the body — not just gaps
                # between chunks, which is what an origin trickling one chunk
                # per read timeout stays inside forever. asyncio.timeout
                # cancels the scope at the deadline (drained writes finish
                # their in-flight chunk first, so no thread outlives the
                # descriptor) and raises TimeoutError at exit, translated
                # below — same outer-deadline pattern as origin_probe.py.
                async with asyncio.timeout(fetch_timeout):
                    async with make_safe_client(timeout=FETCH_TIMEOUT) as client:
                        # fix(#1708): identity requested, enforced
                        # below, and the loop reads aiter_raw — three layers
                        # against compression bombs (see the loop comment).
                        #
                        # The marker below must stay the LAST line before the
                        # call: the suppression query binds a marker to the
                        # line that follows it, so an explanatory comment
                        # inserted between the two silently disarms it (that
                        # is how alert 103 re-fired at r11). Prose goes above.
                        # codeql[py/full-ssrf] fix(#1708): Rule 2 posture — validate_url_for_ssrf gates the URL at submission, and make_safe_client's transport re-resolves, validates, and pins the IP at connect time plus revalidates every redirect hop
                        async with client.stream(
                            "GET",
                            url,
                            headers={"Accept-Encoding": "identity"},
                        ) as response:
                            if response.status_code >= 400:
                                raise UrlFetchError(
                                    f"The server returned HTTP "
                                    f"{response.status_code} for this URL."
                                )
                            # fix(#1708): a transport-compressed
                            # response is refused by design — the staged
                            # file must be the literal bytes the sniff and
                            # GDAL will read.
                            encoding = response.headers.get(
                                "Content-Encoding", "identity"
                            ).lower()
                            if encoding not in ("", "identity"):
                                raise UrlFetchError(
                                    "The server sent a transport-compressed "
                                    f"response (Content-Encoding: {encoding}). "
                                    "URL imports require an uncompressed "
                                    "transfer; the file itself may be any "
                                    "supported format."
                                )
                            declared = response.headers.get("Content-Length", "")
                            if declared.isdigit() and int(declared) > max_size_bytes:
                                raise _size_cap_error(max_size_bytes, cap_error_detail)
                            # Drained threaded writes (so a cancelled
                            # request can't leave a worker thread writing
                            # through an unlinked descriptor), batched
                            # through a buffer so the handoff isn't paid per
                            # httpx chunk. `bytes(buffer)` snapshots before
                            # the thread reads it, so `clear()` is safe.
                            #
                            # fix(#1708): aiter_raw, NEVER
                            # aiter_bytes. aiter_bytes transparently inflates
                            # Content-Encoding gzip/br/zstd, so one wire
                            # chunk could materialize an unbounded
                            # intermediate `bytes` BEFORE the size check ran
                            # — a compression bomb despite the streaming cap.
                            # aiter_raw measures wire bytes even if the
                            # origin lies about its encoding, which (with
                            # identity enforced above) are exactly the
                            # staged bytes.
                            buffer = bytearray()
                            async for chunk in response.aiter_raw(_CHUNK_SIZE):
                                total += len(chunk)
                                if total > max_size_bytes:
                                    raise _size_cap_error(
                                        max_size_bytes, cap_error_detail
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
            except TimeoutError as exc:
                # The outer wall clock above. Not an httpx class: httpx's
                # phase timeouts subclass httpx.HTTPError and are translated
                # below; this one can fire during DNS or header acquisition
                # where no httpx timeout is running down.
                raise UrlFetchError(
                    "The download did not finish within the time budget "
                    f"({int(fetch_timeout)} seconds)."
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
        # fix(#1708): best-effort, so a path the filesystem refuses
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
    "PREFLIGHT_DNS_MAX_SECONDS",
    "FETCH_TIMEOUT",
    "SSRFError",
    "UrlFetchError",
    "UrlFetchTooLargeError",
    "clamp_filename_bytes",
    "fetch_url_to_path",
    "filename_from_url",
]
