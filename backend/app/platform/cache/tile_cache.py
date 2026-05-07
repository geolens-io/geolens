"""Binary Redis tile cache with Prometheus hit/miss counters.

Stores gzip-compressed MVT tile bytes in Redis with configurable TTL.
Uses decode_responses=False for binary-safe storage (unlike the main
RedisCacheProvider which uses JSON serialization).

Graceful degradation: all Redis errors are caught and logged, never
propagated to callers.

PERF-11 (Phase 274): the hit/miss counters carry a ``table_name`` label
so per-dataset cache hit ratios are observable in Prometheus.
Cardinality is bounded by ``_safe_label`` — any table identifier that
does not match the documented ``data.*`` shape (lowercase, starts with
a letter, ``[a-z0-9_]`` only, max 63 chars) is collapsed to the literal
``"_other"`` so a malicious or unexpected caller cannot explode the
metric label set.
"""

import re

import redis.asyncio as redis_async
import structlog
from prometheus_client import Counter

logger = structlog.stdlib.get_logger(__name__)

# PERF-11 (Phase 274): per-table cache observability. Cardinality
# protection: callers passing a table name not matching
# _SAFE_TABLE_RE get the literal "_other" label (see _safe_label).
tile_cache_hits = Counter(
    "geolens_tile_cache_hits_total",
    "Total tile cache hits",
    labelnames=["table_name"],
)
tile_cache_misses = Counter(
    "geolens_tile_cache_misses_total",
    "Total tile cache misses",
    labelnames=["table_name"],
)


# PostgreSQL identifier shape used for `data.*` dataset tables in this repo.
# Lowercase, starts with a letter, only [a-z0-9_], up to 63 chars (PG limit).
_SAFE_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _safe_label(table: str) -> str:
    """Bound Prometheus label cardinality (PERF-11).

    Returns ``table`` if it matches the documented dataset table shape,
    otherwise ``"_other"`` so an unsanitized identifier cannot pollute
    the Prometheus label index.
    """
    return table if _SAFE_TABLE_RE.match(table) else "_other"


class TileCacheProvider:
    """Binary tile cache backed by Redis.

    Cache key format: ``tile:{table}:{z}:{x}:{y}``
    """

    def __init__(self, url: str) -> None:
        self._client = redis_async.from_url(url, decode_responses=False)

    async def get(self, table: str, z: int, x: int, y: int) -> bytes | None:
        """Return cached tile bytes or None on miss/error."""
        key = f"tile:{table}:{z}:{x}:{y}"
        label = _safe_label(table)
        try:
            data = await self._client.get(key)
            if data is not None:
                tile_cache_hits.labels(table_name=label).inc()
                return data
            tile_cache_misses.labels(table_name=label).inc()
            return None
        except Exception:
            logger.warning("tile_cache_get_failed", key=key, exc_info=True)
            tile_cache_misses.labels(table_name=label).inc()
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
            logger.warning("tile_cache_invalidate_failed", table=table, exc_info=True)
