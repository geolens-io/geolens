"""Config operations API: export, import, and dry-run endpoints."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.config_ops.schemas import (
    ConfigExportResponse,
    ConfigImportRequest,
    ConnectivityResult,
    DryRunResponse,
    ImportMode,
    ImportResult,
)
from app.config_ops.service import (
    dry_run_import,
    export_config,
    import_config,
    validate_connectivity,
)
from app.dependencies import get_db
from app.export.service import safe_content_disposition

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/config-ops", tags=["config-ops"])


@router.get("/export/", response_model=ConfigExportResponse)
async def export_configuration(
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Export full configuration as JSON (settings + OAuth providers, secrets redacted).

    Returns a downloadable JSON payload with Content-Disposition header.
    """
    from fastapi.responses import JSONResponse

    data = await export_config(db)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"geolens-config-{timestamp}.json"
    headers = {"Content-Disposition": safe_content_disposition(filename)}
    return JSONResponse(content=data, headers=headers)


@router.post("/import/", response_model=ImportResult)
async def import_configuration(
    data: ConfigImportRequest,
    request: Request,
    mode: ImportMode = Query("merge"),
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Import configuration in merge or overwrite mode.

    Merge mode: updates existing settings and OAuth providers, adds new ones.
    Overwrite mode: replaces all settings and OAuth providers.
    """
    ip_address = request.client.host if request.client else None
    result = await import_config(
        db,
        data.model_dump(),
        mode,
        user.id,
        ip_address,
    )
    return result


@router.post("/validate/", response_model=ConnectivityResult)
async def validate_configuration(
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Validate connectivity to storage, cache, and all enabled OIDC providers.

    Returns pass/fail with latency and error details for each service.
    """
    result = await validate_connectivity(db)
    return result


@router.post("/dry-run/", response_model=DryRunResponse)
async def dry_run_configuration(
    data: ConfigImportRequest,
    mode: ImportMode = Query("merge"),
    user: User = Depends(require_permission("manage_settings")),
    db: AsyncSession = Depends(get_db),
):
    """Preview what an import would change without applying any modifications."""
    result = await dry_run_import(db, data.model_dump(), mode)
    return result
