"""Catalog cache invalidation helpers."""

import structlog

logger = structlog.get_logger()


async def invalidate_catalog_cache() -> None:
    """Delete all catalog cache keys after data mutations."""
    try:
        from app.platform.cache import get_cache

        cache = get_cache()
        await cache.delete_pattern("catalog:*")
        logger.info("catalog_cache_invalidated")
    except Exception:  # broad: cache invalidation must not break callers; redis can throw varied pool/timeout errors
        logger.warning("catalog_cache_invalidation_failed", exc_info=True)
