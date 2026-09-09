"""Procrastinate defer-async orphan guard (Theme H).

Callers of ``task.defer_async(...)`` commit DB state (pending ``IngestJob``,
VRT ``regenerating`` status) *before* dispatching. If the queue is
unreachable, the already-committed state leaks as an orphan and the client
sees a generic 500. IngestJob orphans get swept after 60 minutes; VRT
``regenerating`` state has no sweep and stays stuck until an operator resets
it manually.

Wraps the defer call in try/except and invokes a caller-supplied rollback
closure to revert committed state before re-raising as HTTP 503. Each site
supplies its own rollback:

- Reupload paths: mark the ``IngestJob`` row failed.
- VRT regeneration paths: revert ``vrt_asset.status`` /
  ``current_generation_id`` AND mark the ``IngestJob`` / ``VrtGeneration`` failed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import structlog
from fastapi import HTTPException, status
from sqlalchemy import inspect as sa_inspect, update
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.url_redaction import redact_exception_text
from app.platform.jobs.models import (
    COMMIT_ATTEMPTED_METADATA_KEY,
    IngestJob,
    commit_attempted_marker,
)

if TYPE_CHECKING:
    # Typing-only: `platform/` must not import `processing/` at module scope
    # (test_layering.py's _PLATFORM_PROCESSING_IMPORT_BURNDOWN may shrink,
    # never grow), but the VRT factory signature below needs these two names.
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

    fix(#1550): ``rolled_back`` tells a caller whether the revert actually
    landed, so an audit trail doesn't record "failed" while the row is still
    ``pending`` (which would block every later embedding-backfill run).

    fix(#1755): ``cause_class`` is ``type(cause).__name__`` — a safe
    Python identifier, never ``str(cause)``, which can carry a credential or
    provider-chosen string. It distinguishes a bug in the defer closure from
    Procrastinate's queue genuinely being unreachable.
    """

    def __init__(self, *, rolled_back: bool, cause: BaseException) -> None:
        self.cause_class = type(cause).__name__
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "queue_unavailable",
                "message": "Task queue unavailable, please retry",
                "cause_class": self.cause_class,
            },
        )
        self.rolled_back = rolled_back


