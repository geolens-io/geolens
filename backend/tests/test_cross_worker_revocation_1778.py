"""fix(#1778 codex r3/r4): a revoke on one Uvicorn worker has to reach the others.

``RedisCacheProvider``'s in-memory fallback and its authoritative-replay queue
are PROCESS-local, and production runs several workers behind one socket, so
every guarantee they make is a per-worker guarantee. The sequence that breaks:

  1. Redis goes down.
  2. Worker B validates embed token T and caches a positive.
  3. Worker A revokes T. The denial goes to A's fallback and A's replay queue.
     B knows about neither.
  4. B keeps serving T.
  5. Redis recovers, still holding the pre-outage positive, because A's replay
     has not run and may never run if A gets no traffic. B reads it.

Two mechanisms close it. ``security=True`` stops steps 2 and 4: an authorization
positive is never taken from a process-local store, so during an outage every
validation falls through to the database. The transactional revocation
generation closes step 5: the revoke advanced a counter row in the same
transaction as the ``is_active`` flip, and B refuses any entry stamped behind it.

The provider-level cases build TWO providers over ONE fakeredis, which is what
"two workers, one Redis" means in a single process; they deliberately do not
share a fallback, because that is the whole point.

fix(#1778 codex r4): the generation cases now use REAL database sessions and the
production call order. The earlier drafts called ``_circuit_open()`` before
consuming a recovery signal, which is not what a request does, and that masked
the defect where the first request after a lapsed cooldown read a stale
generation. The signal is gone; the counter is read from the database on every
validation.
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
from sqlalchemy import text

from app.platform.cache.memory import InMemoryCacheProvider
from app.platform.cache.redis import RedisCacheProvider
from app.platform.cache.revocation import (
    bump_revocation_generation,
    current_revocation_generation,
)

pytestmark = pytest.mark.anyio

KEY = "embed_token:" + ("a" * 64)

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
    return provider


def _open_circuit(provider) -> None:
    provider._failure_count = provider._max_failures
    provider._circuit_open_until = time.monotonic() + 300


@pytest.fixture
def workers():
    shared_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return _worker(shared_redis), _worker(shared_redis)


class TestSecurityReadsNeverComeFromLocalMemory:
    async def test_an_outage_denies_a_security_positive_from_the_fallback(
        self, workers
    ):
        """Steps 2 and 4: worker B cannot answer from its own memory.

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

        stored = await worker_b.set_if_absent(
            KEY, {"is_valid": True}, 300, security=True
        )
        assert stored is False
        assert await worker_b._fallback.get(KEY) is None

    async def test_a_refusal_may_still_come_from_the_queue(self, workers):
        """Refusing on stale information is fail-closed, so the queued override
        is exempt from the rule above."""
        _worker_a, worker_b = workers
        _open_circuit(worker_b)
        await worker_b.set_authoritative(KEY, {"is_valid": False}, 300)

        assert await worker_b.get(KEY, security=True) == {"is_valid": False}


