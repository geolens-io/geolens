"""Whether a manifest key is busy, and the reservation that claims it.

fix(#1814): the key lock, the in-flight read, the staleness rule and the fenced
stage exits answer one question, so they live together rather than in step.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs import ledger
from app.platform.jobs.models import MANIFEST_STAGE_METADATA_KEY, IngestJob
from app.platform.jobs.sweep import settle_stale_jobs

log = structlog.get_logger()

MANIFEST_STAGE_DOWNLOADING = "downloading"

# fix(#1814): names no id. The row this attempt owned is terminal, and the row
# that replaced it belongs to a different request.
RESERVATION_LOST_MESSAGE = (
    "Manifest dataset apply lost its reservation while the source was being "
    "staged; re-apply the manifest."
)


def downloading_stage_marker() -> dict[str, str]:
    """The metadata a reservation carries between its insert and its staging."""
    return {MANIFEST_STAGE_METADATA_KEY: MANIFEST_STAGE_DOWNLOADING}


async def lock_manifest_key(db: AsyncSession, key: str) -> None:
    """Serialize check-and-reserve for one manifest key.

    fix(#1814): transaction-scoped and blocking. End the transaction before any
    network I/O and before the next entry, or two manifests deadlock on two keys.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"manifest_apply:{key}"},
    )


async def latest_in_flight_manifest_job(db: AsyncSession, key: str) -> IngestJob | None:
    """The newest queued, running, or reserved job for ``key``, if any."""
    result = await db.execute(
        select(IngestJob)
        .where(
            IngestJob.status.in_(["pending", "running"]),
            IngestJob.user_metadata["manifest_key"].astext == key,
        )
        .order_by(desc(IngestJob.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _without_stage_marker():
    """The row's metadata with the downloading marker removed, as SQL.

    Written as a JSONB key removal rather than from the instance, because both
    callers may hold an expired one (fix(#1814)).
    """
    return IngestJob.user_metadata.op("-", return_type=JSONB)(
        MANIFEST_STAGE_METADATA_KEY
    )


def _still_downloading():
    """Whether the reservation is still downloading its source, as SQL."""
    return (
        IngestJob.user_metadata[MANIFEST_STAGE_METADATA_KEY].astext
        == MANIFEST_STAGE_DOWNLOADING
    )


async def expire_stale_manifest_reservations(
    db: AsyncSession, key: str, *, now: datetime | None = None
) -> int:
    """Settle reservations for ``key`` whose apply never came back. Returns the count.

    The stale-job pass, limited to this key's downloading reservations, so the
    expiry and the running sweep cannot disagree about which rows are live or
    what a settled one says. Does not commit.

    fix(#1814): settling rather than ignoring is what lets the staging bind's
    fence catch a slow attempt whose reservation was replaced.
    """
    reservations = (
        await db.execute(
            select(IngestJob.id).where(
                IngestJob.status == "running",
                IngestJob.user_metadata["manifest_key"].astext == key,
                _still_downloading(),
            )
        )
    ).scalars()
    job_ids = list(reservations)
    if not job_ids:
        return 0
    outcome = await settle_stale_jobs(
        db, now or datetime.now(timezone.utc), job_ids=job_ids
    )
    return outcome.running_failed


async def bind_reservation_to_staged_source(
    db: AsyncSession, job: IngestJob, *, file_path: str, now: datetime | None = None
) -> bool:
    """Fenced downloading -> staged transition. False means the row is not ours.

    fix(#1814): ``staged_at`` is stamped here, so the pending sweep measures
    from staging rather than from a creation that predates the download.
    """
    now = now or datetime.now(timezone.utc)
    if not await ledger.stage(
        db,
        job.id,
        job.attempt_id,
        values={
            "file_path": file_path,
            "user_metadata": _without_stage_marker().op("||", return_type=JSONB)(
                func.jsonb_build_object("staged_at", now.isoformat())
            ),
        },
        require=(_still_downloading(),),
        mirror=job,
    ):
        # fix(#2017): distinguishes a sweep reaping the row from a cancel,
        # for the same job the CAS just missed on.
        observed = (
            await db.execute(select(IngestJob.status).where(IngestJob.id == job.id))
        ).scalar_one_or_none()
        log.warning(
            "Manifest reservation bind missed its CAS",
            job_id=str(job.id),
            observed_status=observed,
        )
        return False
    return True


async def release_manifest_reservation(
    db: AsyncSession, job: IngestJob, message: str
) -> bool:
    """Fenced running -> failed for a reservation that never staged its source.

    The shared settlement fences on ``pending``, so the lease needs its own
    exit. The ledger stores ``message`` redacted, since the manifest door
    composes it from an exception.
    """
    return await ledger.fail(
        db,
        job.id,
        job.attempt_id,
        reason=message,
        values={"user_metadata": _without_stage_marker()},
        require=(_still_downloading(),),
        mirror=job,
    )


async def staged_source_is_referenced(
    db: AsyncSession, job_id: uuid.UUID, *, file_path: str
) -> bool:
    """Does the committed row point at these staged bytes?

    fix(#1814): raises rather than guessing. The caller's settlement wrapper
    resets and retries, and keeps the bytes if neither attempt can read.
    """
    row = (
        await db.execute(select(IngestJob.file_path).where(IngestJob.id == job_id))
    ).one_or_none()
    return row is not None and row.file_path == file_path
