"""Platform cache namespace."""

from app.platform.cache.provider import CacheProvider, get_cache, init_cache
from app.platform.cache.tenant import tenant_cache_context_available, tenant_cache_key

__all__ = [
    "CacheProvider",
    "get_cache",
    "init_cache",
    "tenant_cache_context_available",
    "tenant_cache_key",
]
