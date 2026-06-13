"""Request body size limit middleware.

Rejects requests whose body exceeds the configured maximum, returning
413 Payload Too Large. Handles both Content-Length and chunked
Transfer-Encoding requests via stream byte counting.

BUG-007 (Phase 1181): The effective limit is resolved PER-REQUEST from the
cached PersistentConfig value instead of the boot-time env value, so an
admin-raised UPLOAD_MAX_SIZE_MB takes effect without a process restart.

GAP-001 (Phase 1184): Per-route body cap. Non-upload routes get a small
default cap (DEFAULT_BODY_LIMIT_BYTES = 10 MB). Only the two endpoints that
stream a multipart file body — POST /ingest/upload and POST
/datasets/{id}/reupload — get the admin-configurable UPLOAD_MAX_SIZE_MB
(500 MB default) resolved via _get_upload_limit(). Everything else, including
the JSON-only presigned / commit / preview sub-routes of those flows, stays on
the small default so a large JSON body cannot slip past the DoS cap (PR #249
review).

GAP-001 fix: the app runs with root_path="/api", but every deployment fronts
it with a proxy that STRIPS the /api prefix before the request reaches the
ASGI app (prod nginx `rewrite ^/api/(.*) /$1`; dev Vite proxy
`rewrite: p.replace(/^\\/api/, '')`). So scope["path"] is the un-prefixed
form (/ingest/upload) in real deployments, and matching against a literal
/api/ingest/upload prefix never fired — every upload was silently capped at
the 10 MB default. _is_upload_route normalises away the optional /api prefix
so the limit applies whether or not the proxy stripped it.

The resolution helper `_get_upload_limit` accepts a `route_override` seam:

    route_override or _get_upload_limit() or _FALLBACK_LIMIT_BYTES

`route_override=DEFAULT_BODY_LIMIT_BYTES` is passed for non-upload routes.
"""

import time
import uuid
from typing import Any

from starlette.responses import JSONResponse

from app.standards.ogc.errors import ProblemDetail

# Sync in-memory cache for the upload limit — avoids an async DB pool
# checkout on every request (mirrors DynamicCORSMiddleware's pattern).
# Layout: (cached_at: float, limit_bytes: int)
_limit_cache: tuple[float, int] = (0.0, 0)
_LIMIT_CACHE_TTL = 30  # seconds — matches PersistentConfig cache TTL

# Fallback used when the cache is cold AND the async DB path is unavailable
# (e.g. during lifespan startup before the pool is initialised).
_FALLBACK_LIMIT_BYTES = 500 * 1024 * 1024  # 500 MB

# GAP-001: small default cap for non-upload routes (protects JSON/form endpoints
# from large-body DoS while leaving file-upload paths unrestricted).
DEFAULT_BODY_LIMIT_BYTES = 10 * 1024 * 1024  # 10 MB


def _too_large_response(max_bytes: int) -> JSONResponse:
    """Build the 413 response in the app-wide RFC 7807 ProblemDetail shape.

    GAP-032: this middleware fires before ``register_error_handlers`` installs
    the shared exception handlers, so it must build the ProblemDetail body
    itself. Mirror that convention exactly — the ``type/title/status/detail``
    envelope and the ``application/problem+json`` media type — so SDK consumers
    that branch on the uniform error shape parse 413 like every other error.
    """
    return JSONResponse(
        status_code=413,
        content=ProblemDetail(
            title="Payload Too Large",
            status=413,
            detail=(
                f"Request body too large. Maximum allowed size is {max_bytes} bytes."
            ),
        ).model_dump(),
        media_type="application/problem+json",
    )


def _strip_api_prefix(path: str) -> str:
    """Strip the optional ``/api`` root_path prefix from *path*.

    The app is mounted with ``root_path="/api"``, but every deployment fronts it
    with a proxy that removes ``/api`` before the request reaches the ASGI app
    (prod nginx ``rewrite ^/api/(.*) /$1``; dev Vite proxy
    ``rewrite: p.replace(/^\\/api/, '')``). So ``scope["path"]`` is the
    un-prefixed form in production, while a direct hit on the API container keeps
    the prefix. Normalising both to the un-prefixed form lets the upload-route
    classifier fire in every case. The prefix match is case-sensitive, mirroring
    the proxy rewrites and FastAPI's case-sensitive routing.
    """
    if path.startswith("/api/"):
        return path[len("/api") :]  # drop "/api", keep the leading slash
    if path == "/api":
        return "/"
    return path


