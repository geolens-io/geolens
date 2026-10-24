"""Tests for cache providers and tile invalidation."""

import asyncio
import time
from collections import OrderedDict
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
async def test_memory_lru_bound_evicts_coldest():
    """The store is size-bounded; overflow evicts least-recently-used."""
    cache = InMemoryCacheProvider(max_entries=3)
    for i in range(3):
        await cache.set(f"k{i}", i, ttl=60)
    # Touch k0 so it is most-recently-used; k1 is now the coldest.
    assert await cache.get("k0") == 0
    await cache.set("k3", 3, ttl=60)  # overflow -> evict k1
    assert len(cache._store) == 3
    assert await cache.get("k1") is None
    assert await cache.get("k0") == 0
    assert await cache.get("k3") == 3


@pytest.mark.asyncio
async def test_memory_byte_budget_evicts_coldest():
    cache = InMemoryCacheProvider(max_bytes=250)
    for i in range(3):
        await cache.set(f"k{i}", "x" * 100, ttl=60)
    assert await cache.get("k0") is None
    assert await cache.get("k1") == "x" * 100
    assert await cache.get("k2") == "x" * 100


@pytest.mark.asyncio
async def test_memory_skips_oversized_value_and_drops_the_stale_one():
    cache = InMemoryCacheProvider(max_bytes=250)
    await cache.set("k", "small", ttl=60)
    await cache.set("k", "x" * 500, ttl=60)
    assert await cache.get("k") is None
    assert cache._bytes == 0
    assert await cache.set_if_absent("k", "x" * 500, ttl=60) is False


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
    # These build the provider through __new__, so the
    # replay state __init__ sets up has to be seeded here too.
    provider._pending_authoritative = OrderedDict()
    provider._replay_lock = asyncio.Lock()
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
    # These build the provider through __new__, so the
    # replay state __init__ sets up has to be seeded here too.
    provider._pending_authoritative = OrderedDict()
    provider._replay_lock = asyncio.Lock()
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
    # These build the provider through __new__, so the
    # replay state __init__ sets up has to be seeded here too.
    provider._pending_authoritative = OrderedDict()
    provider._replay_lock = asyncio.Lock()
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
    # These build the provider through __new__, so the
    # replay state __init__ sets up has to be seeded here too.
    provider._pending_authoritative = OrderedDict()
    provider._replay_lock = asyncio.Lock()
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
# Regression: _update_sync_cache must warm semantic/basemap rate limits
# ---------------------------------------------------------------------------


