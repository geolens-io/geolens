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
    UNKNOWN_GENERATION,
    RevocationGenerationError,
    bump_revocation_generation,
    current_revocation_generation,
    is_usable_generation,
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

    async def test_a_deleted_counter_row_is_healed_and_the_heal_persists(
        self, test_db_session, clean_tables
    ):
        """fix(#1778 codex r6 P1): the heal must survive past the call that
        discovered the row missing. It runs on its own connection, committed
        independently of whatever session happens to be reading when it fires,
        so a second, unrelated session sees it too.

        The delete is committed before the heal runs, deliberately: round 5's
        test deleted and healed inside the SAME uncommitted session, which
        this fix turns into a deadlock rather than a false pass -- a second
        connection's ``INSERT ... ON CONFLICT`` blocks on the row lock an
        uncommitted DELETE from elsewhere still holds. A committed delete is
        also the only version of "the row is gone" any other worker's request
        can actually observe.

        Counterfactual: heal on the caller's own session (round 5's shape) and
        the row a second, independent session reads back is gone again.
        """
        import app.core.db as db_module

        async with db_module.async_session() as delete_session:
            await delete_session.execute(
                text("DELETE FROM catalog.security_revocation_generation")
            )
            await delete_session.commit()

        async with db_module.async_session() as reader_session:
            healed = await self._generation(reader_session)
            assert healed != UNKNOWN_GENERATION, "the row was not healed"

        async with db_module.async_session() as second_session:
            row = await second_session.scalar(
                text(
                    "SELECT generation FROM catalog.security_revocation_generation "
                    "WHERE id IS TRUE"
                )
            )
        assert row is not None, (
            "the healed row did not survive past the session that healed it"
        )
        assert row == healed

    async def test_a_deleted_counter_row_is_recreated_with_a_fresh_random_seed(
        self, test_db_session, clean_tables
    ):
        """fix(#1778 codex r6 P2): two heals must not produce the same
        generation. Round 5 seeded the heal from
        ``EXTRACT(EPOCH FROM clock_timestamp())::bigint`` -- whole wall-clock
        seconds -- so two heals landing in the same second reproduced the
        identical value, and a Redis positive stamped with the pre-delete
        generation would then compare equal to it and be trusted again after
        "recovery". A fleet under sustained revocation traffic can hit the
        same collision without any clock coincidence at all, by walking the
        counter's integer value past the current epoch-seconds count.

        Counterfactual: seed the heal from the epoch-seconds expression again
        and this fails whenever both heals land in the same wall-clock second,
        which a same-process test loop hits on essentially every run, not as
        a rare edge case.
        """
        import app.core.db as db_module
        from app.platform.cache.revocation import _reseed_missing_generation_row

        async def _delete_and_commit() -> None:
            async with db_module.async_session() as session:
                await session.execute(
                    text("DELETE FROM catalog.security_revocation_generation")
                )
                await session.commit()

        try:
            await _delete_and_commit()
            first = await _reseed_missing_generation_row()

            await _delete_and_commit()
            second = await _reseed_missing_generation_row()

            assert first != second, (
                "two heals produced the same generation -- an epoch-second "
                "seed collides with itself here, and a cache entry stamped "
                "with the pre-delete generation would wrongly compare equal "
                "to it after recovery"
            )
        finally:
            # Idempotent: a no-op if a row already exists (the ordinary case,
            # since the heals above each leave one behind), and the safety
            # net if an assertion above fired before the second heal ran.
            await _reseed_missing_generation_row()

    async def test_an_unreadable_counter_is_not_a_generation(self):
        """Fail closed: the sentinel must never compare equal to anything.

        Counterfactual: treat UNKNOWN_GENERATION as an ordinary value and two
        entries stamped with it match, which is how a positive cached while the
        counter was unreadable survived a later revocation.
        """
        broken = AsyncMock()
        broken.scalar = AsyncMock(side_effect=RuntimeError("counter unreachable"))

        assert await current_revocation_generation(broken) == UNKNOWN_GENERATION
        assert is_usable_generation(UNKNOWN_GENERATION) is False
        assert is_usable_generation(1) is True

    async def test_a_bump_that_cannot_advance_raises(
        self, test_db_session, clean_tables
    ):
        """fix(#1778 codex r5): a revocation nobody else can hear about must not
        quietly succeed. Raising rolls the caller back, ``is_active`` flip and
        all, so the operator sees a failed revoke instead of one half the fleet
        ignores."""
        import app.core.db as db_module

        async with db_module.async_session() as session:
            await session.execute(
                text("DELETE FROM catalog.security_revocation_generation")
            )
            with pytest.raises(RevocationGenerationError):
                await bump_revocation_generation(session)
            await session.rollback()

    async def test_a_revoke_fails_loudly_when_the_counter_is_gone(
        self, test_db_session, clean_tables
    ):
        """The same thing through the revoke helper the routers actually call."""
        import app.core.db as db_module
        from app.modules.embed_tokens import service as embed_service

        async with db_module.async_session() as session:
            await session.execute(
                text("DELETE FROM catalog.security_revocation_generation")
            )
            with pytest.raises(RevocationGenerationError):
                await embed_service._deny_revoked_embed_tokens(session, "a" * 64)
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

    async def test_an_entry_stamped_with_the_sentinel_is_never_trusted(self):
        """fix(#1778 codex r5): two entries stamped with the sentinel compared
        EQUAL, so a positive cached while the counter was unreadable survived a
        later revocation whose denial could not reach shared Redis."""
        cache = InMemoryCacheProvider()
        await cache.set(TOKEN_KEY, self._positive(UNKNOWN_GENERATION), 300)

        assert (
            await self._validate(cache, UNKNOWN_GENERATION, token_row=None) is False
        ), "a sentinel-stamped entry compared equal to an unreadable counter"

    async def test_an_unreadable_counter_refuses_a_perfectly_good_entry(self):
        """Not knowing whether anything was revoked means not trusting the
        cache, in either direction."""
        cache = InMemoryCacheProvider()
        await cache.set(TOKEN_KEY, self._positive(5), 300)

        assert await self._validate(cache, UNKNOWN_GENERATION, token_row=None) is False

    async def test_nothing_is_cached_while_the_counter_is_unreadable(self):
        """An entry stamped with the sentinel is one a future reader cannot
        check, so it is never written in the first place."""
        cache = InMemoryCacheProvider()
        token_row = MagicMock(
            id=uuid.uuid4(),
            map_id=uuid.uuid4(),
            allowed_origins=None,
            scoped_dataset_ids=[str(DATASET_ID)],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            tenant_id=None,
        )

        assert (
            await self._validate(cache, UNKNOWN_GENERATION, token_row=token_row) is True
        )
        assert await cache.get(TOKEN_KEY) is None, (
            "a positive was cached with a generation no reader can check it against"
        )


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTheHealSurvivesARealRequest:
    """fix(#1778 codex r6 P1): drives the heal through the real dependency
    chain -- an actual read request on ``get_db()`` -- rather than calling
    ``current_revocation_generation`` directly. Every production caller of
    that function is a read endpoint, and ``core/dependencies.py``'s
    ``get_db()`` commits NOTHING on a successful request; the assertion here
    is about what the request leaves behind, not what the function returns.
    """

    async def test_a_read_endpoints_heal_of_the_counter_row_survives_the_request(
        self, client, admin_auth_header, test_db_session
    ):
        """Counterfactual: heal on the request's own ``db`` session (round 5's
        shape) and the row a second, independent session reads back afterward
        is gone again -- the request's session never committed it.
        """
        from app.core.config import settings
        from tests.factories import get_user_id
        from tests.test_embed_tokens import (
            _cleanup_data_table,
            _create_data_table,
            _create_map_with_layer,
            _create_private_dataset,
        )

        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        table_name = f"embed_heal_{uuid.uuid4().hex[:8]}"
        dataset = await _create_private_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )
        map_obj, _ = await _create_map_with_layer(
            test_db_session, client, admin_auth_header, dataset, created_by=user_id
        )
        await _create_data_table(test_db_session, table_name)

        try:
            create_resp = await client.post(
                f"/maps/{map_obj.id}/embed-tokens/",
                json={},
                headers=admin_auth_header,
            )
            assert create_resp.status_code == 201
            raw_token = create_resp.json()["raw_token"]

            await test_db_session.execute(
                text("DELETE FROM catalog.security_revocation_generation")
            )
            await test_db_session.commit()

            tile_resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                headers={"X-Embed-Token": raw_token},
            )
            assert tile_resp.status_code in (200, 204), (
                "the read request itself must still succeed while the counter "
                "row is missing -- validate_embed_token_access falls through "
                "to the database and neither caches nor denies on an unusable "
                "generation"
            )

            import app.core.db as db_module

            async with db_module.async_session() as second_session:
                row = await second_session.scalar(
                    text(
                        "SELECT generation FROM catalog.security_revocation_generation "
                        "WHERE id IS TRUE"
                    )
                )
            assert row is not None, (
                "the counter row healed during the request did not survive "
                "past it -- the heal ran on the request's own get_db() "
                "session, which is never committed on a successful read"
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)
