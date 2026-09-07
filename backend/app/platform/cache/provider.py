from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

import structlog

if TYPE_CHECKING:
    from app.platform.cache.tile_cache import (
        InMemoryTileCacheProvider,
        TileCacheProvider,
    )

logger = structlog.stdlib.get_logger(__name__)


class CacheProvider(Protocol):
    """Provider-agnostic cache interface."""

    async def get(self, key: str, *, security: bool = False) -> Any | None:
        """Return cached value or None on miss.

        fix(#1778): a ``security=True`` positive can only come from a store
        every worker shares -- a layered provider must not answer it from a
        process-local fallback (unreachable shared store answers None; caller
        re-derives from the database). A REFUSAL is exempt: refusing on stale
        data is fail-closed, so it may come from a process-local fallback too.
        """
        ...

    async def set(
        self, key: str, value: Any, ttl: int = 300, *, security: bool = False
    ) -> None:
        """Store value with TTL in seconds.

        fix(#1778): ``security=True`` skips a layered provider's process-local
        fallback entirely -- a security positive can never be served from
        there, so caching one would only mislead a future reader.
        """
        ...

    async def set_if_absent(
        self, key: str, value: Any, ttl: int = 300, *, security: bool = False
    ) -> bool:
        """Store value with TTL only when *key* has no entry. True if stored.

        fix(#1778): the contract is "do not overwrite" -- a concurrent writer's
        decision must win (e.g. a revocation racing this write). Must be
        atomic against a concurrent writer of the same key (Redis ``SET NX``,
        or no await between the presence check and the write). "No entry"
        means in EVERY store a later read might consult, not just the one
        written now -- a layered provider must check its fallback too.
        ``security=True`` follows ``set``: never publish a positive into a
        process-local store; answer False when the shared store is
        unreachable.
        """
        ...

    async def set_authoritative(self, key: str, value: Any, ttl: int = 300) -> None:
        """Store value with TTL in EVERY store, overriding whatever is there.

        fix(#1778): counterpart to ``set_if_absent`` -- this IS the decision,
        so it must land everywhere a later read could look, including a
        layered provider's fallback that an outage may have populated with a
        now-stale value. ``set`` is not a substitute; it writes to one store.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete key. No error if missing."""
        ...

    async def delete_many(self, *keys: str) -> None:
        """Delete several keys as ONE operation. No error if any is missing.

        fix(#1543): the contract is atomicity, not batching for speed -- no
        reader may observe some of ``keys`` evicted and the rest still
        present, so no await between individual evictions. ``delete_pattern``
        is not a substitute: it's a scan plus per-key deletes, so it's both
        non-atomic and wider than the caller asked for.
        """
        ...

    async def delete_pattern(self, pattern: str) -> None:
        """Delete all keys matching glob pattern (e.g. 'settings:*')."""
        ...

    async def health_check(self) -> None:
        """Verify the cache backend is reachable. Raise on failure."""
        ...


_cache_provider: CacheProvider | None = None


def init_cache() -> None:
    """Initialize the cache provider singleton. Called once at startup."""
    global _cache_provider
    from app.core.config import settings

    if settings.redis_url:
        from app.platform.cache.redis import RedisCacheProvider

        _cache_provider = RedisCacheProvider(url=settings.redis_url)
    else:
        from app.platform.cache.memory import InMemoryCacheProvider

        _cache_provider = InMemoryCacheProvider()


def get_cache() -> CacheProvider:
    """Get the configured cache provider singleton."""
    if _cache_provider is None:
        raise RuntimeError("Cache not initialized. Call init_cache() first.")
    return _cache_provider


_tile_cache: "TileCacheProvider | InMemoryTileCacheProvider | None" = None


def init_tile_cache(*, in_memory_fallback: bool = True) -> None:
    """Initialize the tile cache singleton.

    Uses the Redis-backed provider when ``REDIS_URL`` is set, else an
    in-memory LRU fallback so single-VPS deployments without Redis still
    get tile-cache benefits.

    fix(#1315): pass ``in_memory_fallback=False`` from a process that only
    invalidates tiles and never reads them (the Procrastinate worker) -- a
    process-local LRU there would hold nothing, so purges would silently
    no-op. Leaving the singleton ``None`` instead surfaces the gap via the
    warning below.
    """
    global _tile_cache
    from app.core.config import settings

    if settings.redis_url:
        from app.platform.cache.tile_cache import (
            TileCacheProvider as _TileCacheProvider,
        )

        _tile_cache = _TileCacheProvider(url=settings.redis_url)
        return

    if not in_memory_fallback:
        _tile_cache = None
        logger.warning(
            "tile_cache_unavailable_in_worker",
            reason="REDIS_URL is unset",
            consequence=(
                "worker-side MVT purges after a reupload or PostGIS refresh "
                "cannot reach the API process's in-memory tile cache; the API "
                "keeps serving pre-swap tiles for up to tile_cache_ttl"
            ),
            remediation="set REDIS_URL so both processes share one tile cache",
        )
        return

    from app.platform.cache.tile_cache import (
        InMemoryTileCacheProvider as _InMemoryTileCacheProvider,
    )

    _tile_cache = _InMemoryTileCacheProvider()


def get_tile_cache() -> "TileCacheProvider | InMemoryTileCacheProvider | None":
    """Return the tile cache provider, or None if uninitialized.

    ``None`` means either ``init_tile_cache()`` wasn't called yet (a unit
    test before app startup), or fix(#1315): the worker process with
    ``REDIS_URL`` unset, where a process-local cache would hold nothing
    anyone reads.
    """
    return _tile_cache


# fix(#1429): the tile router keeps a process-local table_name -> dataset map
# (authorization fields included) to skip a DB round trip per tile request;
# versioning the tile cache key doesn't reach it. This function is the seam
# letting the catalog delete path evict that entry without importing
# `app.processing.*` (test_layering.py forbids catalog -> processing; both
# may import platform/).
#
# Call AFTER the triggering transaction commits -- inside it, a concurrent
# tile request can still read the not-yet-deleted row and re-cache what was
# just evicted.
#
# Two staleness windows survive even post-commit: other uvicorn workers'
# maps aren't evicted (bounded by the map's 60s TTL), and a request whose
# read was already in flight writes its stale result after eviction (also
# TTL-bounded). fix(#1444): both are safe because GH-1443 retires freed
# table names in catalog.retired_table_names, so a stale entry can only ever
# describe the SAME dataset it was cached for, never a reused name's
# predecessor -- eviction here is an optimization, not a safety mechanism.
_table_invalidation_listeners: list[Callable[[str], None]] = []


def register_table_invalidation_listener(listener: Callable[[str], None]) -> None:
    """Register a callable invoked with a table name when that table changes."""
    _table_invalidation_listeners.append(listener)


def notify_table_invalidated(table_name: str) -> None:
    """Tell every listener a table's identity or contents changed.

    Best-effort and never raises: callers run this beside a cache purge, and a
    listener failure must not fail the operation that triggered it.
    """
    for listener in _table_invalidation_listeners:
        try:
            listener(table_name)
        except Exception:  # broad: listener internals are not this call's to know
            logger.warning(
                "table_invalidation_listener_failed",
                table_name=table_name,
                exc_info=True,
            )
