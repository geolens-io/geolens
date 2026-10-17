"""The hourly worker task that applies each dataset's row retention.

Lives under ``modules/admin/`` with the other queued task that emits audit
events: ``modules/catalog/`` may not import ``app.processing`` (where
``task_app`` is), and ``processing/`` may not import catalog or audit
(``test_layering.py``). The worker picks it up via ``task_app.import_paths``
in ``processing/ingest/tasks_common.py``.
"""

import structlog

from app.modules.catalog.features.retention import prune_expired_rows
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)


async def prune_expired_rows_for_all_tenants() -> None:
    """Run retention once, or once per registered tenant in hosted mode.

    ``catalog.datasets`` is RLS scoped in hosted mode, so each tenant runs
    under its own context and a failure is isolated to that tenant.
    """
    from app.core.db.tenant_session import tenant_job_context
    from app.core.tenancy import is_multi_tenant
    from app.platform.jobs.worker import _registered_tenant_ids_for_recovery

    if not is_multi_tenant():
        await prune_expired_rows()
        return

    for tenant_id in await _registered_tenant_ids_for_recovery():
        try:
            with tenant_job_context(tenant_id):
                await prune_expired_rows()
        except Exception:  # broad: one tenant's failure must not strand the rest
            logger.warning(
                "dataset_retention_tenant_failed", tenant_id=tenant_id, exc_info=True
            )


@task_app.periodic(cron="23 * * * *", periodic_id="dataset-retention")
@task_app.task(
    queue="ingest",
    retry=0,
    # queueing_lock keeps one run waiting; lock keeps two from running at once.
    queueing_lock="dataset-retention",
    lock="dataset-retention",
)
async def apply_dataset_retention(timestamp: int | None = None) -> None:
    """Delete rows past each dataset's retention window."""
    await prune_expired_rows_for_all_tenants()
