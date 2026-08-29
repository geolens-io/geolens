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
    _await_provider_call_draining,
    claim_fan_out_parent,
    create_fan_out_jobs,
    create_ingest_job,
    discover_unregistered_tables,
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
    UrlFetchError,
    UrlFetchTooLargeError,
    clamp_filename_bytes,
    fetch_url_to_path,
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
from app.processing.ingest.validation import validate_file_content
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

    fix(#1682 codex r3): read from ``settings`` rather than a frozen literal.
    The literal was written to match "the original production default" and then
    stayed put through two format additions, so during the exact DB hiccup this
    fallback exists to tolerate, a `.parquet`/`.fgb`/`.kml`/`.kmz` upload was
    refused for a reason the operator could not see and had not configured.

    A narrower list is not a safer one: the accepted-extension list gates
    nothing on its own — content validation, the size limit, and the quota
    check all still run — so a stale fallback only breaks uploads the operator
    is entitled to make. ``settings`` needs no database, and when nothing is
    stored it is already what ``UPLOAD_ALLOWED_EXTENSIONS`` resolves to.
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
    # fix(#1235 review r4): a gate, not a value. Every signature below computes
    # its own expiration inside the signing thread; this call is here so a job
    # with no usable lifetime left is refused before an upload id is ever
    # initiated, rather than after — the return is deliberately discarded.
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
                # fix(#1235 review r5/r8): each part computes its own
                # expiration, INSIDE the signing thread — see
                # `sign_url_with_deadline` for why the two must be adjacent.
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
            # fix(#1235 review r5): an HTTPException from here is the lifetime
            # refusal, which must survive as its own 409 — the abort above has
            # already run, and mapping it to "Storage service unavailable"
            # would blame the provider for the job's clock.
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
            # fix(#1235 review r9): the fourth signing path needed the same
            # passthrough as the multipart branch. Signing moved into the
            # thread, so the lifetime refusal now raises through here, and this
            # handler turned a closed upload window into "Storage service
            # unavailable". No CancelledError case: this except is `Exception`,
            # which never catches one, and nothing is spent on a one-shot PUT.
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

    # fix(#1213 review r3): both one-shot facts, shared with the reupload door.
    # An abandoned presigned upload is marked failed by the stale-pending
    # reaper after an hour — the same hour its PUT URL stays valid — so this
    # door reaches the terminal-job case without ever stamping it itself.
    require_completable_presigned_job(job, restart_hint="Start a new upload.")

    storage = get_storage()
    s3_key = um["s3_key"]
    physical_s3_key = resolve_current_storage_key(s3_key)

    # fix(#1202 review r3): skip assembly when it already happened. For an S3
    # multipart upload the staging object exists IF AND ONLY IF
    # CompleteMultipartUpload succeeded — uploaded parts are invisible as an
    # object until then — so the object's presence is a sound record that this
    # step is done, with no metadata to keep in sync. Without this, a
    # completion that got past assembly and then failed (at the freeze, say)
    # left the job unbound and the upload id SPENT: the retry this endpoint's
    # 502 advertises re-entered the branch, called complete with a consumed id,
    # and could never succeed. The parts-required 400 is skipped along with it,
    # deliberately — a retrying client has nothing left to resend.
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
                # fix(#1233): do NOT delete the assembled object here. The
                # upload id was consumed by CompleteMultipartUpload above, so
                # the object's presence is the only record that assembly
                # succeeded — `should_assemble_multipart` reads exactly that to
                # let a retry skip re-assembly (#1202 r3). Deleting it left the
                # client's natural retry re-assembling with a spent id, 502ing
                # forever with no way back. Drain and re-raise only; the
                # cancellation is not a rejection of the bytes.
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

    # fix(#1202): rows 7-13 of the completion contract — exists, pre-copy size
    # gate, drained freeze, verify and content-validate the frozen bytes, with
    # every cleanup decision. Shared with the reupload door so the two cannot
    # drift; its docstring carries the failure contract as postconditions.
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
    # fix(#1186): the presigned path never stamped file_type, and on an S3
    # deployment the frontend always uploads through it — so every GeoTIFF
    # fell through to the vector branch: 422 at preview, a vector commit body
    # after that, and an ogr2ogr dispatch after that.
    _stamp_raster_metadata(job, job.source_filename)
    await db.commit()

    # fix(#1202 review r3): AFTER the commit, never before. Deleting first
    # meant a failed commit rolled `file_path` back with the staging object
    # already gone — the retry then hit "File not found in S3 after upload"
    # and the frozen copy orphaned with nothing pointing at it. Now a failed
    # commit leaves both objects, so the retry re-copies over the frozen key
    # and proceeds.
    #
    # Past this line the staging object has served its purpose. A delete
    # failure here, or a late re-PUT through the still-valid URL, leaves an
    # orphan that nothing reads.
    #
    # It is swept at job end by whichever terminal reaper owns the job. Every
    # one of them resolves the key through `owned_presigned_staging_key`, so
    # grep that name for the current set rather than trusting a list here —
    # this comment has already gone stale once by naming them. The stale-job
    # purge is a backstop, not a guarantee: it exempts the newest complete job
    # per dataset, which is exactly what a successful ingest leaves behind, so
    # a path with no task-level reaper would keep its orphan indefinitely.
    # S3 cannot revoke an individual presigned URL, so reaping is the only
    # real remedy.
    await _cleanup_saved_upload(s3_key, str(job.id))

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded and ready for preview",
    )


