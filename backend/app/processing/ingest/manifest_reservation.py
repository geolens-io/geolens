"""Whether a manifest key is busy or held, and the reservation that claims it.

The key lock, the in-flight and held reads, the staleness rule and the fenced
stage exits answer one question, so they live together rather than in step.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs import ledger
from app.platform.jobs.models import (
    ACTIVE_STATUSES,
    MANIFEST_FINGERPRINT_METADATA_KEY,
    MANIFEST_STAGE_METADATA_KEY,
    IngestJob,
)
from app.platform.jobs.sweep import settle_stale_jobs
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest.manifest_schemas import (
    ManifestApplyEntryResult,
    ManifestDataset,
)

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
            IngestJob.status.in_(ACTIVE_STATUSES),
            IngestJob.user_metadata["manifest_key"].astext == key,
        )
        .order_by(desc(IngestJob.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def held_entry(
    db: AsyncSession,
    entry: ManifestDataset,
    fingerprint: str,
    completed_job: IngestJob,
    dataset: object,
) -> ManifestApplyEntryResult | None:
    """The ``blocked`` result for an entry whose last apply is held for review.

    None unless applying the unchanged entry again would only repeat the hold:
    the key's newest held job must carry ``fingerprint``, postdate the last
    completed import, and still be acceptable: its acceptance unspent, the
    dataset's data at the version it was held against, and the copy apply
    staged still on disk. A raw seed is the entry's own source, so applying
    again could not restage it.
    """
    row = (
        await db.execute(
            select(IngestJob, DatasetRefreshRun)
            .join(DatasetRefreshRun, DatasetRefreshRun.ingest_job_id == IngestJob.id)
            .where(
                IngestJob.user_metadata["manifest_key"].astext == entry.key,
                DatasetRefreshRun.status == "blocked",
            )
            .order_by(desc(IngestJob.created_at))
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    job, run = row
    verification = run.verification or {}
    if (
        (job.user_metadata or {}).get(MANIFEST_FINGERPRINT_METADATA_KEY) != fingerprint
        or job.dataset_id != getattr(dataset, "id", None)
        or job.created_at <= completed_job.created_at
        or "acceptance_consumed_by_run_id" in verification
        or verification.get("live_version") != getattr(dataset, "current_version", None)
        or not job.file_path
    ):
        return None
    staged = Path(job.file_path)
    if staged.name.startswith(f"{job.id}_") and not await asyncio.to_thread(
        staged.exists
    ):
        return None
    return ManifestApplyEntryResult(
        dataset_key=entry.key,
        action="blocked",
        job_id=job.id,
        dataset_id=run.dataset_id,
        run_id=run.id,
        review_reasons=[str(r) for r in verification.get("review_reasons") or ()],
        message=(
            "Manifest dataset entry is unchanged since its last apply, which "
            f"is blocked for review, so nothing was queued. Accept run {run.id} "
            "to publish it, or change the entry."
        ),
    )


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
