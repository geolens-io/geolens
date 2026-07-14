"""Job status API endpoints: poll ingestion job progress and retry."""

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast, overload

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_current_active_user,
    require_permission,
)
from app.processing.ingest.schemas import UploadResponse
from app.processing.ingest.service import queue_ingest_job
from app.platform.extensions import get_permission_extension
from app.platform.jobs.models import IngestJob
from app.platform.jobs.schemas import (
    DbfTruncationCollisionWarning,
    JobStatusResponse,
    ReservedRenameWarning,
    StaleCleanupResponse,
)
from app.standards.ogc.errors import CONFLICT_RESPONSE, ERROR_RESPONSES_AUTH

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


@dataclass(frozen=True)
class StaleCleanupOutcome:
    """Complete result of one stale-job and retained-staging cleanup pass."""

    pending_failed: int
    running_failed: int
    vrt_assets_recovered: int
    vrt_generations_failed: int
    terminal_jobs_purged: int
    staged_paths_considered: int
    local_files_reaped: int
    storage_objects_reaped: int
    staged_paths_skipped: int
    staged_cleanup_failures: int
    _staged_paths: tuple[str, ...] = field(default=(), repr=False, compare=False)

    @property
    def total_cleaned(self) -> int:
        """Legacy count: ingest jobs transitioned from active to failed."""
        return self.pending_failed + self.running_failed

    @property
    def total_affected(self) -> int:
        """Rows and staged objects mutated by the cleanup pass."""
        return (
            self.total_cleaned
            + self.vrt_assets_recovered
            + self.vrt_generations_failed
            + self.terminal_jobs_purged
            + self.local_files_reaped
            + self.storage_objects_reaped
        )

    def as_dict(self) -> dict[str, int]:
        """Return the stable API and audit detail shape."""
        return {
            "pending_failed": self.pending_failed,
            "running_failed": self.running_failed,
            "total_cleaned": self.total_cleaned,
            "vrt_assets_recovered": self.vrt_assets_recovered,
            "vrt_generations_failed": self.vrt_generations_failed,
            "terminal_jobs_purged": self.terminal_jobs_purged,
            "staged_paths_considered": self.staged_paths_considered,
            "local_files_reaped": self.local_files_reaped,
            "storage_objects_reaped": self.storage_objects_reaped,
            "staged_paths_skipped": self.staged_paths_skipped,
            "staged_cleanup_failures": self.staged_cleanup_failures,
            "total_affected": self.total_affected,
        }


async def _reap_committed_staged_paths(
    outcome: StaleCleanupOutcome,
) -> StaleCleanupOutcome:
    """Delete staging artifacts only after their job-row purge is durable."""
    local_files_reaped = 0
    storage_objects_reaped = 0
    staged_paths_skipped = 0
    staged_cleanup_failures = 0
    staging_root = Path(settings.upload_staging_dir).resolve()

    for file_path in outcome._staged_paths:
        try:
            local = Path(file_path).resolve()
            if local.exists():
                if local.is_relative_to(staging_root):
                    local.unlink(missing_ok=True)
                    local_files_reaped += 1
                else:
                    staged_paths_skipped += 1
            elif file_path.startswith("staging/"):
                # Only presigned-upload staging keys ("staging/{job_id}/…")
                # may be deleted. Manifest sources can reference arbitrary
                # same-bucket keys through this column.
                from app.platform.storage import get_storage

                await get_storage().delete(file_path)
                storage_objects_reaped += 1
            else:
                staged_paths_skipped += 1
        except Exception:  # broad: best-effort staging cleanup
            staged_cleanup_failures += 1
            log.warning(
                "Failed to reap staged file for purged jobs",
                file_path=file_path,
            )

    return replace(
        outcome,
        local_files_reaped=local_files_reaped,
        storage_objects_reaped=storage_objects_reaped,
        staged_paths_skipped=staged_paths_skipped,
        staged_cleanup_failures=staged_cleanup_failures,
    )


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
    # Fail generation leases atomically. The status + liveness predicates are
    # re-evaluated by PostgreSQL at UPDATE time, so a heartbeat racing the
    # sweep wins and the generation remains live.
    stale_gen_result = await db.execute(
        update(VrtGeneration)
        .where(
            VrtGeneration.status.in_(["pending", "running"]),
            func.coalesce(VrtGeneration.heartbeat_at, VrtGeneration.started_at)
            < stale_cutoff,
        )
        .values(
            status="failed",
            completed_at=now,
            error_message=(
                f"Stale: regeneration running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
            ),
        )
        .returning(VrtGeneration.id)
    )
    stale_generation_ids = list(stale_gen_result.scalars())

    # Clear an asset only if it still points at the generation just failed.
    # A newer regeneration has a different current_generation_id and is fenced.
    stale_asset_result = await db.execute(
        update(RasterAsset)
        .where(
            RasterAsset.status == "regenerating",
            RasterAsset.current_generation_id.in_(stale_generation_ids),
        )
        .values(status="failed", current_generation_id=None)
        .returning(RasterAsset.dataset_id)
    )
    stale_asset_ids = list(stale_asset_result.scalars())
    for dataset_id in stale_asset_ids:
        log.warning(
            "Recovered stale regenerating VRT asset",
            dataset_id=str(dataset_id),
            stale_cutoff=str(stale_cutoff),
        )

    return len(stale_asset_ids), len(stale_generation_ids)


