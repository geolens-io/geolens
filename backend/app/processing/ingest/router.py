"""Ingest API endpoints: file upload, preview, commit, and table registration."""

import asyncio
import math
import uuid
from datetime import datetime, timezone

import structlog
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

if TYPE_CHECKING:
    from app.platform.jobs.models import IngestJob
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import unknown_srid_refusal
from app.core.identity import Identity
from app.core.async_io import (
    run_in_thread_draining,
    run_in_thread_draining_capture_cancel,
)
from app.modules.auth.dependencies import (
    get_current_active_user,
    require_mode_permission,
    require_permission,
)
from app.core.config import settings
from app.core.db.tenant_session import defer_async_with_tenant
from app.core.dependencies import get_db
from app.core.pointcloud import POINTCLOUD_FILE_TYPE
from app.core.tiles3d import TILESET_FILE_TYPE
from app.processing.ingest.layer_guard import (
    known_layer_names as known_layer_names_for,
    reject_option_like_layer_name,
    validate_commit_layer_name,
)
from app.processing.ingest.ogr import (
    IngestBudgetExceededError,
    IngestionError,
    detect_geometry_columns,
    run_ogrinfo_preview,
)
from app.processing.ingest.schemas import (
    BaseCommitRequest,
    BulkRegisterItem,
    BulkRegisterRequest,
    BulkRegisterResponse,
    BulkRegisterResult,
    CommitRequest,
    CommitResponse,
    DiscoverResponse,
    FanOutCommitRequest,
    FanOutCommitResponse,
    PointCloudCommitRequest,
    PreviewResponse,
    PresignedCompleteRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
    RasterCommitRequest,
    RasterPreviewResponse,
    RegisterRequest,
    ServiceCommitRequest,
    StagedPreviewResponse,
    TableRegisterResponse,
    TilesetCommitRequest,
    UPLOAD_KIND_DESCRIPTION,
    UploadConfigResponse,
    UploadResponse,
    VectorCommitRequest,
    VrtAddSourceRequest,
    VrtCreateRequest,
    VrtCreateResponse,
    VrtMutationResponse,
)
from app.processing.ingest.service import (
    PART_SIZE,
    _assert_commit_credential_dispatchable,
    _cleanup_saved_upload,
    admit_import_commit,
    claim_fan_out_parent,
    create_fan_out_jobs,
    create_ingest_job,
    discover_unregistered_tables,
    job_service_format,
    raster_stamped_metadata,
    record_preview_layers,
    restore_fan_out_parent_pending,
    get_job_or_404,
    queue_ingest_job,
    register_existing_table,
    registration_failure_reason,
    resolve_file_path,
    save_upload_file,
    validate_file_extension,
)
from app.processing.ingest.upload_limits import build_upload_config
from app.processing.ingest.presigned import (
    abort_presigned_multipart_upload,
    admit_presigned_pointcloud,
    admit_presigned_tileset,
    finalize_presigned_object,
    lock_presigned_job,
    require_completable_presigned_job,
    require_signable_job_lifetime,
    should_assemble_multipart,
    sign_url_with_deadline,
)
from app.processing.ingest.pointcloud import (
    preview_staged_pointcloud,
    require_pointcloud_file,
    staged_pointcloud_bytes,
    staged_pointcloud_metadata,
)
from app.processing.ingest.tasks import regenerate_vrt_staged
from app.processing.ingest.vrt_admission import stage_vrt_regeneration
from app.processing.ingest.tileset import (
    TILESET_UNPACKED_BYTES_FIELD,
    preview_staged_tileset,
    require_tileset_archive,
    staged_tileset_metadata,
    staged_unpacked_bytes,
)
from app.core.upload_errors import CodedRefusal, refusal_detail
from app.processing.ingest.validation import (
    UnsafeUploadError,
    validate_file_content,
)
from app.platform.catalog_locks import admit_vrt_mutation
from app.platform.jobs.defer_guard import (
    DeferFailed,
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs import ledger
from app.platform.dataset_origin import PORTAL_LINK_KEYS
from app.platform.portal_link import (
    PortalLink,
    resolve_portal_link,
)
from app.core.persistent_config import (
    UPLOAD_MAX_SIZE_MB,
    get_allowed_extensions_list,
)
from app.modules.quota.service import check_upload_quota, remaining_dataset_quota
from app.modules.quota.service import DatasetQuotaExceededError
from app.processing.raster.validation import validate_sources_async
from app.platform.service_auth import (
    credential_or_422,
    service_credential_from_request,
)
from app.platform.storage import get_storage
from app.platform.upload_filenames import (
    refuse_control_characters,
    safe_upload_basename,
)
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    ERROR_RESPONSES_WRITE,
    FORBIDDEN_RESPONSE,
    PAYLOAD_TOO_LARGE_RESPONSE,
)

logger = structlog.get_logger(__name__)

# Each bulk-register item holds a pooled connection while it runs.
_BULK_REGISTER_CONCURRENCY = 4

# A table in the data schema has no owner until it is registered, so only an
# administrator may list, claim or alter one.
require_table_registrar = require_mode_permission(
    single_tenant="manage_settings", multi_tenant="manage_tenants"
)

router = APIRouter(
    prefix="/ingest",
    tags=["Datasets"],
    responses=ERROR_RESPONSES_WRITE,
)


def _fallback_allowed_extensions() -> list[str]:
    """Allowed extensions when the persistent_config DB lookup fails.

    Read from ``settings``, not a frozen literal, so the fallback accepts
    every format the settings allow.
    """
    return list(settings.allowed_extensions_list)


def _reject_standalone_vrt(filename: str) -> None:
    """Reject a raw VRT XML upload; unlike one GeoLens builds, it has no catalog-tracked sources and may carry external paths."""
    if Path(filename).suffix.lower() == ".vrt":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "standalone_vrt_not_supported",
                "message": (
                    "Standalone VRT uploads are not supported. Create a managed "
                    "VRT from existing raster datasets instead."
                ),
            },
        )


async def _get_allowed_extensions_safely(db: AsyncSession) -> list[str]:
    """Load allowed upload extensions with a DB-failure fallback.

    A transient DB error during the lookup must not fail the upload
    endpoint with a 500, so this falls back to the settings list and logs
    the failure for operators.
    """
    try:
        return await get_allowed_extensions_list(db)
    except Exception as exc:  # broad: persistent_config lookup must not crash uploads; fall back to safe default list
        logger.warning(
            "Failed to load allowed extensions from persistent_config — using fallback",
            error=str(exc),
        )
        return _fallback_allowed_extensions()


