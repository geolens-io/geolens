"""The follow-ups a job owes once its terminal commit has landed.

A first ingest owes its completion follow-ups, and a rejected replacement owes
its failure notice. The terminal transaction records them on the job row, so
the record exists exactly when the commit does. Whoever claims the record runs
them: the task after its commit, or the stale-job sweep when the task could not.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import Text, func, literal, select, text, update
from sqlalchemy.orm import joinedload

from app.core.failure_reason import redact_failure_reason
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_common import _emit_billing_event, cleanup_step

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# The job-row record of follow-ups a landed terminal commit still owes: the
# task (a complete job's first ingest, or a failed job's replacement) and the
# attempt that wrote it, since a retry keeps the row and its metadata.
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
    """Record, in the terminal transaction, that this attempt's ``task`` follow-ups are owed."""
    owed = func.jsonb_build_object(
        PUBLISH_FOLLOWUPS_FIELD,
        func.jsonb_build_object("task", task, "attempt_id", str(attempt_uuid)),
    )
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
    """Run a job's owed follow-ups once its terminal commit is visible, at most once.

    Claims the job's record. The job's status chooses what runs: a complete
    first ingest's follow-ups, or a failed job's ``ingest_failed`` notice. A job
    in neither status, or a row another caller has locked, runs nothing. A
    record an earlier attempt wrote, or a deleted dataset, is cleared and runs
    nothing. Returns whether this call claimed.
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
                select(
                    IngestJob.status,
                    IngestJob.dataset_id,
                    IngestJob.error_message,
                    IngestJob.attempt_id,
                    owed["task"].astext,
                    owed["attempt_id"].astext,
                )
                .where(
                    IngestJob.id == job_uuid,
                    IngestJob.status.in_(("complete", "failed")),
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

    status, dataset_id, error_message, attempt_id, task, owed_attempt = claim
    job_id = str(job_uuid)
    log = structlog.get_logger().bind(job_id=job_id, task=task)
    if owed_attempt != str(attempt_id):
        log.info("publish_followups_from_an_earlier_attempt")
        return True
    if status == "failed":
        async with cleanup_step("failure notice", job_id=job_id):
            await notify_ingest_failed(job_uuid, task=task, reason=error_message or "")
        return True
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


async def notify_ingest_failed(
    job_id: uuid.UUID, *, task: str, reason: str | BaseException
) -> None:
    """Send ``ingest_failed`` for ``job_id``, with ``reason`` redacted."""
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    message = redact_failure_reason(reason)
    await emit_event_safe(
        event_key="ingest_failed",
        build=lambda: build_event_notification(
            "ingest_failed",
            subject=f"Ingest failed: {task}",
            body=f"Ingest job (task={task}) failed.",
            reason=message,
            extra={"job_id": str(job_id), "task": task},
        ),
    )


async def run_owed_publish_followups() -> int:
    """Run the follow-ups landed terminal commits still owe, a bounded batch a call; never raises.

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
                        IngestJob.status.in_(("complete", "failed")),
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
