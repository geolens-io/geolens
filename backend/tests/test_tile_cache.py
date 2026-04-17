"""Tests for TileCacheProvider and pool settings externalization."""

import gzip
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from app.platform.cache.tile_cache import TileCacheProvider


# --- Fixtures ---


@pytest.fixture
def tile_cache():
    """Create TileCacheProvider backed by fakeredis (binary mode)."""
    provider = TileCacheProvider.__new__(TileCacheProvider)
    provider._client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    # Reset Prometheus counters for isolation
    from app.platform.cache.tile_cache import tile_cache_hits, tile_cache_misses

    tile_cache_hits._value.set(0)
    tile_cache_misses._value.set(0)
    return provider


# --- TileCacheProvider get/set tests ---


@pytest.mark.asyncio
async def test_tile_cache_get_miss(tile_cache):
    """Cache miss returns None and increments miss counter."""
    from app.platform.cache.tile_cache import tile_cache_misses

    result = await tile_cache.get("test_table", 5, 10, 15)
    assert result is None
    assert tile_cache_misses._value.get() == 1


@pytest.mark.asyncio
async def test_tile_cache_set_and_get(tile_cache):
    """Binary round-trip: set stores bytes, get returns exact bytes."""
    from app.platform.cache.tile_cache import tile_cache_hits

    raw = b"\x00\x01\x02\x03binary tile data"
    compressed = gzip.compress(raw)
    await tile_cache.set("test_table", 5, 10, 15, compressed, ttl=60)
    result = await tile_cache.get("test_table", 5, 10, 15)
    assert result == compressed
    assert tile_cache_hits._value.get() == 1


@pytest.mark.asyncio
async def test_tile_cache_hit_increments_counter(tile_cache):
    """Successive hits increment the hit counter."""
    from app.platform.cache.tile_cache import tile_cache_hits

    data = gzip.compress(b"tile")
    await tile_cache.set("t", 1, 2, 3, data, ttl=60)
    await tile_cache.get("t", 1, 2, 3)
    await tile_cache.get("t", 1, 2, 3)
    assert tile_cache_hits._value.get() == 2


@pytest.mark.asyncio
async def test_tile_cache_miss_increments_counter(tile_cache):
    """Successive misses increment the miss counter."""
    from app.platform.cache.tile_cache import tile_cache_misses

    await tile_cache.get("t", 1, 2, 3)
    await tile_cache.get("t", 4, 5, 6)
    assert tile_cache_misses._value.get() == 2


# --- Graceful degradation tests ---


@pytest.mark.asyncio
async def test_tile_cache_get_returns_none_on_redis_failure():
    """Redis failure on get returns None (graceful degradation)."""
    from app.platform.cache.tile_cache import tile_cache_misses

    tile_cache_misses._value.set(0)

    provider = TileCacheProvider.__new__(TileCacheProvider)
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client

    result = await provider.get("t", 1, 2, 3)
    assert result is None
    assert tile_cache_misses._value.get() == 1


@pytest.mark.asyncio
async def test_tile_cache_set_silent_on_redis_failure():
    """Redis failure on set is silent (no exception)."""
    provider = TileCacheProvider.__new__(TileCacheProvider)
    mock_client = AsyncMock()
    mock_client.set.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client

    # Should not raise
    await provider.set("t", 1, 2, 3, b"data", ttl=60)


# --- invalidate_table tests ---


@pytest.mark.asyncio
async def test_invalidate_table_removes_all_tiles_for_table(tile_cache):
    """invalidate_table removes all cached tiles for the specified table."""
    data = gzip.compress(b"tile")
    # Cache tiles for two tables
    await tile_cache.set("target", 1, 0, 0, data, ttl=60)
    await tile_cache.set("target", 2, 1, 1, data, ttl=60)
    await tile_cache.set("target", 3, 2, 2, data, ttl=60)
    await tile_cache.set("other", 1, 0, 0, data, ttl=60)

    await tile_cache.invalidate_table("target")

    # All target tiles should be gone
    assert await tile_cache.get("target", 1, 0, 0) is None
    assert await tile_cache.get("target", 2, 1, 1) is None
    assert await tile_cache.get("target", 3, 2, 2) is None
    # Other table's tiles should remain
    assert await tile_cache.get("other", 1, 0, 0) == data


@pytest.mark.asyncio
async def test_invalidate_table_noop_when_no_tiles(tile_cache):
    """invalidate_table is a no-op when the table has no cached tiles."""
    # Should not raise
    await tile_cache.invalidate_table("nonexistent")


@pytest.mark.asyncio
async def test_invalidate_table_silent_on_redis_failure():
    """Redis failure on invalidate_table is silent (graceful degradation)."""
    provider = TileCacheProvider.__new__(TileCacheProvider)
    mock_client = AsyncMock()
    mock_client.scan.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client

    # Should not raise
    await provider.invalidate_table("test_table")


# --- get_tile_cache singleton tests ---


def test_get_tile_cache_returns_none_when_redis_not_set():
    """get_tile_cache() returns None when redis_url is not configured."""
    from unittest.mock import patch

    from app.platform.cache import provider as cache_provider

    old = cache_provider._tile_cache
    try:
        cache_provider._tile_cache = None
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.redis_url = None
            cache_provider.init_tile_cache()
            assert cache_provider.get_tile_cache() is None
    finally:
        cache_provider._tile_cache = old


def test_get_tile_cache_returns_provider_when_redis_set():
    """get_tile_cache() returns TileCacheProvider when redis_url is configured."""
    from unittest.mock import patch

    from app.platform.cache import provider as cache_provider

    old = cache_provider._tile_cache
    try:
        cache_provider._tile_cache = None
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379"
            cache_provider.init_tile_cache()
            result = cache_provider.get_tile_cache()
            assert isinstance(result, TileCacheProvider)
    finally:
        cache_provider._tile_cache = old


# --- Pool settings tests ---


def test_settings_db_pool_size_default():
    """Settings.db_pool_size defaults to 10."""
    from app.core.config import settings

    assert settings.db_pool_size == 10


def test_settings_tile_pool_max_size_default():
    """Settings.tile_pool_max_size defaults to 10."""
    from app.core.config import settings

    assert settings.tile_pool_max_size == 10


def test_settings_db_pool_size_env_override(monkeypatch):
    """DB_POOL_SIZE env var overrides db_pool_size default."""
    monkeypatch.setenv("DB_POOL_SIZE", "25")
    # Re-create settings to pick up env var
    from app.core.config import Settings

    s = Settings(
        postgres_password="test",
        jwt_secret_key="test-jwt-secret-padding-to-32-chars",
        geolens_admin_username="admin",
        geolens_admin_password="admin",
    )
    assert s.db_pool_size == 25


def test_settings_tile_pool_max_size_env_override(monkeypatch):
    """TILE_POOL_MAX_SIZE env var overrides tile_pool_max_size default."""
    monkeypatch.setenv("TILE_POOL_MAX_SIZE", "20")
    from app.core.config import Settings

    s = Settings(
        postgres_password="test",
        jwt_secret_key="test-jwt-secret-padding-to-32-chars",
        geolens_admin_username="admin",
        geolens_admin_password="admin",
    )
    assert s.tile_pool_max_size == 20
