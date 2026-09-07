"""Dynamic CORS middleware that reads allowed origins from PersistentConfig."""

import time

from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.middleware.liveness import is_liveness_request
from app.standards.ogc.utils import standards_api_path

# In-memory cache to avoid a DB pool checkout on every CORS request.
_origins_cache: tuple[float, set[str]] = (0.0, set())
_ORIGINS_CACHE_TTL = 30  # seconds — matches PersistentConfig cache TTL

# fix(#1596): native catalog routes with the same anonymous, read-only
# contract as the standards surface get the same wildcard CORS answer.
# Enumerated, not matched by widening ``standards_api_path`` (shared
# with error/OpenAPI contracts) or by prefix (``/search/saved`` needs
# auth). Both handlers run ``apply_visibility_filter`` treating
# anonymous as no roles, so the wildcard returns exactly the public
# catalog (``tests/test_search_cors_1596.py`` pins GET-only, no auth).
# Tuple, not set: set iteration order is salted per process, so tests
# parametrizing over it wouldn't match across xdist workers.
_PUBLIC_SEARCH_PATHS: tuple[str, ...] = (
    "/search/datasets",
    "/search/datasets/",
    "/search/facets",
    "/search/facets/",
)

# What each public surface actually answers. Search is registered GET-only, and
# the derived-HEAD pass in ``api/main.py`` is keyed on ``standards_api_path``,
# so HEAD and POST 405 here — fix(#1470) is the record of what happens when a
# preflight promises a method the route refuses.
_STANDARDS_PUBLIC_METHODS = "GET, HEAD, POST, OPTIONS"
_SEARCH_PUBLIC_METHODS = "GET, OPTIONS"


