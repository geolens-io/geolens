"""Dynamic CORS middleware that reads allowed origins from PersistentConfig."""

import re
import time

from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.middleware.liveness import is_liveness_request
from app.platform.request_credential import header_api_key_evaluated
from app.standards.ogc.utils import standards_api_path

# In-memory cache to avoid a DB pool checkout on every CORS request.
_origins_cache: tuple[float, set[str]] = (0.0, set())
_ORIGINS_CACHE_TTL = 30  # seconds — matches PersistentConfig cache TTL

# Native catalog routes with the same anonymous, read-only
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
# so HEAD and POST 405 here, which is what happens when a preflight promises a
# method the route refuses.
_STANDARDS_PUBLIC_METHODS = "GET, HEAD, POST, OPTIONS"
_SEARCH_PUBLIC_METHODS = "GET, OPTIONS"

# A COPC or 3D Tiles file route checks read access before anything else it
# answers, and passes an anonymous caller only for a public, published dataset.
# ``_dispatch`` adds the wildcard only to the statuses those routes give after
# that check (a success, a failed precondition, an unsatisfiable range or a
# storage failure), so a private dataset's 404 stays identical to an unknown
# one's. A 429 also gets it: the COPC limits refuse a read before the dataset
# is looked up and count per client, so every id gets the same one. The
# preflight is answered by path, the same for every id.
_PUBLIC_ASSET_PATHS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"/datasets/[^/]+/copc/[^/]+/[^/]+\.copc\.laz"),
        "GET, HEAD, OPTIONS",
    ),
    (re.compile(r"/datasets/[^/]+/tiles3d/.+"), "GET, OPTIONS"),
)
_ASSET_WILDCARD_STATUSES = frozenset({200, 206, 304, 412, 416, 429, 502})

# Request headers no credential rides on: the CORS-safelisted names, and the
# range and conditional headers an asset or download answers.
_SAFE_REQUEST_HEADERS = (
    "Content-Type",
    "Accept",
    "Accept-Language",
    "Content-Language",
)
_CONDITIONAL_HEADERS = ("Range", "If-Range", "If-None-Match", "If-Match")
_SAFE_REQUEST_LOWER = frozenset(h.lower() for h in _SAFE_REQUEST_HEADERS)
_CONDITIONAL_LOWER = frozenset(h.lower() for h in _CONDITIONAL_HEADERS)

_CREDENTIAL_HEADERS = ("authorization", "cookie", "x-api-key", "x-embed-token")
_CREDENTIAL_QUERY_PARAMS = ("api_key", "embed_token")

# A script that sends a key in the X-Api-Key header already holds it, so CORS
# has no ambient credential to guard on that lane and any origin may read the
# answer. Cookies, bearer tokens, embed tokens and query-string credentials are
# ambient or leak-prone and never qualify. A preflight can't carry the key, so
# it qualifies when it asks for x-api-key and only these headers besides.
_HEADER_KEY_ALLOWED_HEADER_NAMES = (
    "X-Api-Key",
    *_SAFE_REQUEST_HEADERS,
    "Idempotency-Key",
    "Idempotency-Attempt",
    *_CONDITIONAL_HEADERS,
)
_HEADER_KEY_ALLOWED_HEADERS = ", ".join(_HEADER_KEY_ALLOWED_HEADER_NAMES)
_HEADER_KEY_ALLOWED_LOWER = frozenset(
    h.lower() for h in _HEADER_KEY_ALLOWED_HEADER_NAMES
)

_ALL_METHODS = "GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS"

# What every policy lets a script read. The anonymous public answer omits the
# two headers only authenticated routes send.
_PUBLIC_EXPOSE_HEADERS = (
    "Link, Content-Crs, Content-Language, Retry-After, "
    "ETag, Content-Range, Accept-Ranges, "
    "X-GeoLens-Source-Dataset-Count, X-GeoLens-Serialized-Dataset-Count, "
    "X-GeoLens-Excluded-Dataset-Count, "
    "X-GeoLens-Metadata-Fallback-Dataset-Count, "
    "X-GeoLens-Metadata-Fallback-Fields, "
    # Says whether numberMatched is exact or the planner's
    # estimate on a filtered feature page.
    "X-GeoLens-Number-Matched, "
    # The feature delete route's committed tile_cache_version; a 204
    # has no body to carry it in, so a cross-origin caller needs it
    # exposed to read it at all.
    "X-GeoLens-Tile-Cache-Version"
)
_EXPOSE_HEADERS = "X-Total-Count, Content-Disposition, " + _PUBLIC_EXPOSE_HEADERS

