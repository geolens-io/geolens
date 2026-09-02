"""Procrastinate defer-async orphan guard (Theme H).

Callers of ``task.defer_async(...)`` in the route/service layer commit
DB state (pending ``IngestJob``, VRT ``regenerating`` status, etc.)
*before* dispatching the background task. If the Procrastinate queue is
unreachable, the exception propagates out, the already-committed state
leaks as an orphan, and the client sees a generic 500.

For ``IngestJob`` rows, stale-cleanup picks the orphan up after 60
minutes. For VRT asset state (``status="regenerating"``) there is **no**
cleanup sweep — a Procrastinate outage leaves the VRT permanently stuck
until an operator manually resets the status. Closing that gap is the
reason this guard exists.

This module provides a generic guard that wraps the defer call in a
try/except and invokes a caller-supplied rollback closure to revert the
committed state before re-raising as HTTP 503. Each site supplies its
own rollback because the exact state to revert differs:

- Reupload paths: mark the ``IngestJob`` row failed.
- VRT regeneration paths: revert ``vrt_asset.status`` /
  ``current_generation_id`` to their pre-mutation values AND mark the
  associated ``IngestJob`` / ``VrtGeneration`` failed.

The original RESILIENCE-2 fix (``create_vrt_job`` /
``queue_ingest_job``) used an ingest-local ``_defer_with_orphan_guard``
helper that hard-coded the IngestJob rollback. This module generalizes
that pattern so the non-ingest callers (``datasets/router_reupload.py``
and ``datasets/router_vrt.py``) can reuse it without depending on the
ingest service module.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import structlog
from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session

from app.platform.jobs.models import (
    COMMIT_ATTEMPTED_METADATA_KEY,
    IngestJob,
    commit_attempted_marker,
)

if TYPE_CHECKING:
    # Typing-only edge: `platform/` must not import `processing/` at module
    # scope (test_layering.py's _PLATFORM_PROCESSING_IMPORT_BURNDOWN "may
    # shrink, never grow"), but the VRT factory below needs these two names
    # for its signature. Mirrors the `AuditEvent`/`Identity` TYPE_CHECKING
    # pattern in `platform/extensions/protocols.py`.
    from app.processing.raster.models import RasterAsset, VrtGeneration

logger = structlog.get_logger()


DeferCallable = Callable[[], Awaitable[Any]]
"""0-arg async callable that invokes ``task.defer_async(...)``."""

RollbackCallable = Callable[[BaseException], Awaitable[None]]
"""Async callable that reverts committed DB state after a defer failure.

