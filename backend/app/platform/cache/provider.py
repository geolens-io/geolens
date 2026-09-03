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

    async def get(self, key: str) -> Any | None:
        """Return cached value or None on miss."""
        ...

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Store value with TTL in seconds."""
        ...

    async def set_if_absent(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Store value with TTL only when *key* has no entry. True if stored.

        fix(#1778): the contract is "do not overwrite", which is what lets a
        caller publish a result it computed from a snapshot without clobbering
        a decision another writer has made in the meantime. The embed-token
        validator uses it to write its positive entry: a concurrent revocation
        stamps a denial under the same key, and whichever of the two lands
        first, the denial is what survives. A plain ``set`` there re-cached a
        token the revoke had already invalidated.

        Must be atomic against a concurrent writer of the same key -- Redis
        ``SET NX``, or a presence check with no await between the read and the
        write.

        fix(#1778 codex r1): "has no entry" means in EVERY store an
        implementation might later read from, not just the one it would write
        to now. A layered provider whose fallback still holds a denial must
        answer False even while its primary store is empty.
        """
        ...

    async def set_authoritative(self, key: str, value: Any, ttl: int = 300) -> None:
        """Store value with TTL in EVERY store, overriding whatever is there.

        fix(#1778 codex r1): the counterpart to ``set_if_absent``. That one
        yields to an existing decision; this one IS the decision, so it has to
        land everywhere a later read could look -- including a layered
        provider's fallback, which an outage may have populated from a snapshot
        that is now wrong.

        The embed-token revoke path is the caller: a positive entry written
        into the in-memory fallback during a Redis outage outlived a revocation
        that only reached Redis, and the next Redis error served the revoked
        token again. ``set`` is not a substitute, because it writes to one
        store.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete key. No error if missing."""
        ...

    async def delete_many(self, *keys: str) -> None:
        """Delete several keys as ONE operation. No error if any is missing.

        fix(#1543): the contract is atomicity, not batching for speed. No
        reader may observe the cache with some of ``keys`` evicted and the rest
        still present, so an implementation must not await between individual
        evictions. ``delete_pattern`` is not a substitute — it is a scan plus
        per-key deletes, so it is both non-atomic and wider than the caller
        asked for.
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


# --- Tile cache (binary, separate from JSON cache) ---

_tile_cache: "TileCacheProvider | InMemoryTileCacheProvider | None" = None


def init_tile_cache(*, in_memory_fallback: bool = True) -> None:
    """Initialize the tile cache singleton.

    Uses the Redis-backed binary provider when ``REDIS_URL`` is set;
    otherwise falls back to an in-memory LRU provider (PERF-01,
    Phase 274) so smaller single-VPS deployments still get tile-cache
    benefits without running Redis.

    fix(#1315): pass ``in_memory_fallback=False`` from a process that only
    ever INVALIDATES tiles and never reads them — the Procrastinate worker.
    A process-local LRU there holds nothing, because nothing in that process
    ever caches a tile, so the post-swap purge would evict zero entries while
    logging ``tile_cache_invalidated`` — a no-op wearing a success message.
    Leaving the singleton unset instead makes the gap legible: the caller sees
    ``None`` and the warning below says what is lost and how to fix it.
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

    # PERF-01 (Phase 274): bounded in-memory LRU fallback.
    from app.platform.cache.tile_cache import (
        InMemoryTileCacheProvider as _InMemoryTileCacheProvider,
    )

    _tile_cache = _InMemoryTileCacheProvider()


def get_tile_cache() -> "TileCacheProvider | InMemoryTileCacheProvider | None":
    """Return the tile cache provider.

    PERF-01 (Phase 274): in the API process this is non-None after
    ``init_tile_cache()`` has run — the in-memory fallback covers an unset
    ``REDIS_URL``.

    ``None`` means one of two things: ``init_tile_cache()`` was never called
    (a unit test before app startup), or fix(#1315) — the worker process
    with ``REDIS_URL`` unset, where no cache this process could hold would
    be the cache anyone reads.
    """
    return _tile_cache


# --- Table invalidation listeners (fix #1429) ---
#
# The tile router keeps a process-local map of table_name -> dataset metadata
# so it does not hit the DB per tile request. That map decides authorization —
# visibility, record_status and created_by are read from the cached snapshot
# rather than re-queried — so versioning the tile cache key does not reach it:
# the stale entry is what picks the dataset, before any cache key is built.
#
# This is the seam that lets the catalog delete path tell the tile router to
# drop that entry without importing it — `catalog/` must not import
# `app.processing.*` (test_layering.py::test_no_catalog_imports_processing),
# but both sides may import `platform/`.
#
# Call this AFTER the triggering transaction commits. The map is populated
# from `catalog.datasets`, which a dataset delete does not lock, so a notify
# from inside the open transaction is undone by any concurrent tile request:
# it still reads the not-yet-deleted row and re-caches what was just evicted.
#
# Scope, stated plainly, because two windows survive even post-commit:
#   - Listeners are in-process. A delete handled by one uvicorn worker cannot
#     evict another worker's map, so multi-worker deployments keep a window
#     bounded by that map's 60s TTL.
#   - A request whose catalog read was already in flight when the eviction ran
#     writes its result afterwards. The opportunity is only one query wide,
#     but an entry that does land then lives the full TTL like any other — the
#     narrow window buys a short race, not a short consequence.
# fix(#1444): both windows are now exactly the bounded-staleness tradeoff
# already documented for visibility changes in processing/tiles/router.py —
# the stale entry describes the SAME dataset it was cached for, and nothing
# worse. It used to be able to describe a PREDECESSOR of a reused table name,
# which no notification channel in this topology could have fixed (REDIS_URL is
# unset by default, and LISTEN/NOTIFY needs a session-pinned connection that
# transaction-mode PgBouncer — a supported topology, see the SET LOCAL note in
# processing/tiles/router.py — does not provide). GH-1443 removed the
# precondition instead: a table name freed by a delete is retired in
# catalog.retired_table_names and never handed out again, so an entry cached
# under a name cannot outlive its dataset's exclusive claim on that name.
# Eviction is therefore an optimization here, not the thing standing between a
# successor's rows and a predecessor's visibility.
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
