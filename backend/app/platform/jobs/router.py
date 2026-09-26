"""Job status API endpoints: poll ingestion job progress and retry.

The stale-job recovery/sweep handlers split out into ``sweep.py`` (#1335);
this module keeps the job CRUD routes and re-exports what it imports from
there for backward compatibility.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.sqlstate import is_lock_conflict
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
from app.platform.jobs.ledger import Outcome, cancel, retry
from app.platform.jobs.models import (
    EMBEDDING_BACKFILL_METADATA_KEY,
    FAN_OUT_INTERRUPTED_METADATA_KEY,
    TERMINAL_STATUSES,
    URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY,
    IngestJob,
)
from app.platform.jobs.schemas import (
    DbfTruncationCollisionWarning,
    JobCancelResponse,
    JobStatusResponse,
    MercatorClipWarning,
    ReservedRenameWarning,
    StaleCleanupResponse,
)
from app.platform.jobs.staging_reconcile import reconcile_orphaned_staging_objects
from app.platform.jobs.sweep import (
    JOB_TIMEOUT_SECONDS,  # noqa: F401 -- re-exported, see __all__
    StaleCleanupOutcome,  # noqa: F401 -- re-exported, see __all__
    _RECHECK_TRANSFER_MARGIN_SECONDS,  # noqa: F401 -- re-exported, see __all__
    _reap_committed_staged_paths,
    _sweep_expired_presigned_staging,
    fail_stale_jobs,
    is_held_back,
    may_be_stale,
    post_expiry_sweep_after_seconds,  # noqa: F401 -- re-exported, see __all__
    publish_refresh_reconciliation,
    settle_stale_jobs,
    stale_pending_cutoff_seconds,  # noqa: F401 -- re-exported, see __all__
    sweep_stale_vrt_assets,  # noqa: F401 -- re-exported, see __all__
)
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import CONFLICT_RESPONSE, ERROR_RESPONSES_AUTH

log = structlog.get_logger()

# Contract: only these two keys may appear in temporal_parse_errors. The
# alias lets ``cast`` narrow dict writes without ruff F821 on Literal strings.
TemporalParseKey = Literal["temporal_start", "temporal_end"]

router = APIRouter(prefix="/jobs", tags=["Admin"], responses=ERROR_RESPONSES_AUTH)


async def _can_access_another_users_job(
    request: Request,
    db: AsyncSession,
    user: Identity,
    job: IngestJob,
    *,
    log_denial: bool = True,
) -> bool:
    """Delegate cross-user job access to the effective permission policy.

    Owner access is handled by callers before invoking this helper. Passing
    the job as ``resource`` lets enterprise extensions apply finer-grained
    policy instead of a hard-coded role-name check.

    ``log_denial`` (fix(#1709)): where this check decides alone
    (``get_job_status``, ``retry_job``), a refusal here IS the request's
    refusal and must be recorded. Where a later arm can still grant
    (cancel's dataset-write arm), logging here would file a denial on every
    SUCCESSFUL cancel — such callers pass ``log_denial=False`` and emit
    exactly one event once every arm has failed. Default True: a caller
    that forgets the flag over-reports rather than losing a denial silently.
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
    if not granted and log_denial:
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
            # tenant; the lifecycle helper opens a scoped transaction per
            # tenant and reaps each one's staged objects in context.
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
            # fix(#1277): this path passed commit=False, so the sweep
            # deferred its counter to the commit above; the fleet helper
            # (multi-tenant) already publishes its own per tenant.
            publish_refresh_reconciliation(outcome)
            outcome = await _reap_committed_staged_paths(outcome)
            outcome = await _sweep_expired_presigned_staging(db, outcome)
            # fix(#1249): same object-driven reconciliation the background
            # sweeper runs; the fleet helper (multi-tenant) already
            # reconciles per tenant.
            await reconcile_orphaned_staging_objects(db)
            from app.processing.ingest.publish_followups import (
                run_owed_publish_followups,
            )

            await run_owed_publish_followups()
            details = outcome.as_dict()
    except Exception as exc:  # broad: cleanup spans DB and artifact deletion
        await db.rollback()
        # Cleanup failures can embed local paths or storage keys in exception
        # messages; record only the exception class, and let the correlated
        # audit event carry a stable error code only.
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
    # outage must not turn that success into a retryable 500 or a
    # contradictory ``failed`` event; the phase marker is already durable.
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
    # Clients poll every few seconds. A job inside its lease costs no statement
    # here, and a stale one its queue or children still hold costs one read.
    if may_be_stale(job, now) and not await is_held_back(db, job):
        outcome = await settle_stale_jobs(db, now, job_ids=(job.id,))
        await db.commit()
        publish_refresh_reconciliation(outcome)
        # Only after the commit: a reap before it could delete what a
        # rolled-back settlement still owns.
        await _reap_committed_staged_paths(outcome)
        await db.refresh(job)

    # fix(#1860): this handler already refused non-creators without policy
    # access, so every caller here is entitled to the full payload.
    return await _job_to_status_response(job, include_detail=True)


# fix(#1710): the run of "this kind of job is not an ordinary import" checks,
# as an ORDERED table rather than a branch each — the chain had reached the
# complexity cap, and order is part of the contract (a service refresh job
# carries both `reupload` and `refresh` and must keep the reupload wording).
_UNREPLAYABLE_JOB_MARKERS: tuple[tuple[str, str], ...] = (
    (
        "reupload",
        "Dataset replacement jobs cannot be replayed as ordinary imports. "
        "Start the reupload again.",
    ),
    # feat(#1265): a registered-PostGIS refresh job carries no file/URL, so
    # without this it fell through to the import copy, telling the user their
    # "source" was gone.
    (
        "refresh",
        "Refresh runs cannot be replayed as imports. Refresh the dataset "
        "again from its source panel.",
    ),
    # fix(#1709): a fan-out parent whose dispatch crashed before any child was
    # queued. Generic retry would re-queue it as ONE default-layer import —
    # the layer selection was never persisted.
    (
        FAN_OUT_INTERRUPTED_METADATA_KEY,
        "Fan-out dispatch was interrupted before any layer was queued. "
        "Re-upload the file and select its layers again.",
    ),
    (
        "service_auth_required",
        "This service import requires fresh credentials. Start the import "
        "again to re-authenticate.",
    ),
    # ux(#698): analysis jobs carry file_path="" and are not replayable
    # anyway — the drawn clip mask is never persisted.
    (
        "analysis",
        "Analysis runs cannot be replayed as imports. Start the analysis "
        "again from the map builder.",
    ),
    # fix(#1542): restart via POST /admin/backfill-embeddings/, which re-runs
    # its own pre-flight and concurrency guards; retry would skip both.
    (
        EMBEDDING_BACKFILL_METADATA_KEY,
        "Embedding backfill runs cannot be replayed as imports. Start the "
        "backfill again from Settings.",
    ),
    # fix(#1814): generic retry's failed -> pending CAS skips the manifest
    # key's advisory lock, risking a second job for a key a re-apply claims.
    (
        "manifest_key",
        "Manifest imports cannot be replayed here. Apply the manifest again, "
        "which is what serializes work on its own keys.",
    ),
    # fix(#1710): file_path is a download destination the worker never
    # finished. A truncated CSV or GeoJSON still parses, so replaying it would
    # import an incomplete dataset as a complete one.
    (
        URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY,
        "The download did not finish, so the file is incomplete. Start the "
        "import again.",
    ),
)


async def _retry_capability(job: IngestJob) -> tuple[bool, str | None]:
    if job.status != "failed":
        return False, None
    metadata = job.user_metadata or {}
    for marker, reason in _UNREPLAYABLE_JOB_MARKERS:
        if metadata.get(marker):
            return False, reason
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


def _redacted_job_status(job: IngestJob) -> JobStatusResponse:
    """The job payload for a reader with no claim on the job itself.

    fix(#1860): ``GET /jobs/by-dataset/{dataset_id}`` gated on the DATASET
    being visible but returned the whole job row, leaking another user's
    failure text and upload filename to any reader of a public/internal
    dataset. This projection applies the same provenance rule
    ``list_dataset_refresh_runs`` already applies, decided field by field.

    Kept (refresh-runs publishes the same fact to the same audience):

    - ``id``: not a capability — read/retry/cancel are owner-or-policy, and
      refresh-runs already publishes ``ingest_job_id``.
    - ``status``: refresh-runs publishes it unredacted.
    - ``dataset_id``: the caller supplied it in the path.
    - ``started_at`` / ``completed_at`` / ``created_at``: refresh-runs
      publishes its own three timestamps unredacted.

    Redacted (each says who ran the job or what was in the data):

    - ``source_filename``: STRICTER than the dataset's own published
      filename (``dataset_to_response`` publishes ``Dataset.source_filename``
      to any reader; ``list_dataset_versions`` publishes it per-version too)
      because a FAILED run's filename never reaches the dataset row — this
      is the only door it reaches a stranger through. Nulled unconditionally
      so the rule stays decidable from the job row alone.
    - ``error_message`` / ``error_code``: the fields refresh-runs redacts by
      name.
    - ``warning_message`` / ``warnings``: name source columns, including
      ORIGINAL names a renaming ingest never publishes (the ``schema_diff``
      class).
    - ``current_step``: names an ingest-toolchain step, past what ``status``
      already says.
    - ``rows_processed`` / ``rows_failed``: redacted as a pair — one without
      the other reads as full coverage for a run that dropped rows.
    - ``archive_failed``: an internal storage outcome.
    - ``temporal_parse_errors``: values are unparsed cell text from the
      source data.
    - ``can_retry`` / ``retry_reason``: retry is owner-or-policy, so
      ``False`` is the honest answer here, not a concealment; also spares a
      storage round trip this caller cannot act on.
    """
    return JobStatusResponse(
        id=job.id,
        status=job.status,
        dataset_id=job.dataset_id,
        source_filename=None,
        error_message=None,
        error_code=None,
        can_retry=False,
        retry_reason=None,
        warning_message=None,
        warnings=[],
        progress=None,
        current_step=None,
        rows_processed=None,
        rows_failed=None,
        archive_failed=False,
        temporal_parse_errors={},
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


async def _job_to_status_response(
    job: IngestJob, *, include_detail: bool
) -> JobStatusResponse:
    """Extract warnings + structured metadata from ``user_metadata`` (S3/TYPE-2).

    Shared by ``get_job_status`` and ``get_job_status_by_dataset`` so the
    warning-parse contract lives in one place.

    ``include_detail`` is keyword-only with no default: every call site must
    settle who is reading before serializing a job. True yields the full
    payload, False the redacted projection on ``_redacted_job_status``. A
    default here is how this endpoint became a third unguarded door (#1860).

    Warnings validate through the ``IngestJobWarning`` discriminated union;
    a malformed entry (unknown ``kind``, missing fields) is logged and
    dropped so a stale producer can't break the whole endpoint.
    """
    if not include_detail:
        return _redacted_job_status(job)

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
            # Narrow to the contract keys — drop unknown ones so Pydantic's
            # Literal validation can't reject the whole response on a stale
            # producer. `cast` makes the narrowing explicit to mypy.
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
        error_code=job.error_code,
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

    Not every caller gets every field. Seeing the dataset decides whether there
    is an answer at all; who ran the job decides how much of the answer is
    filled in. The dataset's owner, an admin, and the job's own creator get the
    full payload. Any other reader of a visible dataset gets the job id, its
    status and its timestamps, with the run's own detail nulled: no
    ``error_message``, ``source_filename``, warnings, step, row counts or
    retry hint. That is the redaction ``GET /datasets/{dataset_id}/refresh-runs``
    already applies to the same failure text, and ``_redacted_job_status``
    documents the decision field by field.
    """
    # Visibility check: reuse the dataset detail permission so only users
    # who can see the dataset can see the job; avoids leaking existence via
    # 403 vs 404 divergence.
    from app.modules.catalog.authorization import (
        apply_visibility_filter,
        can_view_dataset_provenance,
        get_user_roles,
    )
    from app.modules.catalog.datasets.domain.models import (
        Dataset,
        DatasetGrant,
        Record,
    )

    user_roles = await get_user_roles(db, user)
    # fix(#1860): selects the Record, not Dataset.id, because the provenance
    # predicate reads it — stays correct if that predicate needs a second field.
    dataset_stmt = (
        select(Record)
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    dataset_stmt = apply_visibility_filter(
        dataset_stmt, user, user_roles, Record, DatasetGrant
    )
    record = (await db.execute(dataset_stmt)).scalar_one_or_none()
    if record is None:
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
        # Dataset visible but has no ingest job (remote/STAC/registered
        # dataset). 200 + null, not 404, so the detail page treats it as
        # "no warnings" without a console 404.
        return None

    # fix(#1860): the gate above is a VISIBILITY check — it says nothing
    # about whose job row this is. The creator keeps the full payload (it's
    # their run, and the import flow polls this route); everyone else goes
    # through the same provenance predicate ``list_dataset_refresh_runs``
    # applies to this text.
    include_detail = job.created_by == user.id or can_view_dataset_provenance(
        record, user, user_roles
    )
    return await _job_to_status_response(job, include_detail=include_detail)


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
    if await retry(db, job) is not Outcome.LANDED:
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
                "next_attempt_id": str(job.attempt_id),
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


# SQL to find the live Procrastinate row(s) for one ingest job — same
# args->>'job_id' correlation the sweeps use. At most one row is live in
# practice; a retried job's old row is terminal and excluded here.
_LIVE_QUEUE_ROWS_SQL = text(
    "SELECT id FROM catalog.procrastinate_jobs"
    " WHERE args->>'job_id' = :job_id AND status IN ('todo', 'doing')"
)


def _is_lock_conflict(exc: DBAPIError) -> bool:
    """True for PostgreSQL 55P03 (lock timeout) or 40P01 (deadlock victim).

    Both mean another transaction owns rows this cancel needs, and both are
    safe to report as a retryable 409: nothing was written. 40P01 should be
    unreachable now that cancel takes locks in the worker's own order (see
    ``cancel_job``, fix(#1709)), but mapping it costs one tuple
    member and turns a future ordering regression into a 409, not a 500.

    fix(#1847): moved to ``app.core.db.sqlstate`` for a third caller — a
    rename, not a policy change.
    """
    return is_lock_conflict(exc)


async def _may_cancel_job(
    request: Request,
    db: AsyncSession,
    user: Identity,
    job: IngestJob,
) -> bool:
    """The three authorization arms for cancel (#1677 design §3).

    Arm 1: owners always retain access. Arm 2: the effective cross-user
    capability policy (same as view/retry). Arm 3: dataset write access —
    ``check_dataset_write_access`` raises 404 (not visible) or 403 (visible,
    not owner/admin); the caller's generic 403 avoids leaking visibility.

    fix(#1709): arm 2 runs as a SILENT probe — a losing arm is
    not a denial when a later arm grants (arm 3, for a dataset owner
    cancelling a refresh an admin triggered). The denial fires once, below,
    only after every arm fails; arm 3 emits no telemetry of its own, so the
    deny path's event count stays exactly one.
    """
    from app.modules.auth.dependencies import (
        get_cached_user_roles,
        log_permission_denial,
    )

    if job.created_by == user.id:
        return True
    if await _can_access_another_users_job(request, db, user, job, log_denial=False):
        return True
    if job.dataset_id is not None:
        from app.modules.catalog.authorization import check_dataset_write_access
        from app.modules.catalog.datasets.domain.service import get_dataset

        dataset = await get_dataset(db, job.dataset_id)
        try:
            await check_dataset_write_access(db, dataset, job.dataset_id, user)
            return True
        except HTTPException:
            pass

    # Every arm failed: a real denial, the only one. `get_cached_user_roles`
    # is request-cached, so arm 2 already paid for this read.
    log_permission_denial(
        request,
        user,
        "manage_users",
        await get_cached_user_roles(request, db, user),
        resource_type="ingest_job",
    )
    return False


@router.post(
    "/{job_id}/cancel",
    response_model=JobCancelResponse,
    responses={409: CONFLICT_RESPONSE},
)
async def cancel_job(
    job_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> JobCancelResponse:
    """Cancel a pending or running ingest job.

    The database marks the job and any bound refresh run as cancelled before
    requesting a queue abort. Transaction fencing prevents a worker from
    installing data after cancellation even if it misses the abort request.

    The job creator, a user with cross-user job permission, or anyone with
    write access to the job's dataset may cancel it.
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

    if not await _may_cancel_job(request, db, user, job):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to cancel this job",
        )

    if job.status == "cancelled":
        return JobCancelResponse(
            id=job.id, status="cancelled", run_id=None, already=True
        )
    # `cancelled` is answered above as the idempotent repeat, so a terminal
    # status here is "too late".
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "job_already_finished", "status": job.status},
        )

    # One transaction: the ledger's fenced cancel, which ends the job's linked
    # rows with it, and this request's audit event, then commit. The ledger's
    # 2 s lock_timeout covers the audit write too.
    previous_attempt_id = job.attempt_id
    try:
        ended = await cancel(db, job, actor=user.id)
        if ended.outcome is not Outcome.LANDED:
            # Another actor moved the row between the read and the CAS.
            # Report what it became; nothing was written.
            await db.rollback()
            await db.refresh(job)
            if job.status == "cancelled":
                return JobCancelResponse(
                    id=job.id, status="cancelled", run_id=None, already=True
                )
            code = (
                "job_already_finished"
                if job.status in TERMINAL_STATUSES
                # Still active under a different attempt id: retried
                # concurrently — a cancel on the old attempt must not kill
                # the new one.
                else "job_conflict"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": code, "status": job.status},
            )

        run_id = ended.linked.get("run")
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="job.cancel",
                resource_type="ingest_job",
                resource_id=job.id,
                details={
                    "job_owner_id": (
                        str(job.created_by) if job.created_by is not None else None
                    ),
                    "attempt_id": (
                        str(previous_attempt_id)
                        if previous_attempt_id is not None
                        else None
                    ),
                    "run_id": str(run_id) if run_id is not None else None,
                    "cross_user": job.created_by != user.id,
                },
                ip_address=get_client_ip(request),
            ),
        )
    except DBAPIError as exc:
        if not _is_lock_conflict(exc):
            raise
        await db.rollback()
        # A finalize transaction owns rows this cancel needs; nothing was
        # written. The client may retry and will then get `job_already_finished`.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "job_finishing"},
        ) from exc
    await db.commit()

    # Post-commit, best-effort: ask Procrastinate to cancel a todo row or
    # abort a doing one. Any failure past the commit — row lookup included
    # (fix(#1709): a dropped connection here used to 500 an
    # already-durable cancel) — is logged, not surfaced: the fences above
    # make delivery a no-op either way.
    try:
        queue_rows = await db.execute(_LIVE_QUEUE_ROWS_SQL, {"job_id": str(job.id)})
        queue_job_ids = list(queue_rows.scalars())
    except Exception:  # broad: post-commit lookup is acceleration, never the guarantee
        log.warning(
            "job_cancel_queue_lookup_failed",
            job_id=str(job.id),
            exc_info=True,
        )
        queue_job_ids = []
    for queue_job_id in queue_job_ids:
        try:
            # Deferred: the API process holds this connector open for its
            # whole lifespan (app/api/main.py lifespan).
            from app.processing.ingest.tasks import task_app

            await task_app.job_manager.cancel_job_by_id_async(queue_job_id, abort=True)
        except Exception:  # broad: queue abort is acceleration, never the guarantee
            log.warning(
                "job_cancel_queue_abort_failed",
                job_id=str(job.id),
                queue_job_id=queue_job_id,
                exc_info=True,
            )

    return JobCancelResponse(id=job.id, status="cancelled", run_id=run_id)


__all__ = [
    "JOB_TIMEOUT_SECONDS",
    "StaleCleanupOutcome",
    "TemporalParseKey",
    "_RECHECK_TRANSFER_MARGIN_SECONDS",
    "fail_stale_jobs",
    "get_retry_capability",
    "post_expiry_sweep_after_seconds",
    "router",
    "stale_pending_cutoff_seconds",
    "sweep_stale_vrt_assets",
]
