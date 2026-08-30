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

# Audit outcome for a run whose fate could not be written to its job row —
# another actor settled the row first. It is terminal (the operation is over and
# the trail says so) but it deliberately does not claim the run succeeded or
# failed, because on this path the worker no longer owns that answer.
UNRESOLVED_OUTCOME = "unresolved"


# The statuses that hold the slot. Must stay byte-identical to the predicate of
# `uq_ingest_jobs_active_embedding_backfill` (migration 0050) — the index is the
# guard, this query is only the friendly half that produces a readable 409, and
# a query admitting a run the index then refuses would turn every such request
# into a 409 the operator cannot act on.
SLOT_HOLDING_STATUSES = ("pending", "running")


async def find_active_embedding_backfill(session: AsyncSession) -> IngestJob | None:
    """Return the embedding backfill run currently holding the slot, if any.

    Keyed on status alone, deliberately, and NOT on a heartbeat lease.

    fix(#1542 review P1): an earlier revision admitted a new run once a
    ``running`` row's heartbeat had gone stale, on the reasoning that a dead
    worker should not lock an operator out forever. A partial unique index
    cannot express that — its predicate has to be immutable, so it cannot
    consult ``now()`` — and the two halves disagreeing is worse than either
    rule: the query says go, the index says no, and the operator gets a 409
    naming a job that by the query's own reckoning is not running.

    Status-only is also the stronger rule, which is the right side to err on
    for a force run that DELETEs every embedding before regenerating. A stale
    heartbeat is not proof the old worker is gone; it is proof we have not
    heard from it. Admitting a second regenerate on that evidence is exactly
    the concurrent double-DELETE this guard exists to prevent.

    The slot is released when the row reaches a terminal status — by the worker
    finishing, or by the stale-job sweeper, which fails abandoned ``running``
    rows on the shared 60-minute ingest backstop and runs every five minutes.
    That is the same release path every other abandoned ingest job has.

    Scoped per tenant in hosted mode, matching the index's key: the backfill
    only ever touches records the calling tenant can see, so one tenant's run
    must not lock another's out.
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
    extra_metadata: dict[str, Any] = {}
    if result is not None:
        backfill_meta["result"] = result
        values["rows_processed"] = result["processed"]
        # fix(#1550 review): surfaced through JobStatusResponse.rows_failed so
        # a partly-failed run is visible to whoever is watching. A run that
        # created most of the catalog and had some records rejected is
        # `complete` and is not a clean success. fix(#1549): after a force run
        # those rejections are records that KEPT their old vectors, since a
        # record whose replacement never committed never had its existing row
        # deleted — so the gap is stale coverage rather than none.
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
        # One operation, one terminal entry, and the DATABASE decides which —
        # `uq_audit_logs_terminal_embedding_backfill` (migration 0051). The
        # poll and the sweeper can both legitimately close a run this worker is
        # still inside, so a check here would be a check-then-insert. Losing
        # that race raises IntegrityError, which `audit_emit_durable` contains
        # on its own session.
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

    fix(#1550 review P2, round 3): this PR fixed the "job row and audit trail
    must agree" class four times — the dispatch failure, the lost fence, the
    cancellation — and each fix revealed one more exit that did not go through
    it. The exits are not the problem; a handler per exception type is. Every
    way this task can end now funnels through :func:`_settle`, and this record
    is what makes that safe: it knows whether the terminal row write has already
    landed, so the recovery path never overwrites a committed outcome and never
    skips one that is still missing.
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
    # fix(#1550 review): the live status the row was OBSERVED in. Every
    # recovery path in this module was built around `running` — the fence
    # matches running, the heartbeat covers running, the sweeper expires
    # running — so a run whose claim commit was lost sat in `pending`,
    # invisible to all of it, holding the unique slot (which counts pending and
    # running alike) until stale cleanup. Recovery terminalizes from whatever
    # state it finds rather than from the one it expected.
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

    Idempotent by construction: each half is skipped if it has already been
    done. That is what lets the recovery path call this again after a failure or
    a cancellation without overwriting a committed outcome. It is deliberately
    the SAME function on both paths, so a recovery cannot drift from the happy
    path it is recovering.
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

    fix(#1550 review P2): the recovery opened a fresh session while the caller's
    transaction was still open and still holding the job row's lock — a
    cancellation during ``session.commit()`` leaves exactly that state. The
    recovery's UPDATE then blocked on its own caller until the 15s timeout
    expired, after which nothing had been written and the row stayed ``running``,
    holding the unique backfill slot until the stale sweep. You cannot take a
    lock the thing you are recovering from is still holding.

    Bounded separately from the caller's overall timeout so a wedged rollback
    cannot consume the whole budget, and escalating to ``invalidate()`` — which
    drops the connection rather than trying to speak to it — because a
    connection that will not roll back will not do anything else either, and
    dropping the socket is what actually releases the server-side lock.
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

    fix(#1550 review P2, round 4): the previous revision decided what the
    recovery owed from ``state.row_attempted``, an in-process flag set after
    ``_finalize`` returned. That flag cannot describe what the database did. If
    PostgreSQL committed the terminal ``complete`` but the acknowledgement was
    lost — a cancellation or a dropped connection during ``commit()`` — the flag
    stayed False, the recovery retried the fenced update, matched nothing
    (because the row was already complete, not running), and recorded
    ``unresolved`` over a committed success.

    "My fenced update matched nothing" has two causes that demand opposite
    audit entries: someone else settled the row, or I settled it and never heard
    back. No flag can tell them apart. The row can, so ask it.

    The rule this settles on: **the audit describes the row.** If the row's
    terminal status is the one this run decided, the decided outcome is true of
    it and is what gets recorded — whoever's write landed. If it differs, the
    row belongs to someone else's decision and the entry says UNRESOLVED. That
    covers the lost acknowledgement, the late cancellation, and the stale-sweeper
    race with one read and no special cases.
    """
    from app.core.db import async_session

    await _release_caller_transaction(session, audit_context["job_id"])

    if state.status is None:
        state.decide_failed(error_code=error_code, message=message)

    async with async_session() as fresh:
        observed = await fresh.get(IngestJob, job_uuid)
        if observed is not None and observed.status in _TERMINAL_STATUSES:
            # Settled already. Whether by this run's own committed write or by
            # another actor, the trail must describe what the row says.
            #
            # fix(#1556 review, codex P2): status-matching is deliberately
            # enough HERE, unlike in `_undispatched_settle_write_landed`, and
            # the difference is worth stating because the two reads look
            # identical. This one is reached only after this worker took the
            # delivery, so "did the operation run at all" is already answered.
            # `complete` has exactly one producer for a backfill row — this
            # attempt's own fenced `_finalize` — so matching it proves
            # authorship. `failed` has several producers, but every one of
            # them records the same `outcome`, differing only in `error_code`,
            # and each is a true description of a run that ended without
            # success. Where they do differ the residual imprecision points
            # the safe way: `worker_cancelled` warns that a force run's
            # vectors may already be gone, which is the conservative claim.
            # The dispatch cleanup had neither property, which is why it needs
            # evidence of its own write rather than a matching status.
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

    fix(#1556 review, codex P2): observing `status == "failed"` is observing
    the state this write would have produced, not evidence that it produced
    it — and `failed` is a state four other actors also write. The reachable
    case: the dispatch DID land, a worker claimed the job and finalized it
    `failed`, and only then was the request cancelled. The fenced update
    matches nothing (the row is no longer `pending`) and its acknowledgement
    is lost as well, so a status-only read calls the WORKER's failure this
    cleanup's write and records `dispatch_cancelled` — which says the run
    never started and nothing was deleted, over a force regenerate that ran
    and failed after deleting every vector. Terminal entries are unique per
    job id (migration 0051), so that entry then refuses the worker's real
    `backfill_failed`: a lie that also evicts the truth.

    ``UNDISPATCHED_RUN_MESSAGE`` is written at exactly one site, this one, and
    once the row is terminal no other writer can overwrite it (every one of
    them is fenced on a live status). So it is a marker only this write can
    have left, which is the fact the caller actually needs.

    Bounded separately, like ``_release_caller_transaction``: this runs during
    a shutdown that has already lost one database round trip, and a second one
    hanging must not extend the drain.
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
    job_uuid: uuid.UUID, *, audit_context: dict[str, Any]
) -> None:
    """Settle a run that was committed but never reliably queued.

    fix(#1550 review): ``defer_with_orphan_guard`` catches ``Exception``, so a
    cancellation during dispatch walks past it AND past the route's
    ``DeferFailed`` handler — the third time on this PR that ``except
    Exception`` has silently excluded ``BaseException``, now at the point where
    the job is created rather than where it ends. The row stays ``pending``
    with no worker coming for it, and because the unique index counts
    ``pending`` and ``running`` alike, it blocks every later backfill just as
    effectively as a stuck running one.

    Fenced on ``pending`` so it cannot overwrite a run a worker did pick up
    after all — the dispatch may well have reached the queue before the
    cancellation landed, which is precisely why this is fenced rather than
    unconditional.

    fix(#1556): the settle's own commit is the last awaited commit on this
    lifecycle that still sat outside the recovery boundary. It runs under the
    cancellation that triggered it, so losing its acknowledgement is the
    ordinary case rather than the exotic one — and the row it leaves behind is
    ``failed``, which every sweeper skips because it is terminal. Nothing
    would ever have closed the trail, so the run would keep ``requested`` as
    its last word over a job the database records as failed. Same rule as
    ``_recover_unsettled``: when the answer is lost, read the row — and read
    it for evidence of THIS write rather than for the state this write would
    have produced, because ``failed`` is a state four other actors also
    reach. See ``_undispatched_settle_write_landed``.
    """
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
        # A worker took it, or the lost write never landed after all. Leave
        # both records to whoever owns the row now — a worker that claimed the
        # delivery closes its own trail, and a row still ``pending`` is closed
        # by the stale-pending sweep, which writes the status and the entry in
        # one transaction.
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

    ``retry=0``: a replay starts from scratch. fix(#1549) removed the reason
    this used to give — a force run no longer deletes ahead of regenerating, so
    an automatic replay would not delete a second time — but the flag stays,
    because a replay would re-embed every record the first attempt had already
    written, at provider rates, on behalf of an operator who never asked for it.
    Failures are terminal and the operator restarts the run, which picks up
    where it makes sense to rather than where the worker died.
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
        state = _TerminalState()
        heartbeat = None
        try:
            # fix(#1550 review): the claim is INSIDE the guarded region. Its
            # own commit is a lost-acknowledgement window at the other end of
            # the run — a shutdown cancelling `pending`->`running` mid-commit
            # can apply it without returning, and with the claim outside, the
            # recovery never ran: the row stayed `running`, held the unique
            # slot until the stale sweep, and kept only its `requested` entry.
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

            # fix(#1709 review r6): the cooperative stop signal, read off the
            # JOB ROW rather than procrastinate's abort flag — the DB CAS is
            # the cancel design's correctness mechanism, and the row also
            # covers settles by the sweeps. Polled by backfill_embeddings once
            # per batch, so a user cancel whose best-effort queue abort was
            # lost stops this run within one batch of provider spend; the
            # fenced _settle below then loses to the committed cancel exactly
            # like every other worker, and the terminal-audit unique index
            # arbitrates the trail. Same session on purpose: the loop commits
            # per batch and READ COMMITTED shows each new statement the
            # latest committed status either way.
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
                    # fix(#1550 review P1): `backfill_embeddings` swallows
                    # per-record provider errors and returns counts rather than
                    # raising, so a run where EVERY embedding failed returned
                    # normally and was stamped `complete`. On the force path
                    # that reads as a finished regenerate over a catalog whose
                    # vectors were deleted and never rebuilt — zero coverage
                    # reported as success, which is the one state an operator
                    # most needs to be told about.
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
            # are separate steps on purpose: everything above only decides, so
            # there is exactly one place where the job row and the audit trail
            # are written, and exactly one place the recovery below has to
            # resume from.
            await _settle(
                session,
                job_uuid,
                attempt_uuid,
                metadata=metadata,
                state=state,
                audit_context=audit_context,
            )
        except BaseException as exc:
            # THE guarded exit — one, not one per exception type. Reached by a
            # cancellation (a deploy draining the worker), by a failure of the
            # terminal write itself (a connection blip after the provider work
            # finished), and by anything else that unwinds past a claimed job.
            #
            # fix(#1550 review P2 round 3): the previous revision caught only
            # `CancelledError` here, so an `Exception` raised INSIDE the
            # terminal write escaped — leaving the row `running`, holding the
            # single active-backfill slot until the 60-minute sweep, and
            # reporting finished provider work as nothing at all. Same harm as
            # the cancellation bug, reached one line further in.
            #
            # `_settle` is idempotent and `state` records how far it got, so
            # this never rewrites an outcome that already committed: a shutdown
            # arriving after `complete` landed emits the COMPLETED audit rather
            # than contradicting a durable success.
            cancelled = isinstance(exc, asyncio.CancelledError)
            logger.warning(
                "embedding_backfill_cancelled"
                if cancelled
                else "embedding_backfill_settle_failed",
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
                            error_code=(
                                "worker_cancelled" if cancelled else "settle_failed"
                            ),
                            message=(
                                "Embedding backfill was cancelled by a worker "
                                "shutdown. Records it had already reached carry "
                                "their new vectors and the rest are unchanged; "
                                "re-run to finish the remainder."
                                if cancelled
                                else "Embedding backfill could not record its "
                                "outcome. See server logs for details."
                            ),
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