class TestTheGenerationIsTransactional:
    """fix(#1778 codex r4): the counter and the is_active flip become visible in
    the same instant, so no interleaving can cache a positive that outlives the
    revocation it raced.

    These use real sessions against the test database. Counterfactual for the
    interleaving case: make bump_revocation_generation non-transactional (a
    sequence nextval, or a side session that commits on its own) and
    test_a_positive_cached_during_an_uncommitted_revoke_is_refused_after_commit
    fails, because the racing reader stamps its entry with the post-revoke
    generation.
    """

    async def _generation(self, session) -> int:
        return await current_revocation_generation(session)

    async def test_a_bump_is_invisible_until_the_transaction_commits(
        self, test_db_session, clean_tables
    ):
        import app.core.db as db_module

        before = await self._generation(test_db_session)

        async with db_module.async_session() as revoker:
            bumped = await bump_revocation_generation(revoker)
            assert bumped == before + 1

            # A separate session must still see the OLD value: the revocation
            # this stands for has not committed either.
            async with db_module.async_session() as reader:
                assert await self._generation(reader) == before

            await revoker.commit()

        async with db_module.async_session() as reader:
            assert await self._generation(reader) == before + 1

    async def test_a_rolled_back_revoke_leaves_the_generation_alone(
        self, test_db_session, clean_tables
    ):
        """The counter stands for a revocation. If that did not happen, neither
        did this."""
        import app.core.db as db_module

        before = await self._generation(test_db_session)

        async with db_module.async_session() as revoker:
            await bump_revocation_generation(revoker)
            await revoker.rollback()

        async with db_module.async_session() as reader:
            assert await self._generation(reader) == before

    async def test_a_positive_cached_during_an_uncommitted_revoke_is_refused_after_commit(
        self, test_db_session, clean_tables
    ):
        """The interleaving P1b describes, driven with real sessions.

        A validator reads the generation and the token row while the revoke is
        in flight, so it legitimately sees an active row and caches a positive.
        What must not happen is that entry surviving the commit.
        """
        import app.core.db as db_module

        cache = InMemoryCacheProvider()

        async with db_module.async_session() as revoker:
            # The revoke has flipped is_active and advanced the counter, and has
            # NOT committed.
            await bump_revocation_generation(revoker)

            # A concurrent validator, on another worker, in its own transaction.
            async with db_module.async_session() as validator:
                stamped = await self._generation(validator)
                await cache.set(
                    TOKEN_KEY, {"is_valid": True, "generation": stamped}, 300
                )

            await revoker.commit()

        # After the commit every worker reads the new generation, and the entry
        # the racer left behind no longer matches it.
        async with db_module.async_session() as reader:
            now = await self._generation(reader)

        cached = await cache.get(TOKEN_KEY)
        assert cached["generation"] != now, (
            "a positive cached during the uncommitted revoke still matched the "
            "generation after commit, so every worker would keep serving it"
        )

    async def test_the_generation_never_consults_the_cache(
        self, test_db_session, clean_tables
    ):
        """fix(#1778 codex r4): the P1a defect, made structurally impossible.

        The earlier draft cached this number in Redis and re-read it from the
        database only when a circuit-breaker transition said to. Nothing detects
        a lapsed cooldown until some cache method looks, so the FIRST request
        after recovery consumed a signal that had not been raised yet, read the
        stale Redis value, and accepted a pre-outage positive. There is no call
        order that fixes a value which can simply be behind.

        So the module reads the counter from the database, full stop.

        Asserted against the SOURCE rather than by patching ``get_cache``.
        Patching only catches a lazy, in-function import; a module-level
        ``from app.platform.cache.provider import get_cache`` binds its own
        reference and would sail straight past a patched attribute, which is
        exactly the shape someone would add when "just caching it again" looks
        like an optimization.
        """
        import ast
        import inspect

        from app.platform.cache import revocation

        source = inspect.getsource(revocation)
        tree = ast.parse(source)

        reached: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "cache.provider" in node.module or node.module.endswith("cache"):
                    reached.append(f"import from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "cache.provider" in alias.name:
                        reached.append(f"import {alias.name}")
            elif isinstance(node, ast.Name) and node.id == "get_cache":
                reached.append("reference to get_cache")

        assert not reached, (
            "platform/cache/revocation.py reached the cache: "
            f"{sorted(set(reached))}. A cached generation can be stale-low, "
            "which makes a revoked entry compare equal and be served; that is "
            "the defect fix(#1778 codex r4) removed by reading the database."
        )

        # And it still answers, from the database.
        assert await self._generation(test_db_session) >= 1

    async def test_a_missing_counter_row_refuses_every_stamp(
        self, test_db_session, clean_tables
    ):
        """Fail closed: a counter that cannot be read matches no entry."""
        import app.core.db as db_module

        async with db_module.async_session() as session:
            await session.execute(
                text("DELETE FROM catalog.security_revocation_generation")
            )
            assert await self._generation(session) == -1
            await session.rollback()


class TestTheValidatorRefusesAStaleGeneration:
    """The comparison, driven through validate_embed_token_access itself.

    Counterfactual: delete the generation comparison from
    validate_embed_token_access and the first two tests return True off the
    stale entry.
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
        cache = InMemoryCacheProvider()
        await cache.set(TOKEN_KEY, self._positive(4), 300)

        assert await self._validate(cache, 5, token_row=None) is False

    async def test_an_unstamped_pre_upgrade_entry_is_refused(self):
        entry = self._positive(5)
        del entry["generation"]
        cache = InMemoryCacheProvider()
        await cache.set(TOKEN_KEY, entry, 300)

        assert await self._validate(cache, 5, token_row=None) is False

    async def test_a_current_entry_is_still_trusted(self):
        """The comparison must refuse a STALE stamp, not every stamp."""
        cache = InMemoryCacheProvider()
        await cache.set(TOKEN_KEY, self._positive(5), 300)

        assert await self._validate(cache, 5, token_row=None) is True, (
            "a current entry was re-validated against the database, which "
            "would make the cache pointless"
        )
