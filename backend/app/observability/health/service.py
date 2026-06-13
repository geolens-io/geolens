"""Health check service -- probes database, storage, and cache in parallel."""

import asyncio
import time
from contextvars import ContextVar
from typing import Any, Coroutine

import structlog

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import engine

logger = structlog.stdlib.get_logger(__name__)

HEALTH_TIMEOUT = 5.0

# GAP-016: gates whether per-provider probe failures include the raw exception
# string in the response dict. Defaults to False so the unauthenticated /health
# endpoint never leaks provider internals; the admin path opts in. Carried via a
# ContextVar so it threads through asyncio.gather without changing _probe's
# signature (which tests call directly).
_include_probe_errors: ContextVar[bool] = ContextVar(
    "_include_probe_errors", default=False
)


async def _probe(name: str, coro: Coroutine[Any, Any, None]) -> dict[str, Any]:
    """Run a health probe coroutine with timeout, returning status dict.

    GAP-016: the raw provider exception (asyncpg/SQLAlchemy/S3 internals — may
    embed hostnames, ports, usernames, bucket names) is ALWAYS logged
    server-side here, but is only returned in the dict when the caller asks for
    it via ``check_health(include_errors=True)``. The unauthenticated ``/health``
    endpoint omits it so anonymous callers never see internal detail; the
    authenticated admin ``/infrastructure`` view opts in.
    """
    start = time.monotonic()
    try:
        await asyncio.wait_for(coro, timeout=HEALTH_TIMEOUT)
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:  # broad: health probes intentionally aggregate any provider-side failure as a degraded status
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        logger.warning("health_probe_failed", provider=name, error=str(exc))
        result: dict[str, Any] = {"status": "error", "latency_ms": latency_ms}
        if _include_probe_errors.get():
            result["error"] = str(exc)
        return result


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


async def check_health(*, include_errors: bool = False) -> dict[str, Any]:
    """Run all health probes in parallel and return aggregate status.

    ``include_errors`` controls whether per-provider failures embed the raw
    exception string. The unauthenticated ``/health`` endpoint leaves it False
    (GAP-016 — no provider internals to anonymous callers); the authenticated
    admin ``/infrastructure`` view passes True so operators keep the detail.
    The exception is logged server-side regardless.
    """
    token = _include_probe_errors.set(include_errors)
    try:
        db, storage, cache = await asyncio.gather(
            _probe("database", _check_database()),
            _probe("storage", _check_storage()),
            _probe("cache", _check_cache()),
        )
    finally:
        _include_probe_errors.reset(token)
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
    except Exception as exc:  # broad: OAuth provider enumeration is non-fatal; health endpoint should not 500 if list fails
        logger.warning(
            "Failed to enumerate OAuth providers for health probe",
            error=str(exc),
            exc_info=True,
        )
        return {}

    if not providers:
        return {}

    # OIDC health is surfaced only on the authenticated admin /infrastructure
    # view, so operators keep the error detail (GAP-016 scope is the
    # unauthenticated /health path).
    token = _include_probe_errors.set(True)
    try:
        probes = await asyncio.gather(
            *[_probe(p.slug, check_oidc_endpoint(p)) for p in providers]
        )
    finally:
        _include_probe_errors.reset(token)
    return {p.slug: result for p, result in zip(providers, probes)}
