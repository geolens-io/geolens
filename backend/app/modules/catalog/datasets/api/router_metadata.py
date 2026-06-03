"""Dataset metadata endpoints: attributes, column stats, versions, and relationships."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
    require_permission,
)
from app.modules.catalog.authorization import (
    check_dataset_access,
    check_dataset_access_or_anonymous,
)
from app.modules.catalog.datasets.domain.schemas import (
    AttributeMetadataListResponse,
    AttributeMetadataResponse,
    AttributeMetadataUpdate,
    ColumnStatsResponse,
    ColumnValuesResponse,
    DatasetRelationshipCreate,
    DatasetRelationshipResponse,
    DatasetRowsResponse,
    DatasetVersionListResponse,
    DatasetVersionResponse,
)
from app.modules.catalog.datasets.domain.service import (
    get_dataset,
    get_dataset_versions,
)
from app.core.dependencies import get_db
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Metadata"], responses=ERROR_RESPONSES_WRITE
)


# ---------------------------------------------------------------------------
# Versions endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/{dataset_id}/versions/",
    response_model=DatasetVersionListResponse,
)
async def get_dataset_versions_endpoint(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetVersionListResponse:
    """Get paginated version history for a dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    versions, total = await get_dataset_versions(db, dataset_id, skip=skip, limit=limit)

    return DatasetVersionListResponse(
        versions=[DatasetVersionResponse.model_validate(v) for v in versions],
        total=total,
    )


# ---------------------------------------------------------------------------
# Attribute metadata endpoints
# ---------------------------------------------------------------------------


@router.get("/{dataset_id}/attributes/", response_model=AttributeMetadataListResponse)
async def list_attributes_endpoint(
    dataset_id: uuid.UUID,
    include_removed: bool = Query(False),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> AttributeMetadataListResponse:
    """List all attribute metadata for a dataset."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
    from app.modules.catalog.datasets.domain.service import list_attributes

    attributes = await list_attributes(db, dataset_id, include_removed=include_removed)
    return AttributeMetadataListResponse(
        attributes=[AttributeMetadataResponse.model_validate(a) for a in attributes],
        total=len(attributes),
    )


@router.get(
    "/{dataset_id}/attributes/{attribute_id}/", response_model=AttributeMetadataResponse
)
async def get_attribute_endpoint(
    dataset_id: uuid.UUID,
    attribute_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AttributeMetadataResponse:
    """Get a single attribute metadata entry."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)
    from app.modules.catalog.datasets.domain.service import get_attribute

    attr = await get_attribute(db, attribute_id)
    if attr is None or attr.dataset_id != dataset.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    return AttributeMetadataResponse.model_validate(attr)


@router.patch(
    "/{dataset_id}/attributes/{attribute_id}/", response_model=AttributeMetadataResponse
)
async def update_attribute_endpoint(
    dataset_id: uuid.UUID,
    attribute_id: uuid.UUID,
    body: AttributeMetadataUpdate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> AttributeMetadataResponse:
    """Update user-editable attribute metadata fields."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)
    from app.modules.catalog.datasets.domain.service import (
        get_attribute as get_attr_svc,
    )
    from app.modules.catalog.datasets.domain.service import update_attribute

    attr = await get_attr_svc(db, attribute_id)
    if attr is None or attr.dataset_id != dataset.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    try:
        # Use exclude_unset (not exclude_none) so explicit null clears the field
        updates = body.model_dump(exclude_unset=True)
        if updates:
            attr = await update_attribute(db, attribute_id, **updates)
            dataset.record.updated_by = user.id
            await audit_emit(
                db,
                AuditEvent(
                    user_id=user.id,
                    action="attribute.edit",
                    resource_type="dataset",
                    resource_id=dataset_id,
                    details={
                        "attribute_id": str(attr.id),
                        "field_name": attr.field_name,
                        "changed_fields": sorted(updates.keys()),
                    },
                ),
            )
            await db.commit()
        await db.refresh(attr)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    return AttributeMetadataResponse.model_validate(attr)


@router.post(
    "/{dataset_id}/attributes/{attribute_id}/reset/",
    response_model=AttributeMetadataResponse,
)
async def reset_attribute_endpoint(
    dataset_id: uuid.UUID,
    attribute_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> AttributeMetadataResponse:
    """Reset attribute metadata to auto-populated values, clearing user_modified_fields."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access(db, dataset, dataset_id, user)
    from app.modules.catalog.datasets.domain.service import (
        get_attribute as get_attr_svc,
    )
    from app.modules.catalog.datasets.domain.service import reset_attribute

    attr = await get_attr_svc(db, attribute_id)
    if attr is None or attr.dataset_id != dataset.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    try:
        attr = await reset_attribute(db, attribute_id, dataset.table_name)
        dataset.record.updated_by = user.id
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="attribute.reset",
                resource_type="dataset",
                resource_id=dataset_id,
                details={
                    "attribute_id": str(attr.id),
                    "field_name": attr.field_name,
                    "changed_fields": [
                        "title",
                        "description",
                        "units",
                        "domain_type",
                        "semantic_role",
                        "example_values",
                        "user_modified_fields",
                    ],
                },
            ),
        )
        await db.commit()
        await db.refresh(attr)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Attribute not found"
        )
    return AttributeMetadataResponse.model_validate(attr)


