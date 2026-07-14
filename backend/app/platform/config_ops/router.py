"""Config operations API: export, import, and dry-run endpoints."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import require_mode_permission
from app.platform.config_ops.exceptions import (
    ConfigLockedError,
    ConfigPreviewError,
    ConfigValidationError,
)
from app.platform.config_ops.schemas import (
    ConfigImportRequest,
    ConnectivityResult,
    DryRunResponse,
    ImportMode,
    ImportResult,
)
from app.platform.config_ops.service import (
    dry_run_import,
    export_config,
    import_config,
    validate_connectivity,
)
from app.processing.export.service import safe_content_disposition
from app.standards.ogc.errors import CONFLICT_RESPONSE, ERROR_RESPONSES_AUTH

logger = structlog.stdlib.get_logger(__name__)

require_config_operator = require_mode_permission(
    single_tenant="manage_settings", multi_tenant="manage_tenants"
)

router = APIRouter(
    prefix="/config-ops", tags=["config-ops"], responses=ERROR_RESPONSES_AUTH
)


@router.get(
    "/export/",
    response_class=JSONResponse,
    responses={
        200: {
            "description": "Downloadable configuration JSON with Content-Disposition attachment header.",
            "content": {"application/json": {}},
        }
    },
)
async def export_configuration(
    request: Request,
    user: Identity = Depends(require_config_operator),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Export full configuration as JSON (settings + OAuth providers, secrets redacted).

    Returns a downloadable JSON payload with Content-Disposition header. This is a
    file-download endpoint — the previous ``response_model=ConfigExportResponse``
    was silently ignored because the handler returns a raw JSONResponse with custom
    headers (TYPE-N3). Using ``response_class=JSONResponse`` is the correct way to
    document a download endpoint in OpenAPI.
    """
    # Deferred by design: platform must not depend upward on product domains
    # at module load time (D-17). The audit module owns persistence of its DTO.
    from app.modules.audit.service import AuditEvent, audit_emit

    data = await export_config(db)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="config_export",
            resource_type="config",
            details={
                "settings_count": len(data["settings"]),
                "oauth_providers_count": len(data["oauth_providers"]),
            },
            ip_address=get_client_ip(request),
        ),
    )
    # Do not release a sensitive export unless its audit record is durable.
    await db.commit()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"geolens-config-{timestamp}.json"
    headers = {"Content-Disposition": safe_content_disposition(filename)}
    return JSONResponse(content=data, headers=headers)


@router.post(
    "/import/", response_model=ImportResult, responses={409: CONFLICT_RESPONSE}
)
async def import_configuration(
    data: ConfigImportRequest,
    request: Request,
    mode: ImportMode = Query("merge"),
    preview_token: str | None = Header(
        default=None,
        alias="X-Config-Preview-Token",
        description=(
            "Signed token returned by the matching dry-run. Required for overwrite mode."
        ),
    ),
    user: Identity = Depends(require_config_operator),
    db: AsyncSession = Depends(get_db),
) -> ImportResult:
    """Import configuration in merge or overwrite mode.

    Merge mode: updates existing settings and OAuth providers, adds new ones.
    Overwrite mode: replaces all settings and OAuth providers.
    """
    ip_address = get_client_ip(request)
    try:
        result = await import_config(
            db,
            {
                "settings": data.settings,
                "oauth_providers": data.oauth_providers,
            },
            mode,
            user.id,
            ip_address,
            preview_token=preview_token,
        )
    except ConfigLockedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Configuration locked to environment variables",
        )
    except ConfigValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except ConfigPreviewError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configuration import conflict — duplicate entry",
        )
    return result


@router.post("/validate/", response_model=ConnectivityResult)
async def validate_configuration(
    user: Identity = Depends(require_config_operator),
    db: AsyncSession = Depends(get_db),
) -> ConnectivityResult:
    """Validate connectivity to storage, cache, and all enabled OIDC providers.

    Returns pass/fail with latency and error details for each service.
    """
    result = await validate_connectivity(db)
    return result


@router.post("/dry-run/", response_model=DryRunResponse)
async def dry_run_configuration(
    data: ConfigImportRequest,
    mode: ImportMode = Query("merge"),
    user: Identity = Depends(require_config_operator),
    db: AsyncSession = Depends(get_db),
) -> DryRunResponse:
    """Preview what an import would change without applying any modifications."""
    try:
        result = await dry_run_import(
            db,
            {
                "settings": data.settings,
                "oauth_providers": data.oauth_providers,
            },
            mode,
        )
    except ConfigLockedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Configuration locked to environment variables",
        )
    except ConfigValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    return result