async def _cleanup_saved_upload(
    saved_path: Path | str,
    job_id: str,
) -> None:
    """Delete a saved upload regardless of storage backend.

    Used to roll back a failed upload (e.g., content validation error) so
    we don't leave orphaned files in local staging or S3. Never raises —
    S3 failures are logged instead (KISS-N9).
    """
    if isinstance(saved_path, Path):
        saved_path.unlink(missing_ok=True)
        return
    try:
        physical_saved_path = resolve_current_storage_key(saved_path)
        await _await_provider_call_draining(get_storage().delete(physical_saved_path))
    except (
        BaseException
    ):  # broad: cleanup is best-effort and must drain through request cancellation
        logger.warning(
            "S3 cleanup failed during validation error — file may be orphaned",
            s3_key=str(saved_path),
            job_id=job_id,
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
    job.user_metadata = _raster_stamped_metadata(job.user_metadata, filename)


def _raster_stamped_metadata(
    user_metadata: dict | None, filename: str | None
) -> dict | None:
    """Pure form of ``_stamp_raster_metadata``: the metadata that should be
    persisted for ``filename``, without touching an ORM instance.

    fix(#1708 codex r2): the URL-import path persists its final state through
    a guarded compare-and-swap ``UPDATE`` rather than by dirtying the ORM
    object (a dirtied object would flush a SECOND, unguarded UPDATE on
    commit, silently bypassing the CAS). It still must apply the exact same
    stamping policy, so the policy lives here and both forms share it.
    """
    if not (filename or "").lower().endswith((".tif", ".tiff", ".vrt")):
        return user_metadata

    return {**(user_metadata or {}), "file_type": "raster"}


def _url_import_filename(body: UrlUploadRequest) -> str:
    """The staging filename for a URL import, or the endpoint's 400/422.

    fix(#1708 codex P2): both name sources go through the byte clamp. The
    schema admits 255 CHARACTERS, but filesystems cap name components in
    BYTES (NAME_MAX 255), and staging prepends a 37-byte job-id prefix — an
    unclamped long-ASCII or multibyte override made open() ENAMETOOLONG and
    the endpoint answer 500.

    fix(#1708 codex r2): callers must invoke this INSIDE their guarded
    block — urlparse raises ValueError on malformed authorities
    ('http://[/x.geojson'), which used to escape as a 500 because the
    derivation ran before the handler's try.
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
        saved_path = await save_upload_file(
            file, str(job.id), max_size_bytes=max_size_bytes
        )
        validation_path = str(saved_path)
        downloaded_validation_path: Path | None = None
        try:
            if not isinstance(saved_path, Path):
                validation_path = await resolve_file_path(saved_path, str(job.id))
                downloaded_validation_path = Path(validation_path)

            # Inline content validation for immediate feedback.
            try:
                validate_file_content(validation_path, file.filename)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc

            _stamp_raster_metadata(job, file.filename)

            job.file_path = str(saved_path)
            await db.commit()
        except BaseException:
            # Until the job commit below, this request exclusively owns the
            # staged source. Resolve/provider/content failures must delete it;
            # otherwise the transaction rolls back the only retention record.
            await _cleanup_saved_upload(saved_path, str(job.id))
            raise
        finally:
            if downloaded_validation_path is not None:
                downloaded_validation_path.unlink(missing_ok=True)

        return UploadResponse(
            job_id=job.id,
            status="pending",
            message="File uploaded and ready for preview",
        )
    # N4: except clause order matters. HTTPException must be caught and
    # re-raised BEFORE the bare `except Exception`, otherwise a deliberate
    # 4xx raised by a downstream helper (persistent config, validation,
    # etc.) would be rewritten as a generic 500 by the fallback branch.
    # Do not reorder these clauses without understanding the 4xx→500
    # regression it would introduce.
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
    """Import a geospatial file from an HTTP(S) URL for staging.

    feat(#1705): the URL variant of ``POST /ingest/upload`` — NOT a new
    source type. The server fetches the file itself and the staged bytes
    enter the normal pipeline unchanged (preview → commit). Rule 2 posture:
    ``validate_url_for_ssrf`` gates the URL at submission, the download runs
    through ``make_safe_client()`` (connect-time IP pinning plus per-hop
    redirect revalidation), the size cap is enforced while streaming, the
    staged file passes the same extension allowlist and content sniff as a
    direct upload, and GDAL only ever sees the staged local file.
    """
    from sqlalchemy import update as sa_update

    from app.core.url_redaction import redact_url_credentials
    from app.platform.jobs.models import IngestJob
    from app.platform.security import SSRFError, validate_url_for_ssrf

    # Exception-safe on malformed input by design (fix #1119) — safe to run
    # before the guarded block below.
    safe_url = redact_url_credentials(body.url)
    try:
        filename = _url_import_filename(body)
        allowed_list = await _get_allowed_extensions_safely(db)
        _reject_standalone_vrt(filename)
        validate_file_extension(filename, allowed_list)

        max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
        max_size_bytes = max_size_mb * 1024 * 1024

        # Rule 2, submission gate: refuse private/link-local/reserved targets
        # before any connection is attempted. The safe client re-validates at
        # connect time and per redirect hop during the fetch below.
        try:
            await validate_url_for_ssrf(body.url)
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

        # QUOTA-02: refuse at the dataset-count cap before staging anything.
        # The byte half (QUOTA-01) runs again after the download with the
        # real size — Content-Length may be absent or dishonest, so nothing
        # is charged on the remote server's word.
        await check_upload_quota(db, user.id, 0, request)

        job = await create_ingest_job(db, filename, "", user.id)
        # fix(#1708 codex r2): the download runs under the RUNNING lease, not
        # as a bare 'pending' row. A committed 'pending' row with an empty
        # file_path and no live queue task matches every clause of
        # stale_pending_clauses, and pending_job_timeout_seconds may legally
        # be as low as 61s while the fetch is allowed FETCH_MAX_SECONDS
        # (480s) — both the periodic sweep and the get_job_status poll (which
        # the frontend hits every 2s) could fail an in-progress fetch.
        # 'running' rows are judged by the running lease instead:
        # coalesce(heartbeat_at, started_at) against the fixed 3600s
        # JOB_TIMEOUT_SECONDS, so one started_at stamp outlives the fetch's
        # own hard deadline six times over with no periodic heartbeat needed
        # ('running' is already in the status CHECK constraint — no
        # migration). test_url_import_1705 pins FETCH_MAX_SECONDS under the
        # lease. If the process dies mid-fetch, the running sweep reaps the
        # row after an hour — the same recovery every worker task gets.
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        # fix(#1708 codex P1): COMMIT before awaiting the fetch. The session
        # autobegins on its first query and holds a checked-out pool
        # connection until the transaction ends, so leaving it open across a
        # download that may legitimately run for minutes (FETCH_MAX_SECONDS)
        # let pool_size + max_overflow (10 + 3) trickling URL imports starve
        # every DB-backed request in the API. Committing here persists the
        # job row and returns the connection; every later query checks out a
        # fresh one. Consequences, each handled below: the row now survives
        # a failed fetch (CAS-stamped 'failed' in the cleanup path instead of
        # vanishing with a rollback), and the byte-quota check must re-run
        # after the download since the world may have moved while we fetched.
        await db.commit()
        # Capture the scalars now and never touch the ORM instance again:
        # the failure path below ROLLS BACK, and rollback expires every
        # object in the session — a later `job.id` would then lazy-refresh
        # synchronously and die with MissingGreenlet inside the exception
        # handler, turning a clean 4xx into a 500.
        job_id = job.id
        job_metadata = job.user_metadata

        staging_dir = Path(settings.upload_staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)
        local_dest = staging_dir / f"{job_id}_{filename}"

        s3_key: str | None = None
        try:
            try:
                actual_size = await fetch_url_to_path(
                    body.url, local_dest, max_size_bytes
                )
            except UrlFetchTooLargeError as exc:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=str(exc),
                ) from exc
            except SSRFError as exc:
                # A redirect hop or a rebinding DNS answer targeted a blocked
                # address mid-fetch — same refusal as at submission.
                logger.warning(
                    "url_import_ssrf_blocked",
                    event_type="security",
                    url=safe_url,
                    reason=str(exc),
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            except UrlFetchError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=str(exc),
                ) from exc

            # QUOTA-01 with the byte count that actually landed on disk.
            await check_upload_quota(db, user.id, actual_size, request)

            # Same staged-file content sniff as a direct upload.
            try:
                validate_file_content(str(local_dest), filename)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc

            if settings.storage_provider == "s3":
                s3_key = f"staging/{job_id}/{filename}"
                # codeql[py/path-injection] fix(#1708): the component is basename-stripped (safe_upload_basename/filename_from_url) and byte-clamped, rooted under upload_staging_dir
                fh = open(local_dest, "rb")
                try:
                    await _await_provider_call_draining(
                        get_storage().put(resolve_current_storage_key(s3_key), fh)
                    )
                finally:
                    await run_in_thread_draining(fh.close)
                staged_path = s3_key
            else:
                staged_path = str(local_dest)

            # fix(#1708 codex r2): guarded CAS, running -> pending. Only the
            # row this request parked in 'running' may proceed to the
            # previewable state; a Core UPDATE (not dirtied ORM attributes,
            # which would flush a second unguarded UPDATE) so an external
            # flip — admin cancel, or a lease reap that would take an
            # impossible >1h stall — matches zero rows and is SURFACED
            # instead of silently part-updating a dead row.
            cas = await db.execute(
                sa_update(IngestJob)
                .where(IngestJob.id == job_id, IngestJob.status == "running")
                .values(
                    status="pending",
                    file_path=staged_path,
                    user_metadata=_raster_stamped_metadata(job_metadata, filename),
                )
            )
            if cas.rowcount == 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "The import was cancelled or timed out while the "
                        "file was downloading. Start a new import."
                    ),
                )
            await db.commit()
        except BaseException as exc:
            # Until the file_path commit above, this request exclusively owns
            # the staged bytes (the local file and, if the put ran, the S3
            # object) — nothing else references them, so both must go before
            # the exception propagates.
            if s3_key is not None:
                await _cleanup_saved_upload(s3_key, str(job_id))
            # codeql[py/path-injection] fix(#1708): same clamped, staging-rooted path as the open above
            local_dest.unlink(missing_ok=True)
            # fix(#1708 codex P1): the job row was committed before the fetch,
            # so a rollback no longer removes it. Stamp it failed with the
            # refusal so status polling shows why, instead of leaving it under
            # the running lease for an hour. Guarded CAS from 'running' only
            # (codex r2): zero rows means something external already settled
            # the row — never overwrite that verdict. Best-effort: never mask
            # the original error, and a cancelled request may refuse the
            # awaits — then the running sweep's hour is the fallback.
            try:
                await db.rollback()
                await db.execute(
                    sa_update(IngestJob)
                    .where(IngestJob.id == job_id, IngestJob.status == "running")
                    .values(
                        status="failed",
                        error_message=(
                            str(exc.detail)
                            if isinstance(exc, HTTPException)
                            else "URL import failed"
                        ),
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
            except BaseException:
                logger.warning("url_import_fail_stamp_skipped", job_id=str(job_id))
            raise
        if s3_key is not None:
            # S3 is the staging store; the local copy served content
            # validation and has no further reader.
            # codeql[py/path-injection] fix(#1708): same clamped, staging-rooted path as the open above
            local_dest.unlink(missing_ok=True)

        logger.info(
            "url_import_staged",
            url=safe_url,
            job_id=str(job_id),
            filename=filename,
            size_bytes=actual_size,
        )
        return UploadResponse(
            job_id=job_id,
            status="pending",
            message="File downloaded and ready for preview",
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
    except (
        Exception
    ):  # broad: fetch pipeline involves network, file I/O, S3, DB — any can throw
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
        # it names the limit, the observed value, and what to do. Falling
        # through to the generic handler below would tell the user their file
        # "may be malformed or unsupported" when it is merely too large, and
        # preview runs before commit, so that is the moment they can act on it.
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

    # CR-01 fix: persist all_layers into job.user_metadata so the fan-out
    # endpoint's layer-name validation has a non-empty set to check against.
    # Without this, known_layer_names is always empty and the 422 guard is a no-op
    # for real uploads (test helper _make_pending_job bypassed the bug by injecting
    # all_layers directly).
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

    Mirrors the discrimination logic in ``queue_ingest_job`` at
    ``app.ingest.service:477-506``:
      - ``job.source_url`` set (and no ``file_path``) -> service
      - ``job.user_metadata['file_type'] == 'raster'`` -> raster
      - otherwise -> vector (default)

    CRITICAL: Service jobs are discriminated by ``source_url``, NOT by
    ``user_metadata.file_type == 'service'`` — that string does not exist
    anywhere in the codebase. See Phase 220 research Pitfall 1.
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

    # IA-P0-03: re-validate job.source_url against SSRF rules at commit
    # time. Closes the preview→commit DNS-rebinding TOCTOU (default 60s
    # job TTL): an attacker could resolve a public address at preview
    # and a private one at commit. Mirrors the per-hop redirect defense
    # added in v1014 SEC-S04 (`_revalidate_redirect` event hook on
    # `make_safe_client()`), which closes the redirect-chain TOCTOU;
    # this closes the FIRST-hop TOCTOU on the recorded source_url.
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
        # Preserve FastAPI's standard 422 envelope. Currently a safety net:
        # the flat CommitRequest already validated 'title' at the signature
        # level. This branch only fires if a subclass adds stricter
        # per-field rules in a future phase.
        raise RequestValidationError(errors=e.errors())

    # fix(#823): dash-guard + all_layers membership check for the commit's
    # layer_name, which reaches the worker's ogr2ogr argv (see layer_guard).
    validate_commit_layer_name(job, getattr(commit, "layer_name", None))

    # feat(#1691): a non-admin may not commit a public dataset when the
    # restrict_public_visibility instance setting is on. Local import:
    # processing/ must not import app.modules.catalog.* at module level
    # (PROCESS-02/04 layering invariant).
    from app.modules.catalog.authorization import check_public_visibility_allowed

    await check_public_visibility_allowed(db, user, commit.visibility)

    # Extract token only for service commits (ServiceCommitRequest is the
    # only subclass with a token field). AUTH-04: never persisted.
    token = getattr(commit, "token", None)

    # Persist the subclass-filtered view. model_dump(exclude={"token"}) is
    # a no-op when the subclass has no token field. mode="json" so datetime
    # fields (temporal_start/temporal_end) serialize as ISO strings before
    # going into the JSONB column.
    commit_metadata = commit.model_dump(exclude={"token"}, mode="json")
    if token:
        # Persist only the fact that retry needs fresh credentials. The token
        # remains request-only and is never written to JSONB.
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
        await queue_ingest_job(job, str(user.id), db=db, token=token)
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
    # fix(#1709 review r2 P1): the attempt id observed WITH the pending status
    # above — the terminal CAS at the bottom is fenced on this pair, so a
    # cancel (or any other writer) landing between here and there loses or
    # wins cleanly instead of being overwritten.
    parent_attempt_id = job.attempt_id

    # feat(#1691): fan-out jobs inherit the parent job's user_metadata, so a
    # visibility seeded there (defense-in-depth — the request schema itself
    # has no visibility field) goes through the same admin gate as a commit.
    from app.modules.catalog.authorization import check_public_visibility_allowed

    await check_public_visibility_allowed(
        db, user, (job.user_metadata or {}).get("visibility")
    )

    # Validate all requested layer_names appear in the job's all_layers preview.
    # fix(#823): normalisation extracted to layer_guard.known_layer_names,
    # shared with the single-layer commit endpoint's new validation.
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

    # fix(#1709 review r5 P1): the terminal transition is the MUTEX for the
    # whole dispatch — CASed and COMMITTED before the first child exists.
    # The round-2 shape (children first, CAS after the loop, loser cancels
    # its children) left a window: a cancel committing mid-loop let an
    # already-deferred fast child claim and complete before the post-loop
    # cleanup, whose child CAS rightly refuses terminal rows — a 200 cancel
    # that still created that child's dataset. With the flip first, a
    # cancel either wins here (zero children ever created) or arrives after
    # the parent is terminal and gets 409 job_already_finished, with every
    # child individually cancellable through the same endpoint.
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

    # Dispatch one task per layer, collecting results.
    results = []
    for layer in request.layers:
        result = await create_fan_out_jobs(job, layer, db)
        results.append(result)

    # CR-02: an all-failed dispatch (e.g. Procrastinate outage) must leave
    # the parent retryable without a re-upload. Under the early flip that
    # means a fenced restore of `pending` — a CAS on (fanned_out, attempt),
    # so it can only undo the flip THIS request wrote, never resurrect a
    # row some other actor terminated. Partial success keeps the parent
    # `fanned_out`: at least one child is importing, which is the same
    # contract the late transition enforced.
    queued_count = sum(1 for r in results if r.status == "queued")
    if queued_count == 0:
        await restore_fan_out_parent_pending(
            db, job, parent_attempt_id=parent_attempt_id
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
        description="Maximum number of tables to return (PERF-11 bound).",
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
    removing the sequential per-table latency (PERF-3).
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
    Returns 409 if the VRT is currently regenerating (SRC-05) or source already linked.
    Returns 422 if the source is incompatible with existing sources.
    """
    # fix(#1327): the resulting member set is STAGED on the VrtGeneration row;
    # vrt_source_links is written by the regeneration task in the same
    # transaction that publishes the artifact containing it. Deliberately a
    # comment and not a docstring line: FastAPI publishes the docstring as this
    # operation's OpenAPI description, so editing it would churn
    # backend/openapi.json and every generated SDK for an internal note.
    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from sqlalchemy import text

    _port = get_processing_port()
    Dataset = _port.get_dataset_orm_class()
    Record = _port.get_record_orm_class()

    # 1. Load VRT RasterAsset
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

    # 2. Mutation serialization guard (SRC-05)
    if vrt_asset.status == "regenerating":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VRT is currently regenerating. Try again after the current operation completes.",
        )

    # 3. Validate source exists and is a raster_dataset
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

    # 3b. SEC-C: authorize the new source against the caller before linking it
    # into the VRT mosaic. VRT member pixels are compiled into one served asset
    # and cannot be filtered at read time, so authorize at link time (mirrors
    # #234). On denial, check_dataset_access raises 404. Defense-in-depth: also
    # require the caller to access the parent VRT itself. This runs BEFORE the
    # duplicate-link check so a foreign source 404s rather than leaking a 409.
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

    # 4. Check for duplicate link
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

    # 5. Load existing source links and assets for validation
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

    # 6. fix(#1327): STAGE the intended post-mutation member set on the
    # generation instead of writing it into vrt_source_links here. The link
    # table is the catalog's statement about what the served VRT contains, and
    # this request has not produced that artifact yet — regenerate_vrt applies
    # the staged set in the same transaction that swaps the artifact and writes
    # built_from, so a death anywhere before that swap leaves the links exactly
    # where the served bytes are. The full set is staged (not "add this id"),
    # so applying it is a replace: idempotent, and independent of whatever the
    # links happen to hold when it lands.
    #
    # Order IS the position: existing links were read ORDER BY position above,
    # and the new source appends, which is what the MAX(position)+1 insert this
    # replaces computed. Applying the set renumbers positions 0..n-1, closing
    # any gaps a previous removal left behind.
    staged_source_ids = [str(sid) for sid in existing_source_ids] + [
        str(request.source_dataset_id)
    ]

    # 7. Set VRT status to regenerating — capture pre-mutation values so
    # the orphan-guard rollback (Theme H) can restore them if Procrastinate
    # is unreachable.
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

    # 8. Create IngestJob
    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    # 9. Commit + dispatch.
    # If Procrastinate is unreachable the rollback below reverts the VRT
    # asset state and marks the job failed before re-raising as HTTP 503 —
    # otherwise the VRT would sit in ``status="regenerating"`` until
    # ``sweep_stale_vrt_assets`` (GAP-002 / feat(#1267)) reconciled it a
    # timeout later, 409-ing every mutation in between.
    await db.commit()

    async def _defer() -> None:
        # fix(#1327 codex P1): the STAGED task name, not the legacy one. A
        # pre-#1327 worker does not have this task registered and fails the job
        # loudly (procrastinate TaskNotFound) instead of rebuilding from the
        # live links and reporting success, which would drop this add on the
        # floor during a rolling upgrade. See tasks_vrt.regenerate_vrt_staged.
        await defer_async_with_tenant(
            regenerate_vrt_staged,
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            vrt_dataset_id=str(dataset_id),
            generation_id=str(generation.id),
            triggered_by=str(user.id),
        )

    # fix(#1327): no link-table rollback needed here. This used to DELETE the
    # row it had just inserted; with the member set staged on the generation,
    # an undispatched request never touched vrt_source_links, so there is
    # nothing to put back. The staged set stays on the failed generation row
    # as the record of what was asked for — it can only be applied by a task
    # that still owns the asset pointer, which this rollback has just handed
    # back.
    rollback = make_vrt_regeneration_failed_rollback(
        vrt_asset,
        generation,
        job,
        previous_status=previous_status,
        previous_generation_id=previous_generation_id,
    )
    await defer_with_orphan_guard(_defer, rollback=rollback, db=db)

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
    Returns 409 if the VRT is currently regenerating (SRC-05).
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

    # 1. Load VRT RasterAsset
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

    # 2. Mutation serialization guard (SRC-05)
    if vrt_asset.status == "regenerating":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="VRT is currently regenerating. Try again after the current operation completes.",
        )

    # 3. Read the current member set ONCE, in order. fix(#1327): the count
    # guard, the "is it linked" guard and the staged post-removal set are three
    # questions about one set — a single ordered read answers all three and
    # leaves them unable to disagree (this replaced a COUNT(*) and a separate
    # per-link position lookup).
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

    # 4. Check the source is actually linked.
    if source_dataset_id not in existing_source_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not linked to this VRT",
        )

    # 5. fix(#1327): STAGE the post-removal member set on the generation rather
    # than deleting the link row now. The link table keeps describing the VRT
    # that is actually being served until regenerate_vrt publishes the artifact
    # this set describes, and applies the set in that same transaction. The
    # surviving order is preserved; applying renumbers positions 0..n-1 so the
    # removal leaves no gap.
    staged_source_ids = [
        str(sid) for sid in existing_source_ids if sid != source_dataset_id
    ]

    # 6. Set VRT status to regenerating — capture pre-mutation values.
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

    # 7. Create IngestJob
    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    # 8. Commit + dispatch with orphan guard (Theme H).
    # A Procrastinate outage would otherwise leave the VRT in
    # ``status="regenerating"`` until ``sweep_stale_vrt_assets`` reconciled
    # it a timeout later, 409-ing every mutation in between. The rollback
    # below reverts the VRT asset state and marks the job failed.
    await db.commit()

    async def _defer() -> None:
        # fix(#1327 codex P1): staged task name, same reasoning as the add
        # endpoint — a pre-#1327 worker must refuse this delivery rather than
        # rebuild the composition it cannot see.
        await defer_async_with_tenant(
            regenerate_vrt_staged,
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            vrt_dataset_id=str(dataset_id),
            generation_id=str(generation.id),
            triggered_by=str(user.id),
        )

    # fix(#1327): nothing to re-insert. The link row was never deleted — the
    # post-removal set is staged on the generation and only applied at the
    # artifact swap, so an undispatched request leaves the catalog's member
    # set untouched.
    rollback = make_vrt_regeneration_failed_rollback(
        vrt_asset,
        generation,
        job,
        previous_status=previous_status,
        previous_generation_id=previous_generation_id,
    )
    await defer_with_orphan_guard(_defer, rollback=rollback, db=db)

    # fix(#1327): "queued", not "removed" — see the add endpoint's tail.
    return VrtMutationResponse(
        job_id=job.id, message="Source removal queued, VRT regeneration started"
    )
