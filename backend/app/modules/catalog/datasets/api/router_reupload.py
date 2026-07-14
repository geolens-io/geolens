"""Dataset reupload and presigned reupload endpoints."""

import asyncio
import math
import uuid
from pathlib import Path

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.async_io import (
    await_draining,
    run_in_thread_draining,
    run_in_thread_draining_capture_cancel,
)
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import check_dataset_write_access
from app.core.config import settings
from app.core.db.tenant_session import defer_async_with_tenant
from app.modules.catalog.datasets.domain.schemas import (
    ReuploadCommitRequest,
    ReuploadCommitResponse,
    ReuploadPreviewRequest,
    ReuploadPreviewResponse,
    ReuploadServicePreviewRequest,
    ReuploadResponse,
    SchemaDiff,
)
from app.modules.catalog.datasets.domain.service import (
    compute_schema_diff,
    get_dataset,
)
from app.core.dependencies import get_db
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import IngestJob
from app.platform.extensions import get_catalog_port
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB, get_allowed_extensions_list
from app.modules.quota.service import check_upload_quota
from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview
from app.modules.catalog.sources.security import SSRFError, validate_url_for_ssrf
from app.platform.storage import get_storage
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    ERROR_RESPONSES_WRITE,
    PAYLOAD_TOO_LARGE_RESPONSE,
)

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets - Reupload"],
    responses=ERROR_RESPONSES_WRITE,
)
logger = structlog.get_logger(__name__)

_catalog_port = get_catalog_port()
IngestionError = _catalog_port.ingestion_error_class()
PresignedCompleteRequest = _catalog_port.presigned_complete_request_model()
PresignedUploadRequest = _catalog_port.presigned_upload_request_model()
PresignedUploadResponse = _catalog_port.presigned_upload_response_model()
UploadResponse = _catalog_port.upload_response_model()

# Extension sets used for cross-record-type validation.
# Do NOT depend on the runtime allowed_extensions config (which merges all types).
_RASTER_EXTENSIONS: frozenset[str] = frozenset({".tif", ".tiff"})


async def _get_bound_reupload_job_or_404(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    dataset_id: uuid.UUID,
    user_id: uuid.UUID,
) -> IngestJob:
    """Return a reupload job only when all immutable bindings match.

    Ordinary ingest jobs deliberately start without a dataset binding. They
    must never be accepted as reupload jobs, even when the caller can edit the
    target dataset. Returning 404 for every mismatch avoids disclosing whether
    a supplied job UUID belongs to another user or workflow.
    """
    result = await db.execute(
        select(IngestJob).where(
            IngestJob.id == job_id,
            IngestJob.dataset_id == dataset_id,
            IngestJob.created_by == user_id,
        )
    )
    job = result.scalar_one_or_none()
    metadata = job.user_metadata if job is not None else None
    if (
        job is None
        or not metadata
        or metadata.get("reupload") is not True
        or metadata.get("dataset_id") != str(dataset_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reupload job not found",
        )
    return job


async def _cleanup_uncommitted_reupload_source(
    saved_path: Path | str, *, job_id: uuid.UUID
) -> None:
    """Best-effort cleanup while the request still exclusively owns a source."""
    if isinstance(saved_path, Path):
        saved_path.unlink(missing_ok=True)
        return
    try:
        await get_storage().delete(resolve_current_storage_key(saved_path))
    except BaseException:
        logger.warning(
            "reupload_source_cleanup_failed",
            job_id=str(job_id),
            storage_key=saved_path,
        )


def _assert_compatible_record_type(
    dataset,
    filename: str | None,
    *,
    service_type: str | None = None,
) -> None:
    """Raise HTTP 400 when the source is incompatible with dataset.record.record_type.

    Called from `reupload_dataset` (multipart), `request_presigned_reupload` (S3),
    and `reupload_service_preview` (service URL) after dataset lookup, before
    pipeline work, so the user sees the precise cross-record-type message rather
    than a deep-pipeline 500.

    Raster and VRT reupload are rejected at this shared boundary because the
    worker implements only vector/table replacement. File paths additionally
    reject raster inputs for vector and table datasets.

    Audit action `reupload.commit` is shipped — see test_provenance_attribution.py.
    Do not rename to `dataset.reupload`.
    """
    record_type: str = dataset.record.record_type
    ext: str = Path(filename or "").suffix.lower()

    if ext == ".vrt":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Standalone VRT files cannot be reuploaded. "
                "Manage VRT membership through the VRT sources API instead."
            ),
        )

    if record_type == "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "VRT datasets do not support file reupload — "
                "edit the VRT membership instead."
            ),
        )

    if record_type == "raster_dataset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Raster dataset reupload is not supported. "
                "Import a replacement raster dataset instead."
            ),
        )

    if record_type in ("vector_dataset", "table") and ext in _RASTER_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"This dataset is a {record_type.replace('_', ' ')}; "
                f"{ext} files are not supported for reupload. "
                "Cross-record-type swaps are not allowed."
            ),
        )


