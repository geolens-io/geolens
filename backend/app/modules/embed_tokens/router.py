"""Embed token CRUD endpoints for map-scoped data access.

An embed token lets viewers of one shared map, without login, read the
tiles, features and terrain of its layers, and adds those layers to the
shared-map view. It reaches only datasets its creator can still read, and
it is DB-backed so revocation is enforced at request time. Scopes: a
specific map, an Origin allowlist (domain locking), and an expiry.

Kept separate from share tokens (catalog/maps/share_tokens), which grant
access to map metadata/viewer rendering rather than tiles/features, and
carry different revocation semantics and audit categories.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.core.dependencies import get_db
from app.modules.catalog.authorization import (
    ANONYMOUS_MAP_VISIBILITIES,
    RESTRICTED_MAP_VISIBILITY,
    check_public_visibility_allowed,
)
from app.modules.embed_tokens.schemas import (
    EmbedTokenCreate,
    EmbedTokenCreatedResponse,
    EmbedTokenListResponse,
    EmbedTokenResponse,
    EmbedTokenUpdate,
)
from app.modules.embed_tokens.service import (
    DomainLockNotEnforceableError,
    EmbedScopeNotVisibleError,
    assert_domain_lock_is_enforceable,
    create_embed_token,
    get_active_embed_token,
    list_embed_tokens,
    revoke_embed_token,
    update_embed_token,
)
from app.modules.catalog.maps.service import (
    check_map_ownership,
    get_map,
    lock_map_layers,
)
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/maps/{map_id}/embed-tokens",
    tags=["Embed Tokens"],
    responses=ERROR_RESPONSES_WRITE,
)

RESTRICTED_MAP_EMBED_REFUSED = (
    "A map shared with groups can't have an embed token. Remove its groups first."
)


async def _refuse_embed_beyond_map_audience(
    db: AsyncSession, user: Identity, visibility: str
) -> None:
    """Refuse a token that would open a non-public map to anonymous holders
    when its audience forbids that. Call holding the map row lock.

    A restricted map is for its groups only, so it refuses every caller (409).
    On any other non-public map the token is the only anonymous way in, so it
    takes the same gate as making the map public (403 for a non-admin while
    public visibility is restricted), judged on the caller's roles as
    committed now.
    """
    if visibility == RESTRICTED_MAP_VISIBILITY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=RESTRICTED_MAP_EMBED_REFUSED
        )
    if visibility not in ANONYMOUS_MAP_VISIBILITIES:
        await check_public_visibility_allowed(db, user, "public")


# Trailing slash is canonical (in OpenAPI); the no-slash form is a hidden alias
# because api/main.py sets redirect_slashes=False.
@router.post(
    "",
    response_model=EmbedTokenCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/", response_model=EmbedTokenCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def create_embed_token_endpoint(
    request: Request,
    map_id: uuid.UUID,
    body: EmbedTokenCreate,
    # Same permission gate as share_map_endpoint: an embed token outranks the
    # share link it accompanies.
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> EmbedTokenCreatedResponse:
    """Create an embed token scoped to a map's current layers.

    The default 30-day unrestricted token is always available. Custom lifetimes
    and non-empty origin restrictions require advanced sharing controls.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    # Refuse a lock this deployment can't enforce at mint time rather than
    # failing silently later.
    try:
        await assert_domain_lock_is_enforceable(db, request, body.allowed_origins)
    except DomainLockNotEnforceableError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )

    # Before the scope read, so the token freezes the layers the map has now,
    # and before the revocation's cache denials, which no rollback undoes.
    await lock_map_layers(db, map_id)
    # Read under the lock that sharing with groups and visibility changes also
    # take, so a map going restricted can't gain a token after that revoked its
    # others.
    await db.refresh(map_obj, ["visibility"])
    await _refuse_embed_beyond_map_audience(db, user, map_obj.visibility)
    try:
        token, raw_token = await create_embed_token(
            db,
            map_id,
            user.id,
            expires_in_days=body.expires_in_days,
            name=body.name,
            allowed_origins=body.allowed_origins,
        )
    # The map's layers reach a dataset this caller can no longer see, so there
    # is no scope they may freeze into an anonymous tile capability. Same 403
    # shape as the maps router's sibling refusals, and distinct from the 400
    # licensing refusal below so a client can tell the two apart.
    except EmbedScopeNotVisibleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": (
                    "Cannot create an embed token: map contains datasets you "
                    "cannot access"
                ),
                # Deliberately empty (shape parity with siblings): naming
                # the datasets here would disclose ids the caller was never
                # told about.
                "datasets": [],
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="embed_token.create",
            resource_type="embed_token",
            resource_id=token.id,
            details={"map_id": str(map_id)},
        ),
    )
    await db.commit()
    await db.refresh(token)

    token_data = EmbedTokenResponse.model_validate(token).model_dump()
    token_data["raw_token"] = raw_token
    return EmbedTokenCreatedResponse.model_validate(token_data)


@router.get("", response_model=EmbedTokenListResponse, include_in_schema=False)
@router.get("/", response_model=EmbedTokenListResponse)
async def list_embed_tokens_endpoint(
    map_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
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
    request: Request,
    map_id: uuid.UUID,
    token_id: uuid.UUID,
    body: EmbedTokenUpdate,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> EmbedTokenResponse:
    """Update embed token allowed_origins.

    Null clears restrictions. Non-empty origin restrictions require advanced sharing controls.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    # Existence check comes before the deployment-level domain-lock
    # precondition, so a stale/revoked token id gets the real 404 rather than
    # advice to reconfigure PUBLIC_APP_URL.
    if await get_active_embed_token(db, token_id, map_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embed token not found",
        )

    # Same gate as the POST handler. Clearing a lock (allowed_origins=None) is
    # unaffected.
    try:
        await assert_domain_lock_is_enforceable(db, request, body.allowed_origins)
    except DomainLockNotEnforceableError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )

    # Before the cache eviction, which no rollback undoes.
    await lock_map_layers(db, map_id)
    try:
        token = await update_embed_token(db, token_id, map_id, body.allowed_origins)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embed token not found",
        )

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="embed_token.update",
            resource_type="embed_token",
            resource_id=token_id,
            details={"map_id": str(map_id), "allowed_origins": body.allowed_origins},
        ),
    )
    await db.commit()
    await db.refresh(token)

    return EmbedTokenResponse.model_validate(token)


@router.delete("/{token_id}/", response_model=EmbedTokenResponse)
async def revoke_embed_token_endpoint(
    map_id: uuid.UUID,
    token_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
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

    # Before the revocation's cache denial, which no rollback undoes.
    await lock_map_layers(db, map_id)
    token = await revoke_embed_token(db, token_id, map_id)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embed token not found",
        )

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="embed_token.revoke",
            resource_type="embed_token",
            resource_id=token_id,
            details={"map_id": str(map_id)},
        ),
    )
    await db.commit()

    return EmbedTokenResponse.model_validate(token)
