"""Binary Redis tile cache with Prometheus hit/miss counters.

Stores gzip-compressed MVT tile bytes in Redis with configurable TTL.
Uses decode_responses=False for binary-safe storage (unlike the main
RedisCacheProvider which uses JSON serialization).

Graceful degradation: all Redis errors are caught and logged, never
propagated to callers.
"""

import redis.asyncio as redis_async
import structlog
from prometheus_client import Counter

logger = structlog.stdlib.get_logger(__name__)

tile_cache_hits = Counter(
    "geolens_tile_cache_hits_total",
    "Total tile cache hits",
)
tile_cache_misses = Counter(
    "geolens_tile_cache_misses_total",
    "Total tile cache misses",
)


class TileCacheProvider:
    """Binary tile cache backed by Redis.

    Cache key format: ``tile:{table}:{z}:{x}:{y}``
    """

    def __init__(self, url: str) -> None:
        self._client = redis_async.from_url(url, decode_responses=False)

    async def get(
        self, table: str, z: int, x: int, y: int
    ) -> bytes | None:
        """Return cached tile bytes or None on miss/error."""
        key = f"tile:{table}:{z}:{x}:{y}"
        try:
            data = await self._client.get(key)
            if data is not None:
                tile_cache_hits.inc()
                return data
            tile_cache_misses.inc()
            return None
        except Exception:
            logger.warning("tile_cache_get_failed", key=key, exc_info=True)
            tile_cache_misses.inc()
            return None

    async def set(
        self,
        table: str,
        z: int,
        x: int,
        y: int,
        data: bytes,
        ttl: int = 300,
    ) -> None:
        """Store tile bytes with TTL. Silent on failure."""
        key = f"tile:{table}:{z}:{x}:{y}"
        try:
            await self._client.set(key, data, ex=ttl)
        except Exception:
            logger.warning("tile_cache_set_failed", key=key, exc_info=True)

    async def invalidate_table(self, table: str) -> None:
        """Delete all cached tiles for a table. Silent on failure."""
        pattern = f"tile:{table}:*"
        try:
            cursor = 0
            while True:
                cursor, keys = await self._client.scan(
                    cursor=cursor, match=pattern, count=500
                )
                if keys:
                    await self._client.delete(*keys)
                if cursor == 0:
                    break
            logger.info("tile_cache_invalidated", table=table)
        except Exception:
            logger.warning(
                "tile_cache_invalidate_failed", table=table, exc_info=True
            )
