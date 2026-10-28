"""Admin-only ownership transfer for saved maps."""

import uuid
from datetime import datetime

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
    _stored_images_readable,
)
from app.modules.catalog.maps.schemas import MapResponse
from app.modules.catalog.maps.service import (
    check_map_ownership,
    get_map,
    get_map_with_layers,
    lock_map_layers,
    with_visible_vrt_extents,
)
from app.modules.catalog.ownership import require_transfer_admin, transfer_map_owner
from app.modules.catalog.write_recheck import refuse_stale_write
from app.modules.catalog.maps.visibility_contract import map_visibility_contract
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/maps",
    tags=["Maps"],
    responses=ERROR_RESPONSES_WRITE,
    dependencies=[Depends(map_visibility_contract)],
)


class MapPatch(BaseModel):
    """Partial map update. PUT /maps/{map_id} edits the map's content."""

    model_config = ConfigDict(extra="forbid")

    owner_id: uuid.UUID = Field(
        description="Admin only: transfer the map to this active user."
    )
    expected_updated_at: datetime | None = Field(
        default=None,
        description=(
            "The map's `updated_at` the caller read. When set and the map has "
            "changed since, nothing is written and the answer is 409 with "
            "`detail.code` `stale_write`. Omit it to write unconditionally."
        ),
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
    owner_id = require_transfer_admin(await get_user_roles(db, user), body.owner_id)
    if body.expected_updated_at is not None:
        # FOR NO KEY UPDATE, which every UPDATE of the map row waits on, so no
        # edit lands between this comparison and the transfer.
        await lock_map_layers(db, map_id)
        await db.refresh(map_obj, ["updated_at"])
        refuse_stale_write(map_obj.updated_at, body.expected_updated_at)
    await transfer_map_owner(
        db,
        map_obj,
        owner_id,
        actor=user,
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    map_obj, layer_tuples, forked_name, owner_username = await get_map_with_layers(
        db, map_id
    )
    return _build_map_response(
        map_obj,
        _layers_from_tuples(await with_visible_vrt_extents(db, layer_tuples, user)),
        forked_from_name=forked_name,
        created_by_username=owner_username,
        include_notes=True,
        stored_images_readable=await _stored_images_readable(db, map_obj, user),
    )
