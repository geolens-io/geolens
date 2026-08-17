"""Queued embedding backfill: the concurrency guard and the worker task.

fix(#1542): ``POST /admin/backfill-embeddings/`` used to run
``backfill_embeddings`` inline in the request. A full regenerate is ~88%
provider round trips and scales linearly, so a catalog somewhere below 59,000
records outgrows nginx's 600s ``proxy_read_timeout`` for ``/api/``. The proxy
giving up does not stop the run — the server keeps generating and committing
batches against a connection nobody is reading — so the operator cannot tell
"still running" from "died halfway", and the natural retry starts a SECOND full
regenerate alongside the first. On the force path that means a second DELETE.

The run now goes through the Procrastinate queue that already lives inside
PostgreSQL, against an ``IngestJob`` row that gives the operator something to
observe and gives the guard below something to refuse a second run against.

This module lives under ``modules/admin/`` rather than beside the backfill in
``processing/embeddings/`` because the task emits the completion/failure audit
events, and ``processing/`` may not import ``app.modules.audit`` (the burndown
in ``tests/test_layering.py`` may shrink, never grow). The worker picks it up
through ``task_app.import_paths`` in ``processing/ingest/tasks_common.py``.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import current_tenant_var, tenant_task
from app.platform.jobs.heartbeat import (
    claim_job_attempt_and_start_heartbeat,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.platform.jobs.models import EMBEDDING_BACKFILL_METADATA_KEY, IngestJob
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)

# Generic error text for a failed run. The exception itself goes to the log —
# it can carry provider payloads, asyncpg internals and file paths, and the
# job row is readable through /jobs/{id} (RES-2, same reasoning the inline
# route applied to its 502 body).
BACKFILL_FAILED_MESSAGE = "Embedding backfill failed. See server logs for details."

# Audit outcome for a run whose fate could not be written to its job row —
# another actor settled the row first. It is terminal (the operation is over and
# the trail says so) but it deliberately does not claim the run succeeded or
# failed, because on this path the worker no longer owns that answer.
UNRESOLVED_OUTCOME = "unresolved"


def _lease_seconds() -> float:
    """Seconds a ``running`` backfill row holds the slot without a heartbeat.

    The shared 60-minute ingest backstop, deliberately: it is what
    ``/jobs/{id}`` and the stale-job sweeper already apply to every non-analysis
    job, so the guard here and the status those two report cannot disagree
    about whether a dead worker's run is still in flight. A live run renews its
    heartbeat every 30s, so the window only matters after a worker dies.

    Imported inside the function because ``JOB_TIMEOUT_SECONDS`` lives in
    ``platform/jobs/router.py`` — ``worker.py`` reaches it the same way.
    """
    from app.platform.jobs.router import JOB_TIMEOUT_SECONDS

    return float(JOB_TIMEOUT_SECONDS)


async def find_active_embedding_backfill(session: AsyncSession) -> IngestJob | None:
    """Return the embedding backfill run currently in flight, if any.

    "In flight" is queued, or running with a lease that has not expired —
    matching the per-user analysis cap in ``router_analysis.py``, whose
    heartbeat-or-nothing predicate is the shape that survives a dead worker
    without pinning the slot forever.

    Scoped per tenant in hosted mode, for the same reason the analysis ceiling
    is: the backfill only ever touches records the calling tenant can see, so
    one tenant's run must not lock another's out. ``ingest_jobs.tenant_id`` is
    stamped by the database and indexed, so the filter needs no schema work.
    """
    from app.core.tenancy import is_multi_tenant

    lease_cutoff = datetime.now(timezone.utc) - timedelta(seconds=_lease_seconds())
    stmt = (
        select(IngestJob)
        .where(
            IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY),
            or_(
                IngestJob.status == "pending",
                (IngestJob.status == "running")
                & (
                    func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                    >= lease_cutoff
                ),
            ),
        )
        .order_by(IngestJob.created_at.desc())
        .limit(1)
    )
    if is_multi_tenant():
        stmt = stmt.where(IngestJob.tenant_id == current_tenant_var.get())
    return (await session.execute(stmt)).scalars().first()


async def _finalize(
    session: AsyncSession,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    status: str,
    metadata: dict[str, Any] | None,
    result: dict[str, int] | None = None,
    error_message: str | None = None,
) -> bool:
    """Stamp the terminal job state, fenced on the attempt this worker owns.

    Returns whether the row actually took the update. It is fenced, so "I asked"
    and "it happened" are different facts, and the caller writes the audit trail
    off this answer — see ``_emit_terminal_audit``. Returning ``None`` and
    letting the caller assume success is what let a lost fence produce a failed
    job row under a "completed" audit entry.
    """
    values: dict[str, object] = {
        "status": status,
        "completed_at": datetime.now(timezone.utc),
        "error_message": error_message,
    }
    backfill_meta = dict((metadata or {}).get(EMBEDDING_BACKFILL_METADATA_KEY) or {})
    if result is not None:
        backfill_meta["result"] = result
        values["current_step"] = "complete"
        values["progress"] = 1.0
        values["rows_processed"] = result["processed"]
    values["user_metadata"] = {
        **(metadata or {}),
        EMBEDDING_BACKFILL_METADATA_KEY: backfill_meta,
    }
    if not await update_ingest_job_for_attempt(
        session, job_uuid, attempt_uuid, values=values
    ):
        # Another actor moved the row (stale-job sweep, an operator). Say so
        # rather than resurrecting a status somebody else settled.
        logger.warning(
            "embedding_backfill_finalize_skipped_stale_attempt",
            job_id=str(job_uuid),
            attempt_id=str(attempt_uuid),
            intended_status=status,
        )
        await session.rollback()
        return False
    await session.commit()
    return True


async def _emit_outcome_audit(
    *,
    user_id: str | None,
    ip_address: str | None,
    operation_id: str | None,
    job_id: str,
    force: bool,
    outcome: str,
    extra: dict[str, Any],
) -> None:
    """Record the run's outcome under the same action the request recorded.

    The "requested" half is emitted by the route, in the same commit as the job
    row. This half can only be emitted here — after the queue hop the request is
    long gone — so the actor and client IP ride along as task kwargs to keep the
    pair readable as one operation.
    """
    # fix(#1550 review P2): a run's state lives in two places — the job row and
    # the audit trail — written by independent paths. Every path that TERMINATES
    # a run has to write both, and the audit has to describe the row's actual
    # final state rather than the one this worker intended. See
    # `_emit_terminal_audit` for the rule and the module's tests for the
    # enumeration of paths it covers.
    from app.modules.audit.service import AuditEvent, audit_emit_durable

    try:
        await audit_emit_durable(
            AuditEvent(
                user_id=uuid.UUID(user_id) if user_id else None,
                action="embedding.backfill",
                resource_type="record_embedding",
                details={
                    "force": force,
                    "operation_id": operation_id,
                    "job_id": job_id,
                    "outcome": outcome,
                    **extra,
                },
                ip_address=ip_address,
            ),
        )
    except Exception:  # broad: the audit write must not change the job outcome
        logger.exception(
            "embedding_backfill_outcome_audit_failed",
            job_id=job_id,
            outcome=outcome,
        )


async def _emit_terminal_audit(
    *, applied: bool, outcome: str, extra: dict[str, Any], **context: Any
) -> None:
    """Close the audit trail with what actually happened to the job row.

    ``applied`` is ``_finalize``'s answer. When the fenced update did not land,
    another actor (the stale-job sweeper, a status poll expiring the lease) has
    already settled the row, and claiming the outcome this worker intended would
    put a "completed" entry over a failed job. Record UNRESOLVED instead, and
    carry the intended outcome so an operator can still see what the run did —
    "the regenerate finished but its row was settled by someone else" is a
    different incident from "the regenerate failed", and only one of them means
    the vectors are missing.
    """
    if applied:
        await _emit_outcome_audit(outcome=outcome, extra=extra, **context)
        return
    await _emit_outcome_audit(
        outcome=UNRESOLVED_OUTCOME,
        extra={
            "error_code": "finalize_lost_attempt",
            "intended_outcome": outcome,
            **extra,
        },
        **context,
    )


@task_app.task(queue="ingest", retry=0)
@tenant_task
async def run_embedding_backfill(
    job_id: str,
    attempt_id: str | None = None,
    force: bool = False,
    user_id: str | None = None,
    ip_address: str | None = None,
    operation_id: str | None = None,
) -> None:
    """Run one embedding backfill against its ``IngestJob`` row.

    ``retry=0``: a force run deletes before it regenerates, so an automatic
    replay would delete a second time on behalf of an operator who never asked
    for it. Failures are terminal and the operator restarts the run.
    """
    from app.core.db import async_session
    from app.processing.embeddings.backfill import backfill_embeddings

    # Every `return` below closes the audit trail. The route has already
    # committed a "requested" entry, so a path that ends the run without a
    # terminal entry leaves an administrative operation looking perpetually
    # in flight — the same divergence as claiming an outcome that did not
    # happen, in the other direction.
    audit_context: dict[str, Any] = {
        "user_id": user_id,
        "ip_address": ip_address,
        "operation_id": operation_id,
        "job_id": job_id,
        "force": force,
    }

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="embedding backfill"
    )
    if resolved is None:
        # A tokenless legacy delivery that could not adopt the row. The route
        # always sends an attempt id, so this is unreachable today and stays
        # covered anyway: an unreachable path that silently drops the run is
        # exactly what a future change to the dispatch would turn into a live
        # one, with no signal that it had.
        await _emit_outcome_audit(
            **audit_context,
            outcome=UNRESOLVED_OUTCOME,
            extra={"error_code": "attempt_unresolvable"},
        )
        return
    job_uuid, attempt_uuid = resolved

    async with async_session() as session:
        job = await session.get(IngestJob, job_uuid)
        metadata = dict(job.user_metadata or {}) if job is not None else {}
        heartbeat = await claim_job_attempt_and_start_heartbeat(
            session, job_uuid, attempt_uuid
        )
        if heartbeat is None:
            # The row was not `pending` under this attempt — the stale-pending
            # reaper got there first, or a retry rotated the token. This worker
            # never took the run, and nothing else will emit its outcome.
            logger.warning("embedding_backfill_attempt_no_longer_owned", job_id=job_id)
            await _emit_outcome_audit(
                **audit_context,
                outcome=UNRESOLVED_OUTCOME,
                extra={"error_code": "attempt_not_owned"},
            )
            return
        try:
            try:
                result = await backfill_embeddings(session, force=force)
            except Exception:  # broad: the backfill spans the embedding SDK and DB writes; every failure ends the run the same way
                logger.exception(
                    "embedding_backfill_failed",
                    job_id=job_id,
                    force=force,
                    operation_id=operation_id,
                )
                await session.rollback()
                applied = await _finalize(
                    session,
                    job_uuid,
                    attempt_uuid,
                    status="failed",
                    metadata=metadata,
                    error_message=BACKFILL_FAILED_MESSAGE,
                )
                await _emit_terminal_audit(
                    **audit_context,
                    applied=applied,
                    outcome="failed",
                    extra={"error_code": "backfill_failed"},
                )
                return
            applied = await _finalize(
                session,
                job_uuid,
                attempt_uuid,
                status="complete",
                metadata=metadata,
                result=result,
            )
            await _emit_terminal_audit(
                **audit_context,
                applied=applied,
                outcome="completed",
                extra=dict(result),
            )
        finally:
            await stop_ingest_job_heartbeat(heartbeat)
