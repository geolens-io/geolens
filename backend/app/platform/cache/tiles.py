"""Catalog cache invalidation helpers."""

import structlog

logger = structlog.get_logger()


async def invalidate_catalog_cache() -> bool:
    """Delete all catalog cache keys after data mutations; returns whether the delete landed."""
    try:
        from app.platform.cache import get_cache, tenant_cache_key

        cache = get_cache()
        await cache.delete_pattern(tenant_cache_key("catalog:*"))
        logger.info("catalog_cache_invalidated")
    except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
        logger.warning("catalog_cache_invalidation_failed", exc_info=True)
        return False
    return True
