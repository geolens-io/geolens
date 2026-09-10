"""Dataset reupload and presigned reupload endpoints."""

import asyncio
import math
import uuid
from datetime import datetime, timezone
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

from app.core.failure_reason import redact_failure_reason
from app.core.geo import unknown_srid_refusal
from app.core.upload_errors import (
    IngestCeilingError,
    UnsafeUploadError,
    geometry_loss_refusal,
)
from app.core.identity import Identity
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
from app.platform.service_auth import (
    credential_or_422,
    url_query_token,
    wire_credential,
)
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


def _service_format(service_label: object) -> str | None:
    """The canonical service format a human service label resolves to.

    fix(#1746): the credential policy is chosen by the format, because that is
    what decides whether the credential becomes a header line or a URL query
    parameter. An unrecognized service label answers None, which is the
    worker's error to report; this does not take that decision away from it.
    """
    try:
        _, source_format = _catalog_port.resolve_service_type(str(service_label or ""))
    except IngestionError:
        return None
    return source_format


def _job_service_format(job) -> str | None:
    """The canonical service format a re-upload job's origin resolves to."""
    return _service_format((job.user_metadata or {}).get("service_type"))


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


def _pending_reupload_update(job_id: uuid.UUID, dataset_id: uuid.UUID):
    """An UPDATE that matches the job only while it is pending and bound here.

    Every write after the row is committed goes through this guard, so a row
    the sweep reclaimed, or one a dataset deletion unbound, is left as it was
    and the caller learns that from a zero rowcount.
    """
    return update(IngestJob).where(
        IngestJob.id == job_id,
        IngestJob.dataset_id == dataset_id,
        IngestJob.status == "pending",
    )