# ---------------------------------------------------------------------------
# Column values & stats endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{dataset_id}/columns/{column_name}/values/", response_model=ColumnValuesResponse
)
async def get_column_values(
    dataset_id: uuid.UUID,
    column_name: str,
    limit: int = Query(100, ge=1, le=500),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ColumnValuesResponse:
    """Get distinct values for a dataset column (for categorical styling)."""
    from app.modules.catalog.datasets.domain.column_stats import get_distinct_values

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        values = await get_distinct_values(db, dataset.table_name, column_name, limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return ColumnValuesResponse(values=values, count=len(values))


@router.get(
    "/{dataset_id}/columns/{column_name}/stats/", response_model=ColumnStatsResponse
)
async def get_column_stats_endpoint(
    dataset_id: uuid.UUID,
    column_name: str,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ColumnStatsResponse:
    """Get statistics for a numeric dataset column (for graduated styling)."""
    from app.modules.catalog.datasets.domain.column_stats import get_column_stats

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access(db, dataset, dataset_id, user)

    try:
        stats = await get_column_stats(db, dataset.table_name, column_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    return ColumnStatsResponse(**stats)


# ---------------------------------------------------------------------------
# Dataset FK relationships
# ---------------------------------------------------------------------------


@router.get(
    "/{dataset_id}/relationships/",
    response_model=list[DatasetRelationshipResponse],
)
async def list_dataset_relationships(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0, description="Number of relationships to skip."),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Maximum number of relationships to return (PERF-N16).",
    ),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> list[DatasetRelationshipResponse]:
    """List FK relationships for a dataset.

    Paginated via ``skip`` and ``limit`` to bound response size for datasets
    with large numbers of auto-detected relationships.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    from app.modules.catalog.datasets.domain.service import list_relationships

    items = await list_relationships(db, dataset.record_id, skip=skip, limit=limit)
    return [DatasetRelationshipResponse(**item) for item in items]


@router.post(
    "/{dataset_id}/relationships/",
    response_model=DatasetRelationshipResponse,
    status_code=201,
)
async def create_dataset_relationship(
    dataset_id: uuid.UUID,
    body: DatasetRelationshipCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Identity = Depends(require_permission("edit_metadata")),
) -> DatasetRelationshipResponse:
    """Create a new FK relationship. Editor+ required."""
    from app.modules.catalog.datasets.domain.service import create_relationship

    # Resolve dataset_id to record_id (FK references catalog.records.id)
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    rel = await create_relationship(db, dataset.record_id, body)
    await db.commit()
    return DatasetRelationshipResponse.model_validate(rel)


@router.delete("/relationships/{relationship_id}/", status_code=204)
async def delete_dataset_relationship(
    relationship_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Identity = Depends(require_permission("edit_metadata")),
) -> Response:
    """Delete a FK relationship. Editor+ required."""
    from app.modules.catalog.datasets.domain.service import delete_relationship

    try:
        await delete_relationship(db, relationship_id)
        await db.commit()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Relationship not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{dataset_id}/features/{gid}/related/{relationship_id}/",
    response_model=DatasetRowsResponse,
)
async def get_feature_related_records(
    dataset_id: uuid.UUID,
    gid: int,
    relationship_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    after: int = Query(0, ge=0),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetRowsResponse:
    """Get related records for a feature via FK relationship."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    from app.modules.catalog.datasets.domain.service import get_related_records

    try:
        result = await get_related_records(
            db, dataset_id, gid, relationship_id, limit=limit, after=after
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return DatasetRowsResponse(**result)
