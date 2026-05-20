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

from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_optional_user,
    require_permission,
)
from app.modules.catalog.authorization import (
    check_dataset_access,
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
from app.platform.extensions import get_catalog_port, get_workflow_extension
from app.platform.extensions.defaults import DefaultWorkflowExtension
from app.platform.extensions.protocols import WorkflowTransitionContext
from app.modules.catalog.validation.schemas import (
    ValidationIssue as ValidationIssueSchema,
    ValidationResultResponse,
)
from app.modules.catalog.validation.service import validate_record as run_validation
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Data"], responses=ERROR_RESPONSES_WRITE
)


@router.get("/{dataset_id}/related/", response_model=RelatedDatasetsResponse)
async def list_related_datasets(
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> RelatedDatasetsResponse:
    """Return top-5 datasets similar to this one by embedding cosine similarity."""
    # Phase 1061 SEC-S05: visibility-gate the SEED before reading its embedding.
    # Before this fix, anonymous attackers could probe any UUID — neighbor-similarity
    # scores leaked content about the private seed via cosine-distance oracle.
    # The neighbor query (inside get_related_datasets) already applies
    # apply_visibility_filter, so neighbors stay correctly gated.
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    user_roles = await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
    items = await get_related_datasets(db, dataset_id, user, user_roles)
    return RelatedDatasetsResponse(items=items, total=len(items))


@router.get("/{dataset_id}/rows/", response_model=DatasetRowsResponse)
async def get_dataset_rows_endpoint(
    request: Request,
    dataset_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    after: int = Query(0, ge=0),
    user: Identity | None = Depends(get_optional_user),
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
    user: Identity | None = Depends(get_optional_user),
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
        quality = await get_catalog_port().compute_quality_score(
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
    user: Identity | None = Depends(get_optional_user),
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

# Compatibility export for legacy tests/docs. Runtime status changes below use
# WorkflowExtension directly so overlays can replace the transition policy.
ALLOWED_TRANSITIONS = {
    status: set(targets)
    for status, targets in DefaultWorkflowExtension.DEFAULT_ALLOWED_TRANSITIONS.items()
}


@router.patch("/{dataset_id}/status/", response_model=StatusUpdateResponse)
async def update_publication_status(
    dataset_id: uuid.UUID,
    body: StatusUpdate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
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
    # Phase 1061 CR-01: resource-level access check (SEC-S02 pattern).
    # require_permission("edit_metadata") is role-level only; any editor
    # could otherwise promote another user's private dataset to published.
    await check_dataset_access(db, dataset, dataset_id, user)

    current = dataset.record.record_status
    target = body.status
    workflow = get_workflow_extension()
    context = WorkflowTransitionContext(
        session=db,
        dataset=dataset,
        actor=user,
        from_status=current,
        to_status=target,
        mode="status",
    )
    allowed = await workflow.allowed_transitions(context)
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot transition from '{current}' to '{target}'. Allowed: {allowed}"
            ),
        )

    dataset.record.record_status = target
    await workflow.on_transition(context)
    await db.commit()
    await db.refresh(dataset)
    return StatusUpdateResponse(id=str(dataset.id), record_status=target)


@router.patch("/{dataset_id}/target-status/", response_model=StatusUpdateResponse)
async def set_target_status(
    dataset_id: uuid.UUID,
    body: StatusUpdate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
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
    # Phase 1061 CR-01: resource-level access check (SEC-S02 pattern).
    # require_permission("edit_metadata") is role-level only; any editor
    # could otherwise walk another user's private dataset through the full
    # draft→ready→internal→published chain without ownership check.
    await check_dataset_access(db, dataset, dataset_id, user)

    current = dataset.record.record_status
    target = body.status
    workflow = get_workflow_extension()

    if current == target:
        return StatusUpdateResponse(id=str(dataset.id), record_status=current)

    status_order = list(workflow.status_order())
    cur_idx = status_order.index(current) if current in status_order else -1
    tgt_idx = status_order.index(target) if target in status_order else -1
    if cur_idx == -1 or tgt_idx == -1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown status value: '{current}' or '{target}'",
        )

    step = 1 if tgt_idx > cur_idx else -1
    idx = cur_idx
    while idx != tgt_idx:
        next_idx = idx + step
        from_status = status_order[idx]
        next_status = status_order[next_idx]
        context = WorkflowTransitionContext(
            session=db,
            dataset=dataset,
            actor=user,
            from_status=from_status,
            to_status=next_status,
            mode="target_status",
        )
        allowed = await workflow.allowed_transitions(context)
        if next_status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Cannot transition from '{from_status}' to '{next_status}'. "
                    f"Allowed: {allowed}"
                ),
            )
        dataset.record.record_status = next_status
        await workflow.on_transition(context)
        idx = next_idx

    await db.commit()
    await db.refresh(dataset)
    return StatusUpdateResponse(id=str(dataset.id), record_status=target)
