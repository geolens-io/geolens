"""fix(#1778): a request that races a revoke must not re-cache the token.

Codebase audit 2026-08-30, "Embed-token revocation invalidates the Redis
positive cache BEFORE the caller's commit, so a concurrent request can re-cache
the still-active token and keep it serving for 300s".

The interleaving, in full:

  1. A tile request for embed token T misses the validation cache.
  2. It SELECTs T's row. In READ COMMITTED a plain select does not block on the
     revoking transaction's lock, so the row still reads is_active = True.
  3. The revoke flushes is_active = False and invalidates the cache entry. Its
     caller has not committed yet (a share revoke commits 17 lines further down
     router_sharing.py).
  4. The tile request publishes its positive entry, TTL up to 300 seconds.
  5. The revoke commits.

Every later request is served from step 4's entry, because the cache-hit path
re-checks only expires_at (SEC-014), never is_active. Deleting the key at step 3
cannot help: step 4 writes after it.

So the revoke stamps a DENIAL under the key and the validator publishes with
set_if_absent. Whichever lands first, the denial survives.

The tests below reproduce step 4 exactly: the cache double answers the FIRST
get with a miss while the store already holds the revocation's denial, which is
the same state the racing request sees.

Counterfactual: change set_if_absent back to set in
validate_embed_token_access and test_a_racing_validation_cannot_overwrite_the_
denial fails with the positive entry back in the store.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio
from collections import OrderedDict

import pytest

from app.modules.embed_tokens.service import (
    EMBED_TOKEN_REVOCATION_DENIAL_TTL_SECONDS,
    validate_embed_token_access,
)
from app.platform.cache.memory import InMemoryCacheProvider

pytestmark = pytest.mark.anyio


# fix(#1778 codex r3): the generation the race cases pin themselves to.
_TEST_GENERATION = 7


def _raw_token() -> str:
    import secrets

    return "et_" + secrets.token_urlsafe(32)


def _cache_key(raw_token: str) -> str:
    return f"embed_token:{hashlib.sha256(raw_token.encode()).hexdigest()}"


class RaceCache(InMemoryCacheProvider):
    """A store whose first read misses even though the denial is already in it.

    That is the racing request's view: its cache read happened before the
    revocation stamped the denial, and its write happens after.
    """

    def __init__(self) -> None:
        super().__init__()
        self.first_get_done = False

    async def get(self, key: str, *, security: bool = False):
        if not self.first_get_done:
            self.first_get_done = True
            return None
        return await super().get(key, security=security)


def _active_token_row(map_id: uuid.UUID, dataset_id: uuid.UUID):
    """The row the racing select reads: still committed-active."""
    return MagicMock(
        id=uuid.uuid4(),
        map_id=map_id,
        token_hash="unused",
        allowed_origins=None,
        scoped_dataset_ids=[str(dataset_id)],
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        tenant_id=None,
    )


async def _validate_with(cache, raw, dataset_id, map_id) -> bool:
    result = MagicMock()
    result.scalar_one_or_none.return_value = _active_token_row(map_id, dataset_id)
    db = AsyncMock()
    db.execute.return_value = result

    with (
        patch("app.modules.embed_tokens.service.get_cache", return_value=cache),
        patch(
            "app.modules.embed_tokens.service.map_contains_dataset",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.modules.embed_tokens.service._request_origin_is_allowed",
            AsyncMock(return_value=True),
        ),
        # fix(#1778 codex r2): neutralise the usage bump by replacing the
        # COROUTINE it runs, not asyncio.create_task. Patching create_task
        # substitutes an attribute on the shared asyncio module and hands the
        # service a MagicMock, which it then files in the module-level
        # _usage_bump_tasks set; MagicMock.add_done_callback does nothing, so
        # the mock never leaves the set and the next suite in the same worker
        # to drain it (test_embed_tokens.py) dies on
        # "An asyncio.Future, a coroutine or an awaitable is required". Patching
        # the coroutine keeps a real Task, so the done-callback still discards
        # it.
        patch(
            "app.modules.embed_tokens.service._bump_embed_token_usage_detached",
            AsyncMock(return_value=None),
        ),
        # fix(#1778 codex r3): these cases are about the NX race, not the
        # revocation generation, and RaceCache's deliberately-missing first read
        # would otherwise be spent on the generation lookup instead of the token.
        # Pinned to a constant so the entry the racer publishes is stamped with
        # the same value the reader compares against.
        patch(
            "app.modules.embed_tokens.service.current_revocation_generation",
            AsyncMock(return_value=_TEST_GENERATION),
        ),
    ):
        result = await validate_embed_token_access(raw, dataset_id, db)
    await _drain_usage_bump_tasks()
    return result


async def _drain_usage_bump_tasks() -> None:
    """Let the detached bumps finish before the test's event loop goes away."""
    from app.modules.embed_tokens.service import _usage_bump_tasks

    pending = [task for task in _usage_bump_tasks if not task.done()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def test_a_racing_validation_cannot_overwrite_the_denial():
    raw = _raw_token()
    dataset_id = uuid.uuid4()
    map_id = uuid.uuid4()
    cache = RaceCache()
    key = _cache_key(raw)

    # The revoke has already stamped its denial; the racing request's own read
    # happened before that, so it will miss.
    await cache.set(key, {"is_valid": False}, EMBED_TOKEN_REVOCATION_DENIAL_TTL_SECONDS)

    # The racing request completes -- it read a committed-active row and nothing
    # about it was wrong at the time. What matters is what it leaves behind.
    await _validate_with(cache, raw, dataset_id, map_id)

    assert await cache.get(key) == {"is_valid": False}, (
        "the racing validation re-published a positive entry over the "
        "revocation's denial; every later request would be served from it"
    )


async def test_a_first_validation_still_publishes_its_positive_entry():
    """The guard must refuse only an overwrite, not every cache write."""
    raw = _raw_token()
    dataset_id = uuid.uuid4()
    map_id = uuid.uuid4()
    cache = RaceCache()
    key = _cache_key(raw)

    assert await _validate_with(cache, raw, dataset_id, map_id) is True

    cached = await cache.get(key)
    assert cached is not None, "a clean cache miss must still prime the cache"
    assert cached["is_valid"] is True
    assert cached["scoped_dataset_ids"] == [str(dataset_id)]
    assert cached["generation"] == _TEST_GENERATION


class TestSetIfAbsent:
    """The primitive the fix rests on."""

    async def test_stores_when_absent(self):
        cache = InMemoryCacheProvider()
        assert await cache.set_if_absent("k", "first", 300) is True
        assert await cache.get("k") == "first"

    async def test_refuses_when_present(self):
        cache = InMemoryCacheProvider()
        await cache.set("k", {"is_valid": False}, 300)
        assert await cache.set_if_absent("k", {"is_valid": True}, 300) is False
        assert await cache.get("k") == {"is_valid": False}

    async def test_an_expired_entry_counts_as_absent(self):
        cache = InMemoryCacheProvider()
        await cache.set("k", "stale", 0)
        assert await cache.set_if_absent("k", "fresh", 300) is True
        assert await cache.get("k") == "fresh"


class TestDenialReachesEveryStore:
    """fix(#1778 codex r1): the revoke helper's write must be the two-store one.

    A positive entry that landed in the layered provider's in-memory fallback
    during a Redis outage outlived a denial written after Redis recovered,
    because ``set`` routes to whichever store the circuit says is live. The next
    Redis error then served the revoked token again.

    Counterfactual: change ``set_authoritative`` back to ``set`` in
    ``_deny_revoked_embed_tokens`` and the test below reads the stale positive
    back out of the fallback.
    """

    def _layered_provider(self):
        import fakeredis

        from app.platform.cache.redis import RedisCacheProvider

        provider = RedisCacheProvider.__new__(RedisCacheProvider)
        provider._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        provider._max_failures = 3
        provider._cooldown_seconds = 30
        provider._failure_count = 0
        provider._circuit_open_until = 0.0
        provider._fallback = InMemoryCacheProvider()
        # fix(#1778 codex r2): these build the provider through __new__, so the
        # replay state __init__ sets up has to be seeded here too.
        provider._pending_authoritative = OrderedDict()
        provider._replay_lock = asyncio.Lock()
        return provider

    async def test_a_revoke_denies_through_the_next_redis_outage(self, monkeypatch):
        import time

        from app.modules.embed_tokens import service as embed_service

        provider = self._layered_provider()
        monkeypatch.setattr(embed_service, "get_cache", lambda: provider)

        token_hash = "a" * 64
        key = embed_service._embed_token_cache_key(token_hash)
        # The revoke advances the generation; a scalar-answering session is all
        # _deny_revoked_embed_tokens needs from the database here.
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=_TEST_GENERATION)

        # 1. Redis was down; the validation result landed in the fallback.
        await provider._fallback.set(key, {"is_valid": True}, 300)

        # 2. Redis has recovered and the token is revoked.
        await embed_service._deny_revoked_embed_tokens(db, token_hash)
        assert await provider.get(key) == {"is_valid": False}

        # 3. Redis blips again inside the entry's TTL.
        provider._failure_count = 3
        provider._circuit_open_until = time.monotonic() + 300
        assert await provider.get(key) == {"is_valid": False}, (
            "the revoked token validated again off a stale fallback entry"
        )
