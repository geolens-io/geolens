"""Dataset analysis endpoints: parameterized PostGIS operations (M4)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user
from app.modules.catalog.authorization import check_dataset_access
from app.modules.catalog.datasets.domain.schemas import (
    AnalysisPreviewRequest,
    AnalysisPreviewResponse,
)
from app.modules.catalog.datasets.domain.service import (
    get_dataset,
    run_analysis_preview,
)
from app.platform.sandbox.schemas import SandboxError
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Analysis"], responses=ERROR_RESPONSES_WRITE
)

# Sandbox error categories → HTTP status. Everything else is a sanitized 500.
_SANDBOX_STATUS = {
    "query_busy": status.HTTP_429_TOO_MANY_REQUESTS,
    "query_timeout": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


@router.post("/{dataset_id}/analysis/preview/", response_model=AnalysisPreviewResponse)
async def analysis_preview_endpoint(
    dataset_id: uuid.UUID,
    body: AnalysisPreviewRequest,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisPreviewResponse:
    """Run a parameterized PostGIS operation and return a GeoJSON preview.

    Synchronous, read-only, and capped: results are for on-map preview, not
    persistence — materializing output as a dataset is a separate async path.
    """
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