def _is_uuid(value: str) -> bool:
    """True if *value* parses as a UUID — mirrors the ``dataset_id: uuid.UUID``
    path parameter on the reupload route (FastAPI 422s a non-UUID segment)."""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _is_upload_route(path: str, method: str = "POST") -> bool:
    """Return True only for the two POST endpoints that receive file BYTES.

    GAP-001: file-upload routes need the large UPLOAD_MAX_SIZE_MB limit; every
    other route gets DEFAULT_BODY_LIMIT_BYTES so a large body cannot slip past
    the DoS cap. Exactly two endpoints stream a multipart file body:

        POST /ingest/upload                   (ingest.upload_file)
        POST /datasets/{dataset_id}/reupload  (datasets.reupload_dataset)

    The presigned initiate/complete, commit and preview sub-routes of those two
    flows carry only small JSON — the bytes go straight to object storage — so
    they stay on the default cap (PR #249 review: the previous /ingest/upload*
    prefix and "/reupload"-substring match let a 500 MB JSON body through on
    those routes).

    Both upload endpoints are POST-only, so the method is part of the match: a
    non-POST request to the same path (e.g. PUT /ingest/upload) would otherwise
    get the large cap and be rejected only as 405 *after* the large body was
    allowed through (PR #249 review).

    The optional ``/api`` prefix is normalised away first (see _strip_api_prefix)
    so the classifier fires on the proxy-stripped paths real deployments produce,
    not just on a direct hit against the API container. The match mirrors FastAPI
    routing EXACTLY so the large cap is never handed to a request routing will
    reject anyway: case-sensitive, no trailing slash (the routes are registered
    no-slash with redirect_slashes=False and no reverse alias), and the reupload
    dataset_id must parse as a UUID (the path param is typed uuid.UUID). Each
    otherwise let a variant that 404s/422s receive the large allowance (PR #249
    review rounds).
    """
    if method.upper() != "POST":
        return False
    norm = _strip_api_prefix(path)
    # POST /ingest/upload — the multipart new-file upload (NOT /upload/presigned*).
    if norm == "/ingest/upload":
        return True
    # POST /datasets/{dataset_id}/reupload — the multipart reupload. Match exactly
    # /datasets/<uuid>/reupload: a non-UUID segment 422s and the JSON sub-routes
    # beneath it (presigned/commit/preview) carry only small JSON.
    segments = norm.split("/")
    if (
        len(segments) == 4
        and segments[1] == "datasets"
        and segments[3] == "reupload"
        and _is_uuid(segments[2])
    ):
        return True
    return False


def _get_upload_limit(route_override: int | None = None) -> int:
    """Return the effective upload limit in bytes.

    Resolution order (Phase 1184 seam):
        1. route_override  — per-route cap (non-upload routes supply DEFAULT_BODY_LIMIT_BYTES)
        2. cached config   — PersistentConfig UPLOAD_MAX_SIZE_MB (30 s TTL)
        3. fallback        — _FALLBACK_LIMIT_BYTES (boot-time env default)

    The sync in-memory cache is populated by the async `_refresh_limit_cache`
    call inside ``__call__``.  This function is deliberately sync so it can be
    called from non-async contexts (tests, introspection).
    """
    if route_override is not None:
        return route_override

    _, cached_bytes = _limit_cache
    if cached_bytes > 0:
        return cached_bytes

    return _FALLBACK_LIMIT_BYTES


async def _refresh_limit_cache() -> int:
    """Async refresh of the sync limit cache from PersistentConfig.

    Called once per request when the cache has expired (TTL = 30 s).
    Uses its own async_session so it does not interfere with the request's
    DB session.  Mirrors DynamicCORSMiddleware's pattern exactly.

    Returns the refreshed limit in bytes.
    """
    global _limit_cache

    now = time.monotonic()
    cached_at, cached_bytes = _limit_cache
    if now - cached_at < _LIMIT_CACHE_TTL and cached_bytes > 0:
        return cached_bytes

    try:
        from app.core.db import async_session
        from app.core.persistent_config import UPLOAD_MAX_SIZE_MB

        async with async_session() as db:
            mb = await UPLOAD_MAX_SIZE_MB.get(db)

        limit_bytes = mb * 1024 * 1024
    except Exception:  # broad: dynamic UPLOAD_MAX_SIZE_MB read can fail during startup/test isolation; fall back to cached/default limit
        # Cache unavailable (startup, test isolation) — keep current or use fallback
        limit_bytes = cached_bytes or _FALLBACK_LIMIT_BYTES

    _limit_cache = (now, limit_bytes)
    return limit_bytes


class RequestBodyLimitMiddleware:
    """Enforce body size limit on both Content-Length and chunked-encoding requests.

    The limit is resolved per-request from the cached PersistentConfig value
    (BUG-007).  ``max_bytes`` passed at construction is used only as the
    initial fallback until the first async cache refresh completes.

    GAP-001: non-upload routes get DEFAULT_BODY_LIMIT_BYTES (10 MB); upload
    and reupload routes get the full UPLOAD_MAX_SIZE_MB limit.
    """

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app = app
        # Seed the sync fallback with the boot-time env value so the first
        # request before the async cache warms up uses the configured default.
        global _limit_cache
        _limit_cache = (0.0, max_bytes)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Resolve limit per-request (async cache refresh, TTL 30 s).
        # _refresh_limit_cache populates the sync _limit_cache; _get_upload_limit
        # reads it.  Per GAP-001, non-upload routes use DEFAULT_BODY_LIMIT_BYTES
        # as the route_override so the large upload limit never applies to them.
        await _refresh_limit_cache()

        path = scope.get("path", "")
        method = scope.get("method", "")
        if _is_upload_route(path, method):
            # Upload/reupload: use the admin-configurable limit (500 MB default)
            max_bytes = _get_upload_limit()
        else:
            # All other routes: small default cap (10 MB)
            max_bytes = _get_upload_limit(route_override=DEFAULT_BODY_LIMIT_BYTES)

        # Fast path: Content-Length header present — reject before reading the body
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                pass  # Malformed Content-Length — let downstream handle it
            else:
                if length > max_bytes:
                    response = _too_large_response(max_bytes)
                    await response(scope, receive, send)
                    return

        # Stream-counting path: chunked Transfer-Encoding or missing Content-Length.
        # Wrap the receive callable to count bytes as they arrive.
        total_read = 0
        limit_exceeded = False

        async def limited_receive() -> dict:
            nonlocal total_read, limit_exceeded
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                total_read += len(body)
                if total_read > max_bytes:
                    limit_exceeded = True
                    # Return an empty final chunk so the app sees EOF
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def sending(message: dict) -> None:
            if limit_exceeded and message.get("type") == "http.response.start":
                # Override the response with 413 before headers are sent
                error_response = _too_large_response(max_bytes)
                await error_response(scope, receive, send)
                return
            if not limit_exceeded:
                await send(message)

        await self.app(scope, limited_receive, sending)