async def _refuse_upload(db: AsyncSession, filename: str, kind: str | None) -> None:
    """Refuse a standalone VRT, a disallowed extension, or a mismatched upload kind."""
    _reject_standalone_vrt(filename)
    try:
        # Ahead of the allowed list, so a .las sent as a point cloud gets the hint.
        require_pointcloud_file(kind, filename)
    except UnsafeUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=refusal_detail(exc),
        ) from exc
    allowed_list = await _get_allowed_extensions_safely(db)
    try:
        validate_file_extension(filename, allowed_list)
    except CodedRefusal as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=refusal_detail(exc)
        ) from exc
    try:
        require_tileset_archive(kind, filename)
    except UnsafeUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=refusal_detail(exc),
        ) from exc


@router.get(
    "/upload/config",
    response_model=UploadConfigResponse,
    responses={403: FORBIDDEN_RESPONSE},
)
async def get_upload_config(
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UploadConfigResponse:
    """Return upload configuration including presigned upload availability."""
    return await build_upload_config(db, await remaining_dataset_quota(db, user.id))


@router.post(
    "/upload/presigned",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
)
async def request_presigned_upload(
    request: PresignedUploadRequest,
    http_request: Request,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> PresignedUploadResponse:
    """Request presigned URL(s) for direct-to-S3 file upload."""
    if settings.storage_provider != "s3":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Presigned uploads only available in S3 mode",
        )

    refuse_control_characters(request.filename)
    staged_name = safe_upload_basename(request.filename)
    await _refuse_upload(db, request.filename, request.kind)

    # Reject files exceeding configured size limit at request time
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    max_size_bytes = max_size_mb * 1024 * 1024
    if request.file_size > max_size_bytes:
        size_mb = round(request.file_size / (1024 * 1024), 1)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "file_size_exceeded",
                "message": (
                    f"File size ({size_mb} MB) exceeds the maximum allowed "
                    f"({max_size_mb} MB)."
                ),
                "size_mb": size_mb,
                "limit_mb": max_size_mb,
            },
        )

    await check_upload_quota(db, user.id, request.file_size, http_request)

    job = await create_ingest_job(db, request.filename, "", user.id)
    storage = get_storage()
    s3_key = f"staging/{job.id}/{staged_name}"
    physical_s3_key = resolve_current_storage_key(s3_key)
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024
    # Gate only, return discarded — refuses a dead-lifetime job
    # before an upload id is initiated; each URL still computes its own
    # expiration inside the signing thread.
    require_signable_job_lifetime(job.created_at)

    if request.file_size > threshold:
        upload_id: str | None = None
        try:
            upload_id, initiation_cancel = await run_in_thread_draining_capture_cancel(
                storage.initiate_multipart_upload,
                physical_s3_key,
                request.content_type,
            )
            if initiation_cancel is not None:
                raise initiation_cancel
            num_parts = math.ceil(request.file_size / PART_SIZE)
            urls = [
                # Each part's expiration is computed INSIDE the
                # signing thread — see `sign_url_with_deadline` for why the
                # two must stay adjacent.
                await run_in_thread_draining(
                    sign_url_with_deadline,
                    storage.generate_presigned_part_url,
                    job.created_at,
                    physical_s3_key,
                    upload_id,
                    part_num,
                )
                for part_num in range(1, num_parts + 1)
            ]
        except BaseException as exc:
            if upload_id is not None:
                await abort_presigned_multipart_upload(
                    storage,
                    key=physical_s3_key,
                    upload_id=upload_id,
                    job_id=job.id,
                )
            # An HTTPException here is the lifetime refusal and
            # must survive as its own 409, not get remapped to "Storage
            # service unavailable" — the abort above already ran.
            if isinstance(exc, (asyncio.CancelledError, HTTPException)):
                raise
            logger.exception("presigned_multipart_failed", s3_key=s3_key)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Storage service unavailable",
            ) from exc
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "upload_id": upload_id,
            "multipart": True,
            "expected_size": request.file_size,
            **({"file_type": request.kind} if request.kind else {}),
        }
        try:
            await db.commit()
        except BaseException:
            await abort_presigned_multipart_upload(
                storage,
                key=physical_s3_key,
                upload_id=upload_id,
                job_id=job.id,
            )
            raise
        return PresignedUploadResponse(
            job_id=job.id,
            urls=urls,
            s3_key=physical_s3_key,
            upload_id=upload_id,
            part_size=PART_SIZE,
        )
    else:
        try:
            url = await run_in_thread_draining(
                sign_url_with_deadline,
                storage.generate_presigned_put_url,
                job.created_at,  # expires with the job, not 3600s from now
                physical_s3_key,
                request.content_type,
            )
        except (
            Exception
        ) as exc:  # broad: S3/MinIO presign-put can throw varied SDK errors; map to 502
            # HTTPException passthrough here too — signing happens
            # in the thread, so the lifetime refusal raises through
            # this path and must not become "Storage service unavailable".
            if isinstance(exc, HTTPException):
                raise
            logger.exception("presigned_put_failed", s3_key=s3_key)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Storage service unavailable",
            ) from exc
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "multipart": False,
            "expected_size": request.file_size,
            **({"file_type": request.kind} if request.kind else {}),
        }
        await db.commit()
        return PresignedUploadResponse(
            job_id=job.id,
            urls=[url],
            s3_key=physical_s3_key,
        )


