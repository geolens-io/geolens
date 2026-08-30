"""Lifecycle rules for ``catalog.dataset_refresh_runs``.

feat(#1219, #1223) / ADR-002 Decision 4. Every write to a run row goes through
this module so the state machine has one implementation shared by the request
side (which creates the row at dispatch) and the worker side (which finalizes
it). ``processing/`` cannot import ``modules.catalog``, so a helper either
lives here or gets copy-pasted into both — and a copy-pasted state machine is
how handoff invariant 11 ("same executor") dies quietly.

The row is created at DISPATCH, not at commit (Decision 4b). Writing only at
commit cannot represent a run that never committed: if the worker dies
mid-fetch, an at-commit design leaves zero trace, and the ``ingest_jobs`` row
that might have hinted at the failure is purged after the retention window.

The functions the worker calls key on ``ingest_job_id`` rather than taking a
run id, so nothing has to be threaded through the Procrastinate task
arguments. Task args are durable rows in PostgreSQL; adding an argument to a
deferred task also breaks in-flight jobs on deploy.
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

from app.core.url_redaction import redact_url_credentials
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

# Cap on the stored failure text. GDAL stderr can run to kilobytes and the
# useful part is at the front.
_MAX_ERROR_MESSAGE_CHARS = 2000

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


def redact_run_error(message: str) -> str:
    """Short, credential-free failure text for a run row.

    ADR-002 Decision 3 forbids a raw exception, a URL carrying query-string
    credentials, or a GDAL command line in any stored reason string.
    ``redact_url_credentials`` handles free text as well as URLs — its
    scheme-less branch scans the string for URL-shaped substrings — which is
    what GDAL stderr actually is.
    """
    return redact_url_credentials(message)[:_MAX_ERROR_MESSAGE_CHARS]


def drift_status_from_diff(schema_diff: dict[str, Any] | None) -> str | None:
    """Project a ``compute_schema_diff`` result onto ``schema_drift_status``.

    Returns ``None`` (stored as NULL, rendered as "unknown") when there is no
    diff to judge. NULL is the only spelling of "never determined" — the CHECK
    set deliberately excludes an ``'unknown'`` literal.

    A row-count change alone is NOT drift. The column answers "did the shape
    of the data change", and a service that gained ten features overnight has
    the schema it had yesterday. Only ``columns_added``, ``columns_removed``
    and ``type_changes`` are structural, which is also what makes a column
    RENAME read as drifted: one add plus one removal.
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

    feat(#1268) / ADR-002 Amendment A10. A run row is mutable and cascades
    with its dataset, so it is a status board rather than a ledger: delete the
    dataset and every trace of what was ever pulled into it goes too. The
    audit log is append-only and survives, which is why the lifecycle emits
    into it as well. The two records answer different questions and neither
    replaces the other.

    Reads the row back rather than taking the caller's word for it. Every
    caller invokes this AFTER its transition, so ``status`` and ``error_code``
    are what actually landed — a caller that believed it wrote something else
    cannot log the belief.

    The payload is ids, origin kind, trigger, status and error code, and
    nothing else. Not the origin URI, not ``origin_ref``, not the schema diff,
    and specifically not ``error_message``: that is redacted free text, and
    redaction is the wrong thing to lean on when a closed vocabulary is
    available. ``error_code`` carries the same diagnostic value with none of
    the exposure, and audit rows are written for keeps.

    The four emitters below spell their action as a literal rather than taking
    it as an argument, so ``test_audit_action_registry`` can see every action
    this module writes by reading it. That guard is the reason the registry
    and the frontend's display list cannot drift apart again, and it only
    works on literals.
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

    Deliberately not spelled ``refresh.abandoned``: that action is the
    sweep's bookkeeping correction for a task proven gone, while this one
    records a person asking in-flight work to stop.

    fix(#1709 review r8 B): attributed to ``cancelled_by`` — the CANCELLING
    user — not the run row's immutable ``triggered_by``. The two differ in
    exactly the case the cancel design added authz arm 3 for: a dataset
    owner cancelling a refresh someone else started. The dispatcher's
    identity is not lost — ``refresh.dispatch`` already names it, and the
    same ``job.cancel`` transaction names the canceller — so attributing
    this event to the dispatcher would put an action in one user's history
    that a different user performed. Falls back to the row's actor only
    when no canceller is supplied (no such caller exists today; the default
    keeps a future non-request caller from attributing to nobody).
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
    second active row. The dispatch handler turns it into ADR-002 Decision 5b's
    409 ``dataset_busy``. It is a domain error rather than an HTTPException so
    ``platform/`` does not depend on FastAPI, and so the CLI and the future
    server-side refresh endpoint can render it their own way.
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

    The caller must NOT commit inside this function: the whole point of
    Decision 4b is that the run row and whatever else the request writes land
    together, and the task is deferred only after that commit succeeds.

    Raises ``DatasetBusyError`` when this dataset already has an active run.
    The refusal comes from ``uq_refresh_runs_one_active`` rather than from a
    SELECT here, because a check-then-insert leaves a window between the two
    statements and that window is precisely where a double-click lands. The
    INSERT runs inside a SAVEPOINT so the failure does not poison the caller's
    transaction — the handler still has to render a 409 and, on the reupload
    door, the job row it already wrote is rolled back with the request.

    ``started_at`` and ``created_at`` are stamped in Python rather than left to
    ``server_default``. A server default leaves the attribute expired after
    flush, and the next read lazy-loads — which under AnyIO raises
    ``MissingGreenlet`` rather than returning a value.
    """
    if origin_kind not in RUN_ORIGIN_KINDS:
        raise ValueError(f"unknown origin_kind {origin_kind!r}")
    if trigger not in RUN_TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")

    # Read the parent's STORED tenant_id rather than copying an ORM attribute.
    # In multi-tenant mode the stamping trigger fills `datasets.tenant_id` in
    # the database while the ORM attribute stays None, so the attribute would
    # have written NULL on exactly the installs the column exists for. This
    # table carries no trigger of its own (it is not in migration 0018's set),
    # which is why the value is written here at all.
    tenant_id = await session.scalar(
        text("SELECT tenant_id FROM catalog.datasets WHERE id = :dataset_id"),
        {"dataset_id": dataset_id},
    )

    # fix(#1274 review): a reupload enqueued by a still-draining PRE-migration
    # API pod has a live task but no run row, so the index cannot referee it.
    # Refuse admission while one exists for this dataset. The predicate is
    # deliberately narrow — a LIVE Procrastinate task AND a job with no run
    # row of any status — because post-migration dispatch creates the run in
    # the same transaction, so only legacy work can ever match and the check
    # is inert once those pods drain. One gap is accepted and documented
    # rather than closed (fix #1274 review r8): an old pod that has committed
    # its job but not yet inserted the task row is invisible here for those
    # milliseconds, and no marker can distinguish that state from a staged
    # preview in legacy rows — treating both as busy would 409 refreshes
    # behind every parked preview. Closing it needs a deployment barrier
    # between API generations; single-node compose deploys (the shipping
    # mode) never overlap generations, and rolling K8s deploys bound the
    # exposure to concurrent same-dataset commits during the pod swap.
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


# The index name is matched against the driver's error text so an unrelated
# constraint violation — a bad FK, a CHECK — still propagates as itself rather
# than being reported to the user as "busy". Matching on IntegrityError alone
# would turn every future constraint on this table into a misleading 409.
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

    Every status write goes through here, and every one of them names the
    state it believes the row is in. A blind ``UPDATE ... WHERE id`` would let
    a worker that lost its lease overwrite a terminal status the stale-run
    sweep had already written — the row would then report an outcome that
    contradicts what actually happened, which is worse than reporting nothing.

    Zero rows updated is not an error and not a retry signal: it means another
    actor owns this run now. Log it and back off, which is what the callers do.

    ``expected`` is a tuple because one legitimate caller has two acceptable
    prior states: a run can fail BEFORE it is claimed (``reupload_service``
    revalidates its URL for SSRF before phase 1), so the failure path accepts
    `pending` as well as `running`. What matters, and what the tuple never
    contains, is a terminal state.
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

    Returns the run id when this caller won the transition, else None.

    None is normal, not an error, and covers two different cases the caller
    treats identically: there is no run row at all (a re-upload dispatched
    before this table existed), or another actor already moved it. Both mean
    "this worker does not own a run", and the ingest work proceeds regardless —
    the run row is history, never a gate on the data path.

    ``started_at`` stays at dispatch time; ``claimed_at`` is stamped here, and
    the gap between them IS the queue wait.
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

    feat(#1677). The caller (the cancel endpoint) owns the transaction: this
    runs beside the fenced ``ingest_jobs`` CAS so the two terminal rows commit
    together, and the worker's finalize fence (``require_ingest_job_update``)
    is what guarantees no swap can land after that commit.

    Returns the run id when this caller won the CAS, else ``None`` — no run
    row is bound to the job (plain imports), or another actor finalized it
    first. Both are normal, not errors.
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
    ``modules.catalog`` — the same shape ``platform/dataset_origin.py`` uses.

    ``last_refreshed_at`` is NOT set here: ``_apply_reupload_swap`` already
    stamps it as part of the swap, and two writers would be two answers.

    ``contacted_origin`` gates ``last_checked_at`` because that column means
    "the last time GeoLens contacted the origin at all". A file re-upload
    contacts nothing — the bytes arrived from the browser — so stamping it
    would claim a probe that never happened. ``source_health`` is deliberately
    left alone on every path: the health vocabulary and its classifier belong
    to the probe issue (#1222), and inventing a mapping here would put a
    second, weaker classifier in the tree.
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
    """Finalize this job's run as ``succeeded`` and project drift onto the dataset.

    Called inside the worker transaction that commits the staging swap, so the
    run's terminal status and the job's ``complete`` status land together. That
    atomicity is what lets the stale-run sweep treat "job complete, run still
    running" as impossible rather than as a state it has to guess about.

    Expects ``running``: this worker claimed the run in phase 1, and anything
    else means it lost ownership in between. The dataset projection still runs
    — the swap DID happen and the drift it measured is true regardless of who
    owns the bookkeeping row.
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
    error_message: str,
    contacted_origin: bool,
    origin_binding: tuple[str | None, dict[str, Any] | None, str | None] | None = None,
) -> uuid.UUID | None:
    """Finalize this job's run as ``failed``.

    ``last_refreshed_at`` is untouched by construction — nothing here writes
    it. A failed refresh leaves the live table and its freshness exactly as
    they were, which is handoff invariant 10.

    When the run did reach out to a remote origin, ``last_checked_at`` is
    stamped on the dataset: the attempt happened whether or not it worked, and
    that is precisely the concept that column carries. The UPDATE goes through
    parameterized SQL rather than the ORM class because the failure handler
    runs in a fresh session with no dataset loaded, and ``platform/`` may not
    import the catalog ORM at module scope.

    fix(#1220): that stamp is a GUARDED write, and ``origin_binding`` is what
    makes it one. It is the ``(origin_uri, origin_ref, source_format)`` triple
    the failing attempt read when it started, and the UPDATE only lands while
    the row still carries it. Without the guard, a failure report from an
    attempt whose dataset was rebound mid-flight — a concurrent re-upload
    finishing first, say — would date the NEW binding's contact from the OLD
    binding's doomed fetch, and for a rebind to an upload that is a contact
    time nothing could ever have produced. Same discipline as
    ``_record_failed_origin_contact`` in ``tasks_reupload.py``, which is the
    dataset-side writer on the service path; this is the one every other
    caller reaches. Passing ``contacted_origin=True`` without a binding raises
    rather than falling back to an ID-only write, so the unguarded shape is
    not reachable at all.

    Accepts both non-terminal states. A run usually fails after it was claimed,
    but not always: ``reupload_service`` revalidates its URL for SSRF before
    phase 1, so that failure arrives while the run is still ``pending``, as
    does the defer-guard rollback. Terminal states are excluded either way,
    which is the guarantee that matters.
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

    ``GET /datasets/`` serves ``last_checked_at`` from a 60-second cache, so a
    landed write invalidates it — every other writer of the field does, and a
    lost race changed nothing worth invalidating for.
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

    ``defer_with_orphan_guard`` invokes the rollback and then commits, so both
    the job's failure and the run's land in one transaction — the run can
    never say `pending` for a dispatch that provably never happened.

    The run is finalized AFTER the inner rollback, so a raise from the inner
    closure keeps the pre-existing behaviour (guard logs it and still returns
    503) rather than being masked by this wrapper's own work.
    """

    async def _rollback(defer_exc: BaseException) -> None:
        await inner(defer_exc)
        await record_refresh_failure(
            db,
            ingest_job_id=ingest_job_id,
            error_code="dispatch_failed",
            error_message=f"Failed to queue refresh task: {defer_exc}",
            contacted_origin=False,
        )

    return _rollback


# The shared last clause guards the pathological legacy DOUBLE (fix #1274
# review): the old system had no admission control, so two reupload tasks for
# one dataset can both be live at upgrade time, while the backfill's DISTINCT
# ON could only represent one of them — the unique index allows one active
# row. That sole row's reservation must therefore outlive EVERY live legacy
# reupload task on the dataset, not just its bound job: releasing on the
# bound job's completion would let a new refresh race the unrepresented
# worker's swap. Native runs are unaffected in practice — their own job's
# live task is already accounted for, and a coincidental legacy task on the
# same dataset merely delays finalization by a sweep cycle, which is the
# safe direction.
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
# 'running')` is the expected-state test, and RETURNING gives the rowcount, so
# the sweep can no more overwrite a terminal status than `transition_run` can.
#
# The dataset EXISTS clause looks redundant against a NOT NULL FK, and is not.
# `dataset_refresh_runs` has no RLS policy of its own — its `tenant_id` is
# dormant, like the one on `datasets` — so wherever RLS is ENABLED this UPDATE
# would otherwise see every tenant's rows on every tenant's pass, while the
# `ingest_jobs` sub-query beside it, on a table that does carry a policy, saw
# only the current tenant's jobs and so read another tenant's live job as
# absent. Joining through `catalog.datasets` puts the whole predicate in one
# visibility scope. No table has RLS enabled today (enablement is #998's
# work), so this is currently the no-op it appears to be — which is exactly
# why it has to be written now rather than remembered later.
#
# The two proofs the sweep needs before it may write `cancelled`. ADR-002
# Decision 4d is explicit that this status is a bookkeeping correction and
# never a stop signal, so it may only be written once the work is provably
# not happening.
#
# 1. No Procrastinate job in a live state references the bound ingest job.
#    Correlated on args->>'job_id', which every task in this codebase passes —
#    the same correlation `no_live_procrastinate_job` in platform/jobs/sweep.py
#    uses for ingest rows. Inlined rather than imported to avoid a
#    platform/jobs -> platform/refresh dependency in the other direction.
#
#    A NULL ingest_job_id makes the comparison NULL, so the NOT EXISTS holds:
#    the job row was purged by retention, which means its task is long gone.
#
# 2. The bound ingest job is absent, `failed`, or `pending` with no live
#    task. A `running` job is still someone else's business — the ingest
#    stale sweep runs first in the same pass and will fail it out if it is
#    genuinely dead, so skipping it here costs one cycle and never writes a
#    wrong terminal status. `pending` is NOT excluded (fix #1274 review):
#    proof 1 already established no live task exists, and pending-plus-no-
#    task past the cutoff is precisely the create-then-defer death this
#    sweep exists to compensate — a presigned commit interrupted before its
#    defer would otherwise hold the reservation for the bound-job sweep's
#    24-hour timeout, refusing every retry with dataset_busy. A `complete` job cannot coexist with an active run for NATIVE
#    rows, because `record_refresh_success` and the job's completion commit
#    together — when the state does occur (migration 0037's backfilled rows,
#    whose legacy workers finish without calling the finalizer), cancelling
#    would claim abandonment for data that landed, so
#    _LEGACY_COMPLETED_RUN_SQL above records the success instead and this
#    statement keeps its hands off.
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


# fix(#1274 review): the truth-recording counterpart to the abandonment
# cancel below. For a NATIVE run, "bound job complete + run still active" is
# impossible by construction — record_refresh_success and the job's
# completion commit together — which is exactly why _ABANDONED_RUN_SQL
# refuses to touch it. But migration 0037's backfill creates active rows for
# refreshes already executing in PRE-migration workers, and those workers
# finish by marking the job complete without ever calling the new finalizer.
# A complete job IS the proof the swap committed, so the honest terminal
# state is `succeeded`, stamped with the job's own completion time. Native
# runs never match; if a future bug manufactures the state anyway, recording
# success-when-the-data-landed both tells the truth and un-wedges the
# admission index. No cutoff: the job's terminal status is proof enough.
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
    compensation for the one gap Decision 4b accepts, since create-then-
    defer is not atomic and a process that dies between the commit and the
    ``defer`` leaves a run in ``pending`` with no task behind it. Building
    the dispatch outbox that would close that gap properly is scheduler
    infrastructure, and gate 4 says this milestone ships no scheduler.

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
    # feat(#1268): these two statements are the only terminal transitions no
    # worker reports, so without an event here the audit log would show a
    # dispatch and then nothing, forever. Emitted per run rather than as one
    # summary row: the audit log is keyed on a resource, and "seven runs were
    # reconciled" names no dataset anybody can go look at. Both statements
    # normally match zero rows, so the per-row read costs nothing in practice.
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