Receives the defer exception so the rollback can embed its details in
error messages (matches the ``f"Failed to queue ...: {exc}"`` format the
pre-existing regression tests assert on). Must *not* commit the session
— ``defer_with_orphan_guard`` commits after invoking the rollback.
"""


class DeferFailed(HTTPException):
    """The 503 raised when a defer fails, carrying the rollback's fate.

    fix(#1550 review P2): the guard reverts committed state and then raises,
    and callers that record an outcome need to know whether the revert actually
    landed. Without it, a caller writes "failed" into an audit trail or a
    response while the row it names is still ``pending`` — and for the embedding
    backfill a stuck ``pending`` row goes on blocking every later run through
    the in-flight guard, so the two records disagree about a state that has
    operational teeth.

    Same rule the review applied to ``_finalize`` one layer up: a helper that
    performs a state change reports whether it happened, rather than leaving the
    caller to assume.
    """

    def __init__(self, *, rolled_back: bool) -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue unavailable, please retry",
        )
        self.rolled_back = rolled_back


async def stamp_commit_attempted(job: IngestJob, *, db: AsyncSession) -> None:
    """Record durably, on the row, that a dispatch was attempted for it.

    feat(#1744): the one write that lets the stale sweep tell an abandoned
    upload from a broken one. ``POST /ingest/upload`` deliberately does not
    queue anything, so a `pending` row with no Procrastinate job is the normal
    state between upload and commit, and when the owner walks away at the
    preview step that row looks exactly like a commit whose dispatch died. The
    two are only indistinguishable because nothing on the row said whether a
    dispatch was ever tried; this says it, and ``abandoned_upload`` in
    ``jobs/sweep.py`` reads its absence.

    Committed rather than left dirty on the session, because the states that
    need it most are the ones where nothing later commits: ``get_db`` closes
    without committing, and the two rows the marker has to survive for are a
    defer whose rollback did not land and a dispatch whose queue row later
    vanished with the ingest row still `pending`. The extra commit costs
    nothing here, because every caller of the guard has just committed the row
    it is about to dispatch, which the Phase 1060 close-gate fix made
    mandatory so the worker can see the row before the task exists.

    Idempotent: a second dispatch of the same row (``/jobs/{id}/retry``
    re-queues through ``queue_ingest_job``) keeps the first timestamp and
    issues no write. Written as an UPDATE keyed on the id rather than an ORM
    mutation so it also lands for a caller holding a detached instance, and
    mirrored onto the instance afterwards so in-memory reads agree with the
    row.
    """
    metadata = dict(job.user_metadata or {})
    if metadata.get(COMMIT_ATTEMPTED_METADATA_KEY):
        return
    metadata.update(commit_attempted_marker())
    await db.execute(
        update(IngestJob).where(IngestJob.id == job.id).values(user_metadata=metadata)
    )
    await db.commit()
    job.user_metadata = metadata


async def defer_with_orphan_guard(
    defer_call: DeferCallable,
    *,
    rollback: RollbackCallable,
    db: AsyncSession,
    job: IngestJob,
) -> None:
    """Run a ``defer_async`` call with rollback-on-failure semantics.

    On success: stamps ``job`` as dispatch-attempted, then ``defer_call``.

    On failure:
        1. Invoke ``rollback(defer_exc)`` to revert committed state.
        2. Commit the rollback on ``db``.
        3. If the rollback itself raises, log the rollback error plus
           the original defer error (so operators see both) but still
           re-raise the 503 below so the client retries.
        4. Raise ``DeferFailed`` (an ``HTTPException`` 503) chained from
           the defer error, carrying ``rolled_back`` so a caller can tell
           "the state was reverted" from "the state is still out there".

    feat(#1744): ``job`` is required, and it is required rather than optional
    because this is the one place every ``IngestJob`` dispatch in the codebase
    passes through. Nothing calls ``task.defer_async`` with a ``job_id``
    outside a closure this guard runs, so stamping here reaches every door at
    once and a new door cannot be written that skips it. Same "a caller cannot
    express the operation without also taking the rule" shape that
    ``stale_pending_clauses`` uses for the read side.
    ``test_commit_attempted_marker_doors.py`` pins both halves.

    The stamp is inside the try on purpose. It has to be on the row BEFORE the
    task exists, and a stamp that does not land is a dispatch that must not
    happen: without it a later sweep cannot tell this row from an upload nobody
    ever committed, and would cancel a job whose only recovery path is
    ``/jobs/{id}/retry`` (failed-only). Treating that as a dispatch failure
    settles the row `failed` through the same rollback, which is the state a
    caller can act on.

    Args:
        defer_call: 0-arg async closure that calls ``task.defer_async``.
        rollback: async closure that reverts committed state. Receives
            the defer exception for error-message embedding.
        db: session used to commit the rollback.
        job: the ``IngestJob`` row this dispatch is for, stamped
            dispatch-attempted before the defer runs.

    Raises:
        DeferFailed: always, when ``defer_call`` raises. Existing callers that
            catch ``HTTPException`` are unaffected; the 503 body is unchanged.
    """
    try:
        await stamp_commit_attempted(job, db=db)
        await defer_call()
    except Exception as defer_exc:  # broad: defer_async can throw various job-runner errors; orphan-guard handles all
        rolled_back = False
        try:
            await rollback(defer_exc)
            await db.commit()
            rolled_back = True
        except Exception:  # broad: rollback itself can fail with DB errors; log both, still surface 503 to client
            # Rollback itself failed — log the rollback error plus the
            # defer context so operators can diagnose both. Still raise
            # 503 so the client retry flow stays consistent.
            logger.exception(
                "Orphan-guard rollback failed after defer error",
                defer_error=str(defer_exc),
            )
        raise DeferFailed(rolled_back=rolled_back) from defer_exc


async def settle_ingest_job_failed(
    job: IngestJob,
    defer_exc: BaseException,
    *,
    message_prefix: str,
) -> bool:
    """Fenced ``pending -> failed`` for a dispatch that never queued.

    Returns whether the write landed. Zero rows means the job is no longer
    pending under this attempt — something else already settled it — and
    the rollback correctly does nothing.

    fix(#1709 review r11): this used to be a blind in-place ORM mutation,
    and #1709 round 4 recorded the resulting window as a benign wart. It
    is not. A cancel that commits while the dispatch request is still
    awaiting queue submission was overwritten here: the row went back to
    ``failed``, which is the one status ``/jobs/{id}/retry`` accepts, so
    the user who cancelled was handed a Retry affordance that restarts
    exactly the work they cancelled — with the audit trail (a committed
    ``job.cancel``) contradicting the row.

    The fence is the same one every other write in #1677 uses: status
    ``pending`` AND the attempt id this dispatch belongs to, read when the
    closure was built. That failure mode is right for every caller — a
    settled job needs no orphan rollback, whoever settled it owns its
    terminal state — which is what makes one guard safe across the shared
    surface.

    The ORM attributes are mutated ONLY when the CAS landed, so the
    instance keeps describing the row. On a lost CAS they are deliberately
    left alone: writing ``status='failed'`` onto the instance would have
    the guard's own commit flush it and clobber the row the CAS just
    declined to touch — the same bug in a second costume. Nothing in that
    branch is marked dirty, so the commit writes nothing for this row.

    (Expiring the instance instead is what an earlier draft did, and it
    is wrong here: every caller reads attributes off this object after
    the guard re-raises — ``commit_import`` reads ``file_path`` to clean
    up staging — and a lazily reloading attribute outside a greenlet
    raises ``MissingGreenlet``.)
    """
    completed_at = datetime.now(timezone.utc)
    session = async_object_session(job)
    if session is None:
        # No session to fence through (an unforeseen caller holding a
        # detached instance). Preserve the historical behaviour rather
        # than silently skipping the orphan rollback: an orphaned pending
        # row is the failure this guard exists to prevent.
        job.status = "failed"
        job.error_message = f"{message_prefix}: {defer_exc}"
        job.completed_at = datetime.now(timezone.utc)
        return True

    result = await session.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job.id,
            IngestJob.status == "pending",
            (
                IngestJob.attempt_id == job.attempt_id
                if job.attempt_id is not None
                else IngestJob.attempt_id.is_(None)
            ),
        )
        .values(
            status="failed",
            error_message=f"{message_prefix}: {defer_exc}",
            completed_at=completed_at,
        )
    )
    landed = bool(result.rowcount)
    if landed:
        job.status = "failed"
        job.error_message = f"{message_prefix}: {defer_exc}"
        job.completed_at = completed_at
    else:
        logger.info(
            "orphan_guard_rollback_skipped_job_already_settled",
            job_id=str(job.id),
            defer_error=str(defer_exc),
        )
    return landed


def make_ingest_job_failed_rollback(
    job: IngestJob,
    *,
    message_prefix: str = "Failed to queue ingest task",
) -> RollbackCallable:
    """Build a rollback closure that marks an ``IngestJob`` failed.

    Convenience for the common case where the only committed state to
    revert is a pending ``IngestJob`` row (reupload, vanilla ingest).
    The returned closure captures ``job``; the caller is responsible for
    supplying ``job`` bound to the same session that will commit the
    rollback.

    The ``message_prefix`` is embedded before the defer exception string
    so ``job.error_message`` reads like
    ``"Failed to queue ingest task: <exc>"``. This format matches the
    existing ``test_queue_ingest_job_*`` regression tests.

    fix(#1709 review r11): fenced — see ``settle_ingest_job_failed``.
    """

    async def _rollback(defer_exc: BaseException) -> None:
        await settle_ingest_job_failed(job, defer_exc, message_prefix=message_prefix)

    return _rollback


def make_vrt_regeneration_failed_rollback(
    vrt_asset: RasterAsset,
    generation: VrtGeneration,
    job: IngestJob,
    *,
    previous_status: str,
    previous_generation_id: uuid.UUID | None,
) -> RollbackCallable:
    """Build a rollback closure for a VRT regeneration defer failure.

    Convenience for the three VRT regeneration endpoints (add-source,
    remove-source, refresh) that each commit the same three pieces of state
    before dispatch: ``vrt_asset.status`` / ``current_generation_id``
    (reverted here to the pre-mutation values the caller captured before
    committing), the new ``VrtGeneration`` row (marked failed here), and the
    ``IngestJob`` row (marked failed via `make_ingest_job_failed_rollback`,
    reused rather than duplicated — same message prefix as before, so
    ``job.error_message`` still reads ``"Failed to queue VRT regeneration:
    <exc>"``).
    """

    async def _rollback(defer_exc: BaseException) -> None:
        # fix(#1709 review r11): the job fence decides. The VRT restore is
        # this dispatch's type-specific state, and it is only this
        # dispatch's to undo while the job is still pending under its own
        # attempt. If the CAS matches zero rows, a cancel (or a sweep)
        # already settled the job — and the cancel endpoint reconciles the
        # generation and the asset in the same transaction it commits the
        # cancellation, so restoring here would undo exactly that
        # reconciliation and put the asset back to `regenerating`, the
        # 409-blocking state the reconciliation exists to clear.
        if not await settle_ingest_job_failed(
            job, defer_exc, message_prefix="Failed to queue VRT regeneration"
        ):
            return
        vrt_asset.status = previous_status
        vrt_asset.current_generation_id = previous_generation_id
        generation.status = "failed"
        generation.completed_at = datetime.now(timezone.utc)
        generation.error_message = f"Failed to queue VRT regeneration: {defer_exc}"

    return _rollback
