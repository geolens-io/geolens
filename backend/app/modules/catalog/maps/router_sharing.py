"""Public sharing, visibility checks, and style export routes for saved maps."""

from __future__ import annotations

import html
import uuid

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.core.tenancy import is_multi_tenant
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
    require_permission,
)
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.maps._router_helpers import (
    _build_frame_ancestors,
    _check_map_read_access,
    _layers_from_tuples,
)
from app.modules.catalog.maps.schemas import (
    ShareTokenRequest,
    ShareTokenResponse,
    SharedMapResponse,
    VisibilityCheckResponse,
)
from app.modules.catalog.maps.sharing import get_share_card_image_url
from app.modules.catalog.maps.service import (
    _validate_share_token,
    check_map_ownership,
    create_share_token,
    filter_layer_rows_by_dataset_visibility,
    get_active_share_token,
    get_map,
    get_map_with_layers,
    get_shared_map,
    revoke_share_token_by_map,
    update_share_token,
    validate_public_visibility,
)
from app.modules.catalog.maps.style_json import build_maplibre_style
from app.modules.embed_tokens.service import revoke_embed_tokens_by_map
from app.standards.ogc.errors import GONE_RESPONSE

router = APIRouter()


@router.get(
    "/shared/{token}/card",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def shared_map_card_endpoint(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Return crawler HTML for a public shared map.

    Invalid, expired, revoked, and non-public links return 404 before map details
    are rendered. User-controlled text is escaped before it enters social-card
    metadata. This crawler-only route is excluded from OpenAPI.
    """
    token_obj = await _validate_share_token(db, token)
    if token_obj is None or isinstance(token_obj, str):
        raise HTTPException(status_code=404, detail="Share link not found")

    map_obj = await get_map(db, token_obj.map_id)
    if map_obj is None or map_obj.visibility != "public":
        raise HTTPException(status_code=404, detail="Share link not found")

    image_url = await get_share_card_image_url(db, request, map_obj)
    image_url = html.escape(image_url, quote=True)
    title = html.escape(map_obj.name or "GeoLens Map")
    description = html.escape(map_obj.description or "View this map on GeoLens")
    viewer_url = f"/m/{html.escape(token)}"
    card_html = (
        "<!doctype html>\n"
        "<html><head>\n"
        '<meta charset="UTF-8">\n'
        '<meta property="og:type" content="website">\n'
        f'<meta property="og:title" content="{title}">\n'
        f'<meta property="og:description" content="{description}">\n'
        f'<meta property="og:image" content="{image_url}">\n'
        '<meta name="twitter:card" content="summary_large_image">\n'
        f'<meta name="twitter:title" content="{title}">\n'
        f'<meta name="twitter:description" content="{description}">\n'
        f'<meta name="twitter:image" content="{image_url}">\n'
        f'<meta http-equiv="refresh" content="0;url={viewer_url}">\n'
        "</head><body></body></html>"
    )
    return HTMLResponse(
        content=card_html,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get(
    "/shared/{token}",
    response_model=SharedMapResponse,
    responses={410: GONE_RESPONSE},
)
async def get_shared_map_endpoint(
    token: str,
    response: Response,
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    embed_token: str | None = Header(
        default=None,
        alias="X-Embed-Token",
        description="Optional embed token — includes its scoped dataset layers when valid for this map.",
    ),
    db: AsyncSession = Depends(get_db),
) -> SharedMapResponse:
    """Get a shared map by token. Optionally authenticated for non-public layers.

    SEC-S08 (Phase 1062-05): emits ``Content-Security-Policy: frame-ancestors
    'self' [<allowed_origins>...]`` on the response, derived from the active
    EmbedToken for this map. When no EmbedToken exists or allowed_origins is
    empty, defaults to ``frame-ancestors 'self'``. The SecurityHeadersMiddleware
    respects this route-level CSP and skips emitting X-Frame-Options: DENY.

    fix(#394) SH-01/B-023: accepts ``X-Embed-Token`` so embed viewers get the
    layers the token's scope authorizes (SEC-022 capability posture).
    """
    user_roles = await get_user_roles(db, user) if user is not None else set()
    result = await get_shared_map(
        db,
        token,
        user=user,
        user_roles=user_roles,
        embed_token=embed_token,
        request=request,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Shared map not found")
    if result == "expired":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This shared map link has expired or been revoked",
        )
    map_data, layers, allowed_origins = result
    response.headers["Content-Security-Policy"] = _build_frame_ancestors(
        allowed_origins
    )
    return SharedMapResponse(**map_data, layers=layers)


@router.get("/{map_id}/visibility-check/", response_model=VisibilityCheckResponse)
async def visibility_check_endpoint(
    map_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> VisibilityCheckResponse:
    """Check if a map has non-public datasets. Informational only."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(status_code=404, detail="Map not found")
    await _check_map_read_access(map_obj, user, db)
    non_public_names = await validate_public_visibility(db, map_id)
    return VisibilityCheckResponse(
        non_public_datasets=non_public_names,
        has_non_public=len(non_public_names) > 0,
    )


@router.get("/{map_id}/style.json")
async def export_map_style_endpoint(
    map_id: uuid.UUID,
    request: Request,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Export a saved map as a complete MapLibre style JSON document."""
    tenant_id = getattr(getattr(request, "state", None), "tenant_id", None)
    if is_multi_tenant() and tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context is required for map style export",
        )
    map_obj, layer_tuples, _, _ = await get_map_with_layers(db, map_id)
    if map_obj is None:
        raise HTTPException(status_code=404, detail="Map not found")
    await _check_map_read_access(map_obj, user, db)
    layer_tuples = await filter_layer_rows_by_dataset_visibility(db, layer_tuples, user)
    style = build_maplibre_style(
        map_obj,
        _layers_from_tuples(layer_tuples),
        mvt_source_layer_prefix=tenant_data_schema(tenant_id),
    )
    return JSONResponse(
        content=style,
        media_type="application/json",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{map_id}/share/", response_model=ShareTokenResponse | None)
async def get_map_share_token_endpoint(
    map_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ShareTokenResponse | None:
    """Return the active share token for a map, or null if none exists."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(status_code=404, detail="Map not found")
    await check_map_ownership(map_obj, user, db)
    token_obj = await get_active_share_token(db, map_id)
    if token_obj is None:
        return None
    return ShareTokenResponse(
        token=token_obj.token_hint,
        share_url=None,
        expires_at=token_obj.expires_at,
        is_active=token_obj.is_active,
    )


@router.post("/{map_id}/share/", response_model=ShareTokenResponse)
async def share_map_endpoint(
    map_id: uuid.UUID,
    request: Request,
    body: ShareTokenRequest | None = Body(default=None),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ShareTokenResponse:
    """Create or retrieve a share token for a public map."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(status_code=404, detail="Map not found")
    await check_map_ownership(map_obj, user, db)
    if map_obj.visibility != "public":
        raise HTTPException(status_code=400, detail="Map must be public before sharing")
    try:
        token_obj = await create_share_token(
            db,
            map_id,
            user.id,
            expires_at=body.expires_at if body else None,
            expires_in_days=body.expires_in_days if body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.share",
            resource_type="map",
            resource_id=map_id,
            details={"token_hint": token_obj.token_hint},
            ip_address=request.client.host if request.client else None,
        ),
    )
    await db.commit()
    raw_token = getattr(token_obj, "_raw_token", None)
    return ShareTokenResponse(
        token=raw_token or token_obj.token_hint,
        share_url=f"/m/{raw_token}" if raw_token else None,
        expires_at=token_obj.expires_at,
        is_active=token_obj.is_active,
    )


@router.patch("/{map_id}/share/", response_model=ShareTokenResponse)
async def update_map_share_token_endpoint(
    map_id: uuid.UUID,
    body: ShareTokenRequest,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ShareTokenResponse:
    """Update expiration on an existing share token. Owner or admin only.

    A fixed-day preset is available in every edition. Null clears expiration.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(status_code=404, detail="Map not found")
    await check_map_ownership(map_obj, user, db)
    try:
        token_obj = await update_share_token(
            db,
            map_id,
            body.expires_at,
            expires_in_days=body.expires_in_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if token_obj is None:
        raise HTTPException(status_code=404, detail="No active share token found")
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.update_share_token",
            resource_type="map",
            resource_id=map_id,
            details={
                "expires_at": (
                    token_obj.expires_at.isoformat() if token_obj.expires_at else None
                )
            },
            ip_address=request.client.host if request.client else None,
        ),
    )
    await db.commit()
    return ShareTokenResponse(
        token=token_obj.token_hint,
        share_url=None,
        expires_at=token_obj.expires_at,
        is_active=token_obj.is_active,
    )


@router.delete("/{map_id}/share/", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_map_share_endpoint(
    map_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke share token(s) for a map. Owner or admin only."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(status_code=404, detail="Map not found")
    await check_map_ownership(map_obj, user, db)
    revoked_share = await revoke_share_token_by_map(db, map_id)
    revoked_embed = await revoke_embed_tokens_by_map(db, map_id)
    if not revoked_share and not revoked_embed:
        raise HTTPException(
            status_code=404,
            detail="No active share or embed token found",
        )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.revoke_share",
            resource_type="map",
            resource_id=map_id,
            details={},
            ip_address=request.client.host if request.client else None,
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
