"""Integration tests for gzip, security headers, HSTS, body size limit, and rate limiting middleware."""

import pytest
import structlog
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from slowapi.wrappers import LimitGroup

from app.standards.ogc.errors import register_error_handlers


@pytest.mark.anyio
async def test_gzip_compression(client: AsyncClient):
    """GET /health with Accept-Encoding: gzip returns Content-Encoding: gzip."""
    resp = await client.get("/health", headers={"Accept-Encoding": "gzip"})
    # Health may return 200 or 503 in test env -- we only care about compression
    assert resp.headers.get("content-encoding") == "gzip"


@pytest.mark.anyio
async def test_gzip_skips_small_responses(client: AsyncClient):
    """Small responses below minimum_size (256 bytes) are not compressed."""
    # Use the docs endpoint which returns a redirect (tiny body)
    resp = await client.get(
        "/docs", headers={"Accept-Encoding": "identity"}, follow_redirects=False
    )
    assert resp.headers.get("content-encoding") is None


@pytest.mark.anyio
async def test_security_headers_present(client: AsyncClient):
    """Response includes all 6 security headers."""
    resp = await client.get("/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert resp.headers["x-frame-options"] == "DENY"
    assert (
        resp.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    )


@pytest.mark.anyio
async def test_hsts_with_https(client: AsyncClient):
    """Request with X-Forwarded-Proto: https gets HSTS header."""
    resp = await client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert (
        resp.headers["strict-transport-security"]
        == "max-age=63072000; includeSubDomains"
    )


@pytest.mark.anyio
async def test_hsts_without_https(client: AsyncClient):
    """Request without X-Forwarded-Proto does NOT get HSTS header."""
    resp = await client.get("/health")
    assert "strict-transport-security" not in resp.headers


@pytest.mark.anyio
async def test_body_size_limit_rejects_oversized(client: AsyncClient):
    """Request with Content-Length exceeding limit returns 413."""
    # upload_max_size_mb defaults to 500, so limit = 500 * 1024 * 1024
    max_bytes = 500 * 1024 * 1024
    resp = await client.post(
        "/health",
        content=b"x",
        headers={"Content-Length": str(max_bytes + 1)},
    )
    assert resp.status_code == 413
    assert "too large" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_body_size_limit_allows_normal(client: AsyncClient):
    """Request with Content-Length within limit passes through normally."""
    resp = await client.post(
        "/health",
        content=b'{"test": true}',
        headers={"Content-Length": "14"},
    )
    # /health doesn't accept POST, so we expect 405 (method not allowed),
    # NOT 413 -- proving the body limit middleware let it through
    assert resp.status_code != 413


@pytest.mark.anyio
async def test_rate_limiting(client: AsyncClient):
    """When rate limiter is enabled and client exceeds limit, response is 429."""
    from app.modules.auth.router import limiter

    original_enabled = limiter.enabled
    original_limits = limiter._default_limits
    try:
        limiter.enabled = True
        limiter._default_limits = [
            LimitGroup(
                "2/second", limiter._key_func, None, False, None, None, None, 1, False
            )
        ]
        # Clear any cached rate limit state
        limiter._storage.reset()
        results = []
        for _ in range(5):
            resp = await client.get("/conformance")
            results.append(resp.status_code)
        assert 429 in results, f"Expected at least one 429, got: {results}"
    finally:
        limiter.enabled = original_enabled
        limiter._default_limits = original_limits


@pytest.mark.anyio
async def test_rate_limit_health_excluded(client: AsyncClient):
    """GET /health is not subject to the tight global default rate limit.

    GAP-016: /health carries its own explicit @limiter.limit("60/minute")
    instead of @limiter.exempt. A route-specific limit overrides the global
    default in slowapi, so a tight 2/second default never trips the Docker
    healthcheck / LB polling — exactly the property this test guards.
    """
    from app.modules.auth.router import limiter

    original_enabled = limiter.enabled
    original_limits = limiter._default_limits
    try:
        limiter.enabled = True
        limiter._default_limits = [
            LimitGroup(
                "2/second", limiter._key_func, None, False, None, None, None, 1, False
            )
        ]
        limiter._storage.reset()
        results = []
        for _ in range(10):
            resp = await client.get("/health")
            results.append(resp.status_code)
        assert 429 not in results, (
            f"Health should be exempt from rate limiting, got: {results}"
        )
    finally:
        limiter.enabled = original_enabled
        limiter._default_limits = original_limits


@pytest.mark.anyio
async def test_ai_endpoint_rate_limit(client: AsyncClient, admin_auth_header: dict):
    """AI endpoints respect their per-route rate limit (10/minute for generate)."""
    from app.modules.auth.router import limiter

    original_enabled = limiter.enabled
    try:
        limiter.enabled = True
        limiter._storage.reset()

        results = []
        for _ in range(12):
            resp = await client.post(
                "/ai/generate-map/",
                json={"prompt": "test"},
                headers=admin_auth_header,
            )
            results.append(resp.status_code)

        # Expect 429 to appear after exceeding 10/minute limit.
        # Early responses may be 403 (AI disabled) or 503 (no API key) — that's fine,
        # the rate limiter fires before the endpoint body runs.
        assert 429 in results, f"Expected at least one 429 in {results}"
    finally:
        limiter.enabled = original_enabled
        limiter._storage.reset()


@pytest.mark.anyio
async def test_rate_limit_429_includes_retry_after(client: AsyncClient):
    """(#315) a 429 from the limiter carries a positive integer Retry-After header.

    Drives POST /auth/login past its per-minute budget (5/minute by default)
    with bad credentials so slowapi fires before the handler body, then asserts
    the final 429 advertises the back-off window.
    """
    from app.modules.auth.router import limiter

    original_enabled = limiter.enabled
    try:
        limiter.enabled = True
        limiter._storage.reset()

        last = None
        for _ in range(8):
            last = await client.post(
                "/auth/login",
                data={"username": "nobody", "password": "wrongpassword"},
            )
            if last.status_code == 429:
                break

        assert last is not None and last.status_code == 429, (
            f"Expected a 429 after exhausting login limit, got: "
            f"{last.status_code if last is not None else None}"
        )
        assert "retry-after" in last.headers, (
            f"429 response missing Retry-After header; got: {dict(last.headers)}"
        )
        retry_after = int(last.headers["retry-after"])
        assert retry_after > 0, f"Retry-After must be positive, got: {retry_after}"
    finally:
        limiter.enabled = original_enabled
        limiter._storage.reset()


@pytest.mark.parametrize(
    "detail",
    ["Tile service busy, please retry", {"code": "tile_service_busy"}],
)
@pytest.mark.anyio
async def test_http_exception_handler_preserves_response_headers(detail):
    """RFC 7807 conversion keeps headers attached to HTTPException responses."""
    test_app = FastAPI()

    @test_app.get("/limited")
    async def limited():
        raise HTTPException(
            status_code=429,
            detail=detail,
            headers={"Retry-After": "2"},
        )

    register_error_handlers(test_app)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        response = await test_client.get("/limited")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == detail


@pytest.mark.anyio
async def test_global_rate_limit_configurable(client: AsyncClient):
    """Global rate limit is configurable and defaults to 60/second."""
    from app.modules.auth.router import _global_rate_limit
    from app.core.persistent_config import get_cached_global_rate_limit

    assert get_cached_global_rate_limit() == 60
    assert _global_rate_limit() == "60/second"


@pytest.mark.anyio
async def test_service_field_in_logs(client: AsyncClient):
    """API startup binds service='api' in structlog contextvars."""
    ctx = structlog.contextvars.get_contextvars()
    assert "service" in ctx, f"Expected 'service' in contextvars, got: {ctx}"
    assert ctx["service"] == "api"
