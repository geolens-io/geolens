"""Procrastinate defer-async orphan guard (Theme H).

Callers of ``task.defer_async(...)`` commit DB state (pending ``IngestJob``,
VRT ``regenerating`` status) *before* dispatching. If the queue is
unreachable, the already-committed state leaks as an orphan and the client
sees a generic 500. IngestJob orphans get swept after 60 minutes; VRT
``regenerating`` state has no sweep and stays stuck until an operator resets
it manually.

Wraps the defer call in try/except and invokes a caller-supplied rollback
closure to revert committed state before re-raising as HTTP 503. The usual
rollback fails the ``IngestJob`` through the job ledger, whose hooks settle
the rows linked to it (a refresh run, a VRT generation, a backfill trail).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import structlog
from fastapi import HTTPException, status
from sqlalchemy import inspect as sa_inspect, update
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session
from sqlalchemy.orm.attributes import set_committed_value

from app.core.failure_reason import coded_failure_reason
from app.core.logging_config import redact_nested
from app.platform.jobs import ledger
from app.platform.jobs.ledger import Outcome
from app.platform.jobs.models import (
    COMMIT_ATTEMPTED_METADATA_KEY,
    IngestJob,
    commit_attempted_marker,
)

logger = structlog.get_logger()


DeferCallable = Callable[[], Awaitable[Any]]
"""0-arg async callable that invokes ``task.defer_async(...)``."""

RollbackCallable = Callable[[BaseException], Awaitable[object]]
"""Async callable that reverts committed DB state after a defer failure.

Receives the defer exception so the rollback can name its type in the
stored reason (fix(#1953): ``coded_failure_reason``, never ``str(exc)``,
which ADR-002 Decision 3 keeps out of a stored reason). Must *not* commit
the session — ``defer_with_orphan_guard`` commits after invoking the
rollback. The guard ignores its result.
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
            defer_error=_render_or_unreadable(lambda: redact_nested(str(exc))),
        )
        return False


def _log_dispatch_failure(job: IngestJob, exc: BaseException, *, stage: str) -> None:
    """Record what made a dispatch fail, because nothing downstream will.

    fix(#1755): FastAPI answers a ``DeferFailed`` without logging it.
    ``stage`` separates the two raise sites, which ``cause_class`` alone
    cannot when both fail with the same type.

    fix(#1755): ``error`` is scrubbed HERE, through ``redact_nested``.
    ``_redact_sensitive_fields`` scrubs free text only under ``event`` and
    ``exception``, and a defer exception can quote Procrastinate's
    ``call_string``, which renders a live ``token='...'`` kwarg.

    fix(#1755): ``exc_info`` carries the chain, because Procrastinate wraps
    a connector failure as ``ConnectorException("Database error.")`` and the
    top frame alone tells two outages apart from neither. ``format_exc_info``
    renders it under ``exception``, which the processor does scrub.
    """
    # The inner guards degrade one field; this one covers the emit itself, so
    # a raising processor cannot skip the settlement that follows.
    try:
        logger.warning(
            "ingest_dispatch_failed",
            job_id=_render_or_unreadable(lambda: str(job.id)),
            stage=stage,
            cause_class=type(exc).__name__,
            error=_render_or_unreadable(lambda: redact_nested(str(exc))),
            exc_info=exc,
        )
    except Exception:  # broad: a diagnostic must not preempt the settlement below
        pass


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
    expected_status: str = "pending",
    ip_address: str | None = None,
) -> bool:
    """Fenced ``<expected_status> -> failed`` for a dispatch that never queued.

    fix(#1710): ``expected_status`` exists because the URL import commits its
    row as ``running`` before dispatching — the download owns a worker lease
    from the moment the door answers, and a ``pending`` row would be judged
    by the stale-pending sweep instead. The fence still has to name the state
    the caller actually committed, or a failed defer leaves the row running
    for the whole lease.

    Returns whether the write landed; a miss means something else already
    settled the job, and doing nothing is correct. The fence is the state
    and the attempt id captured when the closure was built, so a cancel that
    committed mid-dispatch keeps its terminal state.

    Raises when ``job`` has no session: without one there is no fenced write
    to make, and reporting the job settled would leave it pending unseen.
    """
    session = async_object_session(job)
    if session is None:
        raise RuntimeError("the job to settle is not attached to a session")
    outcome = await ledger.abort(
        session,
        job,
        code="dispatch_failed",
        reason=coded_failure_reason(message_prefix, defer_exc),
        expect=expected_status,
        ip_address=ip_address,
    )
    if outcome is Outcome.LANDED:
        return True
    logger.info(
        "orphan_guard_rollback_skipped_job_already_settled",
        job_id=str(job.id),
        outcome=outcome.value,
        defer_error=_render_or_unreadable(lambda: redact_nested(str(defer_exc))),
    )
    return False


def make_ingest_job_failed_rollback(
    job: IngestJob,
    *,
    message_prefix: str = "Failed to queue ingest task",
    expected_status: str = "pending",
    ip_address: str | None = None,
) -> Callable[[BaseException], Awaitable[bool]]:
    """Build a rollback closure that marks an ``IngestJob`` failed.

    ``job`` must be bound to the session that commits the rollback. The
    ledger's hooks fail the rows linked to it in the same write.

    ``message_prefix`` is embedded before the exception's type so
    ``job.error_message`` matches ``test_queue_ingest_job_*``'s expected format.

    fix(#1709): fenced — see ``settle_ingest_job_failed``. The closure
    returns whether its write landed, so a wrapper compensates only then.
    """

    async def _rollback(defer_exc: BaseException) -> bool:
        return await settle_ingest_job_failed(
            job,
            defer_exc,
            message_prefix=message_prefix,
            expected_status=expected_status,
            ip_address=ip_address,
        )

    return _rollback
