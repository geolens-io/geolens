"""Collection API endpoints: CRUD, membership, and dataset listing."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.audit.service import log_action
from app.cache import get_cache
from app.cache.tiles import invalidate_catalog_cache
from app.auth.dependencies import get_optional_user, require_permission
from app.auth.models import User
from app.auth.visibility import get_user_roles
from app.collections.schemas import (
    AddDatasetsResponse,
    CollectionAddDatasetsRequest,
    CollectionCreate,
    CollectionListResponse,
    CollectionResponse,
    CollectionUpdate,
)
from app.collections.service import (
    add_datasets_to_collection,
    batch_collection_dataset_counts,
    batch_collection_extents,
    create_collection,
    delete_collection,
    get_collection,
    get_collection_datasets,
    list_collections,
    remove_dataset_from_collection,
    update_collection,
)
from app.datasets.helpers import dataset_to_response
from app.datasets.schemas import DatasetListResponse
from app.dependencies import get_db

router = APIRouter(prefix="/catalog/collections", tags=["Datasets"])


def _collection_to_response(
    collection, dataset_count: int, extent_data: dict
) -> CollectionResponse:
    """Build a CollectionResponse from a Collection ORM object plus computed values."""
    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        created_by=collection.created_by,
        created_at=collection.created_at,
        updated_at=collection.updated_at,
        dataset_count=dataset_count,
        extent_bbox=extent_data.get("extent_bbox"),
        temporal_start=extent_data.get("temporal_start"),
        temporal_end=extent_data.get("temporal_end"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED
)
async def create_collection_endpoint(
    body: CollectionCreate,
    request: Request,
    user: User = Depends(require_permission("manage_collections")),
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Create a new collection."""
    try:
        collection = await create_collection(db, body.name, body.description, user.id)
        await log_action(
            db,
            user_id=user.id,
            action="collection.create",
            resource_type="collection",
            resource_id=collection.id,
            details={"name": body.name},
            ip_address=request.client.host if request.client else None,
        )
        await db.commit()
        await db.refresh(collection)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Collection with name '{body.name}' already exists",
        )

    return _collection_to_response(
        collection,
        dataset_count=0,
        extent_data={"extent_bbox": None, "temporal_start": None, "temporal_end": None},
    )


_CATALOG_CACHE_TTL = 60  # seconds


