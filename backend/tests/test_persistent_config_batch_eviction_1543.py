"""fix(#1543): a settings batch evicts its cache keys as one step.

``update_settings`` commits the whole batch and only then invalidates the cache.
While that invalidation ran one key at a time, a reader landing in the middle
resolved the already-evicted keys from the committed row and the rest from the
still-warm cache — a pair of settings that was never committed together. The
embedding model/dimensions pair is what surfaced it; the contract belongs to
``PersistentConfig``, so these tests use an unrelated pair to say so.

The window is microseconds wide, so racing for it is a coin flip. These tests
drive it instead: the probe cache below suspends the writer *inside* the
eviction and reads the pair at that exact point, which is the state any
concurrent reader scheduled there would observe.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.platform.cache.memory import InMemoryCacheProvider
from app.platform.cache.redis import RedisCacheProvider

# A genuinely paired setting: a model name is only meaningful against the
# provider it belongs to, so a mixed pair is a configuration that never existed.
_OLD = ("anthropic", "claude-old-model")
_NEW = ("openai_compatible", "gpt-new-model")


class _EvictionProbeCache:
    """Delegating cache provider that runs a hook at the start of each eviction.

    Stands in for the real Valkey provider, whose ``delete`` is a network
    round-trip. That round-trip is a real suspension point, and a suspension
    point inside the eviction is precisely what lets another task run between
    two keys of one batch. The in-memory provider has no such point, which is
    why the window cannot be raced for locally and has to be driven.

    The hook only reads, so it never re-enters the eviction methods.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.on_evict: Callable[[], Awaitable[None]] | None = None

    async def _suspend(self) -> None:
        if self.on_evict is not None:
            await self.on_evict()

    async def get(self, key: str) -> Any | None:
        return await self._inner.get(key)

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        await self._inner.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        await self._suspend()
        await self._inner.delete(key)

    async def delete_many(self, *keys: str) -> None:
        await self._suspend()
        await self._inner.delete_many(*keys)

    async def delete_pattern(self, pattern: str) -> None:
        await self._inner.delete_pattern(pattern)

    async def health_check(self) -> None:
        await self._inner.health_check()


@pytest.fixture
async def probe_cache(client: AsyncClient):
    """Install the probe over the live cache provider for one test."""
    from app.platform.cache import init_cache
    from app.platform.cache import provider as cache_provider

    init_cache()
    original = cache_provider._cache_provider
    probe = _EvictionProbeCache(original)
    cache_provider._cache_provider = probe
    try:
        yield probe
    finally:
        cache_provider._cache_provider = original


@pytest.fixture(autouse=True)
async def _clean_settings(client: AsyncClient):
    """Drop the DB overrides and cache entries this module writes."""
    yield
    from app.api.main import app
    from app.core.db.models import AppSetting
    from app.core.dependencies import get_db
    from app.platform.cache import get_cache

    async for db in app.dependency_overrides[get_db]():
        await db.execute(delete(AppSetting))
        await db.commit()

    try:
        cache = get_cache()
    except RuntimeError:
        return
    await cache.delete("config:llm_provider")
    await cache.delete("config:llm_model")


# ---------------------------------------------------------------------------
# The window itself
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_paired_settings_are_never_observed_mismatched(
    client: AsyncClient,
    admin_auth_header: dict[str, str],
    test_db_session,
    probe_cache: _EvictionProbeCache,
):
    """A reader inside the eviction only ever sees a pair that was committed.

    Restoring the per-key eviction loop makes this fail with the mixed pair
    ``("openai_compatible", "claude-old-model")``: the new provider, read from
    the committed row because its key was already evicted, beside the old model,
    still served from the cache because its key had not been evicted yet.
    """
    from app.core.persistent_config import LLM_MODEL, LLM_PROVIDER

    observations: list[tuple[str, str]] = []

    async def read_the_pair() -> None:
        # Start a fresh statement snapshot. Under READ COMMITTED this session
        # sees the batch's commit even though it opened before the request.
        await test_db_session.rollback()
        provider = await LLM_PROVIDER.get(test_db_session)
        model = await LLM_MODEL.get(test_db_session)
        observations.append((provider, model))

    # Commit the old pair, then read it once so both keys are cached. A reader
    # that lands before an eviction has to get a cache hit for the window to
    # exist at all — an unwarmed cache reads everything from the DB and is
    # trivially consistent.
    await LLM_PROVIDER.set(test_db_session, _OLD[0])
    await LLM_MODEL.set(test_db_session, _OLD[1])
    await read_the_pair()
    assert observations == [_OLD]

    probe_cache.on_evict = read_the_pair
    try:
        response = await client.put(
            "/api/settings/",
            json={"settings": {"llm_provider": _NEW[0], "llm_model": _NEW[1]}},
            headers=admin_auth_header,
        )
    finally:
        probe_cache.on_evict = None
    assert response.status_code == 200, response.text

    during_eviction = observations[1:]
    # Without this the test is vacuous: no reader ran, so nothing was proved.
    assert during_eviction, "the probe never ran — the eviction path was not taken"
    assert all(pair in (_OLD, _NEW) for pair in during_eviction), (
        "a reader inside the eviction saw a pair that was never committed "
        f"together: {during_eviction}"
    )

    # And the eviction actually happened — otherwise "never evict anything"
    # would satisfy the assertion above.
    await read_the_pair()
    assert observations[-1] == _NEW


