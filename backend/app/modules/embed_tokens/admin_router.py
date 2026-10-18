"""Admin endpoints for embed token management across all maps."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.core.tenancy import is_multi_tenant
from app.modules.auth.dependencies import require_permission
from app.core.dependencies import get_client_ip, get_db
from app.modules.embed_tokens.schemas import (
    AdminEmbedTokenListResponse,
    AdminEmbedTokenResponse,
    BulkRevokeRequest,
    BulkRevokeResponse,
    EmbedTokenResponse,
)
from app.modules.catalog.maps.service import lock_maps_for_admin_write
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import (
    bulk_revoke_embed_tokens,
    list_admin_embed_tokens,
)
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

router = APIRouter(
    prefix="/admin/embed-tokens",
    tags=["Admin Embed Tokens"],
    responses=ERROR_RESPONSES_AUTH,
)


# Trailing slash is canonical (in OpenAPI); the no-slash form is a hidden alias
# because api/main.py sets redirect_slashes=False.
@router.get("", response_model=AdminEmbedTokenListResponse, include_in_schema=False)
@router.get("/", response_model=AdminEmbedTokenListResponse)
async def list_all_embed_tokens(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    map_id: uuid.UUID | None = Query(None),
    map_search: str | None = Query(None),
    creator: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    user: Identity = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> AdminEmbedTokenListResponse:
    """List basic embed-token inventory across maps; no quota or domain-policy controls (admin only)."""
    # Pass the request-scoped tenant so a tenant-A admin cannot enumerate
    # tenant-B tokens. Inert (None) in single_tenant.
    from app.core.db.tenant_session import current_tenant_var

    request_tenant = current_tenant_var.get()
    filter_tenant_id = (
        uuid.UUID(request_tenant) if is_multi_tenant() and request_tenant else None
    )
    rows, total = await list_admin_embed_tokens(
        db,
        skip,
        limit,
        map_search,
        creator,
        status_filter,
        map_id=map_id,
        tenant_id=filter_tenant_id,
    )

    tokens = [
        AdminEmbedTokenResponse(
            **EmbedTokenResponse.model_validate(
                token, from_attributes=True
            ).model_dump(),
            map_name=map_name,
            creator_username=creator_username,
        )
        for token, map_name, creator_username in rows
    ]

    return AdminEmbedTokenListResponse(tokens=tokens, total=total)


@router.post("/bulk-revoke", response_model=BulkRevokeResponse, include_in_schema=False)
@router.post("/bulk-revoke/", response_model=BulkRevokeResponse)
async def bulk_revoke(
    body: BulkRevokeRequest,
    request: Request,
    user: Identity = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> BulkRevokeResponse:
    """Bulk-revoke basic embed tokens; no quota or domain-policy controls (admin only)."""
    # Scope by tenant so a tenant-A admin cannot revoke tenant-B tokens by
    # UUID (mirrors the list filter above).
    from app.core.db.tenant_session import current_tenant_var

    request_tenant = current_tenant_var.get()
    filter_tenant_id = (
        uuid.UUID(request_tenant) if is_multi_tenant() and request_tenant else None
    )
    # Lock the maps' rows (which re-checks the admin) before any token or
    # cache-denial write.
    maps = select(EmbedToken.map_id).where(
        EmbedToken.id.in_(body.token_ids), EmbedToken.is_active.is_(True)
    )
    if filter_tenant_id is not None:
        maps = maps.where(EmbedToken.tenant_id == filter_tenant_id)
    await lock_maps_for_admin_write(db, (await db.scalars(maps)).all(), user)
    count = await bulk_revoke_embed_tokens(
        db, body.token_ids, tenant_id=filter_tenant_id
    )

    ip = get_client_ip(request)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="embed_token.bulk_revoke",
            resource_type="embed_token",
            resource_id=None,
            details={
                "revoked_count": count,
                "token_ids": [str(tid) for tid in body.token_ids],
            },
            ip_address=ip,
        ),
    )
    await db.commit()

    return BulkRevokeResponse(revoked_count=count)
