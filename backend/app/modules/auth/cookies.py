"""Browser refresh-token cookie + CSRF primitives (GH-1302).

The refresh token is the only credential that moves into a cookie. Access
tokens keep travelling as ``Authorization: Bearer`` headers, so the cookie
only ever authenticates ``POST /auth/refresh`` and ``POST /auth/logout``
(credential of last resort). CSRF enforcement is scoped to exactly those
requests.

Browser mode is negotiated explicitly via the ``X-GeoLens-Auth-Mode: cookie``
header. Header-sniffing (``Accept``/``Sec-Fetch-Mode``) was rejected: it
decides security-relevant behaviour from values proxies rewrite and
non-browser callers can spoof. Absent the header every response is
byte-identical to the pre-GH-1302 contract, keeping the CLI and generated
SDKs working.
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
    header = request.headers.get(AUTH_MODE_HEADER, "")
    return header.strip().lower() == COOKIE_AUTH_MODE


def refresh_cookie_path(request: Request) -> str:
    """Externally-visible ``Path=`` scope for the refresh cookie.

    The app runs with ``root_path="/api"`` behind both the dev proxy and prod
    nginx, neither of which forwards the prefix upstream — deriving from
    ``root_path`` keeps the cookie scoped correctly under any mount point.

    Scoped to ``/auth`` (not ``/``) so the cookie never touches catalog/tile/
    upload/export traffic — it can't leak through hot-path logs or proxies,
    and can't be replayed outside this router.

    fix(#1446): was ``/auth/refresh``, too tight — RFC 6265 path-matching
    meant the browser never sent the cookie to ``/auth/logout``, so
    cookie-authenticated logout (revoking a session whose access token
    already expired) couldn't fire. Widened to the whole auth router; still
    never touches the data plane.
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

    ``SameSite=Lax``: the only route under the cookie's ``Path`` is a POST,
    and Lax and Strict are identical for a same-origin XHR POST. No reason to
    use Strict was found.
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

    fix(#1446): refuses DUPLICATE cookies of this name — an attacker on a
    sibling subdomain with their own valid refresh token can add a
    parent-``Domain`` cookie of the same name; the browser sends both, a
    parser keeps one, and the victim's refresh could rotate the attacker's
    token (login CSRF). The attacker can only ADD a shadow, never remove the
    victim's host cookie, so duplicates are the attack's fingerprint.
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

    fix(#1446): same origin is necessary but not sufficient — ``root_path``
    is fixed at ``/api``, so the cookie is always scoped to ``/api/auth``,
    while ``PUBLIC_API_URL``/``FRONTEND_API_BASE_URL`` accept any path form.
    A deployment mounted elsewhere would get a cookie the browser never
    sends back, and cookie mode has no fragment fallback, so refresh would
    silently stop. Mirrors the SPA's ``cookieAuthAvailable()``.
    """
    root_path = request.scope.get("root_path", "").rstrip("/")
    try:
        configured = urlsplit(api_url).path
    except ValueError:
        return False
    return configured.rstrip("/") == root_path


def is_same_origin(url_a: str, url_b: str) -> bool:
    """Whether two absolute URLs share scheme, host, and effective port.

    Used by the OAuth callback to decide cookie-vs-fragment delivery: a
    cookie is scoped to the host the browser used to reach the API, so it's
    only usable when the SPA lives on that same origin.

    fix(#1446): both sides are the deployment's CONFIGURED public URLs, not
    the live request's host — deriving from the request broke under any
    proxy that rewrites Host (the Vite dev proxy's ``changeOrigin`` replaces
    Host and keeps the real host only in ``X-Forwarded-Host``), which
    reported a false mismatch and silently reverted dev to fragment delivery.

    A false answer degrades to the pre-GH-1302 fragment path rather than
    handing the browser a cookie it will never send back.
    """
    origin_a = _origin_parts(url_a)
    origin_b = _origin_parts(url_b)
    if origin_a is None or origin_b is None:
        return False
    return origin_a == origin_b


def enforce_csrf(request: Request) -> None:
    """Double-submit check for cookie-authenticated refresh. Raises 403.

    Double-submit over a bare custom-header rule because this deployment's
    CORS allowlist is operator-configurable at runtime
    (``DynamicCORSMiddleware`` emits ``Access-Control-Allow-Credentials:
    true`` per listed origin), and a "custom header implies a preflight"
    guarantee is only as strong as that list. Comparing a value the attacker
    can't read doesn't depend on it, and is directly exercisable by a plain
    HTTP client with no preflight to simulate.
    """
    # fix(#1778): the same duplicate-cookie refusal read_refresh_cookie has
    # had since #1446, applied to the CSRF cookie. A sibling subdomain can
    # CHOOSE its value: set geolens_csrf=KNOWN with a parent Domain, and the
    # browser sends two geolens_csrf cookies. Starlette keeps the last
    # occurrence, and a freshly-set Domain cookie sharing Path=/ sorts after
    # the older host-only one (RFC 6265), so the attacker's value wins the
    # comparison while the victim's host-only geolens_refresh stays single
    # and would still be accepted.
    #
    # Refusing on a duplicate turns that into a 403 the victim clears by
    # signing in again — the same trade #1446 accepted for the refresh
    # cookie. Not fixable by naming alone in dev: __Host- (which browsers
    # refuse on a Domain cookie) needs TLS, and _secure_cookies() is False
    # without a terminator.
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
