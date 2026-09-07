import asyncio
import fnmatch
import json
import time
from collections import OrderedDict
from typing import Any

import redis.asyncio as redis_async
import structlog

from app.platform.cache.memory import InMemoryCacheProvider

logger = structlog.stdlib.get_logger(__name__)

# fix(#1778): caps queued authoritative writes so a long outage under a
# revocation storm can't grow the process unbounded. Drops the OLDEST
# first -- it's nearest its own TTL expiry, so replaying it would no-op.
_MAX_PENDING_AUTHORITATIVE = 512


class RedisCacheProvider:
    """Redis/Valkey cache provider with circuit breaker and graceful fallback.

    Every method wraps Redis calls in try/except, logs a warning, and falls
    back to an in-memory cache -- Redis failure never crashes the app.

    Circuit breaker: after ``max_failures`` consecutive errors, stop
    contacting Redis for ``cooldown_seconds`` and route to the fallback.
    After cooldown, the next call probes Redis; success resets the circuit,
    failure re-opens it. ``health_check()`` always bypasses the breaker so
    ``/health`` reflects actual Redis state.

    Which writes survive an outage (fix(#1778)):

    * ``set_authoritative`` -- REPLAYED. It overrides a value that may still
      be live in Redis, so a dropped write would let the outage undo a
      revocation once the circuit closes and reads resume from Redis. Writes
      that can't reach Redis queue in ``_pending_authoritative`` and drain on
      the transition back to closed, before the call that observed it is
      served; until then ``get`` answers from the queue.
    * ``set`` -- fire-and-forget. It caches an answer, not a decision: a miss
      just re-derives cheaply, and replaying would resurrect a pre-outage
      snapshot over what's true now.
    * ``set_if_absent`` -- fire-and-forget, deliberately: its contract is to
      yield to another writer's decision, so replaying after recovery could
      republish a positive a revocation had since superseded. Answers False
      on a Redis error rather than pretending to have published.
    * ``delete*`` -- fire-and-forget on the Redis half; the fallback half
      always runs, and any queued authoritative write for the same key is
      discarded with it. A delete during an outage lives out its TTL in
      Redis (bounded staleness), which is why an eviction that carries an
      authorization decision uses ``set_authoritative`` instead (the embed
      token revoke path). A replay queue for deletes was rejected: a drained
      delete can't tell a stale entry from one a legitimate writer made
      after the outage, so it would evict live data to fix stale data.

    None of that is enough alone (fix(#1778)): the fallback and replay queue
    are PROCESS-local, and production runs several workers -- worker A can
    revoke and queue a denial while worker B still holds a Redis positive,
    and after recovery B can read that stale positive before A's replay
    runs. Two things close that gap:

    * ``security=True`` on ``get``/``set``/``set_if_absent`` -- a positive
      AUTHORIZATION decision is never read from or written to the
      process-local fallback; an unreachable Redis answers None and the
      caller re-derives from the database. A refusal is exempt (fail-closed).
    * ``platform/cache/revocation.py``: a transactional DB counter read on
      every validation instead of cached here, because a per-worker cache of
      it would always be one outage behind.

    Callers that MUST pass ``security=True`` (pinned by
    ``tests/test_layering.py::test_authorization_cache_reads_are_security_scoped``):
    ``app/modules/embed_tokens/service.py``'s ``validate_embed_token_access``
    -- the only value here that decides access to private data (its revoke
    path uses ``set_authoritative``, which needs no flag). Everything else
    routed through this provider is a cached ANSWER (catalog/collection
    listings, search results, config) whose staleness is TTL-bounded, not a
    capability.
    """

    def __init__(
        self,
        url: str,
        max_failures: int = 5,
        cooldown_seconds: int = 30,
    ) -> None:
        self._client = redis_async.from_url(url, decode_responses=True)
        self._max_failures = max_failures
        self._cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._circuit_open_until = 0.0  # monotonic timestamp
        self._fallback = InMemoryCacheProvider()
        # key -> (value, ttl, expiry). Ordered so the bound drops the oldest;
        # keyed so a later write for the same key supersedes rather than queues.
        self._pending_authoritative: OrderedDict[str, tuple[Any, int, float]] = (
            OrderedDict()
        )
        self._replay_lock = asyncio.Lock()

    def _is_circuit_open(self) -> bool:
        if self._failure_count < self._max_failures:
            return False
        return time.monotonic() < self._circuit_open_until

    async def _circuit_open(self) -> bool:
        """``_is_circuit_open``, plus the drain on the transition back to closed.

        fix(#1778): every public method asks through here, so whichever call
        first observes Redis as usable again -- a read included -- replays the
        queued authoritative writes before being served itself.
        """
        if self._is_circuit_open():
            return True
        if self._pending_authoritative:
            await self._replay_pending_authoritative()
            # The drain talks to Redis, so it can reopen the circuit itself.
            return self._is_circuit_open()
        return False

    def _record_success(self) -> None:
        self._failure_count = 0

    def _record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self._max_failures:
            self._circuit_open_until = time.monotonic() + self._cooldown_seconds
            logger.warning(
                "redis_circuit_open",
                cooldown=self._cooldown_seconds,
                failures=self._failure_count,
            )

    def _queue_authoritative_replay(self, key: str, value: Any, ttl: int) -> None:
        """Remember an authoritative write Redis did not take.

        The overflow log omits the key (derived from a credential hash); the
        count is what an operator needs.
        """
        self._pending_authoritative.pop(key, None)
        self._pending_authoritative[key] = (value, ttl, time.monotonic() + ttl)

        dropped = 0
        while len(self._pending_authoritative) > _MAX_PENDING_AUTHORITATIVE:
            self._pending_authoritative.popitem(last=False)
            dropped += 1
        if dropped:
            logger.warning(
                "redis_cache_authoritative_replay_overflow",
                dropped=dropped,
                pending=len(self._pending_authoritative),
                limit=_MAX_PENDING_AUTHORITATIVE,
            )

    async def _replay_pending_authoritative(self) -> None:
        """Push queued authoritative writes into Redis, oldest first.

        Serialized on ``_replay_lock`` so two coroutines can't both drain, and
        no call is served off a half-drained queue.

        Each entry replays with its REMAINING lifetime, not a fresh TTL --
        the goal is to make Redis agree, not extend it. An expired entry is
        dropped rather than written as a no-op.
        """
        if not self._pending_authoritative:
            return
        async with self._replay_lock:
            while self._pending_authoritative:
                key, (value, _ttl, expires_at) = next(
                    iter(self._pending_authoritative.items())
                )
                remaining = int(expires_at - time.monotonic())
                if remaining <= 0:
                    self._pending_authoritative.pop(key, None)
                    continue
                try:
                    await self._client.set(
                        key, json.dumps(value, default=str), ex=remaining
                    )
                except (
                    Exception
                ):  # broad: redis unreachable; leave entries queued for next drain
                    logger.warning(
                        "redis_cache_authoritative_replay_failed",
                        pending=len(self._pending_authoritative),
                        exc_info=True,
                    )
                    self._record_failure()
                    return
                self._pending_authoritative.pop(key, None)
            self._record_success()

    def _pending_authoritative_value(self, key: str) -> tuple[bool, Any]:
        """``(found, value)`` for a queued authoritative write of *key*."""
        entry = self._pending_authoritative.get(key)
        if entry is None:
            return False, None
        value, _ttl, expires_at = entry
        if time.monotonic() >= expires_at:
            self._pending_authoritative.pop(key, None)
            return False, None
        return True, value

    async def get(self, key: str, *, security: bool = False) -> Any | None:
        circuit_open = await self._circuit_open()

        # fix(#1778): a queued authoritative write outranks BOTH stores until
        # replayed, or the circuit-close/drain window could re-serve a stale
        # Redis positive. Applies to security reads too: a queued entry is a
        # revocation, and refusing on stale data is fail-closed.
        found, pending_value = self._pending_authoritative_value(key)
        if found:
            return pending_value

        if circuit_open:
            # fix(#1778): the fallback is THIS WORKER's memory -- not enough
            # for an authorization decision another worker may have revoked.
            # None sends the caller to the database, the only shared store.
            if security:
                return None
            return await self._fallback.get(key)
        try:
            raw = await self._client.get(key)
            self._record_success()
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
            logger.warning("redis_cache_get_failed", key=key, exc_info=True)
            self._record_failure()
            if security:
                return None
            return await self._fallback.get(key)

    async def set(
        self, key: str, value: Any, ttl: int = 300, *, security: bool = False
    ) -> None:
        """Cache an answer. Not replayed after an outage; see the class docstring."""
        if await self._circuit_open():
            # fix(#1778): a security entry in the fallback can never be served
            # (see `get`) -- writing one only invites a future reader to trust it.
            if not security:
                await self._fallback.set(key, value, ttl)
            return
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl)
            self._record_success()
        except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
            logger.warning("redis_cache_set_failed", key=key, exc_info=True)
            self._record_failure()
            if not security:
                await self._fallback.set(key, value, ttl)

    async def set_authoritative(self, key: str, value: Any, ttl: int = 300) -> None:
        """fix(#1778): write BOTH stores, in either circuit state.

        ``set`` routes to whichever store the circuit says is live -- wrong
        for a value that overrides a cached answer (a positive left in the
        fallback during an outage outlived a Redis-only revocation and got
        served again on the next blip). The fallback is written first and
        unconditionally, so a Redis failure can't leave the override applied
        nowhere; when Redis can't be reached, the override queues for replay
        instead of being dropped, since Redis may still hold the very value
        this call exists to overrule. ``get`` answers from the queue until
        it drains.
        """
        await self._fallback.set(key, value, ttl)
        if await self._circuit_open():
            self._queue_authoritative_replay(key, value, ttl)
            return
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl)
            self._record_success()
        except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
            logger.warning(
                "redis_cache_set_authoritative_failed", key=key, exc_info=True
            )
            self._record_failure()
            self._queue_authoritative_replay(key, value, ttl)

    async def set_if_absent(
        self, key: str, value: Any, ttl: int = 300, *, security: bool = False
    ) -> bool:
        """fix(#1778): SET NX. True when this call is the one that stored it.

        A Redis error answers False rather than falling back to the in-memory
        store: a process-local copy can't be overridden by a concurrent
        writer, which breaks the "yield to another writer" contract. False
        means a cache miss next time -- the safe direction. Never replayed
        after an outage; see the class docstring.

        The fallback (and the replay queue) are checked first, in BOTH
        circuit states: ``set_authoritative`` can put a denial in both, and
        a racing publisher that only consulted Redis would answer True in
        the gap between its read and write. Absent must mean absent
        everywhere.
        """
        circuit_open = await self._circuit_open()
        found, _pending_value = self._pending_authoritative_value(key)
        if found:
            return False
        if await self._fallback.get(key) is not None:
            return False
        if circuit_open:
            # fix(#1778): an authorization positive is never published into
            # this worker's memory. False costs one DB re-derivation next time.
            if security:
                return False
            return await self._fallback.set_if_absent(key, value, ttl)
        try:
            stored = await self._client.set(
                key, json.dumps(value, default=str), ex=ttl, nx=True
            )
            self._record_success()
            return bool(stored)
        except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
            logger.warning("redis_cache_set_if_absent_failed", key=key, exc_info=True)
            self._record_failure()
            return False

    # fix(#1778): reads/writes route to ONE store (whichever the circuit says
    # is live), but eviction must not: a validation cached in the fallback
    # during an outage can outlive a revoke that only reached Redis once the
    # circuit closes, serving a revoked embed token on the next blip. So
    # every eviction hits BOTH stores in BOTH circuit states (the fallback
    # call is free) and also discards any queued authoritative write for the
    # key, so a queued override can't resurrect an entry just deleted.

    async def delete(self, key: str) -> None:
        await self._fallback.delete(key)
        self._pending_authoritative.pop(key, None)
        if await self._circuit_open():
            return
        try:
            await self._client.delete(key)
            self._record_success()
        except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
            logger.warning("redis_cache_delete_failed", key=key, exc_info=True)
            self._record_failure()

    async def delete_many(self, *keys: str) -> None:
        # fix(#1543): DEL is variadic -- one round-trip, so no concurrent
        # client can observe the batch half-applied (unlike looping `delete`).
        if not keys:
            return
        await self._fallback.delete_many(*keys)
        for key in keys:
            self._pending_authoritative.pop(key, None)
        if await self._circuit_open():
            return
        try:
            await self._client.delete(*keys)
            self._record_success()
        except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
            logger.warning(
                "redis_cache_delete_many_failed", keys=list(keys), exc_info=True
            )
            self._record_failure()

    async def delete_pattern(self, pattern: str) -> None:
        await self._fallback.delete_pattern(pattern)
        for key in [
            k for k in self._pending_authoritative if fnmatch.fnmatch(k, pattern)
        ]:
            self._pending_authoritative.pop(key, None)
        if await self._circuit_open():
            return
        try:
            async for key in self._client.scan_iter(match=pattern):
                await self._client.delete(key)
            self._record_success()
        except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
            logger.warning(
                "redis_cache_delete_pattern_failed",
                pattern=pattern,
                exc_info=True,
            )
            self._record_failure()

    async def health_check(self) -> None:
        """Verify Redis is reachable via PING.

        Bypasses the circuit breaker so /health reflects actual Redis state.
        """
        await self._client.ping()
