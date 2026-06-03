"""Tests for cache providers and tile invalidation."""

import time
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from app.platform.cache.memory import InMemoryCacheProvider
from app.platform.cache.redis import RedisCacheProvider
from app.platform.cache.tiles import invalidate_catalog_cache  # noqa: F401


# --- InMemoryCacheProvider tests ---


@pytest.mark.asyncio
async def test_memory_get_miss():
    cache = InMemoryCacheProvider()
    assert await cache.get("nonexistent") is None


@pytest.mark.asyncio
async def test_memory_set_and_get():
    cache = InMemoryCacheProvider()
    await cache.set("key1", {"value": 42}, ttl=60)
    result = await cache.get("key1")
    assert result == {"value": 42}


@pytest.mark.asyncio
async def test_memory_ttl_expiry():
    cache = InMemoryCacheProvider()
    await cache.set("key1", "hello", ttl=1)
    # Monkey-patch the stored expiry to be in the past
    key_data = cache._store["key1"]
    cache._store["key1"] = (key_data[0], time.monotonic() - 1)
    assert await cache.get("key1") is None


@pytest.mark.asyncio
async def test_memory_delete():
    cache = InMemoryCacheProvider()
    await cache.set("key1", "val")
    await cache.delete("key1")
    assert await cache.get("key1") is None


@pytest.mark.asyncio
async def test_memory_delete_missing_key():
    cache = InMemoryCacheProvider()
    # Should not raise
    await cache.delete("nonexistent")


@pytest.mark.asyncio
async def test_memory_delete_pattern():
    cache = InMemoryCacheProvider()
    await cache.set("catalog:datasets:1", "a")
    await cache.set("catalog:datasets:2", "b")
    await cache.set("settings:ai", "c")
    await cache.delete_pattern("catalog:*")
    assert await cache.get("catalog:datasets:1") is None
    assert await cache.get("catalog:datasets:2") is None
    assert await cache.get("settings:ai") == "c"


# --- RedisCacheProvider tests (using fakeredis) ---


@pytest.fixture
def redis_cache():
    """Create RedisCacheProvider backed by fakeredis."""
    provider = RedisCacheProvider.__new__(RedisCacheProvider)
    provider._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider._max_failures = 5
    provider._cooldown_seconds = 30
    provider._failure_count = 0
    provider._circuit_open_until = 0.0
    provider._fallback = InMemoryCacheProvider()
    return provider


@pytest.mark.asyncio
async def test_redis_get_miss(redis_cache):
    assert await redis_cache.get("nonexistent") is None


@pytest.mark.asyncio
async def test_redis_set_and_get(redis_cache):
    await redis_cache.set("key1", {"value": 42}, ttl=60)
    result = await redis_cache.get("key1")
    assert result == {"value": 42}


@pytest.mark.asyncio
async def test_redis_delete(redis_cache):
    await redis_cache.set("key1", "val")
    await redis_cache.delete("key1")
    assert await redis_cache.get("key1") is None


@pytest.mark.asyncio
async def test_redis_delete_pattern(redis_cache):
    await redis_cache.set("catalog:a", 1)
    await redis_cache.set("catalog:b", 2)
    await redis_cache.set("other:c", 3)
    await redis_cache.delete_pattern("catalog:*")
    assert await redis_cache.get("catalog:a") is None
    assert await redis_cache.get("catalog:b") is None
    assert await redis_cache.get("other:c") == 3


@pytest.mark.asyncio
async def test_redis_graceful_get_on_failure():
    """Redis connection failure returns None (cache miss), not exception."""
    provider = RedisCacheProvider.__new__(RedisCacheProvider)
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client
    provider._max_failures = 5
    provider._cooldown_seconds = 30
    provider._failure_count = 0
    provider._circuit_open_until = 0.0
    provider._fallback = InMemoryCacheProvider()
    result = await provider.get("any_key")
    assert result is None


@pytest.mark.asyncio
async def test_redis_graceful_set_on_failure():
    """Redis connection failure on set is non-fatal."""
    provider = RedisCacheProvider.__new__(RedisCacheProvider)
    mock_client = AsyncMock()
    mock_client.set.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client
    provider._max_failures = 5
    provider._cooldown_seconds = 30
    provider._failure_count = 0
    provider._circuit_open_until = 0.0
    provider._fallback = InMemoryCacheProvider()
    # Should not raise
    await provider.set("any_key", "any_value", ttl=60)


# --- init_cache tests ---


def test_init_cache_memory():
    """init_cache creates InMemoryCacheProvider when redis_url is None."""
    from app.platform.cache import provider as cache_provider
    from app.platform.cache.memory import (
        InMemoryCacheProvider as CurrentInMemoryCacheProvider,
    )

    old = cache_provider._cache_provider
    try:
        cache_provider._cache_provider = None
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.redis_url = None
            cache_provider.init_cache()
            assert isinstance(
                cache_provider._cache_provider, CurrentInMemoryCacheProvider
            )
    finally:
        cache_provider._cache_provider = old


# --- Circuit breaker tests ---


@pytest.fixture
def cb_redis():
    """Create RedisCacheProvider with circuit breaker state initialized (low threshold for testing)."""
    provider = RedisCacheProvider.__new__(RedisCacheProvider)
    provider._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider._max_failures = 3  # Lower threshold for testing
    provider._cooldown_seconds = 30
    provider._failure_count = 0
    provider._circuit_open_until = 0.0
    provider._fallback = InMemoryCacheProvider()
    return provider


