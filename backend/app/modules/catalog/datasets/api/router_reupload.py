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

from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import check_dataset_access
from app.core.config import settings
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
from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview
from app.modules.catalog.sources.security import SSRFError, validate_url_for_ssrf
from app.platform.storage import get_storage
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Reupload"], responses=ERROR_RESPONSES_WRITE
)

_catalog_port = get_catalog_port()
IngestionError = _catalog_port.ingestion_error_class()
PresignedCompleteRequest = _catalog_port.presigned_complete_request_model()
PresignedUploadRequest = _catalog_port.presigned_upload_request_model()
PresignedUploadResponse = _catalog_port.presigned_upload_response_model()
UploadResponse = _catalog_port.upload_response_model()

# Extension sets used for cross-record-type validation.
# Do NOT depend on the runtime allowed_extensions config (which merges all types).
_RASTER_EXTENSIONS: frozenset[str] = frozenset({".tif", ".tiff"})
_VECTOR_EXTENSIONS: frozenset[str] = frozenset({
    ".zip", ".gpkg", ".geojson", ".json", ".csv", ".xlsx", ".xls"
})


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

    File paths (`reupload_dataset`, `request_presigned_reupload`) pass a filename
    and the helper checks the file extension. Service paths
    (`reupload_service_preview`) pass `service_type` instead — all supported
    service types (WFS, ArcGIS FeatureServer, OGC API – Features) are vector, so
    any non-vector record type is rejected.

    IA-P1-02 (Phase 1065 plan 03): service-URL guard added — VRT rejection +
    raster-vs-vector-service mismatch surfaced early.

    Audit action `reupload.commit` is shipped — see test_provenance_attribution.py.
    Do not rename to `dataset.reupload`.
    """
    record_type: str = dataset.record.record_type
    ext: str = Path(filename or "").suffix.lower()

    if record_type == "vrt_dataset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "VRT datasets do not support file reupload — "
                "edit the VRT membership instead."
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

    if record_type == "raster_dataset" and ext in _VECTOR_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This dataset is a raster dataset; "
                "only .tif/.tiff files are supported for reupload."
            ),
        )

    if service_type is not None and record_type == "raster_dataset":
        # All supported service types (WFS*, ArcGIS*, OGC API*) are vector sources.
        # Pinned by tasks_common._classify_service_type which only accepts these prefixes.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This dataset is a raster dataset; "
                "vector services (WFS, ArcGIS FeatureServer, OGC API – Features) "
                "are not supported for reupload."
            ),
        )


@router.post(
    "/{dataset_id}/reupload",
    response_model=ReuploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reupload_dataset(
    dataset_id: uuid.UUID,
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
    await check_dataset_access(db, dataset, dataset_id, user)

    _assert_compatible_record_type(dataset, file.filename)

    try:
        allowed_list = await get_allowed_extensions_list(db)
        get_catalog_port().validate_file_extension(file.filename, allowed_list)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    job = await get_catalog_port().create_ingest_job(db, file.filename, "", user.id)
    job.dataset_id = dataset_id
    job.user_metadata = {"reupload": True, "dataset_id": str(dataset_id)}

    saved_path = await get_catalog_port().save_upload_file(file, str(job.id))
    validation_path = str(saved_path)
    downloaded_validation_path: Path | None = None

    if not isinstance(saved_path, Path):
        validation_path = await get_catalog_port().resolve_file_path(
            saved_path, str(job.id)
        )
        downloaded_validation_path = Path(validation_path)

    # Inline content validation for immediate feedback
    try:
        get_catalog_port().validate_file_content(validation_path, file.filename)
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
    await check_dataset_access(db, dataset, dataset_id, user)

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
    await check_dataset_access(db, dataset, dataset_id, user)

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
        file_path = await get_catalog_port().resolve_file_path(file_path, str(job.id))

    # GPKG-01 Phase 1058: thread layer_name from request body to ogrinfo helper
    layer_name = request.layer_name if request else None

    # Validate layer_name against the file's actual layers (T-1058A-03).
    # We run ogrinfo without layer_name first to get the full layer list,
    # then validate — or use the targeted call if no validation needed.
    info = await get_catalog_port().run_ogrinfo_preview(file_path, layer_name=layer_name)

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
    await check_dataset_access(db, dataset, dataset_id, user)

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
    # Keep token + layer_name request-only from user_metadata (layer_name goes
    # into the dedicated source_layer column — see D-03 below).
    existing_meta = job.user_metadata or {}
    existing_meta.update(request.model_dump(exclude_none=True, exclude={"token", "layer_name"}))
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
            await (
                get_catalog_port()
                .reupload_service_task()
                .defer_async(
                    job_id=str(job.id),
                    dataset_id=str(dataset_id),
                    source_url=source_url,
                    source_layer=job.source_layer or "",
                    user_id=str(user.id),
                    token=request.token,
                )
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
                await (
                    get_catalog_port()
                    .reupload_file_task()
                    .configure(queue="priority")
                    .defer_async(
                        job_id=str(job.id),
                        dataset_id=str(dataset_id),
                        file_path=file_path,
                        user_id=str(user.id),
                    )
                )

            await defer_with_orphan_guard(_defer_priority, rollback=rollback, db=db)
        else:

            async def _defer_default() -> None:
                await (
                    get_catalog_port()
                    .reupload_file_task()
                    .defer_async(
                        job_id=str(job.id),
                        dataset_id=str(dataset_id),
                        file_path=file_path,
                        user_id=str(user.id),
                    )
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
    await check_dataset_access(db, dataset, dataset_id, user)

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

    job = await get_catalog_port().create_ingest_job(db, request.filename, "", user.id)
    job.dataset_id = dataset_id
    storage = get_storage()
    s3_key = f"staging/{job.id}/{request.filename}"
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024

    part_size = get_catalog_port().ingest_part_size()

    if request.file_size > threshold:
        upload_id = await asyncio.to_thread(
            storage.initiate_multipart_upload,
            s3_key,
            request.content_type,
        )
        num_parts = math.ceil(request.file_size / part_size)
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
            part_size=part_size,
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
    await check_dataset_access(db, dataset, dataset_id, user)

    job = await get_catalog_port().get_ingest_job_or_404(db, job_id, user)
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
