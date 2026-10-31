"""The worker task that sweeps story image objects no row names.

Lives under ``modules/admin/`` beside the other periodic tasks that run
catalog code: ``modules/catalog/`` may not import ``app.processing`` (where
``task_app`` is). The worker picks it up via ``task_app.import_paths`` in
``processing/ingest/tasks_common.py``.
"""

import structlog

from app.modules.catalog.stories.asset_sweep import sweep_unnamed_story_asset_objects
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)


async def sweep_story_asset_objects_for_all_tenants() -> None:
    """Sweep once, or once per registered tenant in hosted mode, where each
    tenant's objects sit under its own prefix."""
    from app.core.db import async_session
    from app.core.db.tenant_session import tenant_job_context
    from app.core.tenancy import is_multi_tenant
    from app.platform.jobs.worker import _registered_tenant_ids_for_recovery

    if not is_multi_tenant():
        async with async_session() as db:
            await sweep_unnamed_story_asset_objects(db)
        return

    for tenant_id in await _registered_tenant_ids_for_recovery():
        try:
            with tenant_job_context(tenant_id):
                async with async_session() as db:
                    await sweep_unnamed_story_asset_objects(db)
        except Exception:  # broad: one tenant's failure must not strand the rest
            logger.warning(
                "story_asset_sweep_tenant_failed", tenant_id=tenant_id, exc_info=True
            )


@task_app.periodic(cron="47 */6 * * *", periodic_id="story-asset-sweep")
@task_app.task(
    queue="ingest",
    retry=0,
    # queueing_lock keeps one run waiting; lock keeps two from running at once.
    queueing_lock="story-asset-sweep",
    lock="story-asset-sweep",
)
async def sweep_story_asset_objects(timestamp: int | None = None) -> None:
    """Delete story image objects no ``story_assets`` row names."""
    await sweep_story_asset_objects_for_all_tenants()