@router.post(
    "/{dataset_id}/reupload",
    response_model=ReuploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={413: PAYLOAD_TOO_LARGE_RESPONSE},
)
async def reupload_dataset(
    dataset_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadResponse:
    """Upload a new file to replace the data in an existing dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)

    _assert_compatible_record_type(dataset, file.filename)

    try:
        allowed_list = await get_allowed_extensions_list(db)
        get_catalog_port().validate_file_extension(file.filename, allowed_list)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # QUOTA-01/02: per-user quota check before any staging or job creation.
    incoming_bytes = file.size if file.size is not None else 0
    await check_upload_quota(db, user.id, incoming_bytes, request)

    job = await get_catalog_port().create_ingest_job(db, file.filename, "", user.id)
    job.dataset_id = dataset_id
    job.user_metadata = {"reupload": True, "dataset_id": str(dataset_id)}

    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    max_size_bytes = max_size_mb * 1024 * 1024
    saved_path = await get_catalog_port().save_upload_file(
        file,
        str(job.id),
        max_size_bytes=max_size_bytes,
    )
    validation_path = str(saved_path)
    downloaded_validation_path: Path | None = None
    try:
        if not isinstance(saved_path, Path):
            validation_path = await get_catalog_port().resolve_file_path(
                saved_path, str(job.id)
            )
            downloaded_validation_path = Path(validation_path)

        # Inline content validation for immediate feedback.
        try:
            get_catalog_port().validate_file_content(validation_path, file.filename)
        except ValueError as exc:
            # Preserve the existing failed-job audit trail for a user content
            # error; provider/transport failures below roll the uncommitted job
            # back with the request transaction.
            job.status = "failed"
            job.error_message = str(exc)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

        job.file_path = str(saved_path)
        await db.commit()
    except BaseException:
        await _cleanup_uncommitted_reupload_source(saved_path, job_id=job.id)
        raise
    finally:
        if downloaded_validation_path is not None:
            downloaded_validation_path.unlink(missing_ok=True)

    return ReuploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded for re-upload preview",
    )


@router.post(
    "/{dataset_id}/reupload/service/preview",
    response_model=ReuploadPreviewResponse,
    responses={502: BAD_GATEWAY_RESPONSE},
)
async def reupload_service_preview(
    dataset_id: uuid.UUID,
    request: ReuploadServicePreviewRequest,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadPreviewResponse:
    """Preview a remote service layer for dataset re-upload."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)

    # IA-P1-02: surface cross-record-type swaps as a useful 400 before the
    # pipeline executes (vector→raster or any→VRT explodes deep otherwise).
    _assert_compatible_record_type(dataset, None, service_type=request.service_type)

    try:
        await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    try:
        gdal_source, layer_arg = build_gdal_source(
            request.service_type,
            request.url,
            request.layer_name,
            request.layer_id,
            token=request.token,
            order_field=None,
            result_limit=5,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    try:
        preview_data = await run_service_preview(
            gdal_source,
            layer_arg,
            token=request.token,
        )
    except IngestionError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to preview remote layer. The service may be unavailable or the layer format is unsupported.",
        )

    diff = compute_schema_diff(
        dataset.column_info or [],
        preview_data["columns"],
        dataset.feature_count,
        preview_data["feature_count"],
    )
    schema_diff = SchemaDiff(**diff)

    job = IngestJob(
        dataset_id=dataset_id,
        source_filename=request.layer_title or request.layer_name,
        source_url=request.url,
        source_layer=request.layer_name,
        created_by=user.id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": request.service_type,
            "layer_id": request.layer_id,
            "source_type": "service_url",
            "object_id_field": request.object_id_field,
        },
    )
    db.add(job)
    await db.flush()
    await db.commit()

    return ReuploadPreviewResponse(
        job_id=job.id,
        source_filename=job.source_filename,
        columns=preview_data["columns"],
        crs=preview_data["srid"],
        geometry_type=preview_data["geometry_type"],
        feature_count=preview_data["feature_count"],
        sample_rows=preview_data["sample_rows"],
        layer_name=request.layer_name
        if request.service_type.startswith("ArcGIS")
        else preview_data["layer_name"],
        schema_diff=schema_diff,
    )


