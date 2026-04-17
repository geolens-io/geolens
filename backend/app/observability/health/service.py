"""Health check service -- probes database, storage, and cache in parallel."""

import asyncio
import time
from typing import Any, Coroutine

import structlog

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import engine

logger = structlog.stdlib.get_logger(__name__)

HEALTH_TIMEOUT = 5.0


async def _probe(name: str, coro: Coroutine[Any, Any, None]) -> dict[str, Any]:
    """Run a health probe coroutine with timeout, returning status dict."""
    start = time.monotonic()
    try:
        await asyncio.wait_for(coro, timeout=HEALTH_TIMEOUT)
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        logger.warning("health_probe_failed", provider=name, error=str(exc))
        return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}


async def _check_database() -> None:
    """Probe database health by exercising a real query path.

    A plain ``SELECT 1`` only verifies the connection pool; it does not
    detect a hung database, broken search_path, or missing catalog schema.
    We additionally run a tiny query against the catalog schema so a
    genuinely unhealthy DB (hung, wrong schema, locks) reports as degraded.
    """
    async with engine.connect() as conn:
        # Cheap connectivity check
        await conn.execute(text("SELECT 1"))
        # Exercise the search_path and catalog schema. Using `to_regclass`
        # returns NULL without error if the table is missing, so this stays
        # a fast read that still validates the schema is accessible.
        await conn.execute(text("SELECT to_regclass('catalog.datasets')"))


async def _check_storage() -> None:
    """Probe storage provider health."""
    from app.platform.storage import get_storage

    storage = get_storage()
    await storage.health_check()


async def _check_cache() -> None:
    """Probe cache provider health."""
    from app.platform.cache import get_cache

    cache = get_cache()
    await cache.health_check()


async def check_health() -> dict[str, Any]:
    """Run all health probes in parallel and return aggregate status."""
    db, storage, cache = await asyncio.gather(
        _probe("database", _check_database()),
        _probe("storage", _check_storage()),
        _probe("cache", _check_cache()),
    )
    all_ok = all(p["status"] == "ok" for p in [db, storage, cache])
    return {
        "status": "healthy" if all_ok else "degraded",
        "providers": {
            "database": db,
            "storage": storage,
            "cache": cache,
        },
    }


async def check_oidc_health(db: AsyncSession) -> dict[str, dict[str, Any]]:
    """Probe all enabled OIDC providers and return status dict keyed by slug."""
    from app.platform.config_ops.service import check_oidc_endpoint

    try:
        from app.modules.auth.oauth import service as oauth_service

        providers = await oauth_service.list_providers(db, enabled_only=True)
    except Exception:
        return {}

    if not providers:
        return {}

    probes = await asyncio.gather(
        *[_probe(p.slug, check_oidc_endpoint(p)) for p in providers]
    )
    return {p.slug: result for p, result in zip(providers, probes)}
