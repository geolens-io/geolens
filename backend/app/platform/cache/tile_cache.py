"""Binary tile cache: Redis-backed primary + in-memory LRU fallback.

Stores gzip-compressed MVT tile bytes with configurable TTL, using
``decode_responses=False`` for binary-safe storage (unlike the JSON-based
RedisCacheProvider). All Redis errors are caught and logged, never
propagated to callers.

When ``REDIS_URL`` is unset, ``InMemoryTileCacheProvider`` gives an
LRU fallback bounded by bytes with matching TTL semantics (default 300s,
per-call override).

Hit/miss counters carry a ``table_name`` label; ``_safe_label``
bounds cardinality by collapsing anything not matching the documented
``data.*`` shape to ``"_other"``.

fix(#1429): the ``table`` argument is the tile router's composite segment
(tenant id, dataset id, cluster params) and never matches ``_safe_label``'s
shape, so deriving the metric label from it collapsed everything to
``"_other"``. Readers now pass the bare table name separately as ``label``.
Invalidation is unaffected: the dataset id sits AFTER the table segment, so
``tile:{table}:*`` still matches every key for a table regardless of which
dataset wrote it.
"""

import re
import time

import redis.asyncio as redis_async
import structlog
from cachetools import LRUCache
from prometheus_client import Counter

from app.platform.redis_protocol import REDIS_PROTOCOL

logger = structlog.stdlib.get_logger(__name__)

# Per-table cache observability (cardinality bounded by _safe_label).
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
    """Bound Prometheus label cardinality: ``table`` if it matches
    the documented dataset-table shape, else ``"_other"`` so an unsanitized
    identifier can't pollute the Prometheus label index.
    """
    return table if _SAFE_TABLE_RE.match(table) else "_other"


def _invalidation_table_segment(table: str) -> str:
    """Return the exact cache-table segment visible to this tenant context."""
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return table
    tenant_id = current_tenant_var.get()
    tenant_data_schema(tenant_id)
    assert tenant_id is not None
    return f"{tenant_id.lower()}:{table}"


class TileCacheProvider:
    """Binary tile cache backed by Redis.

    Cache key format: ``tile:{table}:{z}:{x}:{y}``, where ``table`` is the
    composite table segment the tile router builds — see the module docstring.
    """

    def __init__(self, url: str) -> None:
        self._client = redis_async.from_url(
            url, decode_responses=False, protocol=REDIS_PROTOCOL
        )

    async def get(
        self,
        table: str,
        z: int,
        x: int,
        y: int,
        cols_key: str = "",
        label: str | None = None,
    ) -> bytes | None:
        """Return cached tile bytes or None on miss/error.

        `cols_key` differentiates tiles for the same table/z/x/y with
        different column projections; empty string preserves the original
        key shape. `label` is the bare table name for the metric.
        """
        suffix = f":{cols_key}" if cols_key else ""
        key = f"tile:{table}:{z}:{x}:{y}{suffix}"
        label = _safe_label(table if label is None else label)
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
        """Store tile bytes with TTL. Silent on failure.

        Takes no ``label``: writes emit no Prometheus metric, only reads do.
        """
        suffix = f":{cols_key}" if cols_key else ""
        key = f"tile:{table}:{z}:{x}:{y}{suffix}"
        try:
            await self._client.set(key, data, ex=ttl)
        except Exception:  # broad: redis client surfaces pool/timeout/io errors as varied types; cache write is non-fatal
            logger.warning("tile_cache_set_failed", key=key, exc_info=True)

    async def invalidate_table(self, table: str) -> bool:
        """Delete all cached tiles for a table; returns False on failure, never raises.

        Uses the exact active-tenant prefix; scanning ``tile:*:{table}:*``
        would let one tenant evict another's same-named dataset.
        """
        try:
            scoped_table = _invalidation_table_segment(table)
            pattern = f"tile:{scoped_table}:*"
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
            return False
        return True


# Tiles run from a few KB to several hundred KB on wide tables, so the budget
# is in bytes: a count bound could hold tens of gigabytes.
_MEMORY_TILE_BUDGET_BYTES = 256 * 1024 * 1024
_TILE_ENTRY_OVERHEAD_BYTES = 256


def _tile_entry_size(entry: tuple[bytes, float]) -> int:
    return len(entry[0]) + _TILE_ENTRY_OVERHEAD_BYTES


class InMemoryTileCacheProvider:
    """In-memory LRU fallback for tile cache when REDIS_URL is unset.

    LRU bounded by tile bytes + per-entry TTL.
    Interface matches ``TileCacheProvider`` -- same async
    ``get/set/invalidate_table`` signatures, so callers need zero changes.

    ``cachetools`` has no per-key TTL (``TTLCache`` is one global TTL), so
    entries are stored as ``(value, expires_at_monotonic)`` and checked on
    read; ``maxsize`` bounds bytes, expired entries drop lazily. A tile larger
    than the whole budget is not cached.
    """

    def __init__(self, max_bytes: int = _MEMORY_TILE_BUDGET_BYTES) -> None:
        self._cache: LRUCache[str, tuple[bytes, float]] = LRUCache(
            maxsize=max_bytes, getsizeof=_tile_entry_size
        )

    async def get(
        self,
        table: str,
        z: int,
        x: int,
        y: int,
        cols_key: str = "",
        label: str | None = None,
    ) -> bytes | None:
        """Return cached tile bytes or None on miss / TTL expiry."""
        suffix = f":{cols_key}" if cols_key else ""
        key = f"tile:{table}:{z}:{x}:{y}{suffix}"
        label = _safe_label(table if label is None else label)
        entry = self._cache.get(key)
        if entry is None:
            tile_cache_misses.labels(table_name=label).inc()
            return None
        data, expires_at = entry
        if time.monotonic() > expires_at:
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
        entry = (data, time.monotonic() + ttl)
        if _tile_entry_size(entry) > self._cache.maxsize:
            self._cache.pop(key, None)
            return
        self._cache[key] = entry

    async def invalidate_table(self, table: str) -> bool:
        """Delete all cached tiles for a table.

        Hosted invalidation is restricted to the active tenant's exact prefix;
        single-tenant deployments retain the historical bare-table shape.
        """
        scoped_table = _invalidation_table_segment(table)
        prefix = f"tile:{scoped_table}:"
        keys = [key for key in self._cache if key.startswith(prefix)]
        for k in keys:
            self._cache.pop(k, None)
        logger.info("tile_cache_invalidated", table=table)
        return True
