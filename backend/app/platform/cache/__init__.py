"""Platform cache namespace."""

from app.platform.cache.provider import CacheProvider, get_cache, init_cache

__all__ = ["CacheProvider", "get_cache", "init_cache"]