# The answer depends on the Origin and on which credential headers came, so a
# cache keyed on the URL alone must not replay one variant for another.
_VARY_HEADERS = ("Origin", "Authorization", "X-Api-Key", "X-Embed-Token")


def _merge_vary(response: Response, *names: str) -> None:
    """Declare that this response was derived from the request headers ``names``.

    The answer depends on origin, so a cache keyed without
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

    present = {token.lower() for token in tokens}
    tokens.extend(name for name in names if name.lower() not in present)

    # Assignment (not ``append``) so duplicate field-lines collapse into one.
    response.headers["Vary"] = ", ".join(tokens)


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """CORS middleware that dynamically resolves allowed origins from PersistentConfig.

    Unlike static CORSMiddleware, this reads CORS_ALLOWED_ORIGINS on each request
    (cached in-memory for 30s). Changes take effect without restart.
    """

    async def dispatch(self, request: Request, call_next):
        response = await self._dispatch(request, call_next)
        # One call at the one exit: every representation this middleware returns is
        # origin-dependent, and two of the four policy-writer branches return without
        # calling it.
        _merge_vary(response, *_VARY_HEADERS)
        return response

    async def _dispatch(self, request: Request, call_next) -> Response:
        # The liveness probe gets no CORS policy, and more
        # importantly triggers no policy LOOKUP — `_is_origin_allowed` reads
        # CORS_ALLOWED_ORIGINS from the DB when its 60s cache expires, so a
        # probe carrying an Origin header would block on the DB on the one
        # request that must not depend on it.
        if is_liveness_request(request.scope):
            return await call_next(request)

        origin = request.headers.get("origin")

        if not origin:
            return await call_next(request)

        allowed = await self._is_origin_allowed(origin)

        if not allowed:
            if self._is_header_key_request(request):
                return await self._answer_header_key(request, call_next)

            # Standards discovery and anonymous catalog search are meant to
            # be usable by anonymous browser clients by default. A wildcard
            # is safe here since credential-bearing requests are excluded
            # and Access-Control-Allow-Credentials is never emitted.
            allow_methods = self._anonymous_public_methods(request)
            if allow_methods is None:
                return await call_next(request)
            response = await self._answer(request, call_next)
            if (
                self._public_asset_methods(request) is not None
                and response.status_code not in _ASSET_WILDCARD_STATUSES
            ):
                return response
            self._set_public_cors_headers(response, request, allow_methods)
            return response

        response = await self._answer(request, call_next)
        self._set_cors_headers(response, origin)
        return response

    @staticmethod
    async def _answer(request: Request, call_next) -> Response:
        """An OPTIONS request's empty 200, or the route's own response."""
        if request.method == "OPTIONS":
            return Response(status_code=status.HTTP_200_OK)
        return await call_next(request)

    async def _answer_header_key(self, request: Request, call_next) -> Response:
        """Serve a header-key request; any origin may read what its key unlocked.

        A response gets the wildcard only when the auth layer looked the key up,
        so a made-up key opens no route that never reads one.
        """
        if self._is_preflight(request):
            response = Response(status_code=status.HTTP_200_OK)
            self._set_header_key_cors_headers(response)
            return response
        # Everything below builds its own Request from this scope, so dropping
        # the header here keeps a browser's cookie from authenticating anything.
        request.scope["headers"] = [
            (name, value)
            for name, value in request.scope["headers"]
            if name != b"cookie"
        ]
        # Shared with the auth layer, which marks it when it reads the key.
        request.scope.setdefault("state", {})
        response = await call_next(request)
        if header_api_key_evaluated(request.scope):
            self._set_header_key_cors_headers(response)
        return response

    async def _is_origin_allowed(self, origin: str) -> bool:
        global _origins_cache

        now = time.monotonic()
        cached_at, cached_origins = _origins_cache
        if now - cached_at < _ORIGINS_CACHE_TTL:
            return origin in cached_origins

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

        HEAD and the conditional/range headers are listed because the COG
        download route serves HEAD, byte ranges, ``ETag`` and ``If-Range``;
        without them a preflight is refused and JS couldn't read
        ``ETag``/``Content-Range`` (unexposed = invisible). ``Range`` is listed
        despite Fetch's safelist since pairing with ``If-Range`` forces a
        preflight anyway; ``Content-Length`` is NOT listed since it's already
        safelisted. ``tests/test_cors_range_headers_1540.py`` reads the download
        route's own source and fails if either list here misses a header.

        Echoes the caller's origin, so ``dispatch`` merges
        ``Vary: Origin`` onto every response, not just this one.
        """
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = _ALL_METHODS
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, Accept, X-Api-Key, X-Embed-Token, "
            "X-Config-Preview-Token, Idempotency-Key, Idempotency-Attempt, "
            "Range, If-Range, If-None-Match, If-Match"
        )
        response.headers["Access-Control-Expose-Headers"] = _EXPOSE_HEADERS
        response.headers["Access-Control-Max-Age"] = "3600"

    @staticmethod
    def _requested_headers(request: Request) -> set[str]:
        """The lower-cased header names a preflight asks to send."""
        return {
            value.strip().lower()
            for value in request.headers.get(
                "access-control-request-headers", ""
            ).split(",")
            if value.strip()
        }

    @staticmethod
    def _is_preflight(request: Request) -> bool:
        return request.method == "OPTIONS" and bool(
            request.headers.get("access-control-request-method")
        )

    @classmethod
    def _is_header_key_request(cls, request: Request) -> bool:
        """Whether this request is on the header-key lane, preflight included.

        Under ``/auth/`` only ``/auth/me`` takes a keyed preflight: the rest are
        sign-in, registration and session routes, which no key script calls.
        """
        if cls._is_preflight(request):
            path = cls._request_path(request)
            if path.startswith("/auth/") and path.rstrip("/") != "/auth/me":
                return False
            requested = cls._requested_headers(request)
            return "x-api-key" in requested and requested <= _HEADER_KEY_ALLOWED_LOWER
        if any(param in request.query_params for param in _CREDENTIAL_QUERY_PARAMS):
            return False
        return bool(request.headers.get("x-api-key")) and not (
            request.headers.get("authorization") or request.headers.get("x-embed-token")
        )

    @staticmethod
    def _set_header_key_cors_headers(response: Response) -> None:
        """Answer the header-key lane: any origin, never with credentials."""
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = _ALL_METHODS
        response.headers["Access-Control-Allow-Headers"] = _HEADER_KEY_ALLOWED_HEADERS
        response.headers["Access-Control-Expose-Headers"] = _EXPOSE_HEADERS
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
    def _public_asset_methods(cls, request: Request) -> str | None:
        request_path = cls._request_path(request)
        for pattern, allow_methods in _PUBLIC_ASSET_PATHS:
            if pattern.fullmatch(request_path):
                return allow_methods
        return None

    @classmethod
    def _anonymous_public_methods(cls, request: Request) -> str | None:
        """Return the ``Allow-Methods`` value for an anonymous wildcard answer.

        ``None`` means the request doesn't qualify, falling through to
        the explicit-origin policy or no CORS headers. Each surface
        advertises only the methods its routes answer: standards routes
        GET/HEAD, plus POST on ``/stac/search``; search GET; the asset
        files their own set, with the range and conditional request headers
        allowed in the preflight. Everything after the surface check is shared
        deliberately: the credential exclusion and safelisted-header
        check make a wildcard safe, and a new surface must not opt out.
        """
        request_path = cls._request_path(request)
        standards_path = standards_api_path(request_path)
        asset_methods = cls._public_asset_methods(request)
        asset_headers: frozenset[str] = frozenset()
        stac_search = False
        if standards_path is not None:
            allow_methods = _STANDARDS_PUBLIC_METHODS
            permitted = {"GET", "HEAD"}
            stac_search = standards_path.rstrip("/") == "/stac/search"
        elif request_path in _PUBLIC_SEARCH_PATHS:
            allow_methods = _SEARCH_PUBLIC_METHODS
            permitted = {"GET"}
        elif asset_methods is not None:
            allow_methods = asset_methods
            permitted = {m.strip() for m in asset_methods.split(",")} - {"OPTIONS"}
            asset_headers = _CONDITIONAL_LOWER
        else:
            return None

        requested_method = request.headers.get(
            "access-control-request-method", request.method
        ).upper()
        if requested_method not in permitted and not (
            requested_method == "POST" and stac_search
        ):
            return None

        # The anonymous wildcard never covers a credential, preflights included.
        if any(request.headers.get(header) for header in _CREDENTIAL_HEADERS):
            return None
        if any(param in request.query_params for param in _CREDENTIAL_QUERY_PARAMS):
            return None
        if not cls._requested_headers(request) <= _SAFE_REQUEST_LOWER | asset_headers:
            return None
        return allow_methods

    @staticmethod
    def _set_public_cors_headers(
        response: Response, request: Request, allow_methods: str
    ) -> None:
        """Answer an anonymous public request with the credential-free policy.

        Expose-Headers is shared across the public surfaces and names the
        unsafelisted headers they send, such as ``Link``, ``Retry-After``
        on a 429, and the range validators an asset file answers with.

        A ``*`` answer doesn't strictly need ``Vary: Origin``,
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
        response.headers["Access-Control-Expose-Headers"] = _PUBLIC_EXPOSE_HEADERS
        response.headers["Access-Control-Max-Age"] = "3600"
