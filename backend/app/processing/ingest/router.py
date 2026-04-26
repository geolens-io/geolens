"""Ingest API endpoints: file upload, preview, commit, and table registration."""

import asyncio
import math
import uuid
from datetime import datetime, timezone

import structlog
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

if TYPE_CHECKING:
    from app.platform.jobs.models import IngestJob
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import get_current_active_user, require_permission
from app.modules.auth.models import User
from app.core.config import settings
from app.core.dependencies import get_db
from app.processing.ingest.ogr import (
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
    VectorCommitRequest,
    VrtAddSourceRequest,
    VrtCreateRequest,
    VrtCreateResponse,
    VrtMutationResponse,
)
from app.processing.ingest.service import (
    create_ingest_job,
    discover_unregistered_tables,
    get_job_or_404,
    queue_ingest_job,
    register_existing_table,
    resolve_file_path,
    save_upload_file,
    validate_file_extension,
)
from app.processing.ingest.tasks import regenerate_vrt
from app.processing.ingest.validation import validate_file_content
from app.platform.jobs.defer_guard import defer_with_orphan_guard
from app.core.persistent_config import (
    UPLOAD_ALLOWED_EXTENSIONS,
    UPLOAD_MAX_SIZE_MB,
    get_allowed_extensions_list,
)
from app.processing.raster.validation import validate_sources
from app.platform.storage import get_storage
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ingest", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE)

PART_SIZE = 10 * 1024 * 1024  # 10MB per part

# Fallback list used when the persistent_config DB lookup fails (R-7).
# Kept intentionally conservative: matches the original production default.
# Canonical source: UPLOAD_ALLOWED_EXTENSIONS in app/core/persistent_config.py.
_FALLBACK_ALLOWED_EXTENSIONS: list[str] = [
    ".geojson",
    ".json",
    ".csv",
    ".xlsx",
    ".gpkg",
    ".zip",
    ".tif",
    ".tiff",
    ".vrt",
]


async def _get_allowed_extensions_safely(db: AsyncSession) -> list[str]:
    """Load allowed upload extensions with a DB-failure fallback (R-7).

    A transient DB hiccup during config lookup previously crashed the
    entire upload endpoint with a 500. Fall back to a safe default and
    log the failure so operators can investigate without losing uploads.
    """
    try:
        return await get_allowed_extensions_list(db)
    except Exception as exc:
        logger.warning(
            "Failed to load allowed extensions from persistent_config — using fallback",
            error=str(exc),
        )
        return list(_FALLBACK_ALLOWED_EXTENSIONS)


