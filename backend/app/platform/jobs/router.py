"""Job status API endpoints: poll ingestion job progress and retry.

The stale-job recovery/sweep handlers and their SQL constants split out into
``sweep.py`` (#1335) — this module keeps the plain job CRUD surface (the
FastAPI routes below) and re-exports what it imports from there, so every
name a caller previously imported from ``app.platform.jobs.router`` still
resolves from here.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_current_active_user,
    require_mode_permission,
    require_permission,
)
from app.processing.ingest.schemas import UploadResponse
from app.processing.ingest.service import queue_ingest_job
from app.platform.extensions import get_permission_extension
from app.platform.jobs.heartbeat import ANALYSIS_MATERIALIZE_LEASE_SECONDS
from app.platform.jobs.models import EMBEDDING_BACKFILL_METADATA_KEY, IngestJob
from app.platform.jobs.schemas import (
    DbfTruncationCollisionWarning,
    JobStatusResponse,
    MercatorClipWarning,
    ReservedRenameWarning,
    StaleCleanupResponse,
)
from app.platform.jobs.staging_reconcile import reconcile_orphaned_staging_objects
from app.platform.jobs.sweep import (
    ABANDONED_UPLOAD_MESSAGE,  # noqa: F401 -- re-exported, see __all__
    JOB_TIMEOUT_SECONDS,
    audit_settled_embedding_backfill,
    STALE_PENDING_BOUND_MESSAGE,
    STALE_PENDING_UNBOUND_MESSAGE,  # noqa: F401 -- re-exported, see __all__
    StaleCleanupOutcome,  # noqa: F401 -- re-exported, see __all__
    _RECHECK_TRANSFER_MARGIN_SECONDS,  # noqa: F401 -- re-exported, see __all__
    _reap_committed_staged_paths,
    _reap_stale_generation_storage,  # noqa: F401 -- re-exported, see __all__
    _sweep_expired_presigned_staging,
    fail_stale_jobs,
    post_expiry_sweep_after_seconds,  # noqa: F401 -- re-exported, see __all__
    publish_refresh_reconciliation,
    is_abandoned_presigned_upload,  # noqa: F401 -- re-exported, see __all__
    stale_pending_clauses,
    stale_pending_cutoff_seconds,
    stale_pending_unbound_values,
    sweep_stale_vrt_assets,  # noqa: F401 -- re-exported, see __all__
)
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import CONFLICT_RESPONSE, ERROR_RESPONSES_AUTH

log = structlog.get_logger()

# Contract: only these two keys may appear in temporal_parse_errors. The
# alias lets ``cast`` narrow dict writes without triggering ruff F821 on
# string literals inside the ``Literal[...]`` expression.
TemporalParseKey = Literal["temporal_start", "temporal_end"]

router = APIRouter(prefix="/jobs", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)


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
    user: Identity = Depends(
        require_mode_permission(
            single_tenant="manage_users", multi_tenant="manage_tenants"
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> StaleCleanupResponse:
    """Fail all stale jobs: pending >1h or running >1h.

    **Ops-only.** Not used by the GeoLens UI — invoke from `curl`/`gh api`/cron
    when you need to force-clean orphaned jobs after a worker outage.
    Equivalent logic runs automatically every 5 minutes via the lifespan
    sweeper, so this endpoint is only needed if you need cleanup faster than
    that interval.
    """
    from app.core.tenancy import is_multi_tenant

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
        multi_tenant = is_multi_tenant()
        if multi_tenant:
            # FORCE RLS makes a request session visible only to its current
            # tenant. The lifecycle helper opens a scoped transaction for
            # every tenant and reaps each tenant's staged objects in context.
            from app.api.main import sweep_stale_jobs_once

            fleet_details = await sweep_stale_jobs_once(detailed=True)
            if not isinstance(fleet_details, dict):
                raise TypeError("Detailed fleet cleanup returned no details")
            database_details = fleet_details
        else:
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
        # In single-tenant mode, commit database mutations plus a durable phase
        # marker before touching local/S3 artifacts. The fleet helper applies
        # that ordering inside each tenant-scoped transaction.
        await db.commit()
        if multi_tenant:
            details = database_details
        else:
            # fix(#1277 review): this path passed commit=False, so the sweep
            # deferred its counter to whoever owns the commit — that is the
            # line above. The multi-tenant branch needs nothing here: the
            # fleet helper runs fail_stale_jobs with its own commit per
            # tenant, so each tenant's pass publishes its own.
            publish_refresh_reconciliation(outcome)
            outcome = await _reap_committed_staged_paths(outcome)
            outcome = await _sweep_expired_presigned_staging(db, outcome)
            # fix(#1249): same object-driven reconciliation the background
            # sweeper runs. The multi-tenant branch needs nothing here — the
            # fleet helper runs fail_stale_jobs with its own commit per
            # tenant, and that path already reconciles in tenant context.
            await reconcile_orphaned_staging_objects(db)
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
    #
    # fix(#691): analysis materialize jobs use the short materialize lease
    # rather than the 60-minute backstop, mirroring the per-user cap in
    # router_analysis.py. The frontend polls this route for any job it
    # tracks, so a hard-killed worker's analysis job flips to failed within
    # the lease window and the Analysis panel's Create button re-enables at
    # the same moment the server would admit a new materialize — the client
    # follows the server's signal without needing heartbeat visibility.
    liveness_at = job.heartbeat_at or job.started_at
    if job.status == "running" and liveness_at is not None:
        is_analysis = "analysis" in (job.user_metadata or {})
        lease_seconds = (
            ANALYSIS_MATERIALIZE_LEASE_SECONDS if is_analysis else JOB_TIMEOUT_SECONDS
        )
        elapsed = (now - liveness_at).total_seconds()
        if elapsed > lease_seconds:
            lease_result = await db.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job.id,
                    IngestJob.attempt_id == job.attempt_id,
                    IngestJob.status == "running",
                    func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                    < now - timedelta(seconds=lease_seconds),
                )
                .values(
                    status="failed",
                    error_message=f"Worker heartbeat expired after {int(elapsed)}s",
                    completed_at=now,
                )
            )
            # fix(#1550 review r2): gated on the UPDATE landing, as the
            # stale-pending branch below already is. The predicate is
            # conditional — a heartbeat renewal or the worker's own
            # finalization committing between this request's read and this
            # write makes it match zero rows — and auditing anyway would put
            # "worker_lost" over a job that is still running, or that has just
            # completed. A helper that performs a state change reports whether
            # it landed; a caller recording an outcome conditions on that.
            #
            # Same transaction as the status change, so the two records of one
            # state cannot disagree.
            if lease_result.rowcount:
                await audit_settled_embedding_backfill(
                    db,
                    job_id=job.id,
                    user_metadata=job.user_metadata,
                    created_by=job.created_by,
                    error_code="worker_lost",
                )
            await db.commit()
            await db.refresh(job)

    # Auto-fail jobs stuck in "pending" beyond the timeout (orphaned / never
    # queued). fix(#724 review): gated on the same live-queue predicate the
    # sweeper uses — this is the path that actually fires, because the frontend
    # polls this route every 2s for any job it is tracking.
    if job.status == "pending" and job.created_at is not None:
        elapsed = (now - job.created_at).total_seconds()
        # fix(#1235 review r2): both halves, through the shared clauses. This
        # path is the one that actually fires, so leaving it on the old
        # predicates left the completion race exactly where it was — a poll
        # blocked on a completing job's row lock resumes post-commit and fails
        # the row it waited for.
        for completion_bound, message in (
            (False, f"Stale: pending for {int(elapsed)}s without being processed"),
            (True, STALE_PENDING_BOUND_MESSAGE),
        ):
            # fix(#1235 review r4): a fast-path skip, NOT a correctness gate.
            # The clauses below remain the authority — they re-check the same
            # age in SQL, so a row that slips past this check is still only
            # failed if it genuinely qualifies. What this restores is the outer
            # `elapsed` check the r2 rewrite dropped: without it, every 2s poll
            # of every pending job issued both UPDATEs, and the frontend polls
            # this route for the whole life of a job that is behaving normally.
            if elapsed <= stale_pending_cutoff_seconds(
                completion_bound=completion_bound
            ):
                continue
            # fix(#1556): the unbound half takes the shared ACTION, which
            # settles a never-bound presigned upload as `cancelled`. The bound
            # half keeps writing `failed` outright — a completion that bound
            # bytes and then stalled IS a failure — and this is the same split
            # the background sweep and the worker's startup recovery apply.
            values = (
                {"status": "failed", "error_message": message, "completed_at": now}
                if completion_bound
                else stale_pending_unbound_values(now, message=message)
            )
            result = await db.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job.id,
                    IngestJob.attempt_id == job.attempt_id,
                    *stale_pending_clauses(now, completion_bound=completion_bound),
                )
                .values(**values)
            )
            if result.rowcount:
                await audit_settled_embedding_backfill(
                    db,
                    job_id=job.id,
                    user_metadata=job.user_metadata,
                    created_by=job.created_by,
                    error_code="never_started",
                )
                await db.commit()
                await db.refresh(job)
                break

    return await _job_to_status_response(job)


async def _retry_capability(job: IngestJob) -> tuple[bool, str | None]:
    if job.status != "failed":
        return False, None
    if bool((job.user_metadata or {}).get("reupload")):
        return (
            False,
            "Dataset replacement jobs cannot be replayed as ordinary imports. Start the reupload again.",
        )
    if bool((job.user_metadata or {}).get("refresh")):
        # feat(#1265): a registered-PostGIS refresh job carries no file and no
        # URL, so without this it fell through to the import copy below and
        # told the user their "source" was gone — for a dataset that was never
        # imported from one. Deliberately AFTER the reupload check: a service
        # refresh job carries both markers and keeps its existing wording.
        return (
            False,
            "Refresh runs cannot be replayed as imports. Refresh the dataset again from its source panel.",
        )
    if bool((job.user_metadata or {}).get("service_auth_required")):
        return (
            False,
            "This service import requires fresh credentials. Start the import again to re-authenticate.",
        )
    if (job.user_metadata or {}).get("analysis"):
        # ux(#698): analysis jobs carry file_path="" and would otherwise fall
        # through to the import copy below, telling the user their "source" is
        # gone and to "start the import again" for something that was never an
        # import. They are genuinely not replayable here either: the drawn clip
        # mask is deliberately not persisted (router_analysis.py stores a
        # marker, not the geometry), so a replay could not reconstruct the run.
        return (
            False,
            "Analysis runs cannot be replayed as imports. Start the analysis again from the map builder.",
        )
    if (job.user_metadata or {}).get(EMBEDDING_BACKFILL_METADATA_KEY):
        # fix(#1542): embedding backfill runs carry file_path="" for the same
        # reason analysis runs do, and would otherwise be offered as replayable
        # imports of a source that never existed. Restarting one is a POST to
        # /admin/backfill-embeddings/, which re-runs its own pre-flight and
        # concurrency guards — replaying it through the ingest retry path would
        # skip both.
        return (
            False,
            "Embedding backfill runs cannot be replayed as imports. Start the backfill again from Settings.",
        )
    if job.source_url and not job.file_path:
        return True, None
    if not job.file_path:
        return False, "The source is no longer available. Start the import again."

    from app.core.tenancy import is_multi_tenant

    candidate = Path(job.file_path)
    if candidate.exists() and (candidate.is_absolute() or not is_multi_tenant()):
        return True, None
    if job.file_path.startswith("/"):
        return False, "Staging file no longer available. Please re-upload."

    try:
        from app.platform.storage import get_storage

        physical_file_path = (
            resolve_current_storage_key(job.file_path)
            if job.file_path.startswith("staging/")
            else job.file_path
        )
        if await get_storage().exists(physical_file_path):
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
    warnings: list[
        ReservedRenameWarning | DbfTruncationCollisionWarning | MercatorClipWarning
    ] = []
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
                    elif kind == "mercator_clip":
                        warnings.append(MercatorClipWarning.model_validate(raw))
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
        rows_failed=(job.user_metadata or {}).get("rows_failed"),
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
    ``reserved_rename`` / ``dbf_truncation_collision`` / ``mercator_clip`` /
    ``archive_failed`` / ``temporal_parse_errors`` metadata.

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


__all__ = [
    "ABANDONED_UPLOAD_MESSAGE",
    "JOB_TIMEOUT_SECONDS",
    "STALE_PENDING_BOUND_MESSAGE",
    "STALE_PENDING_UNBOUND_MESSAGE",
    "StaleCleanupOutcome",
    "TemporalParseKey",
    "_RECHECK_TRANSFER_MARGIN_SECONDS",
    "_reap_stale_generation_storage",
    # fix(#1556): the worker's startup recovery settles the same rows this
    # module's sweep does, so it needs the same helper through the same façade.
    "audit_settled_embedding_backfill",
    "fail_stale_jobs",
    "get_retry_capability",
    "is_abandoned_presigned_upload",
    "post_expiry_sweep_after_seconds",
    "router",
    "stale_pending_clauses",
    "stale_pending_cutoff_seconds",
    "stale_pending_unbound_values",
    "sweep_stale_vrt_assets",
]
