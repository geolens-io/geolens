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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.core.dependencies import get_db
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


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
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
    # fix(#819): same permission gate as share_map_endpoint — an embed token outranks the
    # share link it accompanies (anonymous tile capability), so minting or
    # managing one must never be gated weaker than creating the share link.
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

    # fix(#1548 review P2): refuse a lock this deployment cannot enforce, at
    # the moment the operator sets it, rather than silently on every later
    # viewer request. Shared with the PATCH handler so the two cannot drift.
    try:
        await assert_domain_lock_is_enforceable(db, request, body.allowed_origins)
    except DomainLockNotEnforceableError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )

    try:
        token, raw_token = await create_embed_token(
            db,
            map_id,
            user.id,
            expires_in_days=body.expires_in_days,
            name=body.name,
            allowed_origins=body.allowed_origins,
        )
    # fix(#1860): the map's layers reach a dataset this caller can no longer
    # see, so there is no scope they may freeze into an anonymous tile
    # capability. Same 403 and same shape as the maps router's sibling refusals
    # for a map holding datasets the caller cannot use for the operation
    # ("Cannot access one or more layer datasets"). The status also does the
    # separating work: the licensing refusal on this same handler is a 400, so
    # a client can tell "your deployment cannot do that" from "you cannot see
    # that data" without inspecting whether detail is a string or an object.
    except EmbedScopeNotVisibleError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": (
                    "Cannot create an embed token: map contains datasets you "
                    "cannot access"
                ),
                # Deliberately empty, and kept for shape parity with those
                # siblings. GET /maps/{id} drops layers whose dataset the
                # caller cannot see, so this caller has not been told those ids
                # and naming them here would make the refusal the disclosure.
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


# ROUTE-01 (Phase 1092): dual-shape decorator — see POST above.
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

    # fix(#1548 review r2): settle EXISTENCE before the deployment-level
    # precondition below. The gate answers "could this deployment enforce a
    # domain lock", which is not a question about this token at all — asked
    # first, it told the owner of a stale or concurrently revoked token id to
    # go and reconfigure PUBLIC_APP_URL, when the real answer is that their
    # token is gone. The write re-reads through the same helper, so a token
    # revoked in the window between still falls through to the 404 below.
    if await get_active_embed_token(db, token_id, map_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Embed token not found",
        )

    # fix(#1548 review P2): same gate as the POST handler. Clearing a lock
    # (allowed_origins=None) is unaffected.
    try:
        await assert_domain_lock_is_enforceable(db, request, body.allowed_origins)
    except DomainLockNotEnforceableError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )

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
