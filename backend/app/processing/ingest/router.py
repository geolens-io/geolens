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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failure_reason import redact_failure_reason
from app.core.geo import unknown_srid_refusal
from app.core.identity import Identity
from app.core.async_io import (
    run_in_thread_draining,
    run_in_thread_draining_capture_cancel,
)
from app.modules.auth.dependencies import get_current_active_user, require_permission
from app.core.config import settings
from app.core.db.tenant_session import defer_async_with_tenant
from app.core.dependencies import get_db
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
    PreviewResponse,
    PresignedCompleteRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
    RasterCommitRequest,
    RasterPreviewResponse,
    RegisterRequest,
    ServiceCommitRequest,
    TableRegisterResponse,
    UploadConfigResponse,
    UploadResponse,
    UrlUploadRequest,
    VectorCommitRequest,
    VrtAddSourceRequest,
    VrtCreateRequest,
    VrtCreateResponse,
    VrtMutationResponse,
)
from app.processing.ingest.service import (
    PART_SIZE,
    _assert_header_token_dispatchable,
    _cleanup_saved_upload,
    claim_fan_out_parent,
    create_fan_out_jobs,
    create_ingest_job,
    discover_unregistered_tables,
    job_service_format,
    raster_stamped_metadata,
    restore_fan_out_parent_pending,
    get_job_or_404,
    queue_ingest_job,
    register_existing_table,
    resolve_file_path,
    safe_upload_basename,
    save_upload_file,
    validate_file_extension,
)
from app.processing.ingest.url_fetch import (
    PREFLIGHT_DNS_MAX_SECONDS,
    clamp_filename_bytes,
    filename_from_url,
)
from app.processing.ingest.presigned import (
    abort_presigned_multipart_upload,
    finalize_presigned_object,
    lock_presigned_job,
    require_completable_presigned_job,
    require_signable_job_lifetime,
    should_assemble_multipart,
    sign_url_with_deadline,
)
from app.processing.ingest.tasks import regenerate_vrt_staged
from app.processing.ingest.validation import (
    UnsafeUploadError,
    validate_file_content,
)
from app.platform.catalog_locks import admit_vrt_mutation
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_vrt_regeneration_failed_rollback,
)
from app.core.persistent_config import (
    UPLOAD_ALLOWED_EXTENSIONS,
    UPLOAD_MAX_SIZE_MB,
    get_allowed_extensions_list,
)
from app.modules.quota.service import check_upload_quota, get_user_quota_usage
from app.processing.raster.validation import validate_sources
from app.platform.service_auth import (
    credential_or_422,
    service_credential_from_request,
)
from app.platform.storage import get_storage
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    ERROR_RESPONSES_WRITE,
    FORBIDDEN_RESPONSE,
    PAYLOAD_TOO_LARGE_RESPONSE,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/ingest",
    tags=["Datasets"],
    responses=ERROR_RESPONSES_WRITE,
)


def _fallback_allowed_extensions() -> list[str]:
    """Allowed extensions when the persistent_config DB lookup fails (R-7).

    fix(#1682): read from ``settings``, not a frozen literal, so this
    fallback doesn't silently reject formats added since it was written.
    """
    return list(settings.allowed_extensions_list)


def _reject_standalone_vrt(filename: str) -> None:
    """Reject raw VRT XML uploads at every HTTP upload boundary.

    A VRT is only valid when GeoLens builds it from catalog-tracked raster
    sources. Accepting an arbitrary .vrt file would create a ready-looking
    dataset with no source links and may retain external paths in the XML.
    """
    if Path(filename).suffix.lower() == ".vrt":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Standalone VRT uploads are not supported. Create a managed "
                "VRT from existing raster datasets instead."
            ),
        )


def _without_standalone_vrt(extensions: str) -> str:
    """Keep legacy persistent config from advertising a disabled file type."""
    return ",".join(
        extension.strip()
        for extension in extensions.split(",")
        if extension.strip() and extension.strip().lower() != ".vrt"
    )


