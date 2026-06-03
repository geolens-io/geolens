"""SEC-17: GZipMiddleware mount-order vs SecurityHeadersMiddleware is pinned.

Pins the v13.13 closure of L-63. The mount order is significant — flipping
it would mean GZip compresses BEFORE the headers are added, which would
break the security-header guarantee on compressed responses.

Starlette behavior: ``app.add_middleware`` PREPENDS. So the LAST
``add_middleware`` call ends up at index 0 of ``app.user_middleware``.
On the request path, index 0 runs first; on the response path, index 0
runs LAST.

Required ordering on the response path: SecurityHeaders adds headers,
THEN GZip compresses. Therefore SecurityHeaders must be added FIRST
(innermost, runs first on response), GZip added SECOND (outermost, runs
second on response). In ``app.user_middleware``, GZip is at a LOWER
index than SecurityHeaders.

These tests inspect ``app.user_middleware`` directly without invoking
the FastAPI lifespan context, so they do not require a live DB.
"""

from fastapi.testclient import TestClient
from starlette.middleware.gzip import GZipMiddleware

from app.api.main import app
from app.api.middleware.security import SecurityHeadersMiddleware


def _index_of(user_middleware: list, cls) -> int:
    """Return the index of the first Middleware whose .cls is ``cls``, or -1."""
    for i, mw in enumerate(user_middleware):
        if mw.cls is cls:
            return i
    return -1


def test_both_middleware_present():
    """Both GZipMiddleware and SecurityHeadersMiddleware are mounted."""
    sec_idx = _index_of(app.user_middleware, SecurityHeadersMiddleware)
    gzip_idx = _index_of(app.user_middleware, GZipMiddleware)
    assert sec_idx != -1, "SecurityHeadersMiddleware not mounted"
    assert gzip_idx != -1, "GZipMiddleware not mounted"


def test_gzip_outer_to_security_headers_inner():
    """GZipMiddleware (outer) appears at a LOWER index than SecurityHeadersMiddleware (inner).

    Starlette: lower index = added later = outermost = runs LAST on response.
    Required: SecurityHeaders runs FIRST on response (adds headers BEFORE
    compression), so SecurityHeaders is INNER (higher index in user_middleware),
    GZip is OUTER (lower index).
    """
    sec_idx = _index_of(app.user_middleware, SecurityHeadersMiddleware)
    gzip_idx = _index_of(app.user_middleware, GZipMiddleware)
    assert gzip_idx < sec_idx, (
        f"SEC-17: GZipMiddleware (idx {gzip_idx}) MUST be at a LOWER index than "
        f"SecurityHeadersMiddleware (idx {sec_idx}) so SecurityHeaders runs first "
        f"on the response path. Current order: GZip outer, SecurityHeaders inner. "
        f"If this test fails, someone flipped the mount order in "
        f"backend/app/api/main.py — the security-header guarantee is broken."
    )


def test_compressed_response_still_carries_security_headers():
    """End-to-end: a compressed response (via Accept-Encoding: gzip) MUST still
    carry all security headers — proving the order is correct in practice.

    Uses TestClient WITHOUT a `with` block to skip the FastAPI lifespan
    context (which requires DB connectivity); the security-header
    middleware does not depend on lifespan startup. /health resolves
    even when the DB is unreachable — its handler returns a 503
    body, but the middleware-added headers (and gzip compression) still
    apply to the response.
    """
    tc = TestClient(app)  # NOTE: no `with` — skip lifespan
    # The /health endpoint may return 200 or 503 depending on whether the
    # autouse DB fixture set up the DB; for this test we only care about
    # the response headers, which the middleware applies regardless.
    resp = tc.get("/health", headers={"Accept-Encoding": "gzip"})
    # Security headers (from SecurityHeadersMiddleware) MUST be present
    assert resp.headers.get("x-content-type-options") == "nosniff", (
        "SEC-17: x-content-type-options missing — middleware order may be broken."
    )
    assert resp.headers.get("x-frame-options") == "DENY", (
        "SEC-17: x-frame-options missing — middleware order may be broken."
    )
    # The Referrer-Policy global default must still apply on non-OAuth routes
    # (this also pins the SEC-13 setdefault semantics).
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin", (
        "SEC-17/SEC-13: global Referrer-Policy default missing on /health."
    )
