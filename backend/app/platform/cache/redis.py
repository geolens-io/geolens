import json
import time
from typing import Any

import redis.asyncio as redis_async
import structlog

from app.platform.cache.memory import InMemoryCacheProvider

logger = structlog.stdlib.get_logger(__name__)


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

    # ------------------------------------------------------------------
    # Circuit breaker helpers
    # ------------------------------------------------------------------

    def _is_circuit_open(self) -> bool:
        if self._failure_count < self._max_failures:
            return False
        return time.monotonic() < self._circuit_open_until

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
    # CacheProvider interface
    # ------------------------------------------------------------------

    async def get(self, key: str) -> Any | None:
        if self._is_circuit_open():
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
            return await self._fallback.get(key)

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        if self._is_circuit_open():
            await self._fallback.set(key, value, ttl)
            return
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl)
            self._record_success()
        except Exception:  # broad: redis circuit breaker — any Redis error falls back to in-memory cache
            logger.warning("redis_cache_set_failed", key=key, exc_info=True)
            self._record_failure()
            await self._fallback.set(key, value, ttl)

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

    async def delete(self, key: str) -> None:
        await self._fallback.delete(key)
        if self._is_circuit_open():
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
        if self._is_circuit_open():
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
        if self._is_circuit_open():
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