@router.post(
    "/upload/presigned/{job_id}/complete",
    response_model=UploadResponse,
    responses={
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
)
async def complete_presigned_upload(
    job_id: uuid.UUID,
    request: PresignedCompleteRequest,
    http_request: Request,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Notify that direct-to-S3 upload is complete."""
    job = await get_job_or_404(db, job_id, user)
    job = await lock_presigned_job(db, job_id)
    um = job.user_metadata or {}

    if not um.get("presigned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is not a presigned upload",
        )

    # An abandoned presigned upload is marked failed by the
    # stale-pending reaper after an hour, the same hour its PUT URL stays
    # valid — this door can reach the terminal-job case without stamping it.
    require_completable_presigned_job(job, restart_hint="Start a new upload.")

    storage = get_storage()
    s3_key = um["s3_key"]
    physical_s3_key = resolve_current_storage_key(s3_key)

    # Skip assembly when it already happened — the staging object
    # exists IFF CompleteMultipartUpload succeeded, so its presence alone is a
    # sound record, and a retry can't re-call complete with a SPENT upload id.
    # The parts-required 400 is skipped with it: a retrying client has nothing
    # left to resend.
    if await should_assemble_multipart(storage, um, physical_s3_key):
        if not request.parts:
            await abort_presigned_multipart_upload(
                storage,
                key=physical_s3_key,
                upload_id=um.get("upload_id"),
                job_id=job.id,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multipart upload completion requires at least one uploaded part",
            )
        try:
            _, completion_cancel = await run_in_thread_draining_capture_cancel(
                storage.complete_multipart_upload,
                physical_s3_key,
                um["upload_id"],
                [{"ETag": p.etag, "PartNumber": p.part_number} for p in request.parts],
            )
            if completion_cancel is not None:
                # Do NOT delete the assembled object — its
                # presence is the only record assembly succeeded (the upload
                # id is spent); `should_assemble_multipart` relies on it for retries.
                raise completion_cancel
        except Exception as exc:  # broad: S3/MinIO multipart-complete can throw varied SDK errors; map to 502
            await abort_presigned_multipart_upload(
                storage,
                key=physical_s3_key,
                upload_id=um.get("upload_id"),
                job_id=job.id,
            )
            logger.exception(
                "multipart_upload_completion_failed",
                job_id=str(job.id),
                s3_key=s3_key,
                part_count=len(request.parts),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upload completion failed — the upload session may have expired. Please try again.",
            ) from exc

    # Completion contract (exists check, size gate, drained
    # freeze, content validation) shared with the reupload door so the two
    # cannot drift — see the docstring for postconditions.
    frozen_key = await finalize_presigned_object(
        db=db,
        storage=storage,
        job_id=job.id,
        logical_key=s3_key,
        expected_size=um.get("expected_size"),
        filename=job.source_filename or "",
        user_id=user.id,
        request=http_request,
    )
    if um.get("file_type") == TILESET_FILE_TYPE:
        await admit_presigned_tileset(
            db,
            storage,
            job,
            frozen_key=frozen_key,
            user_id=user.id,
            request=http_request,
        )
    if um.get("file_type") == POINTCLOUD_FILE_TYPE:
        await admit_presigned_pointcloud(storage, job, frozen_key=frozen_key)

    job.file_path = frozen_key
    # The presigned path must stamp file_type — on S3 every
    # upload goes through it, so without it every GeoTIFF would fall through
    # to the vector branch (422 at preview, wrong commit dispatch).
    _stamp_raster_metadata(job, job.source_filename)
    await db.commit()

    # Delete AFTER commit, never before — deleting first would leave a
    # failed commit with the staging object already gone and the frozen copy
    # orphaned. Swept later by reapers resolving the key via
    # `owned_presigned_staging_key`.
    # S3 cannot revoke a presigned URL, so reaping is the only remedy; the purge
    # is a backstop that exempts the newest complete job.
    await _cleanup_saved_upload(s3_key, str(job.id))

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded and ready for preview",
    )


def _pending_upload_update(job_id: uuid.UUID):
    """An UPDATE that matches the upload's job only while it is still pending.

    Every write after the row is committed goes through this guard, so a row
    the sweep reclaimed keeps its verdict and the caller learns that from a
    zero rowcount.
    """
    from sqlalchemy import update as sa_update

    from app.platform.jobs.models import IngestJob

    return sa_update(IngestJob).where(
        IngestJob.id == job_id, IngestJob.status == "pending"
    )


def _stamp_raster_metadata(job: "IngestJob", filename: str | None) -> None:
    """Stamp ``user_metadata["file_type"] = "raster"`` from the filename.

    ``file_type`` is the raster discriminator for three consumers — the
    preview branch below, ``_pick_commit_subclass``, and the ingest dispatch
    in ``queue_ingest_job`` — so every upload endpoint has to set it before
    the job is previewable or committable.

    The stamp does no I/O. It does not download the object or run
    ``validate_raster_crs``, which a presigned completion cannot afford:
    presigned uploads exist for the multi-GB case, and preview downloads
    the same object seconds later anyway. ``ingest_raster`` reads the
    CRS from the raster's own metadata rather than from anything stamped
    here, so nothing is lost by skipping the check. Both upload
    endpoints can therefore afford the stamp, including a presigned
    completion request.
    """
    job.user_metadata = raster_stamped_metadata(job.user_metadata, filename)


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={413: PAYLOAD_TOO_LARGE_RESPONSE},
)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
    # A pattern, not a Literal: the generated Python SDK cannot put a nullable
    # Literal into a multipart body.
    kind: str | None = Form(
        None, pattern="^(tiles3d|pointcloud)$", description=UPLOAD_KIND_DESCRIPTION
    ),
) -> UploadResponse:
    """Upload a geospatial file for staging.

    Validates the file extension, creates an ingest job, and saves the file
    to staging. Does NOT auto-queue ingestion -- use preview then commit.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "missing_filename", "message": "Upload missing filename"},
        )
    try:
        await _refuse_upload(db, file.filename, kind)

        # Enforce max_file_size_bytes at HTTP entry, as the presigned
        # path does at request time.
        max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
        max_size_bytes = max_size_mb * 1024 * 1024

        # Per-user quota check before any staging or job creation.
        incoming_bytes = file.size if file.size is not None else 0
        await check_upload_quota(db, user.id, incoming_bytes, request)

        job = await create_ingest_job(db, file.filename, "", user.id)
        job_id = job.id
        job_metadata = job.user_metadata
        # Committed BEFORE the spooled body is staged, so no pooled
        # connection is held across the staging copy or put, the validation
        # download and the content sniff; a failed staging leaves it for the sweep.
        await db.commit()
        saved_path = await save_upload_file(
            file, str(job_id), max_size_bytes=max_size_bytes
        )
        validation_path = str(saved_path)
        downloaded_validation_path: Path | None = None
        try:
            if not isinstance(saved_path, Path):
                validation_path = await resolve_file_path(saved_path, str(job_id))
                downloaded_validation_path = Path(validation_path)

            # Inline content validation for immediate feedback.
            try:
                validate_file_content(validation_path, file.filename)
                kind_metadata = await staged_tileset_metadata(validation_path, kind)
                kind_metadata |= await staged_pointcloud_metadata(validation_path, kind)
            except ValueError as exc:
                # Fenced like the bind below, so a row the sweep already
                # reclaimed keeps its terminal status and message.
                await ledger.abort(db, job, code="content_rejected", reason=exc)
                await db.commit()
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=refusal_detail(exc),
                ) from exc
            if TILESET_UNPACKED_BYTES_FIELD in kind_metadata:
                await check_upload_quota(
                    db, user.id, kind_metadata[TILESET_UNPACKED_BYTES_FIELD], request
                )

            # Bind only while the row is still pending, stamping
            # `staged_at` so the pending window restarts here rather than at
            # creation, which the upload itself has already spent.
            bound = await db.execute(
                _pending_upload_update(job_id).values(
                    file_path=str(saved_path),
                    user_metadata={
                        **(raster_stamped_metadata(job_metadata, file.filename) or {}),
                        **kind_metadata,
                        "staged_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            )
            await db.commit()
            if not bound.rowcount:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This upload could not be attached to its job. It may "
                        "have taken too long, or the job may have been "
                        "cancelled. Upload the file again."
                    ),
                )
        except BaseException:
            # The request owns the staged source until the bind
            # lands, so every failure before it deletes the file; the row
            # itself stays for the sweep or carries the refusal above.
            await _cleanup_saved_upload(saved_path, str(job_id))
            raise
        finally:
            if downloaded_validation_path is not None:
                downloaded_validation_path.unlink(missing_ok=True)

        return UploadResponse(
            job_id=job_id,
            status="pending",
            message="File uploaded and ready for preview",
        )
    # HTTPException must be caught and re-raised before the bare
    # `except Exception` below, or a deliberate 4xx from a
    # downstream helper is rewritten as a generic 500.
    except HTTPException:
        raise
    except (IngestionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception:  # broad: upload pipeline involves file I/O, S3, DB, content validation — any can throw
        logger.exception(
            "Unexpected error during file upload",
            filename=file.filename,
            content_type=file.content_type,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during upload",
        )


async def _preview_raster(
    job: "IngestJob", file_path: str, downloaded_preview_path: Path | None
) -> RasterPreviewResponse:
    """Read a staged raster's metadata and COG compliance for the preview."""
    from app.processing.raster import probe

    file_size: int | None = None
    try:
        inspection = await asyncio.to_thread(
            probe.inspect_raster, file_path, timeout=probe.PREVIEW_TIMEOUT_SECONDS
        )
        try:
            import os

            file_size = os.path.getsize(file_path)
        except OSError:
            pass
    except Exception as exc:  # broad: any failed probe is a failed preview
        kind = exc.kind if isinstance(exc, probe.RasterProbeError) else None
        logger.warning("raster_preview failed", job_id=str(job.id), kind=kind)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "raster_preview_failed",
                "message": str(exc)
                if kind in ("timeout", "internal")
                else "Unable to preview raster file. The file may be malformed or unsupported.",
            },
        )
    finally:
        if downloaded_preview_path is not None:
            downloaded_preview_path.unlink(missing_ok=True)

    meta = inspection["metadata"]
    compliant, reason = inspection["compliant"], inspection["compliance_reason"]
    nodata = meta.get("nodata")
    return RasterPreviewResponse(
        job_id=job.id,
        source_filename=job.source_filename,
        crs_epsg=meta.get("epsg"),
        crs_wkt=meta.get("crs_wkt"),
        band_count=meta["band_count"],
        width=meta["width"],
        height=meta["height"],
        dtype=meta["dtype"],
        nodata=nodata,
        res_x=meta["res_x"],
        res_y=meta["res_y"],
        compression=meta.get("compression"),
        file_size_bytes=file_size,
        is_cog_compliant=compliant,
        compliance_reason=reason,
        temporal_start=meta.get("temporal_start"),
    )


