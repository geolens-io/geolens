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
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.service_tokens import (
    header_token_rejection_reason,
    requires_header_token_policy,
)
from app.core.async_io import (
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
from app.platform.refresh.credentials import (
    CredentialStoreUnavailable,
    discard_service_credential,
    resolve_dispatch_credential,
)
from app.platform.refresh.service import (
    DatasetBusyError,
    create_pending_run,
    make_refresh_run_failed_rollback,
)
from app.platform.dataset_origin import classify_origin
from app.platform.extensions import get_catalog_port
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB, get_allowed_extensions_list
from app.modules.quota.service import check_replacement_quota
from app.modules.catalog.sources.preview import build_gdal_source, run_service_preview
from app.modules.catalog.sources.schemas import service_credential_from_request
from app.platform.service_auth import bearer_token_for_credential
from app.platform.security import SSRFError, validate_url_for_ssrf
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
    except asyncio.CancelledError:
        raise
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

    VRT reupload is rejected at this shared boundary because a VRT is defined by
    its membership, not by a file. Raster reupload IS supported (#1221) and is
    constrained here to raster payloads. File paths additionally reject raster
    inputs for vector and table datasets.

    Every door routes through this one function, which is what makes the
    error class identical across them: the direct multipart door passes
    ``file.filename``, the presigned door passes ``request.filename``, and both
    get the same 400 with the same message for the same rejected payload.

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
        # feat(#1221): a raster dataset is replaced by uploading a replacement
        # raster. There is no service path — nothing fetches a GeoTIFF from a
        # feature service — so a service preview against a raster is refused
        # here rather than failing deep in an ogr2ogr the dataset can never use.
        if service_type is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Raster datasets cannot be refreshed from a remote service. "
                    "Upload a replacement raster file instead."
                ),
            )
        if ext and ext not in _RASTER_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This dataset is a raster dataset; {ext} files are not "
                    "supported for reupload. "
                    "Cross-record-type swaps are not allowed."
                ),
            )
        return

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
    # fix(#1290 review): the REPLACEMENT variant. The creation-shaped check
    # refused at the dataset-count cap, which locked an owner at their limit
    # out of replacing datasets they already own, and charged the incoming file
    # on top of the bytes this dataset already contributes.
    incoming_bytes = file.size if file.size is not None else 0
    await check_replacement_quota(
        db,
        dataset.record.created_by,
        incoming_bytes,
        request,
        dataset_id=dataset_id,
    )

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
    # feat(#1221): this endpoint's whole output is a schema diff, and a raster
    # has no attribute schema — the ogrinfo call below would fail on a GeoTIFF
    # for reasons that read as a broken upload. The raster flow is upload then
    # commit, with no preview step in between.
    if dataset.record.record_type == "raster_dataset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Raster datasets have no schema to preview. "
                "Commit the replacement directly."
            ),
        )

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


def _require_reupload_source(job, is_service_refresh: bool) -> None:
    """fix(#1274 review): reject a source-less job BEFORE reserving the dataset.

    A presigned reupload whose upload never completed has an EMPTY-STRING
    file_path (not None — which is why the truthiness test matters) and no
    source_url. Creating the run first and 400ing after left that
    reservation active, and once the client completed the upload the retry
    hit dataset_busy — unreleasable by the sweep while the job sat pending,
    for up to the 24-hour bound-job timeout. The queue-time is-None check
    stays as defense in depth.
    """
    if not is_service_refresh and not job.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no file_path and no source_url — cannot queue reupload",
        )


