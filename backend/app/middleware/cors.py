"""Dynamic CORS middleware that reads allowed origins from PersistentConfig."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """CORS middleware that dynamically resolves allowed origins from PersistentConfig.

    Unlike static CORSMiddleware, this reads CORS_ALLOWED_ORIGINS on each request
    (cached for 30s via PersistentConfig). Changes take effect without restart.
    """

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")

        # No origin header -- not a CORS request, pass through
        if not origin:
            return await call_next(request)

        # Resolve allowed origins from PersistentConfig (cached 30s)
        allowed = await self._is_origin_allowed(origin)

        if not allowed:
            # Origin not permitted -- pass through without CORS headers
            return await call_next(request)

        # Preflight (OPTIONS)
        if request.method == "OPTIONS":
            response = Response(status_code=200)
            self._set_cors_headers(response, origin)
            return response

        # Normal request -- call downstream, add CORS headers to response
        response = await call_next(request)
        self._set_cors_headers(response, origin)
        return response

    async def _is_origin_allowed(self, origin: str) -> bool:
        """Check if the origin is in the CORS allowed origins list."""
        from app.database import async_session
        from app.persistent_config import CORS_ALLOWED_ORIGINS

        async with async_session() as db:
            raw = await CORS_ALLOWED_ORIGINS.get(db)

        if not raw:
            return False

        # Parse comma-separated origins
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return "*" in origins or origin in origins

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