@router.post(
    "/preview/{job_id}",
    response_model=StagedPreviewResponse,
)
async def preview_file(
    job_id: uuid.UUID,
    layer_name: str | None = Query(
        None, description="Sheet/layer name for multi-layer files"
    ),
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> StagedPreviewResponse:
    """Run preview on a staged file and return preview data.

    For vector files: returns columns, CRS, geometry type, feature count, sample rows.
    For raster files: returns band count, CRS, resolution, compliance status.
    For a 3D Tiles tileset: returns its version, root geometric error, bounding
    volume kind, extent and unpacked size, read from the archive's directory
    and tileset.json without unpacking it.
    For a COPC point cloud: returns its point count and format, CRS, extent,
    elevation range and size, read from its header and hierarchy.
    Only callable on jobs with status 'pending'.
    """
    # layer_name reaches ogrinfo argv; 422 option-like values.
    reject_option_like_layer_name(layer_name)

    job = await get_job_or_404(db, job_id, user)

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # A presigned upload has no file until its completion lands.
    if not job.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no associated file — upload must complete before preview",
        )
    file_type = (job.user_metadata or {}).get("file_type")
    try:
        if file_type == TILESET_FILE_TYPE:
            return await preview_staged_tileset(
                job.id, job.source_filename, job.file_path
            )
        if file_type == POINTCLOUD_FILE_TYPE:
            return await preview_staged_pointcloud(
                job.id, job.source_filename, job.file_path
            )
    except UnsafeUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=refusal_detail(exc),
        ) from exc
    file_path: str = job.file_path
    downloaded_preview_path: Path | None = None
    resolved_file_path = await resolve_file_path(file_path, str(job.id))
    if resolved_file_path != file_path:
        file_path = resolved_file_path
        downloaded_preview_path = Path(file_path)

    # Branch: raster vs vector preview
    um = job.user_metadata or {}
    if um.get("file_type") == "raster":
        return await _preview_raster(job, file_path, downloaded_preview_path)

    try:
        info = await run_ogrinfo_preview(file_path, layer_name=layer_name)
    except IngestBudgetExceededError as exc:
        # The ceiling message is server-authored and actionable —
        # falling through to the generic handler would call an oversized
        # file "malformed or unsupported" when it's merely too large.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=refusal_detail(exc),
        )
    except UnsafeUploadError as exc:
        # A server-authored refusal naming what was blocked and what to upload
        # instead: a presigned upload's first whole-file check, since the
        # presign door only sees a header probe.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=refusal_detail(exc),
        )
    except Exception as exc:  # broad: GDAL subprocess can raise various errors on unsupported/malformed files
        logger.exception("ogrinfo_preview failed", job_id=str(job_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "preview_failed",
                "message": "Unable to preview file. The file may be malformed or unsupported.",
            },
        )
    finally:
        if downloaded_preview_path is not None:
            downloaded_preview_path.unlink(missing_ok=True)

    # Persist all_layers into job.user_metadata so the fan-out
    # endpoint's layer-name validation has a non-empty set — otherwise
    # known_layer_names is empty and the 422 guard is a no-op for real uploads.
    if info.get("all_layers"):
        await record_preview_layers(db, job.id, info["all_layers"])

    # Auto-detect geometry columns for non-spatial files (CSV/XLSX with lat/lng or WKT)
    detected_geom_cols = None
    if info["geometry_type"] is None and info.get("columns"):
        detected = detect_geometry_columns(info["columns"])
        if detected["x_column"] or detected["wkt_column"]:
            detected_geom_cols = detected

    return PreviewResponse(
        job_id=job.id,
        source_filename=job.source_filename,
        columns=info["columns"],
        crs=info["srid"],
        geometry_type=info["geometry_type"],
        feature_count=info["feature_count"],
        sample_rows=info["sample_rows"],
        layer_name=layer_name if layer_name else info["layer_name"],
        layers=info.get("all_layers"),
        detected_geometry_columns=detected_geom_cols,
    )


