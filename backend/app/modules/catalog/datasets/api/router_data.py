"""Dataset data access endpoints: rows, validate, related, maps, and publication status."""

import json
import uuid
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import BAD_QUERY_INPUT, sqlstate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.core.record_types import capabilities
from app.modules.auth.dependencies import (
    get_optional_user,
    require_permission,
)
from app.modules.catalog.authorization import (
    check_dataset_access_or_anonymous,
    check_dataset_write_access,
    check_vrt_audiences_after_change,
    lock_dataset_rows_for_write,
)
from app.modules.catalog.datasets.domain.helpers import WorkflowTransitionDenied
from app.modules.catalog.datasets.domain.models import Dataset as DatasetModel
from app.modules.catalog.datasets.domain.schemas import (
    DatasetRowsResponse,
    RelatedDatasetsResponse,
    StatusUpdate,
    StatusUpdateResponse,
)
from app.modules.catalog.maps.schemas import MapListResponse
from app.modules.catalog.maps.visibility_contract import map_visibility_contract
from app.modules.catalog.records.inherited import (
    inherited_keyword_disclosure_warning,
)
from app.modules.catalog.features.service import current_table_oid
from app.modules.catalog.datasets.domain.service import (
    InvalidSortColumn,
    compile_layer_filter,
    get_dataset,
    get_dataset_rows,
    get_related_datasets,
    refuse_stranding_shared_maps,
    sortable_columns,
)
from app.core.dependencies import get_db
from app.core.persistent_config import (
    REQUIRE_METADATA_FOR_PUBLISH,
    get_cached_semantic_search_rate_limit,
)
from app.platform.ratelimit import limiter
from app.platform.extensions import get_catalog_port, get_workflow_extension
from app.platform.extensions.defaults import DefaultWorkflowExtension
from app.platform.extensions.protocols import WorkflowTransitionContext
from app.modules.catalog.validation.schemas import (
    ValidationIssue as ValidationIssueSchema,
    ValidationResultResponse,
)
from app.modules.catalog.validation.service import validate_record as run_validation
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE, FORBIDDEN_RESPONSE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Data"], responses=ERROR_RESPONSES_WRITE
)


def _semantic_search_rate_limit(_request: Request | None = None) -> str:
    """Per-IP rate limit for embedding-cost endpoints."""
    return f"{get_cached_semantic_search_rate_limit()}/minute"


