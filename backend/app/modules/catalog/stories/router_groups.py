"""Sharing a story with sharing groups."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_client_ip, get_db
from app.core.identity import Identity
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.group_sharing import GroupNotJoinedError, UnknownGroupsError
from app.modules.catalog.stories.groups import (
    audit_shared_maps,
    lock_story_groups,
    set_story_groups,
    story_groups,
)
from app.modules.catalog.stories.schemas import (
    StoryGroupsResponse,
    StoryGroupsUpdate,
)
from app.modules.catalog.stories.service import (
    STORY_NOT_FOUND,
    StoryReachError,
    check_story_ownership,
    get_story,
    lock_story,
    reach_conflict,
)
from app.standards.ogc.errors import (
    CONFLICT_RESPONSE,
    ERROR_RESPONSES_WRITE,
    FORBIDDEN_RESPONSE,
)

router = APIRouter(prefix="/stories", tags=["Stories"], responses=ERROR_RESPONSES_WRITE)

_CONFLICT = {
    **CONFLICT_RESPONSE,
    "description": (
        "Maps the published story uses that some new groups can't read "
        "(`detail.code` `maps_narrower_than_story`, the maps under "
        "`detail.maps`), or another change holding the story's lock (no "
        "`detail.code`)."
    ),
}


@router.put(
    "/{story_id}/groups", response_model=StoryGroupsResponse, include_in_schema=False
)
@router.put(
    "/{story_id}/groups/",
    response_model=StoryGroupsResponse,
    responses={403: FORBIDDEN_RESPONSE, 409: _CONFLICT},
)
async def set_story_groups_endpoint(
    story_id: uuid.UUID,
    body: StoryGroupsUpdate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> StoryGroupsResponse:
    """Share a story with exactly these sharing groups (owner or admin).

    An owner may add only groups they belong to (403); an admin may add any.
    A private story shared with a group becomes restricted, and once
    published its members can read it; a restricted one left with no group
    becomes private. Internal and public stories keep their audience. 404 for
    an unknown group.

    409 `maps_narrower_than_story` when the published story uses maps some
    member of a new group can't read: `detail.maps` names the ones you can
    read, each with `can_share`, and `detail.unreadable_maps` counts the
    rest; see `confirm`.
    """
    story = await get_story(db, story_id)
    if story is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=STORY_NOT_FOUND
        )
    await check_story_ownership(db, story, user)
    try:
        await lock_story_groups(db, story, body.group_ids)
    except UnknownGroupsError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Group not found",
                "group_ids": [str(group_id) for group_id in exc.group_ids],
            },
        )
    story, roles = await lock_story(db, story_id, user)
    try:
        result = await set_story_groups(
            db, story, body.group_ids, actor=user, roles=roles, confirm=body.confirm
        )
    except StoryReachError as exc:
        raise reach_conflict(exc) from exc
    except GroupNotJoinedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can share a story only with groups you belong to.",
        )
    await audit_shared_maps(
        db, result.shared_maps, user, get_client_ip(request), story_id
    )
    if result.previous is not None:
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="story.update",
                resource_type="story",
                resource_id=story_id,
                details={
                    "changed_fields": ["groups"],
                    "group_ids": sorted(str(group_id) for group_id in body.group_ids),
                    "visibility": story.visibility,
                },
                ip_address=get_client_ip(request),
            ),
        )
    # Read before the commit expires the row.
    visibility = story.visibility
    groups = await story_groups(db, story_id)
    await db.commit()
    return StoryGroupsResponse(
        visibility=visibility,
        groups=groups,
        shared_map_ids=[map_.id for map_ in result.shared_maps],
    )
