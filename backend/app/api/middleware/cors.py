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

# fix(#1596): native catalog routes that carry the same anonymous, read-only
# contract as the standards surface and so earn the same wildcard answer.
#
# Enumerated here rather than by widening ``standards_api_path``: that
# classifier is shared with the error and OpenAPI contracts, and adding
# ``/search`` to it would move these routes onto the OGC error shape as a side
# effect of a CORS fix. Enumerated rather than matched by prefix because
# ``/search/saved`` sits under the same router and requires an authenticated
# user — a prefix over ``/search`` would hand it the wildcard too.
#
# Both handlers run ``apply_visibility_filter`` and treat an anonymous caller
# as having no roles, so a wildcard response returns exactly the public
# catalog. ``tests/test_search_cors_1596.py`` holds each listed path to a
# GET-only route with no authenticated-user dependency.
#
# A tuple rather than a set because tests parametrize over it: string hashing
# is salted per process, so a set's iteration order differs between xdist
# workers and collection no longer matches across them.
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

    fix(#1602). What this middleware answers depends on the origin that asked,
    so a cache that stores one answer under a key omitting ``Origin`` can
    replay it to a different origin. The shipped
    ``frontend/nginx.conf`` serves ``location /api/`` with ``proxy_cache off``,
    so this is not a leak on a default deployment; it is what an operator
    fronting the API with their own CDN needs in order not to hand
    ``Access-Control-Allow-Origin: https://a.example`` to ``b.example``.

    Merged rather than assigned. ``standard_response_headers`` already sets
    ``Vary: Accept-Language`` on the search and standards responses, and
    ``GZipMiddleware`` adds ``Accept-Encoding``; overwriting either would buy
    the CORS variance by losing the content-negotiation one, which is the same
    defect pointed at a different header. Tokens are compared case-insensitively
    because field names are, and an already-present ``Origin`` is left exactly
    as the route spelled it.

    Applied to every response the middleware returns, not only the two that
    carry a policy. fix(#1602 codex r1): a response produced for a rejected
    origin, or for a request with no ``Origin`` header at all, is the same URL
    that answers a permitted origin with ``Access-Control-Allow-Origin``. A CDN
    that stores the header-less variant under an origin-less key then replays
    it to a browser origin the operator allowed, and the browser blocks a
    request the configured policy permits. That direction fails closed rather
    than leaking, but a blocked request is still a broken deployment, and it is
    the deployment this header exists for.
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
        # fix(#1602 codex r1): one call, at the one exit. Every representation
        # this middleware can return is origin-dependent, including the ones it
        # writes no policy onto, so the declaration belongs here rather than in
        # the policy writers — where a branch that returns without calling one
        # (and two of the four do) would silently skip it.
        _merge_vary_origin(response)
        return response

    async def _dispatch(self, request: Request, call_next) -> Response:
        # fix(#1778 codex r7): the liveness probe gets no CORS policy and, more
        # to the point, triggers no policy LOOKUP. `_is_origin_allowed` reads
        # CORS_ALLOWED_ORIGINS out of the database whenever its 60s cache has
        # expired, so a probe that happens to carry an Origin header would
        # block on the database on the one request that must not depend on it.
        # A probe is not a browser resource; it needs no Access-Control header,
        # and this middleware already returns without one whenever the origin
        # is not permitted.
        if is_liveness_request(request.scope):
            return await call_next(request)

        origin = request.headers.get("origin")

        # No origin header -- not a CORS request, pass through
        if not origin:
            return await call_next(request)

        # Resolve allowed origins (in-memory cache avoids pool checkout)
        allowed = await self._is_origin_allowed(origin)

        if not allowed:
            # Standards discovery and the anonymous catalog search routes are
            # intentionally usable by anonymous browser clients on a default
            # deployment.  A wildcard response is safe here because
            # credential-bearing requests are excluded and
            # Access-Control-Allow-Credentials is not emitted. Every other
            # native application route retains the explicit-origin,
            # credentialed policy below.
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

        fix(#1602): this policy echoes the caller's origin, so the response it
        is written onto is not reusable for a different one. The declaration
        itself is not made here — ``dispatch`` merges ``Vary: Origin`` onto
        every response, including the ones no policy is written onto.
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

        ``None`` means the request does not qualify and falls through to the
        explicit-origin policy (or to no CORS headers at all).

        The two public surfaces answer different method sets, so the value is
        resolved per surface rather than fixed: standards routes serve GET,
        HEAD and a POST on ``/stac/search``; the search routes in
        ``_PUBLIC_SEARCH_PATHS`` serve GET only. Advertising more than the
        route answers is fix(#1470) — a browser was told HEAD was allowed and
        then got a 405.

        Everything after the surface check is shared, and deliberately so: the
        credential exclusion and the safelisted-header check are what make a
        wildcard safe, and a new surface must not be able to opt out of them.
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

        # Never grant wildcard browser access to a request that can carry an
        # application identity.  This covers actual requests and preflights.
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

        The Expose-Headers list is shared across both public surfaces. It
        covers everything the search routes set that a browser would otherwise
        hide: ``standard_response_headers`` sets ``Vary``, ``Content-Language``
        and ``Link``, and ``Link`` — which carries the next/prev pagination
        hrefs — is the only one of those that is not CORS-safelisted. Search
        sets no count header. It does rate-limit (the per-IP semantic-search
        limit on ``/search/datasets`` and the global limiter), and
        ``_rate_limit_handler`` in ``api/main.py`` puts ``Retry-After`` on that
        429; ``Retry-After`` is not safelisted, so it is listed here and on the
        credentialed policy too, or a cross-origin caller sees the 429 and
        cannot read the retry window (codex on #1601).

        fix(#1602): a ``*`` answer does not strictly need ``Vary: Origin``,
        since every origin gets the same value, but this path shares a URL with
        the credentialed policy and therefore a cache entry, and a stored
        wildcard is indistinguishable from a stored echoed origin once it is in
        the cache. ``dispatch`` puts the header on every response it returns,
        so no writer here has to remember to.
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