@router.get("/upload/config", response_model=UploadConfigResponse)
async def get_upload_config(
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UploadConfigResponse:
    """Return upload configuration including presigned upload availability."""
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)
    allowed_exts = await UPLOAD_ALLOWED_EXTENSIONS.get(db)
    return UploadConfigResponse(
        presigned_uploads=settings.storage_provider == "s3",
        presigned_threshold_bytes=settings.presigned_multipart_threshold_mb
        * 1024
        * 1024,
        max_file_size_bytes=max_size_mb * 1024 * 1024,
        allowed_extensions=allowed_exts,
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

    allowed_list = await _get_allowed_extensions_safely(db)
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
    storage = get_storage()
    s3_key = f"staging/{job.id}/{request.filename}"
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024

    if request.file_size > threshold:
        try:
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
        except Exception:
            logger.exception("presigned_multipart_failed", s3_key=s3_key)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Storage service unavailable",
            )
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
        try:
            url = await asyncio.to_thread(
                storage.generate_presigned_put_url,
                s3_key,
                request.content_type,
            )
        except Exception:
            logger.exception("presigned_put_failed", s3_key=s3_key)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Storage service unavailable",
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
        try:
            await asyncio.to_thread(
                storage.complete_multipart_upload,
                s3_key,
                um["upload_id"],
                [{"ETag": p.etag, "PartNumber": p.part_number} for p in request.parts],
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Upload completion failed — the upload session may have expired. Please try again.",
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
        await get_storage().delete(saved_path)
    except (
        Exception
    ):  # broad: S3 SDK can raise various error types; cleanup is best-effort
        logger.warning(
            "S3 cleanup failed during validation error — file may be orphaned",
            s3_key=str(saved_path),
            job_id=job_id,
        )


async def _stamp_raster_metadata(
    job: "IngestJob",
    saved_path: Path | str,
    filename: str | None,
) -> None:
    """Perform raster CRS validation and stamp job.user_metadata accordingly.

    Non-fatal: missing CRS is acceptable at upload time (the user can supply
    srid_override at commit time). This helper isolates the raster-specific
    branch from the main upload flow (KISS-N9).
    """
    lower_filename = (filename or "").lower()
    if not lower_filename.endswith((".tif", ".tiff", ".vrt")):
        return

    from app.processing.raster.cog import validate_raster_crs

    raster_check_path: str | None = None
    downloaded: Path | None = None
    if isinstance(saved_path, Path):
        raster_check_path = str(saved_path)
    else:
        try:
            raster_check_path = await resolve_file_path(str(saved_path), str(job.id))
            downloaded = Path(raster_check_path)
        except (
            Exception
        ):  # broad: S3 download can fail for network/auth/key-not-found reasons
            raster_check_path = None

    if raster_check_path:
        try:
            await asyncio.to_thread(validate_raster_crs, raster_check_path)
        except ValueError:
            # Allow CRS-missing rasters through; user can provide
            # srid_override at commit time. Store flag for ingest_raster.
            job.user_metadata = {
                **(job.user_metadata or {}),
                "crs_missing": True,
            }
        finally:
            if downloaded is not None:
                downloaded.unlink(missing_ok=True)

    job.user_metadata = {**(job.user_metadata or {}), "file_type": "raster"}


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
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload missing filename",
        )
    try:
        allowed_list = await _get_allowed_extensions_safely(db)
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
            await _cleanup_saved_upload(saved_path, str(job.id))
            if downloaded_validation_path is not None:
                downloaded_validation_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            )
        finally:
            if downloaded_validation_path is not None:
                downloaded_validation_path.unlink(missing_ok=True)

        # Raster-specific CRS validation — reject files without valid CRS at upload time
        await _stamp_raster_metadata(job, saved_path, file.filename)

        job.file_path = str(saved_path)
        await db.commit()

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
    "/preview/{job_id}",
    response_model=PreviewResponse | RasterPreviewResponse,
)
async def preview_file(
    job_id: uuid.UUID,
    layer_name: str | None = Query(
        None, description="Sheet/layer name for multi-layer files"
    ),
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
    if not job.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no associated file — upload must complete before preview",
        )
    file_path: str = job.file_path
    if not Path(file_path).exists():
        from app.processing.ingest.service import resolve_file_path

        file_path = await resolve_file_path(file_path, str(job.id))

    # Branch: raster vs vector preview
    um = job.user_metadata or {}
    if um.get("file_type") == "raster":
        from app.processing.raster.cog import (
            check_cog_compliance,
            extract_raster_metadata,
        )

        try:
            meta, (compliant, reason) = await asyncio.gather(
                asyncio.to_thread(extract_raster_metadata, file_path),
                asyncio.to_thread(check_cog_compliance, file_path),
            )
        except (
            Exception
        ) as exc:  # broad: rasterio/GDAL can raise various errors on malformed files
            logger.warning("raster_preview failed", job_id=str(job_id), error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unable to preview raster file: {exc}",
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

    try:
        info = await run_ogrinfo_preview(file_path, layer_name=layer_name)
    except Exception as exc:  # broad: GDAL subprocess can raise various errors on unsupported/malformed files
        logger.warning("ogrinfo_preview failed", job_id=str(job_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unable to preview file: {exc}",
        )

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

    # Extract token only for service commits (ServiceCommitRequest is the
    # only subclass with a token field). AUTH-04: never persisted.
    token = getattr(commit, "token", None)

    # Persist the subclass-filtered view. model_dump(exclude={"token"}) is
    # a no-op when the subclass has no token field. mode="json" so datetime
    # fields (temporal_start/temporal_end) serialize as ISO strings before
    # going into the JSONB column.
    commit_metadata = commit.model_dump(exclude={"token"}, mode="json")
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
    except Exception:
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
    "/register/",
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
    user: User = Depends(require_permission("upload")),
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
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> BulkRegisterResponse:
    """Bulk-register multiple existing PostGIS tables as datasets.

    Each table is registered independently -- one failure does not block
    others. Tables are processed in parallel via ``asyncio.gather`` with
    a fresh session per task, which keeps transaction isolation while
    removing the sequential per-table latency (PERF-3).
    """
    from app.core.db import async_session

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
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> VrtCreateResponse:
    """Create a VRT dataset by combining existing raster datasets.

    Validates sources synchronously, then defers VRT assembly to an async task.
    Returns a job_id for polling. Validation + queuing logic lives in
    ``ingest.service.create_vrt_job`` (K5 extraction).
    """
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
    user: User = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> VrtMutationResponse:
    """Add a COG source to an existing VRT and trigger async regeneration.

    Validates the new source against existing sources synchronously.
    Returns 202 Accepted with a job_id for polling.
    Returns 409 if the VRT is currently regenerating (SRC-05) or source already linked.
    Returns 422 if the source is incompatible with existing sources.
    """
    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.processing.raster.models import RasterAsset
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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

    # 6. Get max position for new link. COALESCE(..., -1) guarantees non-null
    # in SQL but mypy sees Any|None — default to -1 so the arithmetic is safe.
    max_pos_result = await db.execute(
        text(
            "SELECT COALESCE(MAX(position), -1) FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id"
        ),
        {"vrt_id": dataset_id},
    )
    max_position = max_pos_result.scalar()
    if max_position is None:
        max_position = -1

    # 7. Insert new source link
    new_link_position = max_position + 1
    await db.execute(
        text(
            "INSERT INTO catalog.vrt_source_links(vrt_dataset_id, source_dataset_id, position) "
            "VALUES (:vrt_id, :src_id, :pos)"
        ),
        {
            "vrt_id": dataset_id,
            "src_id": request.source_dataset_id,
            "pos": new_link_position,
        },
    )

    # 8. Set VRT status to regenerating — capture pre-mutation values so
    # the orphan-guard rollback (Theme H) can restore them if Procrastinate
    # is unreachable.
    previous_status = vrt_asset.status
    previous_generation_id = vrt_asset.current_generation_id
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = uuid.uuid4()

    # 9. Create IngestJob
    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    # 10. Commit + dispatch.
    # Unlike IngestJob orphans (rescued by 60-minute stale-cleanup), there
    # is NO sweep for VRT assets stuck in ``status="regenerating"``. If
    # Procrastinate is unreachable, the rollback below reverts the VRT
    # asset state, deletes the inserted source link, and marks the job
    # failed before re-raising as HTTP 503 — otherwise the VRT would be
    # permanently stuck until an operator manually intervenes.
    await db.commit()

    inserted_source_id = request.source_dataset_id

    async def _defer() -> None:
        await regenerate_vrt.defer_async(
            job_id=str(job.id),
            vrt_dataset_id=str(dataset_id),
            triggered_by=str(user.id),
        )

    async def _rollback(defer_exc: BaseException) -> None:
        # Revert VRT asset state to what it was before step 8.
        vrt_asset.status = previous_status
        vrt_asset.current_generation_id = previous_generation_id
        # Delete the source link we just inserted so the VRT matches
        # its pre-mutation source set.
        await db.execute(
            text(
                "DELETE FROM catalog.vrt_source_links "
                "WHERE vrt_dataset_id = :vrt_id AND source_dataset_id = :src_id"
            ),
            {"vrt_id": dataset_id, "src_id": inserted_source_id},
        )
        # Mark the IngestJob failed so /jobs listings reflect reality.
        job.status = "failed"
        job.error_message = f"Failed to queue VRT regeneration: {defer_exc}"
        job.completed_at = datetime.now(timezone.utc)

    await defer_with_orphan_guard(_defer, rollback=_rollback, db=db)

    return VrtMutationResponse(
        job_id=job.id, message="Source added, VRT regeneration started"
    )


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
    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.processing.raster.models import RasterAsset
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

    # 3. Check minimum source count guard. COUNT(*) is non-null but mypy
    # sees Any|None from scalar() — default to 0 so the comparison is safe.
    count_result = await db.execute(
        text(
            "SELECT COUNT(*) FROM catalog.vrt_source_links WHERE vrt_dataset_id = :vrt_id"
        ),
        {"vrt_id": dataset_id},
    )
    source_count = count_result.scalar() or 0
    if source_count <= 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Removing this source would leave fewer than 2 sources. A VRT requires at least 2 sources.",
        )

    # 4. Check source link exists — also capture its position so the
    # orphan-guard rollback (Theme H) can re-insert it with the original
    # ordering if the defer fails.
    link_result = await db.execute(
        text(
            "SELECT position FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id AND source_dataset_id = :src_id"
        ),
        {"vrt_id": dataset_id, "src_id": source_dataset_id},
    )
    link_row = link_result.fetchone()
    if link_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source not linked to this VRT",
        )
    deleted_link_position = link_row.position

    # 5. Delete the source link
    await db.execute(
        text(
            "DELETE FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :vrt_id AND source_dataset_id = :src_id"
        ),
        {"vrt_id": dataset_id, "src_id": source_dataset_id},
    )

    # 6. Set VRT status to regenerating — capture pre-mutation values.
    previous_status = vrt_asset.status
    previous_generation_id = vrt_asset.current_generation_id
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = uuid.uuid4()

    # 7. Create IngestJob
    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id

    # 8. Commit + dispatch with orphan guard (Theme H).
    # No stale-cleanup sweep exists for VRT ``status="regenerating"``, so
    # a Procrastinate outage would leave the VRT permanently stuck and
    # the deleted source link gone until manual operator intervention.
    # The rollback below re-inserts the link with its original position,
    # reverts the VRT asset state, and marks the job failed.
    await db.commit()

    async def _defer() -> None:
        await regenerate_vrt.defer_async(
            job_id=str(job.id),
            vrt_dataset_id=str(dataset_id),
            triggered_by=str(user.id),
        )

    async def _rollback(defer_exc: BaseException) -> None:
        # Re-insert the deleted source link with its original position.
        await db.execute(
            text(
                "INSERT INTO catalog.vrt_source_links("
                "vrt_dataset_id, source_dataset_id, position) "
                "VALUES (:vrt_id, :src_id, :pos)"
            ),
            {
                "vrt_id": dataset_id,
                "src_id": source_dataset_id,
                "pos": deleted_link_position,
            },
        )
        # Revert VRT asset state.
        vrt_asset.status = previous_status
        vrt_asset.current_generation_id = previous_generation_id
        # Mark the IngestJob failed.
        job.status = "failed"
        job.error_message = f"Failed to queue VRT regeneration: {defer_exc}"
        job.completed_at = datetime.now(timezone.utc)

    await defer_with_orphan_guard(_defer, rollback=_rollback, db=db)

    return VrtMutationResponse(
        job_id=job.id, message="Source removed, VRT regeneration started"
    )
