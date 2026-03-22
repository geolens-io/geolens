import json
import time
from typing import Any

import redis.asyncio as redis_async
import structlog

from app.cache.memory import InMemoryCacheProvider

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
        except Exception:
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
        except Exception:
            logger.warning("redis_cache_set_failed", key=key, exc_info=True)
            self._record_failure()
            await self._fallback.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        if self._is_circuit_open():
            await self._fallback.delete(key)
            return
        try:
            await self._client.delete(key)
            self._record_success()
        except Exception:
            logger.warning("redis_cache_delete_failed", key=key, exc_info=True)
            self._record_failure()
            await self._fallback.delete(key)

    async def delete_pattern(self, pattern: str) -> None:
        if self._is_circuit_open():
            await self._fallback.delete_pattern(pattern)
            return
        try:
            async for key in self._client.scan_iter(match=pattern):
                await self._client.delete(key)
            self._record_success()
        except Exception:
            logger.warning(
                "redis_cache_delete_pattern_failed",
                pattern=pattern,
                exc_info=True,
            )
            self._record_failure()
            await self._fallback.delete_pattern(pattern)

    async def health_check(self) -> None:
        """Verify Redis is reachable via PING.

        Bypasses the circuit breaker so /health reflects actual Redis state.
        """
        await self._client.ping()
