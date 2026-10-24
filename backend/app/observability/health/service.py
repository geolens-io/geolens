"""Health check service -- probes database, storage, and cache in parallel."""

import asyncio
import time
import uuid
from contextvars import ContextVar
from typing import Any, Coroutine, NamedTuple

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.background import BackgroundTask

from app.platform.notifications.deadline import notification_deadline
from app.platform.notifications.smtp_channel import SMTP_ABORT_CLEANUP_SECS


logger = structlog.stdlib.get_logger(__name__)

HEALTH_TIMEOUT = 5.0

# Gates whether per-provider probe failures include the raw exception
# string in the response dict. Defaults to False so the unauthenticated /health
# endpoint never leaks provider internals; the admin path opts in. Carried via a
# ContextVar so it threads through asyncio.gather without changing _probe's
# signature (which tests call directly).
_include_probe_errors: ContextVar[bool] = ContextVar(
    "_include_probe_errors", default=False
)


async def _probe(name: str, coro: Coroutine[Any, Any, None]) -> dict[str, Any]:
    """Run a health probe coroutine with timeout, returning status dict.

    The raw provider exception (asyncpg/SQLAlchemy/S3 internals — may
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
    except Exception as exc:  # broad: aggregate any provider failure as degraded
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        logger.warning("health_probe_failed", provider=name, error=str(exc))
        result: dict[str, Any] = {"status": "error", "latency_ms": latency_ms}
        if _include_probe_errors.get():
            result["error"] = str(exc)
        return result


_readiness_engine: AsyncEngine | None = None


def get_readiness_engine() -> AsyncEngine:
    """Engine whose pool is separate from the request pool's."""
    global _readiness_engine
    if _readiness_engine is None:
        from app.core.db.session import build_readiness_engine

        _readiness_engine = build_readiness_engine()
    return _readiness_engine


async def _check_database(engine: AsyncEngine | None = None) -> None:
    """Probe database health by exercising a real query path.

    A plain ``SELECT 1`` only verifies the connection pool; it does not
    detect a hung database, broken search_path, or missing catalog schema.
    We additionally run a tiny query against the catalog schema so a
    genuinely unhealthy DB (hung, wrong schema, locks) reports as degraded.
    ``engine`` defaults to the request pool; readiness passes its own.
    """
    if engine is None:
        from app.core.db import engine  # late-bind for tests

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        # Exercise the search_path and catalog schema. `to_regclass` returns
        # NULL rather than raising for a missing table, so the value itself
        # decides whether the catalog is there.
        result = await conn.execute(text("SELECT to_regclass('catalog.datasets')"))
        if result.scalar() is None:
            raise LookupError("catalog.datasets is missing")


async def _check_storage() -> None:
    from app.platform.storage import get_storage

    storage = get_storage()
    await storage.health_check()


async def _check_cache() -> None:
    from app.platform.cache import get_cache

    cache = get_cache()
    await cache.health_check()