def _pick_commit_subclass(job: "IngestJob") -> type[BaseCommitRequest]:
    """Return the CommitRequest subclass for the given job.

    Mirrors ``queue_ingest_job``'s discrimination:
      - ``job.source_url`` set (no ``file_path``) -> service
      - ``job.user_metadata['file_type'] == 'raster'`` -> raster
      - ``job.user_metadata['file_type'] == 'tiles3d'`` -> tileset
      - ``job.user_metadata['file_type'] == 'pointcloud'`` -> point cloud
      - otherwise -> vector (default)

    Service jobs are discriminated by ``source_url``, NOT by
    ``user_metadata.file_type == 'service'`` — that string doesn't exist
    anywhere in the codebase.
    """
    if job.source_url and not job.file_path:
        return ServiceCommitRequest
    if (job.user_metadata or {}).get("file_type") == "raster":
        return RasterCommitRequest
    if (job.user_metadata or {}).get("file_type") == TILESET_FILE_TYPE:
        return TilesetCommitRequest
    if (job.user_metadata or {}).get("file_type") == POINTCLOUD_FILE_TYPE:
        return PointCloudCommitRequest
    return VectorCommitRequest


@router.post(
    "/commit/{job_id}",
    response_model=CommitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={413: PAYLOAD_TOO_LARGE_RESPONSE},
)
async def commit_import(
    job_id: uuid.UUID,
    request: CommitRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> CommitResponse:
    """Commit a staged file for ingestion with user-supplied metadata.

    Stores user metadata on the job and queues the ingest task.
    Only callable on jobs with status 'pending'. A 3D Tiles tileset's unpacked
    size and a point cloud's size are checked against the storage quota again
    here.
    """
    job = await get_job_or_404(db, job_id, user)

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )
    observed_attempt_id = job.attempt_id

    # Re-validate job.source_url against SSRF rules at commit time
    # — closes the preview→commit DNS-rebinding TOCTOU (default 60s job TTL).
    # Mirrors the per-hop redirect defense in `make_safe_client()`, which
    # closes the redirect-chain TOCTOU; this closes the first-hop TOCTOU.
    if job.source_url and not job.file_path:
        from app.platform.security import (
            SSRFError,
            validate_url_for_ssrf,
        )

        try:
            await validate_url_for_ssrf(job.source_url)
        except SSRFError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"source_url failed safety check at commit time: {exc}",
            )

    # Re-validate the body against the subclass the job belongs to. Extras
    # from other subclasses are silently ignored (Pydantic default), so
    # kitchen-sink bodies still commit cleanly.
    Subclass = _pick_commit_subclass(job)
    try:
        commit = Subclass.model_validate(request.model_dump())
    except ValidationError as e:
        # The only enforcement of the import-commit door's shared safe-token
        # rule. The flat CommitRequest declares the cap the contract publishes;
        # a charset rule has no JSON Schema spelling.
        raise RequestValidationError(errors=e.errors())

    # Dash-guard and all_layers membership check for the commit's
    # layer_name, which reaches the worker's ogr2ogr argv (see layer_guard).
    validate_commit_layer_name(job, getattr(commit, "layer_name", None))

    # An unassigned EPSG code is refused rather than committed and ignored.
    srid_refusal = await unknown_srid_refusal(
        db, getattr(commit, "srid_override", None)
    )
    if srid_refusal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=srid_refusal,
        )

    # A non-admin may not commit a public dataset when
    # restrict_public_visibility is on. Local import: processing/ must not
    # import app.modules.catalog.* at module level.
    from app.modules.catalog.authorization import check_public_visibility_allowed

    await check_public_visibility_allowed(db, user, commit.visibility)
    if Subclass is TilesetCommitRequest:
        await check_upload_quota(db, user.id, staged_unpacked_bytes(job), None)
    if Subclass is PointCloudCommitRequest:
        size = await staged_pointcloud_bytes(job.file_path)
        await check_upload_quota(db, user.id, size, None)

    # Only ServiceCommitRequest carries a credential; it is never persisted.
    # The structured `auth` object is what the layers below take; the flat
    # `token` is its deprecated bearer spelling, and the model refuses a body
    # that sets both. Same conversion helper and 422 codes as the other doors.
    token = getattr(commit, "token", None)
    credential = credential_or_422(
        service_credential_from_request(getattr(commit, "auth", None), token),
        service_format=job_service_format(job),
    )

    # Judge the credential and the store before the write below:
    # `service_auth_required` is a one-way door (`_replay_capability` refuses
    # retry once set), so a later refusal would leave the job un-retryable.
    _assert_commit_credential_dispatchable(job, token, credential)

    # Persist the subclass-filtered view. `auth` is excluded like `token`,
    # and more sharply: user_metadata is durable JSONB, so a nested
    # credential object would land there in full. mode="json" serializes
    # datetime fields (temporal_start/temporal_end) as ISO strings.
    link = (
        resolve_portal_link(commit.item_id, commit.portal_url)
        if isinstance(commit, VectorCommitRequest)
        else PortalLink.unsupported(request.item_id, request.portal_url)
    )
    commit_metadata = {
        **commit.model_dump(
            exclude={"token", "auth", "item_id", "portal_url"}, mode="json"
        ),
        **link.fields,
    }
    if credential is not None:
        # Persist only the fact that retry needs fresh credentials. The
        # credential remains request-only and is never written to JSONB.
        commit_metadata["service_auth_required"] = True
    await admit_import_commit(db, job, observed_attempt_id, commit_metadata)
    staged_path = job.file_path

    # queue_ingest_job owns the orphan guard: a defer failure flips the job to
    # failed and raises 503. The staged file is deleted only when that flip
    # landed; a missed one means a worker owns the job and is reading it.
    try:
        await queue_ingest_job(job, str(user.id), db=db, credential=credential)
    except DeferFailed as exc:
        if staged_path and exc.landed:
            saved: Path | str = (
                Path(staged_path) if staged_path.startswith("/") else staged_path
            )
            await _cleanup_saved_upload(saved, str(job_id))
        raise

    return CommitResponse(
        job_id=job.id,
        status="pending",
        message="Import queued",
        origin_link_loss=link.losses,
    )


