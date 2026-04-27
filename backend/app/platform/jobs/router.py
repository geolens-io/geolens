"""Job status API endpoints: poll ingestion job progress and retry."""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user, require_permission
from app.core.dependencies import get_db
from app.processing.ingest.schemas import UploadResponse
from app.processing.ingest.service import queue_ingest_job
from app.platform.jobs.models import IngestJob
from app.platform.jobs.schemas import (
    DbfTruncationCollisionWarning,
    JobStatusResponse,
    ReservedRenameWarning,
    StaleCleanupResponse,
)
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

# Contract: only these two keys may appear in temporal_parse_errors. The
# alias lets ``cast`` narrow dict writes without triggering ruff F821 on
# string literals inside the ``Literal[...]`` expression.
TemporalParseKey = Literal["temporal_start", "temporal_end"]

router = APIRouter(prefix="/jobs", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)

# Jobs running longer than this are considered stale and auto-failed.
JOB_TIMEOUT_SECONDS = 3600  # 60 minutes (accommodates remote service imports)
# Jobs stuck in "pending" longer than this are considered orphaned (never queued).
PENDING_TIMEOUT_SECONDS = 3600  # 60 minutes


async def fail_stale_jobs(db: AsyncSession) -> tuple[int, int]:
    """Mark stale ingest jobs as failed. Returns (pending_failed, running_failed).

    Stale rules:
      - status='pending' and created_at older than PENDING_TIMEOUT_SECONDS (orphan, never queued)
      - status='running' and started_at older than JOB_TIMEOUT_SECONDS (worker crashed mid-job)

    Used by both the admin cleanup endpoint and the background lifespan sweeper.
    """
    now = datetime.now(timezone.utc)
    pending_cutoff = now - timedelta(seconds=PENDING_TIMEOUT_SECONDS)

    result = await db.execute(
        select(IngestJob).where(
            IngestJob.status == "pending",
            IngestJob.created_at < pending_cutoff,
        )
    )
    pending_jobs = list(result.scalars())
    for job in pending_jobs:
        job.status = "failed"
        job.error_message = "Stale: pending for over 1 hour (never queued)"
        job.completed_at = now

    running_cutoff = now - timedelta(seconds=JOB_TIMEOUT_SECONDS)
    result = await db.execute(
        select(IngestJob).where(
            IngestJob.status == "running",
            IngestJob.started_at < running_cutoff,
        )
    )
    running_jobs = list(result.scalars())
    for job in running_jobs:
        job.status = "failed"
        job.error_message = (
            f"Stale: running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
        )
        job.completed_at = now

    await db.commit()
    return len(pending_jobs), len(running_jobs)


@router.post("/cleanup/stale/", response_model=StaleCleanupResponse)
async def cleanup_stale_jobs(
    user: Identity = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> StaleCleanupResponse:
    """Fail all stale jobs: pending >1h or running >1h.

    **Ops-only.** Not used by the GeoLens UI — invoke from `curl`/`gh api`/cron
    when you need to force-clean orphaned jobs after a worker outage.
    Equivalent logic runs automatically every 5 minutes via the lifespan
    sweeper, so this endpoint is only needed if you need cleanup faster than
    that interval.
    """
    pending_failed, running_failed = await fail_stale_jobs(db)
    return StaleCleanupResponse(
        pending_failed=pending_failed,
        running_failed=running_failed,
        total_cleaned=pending_failed + running_failed,
    )


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse:
    """Get the status of an ingestion job.

    Only the job creator or an admin can view job status.
    """
    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Authorization: only creator or admin
    if job.created_by != user.id:
        from app.modules.catalog.authorization import get_user_roles

        user_roles = await get_user_roles(db, user)
        if "admin" not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this job",
            )

    now = datetime.now(timezone.utc)

    # Auto-fail jobs stuck in "running" beyond the timeout
    if job.status == "running" and job.started_at is not None:
        elapsed = (now - job.started_at).total_seconds()
        if elapsed > JOB_TIMEOUT_SECONDS:
            job.status = "failed"
            job.error_message = f"Timed out after {int(elapsed)}s"
            job.completed_at = now
            await db.commit()

    # Auto-fail jobs stuck in "pending" beyond the timeout (orphaned / never queued)
    if job.status == "pending" and job.created_at is not None:
        elapsed = (now - job.created_at).total_seconds()
        if elapsed > PENDING_TIMEOUT_SECONDS:
            job.status = "failed"
            job.error_message = (
                f"Stale: pending for {int(elapsed)}s without being processed"
            )
            job.completed_at = now
            await db.commit()

    return _job_to_status_response(job)


