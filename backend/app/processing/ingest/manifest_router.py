"""Manifest apply API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.processing.ingest import manifest_service
from app.processing.ingest.manifest_schemas import (
    ManifestApplyRequest,
    ManifestApplyResponse,
)
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

manifest_router = APIRouter(
    prefix="/ingest/manifest",
    tags=["Datasets"],
    responses=ERROR_RESPONSES_WRITE,
)


@manifest_router.post("/apply", response_model=ManifestApplyResponse)
async def apply_manifest_endpoint(
    request: ManifestApplyRequest,
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> ManifestApplyResponse:
    """Apply a versioned manifest through the ingest service layer."""
    return await manifest_service.apply_manifest(db, request, user)
