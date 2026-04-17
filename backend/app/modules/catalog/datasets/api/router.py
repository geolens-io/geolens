"""Dataset core CRUD endpoints: list, create, get, update, delete, quicklook, history."""

import uuid

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.schemas import AuditLogListResponse, AuditLogResponse
from app.modules.audit.service import log_action, query_audit_logs
from app.platform.cache import get_cache
from app.platform.cache.tiles import invalidate_catalog_cache
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
    require_permission,
)
from app.modules.auth.models import User
from app.modules.auth.visibility import (
    check_dataset_access_or_anonymous,
    get_user_roles,
)
from app.modules.catalog.datasets.domain.helpers import (
    dataset_to_response,
    _load_actor_identities,
)
from app.modules.catalog.datasets.domain.schemas import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkDeleteResultItem,
    CreateEmptyDatasetRequest,
    DatasetDeleteRequest,
    DatasetListResponse,
    DatasetMeta,
    DatasetResponse,
)
from app.modules.catalog.collections.service import get_dataset_collections
from app.modules.catalog.datasets.domain.service import (
    DependentVrtError,
    create_empty_dataset,
    delete_dataset,
    get_dataset,
    get_dataset_detail,
    get_datasets_list,
    update_user_metadata,
)
from app.core.dependencies import get_db
from app.core.public_urls import get_dataset_service_url
from app.platform.storage import get_storage

logger = structlog.get_logger()

router = APIRouter(prefix="/datasets", tags=["Datasets"])

_CATALOG_CACHE_TTL = 60  # seconds


