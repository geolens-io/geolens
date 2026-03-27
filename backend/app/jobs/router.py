"""Job status API endpoints: poll ingestion job progress and retry."""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user, require_permission
from app.auth.models import Role, User, UserRole
from app.dependencies import get_db
from app.ingest.schemas import UploadResponse
from app.ingest.tasks import ingest_file, ingest_service
from app.jobs.models import IngestJob
from app.jobs.schemas import JobStatusResponse

router = APIRouter(prefix="/jobs", tags=["Admin"])

# Jobs running longer than this are considered stale and auto-failed.
JOB_TIMEOUT_SECONDS = 3600  # 60 minutes (accommodates remote service imports)
# Jobs stuck in "pending" longer than this are considered orphaned (never queued).
PENDING_TIMEOUT_SECONDS = 3600  # 60 minutes


@router.post("/cleanup/stale/")
async def cleanup_stale_jobs(
    user: User = Depends(require_permission("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Fail all stale jobs: pending >1h or running >1h.

    Admin-only. Use after a failed bulk import to clean up orphaned jobs.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=PENDING_TIMEOUT_SECONDS)

    # Orphaned pending jobs
    result = await db.execute(
        select(IngestJob).where(
            IngestJob.status == "pending",
            IngestJob.created_at < cutoff,
        )
    )
    pending_jobs = list(result.scalars())
    for job in pending_jobs:
        job.status = "failed"
        job.error_message = "Stale: pending for over 1 hour (never queued)"
        job.completed_at = now

    # Stale running jobs
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

    return {
        "pending_failed": len(pending_jobs),
        "running_failed": len(running_jobs),
        "total_cleaned": len(pending_jobs) + len(running_jobs),
    }


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
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
        role_result = await db.execute(
            select(Role.name)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user.id)
        )
        user_roles = {row[0] for row in role_result.all()}
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

    # Extract collision warning from user_metadata if present
    warning_message = None
    if job.user_metadata and isinstance(job.user_metadata, dict):
        warning_message = job.user_metadata.get("collision_warning")

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        dataset_id=job.dataset_id,
        source_filename=job.source_filename,
        error_message=job.error_message,
        warning_message=warning_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.post("/{job_id}/retry", response_model=UploadResponse)
async def retry_job(
    job_id: uuid.UUID,
    user: User = Depends(require_permission("upload")),
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
        role_result = await db.execute(
            select(Role.name)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user.id)
        )
        user_roles = {row[0] for row in role_result.all()}
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

    if job.source_url and not job.file_path:
        # Service job — no staging file needed
        job.status = "pending"
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        job.dataset_id = None
        await db.commit()

        await ingest_service.defer_async(
            job_id=str(job.id),
            source_url=job.source_url,
            source_layer=job.source_layer or "",
            user_id=str(job.created_by),
        )
    else:
        # File job — check staging file exists
        if not job.file_path or not Path(job.file_path).exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Staging file no longer available. Please re-upload.",
            )

        job.status = "pending"
        job.error_message = None
        job.started_at = None
        job.completed_at = None
        job.dataset_id = None
        await db.commit()

        await ingest_file.defer_async(
            job_id=str(job.id),
            file_path=job.file_path,
            user_id=str(job.created_by),
        )

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="Job re-queued for ingestion",
    )
