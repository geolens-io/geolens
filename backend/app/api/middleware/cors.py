"""Dynamic CORS middleware that reads allowed origins from PersistentConfig."""

import time

from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# In-memory cache to avoid a DB pool checkout on every CORS request.
_origins_cache: tuple[float, set[str]] = (0.0, set())
_ORIGINS_CACHE_TTL = 30  # seconds — matches PersistentConfig cache TTL


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """CORS middleware that dynamically resolves allowed origins from PersistentConfig.

    Unlike static CORSMiddleware, this reads CORS_ALLOWED_ORIGINS on each request
    (cached in-memory for 30s). Changes take effect without restart.
    """

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")

        # No origin header -- not a CORS request, pass through
        if not origin:
            return await call_next(request)

        # Resolve allowed origins (in-memory cache avoids pool checkout)
        allowed = await self._is_origin_allowed(origin)

        if not allowed:
            # Origin not permitted -- pass through without CORS headers
            return await call_next(request)

        # Preflight (OPTIONS)
        if request.method == "OPTIONS":
            response = Response(status_code=status.HTTP_200_OK)
            self._set_cors_headers(response, origin)
            return response

        # Normal request -- call downstream, add CORS headers to response
        response = await call_next(request)
        self._set_cors_headers(response, origin)
        return response

    async def _is_origin_allowed(self, origin: str) -> bool:
        """Check if the origin is in the CORS allowed origins list."""
        global _origins_cache

        now = time.monotonic()
        cached_at, cached_origins = _origins_cache
        if now - cached_at < _ORIGINS_CACHE_TTL:
            return origin in cached_origins

        # Cache miss — need a DB session
        from app.core.db import async_session
        from app.core.persistent_config import CORS_ALLOWED_ORIGINS

        async with async_session() as db:
            raw = await CORS_ALLOWED_ORIGINS.get(db)

        if not raw:
            _origins_cache = (now, set())
            return False

        # Parse comma-separated origins.
        # Wildcard is rejected — credentials=true requires explicit origins.
        origins = {o.strip() for o in raw.split(",") if o.strip()}
        if "*" in origins:
            _origins_cache = (now, set())
            return False

        _origins_cache = (now, origins)
        return origin in origins

    @staticmethod
    def _set_cors_headers(response: Response, origin: str) -> None:
        """Add standard CORS headers to the response."""
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, Accept, X-Api-Key, X-Embed-Token"
        )
        response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"
        response.headers["Access-Control-Max-Age"] = "3600"
