"""Browser refresh-token cookie + CSRF primitives (GH-1302).

The refresh token is the only credential that moves into a cookie. Access
tokens keep travelling as ``Authorization: Bearer`` headers, so **no**
state-changing endpoint authenticates from a cookie — exactly one route does:
``POST /auth/refresh``. CSRF enforcement is therefore scoped to that route
rather than to every mutator.

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
    """Externally-visible path of the refresh route, for ``Path=`` scoping.

    The app runs with ``root_path="/api"`` behind both the dev Vite proxy and
    the production nginx ``location /api/`` block, and neither forwards the
    prefix upstream. Deriving the path from ``root_path`` keeps the cookie
    correctly scoped under any mount point instead of hardcoding ``/api``.

    Scoping to the refresh route (rather than ``/``) keeps the cookie off
    catalog, tile, and upload traffic entirely: it cannot leak through access
    logs or intermediary proxies on the hot path, and it cannot be replayed
    against any other endpoint.
    """
    root_path = request.scope.get("root_path", "").rstrip("/")
    return f"{root_path}/auth/refresh"


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
    whose name/path/domain match regardless of where the response came from, so
    ``/auth/logout`` can clear a cookie scoped to ``/auth/refresh``.
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
    return request.cookies.get(REFRESH_COOKIE_NAME)


def is_same_origin_as_request(request: Request, url: str) -> bool:
    """Whether *url* shares scheme+host+port with this request's own origin.

    Used by the OAuth callback: a cookie it sets is scoped to the host the
    browser used to reach the API, so it is only usable afterwards when the SPA
    lives on that same origin. A false answer falls back to the pre-GH-1302
    fragment delivery rather than handing the browser a cookie it will never
    send back — mismatch degrades, it never locks anyone out.
    """
    try:
        target = urlsplit(url)
    except ValueError:
        return False
    if not target.scheme or not target.netloc:
        return False
    return (
        target.scheme.lower() == (request.url.scheme or "").lower()
        and target.netloc.lower() == (request.url.netloc or "").lower()
    )


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
