"""Embed token CRUD endpoints for map-scoped tile access.

# What embed tokens are
# ---------------------
# An embed token grants tile-level access to a single shared map without
# requiring the viewer to log in. The token is signed (not just opaque) so
# revocation is enforced via DB lookup at request time. Each token can be
# scoped to:
#   - A specific map only
#   - A whitelist of allowed Origin headers (domain locking)
#   - A view count or expiry date
#
# # Why a separate router from share tokens
# Share tokens (catalog/maps/share_tokens) grant access to the *map metadata*
# (rendering the viewer page itself), while embed tokens grant access to the
# *tiles and features* used by the embedded iframe. They have different
# revocation semantics and audit categories, so they live in separate routers.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import log_action
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user
from app.core.dependencies import get_db
from app.modules.embed_tokens.schemas import (
    EmbedTokenCreate,
    EmbedTokenCreatedResponse,
    EmbedTokenListResponse,
    EmbedTokenResponse,
    EmbedTokenUpdate,
)
from app.modules.embed_tokens.service import (
    create_embed_token,
    list_embed_tokens,
    revoke_embed_token,
    update_embed_token,
)
from app.modules.catalog.maps.service import check_map_ownership, get_map
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/maps/{map_id}/embed-tokens",
    tags=["Embed Tokens"],
    responses=ERROR_RESPONSES_WRITE,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/", response_model=EmbedTokenCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def create_embed_token_endpoint(
    map_id: uuid.UUID,
    body: EmbedTokenCreate,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> EmbedTokenCreatedResponse:
    """Create an embed token scoped to a map's current layers.

    Expiration and allowed-origin restrictions are enterprise controls (enterprise only).
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    try:
        token, raw_token = await create_embed_token(
            db,
            map_id,
            user.id,
            expires_in_days=body.expires_in_days,
            name=body.name,
            allowed_origins=body.allowed_origins,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    await log_action(
        db,
        user_id=user.id,
        action="embed_token.create",
        resource_type="embed_token",
        resource_id=token.id,
        details={"map_id": str(map_id)},
    )
    await db.commit()
    await db.refresh(token)

    token_data = EmbedTokenResponse.model_validate(token).model_dump()
    token_data["raw_token"] = raw_token
    return EmbedTokenCreatedResponse.model_validate(token_data)


@router.get("/", response_model=EmbedTokenListResponse)
async def list_embed_tokens_endpoint(
    map_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> EmbedTokenListResponse:
    """List all embed tokens for a map."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    tokens = await list_embed_tokens(db, map_id)
    return EmbedTokenListResponse(
        tokens=[EmbedTokenResponse.model_validate(t) for t in tokens],
        total=len(tokens),
    )


@router.patch("/{token_id}/", response_model=EmbedTokenResponse)
async def update_embed_token_endpoint(
    map_id: uuid.UUID,
    token_id: uuid.UUID,
    body: EmbedTokenUpdate,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> EmbedTokenResponse:
    """Update embed token allowed_origins (enterprise only)."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    token = await update_embed_token(db, token_id, map_id, body.allowed_origins)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embed token not found",
        )

    await log_action(
        db,
        user_id=user.id,
        action="embed_token.update",
        resource_type="embed_token",
        resource_id=token_id,
        details={"map_id": str(map_id), "allowed_origins": body.allowed_origins},
    )
    await db.commit()
    await db.refresh(token)

    return EmbedTokenResponse.model_validate(token)


@router.delete("/{token_id}/", response_model=EmbedTokenResponse)
async def revoke_embed_token_endpoint(
    map_id: uuid.UUID,
    token_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> EmbedTokenResponse:
    """Revoke an embed token."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    token = await revoke_embed_token(db, token_id, map_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embed token not found",
        )

    await log_action(
        db,
        user_id=user.id,
        action="embed_token.revoke",
        resource_type="embed_token",
        resource_id=token_id,
        details={"map_id": str(map_id)},
    )
    await db.commit()

    return EmbedTokenResponse.model_validate(token)
