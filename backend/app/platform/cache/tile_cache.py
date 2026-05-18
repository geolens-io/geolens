"""Binary tile cache: Redis-backed primary + in-memory LRU fallback.

Stores gzip-compressed MVT tile bytes with configurable TTL.

The primary path uses ``decode_responses=False`` for binary-safe storage
(unlike the main RedisCacheProvider which uses JSON serialization).
Graceful degradation: all Redis errors are caught and logged, never
propagated to callers.

PERF-01 (Phase 274): when ``REDIS_URL`` is unset (zero-config or
single-VPS deployment shape) ``InMemoryTileCacheProvider`` provides a
bounded LRU fallback so tile responses still get cached. Capacity is
sized at ~50k entries (~200MB at ~4KB / MVT tile) and TTL semantics
match Redis (default 300s, per-call override accepted).

PERF-11 (Phase 274): the hit/miss counters carry a ``table_name`` label
so per-dataset cache hit ratios are observable in Prometheus.
Cardinality is bounded by ``_safe_label`` — any table identifier that
does not match the documented ``data.*`` shape (lowercase, starts with
a letter, ``[a-z0-9_]`` only, max 63 chars) is collapsed to the literal
``"_other"`` so a malicious or unexpected caller cannot explode the
metric label set.
"""

import re
import time

import redis.asyncio as redis_async
import structlog
from cachetools import LRUCache  # PERF-01 (Phase 274)
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

    async def get(
        self, table: str, z: int, x: int, y: int, cols_key: str = ""
    ) -> bytes | None:
        """Return cached tile bytes or None on miss/error.

        `cols_key` differentiates tiles for the same table/z/x/y but with
        different additional column projections (data-driven styling).
        Empty string preserves the original cache key shape for callers
        that don't pass additional columns.
        """
        suffix = f":{cols_key}" if cols_key else ""
        key = f"tile:{table}:{z}:{x}:{y}{suffix}"
        label = _safe_label(table)
        try:
            data = await self._client.get(key)
            if data is not None:
                tile_cache_hits.labels(table_name=label).inc()
                return data
            tile_cache_misses.labels(table_name=label).inc()
            return None
        except Exception:  # broad: redis client surfaces pool/timeout/io errors as varied types; cache miss is non-fatal
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
        cols_key: str = "",
    ) -> None:
        """Store tile bytes with TTL. Silent on failure."""
        suffix = f":{cols_key}" if cols_key else ""
        key = f"tile:{table}:{z}:{x}:{y}{suffix}"
        try:
            await self._client.set(key, data, ex=ttl)
        except Exception:  # broad: redis client surfaces pool/timeout/io errors as varied types; cache write is non-fatal
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
        except Exception:  # broad: redis SCAN/DELETE can throw varied pool/timeout errors; invalidation is non-fatal
            logger.warning("tile_cache_invalidate_failed", table=table, exc_info=True)


class InMemoryTileCacheProvider:
    """In-memory LRU fallback for tile cache when REDIS_URL is unset.

    PERF-01 (Phase 274): bounded LRU + per-entry TTL so smaller
    single-VPS deployments get tile-cache benefits without running
    Redis. Capacity sized at ~50k entries (~200MB at ~4KB / tile).

    Interface is identical to ``TileCacheProvider`` so callers in
    ``processing/tiles/router.py`` and ``modules/catalog/features/router.py``
    need zero changes — both providers expose the same async
    ``get/set/invalidate_table`` signatures.

    TTL semantics: ``cachetools`` does not natively support per-key TTL
    in ``LRUCache`` (and ``TTLCache`` only supports a single global TTL),
    so we store ``(value, expires_at_monotonic)`` tuples and check
    expiry on read. The cache itself bounds memory via ``maxsize``
    eviction; expired entries are dropped lazily on next access.
    """

    def __init__(self, max_entries: int = 50_000) -> None:
        # Stores (data: bytes, expires_at_monotonic: float) tuples.
        self._cache: LRUCache[str, tuple[bytes, float]] = LRUCache(maxsize=max_entries)

    async def get(
        self, table: str, z: int, x: int, y: int, cols_key: str = ""
    ) -> bytes | None:
        """Return cached tile bytes or None on miss / TTL expiry."""
        suffix = f":{cols_key}" if cols_key else ""
        key = f"tile:{table}:{z}:{x}:{y}{suffix}"
        label = _safe_label(table)
        entry = self._cache.get(key)
        if entry is None:
            tile_cache_misses.labels(table_name=label).inc()
            return None
        data, expires_at = entry
        if time.monotonic() > expires_at:
            # Expired — drop and report miss
            self._cache.pop(key, None)
            tile_cache_misses.labels(table_name=label).inc()
            return None
        tile_cache_hits.labels(table_name=label).inc()
        return data

    async def set(
        self,
        table: str,
        z: int,
        x: int,
        y: int,
        data: bytes,
        ttl: int = 300,
        cols_key: str = "",
    ) -> None:
        """Store tile bytes with TTL. LRU evicts oldest when at capacity."""
        suffix = f":{cols_key}" if cols_key else ""
        key = f"tile:{table}:{z}:{x}:{y}{suffix}"
        self._cache[key] = (data, time.monotonic() + ttl)

    async def invalidate_table(self, table: str) -> None:
        """Delete all cached tiles for a table."""
        prefix = f"tile:{table}:"
        keys = [k for k in self._cache if k.startswith(prefix)]
        for k in keys:
            self._cache.pop(k, None)
        logger.info("tile_cache_invalidated", table=table)
