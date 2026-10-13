"""Age out audit rows past the admin-configured retention period."""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog

log = structlog.get_logger()

AUDIT_PRUNE_INTERVAL_SECONDS = 6 * 3600
AUDIT_PRUNE_BATCH_SIZE = 5000


async def prune_expired_audit_logs(*, batch_size: int = AUDIT_PRUNE_BATCH_SIZE) -> int:
    """Delete audit rows older than ``audit_retention_days`` in the current scope.

    Unset keeps everything. Records one ``audit.prune`` event when rows went.
    Returns the number deleted.
    """
    from app.core.db import async_session
    from app.core.persistent_config import AUDIT_RETENTION_DAYS
    from app.modules.audit.service import AuditEvent, audit_emit, prune_audit_logs

    async with async_session() as session:
        days = await AUDIT_RETENTION_DAYS.get(session)
        if days is None:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = await prune_audit_logs(session, cutoff=cutoff, batch_size=batch_size)
        if deleted:
            await audit_emit(
                session,
                AuditEvent(
                    user_id=None,
                    action="audit.prune",
                    resource_type="audit_log",
                    details={
                        "deleted": deleted,
                        "cutoff": cutoff.isoformat(),
                        "retention_days": days,
                    },
                ),
            )
            await session.commit()
        return deleted


async def prune_expired_audit_logs_for_all_tenants() -> None:
    """Run the prune once, or once per registered tenant in hosted mode.

    ``audit_logs`` is FORCE-RLS scoped, so an unscoped delete in hosted mode
    matches nothing; each tenant is pruned under its own context and a failure
    is isolated to that tenant.
    """
    from app.core.db.tenant_session import tenant_job_context
    from app.core.tenancy import is_multi_tenant
    from app.platform.jobs.worker import _registered_tenant_ids_for_recovery

    if not is_multi_tenant():
        await prune_expired_audit_logs()
        return

    for tenant_id in await _registered_tenant_ids_for_recovery():
        try:
            with tenant_job_context(tenant_id):
                await prune_expired_audit_logs()
        except Exception as exc:  # broad: one tenant's failure must not strand the rest
            log.warning(
                "Audit log prune failed for tenant",
                tenant_id=tenant_id,
                error=str(exc),
                exc_info=True,
            )


async def _prune_audit_logs_safely() -> None:
    try:
        await prune_expired_audit_logs_for_all_tenants()
    except Exception:  # broad: best-effort housekeeping, never fatal to the worker
        log.warning("Audit log prune failed", exc_info=True)


async def run_audit_log_prunes() -> None:
    """Prune on an interval for the life of the worker, sleeping first."""
    while True:
        await asyncio.sleep(AUDIT_PRUNE_INTERVAL_SECONDS)
        await _prune_audit_logs_safely()