@pytest.mark.anyio
async def test_settings_reset_evicts_its_batch_in_one_step(
    client: AsyncClient,
    admin_auth_header: dict[str, str],
    test_db_session,
    probe_cache: _EvictionProbeCache,
):
    """POST /settings/reset is the other batch writer and has the same window."""
    from app.core.persistent_config import LLM_MODEL, LLM_PROVIDER

    observations: list[tuple[str, str]] = []

    async def read_the_pair() -> None:
        await test_db_session.rollback()
        observations.append(
            (
                await LLM_PROVIDER.get(test_db_session),
                await LLM_MODEL.get(test_db_session),
            )
        )

    await LLM_PROVIDER.set(test_db_session, _OLD[0])
    await LLM_MODEL.set(test_db_session, _OLD[1])
    await read_the_pair()
    assert observations == [_OLD]

    defaults = (LLM_PROVIDER.env_default, LLM_MODEL.env_default)

    probe_cache.on_evict = read_the_pair
    try:
        response = await client.post(
            "/api/settings/reset/",
            json={"keys": ["llm_provider", "llm_model"]},
            headers=admin_auth_header,
        )
    finally:
        probe_cache.on_evict = None
    assert response.status_code == 200, response.text

    during_eviction = observations[1:]
    assert during_eviction, "the probe never ran — the eviction path was not taken"
    assert all(pair in (_OLD, defaults) for pair in during_eviction), (
        "a reader inside the reset's eviction saw a mix of overridden and "
        f"default values: {during_eviction}"
    )

    await read_the_pair()
    assert observations[-1] == defaults


# ---------------------------------------------------------------------------
# The provider contract the fix rests on
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_memory_delete_many_evicts_without_suspending():
    """The in-memory provider evicts a whole batch in one uninterrupted step.

    Driving the coroutine by hand is the assertion: a coroutine that never
    suspends raises StopIteration on its first ``send``, so there is no point
    at which the event loop could hand control to a reader.
    """
    cache = InMemoryCacheProvider()
    await cache.set("config:a", 1, ttl=60)
    await cache.set("config:b", 2, ttl=60)

    coro = cache.delete_many("config:a", "config:b")
    with pytest.raises(StopIteration):
        coro.send(None)

    assert await cache.get("config:a") is None
    assert await cache.get("config:b") is None


@pytest.fixture
def redis_cache():
    """RedisCacheProvider backed by fakeredis (mirrors test_cache.py)."""
    provider = RedisCacheProvider.__new__(RedisCacheProvider)
    provider._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    provider._max_failures = 5
    provider._cooldown_seconds = 30
    provider._failure_count = 0
    provider._circuit_open_until = 0.0
    provider._fallback = InMemoryCacheProvider()
    # fix(#1778 codex r2): these build the provider through __new__, so the
    # replay state __init__ sets up has to be seeded here too.
    provider._pending_authoritative = OrderedDict()
    provider._replay_lock = asyncio.Lock()
    provider._was_open = False
    provider._recovery_signal = False
    return provider


@pytest.mark.anyio
async def test_redis_delete_many_is_one_variadic_del(redis_cache):
    """DEL is variadic, so the batch is one command no client sees half-done.

    A loop over ``delete`` would put a network round-trip between every pair of
    keys, which is the window on a real Valkey deployment — and a much wider one
    than the in-memory measurement suggests.
    """
    issued: list[tuple[str, ...]] = []
    real_delete = redis_cache._client.delete

    async def recording_delete(*keys: str):
        issued.append(keys)
        return await real_delete(*keys)

    redis_cache._client.delete = recording_delete

    await redis_cache.set("config:a", 1, ttl=60)
    await redis_cache.set("config:b", 2, ttl=60)
    await redis_cache.delete_many("config:a", "config:b")

    assert issued == [("config:a", "config:b")]
    assert await redis_cache.get("config:a") is None
    assert await redis_cache.get("config:b") is None


@pytest.mark.anyio
async def test_redis_delete_many_skips_an_empty_batch(redis_cache):
    """DEL with no arguments is a protocol error, so an empty batch is a no-op."""
    issued: list[tuple[str, ...]] = []

    async def recording_delete(*keys: str):
        issued.append(keys)
        return 0

    redis_cache._client.delete = recording_delete

    await redis_cache.delete_many()

    assert issued == []


@pytest.mark.anyio
async def test_redis_delete_many_falls_back_as_one_step(redis_cache):
    """An open circuit routes the batch to the in-memory fallback, still whole."""
    await redis_cache._fallback.set("config:a", 1, ttl=60)
    await redis_cache._fallback.set("config:b", 2, ttl=60)
    redis_cache._failure_count = redis_cache._max_failures
    redis_cache._circuit_open_until = float("inf")

    await redis_cache.delete_many("config:a", "config:b")

    assert await redis_cache._fallback.get("config:a") is None
    assert await redis_cache._fallback.get("config:b") is None
