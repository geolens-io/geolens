"""FastAPI router for layer creation and column management endpoints."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.db.sqlstate import is_operational
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.core.dependencies import get_db
from app.modules.catalog.authorization import (
    check_dataset_write_access,
    require_dataset_editing_enabled,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.catalog.layers.schemas import (
    AddColumnRequest,
    AlterColumnTypeRequest,
    ColumnListResponse,
    ColumnReferencesResponse,
    CreateLayerRequest,
    CreateLayerResponse,
    RenameColumnRequest,
)
from app.modules.catalog.layers.service import (
    add_column,
    alter_column_type,
    count_maps_referencing_column,
    create_layer,
    drop_column,
    rename_column,
)
from app.platform.cache.provider import get_tile_cache
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE


async def _invalidate_tiles(table_name: str) -> None:
    """fix(#458 E-05): column DDL changes the attribute set embedded in vector
    tiles, so purge cached tiles post-commit — same treatment as the
    feature-edit path (features/router.py) and the reupload swap."""
    tile_cache = get_tile_cache()
    if tile_cache is not None:
        await tile_cache.invalidate_table(table_name)


async def _raise_ddl_db_error(db: AsyncSession, exc: DBAPIError, action: str) -> None:
    """Roll back and map a DDL DB error to the right status. Never returns.

    fix(#458 E-13): add/rename/drop caught only ValueError, so a DB-level failure
    that isn't pre-validated — a dependent view on drop (2BP01), a lock timeout —
    surfaced as a 500. Only `alter_column_type` mapped these. Classify by
    SQLSTATE like the feature-write path: a bad request is a 400, an outage a 503.
    """
    await db.rollback()
    if is_operational(exc):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable.",
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{action} failed: {exc.orig or exc}",
    )


logger = structlog.stdlib.get_logger(__name__)

layers_router = APIRouter(
    prefix="/layers", tags=["Maps"], responses=ERROR_RESPONSES_WRITE
)


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
    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db)

    try:
        columns = await add_column(db, dataset, body.column.name, body.column.type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DBAPIError as exc:
        await _raise_ddl_db_error(db, exc, "Add column")

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
    # fix(#525 B-038): roll the _v= URL cache-buster in the same transaction —
    # the post-commit Valkey purge cannot reach CDN/browser caches keyed on the URL.
    dataset.bump_tile_cache_version()
    await db.commit()
    await _invalidate_tiles(dataset.table_name)

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
    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db)

    try:
        columns = await rename_column(db, dataset, column_name, body.new_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DBAPIError as exc:
        await _raise_ddl_db_error(db, exc, "Rename column")

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
    # fix(#525 B-038): roll the _v= URL cache-buster in the same transaction —
    # the post-commit Valkey purge cannot reach CDN/browser caches keyed on the URL.
    dataset.bump_tile_cache_version()
    await db.commit()
    await _invalidate_tiles(dataset.table_name)
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
    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db)

    try:
        columns = await alter_column_type(db, dataset, column_name, body.new_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DBAPIError as exc:
        # fix(#458 E-42): route through the shared classifier like add/rename/
        # drop, so a lock timeout or connection failure during ALTER TYPE is a
        # 503, while cast failures ("abc" → integer) stay 400 with the message.
        await _raise_ddl_db_error(db, exc, "Type change")

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
    # fix(#525 B-038): roll the _v= URL cache-buster in the same transaction —
    # the post-commit Valkey purge cannot reach CDN/browser caches keyed on the URL.
    dataset.bump_tile_cache_version()
    await db.commit()
    await _invalidate_tiles(dataset.table_name)
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
    await check_dataset_write_access(db, dataset, dataset_id, user)
    await require_dataset_editing_enabled(db)

    try:
        columns = await drop_column(db, dataset, column_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except DBAPIError as exc:
        await _raise_ddl_db_error(db, exc, "Drop column")

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
    # fix(#525 B-038): roll the _v= URL cache-buster in the same transaction —
    # the post-commit Valkey purge cannot reach CDN/browser caches keyed on the URL.
    dataset.bump_tile_cache_version()
    await db.commit()
    await _invalidate_tiles(dataset.table_name)

    return ColumnListResponse(columns=columns)


@layers_router.get(
    "/{dataset_id}/columns/{column_name}/references",
    response_model=ColumnReferencesResponse,
)
async def column_references_endpoint(
    dataset_id: uuid.UUID,
    column_name: str,
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> ColumnReferencesResponse:
    """Count saved maps whose layer config references a column.

    fix(#458 E-06): surfaced in the schema editor before a rename/drop so the
    editor knows how many saved maps depend on the column. Count only — map
    titles may belong to other users and are not exposed here.
    """
    dataset = await get_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)

    count = await count_maps_referencing_column(db, dataset_id, column_name)
    return ColumnReferencesResponse(map_count=count)