def _job_to_status_response(job: IngestJob) -> JobStatusResponse:
    """Extract warnings + structured metadata from ``user_metadata`` (S3/TYPE-2).

    Shared by ``get_job_status`` (lookup by job_id) and
    ``get_job_status_by_dataset`` (lookup by dataset_id) so the warning-parse
    contract lives in a single place.

    Warnings are validated through the ``IngestJobWarning`` discriminated
    union; any malformed entry (unknown ``kind``, missing fields) is logged
    and dropped so a stale-producer bug cannot break the whole endpoint.
    """
    import structlog
    from pydantic import ValidationError

    logger = structlog.get_logger()

    warning_message: str | None = None
    warnings: list[ReservedRenameWarning | DbfTruncationCollisionWarning] = []
    archive_failed = False
    temporal_parse_errors: dict[TemporalParseKey, str] = {}
    if job.user_metadata and isinstance(job.user_metadata, dict):
        warning_message = job.user_metadata.get("collision_warning")
        raw_warnings = job.user_metadata.get("warnings")
        if isinstance(raw_warnings, list):
            for raw in raw_warnings:
                if not isinstance(raw, dict):
                    continue
                kind = raw.get("kind")
                try:
                    if kind == "reserved_rename":
                        warnings.append(ReservedRenameWarning.model_validate(raw))
                    elif kind == "dbf_truncation_collision":
                        warnings.append(
                            DbfTruncationCollisionWarning.model_validate(raw)
                        )
                    else:
                        logger.warning(
                            "Dropping ingest warning with unknown kind",
                            job_id=str(job.id),
                            kind=kind,
                        )
                except ValidationError as exc:
                    logger.warning(
                        "Dropping malformed ingest warning",
                        job_id=str(job.id),
                        kind=kind,
                        error=str(exc)[:500],
                    )
        archive_failed = bool(job.user_metadata.get("archive_failed"))
        raw_temporal = job.user_metadata.get("temporal_parse_errors")
        if isinstance(raw_temporal, dict):
            # Narrow to the contract keys — drop anything unknown so the
            # Pydantic ``Literal`` validation cannot reject the whole
            # response on a stale producer. ``cast`` makes the narrowing
            # explicit to mypy so no ``type: ignore`` is needed.
            for k, v in raw_temporal.items():
                key = str(k)
                if key in ("temporal_start", "temporal_end"):
                    temporal_parse_errors[cast(TemporalParseKey, key)] = str(v)

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        dataset_id=job.dataset_id,
        source_filename=job.source_filename,
        error_message=job.error_message,
        warning_message=warning_message,
        warnings=warnings,
        archive_failed=archive_failed,
        temporal_parse_errors=temporal_parse_errors,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/by-dataset/{dataset_id}", response_model=JobStatusResponse)
async def get_job_status_by_dataset(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse:
    """Look up the most recent ingest job for a dataset.

    Used by the dataset detail page to surface ingest warnings permanently
    (S3 completion) — the job is the source of truth for
    ``reserved_rename`` / ``dbf_truncation_collision`` / ``archive_failed``
    / ``temporal_parse_errors`` metadata.

    Returns the most recently created completed job for the dataset, or 404
    if none exists (e.g. the dataset was registered from an existing table,
    not ingested).
    """
    # Visibility check: reuse the dataset detail permission so only users
    # who can see the dataset can see the job warnings. Avoid leaking the
    # existence of jobs via 403 vs 404 divergence.
    from app.modules.catalog.authorization import (
        apply_visibility_filter,
        get_user_roles,
    )
    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        DatasetGrant,
        Record,
    )

    user_roles = await get_user_roles(db, user)
    dataset_stmt = (
        select(Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    dataset_stmt = apply_visibility_filter(
        dataset_stmt, user, user_roles, Record, DatasetGrant
    )
    dataset_result = await db.execute(dataset_stmt)
    if dataset_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found or no ingest job associated",
        )

    job_result = await db.execute(
        select(IngestJob)
        .where(IngestJob.dataset_id == dataset_id)
        .order_by(IngestJob.created_at.desc())
        .limit(1)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ingest job found for this dataset",
        )

    return _job_to_status_response(job)


@router.post(
    "/{job_id}/retry",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_job(
    job_id: uuid.UUID,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Retry a failed ingestion job by re-queuing.

    Only callable on jobs with status 'failed'. The staging file must
    still exist (preserved on failure for retry).
    """
    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Authorization: only creator or admin
    if job.created_by != user.id:
        from app.modules.catalog.authorization import get_user_roles

        user_roles = await get_user_roles(db, user)
        if "admin" not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to retry this job",
            )

    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed jobs can be retried",
        )

    # Validate staging file exists for file jobs before touching DB state.
    is_service_job = bool(job.source_url and not job.file_path)
    if not is_service_job:
        if not job.file_path or not Path(job.file_path).exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Staging file no longer available. Please re-upload.",
            )

    # Reset the job to pending and commit before re-queueing so the
    # orphan guard in queue_ingest_job can flip it back to failed if
    # the queue is down (RESILIENCE-2).
    job.status = "pending"
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    job.dataset_id = None
    await db.commit()

    await queue_ingest_job(job, str(job.created_by), db=db)

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="Job re-queued for ingestion",
    )
