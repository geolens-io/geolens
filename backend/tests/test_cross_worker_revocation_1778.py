"""fix(#1778 codex r3): a revoke on one Uvicorn worker has to reach the others.

Codex round 3 on #1796. ``RedisCacheProvider``'s in-memory fallback and its
authoritative-replay queue are PROCESS-local, and production runs several
workers behind one socket, so every guarantee they make is a per-worker
guarantee. The sequence that breaks:

  1. Redis goes down.
  2. Worker B validates embed token T and caches a positive.
  3. Worker A revokes T. The denial goes to A's fallback and A's replay queue.
     B knows about neither.
  4. B keeps serving T.
  5. Redis recovers, still holding the pre-outage positive, because A's replay
     has not run and may never run if A gets no traffic. B reads it.

Two mechanisms close it and both are exercised here. ``security=True`` stops
step 2 and step 4: an authorization positive is never taken from a process-local
store, so during an outage every validation falls through to the database. The
database-backed revocation generation closes step 5: the revoke advanced it
while Redis was down, and B refuses any entry stamped with an older one.

Every test builds TWO providers over ONE fakeredis, which is what "two workers,
one Redis" means in a single process. They deliberately do not share a fallback,
because that is the whole point.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from app.platform.cache.memory import InMemoryCacheProvider
from app.platform.cache.redis import RedisCacheProvider

pytestmark = pytest.mark.anyio

KEY = "embed_token:" + ("a" * 64)

# A token the validator-level cases below drive end to end.
RAW_TOKEN = "et_cross_worker_generation_case"
DATASET_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d5")
TOKEN_KEY = "embed_token:" + hashlib.sha256(RAW_TOKEN.encode()).hexdigest()


def _worker(shared_redis) -> RedisCacheProvider:
    """One Uvicorn worker's view: the shared Redis, its own everything else."""
    provider = RedisCacheProvider.__new__(RedisCacheProvider)
    provider._client = shared_redis
    provider._max_failures = 3
    provider._cooldown_seconds = 30
    provider._failure_count = 0
    provider._circuit_open_until = 0.0
    provider._fallback = InMemoryCacheProvider()
    provider._pending_authoritative = OrderedDict()
    provider._replay_lock = asyncio.Lock()
    provider._was_open = False
    provider._recovery_signal = False
    return provider


def _open_circuit(provider) -> None:
    provider._failure_count = provider._max_failures
    provider._circuit_open_until = time.monotonic() + 300


def _close_circuit(provider) -> None:
    provider._circuit_open_until = time.monotonic() - 1


@pytest.fixture
def workers():
    shared_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return _worker(shared_redis), _worker(shared_redis)


class TestSecurityReadsNeverComeFromLocalMemory:
    async def test_an_outage_denies_a_security_positive_from_the_fallback(
        self, workers
    ):
        """Step 2 and step 4: worker B cannot answer from its own memory.

        Counterfactual: drop the ``security`` branch from ``get`` and this
        returns the fallback positive instead of None.
        """
        _worker_a, worker_b = workers
        await worker_b._fallback.set(KEY, {"is_valid": True}, 300)
        _open_circuit(worker_b)

        assert await worker_b.get(KEY, security=True) is None, (
            "an authorization positive was served out of one worker's memory"
        )
        # A non-security read is unaffected: a stale catalog listing is a
        # correctness annoyance, not a capability.
        assert await worker_b.get(KEY) == {"is_valid": True}

    async def test_an_outage_does_not_even_write_a_security_positive(self, workers):
        _worker_a, worker_b = workers
        _open_circuit(worker_b)

        await worker_b.set(KEY, {"is_valid": True}, 300, security=True)
        assert await worker_b._fallback.get(KEY) is None

        assert (
            await worker_b.set_if_absent(KEY, {"is_valid": True}, 300, security=True)
            is False
        )
        assert await worker_b._fallback.get(KEY) is None

    async def test_a_refusal_may_still_come_from_the_queue(self, workers):
        """Refusing on stale information is fail-closed, so the queued override
        is exempt from the rule above."""
        _worker_a, worker_b = workers
        _open_circuit(worker_b)
        await worker_b.set_authoritative(KEY, {"is_valid": False}, 300)

        assert await worker_b.get(KEY, security=True) == {"is_valid": False}