async def _refuse_if_origin_changed(
    db: AsyncSession, dataset, expected_origin_kind: str | None
) -> None:
    """Refuse a commit whose expected origin is no longer the dataset's.

    fix(#1768): `geolens replace` and the web re-upload dialog both refuse to
    replace a dataset bound to a service, a STAC item, or a registered table,
    and both decide that from a SINGLE read taken before the upload. Between
    that read and the commit the user confirms sits an upload, a preview and a
    human — and a service or STAC re-upload committing in that window rebinds
    the dataset invisibly to them. The swap the commit queues then rebinds it
    to `upload` unconditionally (`_apply_reupload_swap` in tasks_reupload.py),
    severing the binding that was just established.

    Called AFTER `create_pending_run`, which is what makes the re-read
    decisive rather than one more racing read: with the one-active-run slot
    held, no other run for this dataset can be in flight, so any origin change
    is already committed and a READ COMMITTED re-read sees it. Same shape as
    the refresh door's own re-read (`router_refresh.py`) and deliberately the
    same `origin_changed` code, so a client learns one word for "the source
    moved under you".

    ``None`` asserts nothing and returns: the field is optional, so a client
    that sends none — an older CLI or SDK — gets exactly the pre-#1768
    behaviour. Only ``record_type`` is left unrefreshed, because no path
    changes a dataset's record type; ``source_format`` is the half that moves.
    """
    if expected_origin_kind is None:
        return
    await db.refresh(dataset, ["source_format"])
    current_origin_kind = classify_origin(
        dataset.source_format, dataset.record.record_type
    )
    if current_origin_kind == expected_origin_kind:
        return
    # Releases the reservation along with the merged job metadata: a leaked run
    # row would refuse every refresh of this dataset until the stale-run
    # sweep's cutoff.
    await db.rollback()
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "origin_changed",
            "message": (
                "This dataset's source changed after this replacement was "
                "staged, so nothing was queued. Re-check the dataset's source "
                "and start the replacement again."
            ),
            "origin_kind": current_origin_kind,
            "expected_origin_kind": expected_origin_kind,
        },
    )


