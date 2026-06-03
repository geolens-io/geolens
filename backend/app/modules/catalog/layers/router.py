"""FastAPI router for layer creation and column management endpoints."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.core.dependencies import get_db
from app.modules.catalog.authorization import check_dataset_access
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.catalog.layers.schemas import (
    AddColumnRequest,
    AlterColumnTypeRequest,
    ColumnListResponse,
    CreateLayerRequest,
    CreateLayerResponse,
    RenameColumnRequest,
)
from app.modules.catalog.layers.service import (
    add_column,
    alter_column_type,
    create_layer,
    drop_column,
    rename_column,
)

logger = structlog.stdlib.get_logger(__name__)

layers_router = APIRouter(prefix="/layers", tags=["Maps"])


@layers_router.post(
    "/",
    response_model=CreateLayerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_layer_endpoint(
    body: CreateLayerRequest,
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> CreateLayerResponse:
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
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ColumnListResponse:
    """Add a column to an existing layer."""
    dataset = await get_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    # Phase 1061 SEC-S03: resource-level access check (create_layers permission gates role only).
    await check_dataset_access(db, dataset, dataset_id, user)

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
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="layer.add_column",
            resource_type="dataset",
            resource_id=dataset_id,
            details={
                "column_name": body.column.name,
                "column_type": body.column.type,
            },
        ),
    )
    await db.commit()

    return ColumnListResponse(columns=columns)


@layers_router.patch(
    "/{dataset_id}/columns/{column_name}/name",
    response_model=ColumnListResponse,
)
async def rename_column_endpoint(
    dataset_id: uuid.UUID,
    column_name: str,
    body: RenameColumnRequest,
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ColumnListResponse:
    """Rename a column on an existing layer."""
    dataset = await get_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    # Phase 1061 SEC-S03: resource-level access check (create_layers permission gates role only).
    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        columns = await rename_column(db, dataset, column_name, body.new_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "layer.rename_column",
        table_name=dataset.table_name,
        old_name=column_name,
        new_name=body.new_name,
        user_id=str(user.id),
    )

    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="layer.rename_column",
            resource_type="dataset",
            resource_id=dataset_id,
            details={"old_name": column_name, "new_name": body.new_name},
        ),
    )
    await db.commit()
    return ColumnListResponse(columns=columns)


@layers_router.patch(
    "/{dataset_id}/columns/{column_name}/type",
    response_model=ColumnListResponse,
)
async def alter_column_type_endpoint(
    dataset_id: uuid.UUID,
    column_name: str,
    body: AlterColumnTypeRequest,
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ColumnListResponse:
    """Change a column's type on an existing layer.

    Postgres performs an implicit ``column::TYPE`` cast; values that cannot be
    cast cause the request to fail and roll back.
    """
    dataset = await get_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    # Phase 1061 SEC-S03: resource-level access check (create_layers permission gates role only).
    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        columns = await alter_column_type(db, dataset, column_name, body.new_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:  # broad: PostgreSQL ALTER COLUMN cast can throw varied DataError types; map all to 400 with rollback
        # Cast failures (e.g. "abc" → integer) surface as Postgres DataError;
        # turn them into 400s instead of 500s so the UI can render the message.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Type change failed: {exc}",
        )

    logger.info(
        "layer.alter_column_type",
        table_name=dataset.table_name,
        column_name=column_name,
        new_type=body.new_type,
        user_id=str(user.id),
    )

    dataset.record.updated_by = user.id
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="layer.alter_column_type",
            resource_type="dataset",
            resource_id=dataset_id,
            details={"column_name": column_name, "new_type": body.new_type},
        ),
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
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ColumnListResponse:
    """Remove a column from an existing layer."""
    dataset = await get_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    # Phase 1061 SEC-S03: resource-level access check (create_layers permission gates role only).
    await check_dataset_access(db, dataset, dataset_id, user)

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
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="layer.drop_column",
            resource_type="dataset",
            resource_id=dataset_id,
            details={"column_name": column_name},
        ),
    )
    await db.commit()

    return ColumnListResponse(columns=columns)