@router.post(
    "/commit-fan-out/{job_id}",
    response_model=FanOutCommitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def commit_fan_out(
    job_id: uuid.UUID,
    request: FanOutCommitRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> FanOutCommitResponse:
    """Convert a single pending IngestJob into N independent per-layer ingest tasks.

    For multi-layer sources (e.g. GeoPackage with 2+ layers), this endpoint
    fans out the original upload into one Procrastinate task per requested
    layer, each becoming a separate dataset. The original job is marked
    'fanned_out' (a terminal state).

    Required: original job must be in status='pending'. Each layer_name in
    the request body must appear in job.user_metadata['all_layers']. Unknown
    layer names return HTTP 422 with the list of unrecognized names.

    Returns HTTP 202 with per-layer outcomes. Partial success is possible:
    each layer result carries status='queued' or status='failed' with a
    user-safe error message.

    Permission: same as POST /ingest/commit/{job_id} — 'upload' capability.
    """
    job = await get_job_or_404(db, job_id, user)

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job already processed (status='{job.status}')",
        )
    # The attempt id observed with the pending status above: the terminal CAS
    # is fenced on this pair, so a cancel (or any other writer) landing in
    # between loses or wins cleanly.
    parent_attempt_id = job.attempt_id

    # Fan-out jobs inherit the parent's user_metadata, so a visibility seeded
    # there (the request schema has no visibility field) goes through the same
    # admin gate as a commit.
    from app.modules.catalog.authorization import check_public_visibility_allowed

    await check_public_visibility_allowed(
        db, user, (job.user_metadata or {}).get("visibility")
    )

    # A retry after an all-failed dispatch replaces the link a first attempt
    # left on the restored parent rather than adding to it.
    link = resolve_portal_link(request.item_id, request.portal_url)
    kept = {
        key: value
        for key, value in (job.user_metadata or {}).items()
        if key not in PORTAL_LINK_KEYS
    }
    if {**kept, **link.fields} != (job.user_metadata or {}):
        job.user_metadata = {**kept, **link.fields}

    known_layer_names = known_layer_names_for(job)

    unknown = [
        layer.layer_name
        for layer in request.layers
        if layer.layer_name not in known_layer_names
    ]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Unknown layer name(s) — not found in the uploaded file",
                "unknown_layers": unknown,
                "available_layers": sorted(known_layer_names),
            },
        )

    # The terminal transition is the mutex for the whole dispatch, CASed and
    # committed before the first child exists. Otherwise a cancel could commit
    # mid-loop while an already-deferred child completes. With the flip first,
    # a cancel either wins outright or arrives after the parent is terminal
    # and gets 409, with every child individually cancellable.
    if not await claim_fan_out_parent(db, job, parent_attempt_id=parent_attempt_id):
        await db.rollback()
        await db.refresh(job)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "job_conflict",
                "status": job.status,
                "message": (
                    "The job changed while this fan-out was being admitted — "
                    "nothing was queued."
                ),
            },
        )

    results = []
    for layer in request.layers:
        result = await create_fan_out_jobs(job, layer, db)
        results.append(result)

    # An all-failed dispatch (e.g. a Procrastinate outage) leaves the parent
    # retryable without a re-upload: a fenced CAS restore to `pending` that
    # can only undo the flip this request wrote. Partial success keeps the
    # parent `fanned_out`.
    queued_count = sum(1 for r in results if r.status == "queued")
    if queued_count == 0:
        restored = await restore_fan_out_parent_pending(
            db, job, parent_attempt_id=parent_attempt_id
        )
        if not restored:
            # The undo matched no row, so a third writer holds the parent
            # terminal and this 202 hides it.
            logger.warning(
                "fan_out_parent_restore_missed",
                job_id=str(job.id),
                attempt_id=(
                    str(parent_attempt_id) if parent_attempt_id is not None else None
                ),
            )

    return FanOutCommitResponse(
        fan_out_id=job.id, results=results, origin_link_loss=link.losses
    )


@router.post(
    "/register/",
    response_model=TableRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_table(
    request: RegisterRequest,
    user: Identity = Depends(require_table_registrar),
    db: AsyncSession = Depends(get_db),
) -> TableRegisterResponse:
    """Register an existing PostGIS table as a dataset.

    Verifies the table exists, extracts metadata, and creates a
    catalog entry. Administrators only.
    """
    from app.modules.catalog.authorization import check_public_visibility_allowed

    await check_public_visibility_allowed(db, user, request.visibility)

    try:
        dataset = await register_existing_table(db, request, user)
        await db.commit()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except (HTTPException, DatasetQuotaExceededError):
        raise
    except Exception:  # broad: metadata extraction involves PostGIS queries that can fail unpredictably
        logger.exception(
            "Unexpected error during table registration",
            table_name=request.table_name,
            user_id=str(user.id),
        )
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed — see server logs",
        )

    return TableRegisterResponse(
        dataset_id=dataset.id,
        title=dataset.record.title,
        table_name=dataset.table_name,
    )


