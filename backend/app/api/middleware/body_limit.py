"""Request body size limit middleware.

Rejects requests whose body exceeds the configured maximum, returning
413 Payload Too Large. Handles both Content-Length and chunked
Transfer-Encoding requests via stream byte counting.

BUG-007 (Phase 1181): The effective limit is resolved PER-REQUEST from the
cached PersistentConfig value instead of the boot-time env value, so an
admin-raised UPLOAD_MAX_SIZE_MB takes effect without a process restart.

The resolution helper `_get_upload_limit` is intentionally kept as a plain
module-level function with a clear seam for Phase 1184's per-route override:

    route_override or _get_upload_limit() or _FALLBACK_LIMIT_BYTES

Phase 1184 can pass `route_override` (e.g. a smaller cap for non-upload
endpoints) without touching any other middleware logic.
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


def _get_upload_limit(route_override: int | None = None) -> int:
    """Return the effective upload limit in bytes.

    Resolution order (Phase 1184 seam):
        1. route_override  — per-route cap (Phase 1184 will supply this)
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
    except Exception:
        # Cache unavailable (startup, test isolation) — keep current or use fallback
        limit_bytes = cached_bytes or _FALLBACK_LIMIT_BYTES

    _limit_cache = (now, limit_bytes)
    return limit_bytes


class RequestBodyLimitMiddleware:
    """Enforce body size limit on both Content-Length and chunked-encoding requests.

    The limit is resolved per-request from the cached PersistentConfig value
    (BUG-007).  ``max_bytes`` passed at construction is used only as the
    initial fallback until the first async cache refresh completes.
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
        # reads it.  Keeping them separate lets Phase 1184 inject a route_override
        # into _get_upload_limit without touching this call site.
        await _refresh_limit_cache()
        max_bytes = _get_upload_limit()

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