async def _get_allowed_extensions_safely(db: AsyncSession) -> list[str]:
    """Load allowed upload extensions with a DB-failure fallback (R-7).

    A transient DB hiccup during config lookup previously crashed the
    entire upload endpoint with a 500. Fall back to a safe default and
    log the failure so operators can investigate without losing uploads.
    """
    try:
        return await get_allowed_extensions_list(db)
    except Exception as exc:  # broad: persistent_config lookup must not crash uploads; fall back to safe default list
        logger.warning(
            "Failed to load allowed extensions from persistent_config — using fallback",
            error=str(exc),
        )
        return _fallback_allowed_extensions()


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
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    allowed_exts = _without_standalone_vrt(await UPLOAD_ALLOWED_EXTENSIONS.get(db))

    # Advisory remaining-quota hint so the client can cap a batch at what the
    # user can actually create. None when no count cap is set (unlimited).
    usage = await get_user_quota_usage(db, user.id)
    remaining = (
        max(0, usage.count_cap - usage.dataset_count) if usage.count_cap > 0 else None
    )

    return UploadConfigResponse(
        presigned_uploads=settings.storage_provider == "s3",
        presigned_threshold_bytes=settings.presigned_multipart_threshold_mb
        * 1024
        * 1024,
        max_file_size_bytes=max_size_mb * 1024 * 1024,
        allowed_extensions=allowed_exts,
        remaining_dataset_quota=remaining,
    )


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

    allowed_list = await _get_allowed_extensions_safely(db)
    _reject_standalone_vrt(request.filename)
    validate_file_extension(request.filename, allowed_list)

    # Reject files exceeding configured size limit at request time
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    max_size_bytes = max_size_mb * 1024 * 1024
    if request.file_size > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"File size ({request.file_size / (1024 * 1024):.1f} MB) exceeds the maximum allowed ({max_size_mb} MB).",
        )

    await check_upload_quota(db, user.id, request.file_size, http_request)

    job = await create_ingest_job(db, request.filename, "", user.id)
    storage = get_storage()
    s3_key = f"staging/{job.id}/{request.filename}"
    physical_s3_key = resolve_current_storage_key(s3_key)
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024
    # fix(#1235): gate only, return discarded — refuses a dead-lifetime job
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
                # fix(#1235): each part's expiration is computed INSIDE the
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
            # fix(#1235): an HTTPException here is the lifetime refusal and
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
            # fix(#1235): HTTPException passthrough here too — signing moved
            # into the thread, so the lifetime refusal now raises through
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

    # fix(#1213): an abandoned presigned upload is marked failed by the
    # stale-pending reaper after an hour, the same hour its PUT URL stays
    # valid — this door can reach the terminal-job case without stamping it.
    require_completable_presigned_job(job, restart_hint="Start a new upload.")

    storage = get_storage()
    s3_key = um["s3_key"]
    physical_s3_key = resolve_current_storage_key(s3_key)

    # fix(#1202): skip assembly when it already happened — the staging object
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
                # fix(#1233): do NOT delete the assembled object — its
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

    # fix(#1202): completion contract (exists check, size gate, drained
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

    job.file_path = frozen_key
    # fix(#1186): the presigned path never stamped file_type — on S3 every
    # upload goes through it, so every GeoTIFF fell through to the vector
    # branch (422 at preview, wrong commit dispatch).
    _stamp_raster_metadata(job, job.source_filename)
    await db.commit()

    # fix(#1202): delete AFTER commit, never before — deleting first left a
    # failed commit with the staging object already gone and the frozen copy
    # orphaned. Swept later by reapers resolving the key via
    # `owned_presigned_staging_key`; grep that name rather than trusting a list here.
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

    fix(#1186): this used to download the whole object and run
    ``validate_raster_crs``, which is exactly why ``complete_presigned_upload``
    never called it — presigned uploads exist for the multi-GB case, and the
    completion request cannot afford a full-object download (preview downloads
    the same object seconds later anyway). The only reader of the resulting
    ``crs_missing`` flag is ``ingest_raster``, which has the raster's metadata
    in hand and now derives the answer there. So the stamp costs no I/O and
    both upload endpoints can afford it.
    """
    job.user_metadata = raster_stamped_metadata(job.user_metadata, filename)


def _url_import_filename(body: UrlUploadRequest) -> str:
    """The staging filename for a URL import, or the endpoint's 400/422.

    fix(#1708): both name sources go through the byte clamp (filesystems cap
    NAME_MAX in BYTES, not the schema's 255 characters). Callers must invoke
    this INSIDE their guarded block — urlparse can raise ValueError on a
    malformed authority.
    """
    try:
        filename = (
            clamp_filename_bytes(safe_upload_basename(body.filename))
            if body.filename
            else filename_from_url(body.url)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid URL: {exc}",
        ) from exc
    # fix(#1708): NUL and other control characters survive percent-
    # decoding ('/roads%00.geojson') or arrive verbatim in the override, and
    # pass every suffix/allowlist check — the filesystem refuses them only at
    # open(), which sits AFTER the running-commit, and the failed open's
    # cleanup unlink then raised on the same invalid path. Refuse them here,
    # before any job row exists.
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Filename contains control characters that are not allowed.",
        )
    if not filename or not Path(filename).suffix:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Could not determine a filename with an extension from the "
                "URL path. Provide 'filename' explicitly."
            ),
        )
    return filename


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
) -> UploadResponse:
    """Upload a geospatial file for staging.

    Validates the file extension, creates an ingest job, and saves the file
    to staging. Does NOT auto-queue ingestion -- use preview then commit.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload missing filename",
        )
    try:
        allowed_list = await _get_allowed_extensions_safely(db)
        _reject_standalone_vrt(file.filename)
        validate_file_extension(file.filename, allowed_list)

        # IA-P0-02: enforce max_file_size_bytes at HTTP entry. Symmetric
        # with the presigned path's request-time check (:158-165).
        max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
        max_size_bytes = max_size_mb * 1024 * 1024

        # QUOTA-01/02: per-user quota check before any staging or job creation.
        incoming_bytes = file.size if file.size is not None else 0
        await check_upload_quota(db, user.id, incoming_bytes, request)

        job = await create_ingest_job(db, file.filename, "", user.id)
        job_id = job.id
        job_metadata = job.user_metadata
        # fix(#1848): committed BEFORE the spooled body is staged, so no pooled
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
            except ValueError as exc:
                # fix(#1848): guarded like the bind below, so a row the sweep
                # already reclaimed keeps its terminal status and message.
                await db.execute(
                    _pending_upload_update(job_id).values(
                        status="failed",
                        error_message=redact_failure_reason(exc),
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc

            # fix(#1848): bind only while the row is still pending, stamping
            # `staged_at` so the pending window restarts here rather than at
            # creation, which the upload itself has already spent.
            bound = await db.execute(
                _pending_upload_update(job_id).values(
                    file_path=str(saved_path),
                    user_metadata={
                        **(raster_stamped_metadata(job_metadata, file.filename) or {}),
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
            # fix(#1848): the request owns the staged source until the bind
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
    # N4: HTTPException must be caught and re-raised BEFORE the bare
    # `except Exception` below — otherwise a deliberate 4xx from a
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


@router.post(
    "/upload/url",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        # fix(#1710): 413 stays documented. The download moved to the worker,
        # but `check_upload_quota` still refuses an over-quota caller here,
        # and dropping it took the branch out of both SDKs.
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
)
async def upload_from_url(
    body: UrlUploadRequest,
    request: Request,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Start importing a geospatial file from an HTTP(S) URL.

    feat(#1705): the URL variant of ``POST /ingest/upload`` — NOT a new
    source type. The server fetches the file itself and the staged bytes
    enter the normal pipeline unchanged (preview then commit).

    feat(#1710): the download is a background job. This call validates the
    URL and returns a job id immediately; poll ``GET /jobs/{job_id}`` and
    preview once the job reaches ``pending``. While the file is downloading
    the job reports status ``running`` with step ``downloading``.

    Rule 2 posture: ``validate_url_for_ssrf`` gates the URL here, the worker
    downloads through ``make_safe_client()`` (connect-time IP pinning plus
    per-hop redirect revalidation), the size cap is enforced while
    streaming, the staged file passes the same extension allowlist and
    content sniff as a direct upload, and GDAL only ever sees the staged
    local file.
    """
    from datetime import datetime, timezone

    from app.core.db.tenant_session import defer_async_with_tenant
    from app.core.url_redaction import redact_url_credentials
    from app.platform.jobs.defer_guard import (
        defer_with_orphan_guard,
        make_ingest_job_failed_rollback,
    )
    from app.platform.jobs.models import URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY
    from app.platform.security import SSRFError, validate_url_for_ssrf
    from app.processing.ingest.tasks import fetch_url

    # Exception-safe on malformed input by design (fix(#1119)) — safe to run
    # before the guarded block below.
    safe_url = redact_url_credentials(body.url)
    try:
        filename = _url_import_filename(body)
        _reject_standalone_vrt(filename)

        # fix(#1708): commit here to END the auth-phase transaction before the
        # DNS await — getaddrinfo has no bound of its own, and holding a
        # connection through it could exhaust the pool under concurrent imports.
        await db.commit()

        # Rule 2, submission gate: refuse private/link-local/reserved targets
        # before anything is queued. The worker's safe client re-validates at
        # connect time and per redirect hop during the download.
        #
        # fix(#1708): bounded at the call site — getaddrinfo has no deadline
        # of its own; wait_for cancels the to_thread wrapper immediately and
        # the abandoned resolver thread ends when the OS resolver gives up.
        try:
            await asyncio.wait_for(
                validate_url_for_ssrf(body.url),
                timeout=PREFLIGHT_DNS_MAX_SECONDS,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "DNS resolution for this URL did not finish within "
                    f"{PREFLIGHT_DNS_MAX_SECONDS} seconds."
                ),
            ) from exc
        except SSRFError as exc:
            logger.warning(
                "url_import_ssrf_blocked",
                event_type="security",
                url=safe_url,
                reason=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

        allowed_list = await _get_allowed_extensions_safely(db)
        validate_file_extension(filename, allowed_list)

        # QUOTA-02: refuse at the dataset-count cap before queueing anything.
        # The byte half (QUOTA-01) runs in the worker with the size that
        # actually landed — Content-Length may be absent or dishonest.
        await check_upload_quota(db, user.id, 0, request)

        job = await create_ingest_job(db, filename, "", user.id)
        job_id = job.id
        # feat(#1710): the row is committed 'running', not 'pending'. The
        # success state of a URL import IS 'pending' (previewable), so a
        # pending row would tell the UI the download had finished; and the
        # stale-PENDING sweep may legally fire at 61s while a download is
        # allowed url_import_fetch_max_seconds. Running rows are judged by
        # the worker lease instead, which the task's heartbeat renews.
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.current_step = "downloading"
        job.progress = 0.0
        # fix(#1710): while this is set, `file_path` names a destination, not
        # a finished file, so retry is refused. The staged transition clears
        # it; see URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY.
        job.user_metadata = {
            **(job.user_metadata or {}),
            URL_DOWNLOAD_IN_FLIGHT_METADATA_KEY: True,
        }
        await db.commit()

        async def _defer_fetch() -> None:
            await defer_async_with_tenant(
                fetch_url,
                job_id=str(job_id),
                attempt_id=str(job.attempt_id),
                url=body.url,
                user_id=str(user.id),
                filename=filename,
            )

        # The URL crosses to the worker as a task argument rather than on the
        # job row: `user_metadata` is served by GET /jobs/{id}, and a URL can
        # carry userinfo credentials.
        await defer_with_orphan_guard(
            _defer_fetch,
            rollback=make_ingest_job_failed_rollback(
                job,
                message_prefix="Failed to queue the download",
                expected_status="running",
            ),
            db=db,
            job=job,
        )

        logger.info("url_import_queued", url=safe_url, job_id=str(job_id))
        return UploadResponse(
            job_id=job_id,
            status="running",
            message="Downloading the file",
        )
    # N4 (mirrors upload_file): HTTPException before the ValueError fallback,
    # or every deliberate 4xx above is rewritten as a 400/500.
    except HTTPException:
        raise
    except (IngestionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception:  # broad: submission involves DNS, config lookups, DB and the queue — any can throw
        logger.exception(
            "Unexpected error during URL import",
            url=safe_url,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during URL import",
        )


@router.post(
    "/preview/{job_id}",
    response_model=PreviewResponse | RasterPreviewResponse,
)
async def preview_file(
    job_id: uuid.UUID,
    layer_name: str | None = Query(
        None, description="Sheet/layer name for multi-layer files"
    ),
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> PreviewResponse | RasterPreviewResponse:
    """Run preview on a staged file and return preview data.

    For vector files: returns columns, CRS, geometry type, feature count, sample rows.
    For raster files: returns band count, CRS, resolution, compliance status.
    Only callable on jobs with status 'pending'.
    """
    # fix(#823): layer_name reaches ogrinfo argv; 422 option-like values.
    reject_option_like_layer_name(layer_name)

    job = await get_job_or_404(db, job_id, user)

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # Resolve S3 key to local file
    if not job.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no associated file — upload must complete before preview",
        )
    file_path: str = job.file_path
    downloaded_preview_path: Path | None = None
    resolved_file_path = await resolve_file_path(file_path, str(job.id))
    if resolved_file_path != file_path:
        file_path = resolved_file_path
        downloaded_preview_path = Path(file_path)

    # Branch: raster vs vector preview
    um = job.user_metadata or {}
    if um.get("file_type") == "raster":
        from app.processing.raster.cog import (
            check_cog_compliance,
            extract_raster_metadata,
        )

        file_size: int | None = None
        try:
            meta, (compliant, reason) = await asyncio.gather(
                asyncio.to_thread(extract_raster_metadata, file_path),
                asyncio.to_thread(check_cog_compliance, file_path),
            )
            try:
                import os

                file_size = os.path.getsize(file_path)
            except OSError:
                pass
        except (
            Exception
        ) as exc:  # broad: rasterio/GDAL can raise various errors on malformed files
            logger.exception(
                "raster_preview failed", job_id=str(job_id), error=str(exc)
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unable to preview raster file. The file may be malformed or unsupported.",
            )
        finally:
            if downloaded_preview_path is not None:
                downloaded_preview_path.unlink(missing_ok=True)

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

    try:
        info = await run_ogrinfo_preview(file_path, layer_name=layer_name)
    except IngestBudgetExceededError as exc:
        # fix(#948): the ceiling message is server-authored and actionable —
        # falling through to the generic handler would call an oversized
        # file "malformed or unsupported" when it's merely too large.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except UnsafeUploadError as exc:
        # fix(#1846, GHSA-hrf5-v3cq-frx5): server-authored refusal naming
        # what was blocked and what to upload instead — a presigned upload's
        # first whole-file check, since the presign door only sees a header probe.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:  # broad: GDAL subprocess can raise various errors on unsupported/malformed files
        logger.exception("ogrinfo_preview failed", job_id=str(job_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unable to preview file. The file may be malformed or unsupported.",
        )
    finally:
        if downloaded_preview_path is not None:
            downloaded_preview_path.unlink(missing_ok=True)

    # fix(CR-01): persist all_layers into job.user_metadata so the fan-out
    # endpoint's layer-name validation has a non-empty set — otherwise
    # known_layer_names is empty and the 422 guard is a no-op for real uploads.
    if info.get("all_layers"):
        job.user_metadata = {
            **(job.user_metadata or {}),
            "all_layers": info["all_layers"],
        }
        await db.commit()

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
      - otherwise -> vector (default)

    Service jobs are discriminated by ``source_url``, NOT by
    ``user_metadata.file_type == 'service'`` — that string doesn't exist
    anywhere in the codebase.
    """
    if job.source_url and not job.file_path:
        return ServiceCommitRequest
    if (job.user_metadata or {}).get("file_type") == "raster":
        return RasterCommitRequest
    return VectorCommitRequest


@router.post(
    "/commit/{job_id}",
    response_model=CommitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def commit_import(
    job_id: uuid.UUID,
    request: CommitRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> CommitResponse:
    """Commit a staged file for ingestion with user-supplied metadata.

    Stores user metadata on the job and queues the ingest task.
    Only callable on jobs with status 'pending'.
    """
    job = await get_job_or_404(db, job_id, user)

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # IA-P0-03: re-validate job.source_url against SSRF rules at commit time
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
    # kitchen-sink bodies still commit cleanly (D-02).
    Subclass = _pick_commit_subclass(job)
    try:
        commit = Subclass.model_validate(request.model_dump())
    except ValidationError as e:
        # fix(#1755, #1931): the only enforcement of the import-commit door's
        # shared safe-token rule. The flat CommitRequest declares the cap the
        # contract publishes; a charset rule has no JSON Schema spelling.
        raise RequestValidationError(errors=e.errors())

    # fix(#823): dash-guard + all_layers membership check for the commit's
    # layer_name, which reaches the worker's ogr2ogr argv (see layer_guard).
    validate_commit_layer_name(job, getattr(commit, "layer_name", None))

    # fix(#2032): an unassigned EPSG code committed and was then ignored.
    srid_refusal = await unknown_srid_refusal(
        db, getattr(commit, "srid_override", None)
    )
    if srid_refusal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=srid_refusal,
        )

    # feat(#1691): a non-admin may not commit a public dataset when
    # restrict_public_visibility is on. Local import: processing/ must not
    # import app.modules.catalog.* at module level (PROCESS-02/04).
    from app.modules.catalog.authorization import check_public_visibility_allowed

    await check_public_visibility_allowed(db, user, commit.visibility)

    # Extract the credential only for service commits (ServiceCommitRequest is
    # the only subclass carrying one). AUTH-04: never persisted.
    #
    # feat(#1746): the structured `auth` object is what the layers below
    # take; the flat `token` is its deprecated bearer spelling, and a body that
    # sets both is refused by the model rather than having one win by an
    # ordering nobody wrote down. Same precedence rule, same conversion helper
    # and same 422 codes as the other four doors.
    token = getattr(commit, "token", None)
    credential = credential_or_422(
        service_credential_from_request(getattr(commit, "auth", None), token),
        service_format=job_service_format(job),
    )

    # fix(#1746): judge the credential BEFORE the write below, not just
    # before the stash inside `queue_ingest_job` — `service_auth_required`
    # is a one-way door (`_replay_capability` refuses retry once set), so a
    # late-rejected credential would leave a `pending` job un-retryable.
    _assert_header_token_dispatchable(job, token)

    # Persist the subclass-filtered view. `auth` is excluded like `token`,
    # and more sharply: user_metadata is durable JSONB, so a nested
    # credential object would land there in full. mode="json" serializes
    # datetime fields (temporal_start/temporal_end) as ISO strings.
    commit_metadata = commit.model_dump(exclude={"token", "auth"}, mode="json")
    if credential is not None:
        # Persist only the fact that retry needs fresh credentials. The
        # credential remains request-only and is never written to JSONB.
        commit_metadata["service_auth_required"] = True
    if job.user_metadata:
        # Service jobs already have service_type and layer_id from preview
        merged = {**job.user_metadata, **commit_metadata}
        job.user_metadata = merged
    else:
        job.user_metadata = commit_metadata
    await db.commit()

    # Dispatch routing lives in the service layer (KISS-9).
    # queue_ingest_job owns the orphan-guard: a defer failure flips the job
    # to failed and raises 503 (RESILIENCE-2). Clean up the staging file
    # on failure so it isn't orphaned on disk/S3.
    try:
        await queue_ingest_job(job, str(user.id), db=db, credential=credential)
    except Exception:  # broad: defer failure or DB error during enqueue — clean up staging file then re-raise
        if job.file_path:
            saved: Path | str = (
                Path(job.file_path) if job.file_path.startswith("/") else job.file_path
            )
            await _cleanup_saved_upload(saved, str(job.id))
        raise

    return CommitResponse(
        job_id=job.id,
        status="pending",
        message="Import queued",
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
    # fix(#1709): the attempt id observed WITH the pending status above —
    # the terminal CAS at the bottom is fenced on this pair, so a cancel (or
    # any other writer) landing between here and there loses or wins cleanly.
    parent_attempt_id = job.attempt_id

    # feat(#1691): fan-out jobs inherit the parent job's user_metadata, so a
    # visibility seeded there (defense-in-depth — the request schema itself
    # has no visibility field) goes through the same admin gate as a commit.
    from app.modules.catalog.authorization import check_public_visibility_allowed

    await check_public_visibility_allowed(
        db, user, (job.user_metadata or {}).get("visibility")
    )

    # fix(#823): layer_name normalisation extracted to
    # layer_guard.known_layer_names, shared with the single-layer commit endpoint.
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

    # fix(#1709): the terminal transition is the MUTEX for the whole
    # dispatch — CASed and COMMITTED before the first child exists. The
    # earlier shape (children first, CAS after) left a window where a
    # cancel could commit mid-loop and let an already-deferred child
    # complete before the post-loop cleanup's CAS refused it. With the flip
    # first, a cancel either wins outright or arrives after the parent is
    # terminal and gets 409, with every child individually cancellable.
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

    # fix(CR-02): an all-failed dispatch (e.g. Procrastinate outage) must
    # leave the parent retryable without a re-upload — a fenced CAS restore
    # to `pending` that can only undo the flip THIS request wrote. Partial
    # success keeps the parent `fanned_out`.
    queued_count = sum(1 for r in results if r.status == "queued")
    if queued_count == 0:
        restored = await restore_fan_out_parent_pending(
            db, job, parent_attempt_id=parent_attempt_id
        )
        if not restored:
            # fix(#2016): the undo matched no row, so a third writer holds the
            # parent terminal and this 202 hides it. Never silent again.
            logger.warning(
                "fan_out_parent_restore_missed",
                job_id=str(job.id),
                attempt_id=(
                    str(parent_attempt_id) if parent_attempt_id is not None else None
                ),
            )

    return FanOutCommitResponse(fan_out_id=job.id, results=results)


@router.post(
    "/register/",
    response_model=TableRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_table(
    request: RegisterRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> TableRegisterResponse:
    """Register an existing PostGIS table as a dataset.

    Verifies the table exists, extracts metadata, and creates a
    catalog entry.
    """
    # feat(#1691): a non-admin may not register a public dataset when the
    # restrict_public_visibility instance setting is on.
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
    except HTTPException:
        raise
    except Exception:  # broad: metadata extraction involves PostGIS queries that can fail unpredictably
        await db.rollback()
        logger.exception(
            "Unexpected error during table registration",
            table_name=request.table_name,
            user_id=str(user.id),
        )
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
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> DiscoverResponse:
    """Discover unregistered tables in the data schema.

    Returns tables not yet in the catalog, excluding staging, old, and
    system tables. Includes geometry type, SRID, and estimated row count.
    Bounded by ``limit`` (default 1000, max 5000) so instances with
    thousands of orphan tables don't blow up the response payload.
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
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> BulkRegisterResponse:
    """Bulk-register multiple existing PostGIS tables as datasets.

    Each table is registered independently -- one failure does not block
    others. Tables are processed in parallel via ``asyncio.gather`` with
    a fresh session per task, which keeps transaction isolation while
    removing the sequential per-table latency.
    """
    from app.core.db import async_session

    # feat(#1691): gate ONCE for the whole batch — any item requesting public
    # visibility puts the request through the shared admin check before any
    # table is registered (403, not a per-item error, so nothing partial runs).
    from app.modules.catalog.authorization import check_public_visibility_allowed

    if any(item.visibility == "public" for item in request.tables):
        await check_public_visibility_allowed(db, user, "public")

    async def _register_one(
        table_req: BulkRegisterItem,
    ) -> BulkRegisterResult:
        async with async_session() as task_db:
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
                    error=str(exc),
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
    ``ingest.service.create_vrt_job`` (K5 extraction).
    """
    # feat(#1691): a non-admin may not create a public VRT dataset when the
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
    # fix(#1327): the resulting member set is STAGED on the VrtGeneration row;
    # vrt_source_links is written by the regeneration task's own transaction
    # that publishes the artifact. Comment, not docstring — the docstring is
    # published OpenAPI text, so editing it would churn openapi.json and SDKs.
    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from sqlalchemy import text

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

    # fix(SEC-C): authorize the new source before linking it into the VRT
    # mosaic — compiled pixels can't be filtered at read time, and this runs
    # BEFORE the duplicate-link check so a foreign source 404s, not a leaked
    # 409. Defense-in-depth: also requires access to the parent VRT itself.
    from app.modules.catalog.authorization import (
        check_dataset_access,
        check_dataset_write_access,
        get_user_roles,
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

    # SRC-05 / fix(#1955): admission, not a status read — the check and the
    # flip below are one sequence, and only the lock inside makes it atomic.
    # After the write check, so a caller who may not mutate cannot hold it.
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
    errors = validate_sources(vrt_asset.vrt_type, all_assets)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[e.model_dump() for e in errors],
        )

    # fix(#1327): STAGE the intended post-mutation member set on the
    # generation rather than writing vrt_source_links here — that table is
    # the catalog's statement about what's actually served, and
    # regenerate_vrt applies the staged set in the same transaction that
    # swaps the artifact. The full set is staged (not "add this id"), so
    # applying it is an idempotent replace. Order IS position: read ORDER BY
    # position above, new source appends — applying renumbers 0..n-1, closing gaps.
    staged_source_ids = [str(sid) for sid in existing_source_ids] + [
        str(request.source_dataset_id)
    ]

    # Capture pre-mutation values so the orphan-guard rollback (Theme H) can
    # restore them if Procrastinate is unreachable.
    previous_status = vrt_asset.status
    previous_generation_id = vrt_asset.current_generation_id
    generation = VrtGeneration(
        vrt_dataset_id=dataset_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
        source_count=len(staged_source_ids),
        staged_source_ids=staged_source_ids,
        triggered_by=str(user.id),
    )
    db.add(generation)
    await db.flush()
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = generation.id

    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    # If Procrastinate is unreachable the rollback below reverts the VRT
    # asset state and marks the job failed before re-raising as HTTP 503 —
    # otherwise the VRT would sit 'regenerating' until sweep_stale_vrt_assets
    # (#1267) reconciled it, 409-ing every mutation in between.
    await db.commit()

    async def _defer() -> None:
        # fix(#1327): dispatch the STAGED task name, not the legacy one — a
        # pre-#1327 worker lacks it and fails loudly (TaskNotFound) instead
        # of silently rebuilding from live links and dropping this add.
        await defer_async_with_tenant(
            regenerate_vrt_staged,
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            vrt_dataset_id=str(dataset_id),
            generation_id=str(generation.id),
            triggered_by=str(user.id),
        )

    # fix(#1327): no link-table rollback needed — with the member set staged
    # on the generation, an undispatched request never touched
    # vrt_source_links, so nothing needs to be put back.
    rollback = make_vrt_regeneration_failed_rollback(
        vrt_asset,
        generation,
        job,
        previous_status=previous_status,
        previous_generation_id=previous_generation_id,
    )
    await defer_with_orphan_guard(_defer, rollback=rollback, db=db, job=job)

    # fix(#1327): "queued", not "added". The catalog's source list still
    # describes the VRT being served; the addition becomes part of it when the
    # regeneration publishes the artifact that contains it.
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
    # fix(#1327): the post-removal member set is STAGED on the VrtGeneration
    # row; vrt_source_links is written by the regeneration task in the same
    # transaction that publishes the artifact without the removed member. Kept
    # out of the docstring — see the note on add_vrt_source.
    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from sqlalchemy import text

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
    from app.modules.catalog.authorization import check_dataset_write_access
    from app.modules.catalog.datasets.domain.service import get_dataset

    vrt_dataset = await get_dataset(db, dataset_id)
    await check_dataset_write_access(db, vrt_dataset, dataset_id, user)

    # SRC-05 / fix(#1955): admission, not a status read — see add_vrt_source.
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

    # fix(#1327): read the current member set ONCE, in order — the count
    # guard, the "is it linked" guard and the staged post-removal set are
    # three questions about one set, and a single ordered read keeps them
    # from disagreeing.
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

    # fix(#1327): STAGE the post-removal member set on the generation rather
    # than deleting the link row now — the link table keeps describing what's
    # served until regenerate_vrt applies the staged set in the same
    # transaction that publishes the artifact. Applying renumbers 0..n-1.
    staged_source_ids = [
        str(sid) for sid in existing_source_ids if sid != source_dataset_id
    ]

    # Capture pre-mutation values for the orphan-guard rollback.
    previous_status = vrt_asset.status
    previous_generation_id = vrt_asset.current_generation_id
    generation = VrtGeneration(
        vrt_dataset_id=dataset_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
        source_count=len(staged_source_ids),
        staged_source_ids=staged_source_ids,
        triggered_by=str(user.id),
    )
    db.add(generation)
    await db.flush()
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = generation.id

    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    # Commit + dispatch with orphan guard (Theme H) — a Procrastinate outage
    # would otherwise leave the VRT 'regenerating' until sweep_stale_vrt_assets
    # reconciled it, 409-ing every mutation; the rollback below reverts state.
    await db.commit()

    async def _defer() -> None:
        # fix(#1327): staged task name, same reasoning as the add endpoint —
        # a pre-#1327 worker must refuse this delivery rather than rebuild
        # the composition it cannot see.
        await defer_async_with_tenant(
            regenerate_vrt_staged,
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            vrt_dataset_id=str(dataset_id),
            generation_id=str(generation.id),
            triggered_by=str(user.id),
        )

    # fix(#1327): nothing to re-insert — the link row was never deleted, and
    # the post-removal set is staged on the generation until the artifact
    # swap, so an undispatched request leaves the catalog untouched.
    rollback = make_vrt_regeneration_failed_rollback(
        vrt_asset,
        generation,
        job,
        previous_status=previous_status,
        previous_generation_id=previous_generation_id,
    )
    await defer_with_orphan_guard(_defer, rollback=rollback, db=db, job=job)

    # fix(#1327): "queued", not "removed" — see the add endpoint's tail.
    return VrtMutationResponse(
        job_id=job.id, message="Source removal queued, VRT regeneration started"
    )