@router.get(
    "/discover/",
    response_model=DiscoverResponse,
)
async def discover_tables(
    limit: int = Query(
        1000,
        ge=1,
        le=5000,
        description="Maximum number of tables to return. Capped at 5000.",
    ),
    user: Identity = Depends(require_table_registrar),
    db: AsyncSession = Depends(get_db),
) -> DiscoverResponse:
    """Discover unregistered tables in the data schema.

    Returns tables not yet in the catalog, excluding staging, old, and
    system tables. Includes geometry type, SRID, and estimated row count.
    Bounded by ``limit`` (default 1000, max 5000) so instances with
    thousands of orphan tables don't blow up the response payload.
    Administrators only.
    """
    tables = await discover_unregistered_tables(db, limit=limit)
    return DiscoverResponse(tables=tables)


@router.post(
    "/register/bulk/",
    response_model=BulkRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_register_tables(
    request: BulkRegisterRequest,
    user: Identity = Depends(require_table_registrar),
    db: AsyncSession = Depends(get_db),
) -> BulkRegisterResponse:
    """Bulk-register multiple existing PostGIS tables as datasets.

    Administrators only. Each table is registered independently -- one
    failure does not block others. Each table gets its own session, and at most
    ``_BULK_REGISTER_CONCURRENCY`` run at once so one batch cannot drain the
    shared connection pool.
    """
    from app.core.db import async_session

    # Gated once for the whole batch: any item requesting public visibility
    # puts the request through the admin check before any table is registered
    # (403, not a per-item error, so nothing partial runs).
    from app.modules.catalog.authorization import check_public_visibility_allowed

    if any(item.visibility == "public" for item in request.tables):
        await check_public_visibility_allowed(db, user, "public")

    slots = asyncio.Semaphore(_BULK_REGISTER_CONCURRENCY)

    async def _register_one(
        table_req: BulkRegisterItem,
    ) -> BulkRegisterResult:
        async with slots, async_session() as task_db:
            try:
                reg_request = RegisterRequest(
                    table_name=table_req.table_name,
                    title=table_req.title,
                    summary=table_req.summary,
                    visibility=table_req.visibility,
                )
                dataset = await register_existing_table(task_db, reg_request, user)
                await task_db.commit()
                return BulkRegisterResult(
                    table_name=table_req.table_name,
                    dataset_id=dataset.id,
                    title=dataset.record.title,
                    status="success",
                )
            except Exception as exc:  # broad: per-table registration is isolated; any failure is recorded per-item
                await task_db.rollback()
                return BulkRegisterResult(
                    table_name=table_req.table_name,
                    status="error",
                    error=registration_failure_reason(exc, table_req.table_name),
                )

    results = await asyncio.gather(
        *(_register_one(table_req) for table_req in request.tables)
    )
    return BulkRegisterResponse(results=list(results))


@router.post(
    "/vrt/create",
    response_model=VrtCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_vrt(
    request: VrtCreateRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> VrtCreateResponse:
    """Create a VRT dataset by combining existing raster datasets.

    Validates sources synchronously, then defers VRT assembly to an async task.
    Returns a job_id for polling. Validation + queuing logic lives in
    ``ingest.service.create_vrt_job``.
    """
    # A non-admin may not create a public VRT dataset when the
    # restrict_public_visibility instance setting is on.
    from app.modules.catalog.authorization import check_public_visibility_allowed

    await check_public_visibility_allowed(db, user, request.visibility)

    from app.processing.ingest.service import create_vrt_job

    job = await create_vrt_job(db, request, user)
    return VrtCreateResponse(job_id=job.id, message="VRT creation queued")


@router.post(
    "/vrt/{dataset_id}/sources/",
    response_model=VrtMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def add_vrt_source(
    dataset_id: uuid.UUID,
    request: VrtAddSourceRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> VrtMutationResponse:
    """Add a COG source to an existing VRT and trigger async regeneration.

    Validates the new source against existing sources synchronously.
    Returns 202 Accepted with a job_id for polling.
    Returns 409 if the VRT is currently regenerating or the source is already linked.
    Returns 422 if the source is incompatible with existing sources.
    """
    # The resulting member set is staged on the VrtGeneration row;
    # vrt_source_links is written by the regeneration task's transaction that
    # publishes the artifact.
    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset

    _port = get_processing_port()
    Dataset = _port.get_dataset_orm_class()
    Record = _port.get_record_orm_class()

    vrt_result = await db.execute(
        select(RasterAsset)
        .join(Dataset, RasterAsset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id, Record.record_type == "vrt_dataset")
    )
    vrt_asset = vrt_result.scalar_one_or_none()
    if vrt_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VRT dataset {dataset_id} not found",
        )

    source_result = await db.execute(
        select(RasterAsset)
        .join(Dataset, RasterAsset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(
            Dataset.id == request.source_dataset_id,
            Record.record_type == "raster_dataset",
        )
    )
    source_asset = source_result.scalar_one_or_none()
    if source_asset is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Source dataset {request.source_dataset_id} not found or not a raster dataset",
        )

    # Authorize the new source before the duplicate-link check, so a source the
    # caller can't read gets a 404 rather than a 409 confirming it is linked.
    from app.modules.catalog.authorization import (
        check_dataset_access,
        check_dataset_write_access,
        check_vrt_members,
        get_user_roles,
        lock_dataset_rows_for_write,
    )
    from app.modules.catalog.datasets.domain.service import get_dataset

    user_roles = await get_user_roles(db, user)
    source_dataset = await get_dataset(db, request.source_dataset_id)
    # The source only needs to be readable by the caller (it is being linked, not
    # modified); the VRT itself is being mutated, so it requires owner-or-admin.
    await check_dataset_access(
        db, source_dataset, request.source_dataset_id, user, user_roles=user_roles
    )
    vrt_dataset = await get_dataset(db, dataset_id)
    await check_dataset_write_access(
        db, vrt_dataset, dataset_id, user, user_roles=user_roles
    )
    await check_vrt_members(db, vrt_dataset, adding=request.source_dataset_id)

    # Admission, not a status read: the check and the flip are one sequence,
    # and only the lock inside makes it atomic. After the write check, so a
    # caller who may not mutate cannot hold it.
    if not await admit_vrt_mutation(db, dataset_id, vrt_asset):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": (
                    "VRT is currently regenerating. Try again after the "
                    "current operation completes."
                ),
            },
        )

    dup_result = await db.execute(
        text(
            "SELECT 1 FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id AND source_dataset_id = :src_id"
        ),
        {"vrt_id": dataset_id, "src_id": request.source_dataset_id},
    )
    if dup_result.fetchone() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source already linked to this VRT",
        )

    links_result = await db.execute(
        text(
            "SELECT source_dataset_id FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id ORDER BY position ASC"
        ),
        {"vrt_id": dataset_id},
    )
    existing_source_ids = [row.source_dataset_id for row in links_result.fetchall()]

    existing_assets_result = await db.execute(
        select(RasterAsset)
        .join(Dataset, RasterAsset.dataset_id == Dataset.id)
        .where(Dataset.id.in_(existing_source_ids))
    )
    existing_assets = list(existing_assets_result.scalars().all())
    all_assets = existing_assets + [source_asset]

    if not vrt_asset.vrt_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"VRT dataset {dataset_id} has no vrt_type — cannot validate sources",
        )
    errors = await validate_sources_async(vrt_asset.vrt_type, all_assets)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[e.model_dump(mode="json") for e in errors],
        )

    # Staged on the generation rather than written to vrt_source_links, which
    # states what is served; regenerate_vrt applies the staged set in the
    # transaction that swaps the artifact. The full set is staged, so applying
    # it is an idempotent replace. Order is position: the new source appends,
    # and applying renumbers 0..n-1.
    staged_source_ids = [str(sid) for sid in existing_source_ids] + [
        str(request.source_dataset_id)
    ]

    await lock_dataset_rows_for_write(db, vrt_dataset, raster_asset_cls=RasterAsset)
    job, generation = await stage_vrt_regeneration(
        db, vrt_asset, dataset_id, staged_source_ids, user
    )

    # A queue outage fails the job below and releases the VRT with it before
    # the 503; otherwise the asset sits 'regenerating', 409-ing every mutation
    # until sweep_stale_vrt_assets reconciles it.
    await db.commit()

    async def _defer() -> None:
        # The staged task name: a worker that predates staged sets lacks it
        # and fails loudly (TaskNotFound) instead of rebuilding from live
        # links and dropping this add.
        await defer_async_with_tenant(
            regenerate_vrt_staged,
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            vrt_dataset_id=str(dataset_id),
            generation_id=str(generation.id),
            triggered_by=str(user.id),
        )

    # An undispatched request never touched vrt_source_links, so nothing
    # needs to be put back.
    rollback = make_ingest_job_failed_rollback(
        job, message_prefix="Failed to queue VRT regeneration"
    )
    await defer_with_orphan_guard(_defer, rollback=rollback, db=db, job=job)

    # "queued", not "added": the catalog's source list still describes the
    # VRT being served until the regeneration publishes.
    return VrtMutationResponse(
        job_id=job.id, message="Source add queued, VRT regeneration started"
    )


