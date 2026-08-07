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

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.url_redaction import redact_url_credentials
from app.platform.refresh.models import DatasetRefreshRun

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

    ``started_at`` and ``created_at`` are stamped in Python rather than left to
    ``server_default``. A server default leaves the attribute expired after
    flush, and the next read lazy-loads — which under AnyIO raises
    ``MissingGreenlet`` rather than returning a value.
    """
    if origin_kind not in RUN_ORIGIN_KINDS:
        raise ValueError(f"unknown origin_kind {origin_kind!r}")
    if trigger not in RUN_TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}")

    now = datetime.now(timezone.utc)
    run = DatasetRefreshRun(
        dataset_id=dataset_id,
        ingest_job_id=ingest_job_id,
        origin_kind=origin_kind,
        trigger=trigger,
        status="pending",
        triggered_by=triggered_by,
        started_at=now,
        created_at=now,
        feature_count_before=feature_count_before,
    )
    session.add(run)
    await session.flush()
    return run


async def claim_run_for_job(
    session: AsyncSession, ingest_job_id: uuid.UUID
) -> uuid.UUID | None:
    """Move this job's run to ``running``; return its id, or None if there is none.

    ``started_at`` is deliberately left at dispatch time, so queue wait is
    measurable as the gap between it and the row's update.

    Returning None is normal, not an error: a re-upload dispatched before this
    table existed has no run row, and the worker must still complete.
    """
    result = await session.execute(
        update(DatasetRefreshRun)
        .where(
            DatasetRefreshRun.ingest_job_id == ingest_job_id,
            DatasetRefreshRun.status == "pending",
        )
        .values(status="running")
        .returning(DatasetRefreshRun.id)
    )
    return result.scalar_one_or_none()


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
    """
    now = datetime.now(timezone.utc)
    project_refresh_success(
        dataset,
        schema_diff=schema_diff,
        contacted_origin=contacted_origin,
        now=now,
    )
    result = await session.execute(
        update(DatasetRefreshRun)
        .where(
            DatasetRefreshRun.ingest_job_id == ingest_job_id,
            DatasetRefreshRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .values(
            status="succeeded",
            finished_at=now,
            dataset_version_id=dataset_version_id,
            feature_count_after=feature_count_after,
            schema_diff=schema_diff,
        )
        .returning(DatasetRefreshRun.id)
    )
    return result.scalar_one_or_none()


async def record_refresh_failure(
    session: AsyncSession,
    *,
    ingest_job_id: uuid.UUID,
    error_code: str,
    error_message: str,
    contacted_origin: bool,
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
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(DatasetRefreshRun)
        .where(
            DatasetRefreshRun.ingest_job_id == ingest_job_id,
            DatasetRefreshRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .values(
            status="failed",
            finished_at=now,
            error_code=error_code[:64],
            error_message=redact_run_error(error_message),
        )
        .returning(DatasetRefreshRun.id, DatasetRefreshRun.dataset_id)
    )
    row = result.one_or_none()
    if row is None:
        return None
    if contacted_origin:
        await session.execute(
            text(
                "UPDATE catalog.datasets SET last_checked_at = :now "
                "WHERE id = :dataset_id"
            ),
            {"now": now, "dataset_id": row.dataset_id},
        )
    return row.id


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


# The dataset EXISTS clause looks redundant against a NOT NULL FK, and is
# not. `dataset_refresh_runs` carries no tenant_id and no RLS policy, like
# every other per-dataset child table, so under FORCE RLS this UPDATE would
# otherwise see EVERY tenant's rows on EVERY tenant's sweep pass — while the
# `ingest_jobs` sub-query beside it, on a table that DOES have a policy, saw
# only the current tenant's jobs and so read another tenant's live job as
# absent. Joining through `catalog.datasets` puts the whole predicate inside
# one visibility scope: the sweep can only reach runs whose dataset the
# current session can see. In single-tenant mode RLS is disabled and the
# clause is the no-op it appears to be.
#
# The two proofs the sweep needs before it may write `cancelled`. ADR-002
# Decision 4d is explicit that this status is a bookkeeping correction and
# never a stop signal, so it may only be written once the work is provably
# not happening.
#
# 1. No Procrastinate job in a live state references the bound ingest job.
#    Correlated on args->>'job_id', which every task in this codebase passes —
#    the same correlation `no_live_procrastinate_job` in platform/jobs/router.py
#    uses for ingest rows. Inlined rather than imported because that helper
#    lives in a router module, and importing an API-edge module executes route
#    registration as a side effect.
#
#    A NULL ingest_job_id makes the comparison NULL, so the NOT EXISTS holds:
#    the job row was purged by retention, which means its task is long gone.
#
# 2. The bound ingest job is absent or already `failed`. A `pending` or
#    `running` job is still someone else's business — the ingest stale sweep
#    runs first in the same pass and will fail it out if it is genuinely dead,
#    so skipping it here costs one cycle and never writes a wrong terminal
#    status. A `complete` job cannot coexist with an active run, because
#    `record_refresh_success` and the job's completion commit together; if it
#    somehow did, cancelling would claim abandonment for data that landed, so
#    the row is deliberately left visible instead.
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
            AND j.status IN ('pending', 'running', 'complete')
      )
    RETURNING r.id
    """
)


async def sweep_abandoned_refresh_runs(
    session: AsyncSession, now: datetime | None = None
) -> int:
    """Cancel runs whose task is proven gone. Returns the number cancelled.

    This is the compensation for the one gap Decision 4b accepts: create-then-
    defer is not atomic, so a process that dies between the commit and the
    ``defer`` leaves a run in ``pending`` with no task behind it. Building the
    dispatch outbox that would close the gap properly is scheduler
    infrastructure, and gate 4 says this milestone ships no scheduler.
    """
    resolved_now = now or datetime.now(timezone.utc)
    result = await session.execute(
        _ABANDONED_RUN_SQL,
        {
            "now": resolved_now,
            "cutoff": resolved_now - timedelta(seconds=ABANDONED_RUN_CUTOFF_SECONDS),
            "error_code": ABANDONED_ERROR_CODE,
            "error_message": ABANDONED_ERROR_MESSAGE,
        },
    )
    return len(list(result.scalars()))


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
