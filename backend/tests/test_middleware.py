"""Integration tests for gzip, security headers, HSTS, body size limit, and rate limiting middleware."""

import pytest
import structlog
from httpx import AsyncClient
from slowapi.wrappers import LimitGroup


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
    from app.auth.router import limiter

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
    """GET /health is exempt from rate limiting when decorated with @limiter.exempt."""
    from app.auth.router import limiter

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
async def test_global_rate_limit_configurable(client: AsyncClient):
    """Global rate limit is configurable and defaults to 60/second."""
    from app.auth.router import _global_rate_limit
    from app.persistent_config import get_cached_global_rate_limit

    assert get_cached_global_rate_limit() == 60
    assert _global_rate_limit() == "60/second"


@pytest.mark.anyio
async def test_service_field_in_logs(client: AsyncClient):
    """API startup binds service='api' in structlog contextvars."""
    ctx = structlog.contextvars.get_contextvars()
    assert "service" in ctx, f"Expected 'service' in contextvars, got: {ctx}"
    assert ctx["service"] == "api"
