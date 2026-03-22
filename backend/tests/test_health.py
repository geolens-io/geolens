"""Tests for health service and infrastructure schemas."""

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

# Env vars needed for module-level _create_settings() on first import
_IMPORT_ENV = {
    "POSTGRES_PASSWORD": "testpass",
    "JWT_SECRET_KEY": "testsecret",
    "GEOLENS_ADMIN_USERNAME": "admin",
    "GEOLENS_ADMIN_PASSWORD": "adminpass",
}

_orig_env = os.environ.copy()
for k, v in _IMPORT_ENV.items():
    os.environ.setdefault(k, v)

if "app.config" in sys.modules:
    del sys.modules["app.config"]

from app.health.service import _probe, check_health  # noqa: E402
from app.admin.schemas import (  # noqa: E402
    InfrastructureConfig,
    InfrastructureResponse,
    ProviderHealth,
)

os.environ.clear()
os.environ.update(_orig_env)


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
    """Failed probe returns error status with message."""

    async def fail_coro():
        raise ConnectionError("Connection refused")

    result = await _probe("test", fail_coro())
    assert result["status"] == "error"
    assert "latency_ms" in result
    assert "Connection refused" in result["error"]


@pytest.mark.asyncio
async def test_probe_timeout():
    """Slow probe is aborted by timeout."""

    async def slow_coro():
        await asyncio.sleep(60)

    with patch("app.health.service.HEALTH_TIMEOUT", 0.1):
        result = await _probe("test", slow_coro())
    assert result["status"] == "error"
    assert result["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_check_health_all_healthy():
    """All providers healthy returns status=healthy."""

    async def noop():
        pass

    with (
        patch("app.health.service._check_database", new=noop),
        patch("app.health.service._check_storage", new=noop),
        patch("app.health.service._check_cache", new=noop),
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
        patch("app.health.service._check_database", new=fail),
        patch("app.health.service._check_storage", new=noop),
        patch("app.health.service._check_cache", new=noop),
    ):
        result = await check_health()

    assert result["status"] == "degraded"
    assert result["providers"]["database"]["status"] == "error"
    assert result["providers"]["storage"]["status"] == "ok"
    assert result["providers"]["cache"]["status"] == "ok"


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
