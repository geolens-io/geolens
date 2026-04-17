"""Dataset reupload and presigned reupload endpoints."""

import asyncio
import math
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import require_permission
from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.datasets.domain.schemas import (
    ReuploadCommitRequest,
    ReuploadCommitResponse,
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
from app.processing.ingest.constants import PRIORITY_QUEUE_THRESHOLD_BYTES
from app.processing.ingest.ogr import IngestionError, run_ogrinfo_preview
from app.processing.ingest.schemas import (
    PresignedCompleteRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
    UploadResponse,
)
from app.processing.ingest.service import (
    create_ingest_job,
    resolve_file_path,
    save_upload_file,
    validate_file_extension,
)
from app.processing.ingest.tasks import reupload_file, reupload_service
from app.processing.ingest.validation import validate_file_content
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import IngestJob
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB, get_allowed_extensions_list
from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview
from app.modules.catalog.sources.security import SSRFError, validate_url_for_ssrf
from app.platform.storage import get_storage

router = APIRouter(prefix="/datasets", tags=["Datasets - Reupload"])


@router.post(
    "/{dataset_id}/reupload",
    response_model=ReuploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reupload_dataset(
    dataset_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadResponse:
    """Upload a new file to replace the data in an existing dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    try:
        allowed_list = await get_allowed_extensions_list(db)
        validate_file_extension(file.filename, allowed_list)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    job = await create_ingest_job(db, file.filename, "", user.id)
    job.dataset_id = dataset_id
    job.user_metadata = {"reupload": True, "dataset_id": str(dataset_id)}

    saved_path = await save_upload_file(file, str(job.id))
    validation_path = str(saved_path)
    downloaded_validation_path: Path | None = None

    if not isinstance(saved_path, Path):
        validation_path = await resolve_file_path(saved_path, str(job.id))
        downloaded_validation_path = Path(validation_path)

    # Inline content validation for immediate feedback
    try:
        validate_file_content(validation_path, file.filename)
    except ValueError as exc:
        if isinstance(saved_path, Path):
            saved_path.unlink(missing_ok=True)
        else:
            storage = get_storage()
            await storage.delete(saved_path)
        if downloaded_validation_path is not None:
            downloaded_validation_path.unlink(missing_ok=True)
        # Mark the job as failed so it doesn't linger as a dangling pending row
        job.status = "failed"
        job.error_message = str(exc)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )
    finally:
        if downloaded_validation_path is not None:
            downloaded_validation_path.unlink(missing_ok=True)

    job.file_path = str(saved_path)
    await db.commit()

    return ReuploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded for re-upload preview",
    )


@router.post(
    "/{dataset_id}/reupload/service/preview",
    response_model=ReuploadPreviewResponse,
)
async def reupload_service_preview(
    dataset_id: uuid.UUID,
    request: ReuploadServicePreviewRequest,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadPreviewResponse:
    """Preview a remote service layer for dataset re-upload."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    try:
        validate_url_for_ssrf(request.url)
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
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadPreviewResponse:
    """Preview the schema diff between old dataset and new upload."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Validate job belongs to this dataset
    job_dataset_id = job.dataset_id or (
        job.user_metadata.get("dataset_id") if job.user_metadata else None
    )
    if job_dataset_id is not None and str(job_dataset_id) != str(dataset_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job does not belong to this dataset",
        )

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # Resolve S3 key to local file for ogrinfo
    file_path = job.file_path
    if file_path and not Path(file_path).exists():
        from app.processing.ingest.service import resolve_file_path

        file_path = await resolve_file_path(file_path, str(job.id))

    info = await run_ogrinfo_preview(file_path)

    diff = compute_schema_diff(
        dataset.column_info or [],
        info["columns"],
        dataset.feature_count,
        info["feature_count"],
    )
    schema_diff = SchemaDiff(**diff)

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
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ReuploadCommitResponse:
    """Commit a re-upload, queuing the background swap task."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    result = await db.execute(select(IngestJob).where(IngestJob.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Validate job belongs to this dataset
    job_dataset_id = job.dataset_id or (
        job.user_metadata.get("dataset_id") if job.user_metadata else None
    )
    if job_dataset_id is not None and str(job_dataset_id) != str(dataset_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job does not belong to this dataset",
        )

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # Merge commit request params into user_metadata, preserving existing keys.
    # Keep token request-only (never persisted).
    existing_meta = job.user_metadata or {}
    existing_meta.update(request.model_dump(exclude_none=True, exclude={"token"}))
    job.user_metadata = existing_meta
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
            await reupload_service.defer_async(
                job_id=str(job.id),
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

        if file_size > 0 and file_size <= PRIORITY_QUEUE_THRESHOLD_BYTES:

            async def _defer_priority() -> None:
                await reupload_file.configure(queue="priority").defer_async(
                    job_id=str(job.id),
                    dataset_id=str(dataset_id),
                    file_path=file_path,
                    user_id=str(user.id),
                )

            await defer_with_orphan_guard(_defer_priority, rollback=rollback, db=db)
        else:

            async def _defer_default() -> None:
                await reupload_file.defer_async(
                    job_id=str(job.id),
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
)
async def request_presigned_reupload(
    dataset_id: uuid.UUID,
    request: PresignedUploadRequest,
    user: User = Depends(require_permission("edit_metadata")),
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

    try:
        allowed_list = await get_allowed_extensions_list(db)
    except Exception:
        allowed_list = [".zip", ".gpkg", ".geojson", ".json", ".csv", ".tif", ".tiff", ".xlsx", ".xls"]
    validate_file_extension(request.filename, allowed_list)

    # Reject files exceeding configured size limit at request time
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    max_size_bytes = max_size_mb * 1024 * 1024
    if request.file_size > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"File size ({request.file_size / (1024 * 1024):.1f} MB) exceeds the maximum allowed ({max_size_mb} MB).",
        )

    job = await create_ingest_job(db, request.filename, "", user.id)
    job.dataset_id = dataset_id
    storage = get_storage()
    s3_key = f"staging/{job.id}/{request.filename}"
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024

    from app.processing.ingest.router import PART_SIZE

    if request.file_size > threshold:
        upload_id = await asyncio.to_thread(
            storage.initiate_multipart_upload,
            s3_key,
            request.content_type,
        )
        num_parts = math.ceil(request.file_size / PART_SIZE)
        urls = list(
            await asyncio.gather(
                *[
                    asyncio.to_thread(
                        storage.generate_presigned_part_url,
                        s3_key,
                        upload_id,
                        part_num,
                    )
                    for part_num in range(1, num_parts + 1)
                ]
            )
        )
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "upload_id": upload_id,
            "multipart": True,
            "reupload": True,
            "dataset_id": str(dataset_id),
        }
        await db.commit()
        return PresignedUploadResponse(
            job_id=job.id,
            urls=urls,
            s3_key=s3_key,
            upload_id=upload_id,
            part_size=PART_SIZE,
        )
    else:
        url = await asyncio.to_thread(
            storage.generate_presigned_put_url,
            s3_key,
            request.content_type,
        )
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "multipart": False,
            "reupload": True,
            "dataset_id": str(dataset_id),
        }
        await db.commit()
        return PresignedUploadResponse(
            job_id=job.id,
            urls=[url],
            s3_key=s3_key,
        )


@router.post(
    "/{dataset_id}/reupload/presigned/{job_id}/complete",
    response_model=UploadResponse,
)
async def complete_presigned_reupload(
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    request: PresignedCompleteRequest,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Notify that direct-to-S3 reupload is complete."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    from app.processing.ingest.service import get_job_or_404

    job = await get_job_or_404(db, job_id, user)
    um = job.user_metadata or {}

    if not um.get("presigned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is not a presigned upload",
        )

    storage = get_storage()
    s3_key = um["s3_key"]

    if um.get("multipart") and request.parts:
        await asyncio.to_thread(
            storage.complete_multipart_upload,
            s3_key,
            um["upload_id"],
            [{"ETag": p.etag, "PartNumber": p.part_number} for p in request.parts],
        )

    if not await storage.exists(s3_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File not found in S3 after upload",
        )

    job.file_path = s3_key
    await db.commit()

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded for re-upload preview",
    )