async def stamp_commit_attempted(job: IngestJob, *, db: AsyncSession) -> None:
    """Record durably, on the row, that a dispatch was attempted for it.

    feat(#1744): the one write that lets the stale sweep tell an abandoned
    upload (owner walked away pre-commit) from a broken dispatch (commit
    happened, task never landed); ``abandoned_upload`` in sweep.py reads its
    absence.

    Committed rather than left dirty, since the states that need it most
    never commit again (e.g. ``get_db`` closing without committing).

    Idempotent, and written as an UPDATE keyed on the id (not an ORM
    mutation) so it lands even for a detached instance; mirrored onto the
    instance afterwards.
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


def _restore_settlement_identifiers(
    job: IngestJob, identifiers: dict[str, Any] | None
) -> None:
    """Put the settlement's own identifiers back after a rollback expired them.

    fix(#1774): ``Session.rollback()`` expires every instance in
    the failed transaction; a synchronous read of an expired attribute on an
    ``AsyncSession`` raises ``MissingGreenlet`` instead of lazy-loading.
    ``settle_ingest_job_failed`` reads ``job.id``/``job.attempt_id``
    synchronously, so without this the reset that unblocks the session is
    also what stops the settlement from running.

    Restored from a snapshot taken BEFORE the failed write, via
    ``set_committed_value`` (marks loaded without a query, without a reload).
    Only the two attributes the shared settlement reads are restored. A
    no-op if ``identifiers`` is None (already expired, or a non-mapped test double).
    """
    if identifiers is None or sa_inspect(job, raiseerr=False) is None:
        return
    for key, value in identifiers.items():
        set_committed_value(job, key, value)


async def reset_session_for_settlement(job: IngestJob, *, db: AsyncSession) -> None:
    """Make a session usable again for the settlement that follows a failure.

    fix(#1774, #1814): call before ``settle_ingest_job_failed`` on any DB
    error. The rollback expires ``job``; its identifiers are snapshotted first.
    """
    # Reading them is itself an attribute access; an already-expired instance
    # has nothing to snapshot, so the reload below is the only route back.
    try:
        identifiers: dict[str, Any] | None = {
            "id": job.id,
            "attempt_id": job.attempt_id,
        }
    except Exception:  # broad: an already-expired instance has nothing to snapshot
        identifiers = None

    try:
        await db.rollback()
    except Exception:  # broad: a dead connection cannot be reset here
        logger.exception("Could not reset the session before settling a job")
    _restore_settlement_identifiers(job, identifiers)
    try:
        await db.refresh(job)
    except Exception:  # broad: best effort; the snapshot above is the guarantee
        logger.exception("Could not reload the job before settling it")


async def _settle_after_failed_dispatch(
    rollback: RollbackCallable, exc: BaseException, db: AsyncSession
) -> bool:
    """Run the caller's rollback closure and commit it. Returns whether it landed.

    fix(#1774): one copy, so the two ways a dispatch can fail settle the row
    identically rather than diverging on committing, logging or `rolled_back`.
    """
    try:
        await rollback(exc)
        await db.commit()
        return True
    except Exception:  # broad: rollback can itself fail with DB errors
        logger.exception(
            "Orphan-guard rollback failed after defer error",
            defer_error=str(exc),
        )
        return False


def _render_or_unreadable(render: Callable[[], str]) -> str:
    """One diagnostic field, or a placeholder when producing it raises.

    fix(#1755): an already-expired ``job`` raises on the ``id`` read and an
    exception with a failing ``__str__`` raises on render. Neither may
    escape the log that runs in front of the settlement.
    """
    try:
        return render()
    except Exception:  # broad: a diagnostic must not replace the failure it reports
        return "unreadable"


def _log_dispatch_failure(job: IngestJob, exc: BaseException, *, stage: str) -> None:
    """Record what made a dispatch fail, because nothing downstream will.

    fix(#1755): FastAPI answers a ``DeferFailed`` without logging it.
    ``stage`` separates the two raise sites, which ``cause_class`` alone
    cannot when both fail with the same type.
    """
    logger.warning(
        "ingest_dispatch_failed",
        job_id=_render_or_unreadable(lambda: str(job.id)),
        stage=stage,
        cause_class=type(exc).__name__,
        error=_render_or_unreadable(lambda: redact_exception_text(exc)),
    )


async def defer_with_orphan_guard(
    defer_call: DeferCallable,
    *,
    rollback: RollbackCallable,
    db: AsyncSession,
    job: IngestJob,
) -> None:
    """Run a ``defer_async`` call with rollback-on-failure semantics.

    On success: stamps ``job`` dispatch-attempted, then calls ``defer_call``.
    On failure of either step: invoke ``rollback(defer_exc)``, commit it, and
    raise ``DeferFailed`` (503) carrying whether the rollback landed. If the
    rollback itself raises, both errors are logged but the 503 still raises.

    feat(#1744): ``job`` is required because this is the one place every
    ``IngestJob`` dispatch passes through — stamping here reaches every door
    at once (``test_commit_attempted_marker_doors.py`` pins it). A failed
    stamp is treated as a failed dispatch and settled the same way: without
    the marker, a later sweep can't tell this row from an uncommitted upload.

    fix(#1774): the stamp gets its own try because that
    failure leaves the session in a failed transaction, and settlement is
    itself a statement on that session — it must be reset first.

    Args:
        defer_call: 0-arg async closure that calls ``task.defer_async``.
        rollback: async closure that reverts committed state, given the
            defer exception for error-message embedding.
        db: session used to commit the rollback.
        job: the ``IngestJob`` row, stamped dispatch-attempted before defer.

    Raises:
        DeferFailed: always, when ``defer_call`` raises.
    """
    try:
        await stamp_commit_attempted(job, db=db)
    except Exception as stamp_exc:  # broad: a failed marker write is a failed dispatch
        _log_dispatch_failure(job, stamp_exc, stage="commit_attempted_marker")
        # fix(#1774): reset discards nothing — every caller commits before dispatching.
        await reset_session_for_settlement(job, db=db)
        rolled_back = await _settle_after_failed_dispatch(rollback, stamp_exc, db)
        raise DeferFailed(rolled_back=rolled_back, cause=stamp_exc) from stamp_exc

    try:
        await defer_call()
    except (
        Exception
    ) as defer_exc:  # broad: defer_async can throw various job-runner errors
        _log_dispatch_failure(job, defer_exc, stage="defer_async")
        rolled_back = await _settle_after_failed_dispatch(rollback, defer_exc, db)
        raise DeferFailed(rolled_back=rolled_back, cause=defer_exc) from defer_exc


async def settle_ingest_job_failed(
    job: IngestJob,
    defer_exc: BaseException,
    *,
    message_prefix: str,
) -> bool:
    """Fenced ``pending -> failed`` for a dispatch that never queued.

    Returns whether the write landed; zero rows means something else already
    settled the job, and doing nothing is correct.

    fix(#1709): replaces a blind in-place ORM mutation. That bug let a
    cancel which committed mid-dispatch get overwritten back to `failed`,
    handing the user a Retry affordance for work they'd just cancelled. The
    fence is status ``pending`` AND the attempt id captured when the closure
    was built — a settled job needs no rollback, whoever settled it owns its
    terminal state.

    ORM attributes are mutated ONLY when the CAS lands, so a lost CAS leaves
    nothing dirty for the guard's own commit to flush onto the row. Expiring
    the instance instead (an earlier draft) is wrong: callers read attributes
    off it after the guard re-raises (``commit_import`` reads ``file_path``),
    and a lazy reload outside a greenlet raises ``MissingGreenlet``.
    """
    completed_at = datetime.now(timezone.utc)
    session = async_object_session(job)
    if session is None:
        # No session to fence through (detached instance). Still act — an
        # orphaned pending row is the failure this guard exists to prevent.
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

    Convenience for the common case (reupload, vanilla ingest) where the
    only committed state to revert is a pending ``IngestJob`` row. Caller
    must supply ``job`` bound to the session that commits the rollback.

    ``message_prefix`` is embedded before the exception so
    ``job.error_message`` matches ``test_queue_ingest_job_*``'s expected format.

    fix(#1709): fenced — see ``settle_ingest_job_failed``.
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

    Shared by the three VRT regeneration endpoints (add/remove-source,
    refresh): reverts ``vrt_asset.status``/``current_generation_id`` to the
    caller's pre-mutation values, marks the ``VrtGeneration`` failed, and
    marks the ``IngestJob`` failed via ``make_ingest_job_failed_rollback``.
    """

    async def _rollback(defer_exc: BaseException) -> None:
        # fix(#1709): the job fence decides. If the CAS misses, a cancel
        # already reconciled the asset in the same transaction — restoring
        # here would put it back to the 409-blocking `regenerating` state.
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
