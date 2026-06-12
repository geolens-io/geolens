"""Request body size limit middleware.

Rejects requests whose body exceeds the configured maximum, returning
413 Payload Too Large. Handles both Content-Length and chunked
Transfer-Encoding requests via stream byte counting.

BUG-007 (Phase 1181): The effective limit is resolved PER-REQUEST from the
cached PersistentConfig value instead of the boot-time env value, so an
admin-raised UPLOAD_MAX_SIZE_MB takes effect without a process restart.

GAP-001 (Phase 1184): Per-route body cap. Non-upload routes get a small
default cap (DEFAULT_BODY_LIMIT_BYTES = 10 MB). Upload/reupload routes use
the admin-configurable UPLOAD_MAX_SIZE_MB (500 MB default) resolved via
_get_upload_limit(). Upload routes are detected by path-prefix match against
UPLOAD_PATH_PREFIXES; any request whose normalised path starts with one of
those prefixes uses the large upload limit, all others use the small default.

GAP-001 fix: the app runs with root_path="/api", but every deployment fronts
it with a proxy that STRIPS the /api prefix before the request reaches the
ASGI app (prod nginx `rewrite ^/api/(.*) /$1`; dev Vite proxy
`rewrite: p.replace(/^\\/api/, '')`). So scope["path"] is the un-prefixed
form (/ingest/upload) in real deployments, and matching against a literal
/api/ingest/upload prefix never fired — every upload was silently capped at
the 10 MB default. _is_upload_route now normalises away the optional /api
prefix so the large-upload limit applies whether or not the proxy stripped it.

The resolution helper `_get_upload_limit` accepts a `route_override` seam:

    route_override or _get_upload_limit() or _FALLBACK_LIMIT_BYTES

`route_override=DEFAULT_BODY_LIMIT_BYTES` is passed for non-upload routes.
"""

import time
from typing import Any

from starlette.responses import JSONResponse

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

# GAP-001: route prefixes — AFTER the /api proxy prefix is stripped (see
# _strip_api_prefix) — that should receive the large upload limit. Matched as
# prefixes against the normalised request path:
#   /ingest/upload           — new-file upload (router prefix /ingest, path /upload*)
#   /ingest/upload/presigned — presigned upload initiation + completion
# Reupload paths (/datasets/{id}/reupload*) carry an embedded {id} segment that a
# plain prefix can't express, so they are matched separately in _is_upload_route.
# Lowercase; _is_upload_route lowercases the request path before comparing.
UPLOAD_PATH_PREFIXES: tuple[str, ...] = ("/ingest/upload",)


def _strip_api_prefix(path: str) -> str:
    """Strip the optional ``/api`` root_path prefix from *path*.

    The app is mounted with ``root_path="/api"``, but every deployment fronts it
    with a proxy that removes ``/api`` before the request reaches the ASGI app
    (prod nginx ``rewrite ^/api/(.*) /$1``; dev Vite proxy
    ``rewrite: p.replace(/^\\/api/, '')``). So ``scope["path"]`` is the
    un-prefixed form in production, while a direct hit on the API container keeps
    the prefix. Normalising both to the un-prefixed form lets the upload-route
    classifier fire in every case. Expects an already-lowercased path.
    """
    if path.startswith("/api/"):
        return path[len("/api") :]  # drop "/api", keep the leading slash
    if path == "/api":
        return "/"
    return path


def _is_upload_route(path: str) -> bool:
    """Return True if *path* is an upload or reupload endpoint.

    GAP-001: upload routes need the large UPLOAD_MAX_SIZE_MB limit; all other
    routes get DEFAULT_BODY_LIMIT_BYTES.  The match is deliberately liberal on
    /datasets/ — only reupload paths POST a large body, but the other dataset
    paths post small JSON.  Restricting /datasets/ further would require parsing
    the path segments; accepting a slightly wider match is safe because the body
    check is still bounded by UPLOAD_MAX_SIZE_MB (500 MB).

    The optional ``/api`` prefix is normalised away first (see _strip_api_prefix)
    so the classifier fires on the proxy-stripped paths real deployments produce,
    not just on a direct hit against the API container.
    """
    norm = _strip_api_prefix(path.lower())
    # /ingest/upload* — all upload-initiation paths (new upload, presigned, complete)
    if any(norm.startswith(prefix) for prefix in UPLOAD_PATH_PREFIXES):
        return True
    # /datasets/{id}/reupload* — dataset reupload paths
    # Match the literal "/reupload" segment inside a /datasets/... path.
    if norm.startswith("/datasets/") and "/reupload" in norm:
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
        if _is_upload_route(path):
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
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                f"Request body too large. "
                                f"Maximum allowed size is {max_bytes} bytes."
                            )
                        },
                    )
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
                error_response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large. "
                            f"Maximum allowed size is {max_bytes} bytes."
                        )
                    },
                )
                await error_response(scope, receive, send)
                return
            if not limit_exceeded:
                await send(message)

        await self.app(scope, limited_receive, sending)
