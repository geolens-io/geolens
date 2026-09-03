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

# fix(#1778 codex r2): how many authoritative writes may wait for Redis to come
# back before the oldest are dropped. Each entry is one key plus a small JSON
# value, so this is kilobytes rather than megabytes; the point of the bound is
# that a long outage under a revocation storm cannot grow the process without
# limit. Dropping the OLDEST is the right end to lose: an entry that has waited
# longest is closest to its own expiry, after which replaying it would be a
# no-op anyway.
_MAX_PENDING_AUTHORITATIVE = 512


class RedisCacheProvider:
    """Redis/Valkey cache provider with circuit breaker and graceful fallback.

    Redis failure never crashes the application -- every method wraps Redis calls
    in try/except, logs a warning, and falls back to an in-memory cache.

    Circuit breaker: after ``max_failures`` consecutive Redis errors the provider
    stops contacting Redis for ``cooldown_seconds``, routing all operations to
    the in-memory fallback.  After the cooldown a single probe request tests
    Redis; success resets the circuit, failure re-enters cooldown.

    ``health_check()`` always bypasses the circuit breaker so ``/health``
    reflects actual Redis state.

    Which writes survive an outage
    ------------------------------

    fix(#1778 codex r2): every method that writes to Redis can find the circuit
    open, and they do NOT all mean the same thing by that, so each one's
    behaviour is stated here rather than left to be inferred:

    * ``set_authoritative`` -- REPLAYED. It overrides a value that may still be
      sitting in Redis, so "the write did not happen" is not a safe outcome. A
      revocation's denial written only to the fallback was silently undone the
      moment the circuit closed and reads went back to Redis, which still held
      the pre-revocation positive for the rest of its TTL. Writes that cannot
      reach Redis are queued in ``_pending_authoritative`` and drained into
      Redis on the transition back to closed, BEFORE the call that observed the
      transition is served. Until the drain lands, ``get`` answers from the
      queue, so the denial wins even against a Redis positive that is still
      there.
    * ``set`` -- fire-and-forget. It publishes a cached ANSWER, not a decision.
      If Redis never took it, the next read is a miss and the caller re-derives
      the value, which is correct and cheap. Replaying it would be worse than
      useless: it would resurrect a snapshot taken before the outage over
      whatever is true now.
    * ``set_if_absent`` -- fire-and-forget, and deliberately so. Its whole
      contract is to yield to a decision another writer may have made, so
      replaying it after recovery would re-publish a positive that a revocation
      may have superseded while Redis was away. That is the exact bug this
      machinery exists to close, running backwards. It answers False on a Redis
      error rather than pretending to have published.
    * ``delete`` / ``delete_many`` / ``delete_pattern`` -- fire-and-forget on
      the Redis half; the fallback half always happens, and any queued
      authoritative write for the same key is discarded with it. A delete issued
      during an outage does not reach Redis, so that entry lives out its TTL
      there. This is bounded staleness on a cached answer, and it is why a
      caller whose eviction carries an AUTHORIZATION decision uses
      ``set_authoritative`` instead of ``delete`` -- which is what the embed
      token revoke path does. A replay queue for deletes was considered and
      rejected: a queued delete drained after recovery cannot tell a pre-outage
      entry from one a legitimate writer put there after the outage ended, so it
      would evict live data in order to fix stale data.

    Why none of that is enough on its own
    -------------------------------------

    fix(#1778 codex r3): every guarantee above is PROCESS-local, and production
    runs several Uvicorn workers. The fallback and the replay queue live in one
    worker's memory, so during an outage worker A can revoke a capability and
    queue the denial in A alone while worker B still holds a positive for it,
    and after recovery B can read the pre-revocation positive straight out of
    Redis before A's replay has run. No amount of care inside one process closes
    that, because the two processes share nothing.

    Two things do:

    * ``security=True`` on ``get`` / ``set`` / ``set_if_absent``. A positive
      AUTHORIZATION decision is then never taken from, or written to, the
      process-local fallback; when Redis is unreachable the read answers None
      and the caller re-derives from the database. A refusal is exempt, because
      refusing on stale information is fail-closed.
    * ``platform/cache/revocation.py``, a database-backed generation every
      revoke advances and every positive entry is stamped with. It uses
      ``consume_recovery_signal()`` below to notice that this worker was cut off
      and to re-read the generation from the database, which is the store that
      stayed up.

    Callers that MUST pass ``security=True``, enumerated so the list can be
    checked rather than inferred (``tests/test_layering.py::
    test_authorization_cache_reads_are_security_scoped`` pins it):

    * ``app/modules/embed_tokens/service.py`` -- ``validate_embed_token_access``
      reads and writes the embed-token validation entry, which is the only value
      cached through this provider that decides access to private data. Its
      revoke paths write through ``set_authoritative``, which is security-shaped
      by construction and takes no flag.

    Everything else routed through this provider is a cached ANSWER, not a
    decision: catalog and collection listings, search results, persistent
    config. A stale one of those is a correctness annoyance bounded by its TTL,
    not a capability someone still holds.
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
        # key -> (value, ttl, monotonic expiry). Ordered so the bound drops the
        # oldest; keyed so a later authoritative write for the same key
        # supersedes the earlier one rather than queueing behind it.
        self._pending_authoritative: OrderedDict[str, tuple[Any, int, float]] = (
            OrderedDict()
        )
        self._replay_lock = asyncio.Lock()
        # fix(#1778 codex r3): _was_open tracks whether this worker has been cut
        # off from Redis; _recovery_signal is raised on the transition back and
        # cleared by consume_recovery_signal(). It is how a caller that HAS a
        # database session learns this worker cannot know what happened while it
        # was away, and must re-read what it was trusting Redis for.
        self._was_open = False
        self._recovery_signal = False

    # ------------------------------------------------------------------
    # Circuit breaker helpers
    # ------------------------------------------------------------------

    def _is_circuit_open(self) -> bool:
        if self._failure_count < self._max_failures:
            return False
        return time.monotonic() < self._circuit_open_until

    async def _circuit_open(self) -> bool:
        """``_is_circuit_open``, plus the drain on the transition back to closed.

        fix(#1778 codex r2): every public method asks through here, so the queued
        authoritative writes are replayed by whichever call first observes Redis
        as usable again -- a read included, which is what makes "before any
        primary read is served" true rather than aspirational. The cooldown
        expiry is not a function anyone calls, it is a timestamp going stale, so
        there is no other transition point to hook.
        """
        if self._is_circuit_open():
            self._was_open = True
            return True
        if self._was_open:
            # fix(#1778 codex r3): raised BEFORE the drain, so a reader that
            # consumes it is not overtaken by a replay that has not run yet.
            # Every process-local guarantee this class makes is a per-worker
            # guarantee, and an outage is exactly when the workers stop agreeing.
            self._was_open = False
            self._recovery_signal = True
        if self._pending_authoritative:
            await self._replay_pending_authoritative()
            # The drain talks to Redis, so it can reopen the circuit itself.
            return self._is_circuit_open()
        return False

    def consume_recovery_signal(self) -> bool:
        """True once per transition out of an outage, then False again.

        fix(#1778 codex r3): read by ``platform/cache/revocation.py``, which
        holds a database session and can therefore do what this class cannot --
        re-read the revocation generation from the one store that stayed up, and
        rewrite the Redis copy. Consuming is destructive so that the database
        read happens once per outage rather than once per request.
        """
        signal = self._recovery_signal
        self._recovery_signal = False
        return signal

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

    # ------------------------------------------------------------------
    # Authoritative-write replay (fix(#1778 codex r2))
    # ------------------------------------------------------------------

    def _queue_authoritative_replay(self, key: str, value: Any, ttl: int) -> None:
        """Remember an authoritative write Redis did not take.

        The overflow log never names a key: these are cache keys derived from
        credential hashes, and a dropped-entry warning is not a reason to put one
        in the application log. The count is what an operator needs.
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

        Serialized on ``_replay_lock`` so two coroutines that observe the
        transition together cannot both drain, and so no call is served off a
        half-drained queue. The lock is only reached when something is queued,
        which is never the case on the ordinary hot path.

        Each entry is replayed with its REMAINING lifetime rather than a fresh
        TTL: the point is to make Redis agree with the decision, not to extend
        it. An entry whose lifetime has already elapsed is dropped, because
        writing it would be a no-op that expires immediately.
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
                except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
                    # Redis is not actually back. Leave this entry and the rest
                    # queued; reads keep answering from the queue until a later
                    # call drains it.
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

    # ------------------------------------------------------------------
    # CacheProvider interface
    # ------------------------------------------------------------------

    async def get(self, key: str, *, security: bool = False) -> Any | None:
        circuit_open = await self._circuit_open()

        # fix(#1778 codex r2): a queued authoritative write outranks BOTH stores
        # until it has been replayed. Without this, the window between the
        # circuit closing and the drain completing serves the pre-outage Redis
        # value, and for a revoked embed token that value is a positive.
        #
        # This one is served even for a security read: a queued override is a
        # REVOCATION, and refusing on stale information is the fail-closed
        # direction. It is the positive that must never come from local memory.
        found, pending_value = self._pending_authoritative_value(key)
        if found:
            return pending_value

        if circuit_open:
            # fix(#1778 codex r3): the fallback is THIS WORKER's memory. For an
            # authorization decision that is not good enough -- another worker
            # may have revoked while Redis was away, and this process cannot
            # have heard about it. Answering None sends the caller to the
            # database, which is the only store all the workers share.
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
            # fix(#1778 codex r3): a security entry in the fallback can never be
            # served (see `get`), so writing one is dead weight that only invites
            # a future reader to trust it.
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
        """fix(#1778 codex r1): write BOTH stores, in either circuit state.

        ``set`` routes to whichever store the circuit says is live, which is
        right for a value that is only a cached answer and wrong for one that
        overrides a cached answer. A positive embed-token entry written into the
        fallback during a Redis outage outlived a revocation that only reached
        Redis, and the next Redis error served the revoked token again.

        The fallback is written first and unconditionally, so a Redis failure
        cannot leave the override applied nowhere.

        fix(#1778 codex r2): "both stores" has to survive the outage, not just
        the moment. When Redis cannot be reached -- circuit open, or the write
        itself raising -- the override is queued for replay rather than dropped,
        because Redis may still be holding the very value this call exists to
        overrule. Until the queue drains, ``get`` answers from it.
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
        store: the caller is publishing a value it wants a concurrent writer to
        be able to override, and a copy in a process-local dict that no other
        process can override is not that. False means "not published", which is
        a cache miss next time -- the safe direction. Never replayed after an
        outage, for the same reason; see the class docstring.

        fix(#1778 codex r1): the fallback is checked first, in BOTH circuit
        states. ``set_authoritative`` puts a revocation's denial in both stores,
        and a racing publisher that only consulted Redis would answer True the
        moment the circuit opened between its read and its write -- writing a
        positive into the fallback the denial had just cleared. Absent has to
        mean absent everywhere, which fix(#1778 codex r2) extends to the replay
        queue: an override still waiting for Redis is present too.
        """
        circuit_open = await self._circuit_open()
        found, _pending_value = self._pending_authoritative_value(key)
        if found:
            return False
        if await self._fallback.get(key) is not None:
            return False
        if circuit_open:
            # fix(#1778 codex r3): an authorization positive is never published
            # into this worker's memory. False reads as "not published", which
            # costs the caller one database re-derivation next time and is the
            # safe direction.
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

    # fix(#1778): codebase audit 2026-08-30, "Cache invalidation never reaches
    # the in-memory fallback, so a revoked embed token can be served as valid
    # during the next Redis blip".
    #
    # Reads and writes route to ONE store: whichever the circuit says is live.
    # Eviction must not, because the two stores are populated at different
    # times. A validation that ran while the circuit was open wrote its result
    # into the process-local fallback; the circuit then closed, an admin revoked
    # the capability, the delete went to Redis alone, and the fallback copy
    # survived. The next blip inside that entry's TTL serves it again. The
    # embed-token positive entry ({"is_valid": True, ...}, TTL up to 300s) is
    # the concrete case, and every authorization-shaped value cached through
    # this provider has the same shape.
    #
    # So every eviction hits BOTH stores in BOTH circuit states. The fallback is
    # an in-process dict, so the extra call costs nothing and cannot fail in a
    # way Redis's own error path does not already cover.
    #
    # fix(#1778 codex r2): an eviction also discards any queued authoritative
    # write for the same key. Replaying an override after the caller has said
    # the entry should not exist would put it back.

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
        # fix(#1543): DEL is variadic and executes as one command, so the whole
        # batch is evicted in a single round-trip that no concurrent client can
        # observe half-applied. Looping over `delete` instead would put a
        # network round-trip between every pair of keys.
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
