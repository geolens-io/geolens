"""Security response headers middleware.

Adds standard security headers to all API responses:
- X-Content-Type-Options: nosniff -- prevents MIME-type sniffing
- Referrer-Policy: strict-origin-when-cross-origin -- limits referrer leakage
- Content-Security-Policy: frame-ancestors 'self' -- prevents clickjacking
- X-Frame-Options: DENY -- legacy clickjacking protection
- Permissions-Policy: camera=(), microphone=(), geolocation=() -- restricts browser features
- Strict-Transport-Security (conditional) -- enforces HTTPS when behind TLS terminator
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        # SEC-13: only set Referrer-Policy if the route did NOT already set it.
        # OAuth callback uses no-referrer to keep the IdP authorization code
        # and URL-fragment tokens out of subsequent Referer headers; non-OAuth
        # routes still get the global strict-origin-when-cross-origin default.
        if "referrer-policy" not in (h.lower() for h in response.headers.keys()):
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        # HSTS only when request arrived via HTTPS (reverse proxy sets header)
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        if forwarded_proto == "https" or request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )

        return response
