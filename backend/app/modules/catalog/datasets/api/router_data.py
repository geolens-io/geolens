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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.auth.dependencies import (
    get_optional_user,
    require_permission,
)
from app.modules.auth.models import User
from app.modules.auth.visibility import (
    check_dataset_access_or_anonymous,
    get_user_roles,
)
from app.modules.catalog.datasets.domain.models import Dataset as DatasetModel
from app.modules.catalog.datasets.domain.schemas import (
    DatasetRowsResponse,
    RelatedDatasetsResponse,
    StatusUpdate,
    StatusUpdateResponse,
)
from app.modules.catalog.maps.schemas import MapListResponse
from app.modules.catalog.datasets.domain.service import (
    get_dataset,
    get_dataset_rows,
    get_related_datasets,
)
from app.core.dependencies import get_db
from app.processing.ingest.metadata import compute_quality_score
from app.modules.catalog.validation.schemas import (
    ValidationIssue as ValidationIssueSchema,
    ValidationResultResponse,
)
from app.modules.catalog.validation.service import validate_record as run_validation

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

    try:
        rows, approx_total, columns, next_cursor = await get_dataset_rows(
            db,
            dataset.table_name,
            limit=limit,
            after_gid=after,
            column_info=dataset.column_info,
            filters=filters if filters else None,
        )
    except DBAPIError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filter parameters",
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
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> MapListResponse:
    """Return maps that contain this dataset, filtered by caller's RBAC visibility."""
    from app.modules.catalog.maps.service import get_maps_for_dataset

    user_id = user.id if user else None
    user_roles = await get_user_roles(db, user) if user else set()

    maps, total = await get_maps_for_dataset(
        db,
        dataset_id,
        user_id=user_id,
        user_roles=user_roles,
        skip=skip,
        limit=limit,
    )
    return MapListResponse(maps=maps, total=total)


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


# Ordered status chain used by target_status to walk transitions
_STATUS_ORDER = ["draft", "ready", "internal", "published"]


@router.patch("/{dataset_id}/target-status/", response_model=StatusUpdateResponse)
async def set_target_status(
    dataset_id: uuid.UUID,
    body: StatusUpdate,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StatusUpdateResponse:
    """Walk the publication chain from current status to target in one request.

    Executes each intermediate transition so the full chain
    (e.g. draft -> ready -> internal -> published) completes server-side.
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

    if current == target:
        return StatusUpdateResponse(id=str(dataset.id), record_status=current)

    cur_idx = _STATUS_ORDER.index(current) if current in _STATUS_ORDER else -1
    tgt_idx = _STATUS_ORDER.index(target) if target in _STATUS_ORDER else -1
    if cur_idx == -1 or tgt_idx == -1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown status value: '{current}' or '{target}'",
        )

    step = 1 if tgt_idx > cur_idx else -1
    idx = cur_idx
    while idx != tgt_idx:
        next_idx = idx + step
        next_status = _STATUS_ORDER[next_idx]
        if next_status not in ALLOWED_TRANSITIONS.get(_STATUS_ORDER[idx], set()):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot transition from '{_STATUS_ORDER[idx]}' to '{next_status}'. "
                    f"Allowed: {ALLOWED_TRANSITIONS.get(_STATUS_ORDER[idx], set())}"
                ),
            )
        dataset.record.record_status = next_status
        idx = next_idx

    await db.commit()
    await db.refresh(dataset)
    return StatusUpdateResponse(id=str(dataset.id), record_status=target)
