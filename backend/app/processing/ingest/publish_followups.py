"""The follow-ups a first ingest owes once its publish has landed.

The publish transaction records them on the job row, so the record exists
exactly when the commit does. Whoever claims the record runs them: the task
after its commit, or the stale-job sweep when the task could not.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import Text, func, literal, select, text, update
from sqlalchemy.orm import joinedload

from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_common import _emit_billing_event, cleanup_step

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# The job-row record of follow-ups a landed publish still owes.
PUBLISH_FOLLOWUPS_FIELD = "publish_followups"

# Each first ingest's completion-notice label, or None when it sends no notice
# and bills nothing.
_LABELS: dict[str, str | None] = {
    "ingest_raster": "Raster",
    "ingest_tileset": "3D Tiles",
    "ingest_vrt": None,
}

_SWEEP_BATCH = 50


async def note_publish_followups(
    session: AsyncSession, job_uuid: uuid.UUID, attempt_uuid: uuid.UUID, task: str
) -> None:
    """Record, in the publish transaction, that ``task``'s follow-ups are owed."""
    owed = func.jsonb_build_object(PUBLISH_FOLLOWUPS_FIELD, task)
    await session.execute(
        update(IngestJob)
        .where(IngestJob.id == job_uuid, IngestJob.attempt_id == attempt_uuid)
        .values(
            user_metadata=func.coalesce(
                IngestJob.user_metadata, text("'{}'::jsonb")
            ).op("||")(owed)
        )
        .execution_options(synchronize_session=False)
    )


async def run_publish_followups(job_uuid: uuid.UUID) -> bool:
    """Run a first ingest's owed follow-ups once its publish is visible, at most once.

    Claims the job's record. A job that isn't complete, or a row another caller
    has locked, runs nothing, and a deleted dataset runs nothing either. Returns
    whether this call claimed.
    """
    import app.core.db as db_module
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.platform.extensions import get_processing_port
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )
    from app.processing.embeddings.helpers import defer_embedding

    owed = IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    async with db_module.async_session() as session:
        claim = (
            await session.execute(
                select(IngestJob.dataset_id, owed.astext)
                .where(
                    IngestJob.id == job_uuid,
                    IngestJob.status == "complete",
                    owed.is_not(None),
                )
                .with_for_update(skip_locked=True)
            )
        ).one_or_none()
        if claim is None:
            return False
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_uuid)
            .values(
                user_metadata=IngestJob.user_metadata.op("-")(
                    literal(PUBLISH_FOLLOWUPS_FIELD, Text)
                )
            )
            .execution_options(synchronize_session=False)
        )
        await session.commit()

    dataset_id, task = claim
    job_id = str(job_uuid)
    log = structlog.get_logger().bind(job_id=job_id, task=task)
    if task not in _LABELS:
        log.warning("publish_followups_unknown_task")
        return True
    Dataset = get_processing_port().get_dataset_orm_class()
    async with db_module.async_session() as session:
        dataset = await session.scalar(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    if dataset is None or dataset.record is None:
        log.info("publish_followups_dataset_gone")
        return True

    label = _LABELS[task]
    title = dataset.record.title
    if label is not None:
        async with cleanup_step("publish completion notice", job_id=job_id):
            await emit_event_safe(
                event_key="ingest_complete",
                build=lambda: build_event_notification(
                    "ingest_complete",
                    subject=f"{label} ingest complete: {title}",
                    body=f"{label} dataset '{title}' has been successfully ingested.",
                    extra={"job_id": job_id, "dataset": title},
                ),
            )
    async with cleanup_step("publish catalog cache", job_id=job_id):
        await invalidate_catalog_cache()
    async with cleanup_step("publish embedding", job_id=job_id):
        await defer_embedding(dataset)
    if label is not None:
        tenant_id = current_tenant_var.get() if is_multi_tenant() else None
        async with cleanup_step("publish usage event", job_id=job_id):
            await _emit_billing_event(
                str(tenant_id) if tenant_id else None, "ingest_jobs", event_id=job_id
            )
    return True


async def run_owed_publish_followups() -> int:
    """Run the follow-ups landed publishes still owe, a bounded batch a call; never raises.

    Returns how many jobs this call claimed. A job whose follow-ups fail is
    logged and skipped.
    """
    import app.core.db as db_module

    log = structlog.get_logger()
    try:
        async with db_module.async_session() as session:
            owed = (
                await session.scalars(
                    select(IngestJob.id)
                    .where(
                        IngestJob.status == "complete",
                        IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD].is_not(None),
                    )
                    .limit(_SWEEP_BATCH)
                )
            ).all()
    except Exception:  # broad: the follow-ups wait for the next pass
        log.warning("owed_publish_followups_unreadable", exc_info=True)
        return 0
    claimed = 0
    for job_uuid in owed:
        try:
            claimed += await run_publish_followups(job_uuid)
        except Exception:  # broad: one job's follow-ups must not stop the rest
            log.warning("publish_followups_failed", job_id=str(job_uuid), exc_info=True)
    return claimed