def _merge_vary_origin(response: Response) -> None:
    """Declare that this response was derived from the request's ``Origin``.

    fix(#1602): the answer depends on origin, so a cache keyed without
    ``Origin`` could replay one origin's CORS headers to another (the
    shipped nginx config runs ``proxy_cache off``, so this is for an
    operator fronting the API with their own CDN). Merged, not assigned,
    since ``standard_response_headers``/``GZipMiddleware`` already set
    ``Vary``; overwriting would trade one variance for another.

    Applied to every response, not just the two carrying a policy: a
    rejected-origin or no-``Origin`` response shares a URL with a
    permitted-origin response, so without ``Vary: Origin`` a CDN could
    cache the header-less variant and replay it to a permitted browser
    origin, which then blocks it — fails closed, but still broken.
    """
    tokens: list[str] = []
    for line in response.headers.getlist("Vary"):
        tokens.extend(token.strip() for token in line.split(",") if token.strip())

    # ``Vary: *`` is an alternative to the token list, not a member of it
    # (RFC 9110: ``Vary = #( field-name ) / "*"``), and it already tells every
    # cache not to reuse the response. Appending to it would only be a syntax
    # error.
    if any(token == "*" for token in tokens):
        return

    if not any(token.lower() == "origin" for token in tokens):
        tokens.append("Origin")

    # Assignment (not ``append``) so duplicate field-lines collapse into one.
    response.headers["Vary"] = ", ".join(tokens)


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """CORS middleware that dynamically resolves allowed origins from PersistentConfig.

    Unlike static CORSMiddleware, this reads CORS_ALLOWED_ORIGINS on each request
    (cached in-memory for 30s). Changes take effect without restart.
    """

    async def dispatch(self, request: Request, call_next):
        response = await self._dispatch(request, call_next)
        # fix(#1602): one call at the one exit. Every representation this
        # middleware returns is origin-dependent, so the declaration
        # belongs here — two of the four policy-writer branches return
        # without calling it, which would silently skip it otherwise.
        _merge_vary_origin(response)
        return response

    async def _dispatch(self, request: Request, call_next) -> Response:
        # fix(#1778): the liveness probe gets no CORS policy, and more
        # importantly triggers no policy LOOKUP — `_is_origin_allowed` reads
        # CORS_ALLOWED_ORIGINS from the DB when its 60s cache expires, so a
        # probe carrying an Origin header would block on the DB on the one
        # request that must not depend on it.
        if is_liveness_request(request.scope):
            return await call_next(request)

        origin = request.headers.get("origin")

        # No origin header -- not a CORS request, pass through
        if not origin:
            return await call_next(request)

        # Resolve allowed origins (in-memory cache avoids pool checkout)
        allowed = await self._is_origin_allowed(origin)

        if not allowed:
            # Standards discovery and anonymous catalog search are meant to
            # be usable by anonymous browser clients by default. A wildcard
            # is safe here since credential-bearing requests are excluded
            # and Access-Control-Allow-Credentials is never emitted.
            allow_methods = self._anonymous_public_methods(request)
            if allow_methods is not None:
                if request.method == "OPTIONS":
                    response = Response(status_code=status.HTTP_200_OK)
                else:
                    response = await call_next(request)
                self._set_public_cors_headers(response, request, allow_methods)
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

        fix(#1540): HEAD, conditional/range headers are here because
        #1528 gave the COG download route HEAD, byte ranges, ``ETag``,
        and ``If-Range`` — without these a preflight was refused and JS
        couldn't read ``ETag``/``Content-Range`` (unexposed = invisible).
        ``Range`` is listed despite Fetch's safelist since pairing with
        ``If-Range`` forces a preflight anyway; ``Content-Length`` is NOT
        listed since it's already safelisted.
        ``tests/test_cors_range_headers_1540.py`` reads the download
        route's own source and fails if either list here misses a header.

        fix(#1602): echoes the caller's origin, so ``dispatch`` merges
        ``Vary: Origin`` onto every response, not just this one.
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
            "Retry-After, "
            "X-GeoLens-Source-Dataset-Count, X-GeoLens-Serialized-Dataset-Count, "
            "X-GeoLens-Excluded-Dataset-Count, "
            "X-GeoLens-Metadata-Fallback-Dataset-Count, "
            "X-GeoLens-Metadata-Fallback-Fields, "
            # fix(#1778): says whether numberMatched is exact or the planner's
            # estimate on a filtered feature page.
            "X-GeoLens-Number-Matched"
        )
        response.headers["Access-Control-Max-Age"] = "3600"

    @staticmethod
    def _request_path(request: Request) -> str:
        """The request path with any ASGI ``root_path`` prefix removed."""
        path = request.scope.get("path", request.url.path)
        root_path = request.scope.get("root_path", "").rstrip("/")
        if root_path and path.startswith(root_path):
            path = path[len(root_path) :] or "/"
        return path

    @classmethod
    def _standards_path(cls, request: Request) -> str | None:
        return standards_api_path(cls._request_path(request))

    @classmethod
    def _anonymous_public_methods(cls, request: Request) -> str | None:
        """Return the ``Allow-Methods`` value for an anonymous wildcard answer.

        ``None`` means the request doesn't qualify, falling through to
        the explicit-origin policy or no CORS headers. Standards routes
        serve GET/HEAD/POST on ``/stac/search``; ``_PUBLIC_SEARCH_PATHS``
        serves GET only — advertising more than the route answers is
        fix(#1470). Everything after the surface check is shared
        deliberately: the credential exclusion and safelisted-header
        check make a wildcard safe, and a new surface must not opt out.
        """
        request_path = cls._request_path(request)
        standards_path = standards_api_path(request_path)
        if standards_path is not None:
            allow_methods = _STANDARDS_PUBLIC_METHODS
            permitted = {"GET", "HEAD"}
            stac_search = standards_path.rstrip("/") == "/stac/search"
        elif request_path in _PUBLIC_SEARCH_PATHS:
            allow_methods = _SEARCH_PUBLIC_METHODS
            permitted = {"GET"}
            stac_search = False
        else:
            return None

        requested_method = request.headers.get(
            "access-control-request-method", request.method
        ).upper()
        if requested_method not in permitted and not (
            requested_method == "POST" and stac_search
        ):
            return None

        # Never grant wildcard access to a request carrying an application
        # identity — covers both actual requests and preflights.
        credential_headers = {
            "authorization",
            "cookie",
            "x-api-key",
            "x-embed-token",
        }
        if any(request.headers.get(header) for header in credential_headers):
            return None
        if "api_key" in request.query_params or "embed_token" in request.query_params:
            return None

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
        if not requested_headers <= allowed_headers:
            return None
        return allow_methods

    @staticmethod
    def _set_public_cors_headers(
        response: Response, request: Request, allow_methods: str
    ) -> None:
        """Answer an anonymous public request with the credential-free policy.

        Expose-Headers is shared across both public surfaces, covering
        what a browser would otherwise hide: ``Vary``/``Content-Language``/
        ``Link`` (only ``Link`` isn't CORS-safelisted), plus
        ``Retry-After`` (also unsafelisted — without it a cross-origin
        caller can't read the retry window on a 429, #1601).

        fix(#1602): a ``*`` answer doesn't strictly need ``Vary: Origin``,
        but this path shares a URL/cache entry with the credentialed
        policy, and a stored wildcard is indistinguishable from a stored
        echoed origin once cached; ``dispatch`` sets the header on every
        response so no writer here has to remember to.
        """
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = allow_methods
        requested_headers = request.headers.get("access-control-request-headers")
        if requested_headers:
            response.headers["Access-Control-Allow-Headers"] = requested_headers
        response.headers["Access-Control-Expose-Headers"] = (
            "Link, Content-Crs, Content-Language, Retry-After, "
            "X-GeoLens-Source-Dataset-Count, X-GeoLens-Serialized-Dataset-Count, "
            "X-GeoLens-Excluded-Dataset-Count, "
            "X-GeoLens-Metadata-Fallback-Dataset-Count, "
            "X-GeoLens-Metadata-Fallback-Fields, "
            # fix(#1778): says whether numberMatched is exact or the planner's
            # estimate on a filtered feature page.
            "X-GeoLens-Number-Matched"
        )
        response.headers["Access-Control-Max-Age"] = "3600"
