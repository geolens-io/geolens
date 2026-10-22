"""Admin routes for sharing groups and their members."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.modules.admin.schemas import (
    GroupListResponse,
    GroupMemberListResponse,
    GroupMembersAdd,
    GroupResponse,
    GroupWrite,
    UserNameItem,
)
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth import groups as group_service
from app.modules.auth.dependencies import require_mode_permission
from app.modules.auth.models import Group
from app.platform.ratelimit import limiter
from app.standards.ogc.errors import CONFLICT_RESPONSE, NOT_FOUND_RESPONSE

router = APIRouter()

# Keeps one audit row bounded however large the deleted group was.
AUDIT_MEMBER_ID_CAP = 1000

# Groups carry no tenant stamp, so in hosted mode only a fleet admin may see
# or change them.
require_group_admin = require_mode_permission(
    single_tenant="manage_users", multi_tenant="manage_tenants"
)


def _group_response(group: Group, member_count: int) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        member_count=member_count,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _not_found(exc: LookupError) -> HTTPException:
    if isinstance(exc, group_service.UnknownUsersError):
        detail: object = {
            "message": "User not found",
            "user_ids": [str(user_id) for user_id in exc.user_ids],
        }
    elif isinstance(exc, group_service.GroupMemberNotFoundError):
        detail = "User is not a member of this group"
    else:
        detail = "Group not found"
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _name_taken(name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"A group named '{name}' already exists",
    )


# Trailing slash is canonical (in OpenAPI); the no-slash form is a hidden alias.
@router.get(
    "/groups",
    response_model=GroupListResponse,
    dependencies=[Depends(require_group_admin)],
    include_in_schema=False,
)
@router.get(
    "/groups/",
    response_model=GroupListResponse,
    dependencies=[Depends(require_group_admin)],
)
async def list_groups(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> GroupListResponse:
    """List sharing groups by name, with member counts (admin only)."""
    groups, total = await group_service.list_groups(db, skip=skip, limit=limit)
    counts = await group_service.member_counts(db, [group.id for group in groups])
    return GroupListResponse(
        groups=[_group_response(group, counts[group.id]) for group in groups],
        total=total,
    )


@router.post(
    "/groups",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/groups/",
    response_model=GroupResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: CONFLICT_RESPONSE},
)
@limiter.limit("30/minute")
async def create_group(
    body: GroupWrite,
    request: Request,
    current_user: Identity = Depends(require_group_admin),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    """Create an empty sharing group (admin only). A duplicate name is 409."""
    try:
        group = await group_service.create_group(db, body.name)
        await audit_emit(
            db,
            AuditEvent(
                user_id=current_user.id,
                action="group.create",
                resource_type="group",
                resource_id=group.id,
                details={"name": group.name},
                ip_address=get_client_ip(request),
            ),
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _name_taken(body.name)
    return _group_response(group, 0)


@router.get(
    "/groups/{group_id}",
    response_model=GroupResponse,
    dependencies=[Depends(require_group_admin)],
    responses={404: NOT_FOUND_RESPONSE},
)
async def get_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    """Get one sharing group with its member count (admin only)."""
    try:
        group = await group_service.get_group(db, group_id)
    except LookupError as exc:
        raise _not_found(exc)
    counts = await group_service.member_counts(db, [group_id])
    return _group_response(group, counts[group_id])


@router.patch(
    "/groups/{group_id}",
    response_model=GroupResponse,
    responses={404: NOT_FOUND_RESPONSE, 409: CONFLICT_RESPONSE},
)
@limiter.limit("30/minute")
async def rename_group(
    group_id: uuid.UUID,
    body: GroupWrite,
    request: Request,
    current_user: Identity = Depends(require_group_admin),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    """Rename a sharing group (admin only). A name already in use is 409."""
    try:
        group, previous = await group_service.rename_group(db, group_id, body.name)
        if previous != group.name:
            await audit_emit(
                db,
                AuditEvent(
                    user_id=current_user.id,
                    action="group.rename",
                    resource_type="group",
                    resource_id=group_id,
                    details={"before": previous, "after": group.name},
                    ip_address=get_client_ip(request),
                ),
            )
        counts = await group_service.member_counts(db, [group_id])
        await db.commit()
    except LookupError as exc:
        raise _not_found(exc)
    except IntegrityError:
        await db.rollback()
        raise _name_taken(body.name)
    return _group_response(group, counts[group_id])


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: NOT_FOUND_RESPONSE},
)
@limiter.limit("30/minute")
async def delete_group(
    group_id: uuid.UUID,
    request: Request,
    current_user: Identity = Depends(require_group_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a sharing group and all its memberships (admin only)."""
    try:
        name, member_ids = await group_service.delete_group(db, group_id)
    except LookupError as exc:
        raise _not_found(exc)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="group.delete",
            resource_type="group",
            resource_id=group_id,
            details={
                "name": name,
                "member_count": len(member_ids),
                "member_ids": [
                    str(user_id) for user_id in member_ids[:AUDIT_MEMBER_ID_CAP]
                ],
                "member_ids_truncated": len(member_ids) > AUDIT_MEMBER_ID_CAP,
            },
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/groups/{group_id}/members",
    response_model=GroupMemberListResponse,
    dependencies=[Depends(require_group_admin)],
    include_in_schema=False,
)
@router.get(
    "/groups/{group_id}/members/",
    response_model=GroupMemberListResponse,
    dependencies=[Depends(require_group_admin)],
    responses={404: NOT_FOUND_RESPONSE},
)
async def list_group_members(
    group_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> GroupMemberListResponse:
    """List a sharing group's members by username (admin only)."""
    try:
        members, total = await group_service.list_members(
            db, group_id, skip=skip, limit=limit
        )
    except LookupError as exc:
        raise _not_found(exc)
    return GroupMemberListResponse(
        members=[
            UserNameItem(id=user_id, username=username) for user_id, username in members
        ],
        total=total,
    )


@router.post(
    "/groups/{group_id}/members",
    response_model=GroupResponse,
    include_in_schema=False,
)
@router.post(
    "/groups/{group_id}/members/",
    response_model=GroupResponse,
    responses={404: NOT_FOUND_RESPONSE},
)
@limiter.limit("30/minute")
async def add_group_members(
    group_id: uuid.UUID,
    body: GroupMembersAdd,
    request: Request,
    current_user: Identity = Depends(require_group_admin),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    """Add users to a sharing group (admin only).

    Users already in the group are skipped. If any id matches no user, the
    request is 404 and nobody is added.
    """
    try:
        group, added = await group_service.add_members(db, group_id, body.user_ids)
    except LookupError as exc:
        raise _not_found(exc)
    if added:
        await audit_emit(
            db,
            AuditEvent(
                user_id=current_user.id,
                action="group.add_members",
                resource_type="group",
                resource_id=group_id,
                details={"user_ids": [str(user_id) for user_id in added]},
                ip_address=get_client_ip(request),
            ),
        )
    counts = await group_service.member_counts(db, [group_id])
    await db.commit()
    return _group_response(group, counts[group_id])


@router.delete(
    "/groups/{group_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: NOT_FOUND_RESPONSE},
)
@limiter.limit("30/minute")
async def remove_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    current_user: Identity = Depends(require_group_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove one user from a sharing group (admin only)."""
    try:
        await group_service.remove_member(db, group_id, user_id)
    except LookupError as exc:
        raise _not_found(exc)
    await audit_emit(
        db,
        AuditEvent(
            user_id=current_user.id,
            action="group.remove_member",
            resource_type="group",
            resource_id=group_id,
            details={"user_id": str(user_id)},
            ip_address=get_client_ip(request),
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
