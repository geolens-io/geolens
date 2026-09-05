"""Worker lease helpers for long-running ingest jobs."""

import asyncio
import re
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob

HEARTBEAT_INTERVAL_SECONDS = 30.0

# fix(#691): lease window for analysis materialize jobs. Governs BOTH the
# per-user materialize cap (router_analysis.py) and the per-job status read's
# auto-fail (platform/jobs/router.py), so the API and the polling client
# always agree on when a dead worker's slot is released. 10x the renewal
# interval: renewal is best-effort (maintain_ingest_job_heartbeat retries
# through transient DB errors), so a short multiple would declare a live but
# briefly-degraded worker dead and admit a second concurrent CTAS — ten
# consecutive missed renewals means the worker is gone or the DB is in a
# state where one more failed CTAS is not the problem. Still releases the
# slot in five minutes instead of the 60-minute JOB_TIMEOUT_SECONDS backstop.
# Module-level constant on purpose: promoting it to Settings is #696's scope.
ANALYSIS_MATERIALIZE_LEASE_SECONDS = 300.0


class StaleIngestAttempt(RuntimeError):
    """Raised when a worker no longer owns the job attempt it received."""


# fix(#1858): the shape `attempt_scoped_staging_table` produces, written once
# so the code that RECOGNISES one of these names cannot drift from the code
# that makes one. Deliberately narrow: `_staging_` followed by exactly a
# `uuid4().hex`, anchored at the end. `generate_table_name` slugifies a
# user-chosen title, so `parcels_staging`, `parcels_old` and `parcels_staging_
# area` are all names a person can legitimately ask for, and a predicate wide
# enough to cover them would refuse their registration. The spelling is a
# POSIX regular expression because PostgreSQL's `~` and Python's `re` agree on
# exactly this subset, which is what lets one string serve the SQL half of the
# rule and the Python half (`backend/tests/test_staging_table_names_1858.py`
# checks the two engines against each other).
ATTEMPT_STAGING_NAME_PATTERN = r"_staging_[0-9a-f]{32}$"

_ATTEMPT_STAGING_NAME_RE = re.compile(ATTEMPT_STAGING_NAME_PATTERN)


def attempt_scoped_staging_table(base_table: str, attempt_id: uuid.UUID) -> str:
    """Return a PostgreSQL-safe physical staging name owned by one attempt."""
    suffix = f"_staging_{attempt_id.hex}"
    return f"{base_table[: 63 - len(suffix)]}{suffix}"


def is_attempt_scoped_staging_table(table_name: str) -> bool:
    """Whether *table_name* is a physical staging table owned by an attempt.

    fix(#1858): these are created inside an import and dropped in its
    ``finally``, so one only survives a worker that was SIGKILLed or
    OOM-killed between the two. Nothing reaps the survivor -- the sweeps in
    ``platform/jobs/sweep.py`` cover storage objects, analysis outputs and VRT
    generations, and none of them looks at PostGIS tables -- so table
    discovery listed it and bulk registration bound a permanent dataset to a
    table the next attempt is entitled to ``ALTER ... RENAME`` away.
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

    fix(#836): the parse/resolve/warn prologue was pasted at seven ingest task
    sites. Returns ``(job_uuid, attempt_uuid)``, or ``None`` when a tokenless
    legacy delivery could not adopt the pending job — the caller must return
    without touching the row. ``task_label`` preserves each task family's
    historical log message ("ingest" / "raster" / "reupload" / "vrt").
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

    fix(#836): the claim/stamp/commit/heartbeat prologue was pasted at seven
    ingest task sites. Rolls back and returns ``None`` when the caller no
    longer owns the attempt (another actor moved the row). When ``job`` and
    ``current_step`` are given, stamps the first progress step in the same
    commit so the polling UI sees a fresh signal on its first poll after
    pickup (REMED-02 / ingest-audit P2-07).
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
            # A transient heartbeat write must not mask the ingest result. The
            # next interval gets another chance before the one-hour lease ends.
            logger.warning(
                "ingest_job_heartbeat_failed",
                job_id=str(job_id),
                attempt_id=str(attempt_id),
                exc_info=True,
            )


async def renew_vrt_generation_heartbeat(generation_id: uuid.UUID) -> bool:
    """Renew a running managed-VRT generation lease."""
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