@overload
async def fail_stale_jobs(
    db: AsyncSession,
    *,
    commit: bool = True,
    detailed: Literal[False] = False,
) -> tuple[int, int]: ...


@overload
async def fail_stale_jobs(
    db: AsyncSession,
    *,
    commit: bool = True,
    detailed: Literal[True],
) -> StaleCleanupOutcome: ...


async def fail_stale_jobs(
    db: AsyncSession,
    *,
    commit: bool = True,
    detailed: bool = False,
) -> tuple[int, int] | StaleCleanupOutcome:
    """Mark stale jobs failed and reap retained staging artifacts.

    The default two-item tuple preserves the background-sweeper contract.
    ``detailed=True`` returns the complete operational outcome for the admin
    endpoint and its audit event.

    Stale rules:
      - status='pending' and created_at older than PENDING_TIMEOUT_SECONDS (orphan, never queued)
      - status='running' and heartbeat_at/started_at older than JOB_TIMEOUT_SECONDS
        (worker lease expired)

    Also sweeps VRT RasterAsset rows stuck in status='regenerating' past
    JOB_TIMEOUT_SECONDS (GAP-002) via the shared ``sweep_stale_vrt_assets``
    helper. The VRT sweep uses the same stale_cutoff as the running-jobs sweep.

    Used by both the admin cleanup endpoint and the background lifespan sweeper.
    """
    now = datetime.now(timezone.utc)
    pending_cutoff = now - timedelta(seconds=PENDING_TIMEOUT_SECONDS)

    pending_result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.status == "pending",
            IngestJob.created_at < pending_cutoff,
        )
        .values(
            status="failed",
            error_message="Stale: pending for over 1 hour (never queued)",
            completed_at=now,
        )
        .returning(IngestJob.id)
    )
    pending_job_ids = list(pending_result.scalars())

    running_cutoff = now - timedelta(seconds=JOB_TIMEOUT_SECONDS)
    running_result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.status == "running",
            func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
            < running_cutoff,
        )
        .values(
            status="failed",
            error_message=(
                f"Stale: running for over {JOB_TIMEOUT_SECONDS // 60} minutes"
            ),
            completed_at=now,
        )
        .returning(IngestJob.id)
    )
    running_job_ids = list(running_result.scalars())

    # GAP-002: sweep stale VRT regenerating assets using the same cutoff.
    vrt_assets_recovered, vrt_generations_failed = await sweep_stale_vrt_assets(
        db, running_cutoff
    )

    terminal_jobs_purged = 0
    staged_paths_considered = 0
    local_files_reaped = 0
    storage_objects_reaped = 0
    staged_paths_skipped = 0
    staged_cleanup_failures = 0
    deleted_paths: set[str] = set()

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
        terminal_jobs_purged = len(deleted_rows)
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
        staged_paths_considered = len(deleted_paths)
    outcome = StaleCleanupOutcome(
        pending_failed=len(pending_job_ids),
        running_failed=len(running_job_ids),
        vrt_assets_recovered=vrt_assets_recovered,
        vrt_generations_failed=vrt_generations_failed,
        terminal_jobs_purged=terminal_jobs_purged,
        staged_paths_considered=staged_paths_considered,
        local_files_reaped=local_files_reaped,
        storage_objects_reaped=storage_objects_reaped,
        staged_paths_skipped=staged_paths_skipped,
        staged_cleanup_failures=staged_cleanup_failures,
        _staged_paths=tuple(sorted(deleted_paths)),
    )
    if commit:
        # Never remove an external artifact for a DELETE that may still roll
        # back. A crash after this commit can leak a staging object, but it
        # cannot restore a job row whose only retry input has been destroyed.
        await db.commit()
        outcome = await _reap_committed_staged_paths(outcome)
    if detailed:
        return outcome
    return outcome.pending_failed, outcome.running_failed


