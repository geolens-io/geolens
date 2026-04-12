"""Dataset data access endpoints: rows, validate, related, maps, and publication status."""

import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import (
    get_optional_user,
    require_permission,
)
from app.auth.models import User
from app.auth.visibility import (
    check_dataset_access_or_anonymous,
    get_user_roles,
)
from app.datasets.models import Dataset as DatasetModel
from app.datasets.schemas import (
    DatasetRowsResponse,
    RelatedDatasetsResponse,
    StatusUpdate,
    StatusUpdateResponse,
)
from app.maps.schemas import MapListResponse
from app.datasets.service import (
    get_dataset,
    get_dataset_rows,
    get_related_datasets,
)
from app.dependencies import get_db
from app.ingest.metadata import compute_quality_score
from app.validation.schemas import (
    ValidationIssue as ValidationIssueSchema,
    ValidationResultResponse,
)
from app.validation.service import validate_record as run_validation

router = APIRouter(prefix="/datasets", tags=["Datasets - Data"])


@router.get("/{dataset_id}/related/", response_model=RelatedDatasetsResponse)
async def list_related_datasets(
    dataset_id: uuid.UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> RelatedDatasetsResponse:
    """Return top-5 datasets similar to this one by embedding cosine similarity."""
    user_roles = await get_user_roles(db, user) if user is not None else set()
    items = await get_related_datasets(db, dataset_id, user, user_roles)
    return RelatedDatasetsResponse(items=items, total=len(items))


@router.get("/{dataset_id}/rows/", response_model=DatasetRowsResponse)
async def get_dataset_rows_endpoint(
    request: Request,
    dataset_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    after: int = Query(0, ge=0),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetRowsResponse:
    """Get keyset-paginated rows from a dataset's data table.

    Uses cursor-based pagination: pass ``after`` (gid) to fetch the next page.
    Supports column filtering via query params: ``filter[column_name]=value``.
    """
    # Fetch dataset
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Visibility check
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    # Extract filter[col]=value params
    filters: dict[str, str] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter[") and key.endswith("]") and value:
            col_name = key[7:-1]
            filters[col_name] = value

    rows, approx_total, columns, next_cursor = await get_dataset_rows(
        db,
        dataset.table_name,
        limit=limit,
        after_gid=after,
        column_info=dataset.column_info,
        filters=filters if filters else None,
    )

    return DatasetRowsResponse(
        rows=rows,
        approximate_total=approx_total,
        columns=columns,
        next_cursor=next_cursor,
    )


@router.get("/{dataset_id}/validate/", response_model=ValidationResultResponse)
async def validate_dataset(
    dataset_id: uuid.UUID,
    refresh: bool = Query(
        False,
        description="Recompute the quality score instead of returning the cached value.",
    ),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> ValidationResultResponse:
    """Get validation status for a dataset. Shows hard errors and soft warnings.

    By default returns the quality score persisted at ingest time. Pass
    ``?refresh=true`` to recompute and persist a fresh score (expensive on
    large tables — issues a full scan per non-geometry column coalesced into
    a single query).
    """
    result = await db.execute(
        select(DatasetModel)
        .options(joinedload(DatasetModel.record))
        .where(DatasetModel.id == dataset_id)
    )
    dataset = result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    validation = await run_validation(db, dataset.record, dataset)

    if refresh or dataset.quality_detail is None:
        quality = await compute_quality_score(
            db, dataset.table_name, dataset.column_info or [], dataset
        )
        dataset.quality_detail = quality
        await db.commit()
    else:
        quality = dataset.quality_detail

    return ValidationResultResponse(
        is_valid=validation.is_valid,
        errors=[
            ValidationIssueSchema(field=e.field, message=e.message, severity=e.severity)
            for e in validation.errors
        ],
        warnings=[
            ValidationIssueSchema(field=w.field, message=w.message, severity=w.severity)
            for w in validation.warnings
        ],
        quality_score=quality,
    )


# ---------------------------------------------------------------------------
# Maps containing dataset
# ---------------------------------------------------------------------------


@router.get("/{dataset_id}/maps/", response_model=MapListResponse)
async def dataset_maps(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> MapListResponse:
    """Return maps that contain this dataset, filtered by caller's RBAC visibility."""
    from app.maps.service import get_maps_for_dataset

    user_id = user.id if user else None
    user_roles = await get_user_roles(db, user) if user else set()

    maps = await get_maps_for_dataset(
        db, dataset_id, user_id=user_id, user_roles=user_roles, skip=skip, limit=limit
    )
    return MapListResponse(maps=maps, total=len(maps))


# ---------------------------------------------------------------------------
# Publication status transitions
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS = {
    "draft": {"ready"},
    "ready": {"draft", "internal"},
    "internal": {"ready", "published"},
    "published": {"internal"},
}


@router.patch("/{dataset_id}/status/", response_model=StatusUpdateResponse)
async def update_publication_status(
    dataset_id: uuid.UUID,
    body: StatusUpdate,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StatusUpdateResponse:
    """Transition a dataset's publication status following allowed paths.

    Allowed transitions:
      draft -> ready -> internal -> published (and back one step).
    """
    dataset = await db.execute(
        select(DatasetModel)
        .options(joinedload(DatasetModel.record))
        .where(DatasetModel.id == dataset_id)
    )
    dataset = dataset.unique().scalar_one_or_none()
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )

    current = dataset.record.record_status
    target = body.status
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot transition from '{current}' to '{target}'. "
                f"Allowed: {ALLOWED_TRANSITIONS.get(current, set())}"
            ),
        )

    dataset.record.record_status = target
    await db.commit()
    await db.refresh(dataset)
    return StatusUpdateResponse(id=str(dataset.id), record_status=target)
