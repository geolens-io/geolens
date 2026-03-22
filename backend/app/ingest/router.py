"""Ingest API endpoints: file upload, preview, commit, and table registration."""

import asyncio
import json
import logging
import math
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_active_user, require_permission
from app.auth.models import User
from app.config import settings
from app.dependencies import get_db
from app.ingest.ogr import IngestionError, detect_geometry_columns, run_ogrinfo_preview
from app.ingest.schemas import (
    BulkRegisterRequest,
    BulkRegisterResponse,
    BulkRegisterResult,
    CommitRequest,
    CommitResponse,
    DiscoverResponse,
    PreviewResponse,
    PresignedCompleteRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
    RasterPreviewResponse,
    RegisterRequest,
    TableRegisterResponse,
    UploadConfigResponse,
    UploadResponse,
    VrtAddSourceRequest,
    VrtCreateRequest,
    VrtCreateResponse,
    VrtMutationResponse,
)
from app.ingest.service import (
    create_ingest_job,
    discover_unregistered_tables,
    get_job_or_404,
    register_existing_table,
    resolve_file_path,
    save_upload_file,
    validate_file_extension,
)
from app.ingest.tasks import ingest_file, ingest_raster, ingest_service, ingest_vrt, regenerate_vrt
from app.ingest.validation import validate_file_content
from app.raster.validation import validate_sources
from app.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["Datasets"])

PART_SIZE = 10 * 1024 * 1024  # 10MB per part
PRIORITY_QUEUE_THRESHOLD_BYTES = (
    10 * 1024 * 1024
)  # 10MB -- small files get priority queue


