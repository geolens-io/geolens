"""Worker lease helpers for long-running ingest jobs."""

import asyncio
import re
import uuid
from contextlib import suppress
from datetime import datetime, timezone

import structlog
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import sqlstate
from app.platform.jobs.models import IngestJob

HEARTBEAT_INTERVAL_SECONDS = 30.0

# fix(#691): lease shared by the materialize cap (router_analysis.py) and the
# job-status auto-fail (platform/jobs/router.py), so API and poller agree. 10x
# the renewal interval so one missed renewal can't admit a second concurrent CTAS.
ANALYSIS_MATERIALIZE_LEASE_SECONDS = 300.0


class StaleIngestAttempt(RuntimeError):
    """Raised when a worker no longer owns the job attempt it received."""


# fix(#1858): shared by the code that MAKES these names and the code that
# RECOGNISES them. Narrow: `parcels_staging` is a legitimate user title.
# POSIX syntax so Postgres `~` and Python `re` agree (test_staging_table_names_1858.py).
ATTEMPT_STAGING_NAME_PATTERN = r"_staging_[0-9a-f]{32}$"

_ATTEMPT_STAGING_NAME_RE = re.compile(ATTEMPT_STAGING_NAME_PATTERN)


def attempt_scoped_staging_table(base_table: str, attempt_id: uuid.UUID) -> str:
    """Return a PostgreSQL-safe physical staging name owned by one attempt."""
    suffix = f"_staging_{attempt_id.hex}"
    return f"{base_table[: 63 - len(suffix)]}{suffix}"


def is_attempt_scoped_staging_table(table_name: str) -> bool:
    """Whether *table_name* is a physical staging table owned by an attempt.

    fix(#1858): a survivor of a SIGKILLed/OOM-killed worker (created in an
    import, dropped in its ``finally``; nothing else reaps it). Left
    unrecognised, table discovery would let bulk registration bind a
    permanent dataset to a table the next attempt can rename away.
    """
    return _ATTEMPT_STAGING_NAME_RE.search(table_name) is not None


async def resolve_ingest_job_attempt(
    job_id: uuid.UUID,
    attempt_id: str | uuid.UUID | None,
) -> uuid.UUID | None:
    """Resolve a delivery token, adopting only a pre-migration queued job.

    Deployments can already have tokenless Procrastinate deliveries when the
    attempt-fencing migration lands. Existing rows remain NULL so exactly one
    such delivery may atomically attach a token while the job is still pending.
    New and retried jobs already have a token and therefore cannot be adopted by
    a tokenless delivery.
    """
    if attempt_id is not None:
        return (
            attempt_id if isinstance(attempt_id, uuid.UUID) else uuid.UUID(attempt_id)
        )

    from app.core.db import async_session

    adopted_attempt = uuid.uuid4()
    async with async_session() as session:
        result = await session.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job_id,
                IngestJob.attempt_id.is_(None),
                IngestJob.status == "pending",
            )
            .values(attempt_id=adopted_attempt)
        )
        await session.commit()
        if result.rowcount:  # type: ignore[attr-defined]
            return adopted_attempt
    return None