async def _can_access_another_users_job(
    request: Request,
    db: AsyncSession,
    user: Identity,
    job: IngestJob,
) -> bool:
    """Delegate cross-user job access to the effective permission policy.

    Owner access is handled by callers before invoking this helper. Passing the
    job as ``resource`` lets enterprise extensions apply finer-grained policy
    without core code falling back to a hard-coded role-name check.
    """
    # Deferred by design: shared platform code must not import product-domain
    # policy implementations at module load time (D-17).
    from app.modules.auth.dependencies import (
        get_cached_user_roles,
        log_permission_denial,
    )
    from app.modules.auth.permissions import get_effective_permissions

    user_roles = await get_cached_user_roles(request, db, user)
    matrix = getattr(request.state, "_effective_permissions", None)
    if matrix is None:
        matrix = await get_effective_permissions(db)
        request.state._effective_permissions = matrix
    granted = await get_permission_extension().check_permission(
        db,
        user,
        "manage_users",
        user_roles=user_roles,
        permission_matrix=matrix,
        resource=job,
    )
    if not granted:
        log_permission_denial(
            request,
            user,
            "manage_users",
            user_roles,
            resource_type="ingest_job",
        )
    return granted


@router.post("/cleanup/stale/", response_model=StaleCleanupResponse)
async def cleanup_stale_jobs(
    request: Request,
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
    # Deferred by design to preserve the platform -> modules layer boundary.
    from app.modules.audit.service import AuditEvent, audit_emit, audit_emit_durable

    operation_uuid = uuid.uuid4()
    operation_id = str(operation_uuid)
    ip_address = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="job.cleanup_stale",
            resource_type="ingest_job",
            resource_id=operation_uuid,
            details={"operation_id": operation_id, "outcome": "requested"},
            ip_address=ip_address,
        ),
    )
    # Retention cleanup can unlink local files and delete S3 objects. Make the
    # operator's request durable before entering that irreversible phase.
    await db.commit()

    try:
        outcome = await fail_stale_jobs(db, commit=False, detailed=True)
        database_details = outcome.as_dict()
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="job.cleanup_stale",
                resource_type="ingest_job",
                resource_id=operation_uuid,
                details={
                    "operation_id": operation_id,
                    "outcome": "database_committed",
                    **database_details,
                },
                ip_address=ip_address,
            ),
        )
        # Commit database mutations plus a durable phase marker before touching
        # local/S3 artifacts. A later failure can leak a staging object, but it
        # cannot roll the job row back after destroying its only retry input.
        await db.commit()
        outcome = await _reap_committed_staged_paths(outcome)
        details = outcome.as_dict()
    except Exception as exc:  # broad: cleanup spans DB and artifact deletion
        await db.rollback()
        # Cleanup failures can embed local paths or storage keys in exception
        # messages. Record only the exception class in operator telemetry; the
        # correlated audit event likewise carries a stable error code only.
        log.error(
            "Stale job cleanup failed",
            operation_id=operation_id,
            user_id=str(user.id),
            error_type=type(exc).__name__,
        )
        try:
            # A failed commit may leave the request session/connection unusable;
            # persist the terminal outcome through an independently owned session.
            await audit_emit_durable(
                AuditEvent(
                    user_id=user.id,
                    action="job.cleanup_stale",
                    resource_type="ingest_job",
                    resource_id=operation_uuid,
                    details={
                        "operation_id": operation_id,
                        "outcome": "failed",
                        "error_code": "cleanup_failed",
                    },
                    ip_address=ip_address,
                )
            )
        except Exception as audit_exc:  # broad: retain the generic failure response
            log.error(
                "Failed to persist stale cleanup failure audit",
                operation_id=operation_id,
                user_id=str(user.id),
                error_type=type(audit_exc).__name__,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stale job cleanup failed. See server logs for details.",
        ) from None

    # Cleanup has already committed and reaped its artifacts. A bookkeeping
    # outage must not turn that successful mutation into a retryable 500 or
    # emit a contradictory ``failed`` event; the committed phase marker still
    # provides a durable recovery trail.
    try:
        await audit_emit_durable(
            AuditEvent(
                user_id=user.id,
                action="job.cleanup_stale",
                resource_type="ingest_job",
                resource_id=operation_uuid,
                details={
                    "operation_id": operation_id,
                    "outcome": "completed",
                    **details,
                },
                ip_address=ip_address,
            )
        )
    except Exception as audit_exc:  # broad: cleanup itself has succeeded
        log.error(
            "Failed to persist stale cleanup completion audit",
            operation_id=operation_id,
            user_id=str(user.id),
            error_type=type(audit_exc).__name__,
        )

    return StaleCleanupResponse(**details)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    request: Request,
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

    # Owners always retain access. Cross-user access follows the active
    # capability policy rather than assuming a hard-coded "admin" role.
    if job.created_by != user.id and not await _can_access_another_users_job(
        request, db, user, job
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this job",
        )

    now = datetime.now(timezone.utc)

    # Auto-fail jobs whose worker lease has expired. Fall back to started_at
    # for jobs created before heartbeat support was deployed.
    liveness_at = job.heartbeat_at or job.started_at
    if job.status == "running" and liveness_at is not None:
        elapsed = (now - liveness_at).total_seconds()
        if elapsed > JOB_TIMEOUT_SECONDS:
            await db.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job.id,
                    IngestJob.attempt_id == job.attempt_id,
                    IngestJob.status == "running",
                    func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                    < now - timedelta(seconds=JOB_TIMEOUT_SECONDS),
                )
                .values(
                    status="failed",
                    error_message=f"Worker heartbeat expired after {int(elapsed)}s",
                    completed_at=now,
                )
            )
            await db.commit()
            await db.refresh(job)

    # Auto-fail jobs stuck in "pending" beyond the timeout (orphaned / never queued)
    if job.status == "pending" and job.created_at is not None:
        elapsed = (now - job.created_at).total_seconds()
        if elapsed > PENDING_TIMEOUT_SECONDS:
            await db.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job.id,
                    IngestJob.attempt_id == job.attempt_id,
                    IngestJob.status == "pending",
                    IngestJob.created_at
                    < now - timedelta(seconds=PENDING_TIMEOUT_SECONDS),
                )
                .values(
                    status="failed",
                    error_message=(
                        f"Stale: pending for {int(elapsed)}s without being processed"
                    ),
                    completed_at=now,
                )
            )
            await db.commit()
            await db.refresh(job)

    return await _job_to_status_response(job)


