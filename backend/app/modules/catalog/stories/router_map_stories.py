"""The stories that use a map, for the map's delete confirmation."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.maps.service import check_map_ownership, get_map
from app.modules.catalog.stories.schemas import MapStoriesResponse, MapStoryReference
from app.modules.catalog.stories.service import stories_using_map
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(prefix="/maps", tags=["Maps"], responses=ERROR_RESPONSES_WRITE)


@router.get("/{map_id}/stories/", response_model=MapStoriesResponse)
async def list_map_stories_endpoint(
    map_id: uuid.UUID,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapStoriesResponse:
    """List the stories whose scenes use this map (owner or admin).

    Stories you can't read are only counted, in `hidden_count`. Deleting the
    map keeps each story's chapters and their text; a chapter whose scene
    used the map loses that scene. 404 when you can't read the map, 403 when
    you can but don't own it.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    roles = await check_map_ownership(map_obj, user, db)
    stories, hidden = await stories_using_map(db, map_id, user.id, "admin" in roles)
    return MapStoriesResponse(
        stories=[MapStoryReference(id=s.id, title=s.title) for s in stories],
        hidden_count=hidden,
    )
