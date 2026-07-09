"""Job status API endpoints: poll ingestion job progress and retry."""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
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

log = structlog.get_logger()

# Contract: only these two keys may appear in temporal_parse_errors. The
# alias lets ``cast`` narrow dict writes without triggering ruff F821 on
# string literals inside the ``Literal[...]`` expression.
TemporalParseKey = Literal["temporal_start", "temporal_end"]

router = APIRouter(prefix="/jobs", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)

# Jobs running longer than this are considered stale and auto-failed.
JOB_TIMEOUT_SECONDS = 3600  # 60 minutes (accommodates remote service imports)
# Jobs stuck in "pending" longer than this are considered orphaned (never queued).
PENDING_TIMEOUT_SECONDS = 3600  # 60 minutes


async def sweep_stale_vrt_assets(
    db: AsyncSession,
    stale_cutoff: datetime,
) -> tuple[int, int]:
    """Reset RasterAsset rows stuck in status='regenerating' past ``stale_cutoff``.

    GAP-002: a worker crash mid-regeneration leaves the VRT asset permanently
    stuck in ``status='regenerating'``, causing all future link/regenerate
    calls to 409. This helper mirrors the IngestJob stale-recovery pattern and
    uses the same ``stale_cutoff = now - JOB_TIMEOUT_SECONDS`` threshold.

    Staleness is measured via the associated ``VrtGeneration.started_at`` for
    the asset's ``current_generation_id``, falling back to querying all
    ``VrtGeneration`` rows whose ``started_at`` predates the cutoff and whose
    ``status`` is still pending/running.

    Recovery status: ``'failed'`` — mirrors the explicit failure-handler path
    in ``tasks_vrt.regenerate_vrt`` (which sets ``status='failed'`` on any
    exception). The regeneration did not finish; an operator or retry call
    can re-trigger it.

    Also marks orphaned ``VrtGeneration`` rows (status pending/running past
    the cutoff) as ``'failed'`` so the generation table stays consistent.

    Args:
        db: The active async session (must NOT be committed before returning
            — the caller is responsible for the final ``await db.commit()``).
        stale_cutoff: Any regenerating asset whose generation started before
            this timestamp is considered stale.

    Returns:
        ``(assets_recovered, gens_failed)``
    """
    from app.processing.raster.models import RasterAsset, VrtGeneration

    now = datetime.now(timezone.utc)

    # --- 1. Find stale regenerating RasterAssets ---
    # A VRT asset is stale when:
    #   - status = 'regenerating'
    #   - its latest VrtGeneration (matched by vrt_dataset_id) has
    #     started_at older than stale_cutoff.
    # We query via VrtGeneration so the staleness signal is the
    # regeneration start time, not the asset's last_regenerated_at
    # (which is only written on successful completion).
    stale_asset_result = await db.execute(
        select(RasterAsset).where(
            RasterAsset.status == "regenerating",
            RasterAsset.dataset_id.in_(
                select(VrtGeneration.vrt_dataset_id).where(
                    VrtGeneration.status.in_(["pending", "running"]),
                    VrtGeneration.started_at < stale_cutoff,
                )
            ),
        )
    )
    stale_assets = list(stale_asset_result.scalars())
    for asset in stale_assets:
        asset.status = "failed"
        asset.current_generation_id = None
        log.warning(
            "Recovered stale regenerating VRT asset",
            dataset_id=str(asset.dataset_id),
            stale_cutoff=str(stale_cutoff),
        )

    # --- 2. Mark orphaned VrtGeneration rows as failed ---
    stale_gen_result = await db.execute(
        select(VrtGeneration).where(
            VrtGeneration.status.in_(["pending", "running"]),
            VrtGeneration.started_at < stale_cutoff,
        )
    )
    stale_gens = list(stale_gen_result.scalars())
    for gen in stale_gens:
        gen.status = "failed"
        gen.completed_at = now
        gen.error_message = (
            f"Stale: regeneration running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
        )
        log.warning(
            "Marked stale VrtGeneration as failed",
            generation_id=str(gen.id),
        )

    return len(stale_assets), len(stale_gens)


