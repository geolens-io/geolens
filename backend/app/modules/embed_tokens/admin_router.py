"""Admin endpoints for embed token management across all maps."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import log_action
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.core.dependencies import get_client_ip, get_db
from app.modules.embed_tokens.schemas import (
    AdminEmbedTokenListResponse,
    AdminEmbedTokenResponse,
    BulkRevokeRequest,
    BulkRevokeResponse,
    EmbedTokenResponse,
)
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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
    """List all embed tokens across all maps with optional filters (admin only)."""
    rows, total = await list_admin_embed_tokens(
        db, skip, limit, map_search, creator, status_filter, map_id=map_id
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


@router.post("/bulk-revoke/", response_model=BulkRevokeResponse)
async def bulk_revoke(
    body: BulkRevokeRequest,
    request: Request,
    user: Identity = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> BulkRevokeResponse:
    """Bulk-revoke multiple embed tokens (admin only)."""
    count = await bulk_revoke_embed_tokens(db, body.token_ids)

    ip = get_client_ip(request)
    await log_action(
        db,
        user_id=user.id,
        action="embed_token.bulk_revoke",
        resource_type="embed_token",
        resource_id=None,
        details={
            "revoked_count": count,
            "token_ids": [str(tid) for tid in body.token_ids],
        },
        ip_address=ip,
    )
    await db.commit()

    return BulkRevokeResponse(revoked_count=count)