@router.get("/", response_model=CollectionListResponse)
async def list_collections_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionListResponse:
    """List all collections with dataset_count and extent computed per-user."""
    user_roles = await get_user_roles(db, user) if user is not None else set()

    # Cache admin views only (non-admin results vary by user identity)
    is_admin = "admin" in user_roles
    cache_key = f"catalog:collections:admin:{skip}:{limit}" if is_admin else None

    if cache_key:
        cache = get_cache()
        cached = await cache.get(cache_key)
        if cached is not None:
            return CollectionListResponse(**cached)

    collections, total = await list_collections(db, skip=skip, limit=limit)

    coll_ids = [c.id for c in collections]
    extent_map = await batch_collection_extents(db, coll_ids, user, user_roles)
    count_map = await batch_collection_dataset_counts(db, coll_ids, user, user_roles)
    default_extent = {"extent_bbox": None, "temporal_start": None, "temporal_end": None}
    responses = [
        _collection_to_response(
            coll, count_map.get(coll.id, 0), extent_map.get(coll.id, default_extent)
        )
        for coll in collections
    ]

    response = CollectionListResponse(collections=responses, total=total)

    if cache_key:
        cache = get_cache()
        await cache.set(
            cache_key, response.model_dump(mode="json"), ttl=_CATALOG_CACHE_TTL
        )

    return response


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection_endpoint(
    collection_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Get a single collection with dataset_count and extent."""
    collection = await get_collection(db, collection_id)
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )

    user_roles = await get_user_roles(db, user) if user is not None else set()
    coll_ids = [collection_id]
    extent_map = await batch_collection_extents(db, coll_ids, user, user_roles)
    count_map = await batch_collection_dataset_counts(db, coll_ids, user, user_roles)
    default_extent = {"extent_bbox": None, "temporal_start": None, "temporal_end": None}

    return _collection_to_response(
        collection,
        count_map.get(collection_id, 0),
        extent_map.get(collection_id, default_extent),
    )


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection_endpoint(
    collection_id: uuid.UUID,
    body: CollectionUpdate,
    request: Request,
    user: User = Depends(require_permission("manage_collections")),
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Update a collection's name and/or description."""
    try:
        collection = await update_collection(
            db, collection_id, name=body.name, description=body.description
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )

    await log_action(
        db,
        user_id=user.id,
        action="collection.update",
        resource_type="collection",
        resource_id=collection_id,
        details=body.model_dump(exclude_none=True),
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await invalidate_catalog_cache()

    user_roles = await get_user_roles(db, user)
    coll_ids = [collection_id]
    extent_map = await batch_collection_extents(db, coll_ids, user, user_roles)
    count_map = await batch_collection_dataset_counts(db, coll_ids, user, user_roles)
    default_extent = {"extent_bbox": None, "temporal_start": None, "temporal_end": None}

    return _collection_to_response(
        collection,
        count_map.get(collection_id, 0),
        extent_map.get(collection_id, default_extent),
    )


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection_endpoint(
    collection_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("manage_collections")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a collection. Admin only."""
    try:
        name = await delete_collection(db, collection_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )

    await log_action(
        db,
        user_id=user.id,
        action="collection.delete",
        resource_type="collection",
        resource_id=collection_id,
        details={"name": name},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await invalidate_catalog_cache()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{collection_id}/datasets/", response_model=AddDatasetsResponse)
async def add_datasets_endpoint(
    collection_id: uuid.UUID,
    body: CollectionAddDatasetsRequest,
    request: Request,
    user: User = Depends(require_permission("manage_collections")),
    db: AsyncSession = Depends(get_db),
) -> AddDatasetsResponse:
    """Add datasets to a collection."""
    try:
        count = await add_datasets_to_collection(
            db, collection_id, body.dataset_ids, user.id
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )

    await log_action(
        db,
        user_id=user.id,
        action="collection.add_datasets",
        resource_type="collection",
        resource_id=collection_id,
        details={"dataset_ids": [str(d) for d in body.dataset_ids]},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await invalidate_catalog_cache()

    return AddDatasetsResponse(added=count)


@router.delete(
    "/{collection_id}/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_dataset_endpoint(
    collection_id: uuid.UUID,
    dataset_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("manage_collections")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove a dataset from a collection."""
    removed = await remove_dataset_from_collection(db, collection_id, dataset_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset membership not found",
        )

    await log_action(
        db,
        user_id=user.id,
        action="collection.remove_dataset",
        resource_type="collection",
        resource_id=collection_id,
        details={"dataset_id": str(dataset_id)},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await invalidate_catalog_cache()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{collection_id}/datasets/", response_model=DatasetListResponse)
async def get_collection_datasets_endpoint(
    collection_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetListResponse:
    """Get datasets in a collection with RBAC filtering."""
    collection = await get_collection(db, collection_id)
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found",
        )

    user_roles = await get_user_roles(db, user) if user is not None else set()
    datasets, total = await get_collection_datasets(
        db, collection_id, user, user_roles, skip=skip, limit=limit
    )

    # Build actor map for created_by_display and last_edited_by_display
    actor_ids: set = set()
    for d in datasets:
        if d.record.created_by:
            actor_ids.add(d.record.created_by)
        if d.record.updated_by:
            actor_ids.add(d.record.updated_by)
    actor_map: dict = {}
    if actor_ids:
        rows = await db.execute(select(User).where(User.id.in_(actor_ids)))
        actor_map = {u.id: u for u in rows.scalars()}

    return DatasetListResponse(
        datasets=[dataset_to_response(d, actors_by_id=actor_map) for d in datasets],
        total=total,
    )