@router.post(
    "/{dataset_id}/reupload/{job_id}/preview",
    response_model=ReuploadPreviewResponse,
)
async def reupload_preview(
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    # GPKG-01 Phase 1058: optional body allows callers to specify a layer_name
    # for multi-layer files; single-layer callers may omit the body entirely.
    request: ReuploadPreviewRequest | None = None,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadPreviewResponse:
    """Preview the schema diff between old dataset and new upload.

    When the uploaded file contains multiple layers, the response includes
    ``all_layers`` (for frontend layer-select UI) and ``previous_source_layer``
    (pre-selection hint from the most-recent completed IngestJob for this
    dataset).  Pass ``layer_name`` in the request body to target a specific
    layer; omit it to get the default first-layer metadata.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)
    _assert_compatible_record_type(dataset, None)

    job = await _get_bound_reupload_job_or_404(
        db,
        job_id=job_id,
        dataset_id=dataset_id,
        user_id=user.id,
    )

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # Resolve S3 key to local file for ogrinfo
    file_path = job.file_path
    downloaded_preview_path: Path | None = None
    if file_path:
        resolved_file_path = await get_catalog_port().resolve_file_path(
            file_path, str(job.id)
        )
        if resolved_file_path != file_path:
            file_path = resolved_file_path
            downloaded_preview_path = Path(file_path)

    # GPKG-01 Phase 1058: thread layer_name from request body to ogrinfo helper
    layer_name = request.layer_name if request else None

    # Validate layer_name against the file's actual layers (T-1058A-03).
    # We run ogrinfo without layer_name first to get the full layer list,
    # then validate — or use the targeted call if no validation needed.
    try:
        info = await get_catalog_port().run_ogrinfo_preview(
            file_path, layer_name=layer_name
        )
    finally:
        if downloaded_preview_path is not None:
            downloaded_preview_path.unlink(missing_ok=True)

    # GPKG-01 Phase 1058: validate user-supplied layer_name appears in the file.
    # WR-02 fix: also check against info["layer_name"] for single-layer files where
    # all_layers is None (ogr.py only sets all_layers when len(layers) > 1).
    # Without this branch a mistyped layer_name on a single-layer file silently
    # falls through and returns data for the wrong layer.
    all_layers = info.get("all_layers")  # None for single-layer files
    if layer_name is not None:
        if all_layers is not None:
            layer_names_in_file = {lyr["name"] for lyr in all_layers}
            if layer_name not in layer_names_in_file:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Layer '{layer_name}' not found in this file.",
                )
        elif info.get("layer_name") and layer_name != info["layer_name"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Layer '{layer_name}' not found in this file "
                    f"(single-layer file contains '{info['layer_name']}')."
                ),
            )

    diff = compute_schema_diff(
        dataset.column_info or [],
        info["columns"],
        dataset.feature_count,
        info["feature_count"],
    )
    schema_diff = SchemaDiff(**diff)

    # GPKG-01 Phase 1058: read the most-recent completed IngestJob's source_layer
    # to provide a pre-selection hint for the frontend layer-select UI (D-02).
    from sqlalchemy import desc

    prior_result = await db.execute(
        select(IngestJob)
        .where(
            IngestJob.dataset_id == dataset_id,
            IngestJob.status == "complete",
            IngestJob.source_layer.isnot(None),
        )
        .order_by(desc(IngestJob.completed_at))
        .limit(1)
    )
    prior_job = prior_result.scalar_one_or_none()
    previous_source_layer = prior_job.source_layer if prior_job else None

    return ReuploadPreviewResponse(
        job_id=job.id,
        source_filename=job.source_filename,
        columns=info["columns"],
        crs=info["srid"],
        geometry_type=info["geometry_type"],
        feature_count=info["feature_count"],
        sample_rows=info["sample_rows"],
        layer_name=info["layer_name"],
        schema_diff=schema_diff,
        all_layers=all_layers,
        previous_source_layer=previous_source_layer,
    )


@router.post(
    "/{dataset_id}/reupload/{job_id}/commit",
    response_model=ReuploadCommitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reupload_commit(
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    request: ReuploadCommitRequest,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadCommitResponse:
    """Commit a re-upload, queuing the background swap task."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)
    _assert_compatible_record_type(dataset, None)

    job = await _get_bound_reupload_job_or_404(
        db,
        job_id=job_id,
        dataset_id=dataset_id,
        user_id=user.id,
    )

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # Merge commit request params into user_metadata, preserving existing keys.
    # Keep token + layer_name request-only from user_metadata (layer_name goes
    # into the dedicated source_layer column — see D-03 below).
    existing_meta = dict(job.user_metadata or {})
    existing_meta.update(
        request.model_dump(exclude_none=True, exclude={"token", "layer_name"})
    )
    existing_meta["reupload"] = True
    existing_meta["dataset_id"] = str(dataset_id)
    if job.source_url and request.token:
        # Keep credentials request-only while recording that an automatic
        # retry cannot safely reproduce this authenticated request.
        existing_meta["service_auth_required"] = True
    job.user_metadata = existing_meta

    # GPKG-01 Phase 1058 (D-03): persist the user-chosen layer to the dedicated
    # IngestJob.source_layer column so the worker reads it via job.source_layer.
    # This is the canonical persistence path; user_metadata is not consulted by
    # the worker for layer selection.
    if request.layer_name is not None:
        job.source_layer = request.layer_name  # GPKG-01 Phase 1058

    await db.commit()

    # Each defer_async path is wrapped in the shared orphan guard
    # (Theme H) so a Procrastinate outage flips the committed pending
    # job to ``failed`` and returns HTTP 503 instead of leaving a ghost
    # pending row for 60 minutes until stale-cleanup catches it.
    rollback = make_ingest_job_failed_rollback(
        job, message_prefix="Failed to queue reupload task"
    )

    if job.source_url and not job.file_path:
        source_url = job.source_url

        async def _defer_service() -> None:
            await defer_async_with_tenant(
                get_catalog_port().reupload_service_task(),
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                dataset_id=str(dataset_id),
                source_url=source_url,
                source_layer=job.source_layer or "",
                user_id=str(user.id),
                token=request.token,
            )

        await defer_with_orphan_guard(_defer_service, rollback=rollback, db=db)
    else:
        # Route small files to priority queue
        import os

        if job.file_path is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Job has no file_path and no source_url — cannot queue reupload",
            )
        file_path = job.file_path

        file_size = 0
        # Only check local files; S3 paths (no leading /) use default queue
        if file_path.startswith("/"):
            try:
                if Path(file_path).exists():
                    file_size = os.path.getsize(file_path)
            except OSError:
                pass  # If we can't stat, use default queue

        if (
            file_size > 0
            and file_size <= get_catalog_port().priority_queue_threshold_bytes
        ):

            async def _defer_priority() -> None:
                await defer_async_with_tenant(
                    get_catalog_port().reupload_file_task().configure(queue="priority"),
                    job_id=str(job.id),
                    attempt_id=str(job.attempt_id),
                    dataset_id=str(dataset_id),
                    file_path=file_path,
                    user_id=str(user.id),
                )

            await defer_with_orphan_guard(_defer_priority, rollback=rollback, db=db)
        else:

            async def _defer_default() -> None:
                await defer_async_with_tenant(
                    get_catalog_port().reupload_file_task(),
                    job_id=str(job.id),
                    attempt_id=str(job.attempt_id),
                    dataset_id=str(dataset_id),
                    file_path=file_path,
                    user_id=str(user.id),
                )

            await defer_with_orphan_guard(_defer_default, rollback=rollback, db=db)

    return ReuploadCommitResponse(
        job_id=job.id,
        status="pending",
        message="Re-upload queued",
    )