async def claim_ingest_job_attempt(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
) -> bool:
    """Atomically move the matching pending attempt to running."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job_id,
            IngestJob.attempt_id == attempt_id,
            IngestJob.status == "pending",
        )
        .values(status="running", started_at=now, heartbeat_at=now)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


# fix(#1950): the budget an attempt-fenced failure write spends on its own
# ingest_jobs row. A long holder is a LATER attempt's phase bracket, whose id
# the fence no longer matches, so no wait starts and a wait past this is stuck.
JOB_ERROR_WRITE_TIMEOUT_MS = 10_000


# fix(#1950): the two SQLSTATEs the budget itself produces — statement_timeout
# and lock_timeout. Any other DBAPIError out of the failure write is a database
# problem, reported under the sibling event rather than as an expiry.
ERROR_WRITE_EXPIRY_CODES = ("57014", "55P03")


def log_job_error_write_failure(exc: BaseException, *, job_id: str, task: str) -> None:
    """Record a failed terminal job write as its own event.

    The caller must swallow *exc* and re-raise whatever it was already handling:
    this write is secondary, and letting it out replaces the cause the operator
    needs with a lock timeout.
    """
    code = sqlstate(exc)
    structlog.get_logger().warning(
        "job_error_write_timeout"
        if code in ERROR_WRITE_EXPIRY_CODES
        else "job_error_write_failed",
        job_id=job_id,
        task=task,
        sqlstate=code,
        budget_ms=JOB_ERROR_WRITE_TIMEOUT_MS,
    )


async def arm_job_error_write_budget(session: AsyncSession) -> None:
    """Bound this transaction's wait on the job row at the error-write budget.

    Issue it on the transaction that carries the failure UPDATE and after any
    rollback on that session: ``SET LOCAL`` dies with the transaction, so an
    arm placed before a rollback or a commit is gone by the next statement.
    """
    await session.execute(
        text(f"SET LOCAL lock_timeout = {JOB_ERROR_WRITE_TIMEOUT_MS}")
    )
    await session.execute(
        text(f"SET LOCAL statement_timeout = {JOB_ERROR_WRITE_TIMEOUT_MS}")
    )


async def update_ingest_job_for_attempt(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    values: dict[str, object],
    expected_status: str = "running",
) -> bool:
    """Apply a job mutation only while the caller owns the active attempt."""
    result = await session.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job_id,
            IngestJob.attempt_id == attempt_id,
            IngestJob.status == expected_status,
        )
        .values(**values)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def write_job_failure_for_attempt(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    values: dict[str, object],
    task_name: str,
) -> bool | None:
    """Commit a fenced terminal job write under the error-write budget.

    Returns whether the fence matched, or ``None`` when the write did not
    happen at all and the transaction was ended: the budget expired or the
    connection went. Never raises, because every caller reaches it from a
    failure path where a raise would replace the cause with a lock timeout.

    fix(#1957): ``None`` is not a fence miss. A caller that treats it as one
    drops cleanup that belongs to an attempt still owning the job row. On
    ``None`` the row stays ``running`` for the stale sweep to settle.

    Issue it AFTER any rollback on *session*: ``SET LOCAL`` dies with the
    transaction, so a budget armed before one is gone by the next statement.
    """
    from sqlalchemy.exc import SQLAlchemyError

    try:
        # The connection first, on its own deadline: `SET LOCAL` cannot bound a
        # wait for the POOL, which on an exhausted pool is `db_pool_timeout`
        # (30s) before any statement runs. Nothing is in flight yet, so this is
        # the one point in the write that is safe to cancel.
        await asyncio.wait_for(
            session.connection(), timeout=JOB_ERROR_WRITE_TIMEOUT_MS / 1000
        )
        await arm_job_error_write_budget(session)
        fenced = await update_ingest_job_for_attempt(
            session, job_id, attempt_id, values=values
        )
        await session.commit()
        return fenced
    except (SQLAlchemyError, TimeoutError) as write_failure:
        # Wider than DBAPIError: a pool timeout is a SQLAlchemyError, and
        # letting one out would replace the failure the caller is handling.
        with suppress(Exception):  # broad: best-effort, the caller keeps its cause
            await session.rollback()
        log_job_error_write_failure(write_failure, job_id=str(job_id), task=task_name)
        return None


async def require_ingest_job_update(
    session: AsyncSession,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    values: dict[str, object],
    expected_status: str = "running",
) -> None:
    """Apply a fenced mutation or abort the stale worker's transaction."""
    if not await update_ingest_job_for_attempt(
        session,
        job_id,
        attempt_id,
        values=values,
        expected_status=expected_status,
    ):
        raise StaleIngestAttempt(
            f"Ingest attempt {attempt_id} no longer owns job {job_id}"
        )


async def resolve_ingest_attempt_or_skip(
    job_id: str,
    attempt_id: str | uuid.UUID | None,
    *,
    task_label: str = "ingest",
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Parse the job id and resolve its delivery token, or signal a skip.

    fix(#836): returns ``(job_uuid, attempt_uuid)``, or ``None`` when a
    tokenless legacy delivery could not adopt the pending job — the caller
    must return without touching the row.
    """
    job_uuid = uuid.UUID(job_id)
    attempt_uuid = await resolve_ingest_job_attempt(job_uuid, attempt_id)
    if attempt_uuid is None:
        structlog.get_logger().warning(
            f"Tokenless {task_label} delivery could not adopt pending legacy job",
            job_id=job_id,
        )
        return None
    return job_uuid, attempt_uuid


async def claim_job_attempt_and_start_heartbeat(
    session: AsyncSession,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    job: IngestJob | None = None,
    current_step: str | None = None,
) -> "asyncio.Task[None] | None":
    """Claim the pending attempt, commit, and start the lease heartbeat.

    fix(#836): rolls back and returns ``None`` when the caller no longer owns
    the attempt. When ``job``/``current_step`` are given, stamps the first
    progress step in the same commit so polling sees a fresh signal on its
    first poll after pickup (REMED-02 / ingest-audit P2-07).
    """
    if not await claim_ingest_job_attempt(session, job_uuid, attempt_uuid):
        await session.rollback()
        return None
    if job is not None and current_step is not None:
        job.current_step = current_step
        job.progress = 0.0
    await session.commit()
    return asyncio.create_task(maintain_ingest_job_heartbeat(job_uuid, attempt_uuid))


async def renew_ingest_job_heartbeat(job_id: uuid.UUID, attempt_id: uuid.UUID) -> bool:
    """Renew a running job's lease and return whether a row was updated."""
    from app.core.db import async_session

    async with async_session() as session:
        result = await session.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job_id,
                IngestJob.attempt_id == attempt_id,
                IngestJob.status == "running",
            )
            .values(heartbeat_at=datetime.now(timezone.utc))
        )
        await session.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]


async def maintain_ingest_job_heartbeat(
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """Renew a job lease until the task ends or the row leaves `running`."""
    logger = structlog.get_logger()
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            if not await renew_ingest_job_heartbeat(job_id, attempt_id):
                return
        except asyncio.CancelledError:
            raise
        except Exception:  # broad: heartbeat lease renewal is best-effort
            # Must not mask the ingest result; the next interval retries.
            logger.warning(
                "ingest_job_heartbeat_failed",
                job_id=str(job_id),
                attempt_id=str(attempt_id),
                exc_info=True,
            )


async def renew_vrt_generation_heartbeat(generation_id: uuid.UUID) -> bool:
    from app.core.db import async_session
    from app.processing.raster.models import VrtGeneration

    async with async_session() as session:
        result = await session.execute(
            update(VrtGeneration)
            .where(
                VrtGeneration.id == generation_id,
                VrtGeneration.status == "running",
            )
            .values(heartbeat_at=datetime.now(timezone.utc))
        )
        await session.commit()
        return bool(result.rowcount)  # type: ignore[attr-defined]


async def maintain_vrt_generation_heartbeat(
    generation_id: uuid.UUID,
    *,
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """Renew a VRT generation lease until completion or cancellation."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            if not await renew_vrt_generation_heartbeat(generation_id):
                return
        except asyncio.CancelledError:
            raise
        except Exception:  # broad: heartbeat lease renewal is best-effort
            structlog.get_logger().warning(
                "vrt_generation_heartbeat_failed",
                generation_id=str(generation_id),
                exc_info=True,
            )


async def stop_ingest_job_heartbeat(task: asyncio.Task[None] | None) -> None:
    """Cancel and await a best-effort heartbeat task."""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
