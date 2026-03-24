"""FastAPI router for layer creation and column management endpoints."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_action
from app.auth.dependencies import require_permission
from app.auth.models import User
from app.dependencies import get_db
from app.datasets.service import get_dataset
from app.layers.schemas import (
    AddColumnRequest,
    ColumnListResponse,
    CreateLayerRequest,
    CreateLayerResponse,
)
from app.layers.service import add_column, create_layer, drop_column

logger = structlog.stdlib.get_logger(__name__)

layers_router = APIRouter(prefix="/layers", tags=["Maps"])


@layers_router.post(
    "/",
    response_model=CreateLayerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_layer_endpoint(
    body: CreateLayerRequest,
    user: User = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new empty spatial layer.

    Creates a PostGIS table with a typed geometry column, runs the full
    post-processing pipeline (geom_4326, spatial index, reader grants),
    and registers the layer as a catalog dataset.

    Requires editor or admin role.
    """
    try:
        dataset = await create_layer(
            db,
            body.title,
            body.geometry_type,
            user.id,
            columns=body.columns,
            description=body.summary,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "layer.create",
        table_name=dataset.table_name,
        user_id=str(user.id),
        geometry_type=body.geometry_type,
    )

    await db.commit()
    await db.refresh(dataset)

    return CreateLayerResponse(
        id=dataset.id,
        title=dataset.record.title,
        table_name=dataset.table_name,
        geometry_type=dataset.geometry_type,
        feature_count=dataset.feature_count or 0,
        visibility=dataset.record.visibility,
        created_at=dataset.record.created_at,
    )


@layers_router.post(
    "/{dataset_id}/columns/",
    response_model=ColumnListResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_column_endpoint(
    dataset_id: uuid.UUID,
    body: AddColumnRequest,
    user: User = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
):
    """Add a column to an existing layer."""
    dataset = await get_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    try:
        columns = await add_column(db, dataset, body.column.name, body.column.type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "layer.add_column",
        table_name=dataset.table_name,
        column_name=body.column.name,
        column_type=body.column.type,
        user_id=str(user.id),
    )

    dataset.record.updated_by = user.id
    await log_action(
        db,
        user_id=user.id,
        action="layer.add_column",
        resource_type="dataset",
        resource_id=dataset_id,
        details={
            "column_name": body.column.name,
            "column_type": body.column.type,
        },
    )
    await db.commit()

    return ColumnListResponse(columns=columns)


@layers_router.delete(
    "/{dataset_id}/columns/{column_name}",
    response_model=ColumnListResponse,
)
async def drop_column_endpoint(
    dataset_id: uuid.UUID,
    column_name: str,
    user: User = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
):
    """Remove a column from an existing layer."""
    dataset = await get_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    try:
        columns = await drop_column(db, dataset, column_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "layer.drop_column",
        table_name=dataset.table_name,
        column_name=column_name,
        user_id=str(user.id),
    )

    dataset.record.updated_by = user.id
    await log_action(
        db,
        user_id=user.id,
        action="layer.drop_column",
        resource_type="dataset",
        resource_id=dataset_id,
        details={"column_name": column_name},
    )
    await db.commit()

    return ColumnListResponse(columns=columns)
