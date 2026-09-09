"""Lifecycle rules for ``catalog.dataset_refresh_runs``.

Every write to a run row goes through this module, shared by the request
side (creates the row at dispatch) and the worker side (finalizes it), since
``processing/`` cannot import ``modules.catalog``.

The row is created at DISPATCH, not at commit: if the worker dies mid-fetch,
an at-commit design would leave zero trace once the ``ingest_jobs`` row is
purged after its retention window.

Worker-facing functions key on ``ingest_job_id`` rather than a run id, so
nothing has to be threaded through Procrastinate task arguments — adding an
argument to a deferred task breaks in-flight jobs on deploy.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failure_reason import coded_failure_reason, redact_failure_reason
from app.platform.refresh.models import DatasetRefreshRun

logger = structlog.get_logger(__name__)

# Mirrors the three CHECK constraints on the table. Kept as tuples so a caller
# can validate before the database does and get a Python error naming the
# field rather than an IntegrityError naming the constraint.
RUN_STATUSES: tuple[str, ...] = (
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)
TERMINAL_RUN_STATUSES: tuple[str, ...] = ("succeeded", "failed", "cancelled")
ACTIVE_RUN_STATUSES: tuple[str, ...] = ("pending", "running")
RUN_TRIGGERS: tuple[str, ...] = ("manual", "api", "cli")
RUN_ORIGIN_KINDS: tuple[str, ...] = (
    "upload",
    "postgis",
    "service",
    "stac",
    "raster",
)

# How long a run may sit in pending/running before the sweep is allowed to
# consider it abandoned. Matches the ingest stale-job abandonment policy in
# platform/jobs/router.py. A legitimately long GDAL run is protected by the
# live-Procrastinate-job predicate below rather than by this number, so the
# cutoff only has to be longer than the gap between dispatch and claim.
ABANDONED_RUN_CUTOFF_SECONDS = 3600

ABANDONED_ERROR_CODE = "abandoned"
ABANDONED_ERROR_MESSAGE = (
    "The refresh task was never picked up by a worker, or the worker "
    "disappeared before recording an outcome."
)

# feat(#1677): an explicit user cancel, distinct from the sweep's `abandoned`
# correction under the same terminal `cancelled` status. `abandoned` means
# "the task is provably gone and nobody reported an outcome"; this means
# "a person asked in-flight work to stop".
USER_CANCELLED_ERROR_CODE = "user_cancelled"
USER_CANCELLED_ERROR_MESSAGE = "Cancelled by user."


def redact_run_error(message: str | BaseException) -> str:
    """ADR-002 Decision 3 applied to a run row's ``error_message``.

    fix(#1953): the clause is enforced in ``core/failure_reason.py``, shared
    with the ``ingest_jobs`` sink, rather than restated per caller.
    """
    return redact_failure_reason(message)


def drift_status_from_diff(schema_diff: dict[str, Any] | None) -> str | None:
    """Project a ``compute_schema_diff`` result onto ``schema_drift_status``.

    Returns ``None`` (stored NULL, rendered "unknown") when there is no diff
    to judge — the CHECK set deliberately excludes an ``'unknown'`` literal.

    A row-count change alone is NOT drift: only ``columns_added``,
    ``columns_removed`` and ``type_changes`` are structural (which is also
    why a column RENAME reads as drifted: one add plus one removal).
    """
    if not schema_diff:
        return None
    structural = (
        schema_diff.get("columns_added"),
        schema_diff.get("columns_removed"),
        schema_diff.get("type_changes"),
    )
    return "drifted" if any(structural) else "none"


async def _run_audit_context(
    session: AsyncSession, run_id: uuid.UUID
) -> tuple[uuid.UUID | None, uuid.UUID, dict[str, Any]] | None:
    """``(actor, dataset_id, details)`` for one run's audit event, or None.

    A run row is mutable and cascades with its dataset (deleting the dataset
    erases it), so the append-only audit log also gets an entry — the two
    answer different questions.

    Reads the row back rather than trusting the caller: every call happens
    AFTER the transition, so ``status``/``error_code`` are what landed.

    Payload is ids, origin kind, trigger, status, error code — never
    ``error_message`` (redacted free text; a closed vocabulary like
    ``error_code`` is safer for a record written for keeps).

    The four emitters below spell their action as a literal, not a param, so
    ``test_audit_action_registry`` can enumerate every action by reading
    the source; that only works on literals.
    """
    row = (
        await session.execute(
            select(
                DatasetRefreshRun.dataset_id,
                DatasetRefreshRun.origin_kind,
                DatasetRefreshRun.trigger,
                DatasetRefreshRun.status,
                DatasetRefreshRun.triggered_by,
                DatasetRefreshRun.error_code,
            ).where(DatasetRefreshRun.id == run_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return (
        row.triggered_by,
        row.dataset_id,
        {
            "run_id": str(run_id),
            "origin_kind": row.origin_kind,
            "trigger": row.trigger,
            "status": row.status,
            "error_code": row.error_code,
        },
    )


async def _emit_refresh_dispatch(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Record that a refresh was admitted. See :func:`_run_audit_context`."""
    from app.platform.audit import AuditEvent, audit_emit

    context = await _run_audit_context(session, run_id)
    if context is None:
        return
    actor, dataset_id, details = context
    await audit_emit(
        session,
        AuditEvent(
            user_id=actor,
            action="refresh.dispatch",
            resource_type="dataset",
            resource_id=dataset_id,
            details=details,
        ),
    )


async def _emit_refresh_succeeded(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Record a refresh that installed new data."""
    from app.platform.audit import AuditEvent, audit_emit

    context = await _run_audit_context(session, run_id)
    if context is None:
        return
    actor, dataset_id, details = context
    await audit_emit(
        session,
        AuditEvent(
            user_id=actor,
            action="refresh.succeeded",
            resource_type="dataset",
            resource_id=dataset_id,
            details=details,
        ),
    )


async def _emit_refresh_failed(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Record a refresh that reported an error and changed no data."""
    from app.platform.audit import AuditEvent, audit_emit

    context = await _run_audit_context(session, run_id)
    if context is None:
        return
    actor, dataset_id, details = context
    await audit_emit(
        session,
        AuditEvent(
            user_id=actor,
            action="refresh.failed",
            resource_type="dataset",
            resource_id=dataset_id,
            details=details,
        ),
    )


async def _emit_refresh_abandoned(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Record the sweep's bookkeeping correction.

    Deliberately not spelled ``refresh.failed``: a run nobody watched finish
    is a different thing to investigate than one that reported an error.
    """
    from app.platform.audit import AuditEvent, audit_emit

    context = await _run_audit_context(session, run_id)
    if context is None:
        return
    actor, dataset_id, details = context
    await audit_emit(
        session,
        AuditEvent(
            user_id=actor,
            action="refresh.abandoned",
            resource_type="dataset",
            resource_id=dataset_id,
            details=details,
        ),
    )


async def _emit_refresh_cancelled(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    cancelled_by: uuid.UUID | None = None,
) -> None:
    """Record an explicit user cancel (#1677).

    Deliberately not ``refresh.abandoned``: that is the sweep's correction
    for a task proven gone, while this records a person stopping in-flight
    work.

    fix(#1709): attributed to ``cancelled_by`` — the CANCELLING user —
    not the row's immutable ``triggered_by``, since a dataset owner may
    cancel a refresh someone else started; crediting the dispatcher would
    put the action in the wrong user's history. Falls back to the row's
    actor only when no canceller is supplied.
    """
    from app.platform.audit import AuditEvent, audit_emit

    context = await _run_audit_context(session, run_id)
    if context is None:
        return
    actor, dataset_id, details = context
    await audit_emit(
        session,
        AuditEvent(
            user_id=cancelled_by if cancelled_by is not None else actor,
            action="refresh.cancelled",
            resource_type="dataset",
            resource_id=dataset_id,
            details=details,
        ),
    )


class DatasetBusyError(Exception):
    """Another refresh run for this dataset is already pending or running.

    Raised by ``create_pending_run`` when the partial unique index refuses a
    second active row; the dispatch handler turns it into 409
    ``dataset_busy``. A domain error, not an HTTPException, so
    ``platform/`` stays free of a FastAPI dependency and callers can render
    it their own way.
    """


async def create_pending_run(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    origin_kind: str,
    trigger: str,
    triggered_by: uuid.UUID | None,
    ingest_job_id: uuid.UUID | None,
    feature_count_before: int | None,
) -> DatasetRefreshRun:
    """Insert the ``pending`` row in the caller's transaction, before ``defer``.

    The caller must NOT commit inside this function: the run row and
    whatever else the request writes must land together, and the task is
    deferred only after that commit succeeds.

    Raises ``DatasetBusyError`` when this dataset already has an active run.
    The refusal comes from ``uq_refresh_runs_one_active``, not a SELECT here,
    because a check-then-insert leaves a race window a double-click lands
    in. The INSERT runs inside a SAVEPOINT so the failure does not poison
    the caller's transaction.

    ``started_at``/``created_at`` are stamped in Python, not left to
    ``server_default``: a server default leaves the attribute expired after
    flush, and the next read lazy-loads, which under AnyIO raises
    ``MissingGreenlet`` instead of returning a value.
    """
    if origin_kind not in RUN_ORIGIN_KINDS:
        raise ValueError(f"unknown origin_kind {origin_kind!r}")
    if trigger not in RUN_TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")

    # Read the parent's STORED tenant_id rather than copying an ORM attribute:
    # the stamping trigger fills `datasets.tenant_id` in the DB while the ORM
    # attribute stays None, so copying it would write NULL. This table has
    # no trigger of its own (not in migration 0018's set).
    tenant_id = await session.scalar(
        text("SELECT tenant_id FROM catalog.datasets WHERE id = :dataset_id"),
        {"dataset_id": dataset_id},
    )

    # fix(#1274): a reupload enqueued by a still-draining PRE-migration API
    # pod has a live task but no run row, so the unique index can't referee
    # it — refuse admission while one exists. Predicate is deliberately
    # narrow (a LIVE task AND a job with no run row) since post-migration
    # dispatch creates the run in the same transaction, so only legacy work
    # matches and the check goes inert once those pods drain. Accepted gap
    # (r8): an old pod that committed its job but hasn't yet inserted the
    # task row is invisible here for those milliseconds; closing it needs a
    # deployment barrier between API generations.
    legacy_live = await session.scalar(
        text(
            """
            SELECT 1
            FROM catalog.ingest_jobs j
            JOIN catalog.procrastinate_jobs pj
              ON pj.args->>'job_id' = j.id::text
             AND pj.status IN ('todo', 'doing')
            WHERE j.dataset_id = :dataset_id
              AND (j.user_metadata->>'reupload') = 'true'
              AND (CAST(:dispatching_job_id AS uuid) IS NULL
                   OR j.id != CAST(:dispatching_job_id AS uuid))
              AND NOT EXISTS (
                  SELECT 1 FROM catalog.dataset_refresh_runs r
                  WHERE r.ingest_job_id = j.id
              )
            LIMIT 1
            """
        ),
        # dispatching_job_id, not ingest_job_id: the immutable-binding AST
        # check treats any dict key of that name as UPDATE values.
        {"dataset_id": dataset_id, "dispatching_job_id": ingest_job_id},
    )
    if legacy_live is not None:
        raise DatasetBusyError("A refresh is already in progress for this dataset.")

    now = datetime.now(timezone.utc)
    run = DatasetRefreshRun(
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        ingest_job_id=ingest_job_id,
        origin_kind=origin_kind,
        trigger=trigger,
        status="pending",
        triggered_by=triggered_by,
        started_at=now,
        created_at=now,
        feature_count_before=feature_count_before,
    )
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError as exc:
        if _ACTIVE_RUN_INDEX not in str(getattr(exc, "orig", exc)):
            raise
        raise DatasetBusyError(
            "A refresh is already in progress for this dataset."
        ) from exc
    # feat(#1268): in the caller's transaction, so a dispatch the caller then
    # rolls back — a busy dataset, a defer that never happened — leaves no
    # audit row claiming a refresh started.
    await _emit_refresh_dispatch(session, run.id)
    return run


# Matched against the driver's error text so an unrelated constraint
# violation (a bad FK, a CHECK) still propagates as itself rather than
# being misreported as "busy" — matching on IntegrityError alone would turn
# every future constraint on this table into a misleading 409.
_ACTIVE_RUN_INDEX = "uq_refresh_runs_one_active"


async def _active_run_id_for_job(
    session: AsyncSession, ingest_job_id: uuid.UUID
) -> uuid.UUID | None:
    """The non-terminal run bound to this job, if any.

    At most one can exist: ``uq_refresh_runs_one_active`` allows one active run
    per dataset, and a job belongs to exactly one dataset.
    """
    return await session.scalar(
        select(DatasetRefreshRun.id).where(
            DatasetRefreshRun.ingest_job_id == ingest_job_id,
            DatasetRefreshRun.status.in_(ACTIVE_RUN_STATUSES),
        )
    )


async def transition_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    expected: tuple[str, ...],
    to: str,
    values: dict[str, Any] | None = None,
) -> bool:
    """Compare-and-set one run's status. True when this caller won.

    Every status write names the state it believes the row is in. A blind
    ``UPDATE ... WHERE id`` would let a worker that lost its lease overwrite
    a terminal status the stale-run sweep already wrote, reporting an
    outcome that contradicts what actually happened.

    Zero rows updated is not an error or a retry signal: it means another
    actor owns this run now — callers log it and back off.

    ``expected`` is a tuple because a run can fail BEFORE it is claimed
    (SSRF revalidation in ``reupload_service``), so the failure path accepts
    both `pending` and `running`; it never contains a terminal state.
    """
    result = await session.execute(
        update(DatasetRefreshRun)
        .where(
            DatasetRefreshRun.id == run_id,
            DatasetRefreshRun.status.in_(expected),
        )
        .values(status=to, **(values or {}))
        .returning(DatasetRefreshRun.id)
    )
    if result.scalar_one_or_none() is not None:
        return True
    logger.info(
        "refresh_run_transition_lost",
        run_id=str(run_id),
        expected=list(expected),
        attempted=to,
    )
    return False


async def claim_run_for_job(
    session: AsyncSession, ingest_job_id: uuid.UUID
) -> uuid.UUID | None:
    """Move this job's run to ``running`` and stamp ``claimed_at``.

    Returns the run id when this caller won the transition, else None. None
    is normal (no run row at all, or another actor already moved it) — the
    ingest work proceeds regardless; the run row is history, never a gate.

    ``started_at`` stays at dispatch time; ``claimed_at`` is stamped here,
    and the gap between them IS the queue wait.
    """
    run_id = await _active_run_id_for_job(session, ingest_job_id)
    if run_id is None:
        return None
    won = await transition_run(
        session,
        run_id,
        expected=("pending",),
        to="running",
        values={"claimed_at": datetime.now(timezone.utc)},
    )
    return run_id if won else None


async def cancel_active_run_for_job(
    session: AsyncSession,
    ingest_job_id: uuid.UUID,
    *,
    error_message: str = USER_CANCELLED_ERROR_MESSAGE,
    cancelled_by: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Finalize this job's active run as ``cancelled`` on a user's request.

    The caller (the cancel endpoint) owns the transaction: this runs beside
    the fenced ``ingest_jobs`` CAS so the two terminal rows commit together,
    and the worker's finalize fence (``require_ingest_job_update``)
    guarantees no swap lands after that commit.

    Returns the run id when this caller won the CAS, else ``None`` (no run
    row bound to the job, or another actor finalized it first — both normal).
    """
    run_id = await _active_run_id_for_job(session, ingest_job_id)
    if run_id is None:
        return None
    won = await transition_run(
        session,
        run_id,
        expected=ACTIVE_RUN_STATUSES,
        to="cancelled",
        values={
            "finished_at": datetime.now(timezone.utc),
            "error_code": USER_CANCELLED_ERROR_CODE,
            "error_message": redact_run_error(error_message),
        },
    )
    if not won:
        return None
    await _emit_refresh_cancelled(session, run_id, cancelled_by=cancelled_by)
    return run_id


def project_refresh_success(
    dataset: Any,
    *,
    schema_diff: dict[str, Any] | None,
    contacted_origin: bool,
    now: datetime | None = None,
) -> None:
    """Write the dataset-level state a successful refresh establishes.

    Duck-typed on the Dataset ORM instance so ``platform/`` does not import
    ``modules.catalog``.

    ``last_refreshed_at`` is NOT set here: ``_apply_reupload_swap`` already
    stamps it as part of the swap, and two writers would be two answers.

    ``contacted_origin`` gates ``last_checked_at`` ("last time GeoLens
    contacted the origin") because a file re-upload contacts nothing — the
    bytes arrived from the browser. ``source_health`` is left alone on every
    path: its classifier belongs to #1222, not here.
    """
    dataset.schema_drift_status = drift_status_from_diff(schema_diff)
    if contacted_origin:
        dataset.last_checked_at = now or datetime.now(timezone.utc)


async def record_refresh_success(
    session: AsyncSession,
    *,
    ingest_job_id: uuid.UUID,
    dataset: Any,
    dataset_version_id: uuid.UUID | None,
    feature_count_after: int | None,
    schema_diff: dict[str, Any] | None,
    contacted_origin: bool,
) -> uuid.UUID | None:
    """Finalize this job's run as ``succeeded``; project drift onto the dataset.

    Called inside the worker transaction that commits the staging swap, so
    the run's terminal status and the job's ``complete`` status land
    together — that atomicity is what lets the stale-run sweep treat "job
    complete, run still running" as impossible.

    Expects ``running``: this worker claimed the run in phase 1. The dataset
    projection still runs even if that expectation fails — the swap DID
    happen and its drift is true regardless of who owns the bookkeeping row.
    """
    now = datetime.now(timezone.utc)
    project_refresh_success(
        dataset,
        schema_diff=schema_diff,
        contacted_origin=contacted_origin,
        now=now,
    )
    run_id = await _active_run_id_for_job(session, ingest_job_id)
    if run_id is None:
        return None
    won = await transition_run(
        session,
        run_id,
        expected=("running",),
        to="succeeded",
        values={
            "finished_at": now,
            "dataset_version_id": dataset_version_id,
            "feature_count_after": feature_count_after,
            "schema_diff": schema_diff,
        },
    )
    if not won:
        return None
    await _emit_refresh_succeeded(session, run_id)
    return run_id


async def record_refresh_failure(
    session: AsyncSession,
    *,
    ingest_job_id: uuid.UUID,
    error_code: str,
    error_message: str | BaseException,
    contacted_origin: bool,
    origin_binding: tuple[str | None, dict[str, Any] | None, str | None] | None = None,
) -> uuid.UUID | None:
    """Finalize this job's run as ``failed``.

    ``last_refreshed_at`` is untouched by construction: a failed refresh
    leaves the live table and its freshness exactly as they were.

    When the run did reach out to a remote origin, ``last_checked_at`` is
    stamped on the dataset via parameterized SQL (the failure handler runs
    in a fresh session with no dataset loaded, and ``platform/`` may not
    import the catalog ORM at module scope).

    fix(#1220): that stamp is a GUARDED write — ``origin_binding`` is the
    ``(origin_uri, origin_ref, source_format)`` triple read when the attempt
    started, and the UPDATE only lands while the row still carries it.
    Without the guard, a failure from an attempt whose dataset was rebound
    mid-flight (a concurrent re-upload finishing first) would date the NEW
    binding's contact from the OLD binding's doomed fetch. Passing
    ``contacted_origin=True`` without a binding raises, so the unguarded
    write is unreachable.

    Accepts both non-terminal states: a run can fail while still ``pending``
    (SSRF revalidation before phase 1, or the defer-guard rollback), not
    just after being claimed. Terminal states are excluded either way.
    """
    if contacted_origin and origin_binding is None:
        raise ValueError(
            "record_refresh_failure(contacted_origin=True) requires "
            "origin_binding; an ID-only contact stamp can land on a dataset "
            "that was rebound while the failing attempt was running."
        )
    now = datetime.now(timezone.utc)
    row = (
        await session.execute(
            select(DatasetRefreshRun.id, DatasetRefreshRun.dataset_id).where(
                DatasetRefreshRun.ingest_job_id == ingest_job_id,
                DatasetRefreshRun.status.in_(ACTIVE_RUN_STATUSES),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    won = await transition_run(
        session,
        row.id,
        expected=ACTIVE_RUN_STATUSES,
        to="failed",
        values={
            "finished_at": now,
            "error_code": error_code[:64],
            "error_message": redact_run_error(error_message),
        },
    )
    if not won:
        return None
    await _emit_refresh_failed(session, row.id)
    if contacted_origin:
        await _stamp_guarded_contact(
            session,
            dataset_id=row.dataset_id,
            binding=origin_binding,  # non-None: checked at the top
            now=now,
        )
    return row.id


# fix(#1220): jsonb, not text. `origin_ref` is compared semantically, so an
# attempt that read `{"url": ..., "kind": ...}` still matches a row whose
# stored key order differs — which a textual comparison would call a rebind.
_GUARDED_CONTACT_SQL = text(
    """
    UPDATE catalog.datasets
    SET last_checked_at = :now
    WHERE id = :dataset_id
      AND origin_uri IS NOT DISTINCT FROM :origin_uri
      AND origin_ref IS NOT DISTINCT FROM CAST(:origin_ref AS jsonb)
      AND source_format IS NOT DISTINCT FROM :source_format
    RETURNING id
    """
)


async def _stamp_guarded_contact(
    session: AsyncSession,
    *,
    dataset_id: uuid.UUID,
    binding: tuple[str | None, dict[str, Any] | None, str | None] | None,
    now: datetime,
) -> bool:
    """Date the origin contact, but only while the binding is still the one.

    Returns whether the write landed. Losing the race is a silent skip: the
    caller is a failed background attempt, there is nobody to tell, and the
    rebind's own commit stamped whatever is true now.

    ``GET /datasets/`` serves ``last_checked_at`` from a 60-second cache, so
    a landed write invalidates it, like every other writer of the field.
    """
    if binding is None:
        return False
    origin_uri, origin_ref, source_format = binding
    landed = await session.scalar(
        _GUARDED_CONTACT_SQL,
        {
            "now": now,
            "dataset_id": dataset_id,
            "origin_uri": origin_uri,
            "origin_ref": json.dumps(origin_ref) if origin_ref is not None else None,
            "source_format": source_format,
        },
    )
    if landed is None:
        logger.info("refresh_contact_stamp_skipped", dataset_id=str(dataset_id))
        return False
    from app.platform.cache.tiles import invalidate_catalog_cache

    await invalidate_catalog_cache()
    return True


def make_refresh_run_failed_rollback(
    inner: Any,
    *,
    db: AsyncSession,
    ingest_job_id: uuid.UUID,
) -> Any:
    """Wrap a defer-guard rollback so it also finalizes the run as ``failed``.

    ``defer_with_orphan_guard`` invokes the rollback and then commits, so
    both the job's failure and the run's land in one transaction — the run
    can never say `pending` for a dispatch that provably never happened.

    Finalized AFTER the inner rollback, so a raise from the inner closure
    keeps the pre-existing behaviour (still returns 503) instead of being
    masked by this wrapper.
    """

    async def _rollback(defer_exc: BaseException) -> None:
        await inner(defer_exc)
        await record_refresh_failure(
            db,
            ingest_job_id=ingest_job_id,
            error_code="dispatch_failed",
            error_message=coded_failure_reason(
                "Failed to queue refresh task", defer_exc
            ),
            contacted_origin=False,
        )

    return _rollback


# fix(#1274): guards the pathological legacy DOUBLE — the old system had no
# admission control, so two reupload tasks for one dataset can both be live
# at upgrade time, while the backfill's DISTINCT ON can represent only one
# (the unique index allows one active row). That row's reservation must
# outlive EVERY live legacy reupload task on the dataset, not just its bound
# job, or a new refresh could race the unrepresented worker's swap. Native
# runs are unaffected — a coincidental legacy task just delays finalization
# by one sweep cycle, the safe direction.
_NO_OTHER_LIVE_LEGACY_TASK = """
      AND NOT EXISTS (
          SELECT 1
          FROM catalog.ingest_jobs oj
          JOIN catalog.procrastinate_jobs pj
            ON pj.args->>'job_id' = oj.id::text
           AND pj.status IN ('todo', 'doing')
          WHERE oj.dataset_id = r.dataset_id
            AND oj.id IS DISTINCT FROM r.ingest_job_id
            AND (oj.user_metadata->>'reupload') = 'true'
      )
"""


# This statement is itself a compare-and-set: `status IN ('pending',
# 'running')` is the expected-state test, RETURNING gives the rowcount, so
# the sweep can no more overwrite a terminal status than `transition_run`.
#
# The dataset EXISTS clause looks redundant against a NOT NULL FK, and is
# not: `dataset_refresh_runs` carries no RLS policy of its own (dormant
# `tenant_id`, like `datasets`), so with RLS ENABLED this UPDATE would see
# every tenant's rows while the `ingest_jobs` sub-query beside it (RLS-
# enforced) sees only the current tenant's — reading another tenant's live
# job as absent. Joining through `catalog.datasets` puts the whole predicate
# in one visibility scope. No table has RLS enabled today (#998), so this is
# currently a no-op — written now rather than remembered later.
#
# fix(#1954): the two proofs THIS sweep needs before writing `cancelled`.
# ADR-002 4d gives the status two writers told apart by `error_code`:
# `abandoned` here, a bookkeeping correction provable only when the work is
# not happening, and `cancel_active_run_for_job`'s `user_cancelled` stop
# signal, which is a person's decision and needs no proof.
#
# 1. No live Procrastinate job references the bound ingest job (correlated
#    on args->>'job_id', inlined rather than importing
#    platform/jobs/sweep.py's `no_live_procrastinate_job` to avoid a
#    platform/jobs -> platform/refresh dependency). A NULL ingest_job_id
#    makes the comparison NULL, so NOT EXISTS holds: the job was purged.
#
# 2. The bound ingest job is absent, `failed`, or `pending` with no live
#    task. `running` is skipped (the ingest stale sweep runs first and
#    fails it out if genuinely dead). `pending` is NOT excluded (#1274):
#    proof 1 already shows no live task, and pending-plus-no-task past the
#    cutoff is exactly the create-then-defer death this sweep compensates
#    for — otherwise a presigned commit interrupted before its defer would
#    hold the reservation for 24h, refusing every retry with dataset_busy.
#    `complete` can't coexist with an active run for NATIVE rows (success
#    and job completion commit together); where it does (migration 0037
#    backfilled legacy rows), _LEGACY_COMPLETED_RUN_SQL records the success
#    instead and this statement stays hands-off.
_ABANDONED_RUN_SQL = text(
    """
    UPDATE catalog.dataset_refresh_runs AS r
    SET status = 'cancelled',
        finished_at = :now,
        error_code = :error_code,
        error_message = :error_message
    WHERE r.status IN ('pending', 'running')
      AND r.started_at < :cutoff
      AND EXISTS (
          SELECT 1 FROM catalog.datasets d WHERE d.id = r.dataset_id
      )
      AND NOT EXISTS (
          SELECT 1 FROM catalog.procrastinate_jobs pj
          WHERE pj.args->>'job_id' = r.ingest_job_id::text
            AND pj.status IN ('todo', 'doing')
      )
      AND NOT EXISTS (
          SELECT 1 FROM catalog.ingest_jobs j
          WHERE j.id = r.ingest_job_id
            AND j.status IN ('running', 'complete')
      )
"""
    + _NO_OTHER_LIVE_LEGACY_TASK
    + """
    RETURNING r.id
    """
)


# fix(#1274): truth-recording counterpart to the abandonment cancel below.
# For a NATIVE run, "bound job complete + run still active" is impossible
# by construction (success and job completion commit together), which is
# why _ABANDONED_RUN_SQL refuses to touch it. But migration 0037's backfill
# creates active rows for refreshes already running in PRE-migration
# workers, which mark the job complete without calling the new finalizer.
# A complete job IS proof the swap committed, so the honest terminal state
# is `succeeded`. No cutoff: the job's terminal status is proof enough.
_LEGACY_COMPLETED_RUN_SQL = text(
    """
    UPDATE catalog.dataset_refresh_runs AS r
    SET status = 'succeeded',
        finished_at = COALESCE(j.completed_at, :now)
    FROM catalog.ingest_jobs j
    WHERE j.id = r.ingest_job_id
      AND r.status IN ('pending', 'running')
      AND j.status = 'complete'
"""
    + _NO_OTHER_LIVE_LEGACY_TASK
    + """
    RETURNING r.id
    """
)


async def sweep_abandoned_refresh_runs(
    session: AsyncSession, now: datetime | None = None
) -> int:
    """Finalize runs whose outcome is provable without a worker's report.

    Two statements, two proofs. The first records success for active runs
    whose bound job completed — only reachable for migration 0037's
    backfilled rows, whose legacy workers finished without knowing this
    table exists. The second cancels runs whose task is proven gone: the
    compensation for create-then-defer not being atomic — a process that
    dies between the commit and the ``defer`` leaves a run ``pending`` with
    no task behind it.

    Returns the number of runs finalized by either statement.
    """
    resolved_now = now or datetime.now(timezone.utc)
    completed = await session.execute(_LEGACY_COMPLETED_RUN_SQL, {"now": resolved_now})
    result = await session.execute(
        _ABANDONED_RUN_SQL,
        {
            "now": resolved_now,
            "cutoff": resolved_now - timedelta(seconds=ABANDONED_RUN_CUTOFF_SECONDS),
            "error_code": ABANDONED_ERROR_CODE,
            "error_message": ABANDONED_ERROR_MESSAGE,
        },
    )
    # RETURNING rows, not a rowcount: an ORM UPDATE..RETURNING carries no
    # usable `.rowcount`, and the ids are needed anyway.
    recovered = list(completed.scalars())
    cancelled = list(result.scalars())
    # feat(#1268): these are the only terminal transitions no worker
    # reports, so without an event here the audit log shows a dispatch and
    # then nothing. Emitted per run, not as one summary row: the audit log
    # is keyed on a resource, and "seven runs reconciled" names none.
    for run_id in recovered:
        await _emit_refresh_succeeded(session, run_id)
    for run_id in cancelled:
        await _emit_refresh_abandoned(session, run_id)
    return len(recovered) + len(cancelled)


async def list_runs_for_dataset(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[DatasetRefreshRun], int]:
    """Newest-first page of one dataset's refresh history, plus the total.

    Ordered by ``started_at`` (dispatch time) with an id tiebreaker, so two
    runs dispatched inside the same clock tick cannot swap places between
    pages and hide a row.
    """
    from sqlalchemy import func as sa_func

    total = await session.scalar(
        select(sa_func.count())
        .select_from(DatasetRefreshRun)
        .where(DatasetRefreshRun.dataset_id == dataset_id)
    )
    result = await session.execute(
        select(DatasetRefreshRun)
        .where(DatasetRefreshRun.dataset_id == dataset_id)
        .order_by(DatasetRefreshRun.started_at.desc(), DatasetRefreshRun.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars()), int(total or 0)