@router.get(
    "/{dataset_id}/related/",
    response_model=RelatedDatasetsResponse,
    responses={403: FORBIDDEN_RESPONSE},
)
@limiter.limit(_semantic_search_rate_limit)
async def list_related_datasets(
    request: Request,
    dataset_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> RelatedDatasetsResponse:
    """Return top-5 datasets similar to this one by embedding cosine similarity."""
    # Visibility-gate the SEED before reading its embedding -- an
    # anonymous attacker could otherwise probe any UUID via a
    # cosine-distance oracle leaking content about the private seed. The
    # neighbor query already applies apply_visibility_filter separately.
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    user_roles = await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
    items = await get_related_datasets(db, dataset_id, user, user_roles)
    return RelatedDatasetsResponse(items=items, total=len(items))


@router.get(
    "/{dataset_id}/rows/",
    response_model=DatasetRowsResponse,
    responses={403: FORBIDDEN_RESPONSE},
)
async def get_dataset_rows_endpoint(
    request: Request,
    dataset_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    after: int = Query(0, ge=0),
    sort: str | None = Query(
        None,
        description=(
            "Column to order rows by, then by gid. NULLs sort last in both"
            " directions. An unknown or unsortable column returns 400."
        ),
    ),
    order: Literal["asc", "desc"] = Query(
        "asc", description="Sort direction; applies only with `sort`."
    ),
    filter: str | None = Query(
        None,
        description=(
            "Optional CQL2-JSON filter expression (as the OGC items route's"
            " ``filter-lang=cql2-json``). ANDs with the ``filter[column]``"
            " ILIKE filters; malformed expressions and unknown columns"
            " return 400."
        ),
    ),
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> DatasetRowsResponse:
    """Get keyset-paginated rows from a dataset's data table.

    Uses cursor-based pagination: pass ``after`` (the ``next_cursor`` gid) to
    fetch the next page, with or without ``sort``.
    Supports column filtering via query params: ``filter[column_name]=value``.
    An optional CQL2-JSON ``filter`` expression ANDs with them.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)
    if not capabilities(dataset.record.record_type).feature_table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This dataset has no data table",
        )

    # Compiled after the access guard, so a filter's validity never leaks a
    # dataset's existence or column set to a caller who cannot read it. The
    # helpers are the OGC items route's: a parse/compile failure is the
    # caller's bug and 400s before any row query runs.
    cql2_filter: tuple[str, list] | None = None
    if filter is not None:
        try:
            parsed = json.loads(filter)
            # A present-but-null body is a malformed expression, not an
            # absent one: None is compile_layer_filter's "no filter" input.
            if parsed is None:
                raise ValueError("filter must be a CQL2-JSON expression, not null")
            cql2_filter = await compile_layer_filter(
                db, dataset, parsed, bind_prefix="cql2_rows"
            )
        except (ValueError, RecursionError) as exc:
            # RecursionError is no ValueError: a body nested past the JSON
            # parser's own depth limit is the caller's bug all the same, and
            # must not surface as a 500.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid filter parameters: {exc}",
            ) from exc

    filters: dict[str, str] = {}
    for key, value in request.query_params.items():
        if key.startswith("filter[") and key.endswith("]") and value:
            col_name = key[7:-1]
            filters[col_name] = value

    table_name = dataset.table_name
    # Read before the rows: each statement takes its own snapshot, so a table
    # swapped in between can only make a later write's table_id check refuse,
    # never label old rows with the new table's id.
    table_oid = await current_table_oid(db, table_name)
    try:
        rows, total, total_kind, columns, next_cursor = await get_dataset_rows(
            db,
            table_name,
            limit=limit,
            after_gid=after,
            column_info=dataset.column_info,
            filters=filters if filters else None,
            dataset_id=dataset_id,
            sort=sort,
            descending=order == "desc",
            cql2_filter=cql2_filter,
        )
    except InvalidSortColumn:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sort column",
        )
    except DBAPIError as exc:
        # Only a caller-caused error is a 400; connection loss,
        # statement timeout, and permission failures fall through to the
        # central 503 handler rather than being reported as the caller's fault.
        if sqlstate(exc) in BAD_QUERY_INPUT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid filter parameters",
            )
        raise

    return DatasetRowsResponse(
        rows=rows,
        approximate_total=total,
        total_kind=total_kind,
        columns=columns,
        next_cursor=next_cursor,
        # `columns`, not `dataset`: an absent data table rolls the session back,
        # which expires the ORM object, and a lazy load here has no greenlet.
        sortable_columns=sortable_columns(columns),
        table_id=None if table_oid is None else str(table_oid),
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

    # The explicit ?refresh=true path recomputes and PERSISTS a fresh quality
    # score (an expensive write), restricted to owner/admin. The implicit
    # first-read populate (quality_detail is None) stays open so
    # ordinary/anonymous readers still get a score lazily.
    if refresh:
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to refresh validation.",
            )
        await check_dataset_write_access(db, dataset, dataset_id, user)

    validation = await run_validation(db, dataset.record, dataset)

    if refresh or dataset.quality_detail is None:
        quality = await get_catalog_port().compute_quality_score(
            db, dataset.table_name, dataset.column_info or [], dataset
        )
        if refresh:
            await _store_refreshed_quality(db, dataset, quality)
        else:
            _fill_quality_cache(dataset, quality)
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


@router.get(
    "/{dataset_id}/maps/",
    response_model=MapListResponse,
    responses={403: FORBIDDEN_RESPONSE},
    dependencies=[Depends(map_visibility_contract)],
)
async def dataset_maps(
    dataset_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: Identity | None = Depends(get_optional_user),
) -> MapListResponse:
    """Return maps that contain this dataset, filtered by caller's RBAC visibility."""
    from app.modules.catalog.maps.service import get_maps_for_dataset

    # Gate on dataset visibility before listing maps -- without this,
    # anonymous callers could probe any dataset_id UUID to confirm it
    # exists, which would otherwise provide an existence oracle.
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    user_roles = await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    maps, total = await get_maps_for_dataset(
        db,
        dataset_id,
        user=user,
        user_roles=user_roles,
        skip=skip,
        limit=limit,
    )
    return MapListResponse(maps=maps, total=total)


# Compatibility export for legacy tests/docs. Runtime status changes below
# use WorkflowExtension directly so overlays can replace the transition policy.
ALLOWED_TRANSITIONS = {
    status: set(targets)
    for status, targets in DefaultWorkflowExtension.DEFAULT_ALLOWED_TRANSITIONS.items()
}


async def _store_refreshed_quality(
    db: AsyncSession, dataset: DatasetModel, quality: dict
) -> None:
    """The owner's forced recompute: a write, taken under the catalog rows and
    re-checked there."""
    await lock_dataset_rows_for_write(db, dataset)
    dataset.quality_detail = quality


def _fill_quality_cache(dataset: DatasetModel, quality: dict) -> None:
    """A reader's first-read fill of the cached score.

    It writes the datasets row alone and acts for no caller, so it takes
    neither the records row nor a re-check.
    """
    dataset.quality_detail = quality


async def _roll_publication_version(db: AsyncSession, dataset: DatasetModel) -> None:
    """Retire the tile signatures minted under the status being left.

    A signed tile template binds the dataset's ``publication_version``, so
    rolling it in the transition's own transaction is what makes an unpublish
    reach the stateless tile path. Takes both catalog rows in house
    order first, since the roll makes the caller a two-row writer; call it
    immediately before the writes, with every workflow query already done.
    """
    from app.modules.catalog.features.service import lock_catalog_rows_for_write
    from app.platform.catalog_locks import bump_publication_version_on

    await lock_catalog_rows_for_write(db, dataset)
    await bump_publication_version_on(db, dataset)


async def _refuse_stranding(
    db: AsyncSession, dataset: DatasetModel, target: str
) -> None:
    """422 when moving to ``target`` strands one of the owner's shared maps."""
    try:
        await refuse_stranding_shared_maps(
            db, dataset.record, dataset.id, record_status=target
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


async def _require_publishable(db: AsyncSession, dataset: DatasetModel) -> None:
    """Refuse a transition into published while the metadata requirement is unmet.

    Runs after the catalog rows are locked, with the record reloaded, so a
    concurrent metadata edit that committed first is validated, not a stale
    snapshot.
    """
    if not await REQUIRE_METADATA_FOR_PUBLISH.get(db):
        return
    record = dataset.record
    await db.refresh(dataset)
    await db.refresh(record)
    result = await run_validation(db, record, dataset)
    if not result.is_valid:
        error_msgs = [f"{e.field}: {e.message}" for e in result.errors]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot publish: {'; '.join(error_msgs)}",
        )


@router.patch("/{dataset_id}/status/", response_model=StatusUpdateResponse)
async def update_publication_status(
    dataset_id: uuid.UUID,
    body: StatusUpdate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StatusUpdateResponse:
    """Transition a dataset's publication status following allowed paths.

    The allowed set comes from the workflow extension's
    allowed_transitions(), so an overlay may define its own. The community
    default is draft -> ready -> internal -> published (and back one step).
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
    # Owner-or-admin: publish/unpublish is a mutation. The role gate +
    # visibility check let any editor change the status of a peer's public
    # dataset (e.g. unpublish a dataset they did not publish).
    await check_dataset_write_access(db, dataset, dataset_id, user)

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
            detail=WorkflowTransitionDenied(current, target, allowed).detail,
        )
    await check_vrt_audiences_after_change(db, dataset, record_status=target)
    await _refuse_stranding(db, dataset, target)

    # The transition rolls the signed-scope counter, so this handler dirties the
    # datasets row too and must take both in house order: after the workflow
    # query, immediately before the writes.
    await _roll_publication_version(db, dataset)
    if target == "published" and current != "published":
        await _require_publishable(db, dataset)
        dataset.record.published_at = func.now()
    dataset.record.record_status = target
    await workflow.on_transition(context)
    # Writes record_status without going through
    # update_user_metadata, so it must run the same inherited-keyword
    # check or the ordinary publish flow warns nobody.
    warning = await inherited_keyword_disclosure_warning(
        db, dataset.record, dataset_id, actor=user
    )
    await db.commit()
    await db.refresh(dataset)
    return StatusUpdateResponse(
        id=str(dataset.id),
        record_status=target,
        metadata_warnings=[warning] if warning else None,
    )


@router.patch("/{dataset_id}/target-status/", response_model=StatusUpdateResponse)
async def set_target_status(
    dataset_id: uuid.UUID,
    body: StatusUpdate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StatusUpdateResponse:
    """Walk the publication chain from current status to target in one request.

    Executes each intermediate transition so the full chain completes
    server-side. The order comes from the workflow extension's
    status_order(), so an overlay may define its own; the community default
    is draft -> ready -> internal -> published.
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
    # Owner-or-admin: the role gate + visibility check alone let any editor
    # publish/unpublish a peer's public dataset through the full chain.
    await check_dataset_write_access(db, dataset, dataset_id, user)

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

    # Every workflow query runs BEFORE the pair lock, so the rows
    # are not held across extension I/O. `allowed_transitions` reads
    # `context.from_status`, never the record, so validating the whole chain
    # up front sees exactly what the per-step loop saw.
    step = 1 if tgt_idx > cur_idx else -1
    chain: list[tuple[str, WorkflowTransitionContext]] = []
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
                detail=WorkflowTransitionDenied(
                    from_status, next_status, allowed
                ).detail,
            )
        chain.append((next_status, context))
        idx = next_idx

    enters_published = any(next_status == "published" for next_status, _ in chain)

    await check_vrt_audiences_after_change(db, dataset, record_status=target)
    await _refuse_stranding(db, dataset, target)

    # Once for the whole chain, immediately before its writes.
    await _roll_publication_version(db, dataset)
    if enters_published:
        await _require_publishable(db, dataset)

    for next_status, context in chain:
        if next_status == "published":
            dataset.record.published_at = func.now()
        dataset.record.record_status = next_status
        await workflow.on_transition(context)

    # The ordinary publish flow (DatasetPage's publish toggle)
    # lands here, not in update_user_metadata -- the inherited-keyword
    # check has to run after the chain completes.
    warning = await inherited_keyword_disclosure_warning(
        db, dataset.record, dataset_id, actor=user
    )
    await db.commit()
    await db.refresh(dataset)
    return StatusUpdateResponse(
        id=str(dataset.id),
        record_status=target,
        metadata_warnings=[warning] if warning else None,
    )