async def check_health(*, include_errors: bool = False) -> dict[str, Any]:
    """Run all health probes in parallel and return aggregate status.

    ``include_errors`` controls whether per-provider failures embed the raw
    exception string. The unauthenticated ``/health`` endpoint leaves it False
    (no provider internals to anonymous callers); the authenticated
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


async def check_readiness() -> dict[str, str]:
    """Readiness: whether this process can reach the database.

    The cache has an in-memory fallback and the object store is shared by
    every replica, so neither decides whether one API process can take
    traffic; ``check_health`` still reports both.
    """
    database = await _probe("database", _check_database(get_readiness_engine()))
    return {"status": "ready" if database["status"] == "ok" else "not_ready"}


async def check_oidc_health(db: AsyncSession) -> dict[str, dict[str, Any]]:
    """Probe all enabled OIDC providers and return status dict keyed by slug."""
    from app.platform.config_ops.service import check_oidc_endpoint

    try:
        from app.modules.auth.oauth import service as oauth_service

        providers = await oauth_service.list_providers(db, enabled_only=True)
    except Exception as exc:  # broad: enumeration is non-fatal; must not 500 the probe
        logger.warning(
            "Failed to enumerate OAuth providers for health probe",
            error=str(exc),
            exc_info=True,
        )
        return {}

    if not providers:
        return {}

    # OIDC health is surfaced only on the authenticated admin /infrastructure
    # view, so operators keep the error detail (only the
    # unauthenticated /health path withholds it).
    token = _include_probe_errors.set(True)
    try:
        probes = await asyncio.gather(
            *[_probe(p.slug, check_oidc_endpoint(p)) for p in providers]
        )
    finally:
        _include_probe_errors.reset(token)
    return {p.slug: result for p, result in zip(providers, probes)}


HEALTH_ALERT_COOLDOWN_SECS = 300
HEALTH_ALERT_DELIVERY_TIMEOUT = 60
# Cover delivery, socket-abort cleanup and a delayed acquisition reply, with margin.
HEALTH_ALERT_CLAIM_SECS = int(
    HEALTH_ALERT_DELIVERY_TIMEOUT + SMTP_ABORT_CLEANUP_SECS + 2 * HEALTH_TIMEOUT
)
# How long a failed delivery keeps the claim before any replica may retry.
HEALTH_ALERT_RETRY_SECS = 60
_HEALTH_ALERT_KEY = "health_alert:sent"
_alert_claim_token: str | None = None
# Serializes this process's observed-token bookkeeping with claim mutations.
_alert_claim_lock = asyncio.Lock()


class HealthAlertClaim(NamedTuple):
    """A claim to send the alert under.

    ``shared`` is true when the claim holds a key every process sees (Redis
    with its circuit closed), so another process can take over a failed send;
    otherwise only the local cooldown throttles.
    """

    token: str
    shared: bool = False


async def claim_health_alert(failing: list[str]) -> HealthAlertClaim | None:
    """The claim to send the degraded-health alert under, or None to stand down.

    With a shared cache (Redis) one replica wins a short delivery lease,
    extended to the cooldown after delivery. Only a
    stored key counts as another replica's claim: ``set_if_absent`` also
    answers False when its write fails, and that must not swallow the alert.
    Without a reachable Redis the claim is per-process.
    """
    global _alert_claim_token
    token = uuid.uuid4().hex
    if "cache" in failing:
        return HealthAlertClaim(token)

    from app.platform.cache import get_cache

    cache = get_cache()
    try:
        async with asyncio.timeout(HEALTH_TIMEOUT), _alert_claim_lock:
            # Stored before the write, so a write that commits after its reply
            # timed out is still released on recovery.
            _alert_claim_token = token
            if await cache.set_if_absent(
                _HEALTH_ALERT_KEY, token, ttl=HEALTH_ALERT_CLAIM_SECS
            ):
                # A key in this process's own memory holds no other process back.
                return HealthAlertClaim(token, shared=getattr(cache, "shared", False))
            # Remember the incident another replica claimed, so whichever
            # replica sees recovery can release it.
            _alert_claim_token = await cache.get(_HEALTH_ALERT_KEY)
            return HealthAlertClaim(token) if _alert_claim_token is None else None
    except Exception as exc:  # broad: a cache fault or stall must not block the alert
        logger.warning("health_alert_claim_failed", error=str(exc))
        return HealthAlertClaim(token)


async def release_health_alert() -> None:
    """Drop the claim for the incident this process saw, so a new incident alerts.

    A claim taken for a newer incident holds a different token and stays.
    """
    global _alert_claim_token
    from app.platform.cache import get_cache

    try:
        async with asyncio.timeout(HEALTH_TIMEOUT), _alert_claim_lock:
            token, _alert_claim_token = _alert_claim_token, None
            if token is None:
                return
            cache = get_cache()
            await cache.compare_and_delete(_HEALTH_ALERT_KEY, token)
    except Exception as exc:  # broad: recovery must not fail on a cache fault
        logger.warning("health_alert_release_failed", error=str(exc))


async def retry_health_alert_later(token: str) -> None:
    """Set *token*'s remaining claim TTL to the retry backoff.

    Only that claim: a newer incident's claim holds another token and stays.
    """
    await _set_health_alert_ttl(token, HEALTH_ALERT_RETRY_SECS)


async def _set_health_alert_ttl(token: str, ttl: int) -> None:
    """Renew only the delivery's own claim; recovery or a new owner wins."""
    from app.platform.cache import get_cache

    try:
        async with asyncio.timeout(HEALTH_TIMEOUT), _alert_claim_lock:
            await get_cache().compare_and_set(_HEALTH_ALERT_KEY, token, token, ttl=ttl)
    except Exception as exc:  # broad: a cache fault leaves the lease to expire
        logger.warning("health_alert_claim_update_failed", error=str(exc))


