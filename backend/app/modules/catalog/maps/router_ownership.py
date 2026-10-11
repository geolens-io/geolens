"""Admin-only ownership transfer for saved maps."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.core.permissions import EDIT_METADATA
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.maps._router_helpers import (
    _build_map_response,
    _layers_from_tuples,
)
from app.modules.catalog.maps.schemas import MapResponse
from app.modules.catalog.maps.service import (
    check_map_ownership,
    get_map,
    get_map_with_layers,
)
from app.modules.catalog.ownership import resolve_new_owner, transfer_map_owner
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(prefix="/maps", tags=["Maps"], responses=ERROR_RESPONSES_WRITE)


class MapPatch(BaseModel):
    """Partial map update. PUT /maps/{map_id} edits the map's content."""

    model_config = ConfigDict(extra="forbid")

    owner_id: uuid.UUID = Field(
        description="Admin only: transfer the map to this active user."
    )


@router.patch("/{map_id}", response_model=MapResponse)
async def patch_map_endpoint(
    map_id: uuid.UUID,
    body: MapPatch,
    request: Request,
    user: Identity = Depends(require_permission(EDIT_METADATA)),
    db: AsyncSession = Depends(get_db),
) -> MapResponse:
    """Transfer a map to another owner. Admin only."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)
    new_owner = await resolve_new_owner(
        db,
        body.owner_id,
        actor_roles=await get_user_roles(db, user),
        capability=EDIT_METADATA,
    )
    await transfer_map_owner(
        db,
        map_obj,
        new_owner,
        actor=user,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    map_obj, layer_tuples, forked_name, owner_username = await get_map_with_layers(
        db, map_id
    )
    return _build_map_response(
        map_obj,
        _layers_from_tuples(layer_tuples),
        forked_from_name=forked_name,
        created_by_username=owner_username,
    )
