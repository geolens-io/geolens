"""Cache provider abstraction.

Pluggable cache backend with `memory` (in-process dict) and `redis` (Redis/Valkey)
implementations selected by the `REDIS_URL` environment variable. Used by tile
serving, settings reads, and any other code path that needs cross-instance
cache consistency.
"""

from app.cache.provider import CacheProvider, get_cache, init_cache

__all__ = ["CacheProvider", "get_cache", "init_cache"]
