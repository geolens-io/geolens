"""Catalog cache invalidation helpers."""

import structlog

logger = structlog.get_logger()


async def invalidate_catalog_cache() -> None:
    """Delete all catalog cache keys after data mutations."""
    try:
        from app.cache import get_cache

        cache = get_cache()
        await cache.delete_pattern("catalog:*")
        logger.info("catalog_cache_invalidated")
    except Exception:
        logger.warning("catalog_cache_invalidation_failed", exc_info=True)