def _reupload_bind_refusal() -> HTTPException:
    """The 409 for a guarded write that matched no row."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "This upload could not be attached to the dataset. It may "
            "have taken too long, or the dataset may no longer exist. "
            "Start the re-upload again."
        ),
    )


async def _bind_presigned_reupload(
    db: AsyncSession,
    *,
    job_id: uuid.UUID,
    dataset_id: uuid.UUID,
    metadata: dict,
) -> bool:
    """Write the presigned facts onto the job; False when no row matched.

    No `staged_at` is stamped: nothing is staged until the completion door
    binds the frozen key, which moves the row into the sweep's 24-hour
    completion-bound class, still measured from `created_at`.
    """
    bound = await db.execute(
        _pending_reupload_update(job_id, dataset_id).values(user_metadata=metadata)
    )
    await db.commit()
    return bool(bound.rowcount)


def _assert_compatible_record_type(
    dataset,
    filename: str | None,
    *,
    service_type: str | None = None,
) -> None:
    """Raise HTTP 400 when the source is incompatible with dataset.record.record_type.

    Called from all three reupload doors (multipart, S3, service preview)
    after dataset lookup, before pipeline work, so this gives one
    identical error class instead of a deep-pipeline 500.

    VRT is rejected here since it's defined by membership, not a file.
    Raster IS supported (#1221), constrained to raster payloads; file
    paths additionally reject raster inputs for vector/table datasets.

    Audit action `reupload.commit` is shipped -- see
    test_provenance_attribution.py. Do not rename to `dataset.reupload`.
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
    # fix(#1290): the REPLACEMENT variant. The creation-shaped check
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
    # fix(#1848): the job is committed BEFORE the upload so the pooled
    # connection is not held across it. The row therefore survives a failed
    # upload as `pending` with no `file_path`, which the stale-pending sweep
    # reaps on its one-hour abandonment policy.
    await db.commit()
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
            # error.
            # fix(#1848): guarded like the bind below, so a row the sweep
            # already reclaimed keeps its terminal status and message.
            await db.execute(
                _pending_reupload_update(job.id, dataset_id).values(
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

        # fix(#1848): bind only while the row is still pending and still bound
        # to this dataset, stamping `staged_at` so the pending window restarts
        # here. The carried-through metadata is what the binding gate reads.
        bound = await db.execute(
            _pending_reupload_update(job.id, dataset_id).values(
                file_path=str(saved_path),
                user_metadata={
                    **(job.user_metadata or {}),
                    "staged_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        )
        await db.commit()
        if not bound.rowcount:
            raise _reupload_bind_refusal()
    except BaseException:
        await _cleanup_uncommitted_reupload_source(saved_path, job_id=job.id)
        raise
    finally:
        if downloaded_validation_path is not None:
            downloaded_validation_path.unlink(missing_ok=True)

    return ReuploadResponse(
        job_id=job.id,
        # fix(#1848): true by construction, not assumed -- the bind above
        # only reached here because the row was still pending.
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
    # feat(#1746): the same conversion the three sibling doors do, and the same
    # order: the credential is judged before any network call, and against the
    # transport the named service actually uses.
    credential = credential_or_422(
        service_credential_from_request(request.auth, request.token),
        service_format=_service_format(request.service_type),
    )
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

    # fix(#1848): hand the pooled connection back before DNS, the page fetches
    # and ogrinfo. The rollback expires every ORM instance, so the two dataset
    # facts the diff needs and the job's owner are read off them first.
    prior_columns = dataset.column_info or []
    prior_feature_count = dataset.feature_count
    user_id = user.id
    await db.rollback()

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
            # ArcGIS only: `build_gdal_source` percent-encodes this into the
            # ESRIJSON query, and ignores it for WFS and OGC API Features,
            # whose credential travels as a header instead.
            token=url_query_token(credential),
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
            credential=credential,
        )
    except IngestionError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to preview remote layer. The service may be unavailable or the layer format is unsupported.",
        )

    diff = compute_schema_diff(
        prior_columns,
        preview_data["columns"],
        prior_feature_count,
        preview_data["feature_count"],
    )
    schema_diff = SchemaDiff(**diff)

    job = IngestJob(
        dataset_id=dataset_id,
        source_filename=request.layer_title or request.layer_name,
        source_url=request.url,
        source_layer=request.layer_name,
        created_by=user_id,
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

    # fix(#1848): hand the pooled connection back before the S3 download and
    # ogrinfo. The rollback expires every ORM instance, so everything the
    # response and the diff read off `dataset` and `job` is taken first.
    file_path = job.file_path
    job_pk = job.id
    job_source_filename = job.source_filename
    prior_columns = dataset.column_info or []
    prior_feature_count = dataset.feature_count
    prior_record_type = dataset.record.record_type
    prior_geometry_type = dataset.geometry_type
    await db.rollback()

    # Resolve S3 key to local file for ogrinfo
    downloaded_preview_path: Path | None = None
    if file_path:
        resolved_file_path = await get_catalog_port().resolve_file_path(
            file_path, str(job_pk)
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
    except IngestCeilingError as exc:
        # fix(#2043): the ceiling message the import preview already answers.
        # The broad handler below reports "malformed or unsupported", which is
        # wrong for a file that is merely too large, and hides the way out.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except UnsafeUploadError as exc:
        # fix(#1846): the same mapping `preview_file` gives it.
        # This block had no `except` at all, so a content refusal -- which is a
        # deliberate 4xx with a message that names the fix -- reached the client
        # as a 500 on this endpoint alone.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:  # broad: GDAL subprocess can raise various errors on unsupported/malformed files
        # fix(#2036): the 422 the import preview answers for the same failure.
        # A malformed file's IngestionError escaped this door as a 500.
        logger.exception("ogrinfo_preview failed", job_id=str(job_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unable to preview file. The file may be malformed or unsupported.",
        ) from exc
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

    # fix(#2031): the diff below reads attribute columns only, so a geometry
    # loss reached the client as an unremarkable schema diff.
    geometry_loss = geometry_loss_refusal(
        record_type=prior_record_type,
        dataset_geometry_type=prior_geometry_type,
        source_has_geometry=info.get("geometry_type") is not None,
    )
    if geometry_loss:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "geometry_loss", "message": geometry_loss},
        )

    diff = compute_schema_diff(
        prior_columns,
        info["columns"],
        prior_feature_count,
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
        job_id=job_pk,
        source_filename=job_source_filename,
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
    """fix(#1274): reject a source-less job BEFORE reserving the dataset.

    A presigned reupload whose upload never completed has an EMPTY-STRING
    file_path (not None -- hence the truthiness test) and no source_url.
    Creating the run first and 400ing after left that reservation active,
    so a later completed upload hit dataset_busy, unreleasable by the
    sweep for up to the 24-hour bound-job timeout. The queue-time is-None
    check stays as defense in depth.
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

    fix(#1768): `geolens replace` and the re-upload dialog both decide
    from a SINGLE pre-upload read whether they're replacing a
    service/STAC/registered-table dataset. Between that read and commit
    sits an upload, a preview, and a human -- a service/STAC re-upload
    committing in that window would rebind the dataset invisibly, since
    the swap always rebinds to `upload` unconditionally.

    Called AFTER `create_pending_run`: the one-active-run slot means a
    READ COMMITTED re-read sees any origin change already committed.
    Same `origin_changed` code as the refresh door's re-read
    (`router_refresh.py`). ``None`` returns immediately: an older
    CLI/SDK gets the pre-#1768 behaviour.
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

    Three destinations, one admission gate already reserved by the
    caller; this only picks the executor and queue. Every branch goes
    through ``defer_with_orphan_guard`` so a Procrastinate outage flips
    the job to ``failed`` and finalizes the run instead of leaving a
    ghost ``pending`` row. Extracted from ``reupload_commit`` when the
    raster branch (#1221) pushed it past the McCabe gate.

    feat(#1676): ``token``/``credential_ref`` are the two shapes a
    service credential can arrive in, exactly one ever set (from
    ``resolve_dispatch_credential``); both forwarded verbatim.
    """
    if is_service_refresh:
        source_url = job.source_url

        async def _defer_service() -> None:
            task = get_catalog_port().reupload_service_task()
            await defer_async_with_tenant(
                task,
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
        # feat(#1221): the raster swap moves a RasterAsset pointer rather
        # than renaming a staging table, but is admitted by the same
        # `create_pending_run` reservation, so raster and vector reuploads
        # can't both run on one dataset. Goes to the `raster` queue, not
        # `priority`: a minutes-long GDAL conversion there would block the
        # queue that keeps small vector imports snappy.
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
    # feat(#1746): one conversion for the whole handler. The service format is
    # not known until the job has been read, so the credential is judged and
    # composed a few lines below, before anything is written or reserved.
    credential = service_credential_from_request(request.auth, request.token)
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

    # fix(#2032): an unassigned EPSG code committed and was then ignored.
    srid_refusal = await unknown_srid_refusal(db, request.srid_override)
    if srid_refusal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=srid_refusal,
        )

    # fix(#1746): judge the credential by the WORKER's policy for this
    # job's service type -- a WFS token with `+`/`/` used to get a 202,
    # spend its single-use credential, then fail in ogr2ogr's charset
    # check. Placed ahead of every write so a bad credential never takes
    # the one-active-run slot from a refresh that can.
    service_token = wire_credential(credential, service_format=_job_service_format(job))

    # Merge commit request params into user_metadata, preserving existing
    # keys. token + layer_name stay request-only (layer_name goes into the
    # dedicated source_layer column, D-03 below).
    #
    # feat(#1746): `auth` is excluded for the same reason -- user_metadata
    # is a durable JSONB column and this model_dump is a whitelist by
    # omission, so a nested credential object would land in it in full.
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

    # GPKG-01 (D-03): persist to the dedicated IngestJob.source_layer
    # column; user_metadata is not consulted by the worker for this.
    if request.layer_name is not None:
        job.source_layer = request.layer_name  # GPKG-01 Phase 1058

    # feat(#1219) ADR-002 Decision 4b: the run row is written HERE, before
    # the task is deferred, not at swap commit -- a worker dying mid-fetch
    # would otherwise leave no history row at all. `trigger` is `manual`
    # since a human clicked commit. Decision 5b: the insert is also the
    # admission gate (partial unique index, one active run per dataset),
    # refusing a second concurrent commit HERE rather than at the worker.
    is_service_refresh = bool(job.source_url and not job.file_path)
    _require_reupload_source(job, is_service_refresh)

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

    # fix(#1768): the origin door, and it has to be HERE -- after the run
    # row took the one-active-run admission slot, not before it. See
    # `_refuse_if_origin_changed` for why the reservation makes the
    # re-read decisive.
    await _refuse_if_origin_changed(db, dataset, request.expected_origin_kind)

    # feat(#1676): staged before the commit so a configured-but-unreachable
    # store rolls the whole request back rather than leaving a dispatch
    # that can never authenticate. An install with NO store configured
    # takes the third branch and keeps the durable argument instead;
    # refusing there would break protected re-upload on every stock
    # install -- see platform/refresh/credentials for the full contract.
    credential_ref: str | None = None
    token: str | None = service_token
    if is_service_refresh:
        try:
            # The wire value, not the structured credential: this door has
            # already judged it and composed it against the job's own service
            # format, and passing the credential again would ask the helper to
            # re-derive a format it cannot see from here.
            token, credential_ref = await resolve_dispatch_credential(
                service_token, door="reupload_commit"
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

    # fix(#1709): the pending check at the top is a plain read, and
    # everything since flushes in THIS commit -- POST /jobs/{id}/cancel
    # landing in between would, without a fence, bind a pending run to a
    # now-cancelled job that holds `uq_refresh_runs_one_active` for up to
    # an hour of false "busy" after a successful cancel.
    #
    # The same-value CAS below re-evaluates pending+attempt under the row
    # lock, atomically with the run flush: a committed cancel matches zero
    # rows and rolls the whole request back into a clean 409; if this side
    # wins the lock first, the cancel's own CAS then cancels job AND run
    # together. No deadlock: this transaction's run row is invisible to
    # the cancel's CAS until commit.
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

    # Each defer_async path is wrapped in the shared orphan guard so a
    # Procrastinate outage flips the committed job to ``failed`` and
    # returns 503 instead of a ghost ``pending`` row for 60 minutes. The
    # run row rides along -- an hour of `pending` for a provably failed
    # dispatch is the silent-failure shape this table exists to remove.
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
        # fix(#1682): the configured default, not a frozen literal —
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
    # fix(#1290): identical admission to the direct door — same function,
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
    # fix(#1848): the markers the binding gate reads are committed with the
    # row; the presigned facts land through the guarded bind once storage
    # has answered, so a row cancelled or unbound meanwhile is refused.
    job.user_metadata = {"reupload": True, "dataset_id": str(dataset_id)}
    job_id = job.id
    job_created_at = job.created_at
    job_metadata = job.user_metadata
    storage = get_storage()
    s3_key = f"staging/{job_id}/{request.filename}"
    physical_s3_key = resolve_current_storage_key(s3_key)
    threshold = settings.presigned_multipart_threshold_mb * 1024 * 1024

    part_size = get_catalog_port().ingest_part_size()
    # fix(#1235): a gate, not a value — every signature below computes
    # its own expiration inside the signing thread, and this call is here only
    # so a job with no usable lifetime left is refused before an upload id
    # exists. The return is deliberately discarded. Same as the upload door.
    get_catalog_port().require_signable_job_lifetime(job_created_at)
    # fix(#1848): committed before storage is asked for anything, so the pooled
    # connection is not held across the multipart initiation or the signing.
    await db.commit()

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
                # fix(#1235): each part computes its own
                # expiration INSIDE the signing thread. Same as the upload
                # door; `sign_url_with_deadline` carries the reasoning.
                await run_in_thread_draining(
                    get_catalog_port().sign_url_with_deadline,
                    storage.generate_presigned_part_url,
                    job_created_at,
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
                    job_id=job_id,
                )
            # fix(#1235): an HTTPException from here is the lifetime
            # refusal and must survive as its own 409; the abort above has
            # already run. Same as the upload door.
            if isinstance(exc, (asyncio.CancelledError, HTTPException)):
                raise
            logger.exception("presigned_reupload_multipart_failed", s3_key=s3_key)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Storage service unavailable",
            ) from exc
        try:
            bound = await _bind_presigned_reupload(
                db,
                job_id=job_id,
                dataset_id=dataset_id,
                metadata={
                    **job_metadata,
                    "presigned": True,
                    "s3_key": s3_key,
                    "upload_id": upload_id,
                    "multipart": True,
                    "expected_size": request.file_size,
                },
            )
            if not bound:
                raise _reupload_bind_refusal()
        except BaseException:
            await get_catalog_port().abort_presigned_multipart_upload(
                storage,
                key=physical_s3_key,
                upload_id=upload_id,
                job_id=job_id,
            )
            raise
        return PresignedUploadResponse(
            job_id=job_id,
            urls=urls,
            s3_key=physical_s3_key,
            upload_id=upload_id,
            part_size=part_size,
        )
    else:
        url = await run_in_thread_draining(
            get_catalog_port().sign_url_with_deadline,
            storage.generate_presigned_put_url,
            job_created_at,  # expires with the job, not 3600s from now
            physical_s3_key,
            request.content_type,
        )
        bound = await _bind_presigned_reupload(
            db,
            job_id=job_id,
            dataset_id=dataset_id,
            metadata={
                **job_metadata,
                "presigned": True,
                "s3_key": s3_key,
                "multipart": False,
                "expected_size": request.file_size,
            },
        )
        if not bound:
            raise _reupload_bind_refusal()
        return PresignedUploadResponse(
            job_id=job_id,
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

    # fix(#1213): both one-shot facts, shared with the upload door.
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
                # fix(#1233): do NOT delete the assembled object -- the
                # spent upload id means the object's presence is the only
                # record assembly succeeded, which `should_assemble_multipart`
                # reads to let a retry skip re-assembly. Deleting it left a
                # retry 502ing forever with a spent id and no way back.
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
            # fix(#1290): completion is the THIRD admission point, and
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
            job.error_message = redact_failure_reason(str(exc.detail))
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
