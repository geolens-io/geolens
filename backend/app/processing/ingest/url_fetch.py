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
import structlog

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.platform.security import SSRFError, make_safe_client

logger = structlog.get_logger(__name__)

# Connect fast; the read clock is per-chunk (httpx read timeout is the max
# gap between bytes), so a steadily flowing large download is fine.
FETCH_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

# The edge proxy's ceiling on any /api/ request: frontend/nginx.conf's
# `location /api/` sets `proxy_read_timeout 600s`, and this endpoint sends
# NOTHING until the fetch AND all post-work (sniff, quota recheck, S3
# staging copy, final commit) finish — so the whole synchronous path must
# fit inside that deadline or nginx severs the response before the job id
# reaches the browser (#1708 codex r3). A constant so the budget arithmetic
# below is checkable; imports that genuinely need longer need the async
# fetch job (#1710).
EDGE_PROXY_READ_TIMEOUT_SECONDS = 600

# Joint budget for everything the synchronous request stages: fetch +
# content sniff + (S3 mode) the staging put, measured from fetch start.
# fix(#1708): FETCH_MAX_SECONDS bounds only the download — a valid
# near-limit fetch followed by a slow remote-S3 upload still blew past the
# proxy. The put is a blocking boto3 upload in a DRAINED thread
# (storage/s3.py), so asyncio.timeout around it wouldn't bound wall time;
# the router instead waits on the put task only for the budget's remainder
# and ABANDONS the wait at the deadline, bounded by botocore's
# connect_timeout=10/read_timeout=60/3 retries, with a late-landing object
# deleted by the abandonment reaper.
#
# fix(#1708): 540 -> 510, derived rather than assumed. This
# budget's clock does NOT cover the request's whole life (see the
# INVARIANT at its initialization in router.py): auth/permission work runs
# BEFORE the handler body, and the post-stage transaction runs after the
# budget expires; both can wait on a pool checkout up to
# ``settings.db_pool_timeout`` (default 30s). Worst case:
#
#     30s  pre-handler pool wait (db_pool_timeout)
#   + 510s joint stage budget (this constant)
#   + 30s  post-stage pool wait (db_pool_timeout)
#   +  ~0  single-row CAS/commit + serialization, local Postgres
#   = 570s  <= 600s proxy read timeout, ~30s margin
#
# (540 reached exactly 600, no margin.) Fetch keeps its full ceiling either
# way: PREFLIGHT_DNS_MAX_SECONDS + FETCH_MAX_SECONDS == 510.
#
# fix(#1708): 510 is the CEILING, not the answer. db_pool_timeout
# is operator-settable, and a hardcoded 510 silently breaks the invariant
# once raised — at DB_POOL_TIMEOUT=60 the sum is 60+60+510+60+20 = 710 > 600
# and the job id is lost after a successful staging (THREE checkouts, not
# two — r17 undercounted, r18 caught it; see POOL_CHECKOUTS_PER_REQUEST).
# CI only runs the default, so no test catches this either — the budget is
# DERIVED per request from the configured value (``stage_total_budget_seconds``)
# and this constant only bounds it above.
STAGE_TOTAL_CEILING_SECONDS = 510

# Every point where this handler's session BEGINS a transaction after a
# release. Each is a pool checkout that can block up to db_pool_timeout,
# none inside the joint stage clock, so the budget must reserve room for
# every one. Enumerated from ``upload_from_url`` (fix(#1708) codex r18,
# which caught a prior count of 2):
#
#   1. Auth/dependency phase — require_permission -> get_current_user;
#      released by the pre-gate commit (r4).
#   2. Pre-fetch transaction — allowlist/size/quota checks, job INSERT +
#      running stamp; released by the pre-fetch commit (r2/P1).
#   3. Post-stage transaction — byte quota, running->pending CAS, commit.
#
# The non-ambiguous failure path is also 3. The ambiguous-commit path adds
# a 4th — the probe's fresh session — deliberately NOT budgeted: reached
# only when a commit's acknowledgement is lost and the response is already
# an error, so a late response there costs nothing beyond what's already lost.
POOL_CHECKOUTS_PER_REQUEST = 3

# Reserved, beyond the pool waits, for the post-stage transaction's
# single-row CAS and commit plus response serialization — all local
# Postgres, milliseconds in practice; 20s is deliberate slack, not an
# estimate of their cost.
POST_WORK_MARGIN_SECONDS = 20

# A pathological pool timeout (DB_POOL_TIMEOUT=300 leaves 600-900-20 = -320)
# must not yield a zero/negative budget or crash the app at import. Clamp
# here, STRICTLY BELOW ``MIN_FETCH_BUDGET_SECONDS`` so the refusal is
# guaranteed by construction: ``_remaining_fetch_budget`` sees a remainder
# under its floor and refuses before opening a connection. The one-time
# warning below gives the operator a cause instead of a mysterious 502.
STAGE_BUDGET_FLOOR_SECONDS = 1

_budget_floor_warned = False


