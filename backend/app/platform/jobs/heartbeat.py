"""Worker lease helpers for long-running ingest jobs."""

import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob

HEARTBEAT_INTERVAL_SECONDS = 30.0


class StaleIngestAttempt(RuntimeError):
    """Raised when a worker no longer owns the job attempt it received."""


def attempt_scoped_staging_table(base_table: str, attempt_id: uuid.UUID) -> str:
    """Return a PostgreSQL-safe physical staging name owned by one attempt."""
    suffix = f"_staging_{attempt_id.hex}"
    return f"{base_table[: 63 - len(suffix)]}{suffix}"


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
        except Exception:
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
        except Exception:
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
