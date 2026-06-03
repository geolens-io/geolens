from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.platform.cache.tile_cache import (
        InMemoryTileCacheProvider,
        TileCacheProvider,
    )


class CacheProvider(Protocol):
    """Provider-agnostic cache interface."""

    async def get(self, key: str) -> Any | None:
        """Return cached value or None on miss."""
        ...

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Store value with TTL in seconds."""
        ...

    async def delete(self, key: str) -> None:
        """Delete key. No error if missing."""
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


def init_tile_cache() -> None:
    """Initialize the tile cache singleton.

    Uses the Redis-backed binary provider when ``REDIS_URL`` is set;
    otherwise falls back to an in-memory LRU provider (PERF-01,
    Phase 274) so smaller single-VPS deployments still get tile-cache
    benefits without running Redis.
    """
    global _tile_cache
    from app.core.config import settings

    if settings.redis_url:
        from app.platform.cache.tile_cache import (
            TileCacheProvider as _TileCacheProvider,
        )

        _tile_cache = _TileCacheProvider(url=settings.redis_url)
    else:
        # PERF-01 (Phase 274): bounded in-memory LRU fallback.
        from app.platform.cache.tile_cache import (
            InMemoryTileCacheProvider as _InMemoryTileCacheProvider,
        )

        _tile_cache = _InMemoryTileCacheProvider()


def get_tile_cache() -> "TileCacheProvider | InMemoryTileCacheProvider | None":
    """Return the tile cache provider.

    PERF-01 (Phase 274): after ``init_tile_cache()`` has run this is
    always non-None — the in-memory fallback is used when ``REDIS_URL``
    is unset. ``None`` is only possible if ``init_tile_cache()`` was
    never called (e.g. inside a unit test before app startup).
    """
    return _tile_cache
