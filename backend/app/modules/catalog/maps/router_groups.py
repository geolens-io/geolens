"""Sharing a saved map with sharing groups."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.group_sharing import GroupNotJoinedError, UnknownGroupsError
from app.modules.catalog.maps.schemas import MapGroupsResponse, MapGroupsUpdate
from app.modules.catalog.maps.service import (
    check_map_ownership,
    get_map,
    map_groups,
    record_map_history_event,
    set_map_groups,
)
from app.standards.ogc.errors import FORBIDDEN_RESPONSE

router = APIRouter()


@router.put(
    "/{map_id}/groups", response_model=MapGroupsResponse, include_in_schema=False
)
@router.put(
    "/{map_id}/groups/",
    response_model=MapGroupsResponse,
    responses={403: FORBIDDEN_RESPONSE},
)
async def set_map_groups_endpoint(
    map_id: uuid.UUID,
    body: MapGroupsUpdate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapGroupsResponse:
    """Share a map with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private map shared with a group becomes restricted and its members can
    read it; a restricted one left with no group becomes private. Internal
    and public maps keep their audience. Becoming restricted revokes the
    map's share link and embed tokens. 404 for an unknown group.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    roles = await check_map_ownership(map_obj, user, db)
    try:
        previous = await set_map_groups(
            db, map_obj, body.group_ids, actor=user, is_admin="admin" in roles
        )
    except UnknownGroupsError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Group not found",
                "group_ids": [str(group_id) for group_id in exc.group_ids],
            },
        )
    except GroupNotJoinedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can share a map only with groups you belong to.",
        )
    visibility = map_obj.visibility
    if previous is not None:
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="map.update",
                resource_type="map",
                resource_id=map_id,
                details={
                    "changed_fields": ["groups"],
                    "group_ids": sorted(str(group_id) for group_id in body.group_ids),
                    "visibility": visibility,
                },
                ip_address=get_client_ip(request),
            ),
        )
        if visibility != previous:
            await record_map_history_event(
                db,
                map_id=map_id,
                actor=user,
                target_type="map",
                target_id=map_id,
                target_name=map_obj.name,
                action="map.visibility_update",
                summary=f"Changed visibility to {visibility}",
                details={
                    "field": "visibility",
                    "previous": previous,
                    "current": visibility,
                },
            )
    groups = await map_groups(db, map_id)
    await db.commit()
    return MapGroupsResponse(visibility=visibility, groups=groups)