class TestRevocationGenerationCrossesWorkers:
    async def test_a_revoke_during_an_outage_is_seen_after_recovery(self, workers):
        """The pin: B caches a positive, Redis goes down, A revokes, Redis comes
        back, B's next validation is denied.

        The generation is what carries it. A's denial and A's replay queue never
        leave A; the ``nextval`` A performed is in the database, which stayed up,
        and B re-reads it because its own circuit transitioned.
        """
        worker_a, worker_b = workers

        # B validated T before the outage and stamped the entry generation 4.
        await worker_b.set(KEY, {"is_valid": True, "generation": 4}, 300)
        assert await worker_b.get(KEY, security=True) == {
            "is_valid": True,
            "generation": 4,
        }

        # Redis goes down for both workers.
        _open_circuit(worker_a)
        _open_circuit(worker_b)

        # A revokes. Its denial and its queue are A's alone.
        await worker_a.set_authoritative(KEY, {"is_valid": False}, 300)
        assert await worker_b.get(KEY, security=True) is None, (
            "during the outage B must fall through to the database, not its memory"
        )
        # The database generation advanced to 5 while Redis was away.
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=5)

        # Redis recovers. B observes the transition on its next call.
        _close_circuit(worker_a)
        _close_circuit(worker_b)

        from app.platform.cache import revocation

        # B's circuit transitioned, so the generation comes from the database
        # rather than from a Redis key nobody could rewrite during the outage.
        import app.platform.cache.provider as provider_module

        original = provider_module._cache_provider
        provider_module._cache_provider = worker_b
        try:
            generation = await revocation.current_revocation_generation(db)
        finally:
            provider_module._cache_provider = original

        assert generation == 5
        stale = await worker_b.get(KEY, security=True)
        assert stale is not None, "Redis still holds the pre-revocation positive"
        assert stale["generation"] != generation, (
            "the stale entry compared equal to the current generation, so the "
            "validator would have trusted it"
        )

    async def test_a_missing_generation_key_falls_through_to_the_database(
        self, workers
    ):
        """No recovery signal, but nothing in Redis either: the database answers
        and the Redis key is rewritten for everyone else."""
        worker_a, _worker_b = workers
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=9)

        from app.platform.cache import revocation
        import app.platform.cache.provider as provider_module

        original = provider_module._cache_provider
        provider_module._cache_provider = worker_a
        try:
            assert await revocation.current_revocation_generation(db) == 9
            # Published, so the sibling worker reading Redis sees it without its
            # own database round-trip.
            assert await worker_a.get(revocation.REVOCATION_GENERATION_CACHE_KEY) == 9
        finally:
            provider_module._cache_provider = original

    async def test_the_recovery_signal_is_consumed_once(self, workers):
        """The database read happens once per outage, not once per request."""
        _worker_a, worker_b = workers
        _open_circuit(worker_b)
        assert await worker_b._circuit_open() is True

        _close_circuit(worker_b)
        assert await worker_b._circuit_open() is False
        assert worker_b.consume_recovery_signal() is True
        assert worker_b.consume_recovery_signal() is False

    async def test_no_outage_raises_no_signal(self, workers):
        worker_a, _worker_b = workers
        assert await worker_a._circuit_open() is False
        assert worker_a.consume_recovery_signal() is False


class TestTheValidatorRefusesAStaleGeneration:
    """The comparison, driven through validate_embed_token_access itself.

    The provider-level tests above show the generation crosses workers; this one
    shows the validator acts on it. Counterfactual: delete the generation
    comparison from validate_embed_token_access and the first test returns True
    off the stale entry.
    """

    async def _validate(self, cache, generation: int, *, token_row):
        from app.modules.embed_tokens import service as embed_service

        result = MagicMock()
        result.scalar_one_or_none.return_value = token_row
        db = AsyncMock()
        db.execute.return_value = result

        with (
            patch.object(embed_service, "get_cache", return_value=cache),
            patch.object(
                embed_service,
                "current_revocation_generation",
                AsyncMock(return_value=generation),
            ),
            patch.object(
                embed_service, "map_contains_dataset", AsyncMock(return_value=True)
            ),
            patch.object(
                embed_service,
                "_request_origin_is_allowed",
                AsyncMock(return_value=True),
            ),
            patch.object(
                embed_service,
                "_bump_embed_token_usage_detached",
                AsyncMock(return_value=None),
            ),
        ):
            verdict = await embed_service.validate_embed_token_access(
                RAW_TOKEN, DATASET_ID, db
            )
        pending = [t for t in embed_service._usage_bump_tasks if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        return verdict

    def _positive(self, generation: int) -> dict:
        return {
            "is_valid": True,
            "scoped_dataset_ids": [str(DATASET_ID)],
            "allowed_origins": None,
            "map_id": str(uuid.uuid4()),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "tenant_id": None,
            "generation": generation,
        }

    async def test_an_entry_from_before_the_revoke_is_refused(self):
        """Worker B's entry was minted at generation 4; A revoked during the
        outage and the database is now at 5. The row is gone, so the
        re-validation denies."""
        cache = InMemoryCacheProvider()
        await cache.set(TOKEN_KEY, self._positive(4), 300)

        assert await self._validate(cache, 5, token_row=None) is False

    async def test_a_current_entry_is_still_trusted(self):
        """The comparison must refuse a STALE stamp, not every stamp."""
        cache = InMemoryCacheProvider()
        await cache.set(TOKEN_KEY, self._positive(5), 300)

        assert await self._validate(cache, 5, token_row=None) is True, (
            "a current entry was re-validated against the database, which "
            "would make the cache pointless"
        )

    async def test_an_unstamped_pre_upgrade_entry_is_refused(self):
        entry = self._positive(5)
        del entry["generation"]
        cache = InMemoryCacheProvider()
        await cache.set(TOKEN_KEY, entry, 300)

        assert await self._validate(cache, 5, token_row=None) is False