@router.get("/upload/config/")
async def get_upload_config(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UploadConfigResponse:
    """Return upload configuration including presigned upload availability."""
    from app.persistent_config import UPLOAD_MAX_SIZE_MB

    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    return UploadConfigResponse(
        presigned_uploads=settings.storage_provider == "s3",
        presigned_threshold_bytes=settings.presigned_multipart_threshold_mb
        * 1024
        * 1024,
        max_file_size_bytes=max_size_mb * 1024 * 1024,
    )


@router.post(
    "/upload/presigned",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_presigned_upload(
    request: PresignedUploadRequest,
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> PresignedUploadResponse:
    """Request presigned URL(s) for direct-to-S3 file upload."""
    if settings.storage_provider != "s3":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Presigned uploads only available in S3 mode",
        )

    from app.persistent_config import UPLOAD_ALLOWED_EXTENSIONS, UPLOAD_MAX_SIZE_MB

    allowed_ext_str = await UPLOAD_ALLOWED_EXTENSIONS.get(db)
    allowed_list = [e.strip() for e in allowed_ext_str.split(",")]
    validate_file_extension(request.filename, allowed_list)

    # Reject files exceeding configured size limit at request time
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    max_size_bytes = max_size_mb * 1024 * 1024
    if request.file_size > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File size ({request.file_size / (1024 * 1024):.1f} MB) exceeds the maximum allowed ({max_size_mb} MB).",
        )

    job = await create_ingest_job(db, request.filename, "", user.id)
    storage = get_storage()
    s3_key = f"staging/{job.id}/{request.filename}"
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024

    if request.file_size > threshold:
        upload_id = await asyncio.to_thread(
            storage.initiate_multipart_upload,
            s3_key,
            request.content_type,
        )
        num_parts = math.ceil(request.file_size / PART_SIZE)
        urls = []
        for part_num in range(1, num_parts + 1):
            url = await asyncio.to_thread(
                storage.generate_presigned_part_url,
                s3_key,
                upload_id,
                part_num,
            )
            urls.append(url)
        job.user_metadata = {
            "presigned": True,
            "s3_key": s3_key,
            "upload_id": upload_id,
            "multipart": True,
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
        job.user_metadata = {"presigned": True, "s3_key": s3_key, "multipart": False}
        await db.commit()
        return PresignedUploadResponse(
            job_id=job.id,
            urls=[url],
            s3_key=s3_key,
        )


@router.post("/upload/presigned/{job_id}/complete", response_model=UploadResponse)
async def complete_presigned_upload(
    job_id: uuid.UUID,
    request: PresignedCompleteRequest,
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Notify that direct-to-S3 upload is complete."""
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
        message="File uploaded and ready for preview",
    )


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """Upload a geospatial file for staging.

    Validates the file extension, creates an ingest job, and saves the file
    to staging. Does NOT auto-queue ingestion -- use preview then commit.
    """
    try:
        from app.persistent_config import UPLOAD_ALLOWED_EXTENSIONS

        allowed_ext_str = await UPLOAD_ALLOWED_EXTENSIONS.get(db)
        allowed_list = [e.strip() for e in allowed_ext_str.split(",")]
        validate_file_extension(file.filename, allowed_list)

        job = await create_ingest_job(db, file.filename, "", user.id)
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
            # Clean up: local Path or S3 key
            if isinstance(saved_path, Path):
                saved_path.unlink(missing_ok=True)
            else:
                try:
                    await get_storage().delete(saved_path)
                except Exception:
                    pass  # Best-effort cleanup
            if downloaded_validation_path is not None:
                downloaded_validation_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )
        finally:
            if downloaded_validation_path is not None:
                downloaded_validation_path.unlink(missing_ok=True)

        # Raster-specific CRS validation — reject files without valid CRS at upload time
        lower_filename = (file.filename or "").lower()
        if lower_filename.endswith((".tif", ".tiff", ".vrt")):
            from app.raster.cog import validate_raster_crs

            # Re-resolve path since downloaded_validation_path was cleaned up above
            raster_check_path: str | None = None
            _raster_downloaded: Path | None = None
            if isinstance(saved_path, Path):
                raster_check_path = str(saved_path)
            else:
                try:
                    raster_check_path = await resolve_file_path(
                        str(saved_path), str(job.id)
                    )
                    _raster_downloaded = Path(raster_check_path)
                except Exception:
                    raster_check_path = None

            if raster_check_path:
                try:
                    await asyncio.to_thread(validate_raster_crs, raster_check_path)
                except ValueError:
                    # Allow CRS-missing rasters through; user can provide
                    # srid_override at commit time.  Store flag for ingest_raster.
                    job.user_metadata = {
                        **(job.user_metadata or {}),
                        "crs_missing": True,
                    }
                finally:
                    if _raster_downloaded is not None:
                        _raster_downloaded.unlink(missing_ok=True)

            job.user_metadata = {**(job.user_metadata or {}), "file_type": "raster"}

        job.file_path = str(saved_path)
        await db.commit()

        return UploadResponse(
            job_id=job.id,
            status="pending",
            message="File uploaded and ready for preview",
        )
    except HTTPException:
        raise
    except (IngestionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception:
        logger.exception("Unexpected error during file upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during upload",
        )


@router.post(
    "/preview/{job_id}",
    response_model=None,
)
async def preview_file(
    job_id: uuid.UUID,
    layer_name: str | None = Query(None, description="Sheet/layer name for multi-layer files"),
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> PreviewResponse | RasterPreviewResponse:
    """Run preview on a staged file and return preview data.

    For vector files: returns columns, CRS, geometry type, feature count, sample rows.
    For raster files: returns band count, CRS, resolution, compliance status.
    Only callable on jobs with status 'pending'.
    """
    job = await get_job_or_404(db, job_id, user)

    if job.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job already processed",
        )

    # Resolve S3 key to local file
    file_path = job.file_path
    if file_path and not Path(file_path).exists():
        from app.ingest.service import resolve_file_path

        file_path = await resolve_file_path(file_path, str(job.id))

    # Branch: raster vs vector preview
    um = job.user_metadata or {}
    if um.get("file_type") == "raster":
        from app.raster.cog import check_cog_compliance, extract_raster_metadata

        meta, (compliant, reason) = await asyncio.gather(
            asyncio.to_thread(extract_raster_metadata, file_path),
            asyncio.to_thread(check_cog_compliance, file_path),
        )
        file_size: int | None = None
        try:
            import os

            file_size = os.path.getsize(file_path)
        except OSError:
            pass

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

    info = await run_ogrinfo_preview(file_path, layer_name=layer_name)

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


@router.post(
    "/commit/{job_id}",
    response_model=CommitResponse,
)
async def commit_import(
    job_id: uuid.UUID,
    request: CommitRequest,
    user: User = Depends(require_permission("upload")),
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

    # Store user metadata on the job (merge with existing user_metadata for service jobs)
    # Exclude token from persisted metadata (AUTH-04: never store token in DB)
    token = request.token
    commit_metadata = request.model_dump(exclude={"token"})
    if job.user_metadata:
        # Service jobs already have service_type and layer_id from preview
        merged = {**job.user_metadata, **commit_metadata}
        job.user_metadata = merged
    else:
        job.user_metadata = commit_metadata
    await db.commit()

    if job.source_url and not job.file_path:
        # Service job — route to ingest_service
        await ingest_service.defer_async(
            job_id=str(job.id),
            source_url=job.source_url,
            source_layer=job.source_layer or "",
            user_id=str(user.id),
            token=token,
        )
    elif (job.user_metadata or {}).get("file_type") == "raster":
        # Raster file job — route to dedicated raster queue
        await ingest_raster.defer_async(
            job_id=str(job.id),
            file_path=job.file_path,
            user_id=str(user.id),
        )
    else:
        # File job -- route small files to priority queue
        import os

        file_size = 0
        # Only check local files; S3 paths (no leading /) use default queue
        if job.file_path and job.file_path.startswith("/"):
            try:
                if Path(job.file_path).exists():
                    file_size = os.path.getsize(job.file_path)
            except OSError:
                pass  # If we can't stat, use default queue

        if file_size > 0 and file_size <= PRIORITY_QUEUE_THRESHOLD_BYTES:
            await ingest_file.configure(queue="priority").defer_async(
                job_id=str(job.id),
                file_path=job.file_path,
                user_id=str(user.id),
            )
        else:
            await ingest_file.defer_async(
                job_id=str(job.id),
                file_path=job.file_path,
                user_id=str(user.id),
            )

    return CommitResponse(
        job_id=job.id,
        status="pending",
        message="Import queued",
    )


@router.post(
    "/register",
    response_model=TableRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_table(
    request: RegisterRequest,
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> TableRegisterResponse:
    """Register an existing PostGIS table as a dataset.

    Verifies the table exists, extracts metadata, and creates a
    catalog entry.
    """
    try:
        dataset = await register_existing_table(db, request, user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
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
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> DiscoverResponse:
    """Discover unregistered tables in the data schema.

    Returns tables not yet in the catalog, excluding staging, old, and
    system tables. Includes geometry type, SRID, and estimated row count.
    """
    tables = await discover_unregistered_tables(db)
    return DiscoverResponse(tables=tables)


@router.post(
    "/register/bulk/",
    response_model=BulkRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_register_tables(
    request: BulkRegisterRequest,
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> BulkRegisterResponse:
    """Bulk-register multiple existing PostGIS tables as datasets.

    Each table is registered independently -- one failure does not block
    others. Returns per-table success/error results.
    """
    results = []
    for table_req in request.tables:
        try:
            reg_request = RegisterRequest(
                table_name=table_req.table_name,
                title=table_req.title,
                summary=table_req.summary,
                visibility=table_req.visibility,
            )
            dataset = await register_existing_table(db, reg_request, user)
            await db.commit()
            results.append(
                BulkRegisterResult(
                    table_name=table_req.table_name,
                    dataset_id=dataset.id,
                    title=dataset.record.title,
                    status="success",
                )
            )
        except Exception as exc:
            await db.rollback()
            results.append(
                BulkRegisterResult(
                    table_name=table_req.table_name,
                    status="error",
                    error=str(exc),
                )
            )
    return BulkRegisterResponse(results=results)


@router.post("/vrt/create/", response_model=VrtCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_vrt(
    request: VrtCreateRequest,
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> VrtCreateResponse:
    """Create a VRT dataset by combining existing raster datasets.

    Validates sources synchronously, then defers VRT assembly to an async task.
    Returns a job_id for polling.
    """
    from app.datasets.models import Dataset, Record
    from app.raster.models import RasterAsset

    # 1. Validate minimum source count
    if len(request.source_dataset_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least 2 source datasets are required to create a VRT",
        )

    # 2. Load RasterAsset rows for each source dataset
    result = await db.execute(
        select(RasterAsset)
        .join(Dataset, RasterAsset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(
            Dataset.id.in_(request.source_dataset_ids),
            Record.record_type == "raster_dataset",
        )
    )
    found_assets = result.scalars().all()

    # 3. Check all requested IDs were found and are raster_datasets
    found_dataset_ids = {asset.dataset_id for asset in found_assets}
    for sid in request.source_dataset_ids:
        if sid not in found_dataset_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Source dataset {sid} not found or not a raster dataset",
            )

    # 4. Validate source compatibility
    errors = validate_sources(request.vrt_type, list(found_assets))
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[e.model_dump() for e in errors],
        )

    # 5. Create IngestJob
    job = await create_ingest_job(db, f"vrt_{request.vrt_type}", "", user.id)
    job.user_metadata = {
        "vrt_type": request.vrt_type,
        "title": request.title,
        "summary": request.summary,
        "visibility": request.visibility,
    }
    await db.commit()

    # 6. Defer async VRT assembly task
    await ingest_vrt.defer_async(
        job_id=str(job.id),
        user_id=str(user.id),
        source_dataset_ids=json.dumps([str(sid) for sid in request.source_dataset_ids]),
        vrt_type=request.vrt_type,
        resolution_strategy=request.resolution_strategy,
    )

    return VrtCreateResponse(job_id=job.id, message="VRT creation queued")


@router.post(
    "/vrt/{dataset_id}/sources/",
    response_model=VrtMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def add_vrt_source(
    dataset_id: uuid.UUID,
    request: VrtAddSourceRequest,
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> VrtMutationResponse:
    """Add a COG source to an existing VRT and trigger async regeneration.

    Validates the new source against existing sources synchronously.
    Returns 202 Accepted with a job_id for polling.
    Returns 409 if the VRT is currently regenerating (SRC-05) or source already linked.
    Returns 422 if the source is incompatible with existing sources.
    """
    from app.datasets.models import Dataset, Record
    from app.raster.models import RasterAsset
    from sqlalchemy import text

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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Source dataset {request.source_dataset_id} not found or not a raster dataset",
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

    errors = validate_sources(vrt_asset.vrt_type, all_assets)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[e.model_dump() for e in errors],
        )

    # 6. Get max position for new link
    max_pos_result = await db.execute(
        text(
            "SELECT COALESCE(MAX(position), -1) FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id"
        ),
        {"vrt_id": dataset_id},
    )
    max_position = max_pos_result.scalar()

    # 7. Insert new source link
    await db.execute(
        text(
            "INSERT INTO catalog.vrt_source_links(vrt_dataset_id, source_dataset_id, position) "
            "VALUES (:vrt_id, :src_id, :pos)"
        ),
        {
            "vrt_id": dataset_id,
            "src_id": request.source_dataset_id,
            "pos": max_position + 1,
        },
    )

    # 8. Set VRT status to regenerating
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = uuid.uuid4()

    # 9. Create IngestJob
    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    # 10. Commit + dispatch
    await db.commit()
    await regenerate_vrt.defer_async(
        job_id=str(job.id),
        vrt_dataset_id=str(dataset_id),
        triggered_by=str(user.id),
    )

    return VrtMutationResponse(job_id=job.id, message="Source added, VRT regeneration started")


@router.delete(
    "/vrt/{dataset_id}/sources/{source_dataset_id}/",
    response_model=VrtMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def remove_vrt_source(
    dataset_id: uuid.UUID,
    source_dataset_id: uuid.UUID,
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> VrtMutationResponse:
    """Remove a COG source from an existing VRT and trigger async regeneration.

    Returns 202 Accepted with a job_id for polling.
    Returns 409 if the VRT is currently regenerating (SRC-05).
    Returns 422 if removing would leave fewer than 2 sources.
    Returns 404 if the source is not linked to the VRT.
    """
    from app.datasets.models import Dataset, Record
    from app.raster.models import RasterAsset
    from sqlalchemy import text

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

    # 3. Check minimum source count guard
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :vrt_id"
        ),
        {"vrt_id": dataset_id},
    )
    source_count = count_result.scalar()
    if source_count <= 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Removing this source would leave fewer than 2 sources. A VRT requires at least 2 sources.",
        )

    # 4. Check source link exists
    link_result = await db.execute(
        text(
            "SELECT 1 FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id AND source_dataset_id = :src_id"
        ),
        {"vrt_id": dataset_id, "src_id": source_dataset_id},
    )
    if link_result.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not linked to this VRT",
        )

    # 5. Delete the source link
    await db.execute(
        text(
            "DELETE FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id AND source_dataset_id = :src_id"
        ),
        {"vrt_id": dataset_id, "src_id": source_dataset_id},
    )

    # 6. Set VRT status to regenerating
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = uuid.uuid4()

    # 7. Create IngestJob
    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    # 8. Commit + dispatch
    await db.commit()
    await regenerate_vrt.defer_async(
        job_id=str(job.id),
        vrt_dataset_id=str(dataset_id),
        triggered_by=str(user.id),
    )

    return VrtMutationResponse(job_id=job.id, message="Source removed, VRT regeneration started")
