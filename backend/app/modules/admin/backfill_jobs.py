"""Queued embedding backfill: the concurrency guard and the worker task.

fix(#1542): running inline used to outlast nginx's 600s proxy timeout, so a
retry could start a second regenerate (a second DELETE on the force path)
alongside the first. This now runs on the Procrastinate queue against an
``IngestJob`` row the guard below refuses a second run against.

Lives under ``modules/admin/``, not ``processing/embeddings/``, because the
task emits audit events and ``processing/`` may not import
``app.modules.audit`` (``test_layering.py``); the worker picks it up via
``task_app.import_paths`` in ``processing/ingest/tasks_common.py``.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, update
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

# fix(#1556): the row read moved inside the guarded exit, so a run that never
# claimed the row reaches it — and "could not record its outcome" would then
# describe work that never began.
CANCELLED_MESSAGE = (
    "Embedding backfill was cancelled by a worker shutdown. Records it had "
    "already reached carry their new vectors and the rest are unchanged; "
    "re-run to finish the remainder."
)
START_FAILED_MESSAGE = (
    "Embedding backfill could not start. Nothing was changed; re-run it."
)
SETTLE_FAILED_MESSAGE = (
    "Embedding backfill could not record its outcome. See server logs for details."
)

# Audit outcome for a run whose fate could not be written to its job row —
# another actor settled the row first. It is terminal (the operation is over and
# the trail says so) but it deliberately does not claim the run succeeded or
# failed, because on this path the worker no longer owns that answer.
UNRESOLVED_OUTCOME = "unresolved"


# Must stay byte-identical to the predicate of
# `uq_ingest_jobs_active_embedding_backfill` (migration 0050) — the index is
# the guard, this query is only the friendly half producing a readable 409.
SLOT_HOLDING_STATUSES = ("pending", "running")


async def find_active_embedding_backfill(session: AsyncSession) -> IngestJob | None:
    """Return the embedding backfill run currently holding the slot, if any.

    Keyed on status alone, not a heartbeat lease: the partial unique index's
    predicate must be immutable (no ``now()``), so a heartbeat-based query
    could disagree with it. Status-only also errs on the strong side for a
    force run that DELETEs every embedding first — a stale heartbeat is not
    proof the old worker is gone.

    Released when the row reaches a terminal status, either by the worker or
    by the stale-job sweeper (60-minute ingest backstop, every 5 minutes).
    Scoped per tenant in hosted mode, matching the index's key.
    """
    from app.core.tenancy import is_multi_tenant

    stmt = (
        select(IngestJob)
        .where(
            IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY),
            IngestJob.status.in_(SLOT_HOLDING_STATUSES),
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
    expected_status: str = "running",
) -> bool:
    """Stamp the terminal job state, fenced on the attempt this worker owns.

    Returns whether the row actually took the update, since a lost fence must
    not let the caller assume success and audit a "completed" run that never
    happened (see ``_emit_terminal_audit``).
    """
    values: dict[str, object] = {
        "status": status,
        "completed_at": datetime.now(timezone.utc),
        "error_message": error_message,
    }
    backfill_meta = dict((metadata or {}).get(EMBEDDING_BACKFILL_METADATA_KEY) or {})
    extra_metadata: dict[str, Any] = {}
    if result is not None:
        backfill_meta["result"] = result
        values["rows_processed"] = result["processed"]
        # fix(#1550): surfaced via JobStatusResponse.rows_failed so a run that's
        # `complete` with rejections isn't read as a clean success. fix(#1549):
        # on a force run those rejections KEPT their old vectors — the
        # replacement never committed, so the existing row was never deleted.
        extra_metadata["rows_failed"] = result["errors"]
        # Only a run that actually succeeded gets the completion stamps. A run
        # whose every embedding failed still records its counts — that is the
        # evidence an operator needs — but must not read as finished work.
        if status == "complete":
            values["current_step"] = "complete"
            values["progress"] = 1.0
    values["user_metadata"] = {
        **(metadata or {}),
        **extra_metadata,
        EMBEDDING_BACKFILL_METADATA_KEY: backfill_meta,
    }
    if not await update_ingest_job_for_attempt(
        session, job_uuid, attempt_uuid, values=values, expected_status=expected_status
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

    The "requested" half is emitted by the route in the same commit as the job
    row; this half runs after the queue hop, so actor/IP ride along as task
    kwargs to keep the pair readable as one operation.
    """
    # fix(#1550): a run's state lives in two places — job row and audit trail —
    # written by independent paths. Every path that TERMINATES a run must write
    # both, and the audit must describe the row's actual final state, not the
    # one this worker intended (see `_emit_terminal_audit`).
    from app.modules.audit.service import AuditEvent, audit_emit_durable

    try:
        # One operation, one terminal entry, DATABASE-decided which —
        # `uq_audit_logs_terminal_embedding_backfill` (migration 0051). The poll
        # and sweeper can both legitimately close this run (check-then-insert),
        # so the race's IntegrityError is contained by `audit_emit_durable`.
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


