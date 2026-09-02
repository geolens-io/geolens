"""Browser refresh-token cookie + CSRF primitives (GH-1302).

The refresh token is the only credential that moves into a cookie. Access
tokens keep travelling as ``Authorization: Bearer`` headers, so the cookie
only ever authenticates the two session-lifecycle routes: ``POST
/auth/refresh``, and ``POST /auth/logout`` as the credential of last resort.
CSRF enforcement is therefore scoped to exactly those cookie-authenticated
requests rather than to every mutator.

Browser mode is negotiated explicitly with the ``X-GeoLens-Auth-Mode: cookie``
request header. Header-sniffing (``Accept`` / ``Sec-Fetch-Mode``) was rejected:
it decides a security-relevant behaviour from values proxies rewrite and
non-browser callers can spoof, and it would silently stop returning the JSON
refresh token to curl/Postman/CI callers that happen to send a browsery
``Accept``. Absent the header every response is byte-identical to the
pre-GH-1302 contract, which is what keeps the CLI and the generated SDKs
working.
"""

import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response, status

from app.core.config import settings

REFRESH_COOKIE_NAME = "geolens_refresh"
CSRF_COOKIE_NAME = "geolens_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
AUTH_MODE_HEADER = "X-GeoLens-Auth-Mode"
COOKIE_AUTH_MODE = "cookie"

# The CSRF cookie must be readable by the SPA (double-submit), so it is NOT
# HttpOnly. It is not a credential: possession alone authenticates nothing.
_CSRF_TOKEN_BYTES = 32


def wants_cookie_auth(request: Request) -> bool:
    """Whether the caller explicitly opted into the browser cookie flow."""
    header = request.headers.get(AUTH_MODE_HEADER, "")
    return header.strip().lower() == COOKIE_AUTH_MODE


def refresh_cookie_path(request: Request) -> str:
    """Externally-visible ``Path=`` scope for the refresh cookie.

    The app runs with ``root_path="/api"`` behind both the dev Vite proxy and
    the production nginx ``location /api/`` block, and neither forwards the
    prefix upstream. Deriving the path from ``root_path`` keeps the cookie
    correctly scoped under any mount point instead of hardcoding ``/api``.

    Scoping to ``/auth`` (rather than ``/``) keeps the cookie off catalog,
    tile, upload, and export traffic entirely: it cannot leak through access
    logs or intermediary proxies on the hot path, and it cannot be replayed
    against any endpoint outside this router.

    fix(#1446): this was ``/auth/refresh``, which was too tight. RFC 6265
    path-matching meant the browser never sent the cookie to ``/auth/logout``,
    so the cookie-authenticated logout path — the one that revokes a session
    whose access token has already expired — could not fire at all in a real
    browser. Widening to the auth router is the trade: the cookie now rides
    same-origin ``/auth/*`` requests (login, me, config, api-keys) instead of
    the refresh route alone, and still never touches the data plane.
    """
    root_path = request.scope.get("root_path", "").rstrip("/")
    return f"{root_path}/auth"


def _secure_cookies() -> bool:
    """SEC-005: same production switch that hides the API docs and sets
    ``https_only`` on SessionMiddleware. Development and test runs have no TLS
    terminator, so a ``Secure`` cookie there would be silently dropped."""
    return settings.is_production


def issue_browser_session(
    response: Response,
    request: Request,
    refresh_token: str,
    expire_days: int,
) -> None:
    """Attach the refresh + CSRF cookies to *response*.

    ``SameSite=Lax``: the only route under the cookie's ``Path`` is a POST, and
    Lax and Strict are identical for a same-origin XHR POST (Lax's extra
    allowance covers top-level GET navigation, which no route here serves). No
    concrete reason to deviate to Strict was found.
    """
    max_age = expire_days * 24 * 60 * 60
    secure = _secure_cookies()
    path = refresh_cookie_path(request)

    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=path,
    )

    csrf_token = secrets.token_urlsafe(_CSRF_TOKEN_BYTES)
    # Path="/" so any tab on the app can read it, whatever route it loaded on.
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_browser_session(response: Response, request: Request) -> None:
    """Expire both cookies. Safe to call when no cookie was ever set.

    Deletion works from any request path: the browser applies a ``Set-Cookie``
    whose name/path/domain match regardless of where the response came from,
    so this can run from ``/auth/logout`` and the OAuth callback alike.
    """
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=refresh_cookie_path(request),
        httponly=True,
        secure=_secure_cookies(),
        samesite="lax",
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        path="/",
        secure=_secure_cookies(),
        samesite="lax",
    )


def read_refresh_cookie(request: Request) -> str | None:
    """The refresh cookie's value, or None when absent or not trustworthy.

    fix(#1446): refuses DUPLICATE cookies of this name outright. An attacker on
    a sibling subdomain who holds their own valid refresh token can toss a
    parent-``Domain`` cookie with this name; the browser then sends both, a
    parser keeps one of the two, and the victim's refresh would rotate
    whichever token won — installing the attacker's session under the victim's
    UI (login CSRF). The attacker can only ADD a shadow, never remove the
    victim's host cookie, so duplicates are the attack's fingerprint: refusing
    them turns account confusion into a one-time re-login prompt.
    """
    if _cookie_occurrences(request, REFRESH_COOKIE_NAME) > 1:
        return None
    return request.cookies.get(REFRESH_COOKIE_NAME)