@router.get("/", response_model=DatasetListResponse)
async def list_all_datasets(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetListResponse:
    """List datasets with visibility filtering and pagination."""
    user_roles = await get_user_roles(db, user)

    # Cache admin views only (non-admin results vary by user identity)
    is_admin = "admin" in user_roles
    cache_key = f"catalog:datasets:admin:{skip}:{limit}" if is_admin else None

    if cache_key:
        cache = get_cache()
        cached = await cache.get(cache_key)
        if cached is not None:
            return DatasetListResponse(**cached)

    base_url = await get_dataset_service_url(db, request=request)
    datasets, total = await get_datasets_list(
        db, user, user_roles, skip=skip, limit=limit, base_url=base_url
    )
    response = DatasetListResponse(datasets=datasets, total=total)

    if cache_key:
        cache = get_cache()
        await cache.set(
            cache_key, response.model_dump(mode="json"), ttl=_CATALOG_CACHE_TTL
        )

    return response


# ---------------------------------------------------------------------------
# Create empty dataset
# ---------------------------------------------------------------------------


@router.post(
    "/create/", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED
)
async def create_empty_dataset_endpoint(
    body: CreateEmptyDatasetRequest,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Create an empty dataset with user-defined columns.

    Creates a PostGIS table in the data schema and a catalog record.
    """
    try:
        dataset = await create_empty_dataset(db, body, user)
        await db.commit()
        await db.refresh(dataset, ["record"])
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    actors_by_id = await _load_actor_identities(db, [dataset.record.created_by])
    return dataset_to_response(
        dataset,
        actors_by_id=actors_by_id,
        base_url=await get_dataset_service_url(db, request=request),
    )


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_single_dataset(
    dataset_id: uuid.UUID,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Get a single dataset by ID with visibility check."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check — returns resolved user_roles to avoid duplicate DB query
    user_roles = await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    # Log dataset access for authenticated users only
    if user is not None:
        await log_action(
            db,
            user_id=user.id,
            action="dataset.view",
            resource_type="dataset",
            resource_id=dataset_id,
            ip_address=request.client.host if request.client else None,
        )
        await db.commit()

    # Fetch collection memberships for detail view
    colls = await get_dataset_collections(db, dataset_id)
    collections_data = [{"id": str(c.id), "name": c.name} for c in colls]

    base_url = await get_dataset_service_url(db, request=request)
    result = await get_dataset_detail(
        db, dataset_id, user, base_url=base_url, collections_data=collections_data,
        dataset=dataset, user_roles=user_roles,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    return result


@router.get("/{dataset_id}/quicklook")
async def get_quicklook(
    dataset_id: uuid.UUID,
    size: int = Query(256, ge=1, le=512, description="Quicklook size in pixels (256 or 512)"),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a quicklook PNG image for a dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    record_type = getattr(dataset.record, "record_type", None)

    if record_type in ("raster_dataset", "vrt_dataset"):
        from app.processing.raster.models import RasterAsset

        ra_result = await db.execute(
            select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
        )
        raster_asset = ra_result.scalar_one_or_none()
        if raster_asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Raster asset not found",
            )
        uri = (
            raster_asset.quicklook_256_uri
            if size <= 256
            else raster_asset.quicklook_512_uri
        )

    elif record_type == "vector_dataset":
        uri = dataset.quicklook_256_uri
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quicklook not available for this dataset type",
        )

    if uri is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quicklook not available",
        )

    storage = get_storage()
    data = await storage.get(uri)
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.patch("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset_metadata(
    dataset_id: uuid.UUID,
    meta: DatasetMeta,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DatasetResponse:
    """Update user-editable dataset metadata."""
    try:
        dataset = await update_user_metadata(
            db,
            dataset_id,
            meta,
            actor_id=user.id,
        )
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=msg,
        )

    # Log the metadata edit
    await log_action(
        db,
        user_id=user.id,
        action="metadata.edit",
        resource_type="dataset",
        resource_id=dataset_id,
        details=meta.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(dataset)
    await db.refresh(dataset.record)
    await invalidate_catalog_cache()

    actors_by_id = await _load_actor_identities(
        db,
        [dataset.record.created_by, dataset.record.updated_by],
    )
    return dataset_to_response(
        dataset,
        actors_by_id=actors_by_id,
        base_url=await get_dataset_service_url(db, request=request),
    )


@router.post("/bulk-delete/", response_model=BulkDeleteResponse)
async def bulk_delete_datasets_endpoint(
    body: BulkDeleteRequest,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> BulkDeleteResponse:
    """Delete multiple datasets in one request. Returns per-item results."""
    results: list[BulkDeleteResultItem] = []
    deleted = 0

    for item in body.datasets:
        try:
            table_name = await delete_dataset(db, item.dataset_id, item.confirm_title)
            await log_action(
                db,
                user_id=user.id,
                action="dataset.delete",
                resource_type="dataset",
                resource_id=item.dataset_id,
                details={"title": item.confirm_title, "table_name": table_name},
                ip_address=request.client.host if request.client else None,
            )
            # Commit per-item so a later failure cannot orphan storage objects
            # that were already deleted for successfully-committed datasets.
            await db.commit()
            results.append(
                BulkDeleteResultItem(dataset_id=item.dataset_id, status="deleted")
            )
            deleted += 1
        except Exception as exc:
            await db.rollback()
            if not isinstance(exc, (DependentVrtError, ValueError)):
                logger.exception(
                    "Unexpected error during bulk delete",
                    dataset_id=str(item.dataset_id),
                )
            results.append(
                BulkDeleteResultItem(
                    dataset_id=item.dataset_id,
                    status="error",
                    detail=str(exc),
                )
            )

    if deleted > 0:
        await invalidate_catalog_cache()

    return BulkDeleteResponse(
        deleted=deleted, errors=len(results) - deleted, results=results
    )


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset_endpoint(
    dataset_id: uuid.UUID,
    body: DatasetDeleteRequest,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a dataset with cascade cleanup. Admin only, requires confirm_title."""
    try:
        table_name = await delete_dataset(db, dataset_id, body.confirm_title)
    except DependentVrtError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "dependent_vrts": exc.dependents,
            },
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=msg,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg,
        )

    await log_action(
        db,
        user_id=user.id,
        action="dataset.delete",
        resource_type="dataset",
        resource_id=dataset_id,
        details={"title": body.confirm_title, "table_name": table_name},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    # Invalidate caches after dataset deletion
    await invalidate_catalog_cache()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{dataset_id}/history", response_model=AuditLogListResponse)
async def get_dataset_history(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> AuditLogListResponse:
    """Get audit log history for a specific dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    logs, total = await query_audit_logs(
        db,
        resource_type="dataset",
        resource_id=dataset_id,
        skip=skip,
        limit=limit,
    )

    return AuditLogListResponse(
        logs=[
            AuditLogResponse(
                id=log.id,
                user_id=log.user_id,
                username=log.user.username if log.user else None,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                details=log.details,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log in logs
        ],
        total=total,
    )
