"""Dataset analysis endpoints: parameterized PostGIS operations (M4)."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import defer_async_with_tenant
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user
from app.modules.catalog.authorization import check_dataset_access
from app.modules.catalog.datasets.domain.schemas import (
    AnalysisMaterializeRequest,
    AnalysisMaterializeResponse,
    AnalysisPreviewRequest,
    AnalysisPreviewResponse,
)
from app.modules.catalog.datasets.domain.service import (
    get_dataset,
    run_analysis_preview,
)
from app.modules.quota.service import check_upload_quota
from app.platform.analysis_sql import render_mask_expr
from app.platform.extensions import get_catalog_port
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.sandbox.schemas import SandboxError
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Analysis"], responses=ERROR_RESPONSES_WRITE
)

_SAFE_COLUMN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Sandbox error categories → HTTP status. Everything else is a sanitized 500.
_SANDBOX_STATUS = {
    "query_busy": status.HTTP_429_TOO_MANY_REQUESTS,
    "query_timeout": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


async def _load_vector_dataset(db: AsyncSession, dataset_id: uuid.UUID, user: Identity):
    """Fetch + visibility-check a dataset and require it to be vector."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_access(db, dataset, dataset_id, user)
    if not dataset.geometry_type or not dataset.table_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Analysis requires a vector dataset",
        )
    return dataset


@router.post("/{dataset_id}/analysis/preview/", response_model=AnalysisPreviewResponse)
async def analysis_preview_endpoint(
    dataset_id: uuid.UUID,
    body: AnalysisPreviewRequest,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisPreviewResponse:
    """Run a parameterized PostGIS operation and return a GeoJSON preview.

    Synchronous, read-only, and capped: results are for on-map preview, not
    persistence — use the materialize endpoint to save output as a dataset.
    """
    dataset = await _load_vector_dataset(db, dataset_id, user)
    try:
        return await run_analysis_preview(db, dataset, body, user.id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SandboxError as exc:
        raise HTTPException(
            status_code=_SANDBOX_STATUS.get(
                exc.category, status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=exc.user_message,
        ) from exc


@router.post(
    "/{dataset_id}/analysis/materialize/",
    response_model=AnalysisMaterializeResponse,
)
async def analysis_materialize_endpoint(
    dataset_id: uuid.UUID,
    body: AnalysisMaterializeRequest,
    request: Request,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisMaterializeResponse:
    """Materialize an analysis result as a new private dataset (async job).

    Requires read visibility on the source dataset; the new dataset is owned
    by the caller and counted against their dataset quota (the atomic slot
    reservation runs at registration inside the worker). Poll
    ``GET /jobs/{job_id}`` for progress.
    """
    dataset = await _load_vector_dataset(db, dataset_id, user)

    # Fail fast on invalid params before creating a job.
    if body.operation == "clip":
        try:
            render_mask_expr(body.mask or {})
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
    if body.operation == "dissolve" and body.by_field is not None:
        known_columns = {col.get("name") for col in (dataset.column_info or []) if col}
        if (
            not _SAFE_COLUMN_RE.match(body.by_field)
            or body.by_field not in known_columns
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown dissolve column: {body.by_field!r}",
            )

    # Best-effort dataset-count pre-check; the authoritative atomic
    # reservation happens at registration time in the worker.
    await check_upload_quota(db, user.id, 0, request)

    job = await get_catalog_port().create_ingest_job(
        db, f"analysis-{body.operation}", "", user.id
    )
    await db.commit()

    rollback = make_ingest_job_failed_rollback(
        job, message_prefix="Failed to queue analysis task"
    )

    async def _defer() -> None:
        await defer_async_with_tenant(
            get_catalog_port().materialize_analysis_task(),
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            user_id=str(user.id),
            operation=body.operation,
            title=body.title,
            distance_meters=body.distance_meters,
            mask=body.mask,
            by_field=body.by_field,
        )

    await defer_with_orphan_guard(_defer, rollback=rollback, db=db)

    return AnalysisMaterializeResponse(job_id=job.id, status="pending")