@dataclass
class _TerminalState:
    """What this run decided, and how much of that decision has been recorded.

    fix(#1550): every way this task can end funnels through :func:`_settle`,
    and this record is what makes that safe — it knows whether the terminal
    row write has already landed, so recovery never overwrites a committed
    outcome and never skips one still missing.
    """

    status: str | None = None  # job row status: "complete" | "failed"
    outcome: str | None = None  # audit outcome: "completed" | "failed"
    error_code: str | None = None
    error_message: str | None = None
    result: dict[str, int] | None = None
    # "We ran the fenced UPDATE and got an answer" — NOT "the answer was yes".
    # A lost fence is a settled question; a raised exception is not, and only
    # the second one may be retried.
    row_attempted: bool = False
    row_applied: bool = False
    audited: bool = False
    # fix(#1550): the live status the row was OBSERVED in. Every recovery path
    # here was built around `running` (fence, heartbeat, sweeper), so a run
    # whose claim commit was lost sat invisible in `pending` until stale
    # cleanup. Recovery terminalizes from whatever state it finds, not the
    # one it expected.
    expected_status: str = "running"

    def decide_complete(self, result: dict[str, int]) -> None:
        self.status = "complete"
        self.outcome = "completed"
        self.result = result

    def decide_failed(
        self,
        *,
        error_code: str,
        message: str,
        result: dict[str, int] | None = None,
    ) -> None:
        self.status = "failed"
        self.outcome = "failed"
        self.error_code = error_code
        self.error_message = message
        self.result = result

    def audit_extra(self) -> dict[str, Any]:
        extra: dict[str, Any] = dict(self.result or {})
        if self.error_code is not None:
            extra["error_code"] = self.error_code
        return extra