@router.delete(
    "/vrt/{dataset_id}/sources/{source_dataset_id}/",
    response_model=VrtMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def remove_vrt_source(
    dataset_id: uuid.UUID,
    source_dataset_id: uuid.UUID,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> VrtMutationResponse:
    """Remove a COG source from an existing VRT and trigger async regeneration.

    Returns 202 Accepted with a job_id for polling.
    Returns 409 if the VRT is currently regenerating.
    Returns 422 if removing would leave fewer than 2 sources.
    Returns 404 if the source is not linked to the VRT.
    """
    # The post-removal member set is staged on the VrtGeneration row, as in
    # add_vrt_source.
    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset

    _port = get_processing_port()
    Dataset = _port.get_dataset_orm_class()
    Record = _port.get_record_orm_class()

    vrt_result = await db.execute(
        select(RasterAsset)
        .join(Dataset, RasterAsset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id, Record.record_type == "vrt_dataset")
    )
    vrt_asset = vrt_result.scalar_one_or_none()
    if vrt_asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"VRT dataset {dataset_id} not found",
        )

    # Owner-or-admin: removing a source mutates the VRT composition. The
    # `upload` capability alone is not ownership.
    from app.modules.catalog.authorization import (
        check_dataset_write_access,
        lock_dataset_rows_for_write,
    )
    from app.modules.catalog.datasets.domain.service import get_dataset

    vrt_dataset = await get_dataset(db, dataset_id)
    await check_dataset_write_access(db, vrt_dataset, dataset_id, user)

    # Admission, not a status read — see add_vrt_source.
    if not await admit_vrt_mutation(db, dataset_id, vrt_asset):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": (
                    "VRT is currently regenerating. Try again after the "
                    "current operation completes."
                ),
            },
        )

    # Read once, in order: the count guard, the "is it linked" guard and the
    # staged set ask about one set, so a single read keeps them consistent.
    links_result = await db.execute(
        text(
            "SELECT source_dataset_id FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id ORDER BY position ASC"
        ),
        {"vrt_id": dataset_id},
    )
    existing_source_ids = [row.source_dataset_id for row in links_result.fetchall()]

    # Minimum source count guard, evaluated before membership so an
    # under-populated VRT reports the real reason it cannot shrink further.
    if len(existing_source_ids) <= 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Removing this source would leave fewer than 2 sources. A VRT requires at least 2 sources.",
        )

    if source_dataset_id not in existing_source_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not linked to this VRT",
        )

    # Staged rather than deleting the link row now, as in add_vrt_source.
    # Applying renumbers 0..n-1.
    staged_source_ids = [
        str(sid) for sid in existing_source_ids if sid != source_dataset_id
    ]

    await lock_dataset_rows_for_write(db, vrt_dataset, raster_asset_cls=RasterAsset)
    job, generation = await stage_vrt_regeneration(
        db, vrt_asset, dataset_id, staged_source_ids, user
    )

    # Dispatch with the orphan guard: a Procrastinate outage would otherwise
    # leave the VRT 'regenerating' until sweep_stale_vrt_assets reconciled it,
    # 409-ing every mutation; the rollback below releases it.
    await db.commit()

    async def _defer() -> None:
        # The staged task name, as in add_vrt_source.
        await defer_async_with_tenant(
            regenerate_vrt_staged,
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            vrt_dataset_id=str(dataset_id),
            generation_id=str(generation.id),
            triggered_by=str(user.id),
        )

    # The link row was never deleted, so an undispatched request leaves the
    # catalog untouched.
    rollback = make_ingest_job_failed_rollback(
        job, message_prefix="Failed to queue VRT regeneration"
    )
    await defer_with_orphan_guard(_defer, rollback=rollback, db=db, job=job)

    # "queued", not "removed", as in add_vrt_source.
    return VrtMutationResponse(
        job_id=job.id, message="Source removal queued, VRT regeneration started"
    )