def _cookie_occurrences(request: Request, name: str) -> int:
    """How many times *name* appears in the raw ``Cookie:`` header.

    ``request.cookies`` is a dict, so it answers "which of the duplicates did
    the parser keep", never "were there duplicates". Only the raw header can
    tell the two apart.
    """
    raw = request.headers.get("cookie", "")
    seen = 0
    for part in raw.split(";"):
        if part.split("=", 1)[0].strip() == name:
            seen += 1
    return seen


def _origin_parts(url: str) -> tuple[str, str, int | None] | None:
    """(scheme, host, effective port), or None when *url* has no usable origin."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not parts.scheme or not host:
        return None
    scheme = parts.scheme.lower()
    # fix(#1446): EFFECTIVE port. A URL that spells out its default port
    # ("https://example.com:443") is the same origin as one that omits it, but
    # a raw string comparison called that a mismatch.
    effective = port if port is not None else {"https": 443, "http": 80}.get(scheme)
    return scheme, host.lower(), effective


def api_path_is_cookie_scoped(request: Request, api_url: str) -> bool:
    """Whether *api_url*'s path is the mount point this cookie is scoped under.

    fix(#1446): same origin is necessary but not sufficient. ``root_path`` is
    fixed at ``/api`` (api/main.py), so the cookie is always scoped to
    ``/api/auth`` — while ``PUBLIC_API_URL`` / ``FRONTEND_API_BASE_URL`` are
    documented as accepting any path form. A deployment mounted at, say,
    ``/geolens-api`` would be handed a cookie the browser never sends back to
    ``/geolens-api/auth/refresh/``, and cookie mode ships no fragment token to
    fall back on, so the session would silently stop refreshing. Mirrors the
    same guard in the SPA's ``cookieAuthAvailable()``.
    """
    root_path = request.scope.get("root_path", "").rstrip("/")
    try:
        configured = urlsplit(api_url).path
    except ValueError:
        return False
    return configured.rstrip("/") == root_path


def is_same_origin(url_a: str, url_b: str) -> bool:
    """Whether two absolute URLs share scheme, host, and effective port.

    Used by the OAuth callback to decide cookie-vs-fragment delivery: a cookie
    it sets is scoped to the host the browser used to reach the API, so it is
    only usable afterwards when the SPA lives on that same origin.

    fix(#1446): both sides are now the deployment's CONFIGURED public URLs
    rather than the live request's host. Deriving one side from the request was
    wrong under any proxy that rewrites Host — the shipped Vite dev proxy sets
    ``changeOrigin: true``, which replaces Host with the API target and keeps
    the browser-facing host only in ``X-Forwarded-Host``, so the check reported
    a mismatch and silently reverted dev to fragment delivery. Comparing two
    configured values needs no trust decision about forwarded headers at all.

    A false answer degrades to the pre-GH-1302 fragment path rather than
    handing the browser a cookie it will never send back — it never locks
    anyone out.
    """
    origin_a = _origin_parts(url_a)
    origin_b = _origin_parts(url_b)
    if origin_a is None or origin_b is None:
        return False
    return origin_a == origin_b


def enforce_csrf(request: Request) -> None:
    """Double-submit check for cookie-authenticated refresh. Raises 403.

    Double-submit was chosen over a bare enforced-custom-header rule because
    this deployment's CORS allowlist is operator-configurable at runtime
    (``CORS_ALLOWED_ORIGINS``, and ``DynamicCORSMiddleware`` emits
    ``Access-Control-Allow-Credentials: true`` for every listed origin). The
    "custom header implies a preflight the attacker cannot pass" guarantee is
    only ever as strong as that list; comparing a value the attacker cannot
    read does not depend on it. It is also directly exercisable by a plain HTTP
    client, with no browser preflight to simulate.
    """
    # fix(#1778): the same duplicate-cookie refusal read_refresh_cookie has had
    # since #1446, applied to the other half of the pair. Double-submit rests
    # entirely on the attacker not knowing the cookie's value (see the docstring
    # above), and a sibling subdomain can CHOOSE that value: set
    # geolens_csrf=KNOWN with a parent Domain, and the browser sends two
    # geolens_csrf cookies. Starlette's parser keeps the last occurrence, and a
    # freshly-set Domain cookie sharing Path=/ sorts after the older host-only
    # one under RFC 6265, so the attacker's value is the one compared. The
    # victim's host-only geolens_refresh is untouched and still single, so
    # read_refresh_cookie accepts it and the request would go through.
    #
    # Refusing on a duplicate turns that into a 403 the victim can clear by
    # signing in again -- the same trade #1446 already accepted for the refresh
    # cookie, where the attacker can likewise force a re-login by planting a
    # shadow. Not fixable by naming alone in dev: the __Host- prefix (which
    # browsers refuse to honour on a Domain cookie) needs TLS, and
    # _secure_cookies() is False without a terminator.
    if _cookie_occurrences(request, CSRF_COOKIE_NAME) > 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )
    header_token = request.headers.get(CSRF_HEADER_NAME)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not header_token or not cookie_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing CSRF token",
        )
    if not secrets.compare_digest(header_token, cookie_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )
