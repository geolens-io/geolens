"""Sharing groups as someone choosing whom to share with sees them."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth import groups as group_service
from app.modules.auth.dependencies import get_current_active_user
from app.modules.auth.permissions import get_user_roles
from app.modules.auth.schemas import GroupRef, GroupRefListResponse
from app.platform.request_credential import is_publish_key
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

router = APIRouter(prefix="/groups", tags=["Groups"], responses=ERROR_RESPONSES_AUTH)


# Trailing slash is canonical (in OpenAPI); the no-slash form is a hidden alias.
@router.get("/mine", response_model=GroupRefListResponse, include_in_schema=False)
@router.get("/mine/", response_model=GroupRefListResponse)
async def list_my_groups(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> GroupRefListResponse:
    """List the sharing groups the caller may share with, by name.

    That is the groups the caller belongs to, or every group for an admin.
    """
    # A publish key acts only on its owner's own objects, so it isn't admin.
    is_admin = not is_publish_key(db) and "admin" in await get_user_roles(db, user)
    groups, total = await group_service.list_groups(
        db, skip=skip, limit=limit, member_id=None if is_admin else user.id
    )
    return GroupRefListResponse(
        groups=[GroupRef(id=group.id, name=group.name) for group in groups],
        total=total,
    )