async def _emit_terminal_audit(
    *, applied: bool, outcome: str, extra: dict[str, Any], **context: Any
) -> None:
    """Close the audit trail with what actually happened to the job row.

    ``applied`` is ``_finalize``'s answer. When the fenced update didn't land,
    another actor already settled the row, so claiming the intended outcome
    would put a "completed" entry over a failed job — record UNRESOLVED with
    the intended outcome carried alongside instead.
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


async def _settle(
    session: AsyncSession,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    metadata: dict[str, Any] | None,
    state: _TerminalState,
    audit_context: dict[str, Any],
) -> None:
    """Record the run's terminal state — the row, then the trail — exactly once.

    Idempotent by construction: each half is skipped if already done, so
    recovery can call this again after a failure or cancellation without
    overwriting a committed outcome. Deliberately the SAME function on both
    paths, so recovery cannot drift from the happy path it is recovering.
    """
    if state.status is None:
        return
    if not state.row_attempted:
        state.row_applied = await _finalize(
            session,
            job_uuid,
            attempt_uuid,
            status=state.status,
            metadata=metadata,
            result=state.result,
            error_message=state.error_message,
            expected_status=state.expected_status,
        )
        state.row_attempted = True
    if not state.audited:
        await _emit_terminal_audit(
            **audit_context,
            applied=state.row_applied,
            outcome=state.outcome or "failed",
            extra=state.audit_extra(),
        )
        state.audited = True


# Statuses that mean the question is settled: the row will not change again on
# its own. Matches the CHECK constraint on ingest_jobs.status minus the two the
# backfill can occupy while live.
_TERMINAL_STATUSES = frozenset({"complete", "failed", "cancelled", "fanned_out"})


async def _release_caller_transaction(session: AsyncSession, job_id: str) -> None:
    """Let go of the transaction we are recovering FROM, before taking its locks.

    fix(#1550): a cancellation during ``session.commit()`` can leave the
    caller's transaction open and still holding the job row's lock, so a fresh
    recovery session's UPDATE would block on it until the caller's own timeout
    — leaving the row ``running`` and the slot held until the stale sweep.

    Bounded separately from the caller's timeout so a wedged rollback can't
    consume the whole budget; escalates to ``invalidate()`` (drops the
    connection) since a connection that won't roll back won't do anything
    else either, and dropping the socket is what releases the server-side lock.
    """
    try:
        await asyncio.wait_for(session.rollback(), timeout=5)
        return
    except (
        BaseException
    ):  # broad: the connection may be mid-statement or gone; the fallback is the point
        logger.warning(
            "embedding_backfill_recovery_rollback_failed", job_id=job_id, exc_info=True
        )
    try:
        await session.invalidate()
    except BaseException:  # broad: last resort before the fresh session tries anyway
        logger.warning(
            "embedding_backfill_recovery_invalidate_failed",
            job_id=job_id,
            exc_info=True,
        )


async def _recover_unsettled(
    session: AsyncSession,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    metadata: dict[str, Any] | None,
    state: _TerminalState,
    audit_context: dict[str, Any],
    error_code: str,
    message: str,
) -> None:
    """Finish whatever :func:`_settle` did not — by READING the row, not guessing.

    fix(#1550): an in-process "did I write it" flag can't tell apart two causes
    of "my fenced update matched nothing" — someone else settled the row, or I
    settled it and never heard back (ack lost to a cancellation or dropped
    connection during ``commit()``). Only the row itself can, so read it.

    Rule: **the audit describes the row.** If the row's terminal status
    matches this run's decided outcome, that outcome is recorded (whoever's
    write landed); if it differs, the row belongs to someone else's decision
    and the entry says UNRESOLVED.
    """
    from app.core.db import async_session

    await _release_caller_transaction(session, audit_context["job_id"])

    if state.status is None:
        state.decide_failed(error_code=error_code, message=message)

    async with async_session() as fresh:
        observed = await fresh.get(IngestJob, job_uuid)
        if observed is not None and observed.status in _TERMINAL_STATUSES:
            # Settled already — trail must describe what the row says, whoever
            # wrote it.
            #
            # fix(#1556): status-matching suffices HERE (unlike in
            # `_undispatched_settle_write_landed`) because this worker already
            # took delivery. `complete` has exactly one producer (this
            # attempt's fenced `_finalize`), so a match proves authorship;
            # `failed` has several, but all share the same outcome and differ
            # only in `error_code`, and `worker_cancelled` is the conservative
            # one where they diverge.
            state.row_attempted = True
            state.row_applied = observed.status == state.status
            if not state.row_applied:
                logger.warning(
                    "embedding_backfill_recovery_row_settled_elsewhere",
                    job_id=audit_context["job_id"],
                    observed_status=observed.status,
                    intended_status=state.status,
                )
        elif observed is None:
            # The row is gone (retention purge, manual delete). Nothing to write
            # and nothing to claim.
            state.row_attempted = True
            state.row_applied = False
        else:
            # Still live: the terminal write genuinely never landed, so this
            # run still owes one — from whatever state the row is actually in,
            # which after a lost claim commit is `pending`, not `running`.
            state.row_attempted = False
            state.expected_status = observed.status
            # fix(#1556 review): `_finalize` REPLACES user_metadata, so it
            # starts from the row's own — the caller's is empty when the
            # opening read failed, erasing the marker the retry contract reads.
            metadata = dict(observed.user_metadata or {})
        await _settle(
            fresh,
            job_uuid,
            attempt_uuid,
            metadata=metadata,
            state=state,
            audit_context=audit_context,
        )


UNDISPATCHED_RUN_MESSAGE = (
    "Embedding backfill was cancelled before it could be queued. "
    "Nothing was deleted; start the backfill again."
)


async def _fail_undispatched_pending_row(job_uuid: uuid.UUID) -> bool:
    """Fail the still-``pending`` row and report whether it took the update."""
    from app.core.db import async_session

    async with async_session() as session:
        result = await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_uuid, IngestJob.status == "pending")
            .values(
                status="failed",
                completed_at=datetime.now(timezone.utc),
                error_message=UNDISPATCHED_RUN_MESSAGE,
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def _undispatched_settle_write_landed(job_uuid: uuid.UUID) -> bool:
    """Ask the row for evidence of THIS write, on a fresh connection.

    fix(#1556): `status == "failed"` alone isn't proof — a worker could claim
    and fail the job after this cleanup was cancelled, and a status-only read
    would then record `dispatch_cancelled` (nothing deleted) over the real
    `backfill_failed` (everything deleted), evicting the true terminal entry
    (unique per job id, migration 0051).

    ``UNDISPATCHED_RUN_MESSAGE`` is written at exactly one site — this one —
    and once terminal, no other writer can overwrite it, so matching it proves
    only this write could have landed.

    Bounded separately, like ``_release_caller_transaction``: a shutdown that
    already lost one round trip must not let a second one extend the drain.
    """
    from app.core.db import async_session

    async def _read() -> bool:
        async with async_session() as fresh:
            observed = await fresh.get(IngestJob, job_uuid)
        return (
            observed is not None
            and observed.status == "failed"
            and observed.error_message == UNDISPATCHED_RUN_MESSAGE
        )

    return await asyncio.wait_for(_read(), timeout=5)


async def settle_undispatched_run(
    job_uuid: uuid.UUID,
    *,
    audit_context: dict[str, Any],
    caller_session: AsyncSession | None = None,
) -> None:
    """Settle a run that was committed but never reliably queued.

    fix(#1550): ``defer_with_orphan_guard`` catches ``Exception``, so a
    cancellation during dispatch walks past it and the route's
    ``DeferFailed`` handler, leaving the row ``pending`` with no worker
    coming — and since the unique index counts ``pending`` and ``running``
    alike, it blocks every later backfill just as effectively as a stuck
    running one.

    Fenced on ``pending`` so it cannot overwrite a run a worker picked up
    after all — dispatch may have reached the queue before the cancellation
    landed.

    fix(#1556): this settle's own commit can itself lose its acknowledgement
    under the cancellation that triggered it, leaving a terminal ``failed``
    row no sweeper will revisit and a trail stuck on ``requested``. Same rule
    as ``_recover_unsettled``: read the row for evidence of THIS write, not
    for a status other actors also reach (see
    ``_undispatched_settle_write_landed``).

    fix(#1556): ``caller_session`` is released first, because a cancellation
    that landed inside that session's own commit leaves it holding the job
    row's lock, and the fenced write below would then block on it.
    """
    if caller_session is not None:
        await _release_caller_transaction(caller_session, audit_context["job_id"])
    try:
        settled = await _fail_undispatched_pending_row(job_uuid)
    except BaseException:  # broad: a lost acknowledgement is the case recovered here
        logger.warning(
            "embedding_backfill_dispatch_settle_unacknowledged",
            job_id=audit_context["job_id"],
            exc_info=True,
        )
        settled = await _undispatched_settle_write_landed(job_uuid)
    if not settled:
        # A worker took it, or the lost write never landed after all — leave
        # both records to whoever owns the row: a worker closes its own trail,
        # a still-pending row is closed by the stale-pending sweep.
        logger.info(
            "embedding_backfill_dispatch_cancel_found_run_in_progress",
            job_id=audit_context["job_id"],
        )
        return
    await _emit_outcome_audit(
        **audit_context,
        outcome="failed",
        extra={"error_code": "dispatch_cancelled"},
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

    ``retry=0``: fix(#1549) removed the original reason (force no longer
    deletes ahead of regenerating), but an automatic replay would still
    re-embed every already-written record at provider rates on an operator's
    behalf who never asked for it — so failures stay terminal and the
    operator restarts explicitly.
    """
    from app.core.db import async_session
    from app.processing.embeddings.backfill import backfill_embeddings

    # Every `return` below closes the audit trail — the route already
    # committed a "requested" entry, so a path that skips a terminal one
    # leaves the operation looking perpetually in flight.
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
        # A tokenless legacy delivery that could not adopt the row. Unreachable
        # today (the route always sends an attempt id) but stays covered: a
        # silently-dropped run here is what a future dispatch change would
        # turn live, with no signal that it had.
        await _emit_outcome_audit(
            **audit_context,
            outcome=UNRESOLVED_OUTCOME,
            extra={"error_code": "attempt_unresolvable"},
        )
        return
    job_uuid, attempt_uuid = resolved

    async with async_session() as session:
        metadata: dict[str, Any] = {}
        state = _TerminalState()
        heartbeat = None
        try:
            # fix(#1556): the row read is inside the guarded region too.
            # Outside it, a transient outage or a shutdown cancellation here
            # left the row `pending`, holding the slot until the stale sweep.
            job = await session.get(IngestJob, job_uuid)
            if job is not None:
                metadata = dict(job.user_metadata or {})
            # fix(#1550): the claim is INSIDE the guarded region — its own
            # commit is a lost-acknowledgement window too. A shutdown
            # cancelling `pending`->`running` mid-commit can apply it without
            # returning; with the claim outside, recovery never ran and the
            # row stayed `running`, holding the slot until the stale sweep.
            heartbeat = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid
            )
            if heartbeat is None:
                # The row was not `pending` under this attempt — the
                # stale-pending reaper got there first, or a retry rotated the
                # token. This worker never took the run.
                logger.warning(
                    "embedding_backfill_attempt_no_longer_owned", job_id=job_id
                )
                await _emit_outcome_audit(
                    **audit_context,
                    outcome=UNRESOLVED_OUTCOME,
                    extra={"error_code": "attempt_not_owned"},
                )
                return

            # fix(#1709): stop signal reads off the JOB ROW, not
            # procrastinate's abort flag — the DB CAS is the cancel design's
            # correctness mechanism, and it also covers sweep settles. Polled
            # once per batch, so a lost queue-abort still stops the run
            # within one batch of provider spend. Same session on purpose:
            # the loop commits per batch and READ COMMITTED shows each new
            # statement the latest committed status either way.
            async def _job_still_running() -> bool:
                current = await session.scalar(
                    select(IngestJob.status).where(
                        IngestJob.id == job_uuid,
                        IngestJob.attempt_id == attempt_uuid,
                    )
                )
                return current == "running"

            try:
                result = await backfill_embeddings(
                    session, force=force, should_continue=_job_still_running
                )
            except Exception:  # broad: the backfill spans the embedding SDK and DB writes; every failure ends the run the same way
                logger.exception(
                    "embedding_backfill_failed",
                    job_id=job_id,
                    force=force,
                    operation_id=operation_id,
                )
                await session.rollback()
                state.decide_failed(
                    error_code="backfill_failed", message=BACKFILL_FAILED_MESSAGE
                )
            else:
                if result["errors"] and not result["created"]:
                    # fix(#1550): `backfill_embeddings` swallows per-record
                    # provider errors and returns counts instead of raising,
                    # so a run where EVERY embedding failed would otherwise be
                    # stamped `complete` — zero coverage reported as success.
                    logger.error(
                        "embedding_backfill_all_records_failed",
                        job_id=job_id,
                        force=force,
                        operation_id=operation_id,
                        **result,
                    )
                    state.decide_failed(
                        error_code="all_embeddings_failed",
                        message=(
                            f"Embedding backfill failed: all {result['errors']} "
                            "embeddings were rejected and none were created. "
                            "Check the embedding provider and configuration, "
                            "then re-run to restore coverage."
                        ),
                        result=result,
                    )
                else:
                    state.decide_complete(result)
            # The single terminal write. Deciding the outcome and RECORDING it
            # are separate on purpose: exactly one place writes the job row
            # and audit trail, and exactly one place recovery resumes from.
            await _settle(
                session,
                job_uuid,
                attempt_uuid,
                metadata=metadata,
                state=state,
                audit_context=audit_context,
            )
        except BaseException as exc:
            # THE guarded exit — one, not one per exception type. Reached by
            # cancellation, by a failure of the terminal write itself, and by
            # anything else that unwinds past a claimed job.
            #
            # fix(#1550): catching only `CancelledError` let an `Exception`
            # raised INSIDE the terminal write escape, leaving the row
            # `running` and the slot held until the 60-minute sweep.
            #
            # `_settle` is idempotent and `state` records how far it got, so
            # this never rewrites a committed outcome — a shutdown after
            # `complete` landed emits the COMPLETED audit, not a contradiction.
            cancelled = isinstance(exc, asyncio.CancelledError)
            # A null heartbeat means the claim never landed, so this run never
            # took the job — a distinct outcome from failing to record one.
            if cancelled:
                event, error_code = "embedding_backfill_cancelled", "worker_cancelled"
                message = CANCELLED_MESSAGE
            elif heartbeat is None:
                event, error_code = "embedding_backfill_start_failed", "start_failed"
                message = START_FAILED_MESSAGE
            else:
                event, error_code = "embedding_backfill_settle_failed", "settle_failed"
                message = SETTLE_FAILED_MESSAGE
            logger.warning(
                event,
                job_id=job_id,
                force=force,
                operation_id=operation_id,
                exc_info=not cancelled,
            )
            try:
                # Shielded so the cancellation that triggered the recovery does
                # not also cancel it, and bounded so a hung database cannot
                # stall a deploy.
                await asyncio.shield(
                    asyncio.wait_for(
                        _recover_unsettled(
                            session,
                            job_uuid,
                            attempt_uuid,
                            metadata=metadata,
                            state=state,
                            audit_context=audit_context,
                            error_code=error_code,
                            message=message,
                        ),
                        timeout=15,
                    )
                )
            except BaseException:  # broad: best-effort recovery during shutdown; the raise below preserves the abort
                logger.warning(
                    "embedding_backfill_recovery_failed", job_id=job_id, exc_info=True
                )
            # Re-raised, always: swallowing a cancellation breaks cooperative
            # shutdown, and swallowing a settle failure would tell the queue a
            # run recorded itself when it may not have.
            raise
        finally:
            await stop_ingest_job_heartbeat(heartbeat)