async def fail_stale_jobs(db: AsyncSession) -> tuple[int, int]:
    """Mark stale ingest jobs as failed. Returns (pending_failed, running_failed).

    Stale rules:
      - status='pending' and created_at older than PENDING_TIMEOUT_SECONDS (orphan, never queued)
      - status='running' and started_at older than JOB_TIMEOUT_SECONDS (worker crashed mid-job)

    Also sweeps VRT RasterAsset rows stuck in status='regenerating' past
    JOB_TIMEOUT_SECONDS (GAP-002) via the shared ``sweep_stale_vrt_assets``
    helper. The VRT sweep uses the same stale_cutoff as the running-jobs sweep.

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

    # GAP-002: sweep stale VRT regenerating assets using the same cutoff.
    await sweep_stale_vrt_assets(db, running_cutoff)

    # fix(#434): purge terminal jobs past retention so the admin Jobs page
    # doesn't accumulate history forever. Cutoff is on finished-at
    # (coalesce(completed_at, created_at)) rather than created_at — the stale
    # sweep above fails ancient pending/running rows with completed_at=now, and
    # a created_at cutoff would delete that fresh failure evidence in the same
    # transaction (codex P2 r8). 0 = keep forever. Each dataset's most recent
    # complete job is exempt regardless of age: /jobs/by-dataset/{id} serves the
    # dataset page's persistent ingest warnings and the reupload source_layer
    # hint from it (codex P2 on #434). Jobs whose dataset was deleted have
    # dataset_id nulled (FK ondelete=SET NULL) and stay purgeable.
    if settings.ingest_jobs_retention_days > 0:
        retention_cutoff = now - timedelta(days=settings.ingest_jobs_retention_days)
        latest_complete_ids = (
            select(IngestJob.id)
            .where(
                IngestJob.status == "complete",
                IngestJob.dataset_id.is_not(None),
            )
            .distinct(IngestJob.dataset_id)
            .order_by(IngestJob.dataset_id, IngestJob.created_at.desc())
        )
        # codex P2 (r7) on #434: manifest apply classifies skip/update-vs-create
        # via _latest_completed_manifest_job (manifest_service.py), which looks
        # up the newest complete job per user_metadata->>'manifest_key'. A
        # manual reupload makes the manual job the per-dataset exemption, so
        # without this second exemption the manifest-keyed row would age out
        # and the next apply would duplicate the dataset. Mirrors the lookup's
        # ordering (completed_at desc, created_at desc).
        manifest_key = IngestJob.user_metadata["manifest_key"].astext
        latest_manifest_ids = (
            select(IngestJob.id)
            .where(
                IngestJob.status == "complete",
                manifest_key.is_not(None),
                # codex P2 (r9): the mirrored lookup joins Dataset, so a job
                # whose dataset was deleted (dataset_id nulled by the FK) can't
                # influence reapply — exempting it would only defeat cleanup.
                IngestJob.dataset_id.is_not(None),
            )
            .distinct(manifest_key)
            .order_by(
                manifest_key,
                IngestJob.completed_at.desc(),
                IngestJob.created_at.desc(),
            )
        )
        # Single DELETE .. RETURNING re-applies every predicate atomically at
        # delete time — a SELECT-then-DELETE-by-id pair let /jobs/{id}/retry
        # flip a candidate back to pending between the two statements and
        # still lose the row (codex P2 r10 on #434).
        deleted = await db.execute(
            delete(IngestJob)
            .where(
                IngestJob.status.not_in(("pending", "running")),
                func.coalesce(IngestJob.completed_at, IngestJob.created_at)
                < retention_cutoff,
                IngestJob.id.not_in(latest_complete_ids),
                IngestJob.id.not_in(latest_manifest_ids),
            )
            .returning(IngestJob.file_path)
        )
        deleted_rows = deleted.all()
        deleted_paths = {fp for (fp,) in deleted_rows if fp}
        if deleted_rows:
            log.info(
                "Purged ingest jobs past retention",
                purged=len(deleted_rows),
                retention_days=settings.ingest_jobs_retention_days,
            )

        # codex P2 (r3) on #434: failed local uploads keep their staged file
        # for retry (_should_unlink_staging), and fan-out children's shared S3
        # original is explicitly deferred to "a retention policy" (#430 BA-09)
        # — this purge is that policy. Reap staged objects whose last pointer
        # was just deleted, but (codex P2 r4) only when no surviving row that
        # still NEEDS the file references the same path: pending/running read
        # it now; failed keeps it for /jobs/{id}/retry (a failed-only
        # endpoint). Surviving complete rows (e.g. the exemptions above) keep
        # their metadata row but not the staged file — otherwise a successful
        # fan-out's shared original, referenced forever by children that are
        # each a dataset's latest complete job, would never be reaped
        # (codex P2 r5). Running after the DELETE, any remaining row counts.
        if deleted_paths:
            survivors = await db.execute(
                select(IngestJob.file_path).where(
                    IngestJob.file_path.in_(deleted_paths),
                    IngestJob.status.in_(("pending", "running", "failed")),
                )
            )
            deleted_paths -= set(survivors.scalars())
        staging_root = Path(settings.upload_staging_dir).resolve()
        for file_path in deleted_paths:
            try:
                local = Path(file_path).resolve()
                if local.exists():
                    if local.is_relative_to(staging_root):
                        local.unlink(missing_ok=True)
                elif file_path.startswith("staging/"):
                    # codex P1 (r9): only presigned-upload staging keys
                    # ("staging/{job_id}/…", see ingest service/router) may be
                    # deleted from object storage — manifest sources store
                    # arbitrary same-bucket keys (user-managed objects) as
                    # relative file_path values too.
                    from app.platform.storage import get_storage

                    await get_storage().delete(file_path)
            except Exception:  # broad: best-effort staging cleanup
                log.warning(
                    "Failed to reap staged file for purged jobs",
                    file_path=file_path,
                )

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
        # REMED-02 / ingest-audit P2-07: surface worker-written progress fields.
        progress=job.progress,
        current_step=job.current_step,
        rows_processed=job.rows_processed,
        archive_failed=archive_failed,
        temporal_parse_errors=temporal_parse_errors,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/by-dataset/{dataset_id}", response_model=JobStatusResponse | None)
async def get_job_status_by_dataset(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JobStatusResponse | None:
    """Look up the most recent ingest job for a dataset.

    Used by the dataset detail page to surface ingest warnings permanently
    (S3 completion) — the job is the source of truth for
    ``reserved_rename`` / ``dbf_truncation_collision`` / ``archive_failed``
    / ``temporal_parse_errors`` metadata.

    Returns the most recently created completed job for the dataset. When the
    dataset is visible but has no ingest job (e.g. registered from an existing
    table, or a remote/STAC dataset), returns ``200`` with a ``null`` body
    instead of 404 — a "no job" outcome is normal for these datasets and a
    404 would needlessly pollute the browser console on the dataset detail
    page. A genuine 404 is still raised when the dataset is not visible to the
    user, to avoid leaking job existence (see visibility check below).
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
        # Dataset is visible but has no ingest job (remote/STAC/registered
        # dataset). Return 200 + null rather than 404 so the dataset detail
        # page can treat it as "no warnings" without a console 404.
        return None

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