async def _retry_capability(job: IngestJob) -> tuple[bool, str | None]:
    if job.status != "failed":
        return False, None
    if bool((job.user_metadata or {}).get("reupload")):
        return (
            False,
            "Dataset replacement jobs cannot be replayed as ordinary imports. Start the reupload again.",
        )
    if bool((job.user_metadata or {}).get("service_auth_required")):
        return (
            False,
            "This service import requires fresh credentials. Start the import again to re-authenticate.",
        )
    if job.source_url and not job.file_path:
        return True, None
    if not job.file_path:
        return False, "The source is no longer available. Start the import again."

    if Path(job.file_path).exists():
        return True, None
    if job.file_path.startswith("/"):
        return False, "Staging file no longer available. Please re-upload."

    try:
        from app.platform.storage import get_storage

        if await get_storage().exists(job.file_path):
            return True, None
    except (
        Exception
    ):  # broad: storage implementations expose provider-specific failures
        log.warning(
            "retry_source_availability_check_failed",
            job_id=str(job.id),
            storage_key=job.file_path,
            exc_info=True,
        )
        return False, "Source availability could not be verified. Try again later."

    return False, "The staging object is no longer available. Please re-upload."


async def get_retry_capability(job: IngestJob) -> tuple[bool, str | None]:
    """Return the retry contract shared by user and admin job surfaces."""

    return await _retry_capability(job)