def stage_total_budget_seconds() -> int:
    """The joint stage budget for THIS deployment's pool configuration.

    fix(#1708): derived rather than asserted, so raising
    ``settings.db_pool_timeout`` (waited on ``POOL_CHECKOUTS_PER_REQUEST``
    times) shrinks the staging budget automatically instead of quietly
    pushing the response past nginx:

        min(STAGE_TOTAL_CEILING,
            EDGE_PROXY - POOL_CHECKOUTS_PER_REQUEST*pool_timeout
            - POST_WORK_MARGIN)

    The ceiling keeps a very small pool timeout from inflating the budget
    past what preflight/fetch assume; the floor keeps a very large one from
    producing a nonsensical budget.
    """
    global _budget_floor_warned

    pool_timeout = settings.db_pool_timeout
    derived = (
        EDGE_PROXY_READ_TIMEOUT_SECONDS
        - (POOL_CHECKOUTS_PER_REQUEST * pool_timeout)
        - POST_WORK_MARGIN_SECONDS
    )
    budget = min(STAGE_TOTAL_CEILING_SECONDS, derived)
    if budget < STAGE_BUDGET_FLOOR_SECONDS:
        if not _budget_floor_warned:
            _budget_floor_warned = True
            logger.warning(
                "url_import_stage_budget_floored",
                db_pool_timeout=pool_timeout,
                edge_proxy_read_timeout=EDGE_PROXY_READ_TIMEOUT_SECONDS,
                derived_budget=derived,
                floor=STAGE_BUDGET_FLOOR_SECONDS,
                detail=(
                    "DB_POOL_TIMEOUT leaves no room for URL-import staging "
                    "inside the edge proxy's read timeout; URL imports will "
                    "be refused. Lower DB_POOL_TIMEOUT or raise the proxy's "
                    "proxy_read_timeout."
                ),
            )
        return STAGE_BUDGET_FLOOR_SECONDS
    return budget


# Bound on the submission-time SSRF preflight (validate_url_for_ssrf's
# getaddrinfo). fix(#1708): the one long operation left outside
# every deadline — stalled DNS could blow the pre-fetch budget and pile up
# executor resolver threads under load. Bounded AT THE CALL SITE
# (platform/security.py stays untouched — see #1710): asyncio.wait_for
# cancels the to_thread wrapper, which returns immediately while the
# resolver thread runs on until the OS resolver gives up — same abandonment
# pattern as the staging put. 30s dwarfs any healthy resolution and fits
# inside the stage budget with the full fetch cap intact (30+480<=540,
# pinned by the budget test).
PREFLIGHT_DNS_MAX_SECONDS = 30

# The least remaining joint budget worth starting a fetch with. Below this a
# download cannot plausibly connect, transfer and stage, so the request is
# refused promptly with the ordinary timeout shape instead of opening a
# doomed connection (fix(#1708) codex r13).
MIN_FETCH_BUDGET_SECONDS = 5

# Wall-clock ceiling for one fetch. The per-chunk read timeout above cannot
# bound TOTAL time: a server trickling one chunk every few seconds holds the
# request coroutine open forever while staying inside every socket timeout.
#
# Budgeted INSIDE the proxy deadline: 480s of fetch leaves ~120s for
# post-work, of which only the S3 staging copy scales with file size (a
# 500 MB copy to same-network MinIO takes seconds; ~84s even at a
# conservative 50 Mbps to remote S3). A download that can't finish in 480s
# could never complete under the 600s edge deadline anyway — the budget
# turns a mid-flight severed connection into a prompt, clean 502 with the
# staged bytes removed.
FETCH_MAX_SECONDS = 480

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
    # fix(#1708): the caller passes what the JOINT budget has
    # left. Defaulting to the constant keeps the function usable on its
    # own; the handler never relies on that (see stage_total_budget_seconds()).
    fetch_timeout = (
        FETCH_MAX_SECONDS
        if timeout_seconds is None
        else min(FETCH_MAX_SECONDS, timeout_seconds)
    )
    # Synchronous open, mirroring save_upload_file: no cancellation point
    # between acquiring the descriptor and owning it.
    # codeql[py/path-injection] fix(#1708): dest's caller-influenced component is basename-stripped and byte-clamped (clamp_filename_bytes), rooted under upload_staging_dir
    f = open(dest, "wb")
    try:
        try:
            try:
                # fix(#1708): the wall clock wraps the ENTIRE
                # request — DNS, TLS, headers, every redirect hop, the body —
                # not just gaps between chunks. The previous per-chunk check
                # never ran while an origin stalled DNS or trickled headers
                # under httpx's per-read timeout, letting it hold the request
                # past the 600s edge proxy deadline. asyncio.timeout cancels
                # the scope at the deadline (drained writes finish their
                # in-flight chunk first, so no thread outlives the
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
    "FETCH_MAX_SECONDS",
    "MIN_FETCH_BUDGET_SECONDS",
    "PREFLIGHT_DNS_MAX_SECONDS",
    "POOL_CHECKOUTS_PER_REQUEST",
    "POST_WORK_MARGIN_SECONDS",
    "STAGE_BUDGET_FLOOR_SECONDS",
    "STAGE_TOTAL_CEILING_SECONDS",
    "stage_total_budget_seconds",
    "FETCH_TIMEOUT",
    "SSRFError",
    "UrlFetchError",
    "UrlFetchTooLargeError",
    "clamp_filename_bytes",
    "fetch_url_to_path",
    "filename_from_url",
]