async def _dispatch_reupload_task(
    db: AsyncSession,
    *,
    job: IngestJob,
    dataset_id: uuid.UUID,
    record_type: str,
    user_id: uuid.UUID,
    token: str | None,
    credential_ref: str | None,
    is_service_refresh: bool,
    rollback,
) -> None:
    """Defer the worker task this committed reupload needs.

    Three destinations, one admission gate. The run row that admitted this
    commit was already reserved by the caller, so nothing here decides whether
    the refresh may proceed — only which executor performs it and on which
    queue. Every branch goes through ``defer_with_orphan_guard`` so a
    Procrastinate outage flips the committed job to ``failed`` and finalizes
    the run instead of leaving a ghost ``pending`` row.

    Extracted from ``reupload_commit`` when the raster branch (#1221) pushed
    that handler past the McCabe gate.

    feat(#1676): ``token`` and ``credential_ref`` are the two shapes a service
    credential can arrive in, and exactly one of them is ever set — the caller
    gets the pair from ``resolve_dispatch_credential``. Both are forwarded
    verbatim; deciding between them is the worker's job, not this one's.
    """
    if is_service_refresh:
        source_url = job.source_url

        async def _defer_service() -> None:
            await defer_async_with_tenant(
                get_catalog_port().reupload_service_task(),
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                dataset_id=str(dataset_id),
                source_url=source_url,
                source_layer=job.source_layer or "",
                user_id=str(user_id),
                token=token,
                credential_ref=credential_ref,
            )

        await defer_with_orphan_guard(_defer_service, rollback=rollback, db=db, job=job)
        return

    if job.file_path is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job has no file_path and no source_url — cannot queue reupload",
        )
    file_path = job.file_path

    if record_type == "raster_dataset":
        # feat(#1221): the raster swap is a different worker task — it moves a
        # RasterAsset pointer rather than renaming a staging table — but it is
        # reached through this door and admitted by the same
        # `create_pending_run` reservation the caller already holds, so a
        # raster replace and a vector reupload cannot both run on one dataset.
        #
        # No priority-queue branch: raster work goes to the `raster` queue,
        # where COG conversion is already the slow tenant. A small GeoTIFF
        # jumping into `priority` would put a minutes-long GDAL conversion in
        # the queue that exists to keep small vector imports snappy.
        async def _defer_raster() -> None:
            await defer_async_with_tenant(
                get_catalog_port().reupload_raster_task(),
                job_id=str(job.id),
                attempt_id=str(job.attempt_id),
                dataset_id=str(dataset_id),
                file_path=file_path,
                user_id=str(user_id),
            )

        await defer_with_orphan_guard(_defer_raster, rollback=rollback, db=db, job=job)
        return

    # Route small files to priority queue
    import os

    file_size = 0
    # Only check local files; S3 paths (no leading /) use default queue
    if file_path.startswith("/"):
        try:
            if Path(file_path).exists():
                file_size = os.path.getsize(file_path)
        except OSError:
            pass  # If we can't stat, use default queue

    task = get_catalog_port().reupload_file_task()
    if file_size > 0 and file_size <= get_catalog_port().priority_queue_threshold_bytes:
        task = task.configure(queue="priority")

    async def _defer_file() -> None:
        await defer_async_with_tenant(
            task,
            job_id=str(job.id),
            attempt_id=str(job.attempt_id),
            dataset_id=str(dataset_id),
            file_path=file_path,
            user_id=str(user_id),
        )

    await defer_with_orphan_guard(_defer_file, rollback=rollback, db=db, job=job)


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
    # feat(#1746): one conversion for the whole handler. `service_format` is
    # left unset because nothing here composes a header line yet; the transport
    # lane fills it in where the format is resolved below.
    credential = service_credential_from_request(request.auth, request.token)
    service_token = bearer_token_for_credential(credential)
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
    #
    # feat(#1746): `auth` is excluded for the same reason `token` is, and the
    # reason is sharper for it: user_metadata is a durable JSONB column, and
    # this model_dump is a whitelist by omission, so a nested credential object
    # would land in it in full.
    existing_meta = dict(job.user_metadata or {})
    existing_meta.update(
        request.model_dump(exclude_none=True, exclude={"token", "auth", "layer_name"})
    )
    existing_meta["reupload"] = True
    existing_meta["dataset_id"] = str(dataset_id)
    if job.source_url and service_token:
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

    # feat(#1219) ADR-002 Decision 4b: the run row is written HERE, in the
    # request transaction, before the task is deferred — not at swap commit.
    # An at-commit design cannot represent a run that never committed: a
    # worker that dies mid-fetch leaves no history row at all, and the
    # ingest_jobs row that might have hinted at it is purged after the
    # retention window. `trigger` is `manual` because a human clicked commit;
    # `api` and `cli` belong to #1220's server-side refresh endpoint.
    #
    # The insert is also the admission gate (Decision 5b): a partial unique
    # index allows one active run per dataset, so a second concurrent commit
    # is refused HERE, atomically, rather than being discovered by the second
    # worker at the advisory lock with both jobs already queued.
    is_service_refresh = bool(job.source_url and not job.file_path)
    _require_reupload_source(job, is_service_refresh)

    # fix(#1746): judge the token by the policy the WORKER will apply, before
    # anything is reserved and well before the stash below — the same order and
    # the same reason as the refresh door (router_refresh.py). A WFS/OGC token
    # containing `+` or `/` used to get a 202 here, spend its single-use
    # credential, and then fail deterministically in ogr2ogr's own charset
    # check. Placed ahead of `create_pending_run` so a token that cannot work
    # never takes the one-active-run admission slot from a refresh that can.
    # ArcGIS is exempt: its token is a urlencoded query parameter, never a
    # header line, so the strict charset would reject valid ArcGIS tokens.
    if is_service_refresh and service_token:
        try:
            _, service_source_format = _catalog_port.resolve_service_type(
                str((job.user_metadata or {}).get("service_type") or "")
            )
        except IngestionError:
            # An unrecognized service label is the worker's error to report;
            # this check does not take that decision away from it.
            service_source_format = None
        if requires_header_token_policy(service_source_format):
            rejection = header_token_rejection_reason(service_token)
            if rejection is not None:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "code": "invalid_service_token",
                        # The policy, never the input: the caller has the token
                        # and can compare it against the rule, and a response
                        # body must not echo part of a credential.
                        "message": rejection,
                    },
                )

    try:
        await create_pending_run(
            db,
            dataset_id=dataset_id,
            origin_kind="service" if is_service_refresh else "upload",
            trigger="manual",
            triggered_by=user.id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
    except DatasetBusyError as exc:
        # Nothing this request wrote is committed, so the job row it merged
        # metadata into rolls back with it and stays `pending` — the caller can
        # commit the same job again once the active run finishes.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": (
                    "A refresh is already running for this dataset. "
                    "Wait for it to finish, then try again."
                ),
            },
        ) from exc

    # fix(#1768): the origin door, and it has to be HERE — after the run row
    # took the one-active-run admission slot, not before it. See
    # `_refuse_if_origin_changed` for why the reservation is what makes the
    # re-read decisive.
    await _refuse_if_origin_changed(db, dataset, request.expected_origin_kind)

    # feat(#1676): staged before the commit, exactly as the refresh door
    # stages its own, so a configured-but-unreachable store rolls the whole
    # request back — no committed job, no reserved run, nothing for the sweep
    # to unwind — rather than leaving a dispatch that can never authenticate.
    # The reverse order strands the credential instead, which is why the TTL
    # exists and why nothing depends on the discard below actually running.
    #
    # An install with NO store configured takes the third branch and keeps the
    # durable argument this door has always sent. Refusing there would break
    # protected re-upload on every stock install, which is the trade #1220
    # declined; see platform/refresh/credentials for the full contract.
    credential_ref: str | None = None
    token: str | None = service_token
    if is_service_refresh:
        try:
            token, credential_ref = await resolve_dispatch_credential(
                door="reupload_commit", credential=credential
            )
        except CredentialStoreUnavailable as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "credential_store_unavailable",
                    "message": (
                        "Could not stage the service credential for this "
                        "re-upload. Check that the credential store is "
                        "reachable and try again."
                    ),
                },
            ) from exc

    # fix(#1709 review r4 P1): the pending check at the top of this handler
    # is a plain read, and everything since — the metadata merge, the run
    # row, the staged credential — flushes in THIS commit. POST
    # /jobs/{id}/cancel can land between that read and here, and without a
    # fence this commit would bind a pending run to the now-cancelled job:
    # the queued task's claim fence fails immediately, nothing ever
    # finalizes the run, and it holds `uq_refresh_runs_one_active` against
    # every refresh until the stale-run sweep's cutoff — a successful cancel
    # that leaves the dataset reporting busy for up to an hour.
    #
    # The same-value CAS below re-evaluates the pending+attempt pair against
    # committed state under the row lock, atomically with the run flush. A
    # committed cancel makes it match zero rows and the whole request rolls
    # back — run row included — into a clean 409. When this side takes the
    # lock first, the cancel waits at its own CAS and then cancels the job
    # AND the run together: `cancel_active_run_for_job` sees the row this
    # commit just made durable. Either serialization strands nothing.
    #
    # No deadlock risk from the ordering: the cancel locks job-then-run, and
    # the run row this transaction INSERTs is invisible to the cancel's run
    # CAS until commit (any pre-existing active run was refused above as
    # dataset_busy), so the cancel never waits on anything this transaction
    # holds except the job row itself.
    commit_fence = await db.execute(
        update(IngestJob)
        .where(
            IngestJob.id == job.id,
            IngestJob.status == "pending",
            (
                IngestJob.attempt_id == job.attempt_id
                if job.attempt_id is not None
                else IngestJob.attempt_id.is_(None)
            ),
        )
        .values(status="pending")
    )
    if not commit_fence.rowcount:
        await db.rollback()
        await db.refresh(job)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "job_conflict",
                "status": job.status,
                "message": (
                    "The job changed while this commit was in flight — "
                    "nothing was queued."
                ),
            },
        )
    await db.commit()

    # Each defer_async path is wrapped in the shared orphan guard
    # (Theme H) so a Procrastinate outage flips the committed pending
    # job to ``failed`` and returns HTTP 503 instead of leaving a ghost
    # pending row for 60 minutes until stale-cleanup catches it. The run row
    # rides along: the stale-run sweep would eventually cancel it, but the
    # outcome is already known here, and an hour of `pending` for a dispatch
    # that provably failed is the silent-failure shape this table exists to
    # remove.
    inner_rollback = make_refresh_run_failed_rollback(
        make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue reupload task"
        ),
        db=db,
        ingest_job_id=job.id,
    )

    async def rollback(defer_exc: BaseException) -> None:
        await inner_rollback(defer_exc)
        # The worker will never come for it, and the run is already terminal.
        await discard_service_credential(credential_ref)

    await _dispatch_reupload_task(
        db,
        job=job,
        dataset_id=dataset_id,
        record_type=dataset.record.record_type,
        user_id=user.id,
        token=token,
        credential_ref=credential_ref,
        is_service_refresh=is_service_refresh,
        rollback=rollback,
    )

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
        # fix(#1682 codex r3): the configured default, not a frozen literal —
        # see _fallback_allowed_extensions in processing/ingest/router.py for
        # why a narrower fallback is not a safer one.
        allowed_list = list(settings.allowed_extensions_list)
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
    # fix(#1290 review): identical admission to the direct door — same function,
    # same arguments — so the two doors cannot diverge on who may replace what.
    await check_replacement_quota(
        db,
        dataset.record.created_by,
        request.file_size,
        http_request,
        dataset_id=dataset_id,
    )

    job = await get_catalog_port().create_ingest_job(db, request.filename, "", user.id)
    job.dataset_id = dataset_id
    storage = get_storage()
    s3_key = f"staging/{job.id}/{request.filename}"
    physical_s3_key = resolve_current_storage_key(s3_key)
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024

    part_size = get_catalog_port().ingest_part_size()
    # fix(#1235 review r4): a gate, not a value — every signature below computes
    # its own expiration inside the signing thread, and this call is here only
    # so a job with no usable lifetime left is refused before an upload id
    # exists. The return is deliberately discarded. Same as the upload door.
    get_catalog_port().require_signable_job_lifetime(job.created_at)

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
                # fix(#1235 review r5/r8): each part computes its own
                # expiration INSIDE the signing thread. Same as the upload
                # door; `sign_url_with_deadline` carries the reasoning.
                await run_in_thread_draining(
                    get_catalog_port().sign_url_with_deadline,
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
                await get_catalog_port().abort_presigned_multipart_upload(
                    storage,
                    key=physical_s3_key,
                    upload_id=upload_id,
                    job_id=job.id,
                )
            # fix(#1235 review r5): an HTTPException from here is the lifetime
            # refusal and must survive as its own 409; the abort above has
            # already run. Same as the upload door.
            if isinstance(exc, (asyncio.CancelledError, HTTPException)):
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
            get_catalog_port().sign_url_with_deadline,
            storage.generate_presigned_put_url,
            job.created_at,  # expires with the job, not 3600s from now
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
    # fix(#1207): re-fetch under a row lock with attributes reloaded, then read
    # the one-shot fact. `_get_bound_reupload_job_or_404` above stays unlocked —
    # it carries the stricter binding checks (dataset, owner, reupload marker)
    # and its 404 semantics, which the lock helper must not replace.
    job = await get_catalog_port().lock_presigned_job(db, job.id)
    um = job.user_metadata or {}

    if not um.get("presigned"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job is not a presigned upload",
        )

    # fix(#1213 review r3): both one-shot facts, shared with the upload door.
    # This door stamps `failed` itself before a content 422 (below), so without
    # the status half a client could re-PUT and complete again: a 200 that
    # binds a frozen object to a row preview and commit will refuse.
    get_catalog_port().require_completable_presigned_job(
        job, restart_hint="Start the reupload again."
    )

    storage = get_storage()
    s3_key = um["s3_key"]
    physical_s3_key = resolve_current_storage_key(s3_key)

    if await get_catalog_port().should_assemble_multipart(storage, um, physical_s3_key):
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
                # fix(#1233): do NOT delete the assembled object here. The
                # upload id was consumed by CompleteMultipartUpload above, so
                # the object's presence is the only record that assembly
                # succeeded — `should_assemble_multipart` reads exactly that to
                # let a retry skip re-assembly (#1202 r3). Deleting it left the
                # client's natural retry re-assembling with a spent id, 502ing
                # forever with no way back. Drain and re-raise only; the
                # cancellation is not a rejection of the bytes.
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

    # fix(#1207): rows 7-13 of the completion contract, shared with the upload
    # door — exists, pre-copy size gate, drained freeze, verify and
    # content-validate the FROZEN bytes, with every cleanup decision. The
    # docstring carries the failure postconditions.
    try:
        frozen_key = await get_catalog_port().finalize_presigned_object(
            db=db,
            storage=storage,
            job_id=job.id,
            logical_key=s3_key,
            expected_size=um.get("expected_size"),
            filename=job.source_filename or "",
            user_id=dataset.record.created_by,
            request=http_request,
            # fix(#1290 review): completion is the THIRD admission point, and
            # it was still creation-shaped — an owner at the dataset-count cap
            # passed the request-time door, uploaded, and was refused here.
            # Naming the dataset makes the finalizer admit this as a
            # replacement, against the owner, like the other two.
            replacing_dataset_id=dataset_id,
        )
    except HTTPException as exc:
        # Surface-local taxonomy: this door's sibling DIRECT door stamps a
        # failed-job audit trail before raising a content 422, and a
        # provenance test asserts that trail. Parity here is with that
        # sibling, not with the upload surface — so a deliberate content or
        # size refusal gets the same stamp, while transport failures (502)
        # leave the job retryable exactly as they do on the upload door.
        if exc.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
            job.status = "failed"
            job.error_message = str(exc.detail)
            await db.commit()
        raise

    job.file_path = frozen_key
    await db.commit()

    # fix(#1207): after the commit, never before — a rolled-back commit with
    # the staging object already gone strands the retry. The helper is named
    # for its rollback callers, but it is just a best-effort logical-key
    # delete, which is what this needs too.
    await _cleanup_uncommitted_reupload_source(s3_key, job_id=job.id)

    return UploadResponse(
        job_id=job.id,
        status="pending",
        message="File uploaded for re-upload preview",
    )
