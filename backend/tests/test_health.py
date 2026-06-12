"""Tests for health service and infrastructure schemas."""

import asyncio
from unittest.mock import patch

import pytest

from app.observability.health.service import _probe, check_health
from app.modules.admin.schemas import (
    InfrastructureConfig,
    InfrastructureResponse,
    ProviderHealth,
)


@pytest.mark.asyncio
async def test_probe_success():
    """Successful probe returns ok status with latency."""

    async def ok_coro():
        pass

    result = await _probe("test", ok_coro())
    assert result["status"] == "ok"
    assert "latency_ms" in result
    assert isinstance(result["latency_ms"], float)
    assert "error" not in result


@pytest.mark.asyncio
async def test_probe_failure():
    """Failed probe reports error status; detail gated by the error flag.

    GAP-016: _probe omits the raw exception by default (so the unauthenticated
    /health response never leaks it) and only embeds it when
    _include_probe_errors is set (the authenticated admin path).
    """
    from app.observability.health.service import _include_probe_errors

    async def fail_coro():
        raise ConnectionError("Connection refused")

    # Default: error status, latency present, NO raw exception string.
    result = await _probe("test", fail_coro())
    assert result["status"] == "error"
    assert "latency_ms" in result
    assert "error" not in result

    # Opt-in (admin path): the detail is included.
    token = _include_probe_errors.set(True)
    try:
        result = await _probe("test", fail_coro())
    finally:
        _include_probe_errors.reset(token)
    assert "Connection refused" in result["error"]


@pytest.mark.asyncio
async def test_probe_timeout():
    """Slow probe is aborted by timeout."""

    async def slow_coro():
        await asyncio.sleep(60)

    with patch("app.observability.health.service.HEALTH_TIMEOUT", 0.1):
        result = await _probe("test", slow_coro())
    assert result["status"] == "error"
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_check_health_all_healthy():
    """All providers healthy returns status=healthy."""

    async def noop():
        pass

    with (
        patch("app.observability.health.service._check_database", new=noop),
        patch("app.observability.health.service._check_storage", new=noop),
        patch("app.observability.health.service._check_cache", new=noop),
    ):
        result = await check_health()

    assert result["status"] == "healthy"
    assert result["providers"]["database"]["status"] == "ok"
    assert result["providers"]["storage"]["status"] == "ok"
    assert result["providers"]["cache"]["status"] == "ok"


@pytest.mark.asyncio
async def test_check_health_degraded():
    """One failing provider returns status=degraded."""

    async def noop():
        pass

    async def fail():
        raise RuntimeError("db down")

    with (
        patch("app.observability.health.service._check_database", new=fail),
        patch("app.observability.health.service._check_storage", new=noop),
        patch("app.observability.health.service._check_cache", new=noop),
    ):
        result = await check_health()

    assert result["status"] == "degraded"
    assert result["providers"]["database"]["status"] == "error"
    assert result["providers"]["storage"]["status"] == "ok"
    assert result["providers"]["cache"]["status"] == "ok"


@pytest.mark.asyncio
async def test_check_health_default_omits_provider_error():
    """GAP-016: default check_health() must NOT embed the raw exception string.

    The unauthenticated /health endpoint calls check_health() with the default
    include_errors=False, so a failing provider returns only status/latency —
    never the provider exception text (which can leak hostnames, ports, bucket
    names, library internals).
    """
    secret = "asyncpg: could not connect to host db-internal-1.prod:5432 user=svc"

    async def noop():
        pass

    async def leak():
        raise RuntimeError(secret)

    with (
        patch("app.observability.health.service._check_database", new=leak),
        patch("app.observability.health.service._check_storage", new=noop),
        patch("app.observability.health.service._check_cache", new=noop),
    ):
        result = await check_health()

    db = result["providers"]["database"]
    assert db["status"] == "error"
    assert "error" not in db, (
        "Unauthenticated check_health() must not expose the raw provider "
        f"exception; got {db!r}"
    )
    # Defense in depth: the secret must not appear anywhere in the payload.
    assert secret not in str(result)


@pytest.mark.asyncio
async def test_check_health_include_errors_keeps_provider_error():
    """GAP-016: admin path (include_errors=True) keeps the error detail."""
    secret = "asyncpg: could not connect to host db-internal-1.prod:5432"

    async def noop():
        pass

    async def leak():
        raise RuntimeError(secret)

    with (
        patch("app.observability.health.service._check_database", new=leak),
        patch("app.observability.health.service._check_storage", new=noop),
        patch("app.observability.health.service._check_cache", new=noop),
    ):
        result = await check_health(include_errors=True)

    db = result["providers"]["database"]
    assert db["status"] == "error"
    assert db["error"] == secret, (
        "Authenticated admin view must still expose the provider error detail."
    )


@pytest.mark.anyio
async def test_health_endpoint_does_not_leak_provider_error(client):
    """GAP-016: the /health HTTP response omits raw provider exception text."""
    secret = "boto3 endpoint s3://internal-secret-bucket.prod creds=AKIAXXXX"

    async def noop():
        pass

    async def leak():
        raise RuntimeError(secret)

    with (
        patch("app.observability.health.service._check_database", new=noop),
        patch("app.observability.health.service._check_storage", new=leak),
        patch("app.observability.health.service._check_cache", new=noop),
    ):
        resp = await client.get("/health")

    assert resp.status_code == 503  # degraded
    body = resp.text
    assert secret not in body, (
        "The unauthenticated /health response leaked raw provider exception "
        f"text: {body}"
    )
    payload = resp.json()
    assert payload["providers"]["storage"]["status"] == "error"
    assert "error" not in payload["providers"]["storage"]


def test_health_endpoint_is_rate_limited():
    """GAP-016: /health carries an explicit rate limit and is not exempt.

    Before the fix the route was @limiter.exempt (in _exempt_routes, absent
    from _route_limits). After the fix it has its own generous @limiter.limit,
    so it appears in _route_limits and not in _exempt_routes.
    """
    from app.modules.auth.router import limiter

    assert "app.api.main.health" in limiter._route_limits, (
        "/health must carry an explicit @limiter.limit (GAP-016)."
    )
    assert limiter._route_limits["app.api.main.health"], (
        "/health route limit list must be non-empty."
    )
    assert "app.api.main.health" not in limiter._exempt_routes, (
        "/health must no longer be @limiter.exempt."
    )


def test_infrastructure_response_schema():
    """InfrastructureResponse validates correctly."""
    resp = InfrastructureResponse(
        config=InfrastructureConfig(
            storage_provider="local",
            cache_provider="memory",
            database_type="docker-compose",
            database_pooler="internal",
            tile_cache="cdn",
            tile_cache_ttl=300,
            cdn_configured=False,
        ),
        health={
            "database": ProviderHealth(status="ok", latency_ms=1.5),
            "storage": ProviderHealth(status="ok", latency_ms=0.3),
            "cache": ProviderHealth(status="error", latency_ms=5000.0, error="timeout"),
        },
    )
    assert resp.config.storage_provider == "local"
    assert resp.health["cache"].error == "timeout"