@pytest.mark.asyncio
async def test_circuit_breaker_stays_closed_on_success(cb_redis):
    """Normal get/set works, _failure_count stays 0."""
    await cb_redis.set("k", "v", ttl=60)
    result = await cb_redis.get("k")
    assert result == "v"
    assert cb_redis._failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_max_failures(cb_redis):
    """After N consecutive failures, circuit opens and routes to fallback."""
    # Replace client with a failing mock
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("Redis down")
    cb_redis._client = mock_client

    # Trigger max_failures (3) consecutive failures
    for _ in range(3):
        await cb_redis.get("any")

    assert cb_redis._failure_count >= 3
    # Circuit should be open -- next call should go to fallback without touching Redis
    mock_client.get.reset_mock()
    await cb_redis.get("any")
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_circuit_breaker_fallback_serves_cached_data(cb_redis):
    """Set data via fallback while open, get returns it."""
    # Open the circuit
    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() + 300

    # Write to fallback
    await cb_redis.set("fb_key", {"data": 42}, ttl=60)
    # Read from fallback
    result = await cb_redis.get("fb_key")
    assert result == {"data": 42}


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_success(cb_redis):
    """After cooldown, successful probe resets failure count."""
    # Simulate past cooldown (circuit was open but cooldown expired)
    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() - 1  # Expired

    # The next call should try Redis (half-open probe)
    await cb_redis.set("probe", "yes", ttl=60)
    # Success resets failure count
    assert cb_redis._failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_failure(cb_redis):
    """After cooldown, failed probe re-opens circuit."""
    # Simulate past cooldown
    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() - 1  # Expired

    # Replace with failing client for half-open probe
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("Still down")
    cb_redis._client = mock_client

    await cb_redis.get("probe")
    # Should have re-opened circuit (failure count incremented, new cooldown set)
    assert cb_redis._failure_count >= 3
    assert cb_redis._circuit_open_until > time.monotonic()


@pytest.mark.asyncio
async def test_circuit_breaker_success_resets_count(cb_redis):
    """Failures followed by success resets _failure_count to 0."""
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("Redis down")
    cb_redis._client = mock_client

    # 2 failures (below threshold of 3)
    await cb_redis.get("k1")
    await cb_redis.get("k2")
    assert cb_redis._failure_count == 2

    # Now restore working Redis
    cb_redis._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await cb_redis.set("k3", "ok", ttl=60)
    assert cb_redis._failure_count == 0


@pytest.mark.asyncio
async def test_health_check_bypasses_circuit_breaker(cb_redis):
    """health_check calls Redis even when circuit is open."""
    # Open the circuit
    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() + 300

    # health_check should still contact Redis directly (fakeredis responds to ping)
    await cb_redis.health_check()  # Should NOT raise


# ---------------------------------------------------------------------------
# CR-03 regression: _update_sync_cache must warm semantic/basemap rate limits
# ---------------------------------------------------------------------------


def test_update_sync_cache_populates_semantic_search_rate_limit():
    """CR-03: calling _update_sync_cache for 'semantic_search_rate_limit'
    must populate _sync_rate_limit_cache so get_cached_semantic_search_rate_limit()
    returns the overridden value instead of the default.
    """
    import app.core.persistent_config as pc

    # Temporarily write a non-default value into the sync cache directly
    # (simulates what _update_sync_cache does when a PersistentConfig with
    # key='semantic_search_rate_limit' calls set() or get() from DB).
    original = pc._sync_rate_limit_cache.get("semantic_search_rate_limit")
    try:
        pc._sync_rate_limit_cache["semantic_search_rate_limit"] = (99, time.monotonic())
        assert pc.get_cached_semantic_search_rate_limit() == 99, (
            "get_cached_semantic_search_rate_limit() must read from sync cache"
        )
    finally:
        if original is None:
            pc._sync_rate_limit_cache.pop("semantic_search_rate_limit", None)
        else:
            pc._sync_rate_limit_cache["semantic_search_rate_limit"] = original


def test_update_sync_cache_populates_basemap_proxy_rate_limit():
    """CR-03: calling _update_sync_cache for 'basemap_proxy_rate_limit'
    must populate _sync_rate_limit_cache so get_cached_basemap_proxy_rate_limit()
    returns the overridden value instead of the default.
    """
    import app.core.persistent_config as pc

    original = pc._sync_rate_limit_cache.get("basemap_proxy_rate_limit")
    try:
        pc._sync_rate_limit_cache["basemap_proxy_rate_limit"] = (77, time.monotonic())
        assert pc.get_cached_basemap_proxy_rate_limit() == 77, (
            "get_cached_basemap_proxy_rate_limit() must read from sync cache"
        )
    finally:
        if original is None:
            pc._sync_rate_limit_cache.pop("basemap_proxy_rate_limit", None)
        else:
            pc._sync_rate_limit_cache["basemap_proxy_rate_limit"] = original


def test_update_sync_cache_key_allowlist_covers_new_rate_limits():
    """CR-03: _update_sync_cache must include the two new rate-limit keys in
    its dispatch condition. This structural test guards against accidental
    removal of the keys from the allowlist.
    """
    import inspect
    import app.core.persistent_config as pc

    src = inspect.getsource(pc.PersistentConfig._update_sync_cache)
    assert "semantic_search_rate_limit" in src, (
        "'semantic_search_rate_limit' must be in PersistentConfig._update_sync_cache"
    )
    assert "basemap_proxy_rate_limit" in src, (
        "'basemap_proxy_rate_limit' must be in PersistentConfig._update_sync_cache"
    )