# None, not 0.0, means "alert at once": monotonic() can be under the cooldown
# just after boot.
_last_health_alert_at: float | None = None
_last_health_status = "healthy"
# monotonic() of this process's first degraded result in the current incident.
_health_incident_started_at = 0.0
# Probes can finish out of order; an older one never moves the alert state.
_health_probe_seq = 0
_health_applied_seq = 0
# One probe at a time applies its result, its claim or release included.
_health_state_lock = asyncio.Lock()


def begin_health_probe() -> int:
    """Number a ``/health`` probe before it runs, so results apply in order."""
    global _health_probe_seq
    _health_probe_seq += 1
    return _health_probe_seq


async def health_alert_after(seq: int, result: dict) -> BackgroundTask | None:
    """Apply probe *seq*'s *result* to the alert state; the alert to send, if any.

    The send runs after the response, so a slow channel never delays it. A
    probe still waiting on the probes ahead after ``HEALTH_TIMEOUT`` changes
    nothing and the next poll applies its result.
    """
    try:
        async with asyncio.timeout(HEALTH_TIMEOUT):
            await _health_state_lock.acquire()
    except TimeoutError:
        logger.warning("health_probe_result_dropped", probe=seq)
        return None
    try:
        return await _apply_health_result(seq, result)
    finally:
        _health_state_lock.release()


async def _apply_health_result(seq: int, result: dict) -> BackgroundTask | None:
    global _health_applied_seq, _health_incident_started_at
    global _last_health_alert_at, _last_health_status
    if seq < _health_applied_seq:
        return None
    _health_applied_seq = seq
    status = result.get("status", "healthy")
    if status == "healthy":
        if _last_health_status != "healthy":
            await release_health_alert()
        _last_health_status = "healthy"
        _last_health_alert_at = None
        return None

    failing = [
        name
        for name, info in result.get("providers", {}).items()
        if isinstance(info, dict) and info.get("status") != "ok"
    ]
    if _last_health_status == "healthy":
        _last_health_alert_at = None
        _health_incident_started_at = time.monotonic()
    _last_health_status = status
    if (
        _last_health_alert_at is not None
        and time.monotonic() - _last_health_alert_at < HEALTH_ALERT_COOLDOWN_SECS
    ):
        return None
    # Only the winner arms its cooldown: the others keep asking, so any of
    # them can retry once a failed delivery gives the key back.
    claim = await claim_health_alert(failing)
    if claim is None:
        return None
    _last_health_alert_at = sent_at = time.monotonic()
    # Early retries end with the incident's first cooldown, so a channel that
    # works gets a bounded number of repeats while another stays down.
    retry = claim.shared and (
        sent_at - _health_incident_started_at < HEALTH_ALERT_COOLDOWN_SECS
    )
    component = failing[0] if failing else "unknown"
    return BackgroundTask(
        _deliver_health_alert, claim.token, retry, sent_at, component, status
    )


async def _deliver_health_alert(
    token: str, retry: bool, sent_at: float, component: str, status: str
) -> None:
    """Send one claimed alert; with *retry*, a failure on any channel sends it
    to every channel again after the backoff.

    Bound to its own claim token and send time, so a slow failure never
    shortens a newer incident's claim or cooldown. The 75-second lease exceeds
    the 60-second send deadline plus 5 seconds of socket-abort cleanup, with
    10 seconds for acquisition latency and margin. No renewal is required.
    """
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    global _last_health_alert_at
    deadline = sent_at + HEALTH_ALERT_DELIVERY_TIMEOUT
    try:
        with notification_deadline(deadline):
            async with asyncio.timeout(max(0, deadline - time.monotonic())):
                delivery = await emit_event_safe(
                    event_key="health_alert",
                    build=lambda: build_event_notification(
                        "health_alert",
                        subject=f"GeoLens health degraded: {component}",
                        body=(
                            "The GeoLens health check reported a degraded status.\n\n"
                            f"Failing component: {component}"
                        ),
                        extra={"component": component, "status": status},
                    ),
                )
    except TimeoutError:
        logger.warning("health_alert_delivery_timed_out")
        delivery = None
    if delivery or not retry:
        await _set_health_alert_ttl(token, HEALTH_ALERT_COOLDOWN_SECS)
        return
    await retry_health_alert_later(token)
    if _last_health_alert_at == sent_at:
        _last_health_alert_at = (
            time.monotonic() - HEALTH_ALERT_COOLDOWN_SECS + HEALTH_ALERT_RETRY_SECS
        )