def test_update_sync_cache_populates_semantic_search_rate_limit():
    """Calling _update_sync_cache for 'semantic_search_rate_limit'
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
    """Calling _update_sync_cache for 'basemap_proxy_rate_limit'
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
    """_update_sync_cache must include the two new rate-limit keys in
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


# --- Eviction must reach BOTH stores in BOTH circuit states ---
#
# Codebase audit 2026-08-30, "Cache invalidation never reaches the in-memory
# fallback, so a revoked embed token can be served as valid during the next
# Redis blip". Reads and writes route to one store; eviction used to as well,
# so an entry written into the fallback during an outage outlived a delete
# issued after recovery and came back on the next blip.
#
# Counterfactual: restore the "if self._is_circuit_open(): await
# self._fallback.delete(key); return" shape in RedisCacheProvider and each of
# these fails with the stale value still readable.


@pytest.mark.asyncio
async def test_delete_while_closed_also_evicts_the_fallback(cb_redis):
    # Entry landed in the fallback during an outage.
    await cb_redis._fallback.set("embed_token:abc", {"is_valid": True}, 300)

    # Circuit is closed again; the capability is revoked.
    await cb_redis.delete("embed_token:abc")

    # Next blip: reads route to the fallback, which must no longer hold it.
    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() + 300
    assert await cb_redis.get("embed_token:abc") is None


@pytest.mark.asyncio
async def test_delete_many_while_closed_also_evicts_the_fallback(cb_redis):
    await cb_redis._fallback.set("embed_token:a", {"is_valid": True}, 300)
    await cb_redis._fallback.set("embed_token:b", {"is_valid": True}, 300)

    await cb_redis.delete_many("embed_token:a", "embed_token:b")

    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() + 300
    assert await cb_redis.get("embed_token:a") is None
    assert await cb_redis.get("embed_token:b") is None


@pytest.mark.asyncio
async def test_delete_pattern_while_closed_also_evicts_the_fallback(cb_redis):
    await cb_redis._fallback.set("embed_token:a", {"is_valid": True}, 300)
    await cb_redis._fallback.set("other:keep", 1, 300)

    await cb_redis.delete_pattern("embed_token:*")

    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() + 300
    assert await cb_redis.get("embed_token:a") is None
    assert await cb_redis.get("other:keep") == 1


@pytest.mark.asyncio
async def test_delete_while_open_still_evicts_the_fallback(cb_redis):
    """The pre-existing open-circuit behaviour is unchanged."""
    await cb_redis._fallback.set("embed_token:abc", {"is_valid": True}, 300)
    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() + 300

    await cb_redis.delete("embed_token:abc")
    assert await cb_redis.get("embed_token:abc") is None


@pytest.mark.asyncio
async def test_delete_still_reaches_redis_while_closed(cb_redis):
    """Adding the fallback eviction must not drop the Redis one."""
    await cb_redis.set("k", "v", ttl=60)
    await cb_redis.delete("k")
    assert await cb_redis._client.get("k") is None


@pytest.mark.asyncio
async def test_a_failing_redis_delete_still_evicts_the_fallback():
    """A delete that raises must not leave the fallback copy behind."""
    provider = RedisCacheProvider.__new__(RedisCacheProvider)
    mock_client = AsyncMock()
    mock_client.delete.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client
    provider._max_failures = 5
    provider._cooldown_seconds = 30
    provider._failure_count = 0
    provider._circuit_open_until = 0.0
    provider._fallback = InMemoryCacheProvider()
    # These build the provider through __new__, so the
    # replay state __init__ sets up has to be seeded here too.
    provider._pending_authoritative = OrderedDict()
    provider._replay_lock = asyncio.Lock()

    await provider._fallback.set("embed_token:abc", {"is_valid": True}, 300)
    await provider.delete("embed_token:abc")

    assert await provider._fallback.get("embed_token:abc") is None
    assert provider._failure_count == 1


# --- The OVERRIDE has the same two-store requirement ---
#
# The eviction fix above was not enough on its own. A revocation writes a denial
# rather than deleting the key (so a racing publisher cannot re-cache the
# token), and `set` routes to whichever store the circuit says is live. A
# positive entry that landed in the fallback during an outage therefore survived
# a denial written after Redis recovered, and the next Redis error served the
# revoked token again.
#
# Counterfactual: change set_authoritative back to `set` and
# test_the_denial_overwrites_a_stale_fallback_positive fails with the positive
# still readable.


@pytest.mark.asyncio
async def test_the_denial_overwrites_a_stale_fallback_positive(cb_redis):
    """Pin: fallback holds a positive, Redis recovers,
    revoke, Redis errors again, validation is denied."""
    # 1. Outage: the positive lands in the fallback.
    await cb_redis._fallback.set("embed_token:abc", {"is_valid": True}, 300)

    # 2. Redis has recovered (circuit closed) and the token is revoked.
    await cb_redis.set_authoritative("embed_token:abc", {"is_valid": False}, 300)

    # 3. Redis errors again, so reads route to the fallback.
    cb_redis._failure_count = 3
    cb_redis._circuit_open_until = time.monotonic() + 300
    assert await cb_redis.get("embed_token:abc") == {"is_valid": False}


@pytest.mark.asyncio
async def test_set_authoritative_reaches_redis_too(cb_redis):
    await cb_redis.set_authoritative("k", {"is_valid": False}, 60)
    assert await cb_redis._client.get("k") == '{"is_valid": false}'
    assert await cb_redis._fallback.get("k") == {"is_valid": False}


@pytest.mark.asyncio
async def test_set_authoritative_still_lands_when_redis_is_down():
    provider = RedisCacheProvider.__new__(RedisCacheProvider)
    mock_client = AsyncMock()
    mock_client.set.side_effect = ConnectionError("Redis unavailable")
    provider._client = mock_client
    provider._max_failures = 5
    provider._cooldown_seconds = 30
    provider._failure_count = 0
    provider._circuit_open_until = 0.0
    provider._fallback = InMemoryCacheProvider()
    # These build the provider through __new__, so the
    # replay state __init__ sets up has to be seeded here too.
    provider._pending_authoritative = OrderedDict()
    provider._replay_lock = asyncio.Lock()

    await provider.set_authoritative("k", {"is_valid": False}, 60)
    assert await provider._fallback.get("k") == {"is_valid": False}
    assert provider._failure_count == 1


@pytest.mark.asyncio
async def test_set_if_absent_yields_to_a_denial_held_only_in_the_fallback(cb_redis):
    """Absent has to mean absent in EVERY store. A racing publisher whose
    circuit opened between its read and its write would otherwise put a positive
    straight back into the fallback the denial had just cleared."""
    await cb_redis._fallback.set("embed_token:abc", {"is_valid": False}, 300)

    stored = await cb_redis.set_if_absent("embed_token:abc", {"is_valid": True}, 300)

    assert stored is False
    assert await cb_redis._client.get("embed_token:abc") is None
    assert await cb_redis._fallback.get("embed_token:abc") == {"is_valid": False}


@pytest.mark.asyncio
async def test_set_if_absent_still_publishes_into_an_empty_cache(cb_redis):
    assert await cb_redis.set_if_absent("fresh", {"is_valid": True}, 60) is True
    assert await cb_redis.get("fresh") == {"is_valid": True}


# --- An authoritative write has to survive the outage ---
#
# The first fix wrote the denial to both stores, but only when it could reach both.
# With the circuit OPEN it wrote the fallback and returned, and Redis kept the
# pre-revocation positive; once the cooldown lapsed, get() consulted Redis first
# and served that positive for the rest of its TTL. That is the original race running
# backwards, and it needs both halves below to close: the queue-and-replay, so
# Redis eventually agrees, and the queue-first read, so the window before the
# replay is not a hole of its own.
#
# Counterfactuals, each run: drop _queue_authoritative_replay from the
# circuit-open branch and test_a_denial_written_during_an_outage_survives_recovery
# fails after the cooldown; drop the pending-first check in get() and the same
# test fails BEFORE the replay.


def _open_circuit(provider) -> None:
    provider._failure_count = provider._max_failures
    provider._circuit_open_until = time.monotonic() + 300


def _close_circuit(provider) -> None:
    """Let the cooldown lapse without calling anything on the provider.

    This is the real transition: nothing invokes a state machine, a timestamp
    just goes stale. Whichever call next asks _circuit_open() is the one that
    has to drain.
    """
    provider._circuit_open_until = time.monotonic() - 1


@pytest.mark.asyncio
async def test_a_denial_written_during_an_outage_survives_recovery(cb_redis):
    """The pin: positive in Redis, circuit open, revoke, circuit closes,
    denied both before and after the replay."""
    await cb_redis.set("embed_token:abc", {"is_valid": True}, ttl=300)
    assert await cb_redis._client.get("embed_token:abc") is not None

    _open_circuit(cb_redis)
    await cb_redis.set_authoritative("embed_token:abc", {"is_valid": False}, 300)
    assert await cb_redis.get("embed_token:abc") == {"is_valid": False}

    _close_circuit(cb_redis)

    # Before the replay has landed anywhere: the queue answers.
    assert cb_redis._pending_authoritative, "the override was dropped, not queued"
    assert await cb_redis.get("embed_token:abc") == {"is_valid": False}, (
        "the pre-outage Redis positive was served after recovery"
    )

    # The read above is what drained it, so Redis now agrees on its own.
    assert not cb_redis._pending_authoritative
    assert await cb_redis._client.get("embed_token:abc") == '{"is_valid": false}'
    assert await cb_redis.get("embed_token:abc") == {"is_valid": False}


@pytest.mark.asyncio
async def test_a_plain_set_during_an_outage_does_not_replay(cb_redis):
    """set() publishes a cached answer, not a decision. Replaying it would put a
    pre-outage snapshot back over whatever is true now."""
    _open_circuit(cb_redis)
    await cb_redis.set("catalog:datasets", {"total": 1}, ttl=300)
    assert not cb_redis._pending_authoritative

    _close_circuit(cb_redis)
    assert await cb_redis._client.get("catalog:datasets") is None


@pytest.mark.asyncio
async def test_a_failed_authoritative_write_is_queued_too(cb_redis):
    """The circuit does not have to be open for Redis to refuse the write."""
    mock_client = AsyncMock()
    mock_client.set.side_effect = ConnectionError("Redis unavailable")
    cb_redis._client = mock_client

    await cb_redis.set_authoritative("embed_token:abc", {"is_valid": False}, 300)
    assert "embed_token:abc" in cb_redis._pending_authoritative
    assert await cb_redis.get("embed_token:abc") == {"is_valid": False}


class _WriteRefusingRedis:
    """fakeredis that reads normally but refuses every write.

    This is the shape that isolates the queue-first read. A mock client cannot:
    its `get` returns a MagicMock, `json.loads` raises on it, and the read falls
    into the Redis-error branch and answers from the fallback anyway, which
    passes whether or not the queue is consulted.
    """

    def __init__(self, inner):
        self._inner = inner

    async def set(self, *_args, **_kwargs):
        raise ConnectionError("Redis is refusing writes")

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.mark.asyncio
async def test_the_queue_outranks_a_readable_redis_positive(cb_redis):
    """The window the queue-first read exists for.

    Redis is readable and still holds the pre-revocation positive, but will not
    take the denial, and the failure count has not reached the threshold, so the
    circuit stays CLOSED. Every drain attempt fails. Without the queue-first
    check in get(), the read goes straight to a healthy-looking Redis and serves
    the positive for the rest of its TTL.
    """
    await cb_redis.set("embed_token:abc", {"is_valid": True}, ttl=300)
    cb_redis._client = _WriteRefusingRedis(cb_redis._client)

    await cb_redis.set_authoritative("embed_token:abc", {"is_valid": False}, 300)

    assert not cb_redis._is_circuit_open(), (
        "this test is only meaningful while the circuit is closed"
    )
    assert await cb_redis._client.get("embed_token:abc") == '{"is_valid": true}', (
        "Redis still holds the positive, which is the whole point"
    )
    assert await cb_redis.get("embed_token:abc") == {"is_valid": False}, (
        "a readable Redis positive outranked the revocation's denial"
    )


@pytest.mark.asyncio
async def test_a_failed_replay_leaves_the_queue_intact(cb_redis):
    """Redis looking reachable is not Redis being reachable. A drain that raises
    must not lose the override it was trying to persist."""
    _open_circuit(cb_redis)
    await cb_redis.set_authoritative("embed_token:abc", {"is_valid": False}, 300)

    mock_client = AsyncMock()
    mock_client.set.side_effect = ConnectionError("Redis unavailable")
    mock_client.get.side_effect = ConnectionError("Redis unavailable")
    cb_redis._client = mock_client
    _close_circuit(cb_redis)

    assert await cb_redis.get("embed_token:abc") == {"is_valid": False}
    assert "embed_token:abc" in cb_redis._pending_authoritative


@pytest.mark.asyncio
async def test_the_replay_queue_is_bounded_and_drops_the_oldest(cb_redis):
    from app.platform.cache import redis as redis_module

    limit = redis_module._MAX_PENDING_AUTHORITATIVE
    _open_circuit(cb_redis)
    for i in range(limit + 5):
        await cb_redis.set_authoritative(f"embed_token:{i}", {"is_valid": False}, 300)

    assert len(cb_redis._pending_authoritative) == limit
    assert "embed_token:0" not in cb_redis._pending_authoritative
    assert f"embed_token:{limit + 4}" in cb_redis._pending_authoritative


@pytest.mark.asyncio
async def test_a_delete_discards_a_queued_override(cb_redis):
    """Replaying an override after the caller said the entry should not exist
    would put it back."""
    _open_circuit(cb_redis)
    await cb_redis.set_authoritative("embed_token:abc", {"is_valid": False}, 300)
    await cb_redis.delete("embed_token:abc")

    assert not cb_redis._pending_authoritative
    _close_circuit(cb_redis)
    assert await cb_redis.get("embed_token:abc") is None


@pytest.mark.asyncio
async def test_set_if_absent_yields_to_a_queued_override(cb_redis):
    """A racing publisher must lose to an override that is still waiting for
    Redis, the same way it loses to one already in a store."""
    _open_circuit(cb_redis)
    await cb_redis.set_authoritative("embed_token:abc", {"is_valid": False}, 300)
    _close_circuit(cb_redis)

    # Re-queue: the close above has not been observed by any call yet, so the
    # override is still pending when the publisher arrives.
    assert cb_redis._pending_authoritative
    stored = await cb_redis.set_if_absent("embed_token:abc", {"is_valid": True}, 300)
    assert stored is False


@pytest.mark.asyncio
async def test_an_expired_override_is_not_replayed(cb_redis):
    """The queue restores a decision, it does not extend one."""
    _open_circuit(cb_redis)
    await cb_redis.set_authoritative("embed_token:abc", {"is_valid": False}, 300)
    key, (value, ttl, _expires_at) = next(iter(cb_redis._pending_authoritative.items()))
    cb_redis._pending_authoritative[key] = (value, ttl, time.monotonic() - 1)

    _close_circuit(cb_redis)
    assert await cb_redis.get("embed_token:abc") is None
    assert not cb_redis._pending_authoritative
    assert await cb_redis._client.get("embed_token:abc") is None


@pytest.fixture(params=["memory", "redis"])
def conditional_cache(request, redis_cache):
    return InMemoryCacheProvider() if request.param == "memory" else redis_cache


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
@pytest.mark.parametrize(
    "state", ["matching", "different", "missing", "expired", "null"]
)
async def test_conditional_cache_only_changes_a_live_matching_value(
    conditional_cache, operation, state
):
    cache = conditional_cache
    expected = None if state in {"missing", "null"} else "owner"
    original = None if state == "null" else "other" if state == "different" else "owner"
    if state != "missing":
        await cache.set("claim", original)
    if state == "expired":
        if isinstance(cache, RedisCacheProvider):
            await cache._client.pexpire("claim", 0)
        else:
            cache._store["claim"] = (original, time.monotonic() - 1)
    args = (
        ("claim", expected, "renewed", 60)
        if operation == "compare_and_set"
        else ("claim", expected)
    )
    changed = await getattr(cache, operation)(*args)
    matches = state in {"matching", "null"}
    assert changed is matches
    want = (
        "renewed"
        if matches and operation == "compare_and_set"
        else None
        if matches or state in {"missing", "expired"}
        else original
    )
    assert await cache.get("claim") == want
    if matches and operation == "compare_and_set":
        if isinstance(cache, RedisCacheProvider):
            assert 0 < await cache._client.ttl("claim") <= 60
        else:
            assert 0 < cache._store["claim"][1] - time.monotonic() <= 60


@pytest.mark.asyncio
async def test_memory_compare_and_set_reports_a_rejected_value():
    cache = InMemoryCacheProvider(max_bytes=20)
    await cache.set("claim", "owner")
    assert await cache.compare_and_set("claim", "owner", "x" * 21) is False
    assert await cache.get("claim") is None
    assert cache._bytes == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
async def test_redis_conditional_operations_use_the_active_store(
    redis_cache, operation
):
    cache = redis_cache
    cache._failure_count = cache._max_failures
    cache._circuit_open_until = time.monotonic() + 30
    await cache._fallback.set("claim", "owner")
    await cache._client.set("claim", '"another-replica"')
    args = (
        ("claim", "owner", "renewed", 60)
        if operation == "compare_and_set"
        else ("claim", "owner")
    )
    assert await getattr(cache, operation)(*args) is True
    assert await cache._fallback.get("claim") == (
        "renewed" if operation == "compare_and_set" else None
    )
    assert await cache._client.get("claim") == '"another-replica"'


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
async def test_redis_conditional_error_is_not_replayed_or_applied_locally(
    redis_cache, monkeypatch, operation
):
    cache = redis_cache
    await cache.set("claim", "owner")
    await cache._fallback.set("claim", "local")
    monkeypatch.setattr(cache._client, "eval", AsyncMock(side_effect=ConnectionError))
    args = (
        ("claim", "owner", "renewed", 60)
        if operation == "compare_and_set"
        else ("claim", "owner")
    )
    assert await getattr(cache, operation)(*args) is False
    assert cache._failure_count == 1
    assert await cache._fallback.get("claim") == "local"
    assert cache._pending_authoritative == {}
    assert await cache.get("claim") == "owner"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
async def test_redis_conditional_operation_cannot_change_a_racing_owner(
    redis_cache, monkeypatch, operation
):
    cache = redis_cache
    await cache.set("claim", "owner")
    original_get, original_eval = cache._client.get, cache._client.eval

    async def read_then_replace(key):
        value = await original_get(key)
        await cache.set(key, "successor")
        return value

    async def replace_then_compare(*args):
        await cache.set("claim", "successor")
        return await original_eval(*args)

    monkeypatch.setattr(cache._client, "get", read_then_replace)
    monkeypatch.setattr(cache._client, "eval", replace_then_compare)
    args = (
        ("claim", "owner", "renewed", 60)
        if operation == "compare_and_set"
        else ("claim", "owner")
    )
    assert await getattr(cache, operation)(*args) is False
    assert await original_get("claim") == '"successor"'


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
async def test_redis_conditional_error_preserves_a_matching_local_claim(
    redis_cache, monkeypatch, operation
):
    cache = redis_cache
    await cache.set("claim", "owner")
    await cache._fallback.set("claim", "owner", ttl=45)
    local_entry = cache._fallback._store["claim"]
    monkeypatch.setattr(cache._client, "eval", AsyncMock(side_effect=ConnectionError))
    args = (
        ("claim", "owner", "renewed", 60)
        if operation == "compare_and_set"
        else ("claim", "owner")
    )

    changed = await getattr(cache, operation)(*args)

    assert cache._fallback._store.get("claim") == local_entry
    assert changed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
@pytest.mark.parametrize(("expected", "changed"), [("owner", True), ("other", False)])
async def test_redis_conditional_response_resets_consecutive_failures(
    redis_cache, operation, expected, changed
):
    cache = redis_cache
    await cache.set("claim", "owner")
    cache._failure_count = cache._max_failures - 1
    args = (
        ("claim", expected, "renewed", 60)
        if operation == "compare_and_set"
        else ("claim", expected)
    )

    assert await getattr(cache, operation)(*args) is changed
    # A later cache read would reset the count independently and mask this call.
    assert cache._failure_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
async def test_memory_conditional_operation_preserves_a_queued_successor(operation):
    cache = InMemoryCacheProvider()
    await cache.set("claim", "owner")
    args = (
        ("claim", "owner", "renewed", 60)
        if operation == "compare_and_set"
        else ("claim", "owner")
    )
    # Queue the successor immediately after the operation: any yield between
    # reading the owner and mutating storage lets the successor win that gap.
    conditional = asyncio.create_task(getattr(cache, operation)(*args))
    successor = asyncio.create_task(cache.set("claim", "successor"))
    changed, _ = await asyncio.gather(conditional, successor)

    assert changed is True
    assert await cache.get("claim") == "successor"


@pytest.mark.asyncio
async def test_redis_conditional_fallback_honors_the_requested_ttl(redis_cache):
    cache = redis_cache
    cache._failure_count = cache._max_failures
    cache._circuit_open_until = time.monotonic() + 30
    await cache._fallback.set("claim", "owner")

    assert await cache.compare_and_set("claim", "owner", "renewed", ttl=17) is True

    assert await cache._fallback.get("claim") == "renewed"
    assert 0 < cache._fallback._store["claim"][1] - time.monotonic() <= 17


@pytest.mark.asyncio
async def test_memory_conditional_delete_releases_the_byte_budget():
    cache = InMemoryCacheProvider(max_bytes=10)
    await cache.set("claim", "owner")

    assert await cache.compare_and_delete("claim", "owner") is True

    assert cache._bytes == 0
    assert "claim" not in cache._sizes
    await cache.set("next", "value")
    assert await cache.get("next") == "value"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "writer", ["set", "set_authoritative", "set_if_absent", "replay", "compare_and_set"]
)
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
async def test_redis_conditional_mapping_equality_ignores_insertion_order(
    redis_cache, writer, operation
):
    original = {"z": {"c": 3, "a": 1, "b": 2}, "m": 2, "a": 1}
    expected = {"m": 2, "a": 1, "z": {"b": 2, "c": 3, "a": 1}}
    assert original == expected
    if writer == "replay":
        redis_cache._queue_authoritative_replay("claim", original, 60)
        await redis_cache._replay_pending_authoritative()
    elif writer == "compare_and_set":
        await redis_cache.set("claim", "seed")
        assert await redis_cache.compare_and_set("claim", "seed", original, 60)
    else:
        await getattr(redis_cache, writer)("claim", original, ttl=60)

    if operation == "compare_and_set":
        replacement = {"z": 9, "m": 8, "a": 7}
        assert await redis_cache.compare_and_set("claim", expected, replacement, 60)
        assert await redis_cache.get("claim") == replacement
        assert await redis_cache.compare_and_delete("claim", {"m": 8, "a": 7, "z": 9})
    else:
        assert await redis_cache.compare_and_delete("claim", expected)
    assert await redis_cache.get("claim") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("operation", ["compare_and_set", "compare_and_delete"])
async def test_redis_mixed_key_write_and_compare_keeps_legacy_encoding(
    redis_cache, nested, operation
):
    value = {"outer": {1: "a", "b": 2}} if nested else {1: "a", "b": 2}
    expected = {"outer": {1: "a", "b": 2}} if nested else {1: "a", "b": 2}
    decoded = {"outer": {"1": "a", "b": 2}} if nested else {"1": "a", "b": 2}
    await redis_cache.set("claim", "old")

    await redis_cache.set("claim", value)

    assert await redis_cache.get("claim") == decoded
    if operation == "compare_and_set":
        assert await redis_cache.compare_and_set("claim", expected, {1: "new", "b": 3})
        assert await redis_cache.get("claim") == {"1": "new", "b": 3}
        assert await redis_cache.compare_and_delete("claim", {1: "new", "b": 3})
    else:
        assert await redis_cache.compare_and_delete("claim", expected)
    assert await redis_cache.get("claim") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["set", "compare_and_set"])
async def test_redis_failed_mixed_key_write_preserves_the_previous_shared_value(
    redis_cache, monkeypatch, operation
):
    await redis_cache.set("claim", "old")
    before = await redis_cache._client.get("claim")
    write = AsyncMock(side_effect=ConnectionError("write refused before mutation"))
    monkeypatch.setattr(
        redis_cache._client, "set" if operation == "set" else "eval", write
    )

    if operation == "set":
        await redis_cache.set("claim", {1: "a", "b": 2})
    else:
        assert (
            await redis_cache.compare_and_set("claim", "old", {1: "a", "b": 2}) is False
        )

    write.assert_awaited_once()
    assert await redis_cache.get("claim") == "old"
    assert await redis_cache._client.get("claim") == before