async def _job_to_status_response(job: IngestJob) -> JobStatusResponse:
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

    can_retry, retry_reason = await _retry_capability(job)

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        dataset_id=job.dataset_id,
        source_filename=job.source_filename,
        error_message=job.error_message,
        can_retry=can_retry,
        retry_reason=retry_reason,
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

    return await _job_to_status_response(job)


@router.post(
    "/{job_id}/retry",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={409: CONFLICT_RESPONSE},
)
async def retry_job(
    job_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Retry a failed ingestion job by re-queuing.

    Only callable on jobs with status 'failed'. The staging file must
    still exist (preserved on failure for retry).
    """
    # Deferred by design to preserve the platform -> modules layer boundary.
    from app.modules.audit.service import AuditEvent, audit_emit

    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Owners always retain access. Cross-user retries additionally require the
    # effective manage_users capability through PermissionExtension.
    if job.created_by != user.id and not await _can_access_another_users_job(
        request, db, user, job
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to retry this job",
        )

    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only failed jobs can be retried",
        )

    can_retry, retry_reason = await _retry_capability(job)
    if not can_retry:
        status_code = (
            status.HTTP_409_CONFLICT
            if bool((job.user_metadata or {}).get("service_auth_required"))
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(
            status_code=status_code,
            detail=retry_reason or "This job cannot be retried.",
        )

    # Reset the job to pending and commit before re-queueing so the
    # orphan guard in queue_ingest_job can flip it back to failed if
    # the queue is down (RESILIENCE-2).
    previous_attempt_id = job.attempt_id
    next_attempt_id = uuid.uuid4()
    retry_result = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job.id,
            IngestJob.status == "failed",
            IngestJob.attempt_id == previous_attempt_id,
        )
        .values(
            status="pending",
            attempt_id=next_attempt_id,
            error_message=None,
            started_at=None,
            heartbeat_at=None,
            completed_at=None,
            dataset_id=None,
        )
    )
    if not retry_result.rowcount:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job was already retried by another request",
        )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="job.retry",
            resource_type="ingest_job",
            resource_id=job.id,
            details={
                "job_owner_id": (
                    str(job.created_by) if job.created_by is not None else None
                ),
                "previous_attempt_id": (
                    str(previous_attempt_id)
                    if previous_attempt_id is not None
                    else None
                ),
                "next_attempt_id": str(next_attempt_id),
                "cross_user": job.created_by != user.id,
            },
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    await db.refresh(job)

    await queue_ingest_job(job, str(job.created_by), db=db)

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="Job re-queued for ingestion",
    )