# ---------------------------------------------------------------------------
# Presigned re-upload endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{dataset_id}/reupload/presigned",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
)
async def request_presigned_reupload(
    dataset_id: uuid.UUID,
    request: PresignedUploadRequest,
    http_request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> PresignedUploadResponse:
    """Request presigned URL(s) for direct-to-S3 reupload."""
    if settings.storage_provider != "s3":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Presigned uploads only available in S3 mode",
        )

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)

    _assert_compatible_record_type(dataset, request.filename)

    try:
        allowed_list = await get_allowed_extensions_list(db)
    except Exception:  # broad: persistent_config lookup must not crash reupload UI; fall back to safe default list
        allowed_list = [
            ".zip",
            ".gpkg",
            ".geojson",
            ".json",
            ".csv",
            ".tif",
            ".tiff",
            ".xlsx",
            ".xls",
        ]
    get_catalog_port().validate_file_extension(request.filename, allowed_list)

    # Reject files exceeding configured size limit at request time
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    max_size_bytes = max_size_mb * 1024 * 1024
    if request.file_size > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"File size ({request.file_size / (1024 * 1024):.1f} MB) exceeds the maximum allowed ({max_size_mb} MB).",
        )

    # QUOTA-01/02: per-user quota check before any staging or job creation.
    await check_upload_quota(db, user.id, request.file_size, http_request)

    job = await get_catalog_port().create_ingest_job(db, request.filename, "", user.id)
    job.dataset_id = dataset_id
    storage = get_storage()
    s3_key = f"staging/{job.id}/{request.filename}"
    physical_s3_key = resolve_current_storage_key(s3_key)
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024

    part_size = get_catalog_port().ingest_part_size()

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
            num_parts = math.ceil(request.file_size / part_size)
            urls = [
                await run_in_thread_draining(
                    storage.generate_presigned_part_url,
                    physical_s3_key,
                    upload_id,
                    part_num,
                )
                for part_num in range(1, num_parts + 1)
            ]
        except BaseException as exc:
            if upload_id is not None:
                await get_catalog_port().abort_presigned_multipart_upload(
                    storage,
                    key=physical_s3_key,
                    upload_id=upload_id,
                    job_id=job.id,
                )
            if isinstance(exc, asyncio.CancelledError):
                raise
            logger.exception("presigned_reupload_multipart_failed", s3_key=s3_key)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Storage service unavailable",
            ) from exc
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "upload_id": upload_id,
            "multipart": True,
            "reupload": True,
            "dataset_id": str(dataset_id),
            "expected_size": request.file_size,
        }
        try:
            await db.commit()
        except BaseException:
            await get_catalog_port().abort_presigned_multipart_upload(
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
            part_size=part_size,
        )
    else:
        url = await run_in_thread_draining(
            storage.generate_presigned_put_url,
            physical_s3_key,
            request.content_type,
        )
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "multipart": False,
            "reupload": True,
            "dataset_id": str(dataset_id),
            "expected_size": request.file_size,
        }
        await db.commit()
        return PresignedUploadResponse(
            job_id=job.id,
            urls=[url],
            s3_key=physical_s3_key,
        )


