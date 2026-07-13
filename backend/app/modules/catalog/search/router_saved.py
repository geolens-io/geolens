"""Authenticated saved-search routes composed under ``/search/saved``."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user
from app.modules.catalog.search.saved import (
    create_saved_search,
    delete_saved_search,
    get_saved_search,
    list_saved_searches,
)
from app.modules.catalog.search.schemas import (
    SavedSearchCreate,
    SavedSearchListResponse,
    SavedSearchResponse,
)

router = APIRouter(prefix="/saved")


@router.post(
    "",
    response_model=SavedSearchResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/", response_model=SavedSearchResponse, status_code=status.HTTP_201_CREATED
)
async def create_saved_search_endpoint(
    body: SavedSearchCreate,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SavedSearchResponse:
    """Save a search query with a name for later reuse."""
    saved = await create_saved_search(db, user.id, body.name, body.params)
    await db.commit()
    await db.refresh(saved)
    return SavedSearchResponse.model_validate(saved)


@router.get("", response_model=SavedSearchListResponse, include_in_schema=False)
@router.get("/", response_model=SavedSearchListResponse)
async def list_saved_searches_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SavedSearchListResponse:
    """List saved searches for the authenticated user."""
    searches, total = await list_saved_searches(db, user.id, skip=skip, limit=limit)
    return SavedSearchListResponse(
        searches=[SavedSearchResponse.model_validate(search) for search in searches],
        total=total,
    )


@router.get("/{search_id}", response_model=SavedSearchResponse)
async def get_saved_search_endpoint(
    search_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SavedSearchResponse:
    """Get a single saved search by ID."""
    saved = await get_saved_search(db, search_id, user.id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved search not found")
    return SavedSearchResponse.model_validate(saved)


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search_endpoint(
    search_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a saved search."""
    if not await delete_saved_search(db, search_id, user.id):
        raise HTTPException(status_code=404, detail="Saved search not found")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
