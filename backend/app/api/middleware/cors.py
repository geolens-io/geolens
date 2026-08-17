"""Dynamic CORS middleware that reads allowed origins from PersistentConfig."""

import time

from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.standards.ogc.utils import standards_api_path

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
            # Standards discovery and read/search routes are intentionally
            # usable by anonymous browser clients on a default deployment.  A
            # wildcard response is safe here because credential-bearing
            # requests are excluded and Access-Control-Allow-Credentials is not
            # emitted. Native application routes retain the explicit-origin,
            # credentialed policy below.
            if self._is_anonymous_standards_request(request):
                if request.method == "OPTIONS":
                    response = Response(status_code=status.HTTP_200_OK)
                else:
                    response = await call_next(request)
                self._set_public_standards_cors_headers(response, request)
                return response

            # Origin not permitted -- pass through without CORS headers.
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
        """Add standard CORS headers to the response.

        fix(#1540 review P2): HEAD, the conditional/range request headers, and
        the range response headers are all here because #1528 gave
        ``/datasets/{id}/download/cog`` a HEAD, byte ranges, an ``ETag`` and
        ``If-Range``/``If-None-Match`` handling, and a browser client could use
        none of it. A preflight for ``If-Range`` was refused, so a resumable
        cross-origin download never started; and where the request did succeed,
        JavaScript could not read ``ETag`` or ``Content-Range``, because a
        response header not named in ``Access-Control-Expose-Headers`` is not
        merely undocumented — it is invisible to the caller.

        ``Range`` is listed even though the Fetch standard safelists simple
        byte-range values: the safelisting is conditional on the syntax, and a
        request pairing it with ``If-Range`` is preflighted regardless.
        ``Content-Length`` is NOT listed because it is already a safelisted
        response header, and repeating it here would suggest the others are too.

        ``If-Match`` arrived a round later than the rest, and its absence was
        the same defect a second time: the endpoint grew a precondition and this
        list did not learn about it. Remembering to edit both is not a control,
        so ``tests/test_cors_range_headers_1540.py`` now reads the route's own
        source for the conditional headers it evaluates and the response headers
        it sets, and fails if either is missing here. Add a header there and
        this list is what breaks — before a browser console does.
        """
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS"
        )
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, Accept, X-Api-Key, X-Embed-Token, "
            "X-Config-Preview-Token, Range, If-Range, If-None-Match, If-Match"
        )
        response.headers["Access-Control-Expose-Headers"] = (
            "X-Total-Count, Link, Content-Crs, Content-Language, "
            "ETag, Content-Range, Accept-Ranges, Content-Disposition, "
            "X-GeoLens-Source-Dataset-Count, X-GeoLens-Serialized-Dataset-Count, "
            "X-GeoLens-Excluded-Dataset-Count, "
            "X-GeoLens-Metadata-Fallback-Dataset-Count, "
            "X-GeoLens-Metadata-Fallback-Fields"
        )
        response.headers["Access-Control-Max-Age"] = "3600"

    @staticmethod
    def _standards_path(request: Request) -> str | None:
        return standards_api_path(
            request.scope.get("path", request.url.path),
            root_path=request.scope.get("root_path", ""),
        )

    @classmethod
    def _is_anonymous_standards_request(cls, request: Request) -> bool:
        path = cls._standards_path(request)
        if path is None:
            return False

        requested_method = request.headers.get(
            "access-control-request-method", request.method
        ).upper()
        if requested_method not in {"GET", "HEAD"} and not (
            requested_method == "POST" and path.rstrip("/") == "/stac/search"
        ):
            return False

        # Never grant wildcard browser access to a request that can carry an
        # application identity.  This covers actual requests and preflights.
        credential_headers = {
            "authorization",
            "cookie",
            "x-api-key",
            "x-embed-token",
        }
        if any(request.headers.get(header) for header in credential_headers):
            return False
        if "api_key" in request.query_params or "embed_token" in request.query_params:
            return False

        requested_headers = {
            value.strip().lower()
            for value in request.headers.get(
                "access-control-request-headers", ""
            ).split(",")
            if value.strip()
        }
        allowed_headers = {
            "accept",
            "accept-language",
            "content-language",
            "content-type",
        }
        return requested_headers <= allowed_headers

    @staticmethod
    def _set_public_standards_cors_headers(
        response: Response, request: Request
    ) -> None:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, POST, OPTIONS"
        requested_headers = request.headers.get("access-control-request-headers")
        if requested_headers:
            response.headers["Access-Control-Allow-Headers"] = requested_headers
        response.headers["Access-Control-Expose-Headers"] = (
            "Link, Content-Crs, Content-Language, "
            "X-GeoLens-Source-Dataset-Count, X-GeoLens-Serialized-Dataset-Count, "
            "X-GeoLens-Excluded-Dataset-Count, "
            "X-GeoLens-Metadata-Fallback-Dataset-Count, "
            "X-GeoLens-Metadata-Fallback-Fields"
        )
        response.headers["Access-Control-Max-Age"] = "3600"