@router.post(
    "/{dataset_id}/reupload/presigned/{job_id}/complete",
    response_model=UploadResponse,
    responses={
        413: PAYLOAD_TOO_LARGE_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
)
async def complete_presigned_reupload(
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    request: PresignedCompleteRequest,
    http_request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Notify that direct-to-S3 reupload is complete."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)
    _assert_compatible_record_type(dataset, None)

    job = await _get_bound_reupload_job_or_404(
        db,
        job_id=job_id,
        dataset_id=dataset_id,
        user_id=user.id,
    )
    um = job.user_metadata or {}

    if not um.get("presigned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is not a presigned upload",
        )

    storage = get_storage()
    s3_key = um["s3_key"]
    physical_s3_key = resolve_current_storage_key(s3_key)

    if um.get("multipart"):
        if not request.parts:
            await get_catalog_port().abort_presigned_multipart_upload(
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
                await await_draining(storage.delete(physical_s3_key))
                raise completion_cancel
        except Exception as exc:  # broad: storage providers raise varied SDK errors
            await get_catalog_port().abort_presigned_multipart_upload(
                storage,
                key=physical_s3_key,
                upload_id=um.get("upload_id"),
                job_id=job.id,
            )
            logger.exception(
                "multipart_reupload_completion_failed",
                job_id=str(job.id),
                s3_key=s3_key,
                part_count=len(request.parts),
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upload completion failed — the upload session may have expired. Please try again.",
            ) from exc

    if not await storage.exists(physical_s3_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File not found in S3 after upload",
        )
    await get_catalog_port().verify_completed_presigned_upload(
        db=db,
        storage=storage,
        key=physical_s3_key,
        expected_size=um.get("expected_size"),
        user_id=user.id,
        request=http_request,
        job_id=job.id,
    )

    job.file_path = s3_key
    await db.commit()

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded for re-upload preview",
    )
