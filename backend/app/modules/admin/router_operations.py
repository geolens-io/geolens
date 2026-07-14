"""Admin API key, infrastructure, and sharing routes."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.dependencies import get_client_ip, get_db
from app.modules.admin.schemas import (
    AdminApiKeyCreateRequest,
    AdminApiKeyListItem,
    AdminApiKeyListResponse,
    AdminShareTokenListResponse,
    AdminShareTokenResponse,
    InfrastructureConfig,
    InfrastructureResponse,
)
from app.modules.admin.service import AdminService
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import require_mode_permission, require_permission
from app.modules.auth.models import ApiKey, User
from app.modules.auth.router import limiter
from app.modules.auth.schemas import ApiKeyCreateResponse

router = APIRouter()


def _api_key_response(key: ApiKey) -> AdminApiKeyListItem:
    """Convert an ApiKey ORM object to an AdminApiKeyListItem schema."""
    return AdminApiKeyListItem(
        id=key.id,
        user_id=key.user_id,
        name=key.name,
        fingerprint=key.fingerprint,
        is_active=key.is_active,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
    )


@router.post(
    "/api-keys",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/api-keys/",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def create_api_key(
    body: AdminApiKeyCreateRequest,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """Create an API key for a user (admin only).

    The raw key is returned only in this response and cannot be retrieved again.
    """
    from app.modules.auth.service import (
        ApiKeyTargetUserNotFoundError,
        create_api_key_for_user,
    )

    try:
        api_key, raw_key = await create_api_key_for_user(db, body.user_id, body.name)
    except ApiKeyTargetUserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from exc
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="api_key.create",
            resource_type="api_key",
            resource_id=api_key.id,
            details={
                "name": body.name,
                "fingerprint": api_key.fingerprint,
                "target_user_id": str(body.user_id),
            },
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    assert api_key.fingerprint is not None
    return ApiKeyCreateResponse(
        id=api_key.id,
        key=raw_key,
        fingerprint=api_key.fingerprint,
        name=api_key.name,
        created_at=api_key.created_at,
    )


@router.get(
    "/api-keys",
    response_model=AdminApiKeyListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
    include_in_schema=False,
)
@router.get(
    "/api-keys/",
    response_model=AdminApiKeyListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_api_keys(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user_id: uuid.UUID | None = Query(None, description="Filter by user ID"),
    db: AsyncSession = Depends(get_db),
) -> AdminApiKeyListResponse:
    """List all API keys (admin only). Never returns the raw key."""
    stmt = select(ApiKey).join(User, ApiKey.user_id == User.id)
    if user_id is not None:
        stmt = stmt.where(ApiKey.user_id == user_id)
    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    keys = (await db.execute(stmt.offset(skip).limit(limit))).scalars().all()
    return AdminApiKeyListResponse(
        items=[_api_key_response(key) for key in keys], total=total
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def revoke_api_key(
    key_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke (soft-delete) an API key (admin only)."""
    api_key = (
        await db.execute(
            select(ApiKey)
            .join(User, ApiKey.user_id == User.id)
            .where(ApiKey.id == key_id)
        )
    ).scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key not found")
    api_key.is_active = False
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="api_key.revoke",
            resource_type="api_key",
            resource_id=key_id,
            details={
                "name": api_key.name,
                "fingerprint": api_key.fingerprint,
                "target_user_id": str(api_key.user_id),
            },
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/infrastructure",
    response_model=InfrastructureResponse,
    include_in_schema=False,
)
@router.get(
    "/infrastructure/",
    response_model=InfrastructureResponse,
)
async def get_infrastructure(
    _user: User = Depends(
        require_mode_permission(
            single_tenant="manage_users", multi_tenant="manage_tenants"
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> InfrastructureResponse:
    """Return infrastructure configuration, live health status, and OIDC provider connectivity."""
    from app.observability.health.service import check_health, check_oidc_health

    health, oidc_health = await asyncio.gather(
        check_health(include_errors=True), check_oidc_health(db)
    )
    config = InfrastructureConfig(
        storage_provider=app_settings.storage_provider,
        cache_provider="redis" if app_settings.redis_url else "memory",
        database_type=(
            "external" if app_settings.database_url_override else "docker-compose"
        ),
        database_pooler=(
            "external" if app_settings.db_use_external_pooler else "internal"
        ),
        tile_cache="cdn",
        tile_cache_ttl=app_settings.tile_cache_ttl,
        cdn_configured=bool(app_settings.cdn_base_url),
    )
    return InfrastructureResponse(
        config=config, health=health["providers"], oidc_providers=oidc_health
    )


@router.get(
    "/share-tokens",
    response_model=AdminShareTokenListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
    include_in_schema=False,
)
@router.get(
    "/share-tokens/",
    response_model=AdminShareTokenListResponse,
    dependencies=[Depends(require_permission("manage_users"))],
)
async def list_share_tokens_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = Query(None, max_length=200),
    status_filter: str | None = Query(
        None, alias="status", pattern="^(active|expired|revoked)$"
    ),
    db: AsyncSession = Depends(get_db),
) -> AdminShareTokenListResponse:
    """List basic share-token inventory with map info; no quotas or domain controls (admin only)."""
    from app.modules.catalog.maps.service import list_share_tokens

    tokens, total = await list_share_tokens(
        db, skip, limit, search=search, status_filter=status_filter
    )
    return AdminShareTokenListResponse(
        tokens=[AdminShareTokenResponse(**token) for token in tokens], total=total
    )


@router.delete("/share-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def admin_revoke_share_token(
    token_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke a basic share token and cascade to its embed tokens; no quota controls (admin only)."""
    result = await AdminService(db).revoke_share_token_with_cascade(token_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Share token not found")
    revoked_token_id, map_id, cascade_count = result
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="map.admin_share_revoke",
            resource_type="map_share_token",
            resource_id=revoked_token_id,
            details={
                "map_id": str(map_id),
                "cascade_embed_count": cascade_count,
            },
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
