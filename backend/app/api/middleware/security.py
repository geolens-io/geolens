"""Security response headers middleware.

Adds standard security headers to all API responses:
- X-Content-Type-Options: nosniff -- prevents MIME-type sniffing
- Referrer-Policy: strict-origin-when-cross-origin -- limits referrer leakage
  (skipped if the route already set Referrer-Policy, e.g. OAuth callbacks
  use no-referrer per SEC-13)
- Content-Security-Policy: frame-ancestors 'self' -- prevents clickjacking
  (skipped if the route already set Content-Security-Policy, e.g. the icon
  GET endpoint uses `default-src 'none'; sandbox` for SVG per SEC-01)
- X-Frame-Options: DENY -- legacy clickjacking protection (skipped when
  the route set its own CSP frame-ancestors, per SEC-S08: legacy
  browsers apply XFO=DENY unconditionally and reject a permitted embed)
- Permissions-Policy: camera=(), microphone=(), geolocation=()
- Strict-Transport-Security (conditional) -- when behind a TLS terminator
"""

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Add security headers to every response.

    A plain ASGI middleware rather than ``BaseHTTPMiddleware``, which costs a
    task and a memory stream per request, tiles included.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # HSTS only when request arrived via HTTPS (reverse proxy sets header)
        forwarded_proto = Headers(scope=scope).get("x-forwarded-proto", "")
        https = forwarded_proto == "https" or scope.get("scheme") == "https"

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                _add_security_headers(MutableHeaders(scope=message), https=https)
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


def _add_security_headers(headers: MutableHeaders, *, https: bool) -> None:
    route_set = {key.lower() for key in headers.keys()}
    headers["X-Content-Type-Options"] = "nosniff"
    # SEC-13: only set Referrer-Policy if the route did NOT already set it.
    # OAuth callback uses no-referrer to keep the IdP authorization code
    # and URL-fragment tokens out of subsequent Referer headers; non-OAuth
    # routes still get the global strict-origin-when-cross-origin default.
    if "referrer-policy" not in route_set:
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # SEC-01: only set the global CSP if the route hasn't already (the
    # icon GET handler uses `default-src 'none'; sandbox`; the
    # shared-map endpoint (SEC-S08) emits a per-token frame-ancestors).
    #
    # SEC-S08: skip X-Frame-Options: DENY when the route owns its own
    # CSP — modern browsers honor frame-ancestors over XFO, but legacy
    # browsers apply the unconditional XFO=DENY and would reject the
    # embed regardless of the route's per-token policy.
    if "content-security-policy" not in route_set:
        headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        headers["X-Frame-Options"] = "DENY"
    # else: route owns both clickjacking-defense headers; do not add XFO.
    headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if https:
        headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
