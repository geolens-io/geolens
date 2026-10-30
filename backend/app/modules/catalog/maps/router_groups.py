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
    DatasetGroupNotJoinedError,
    LayersHiddenFromGroupsError,
    check_map_ownership,
    get_map,
    map_groups,
    record_map_groups_change,
    set_map_groups,
)
from app.platform.cache.tiles import invalidate_catalog_cache
from app.standards.ogc.errors import CONFLICT_RESPONSE, FORBIDDEN_RESPONSE

router = APIRouter()

_CONFLICT = {
    **CONFLICT_RESPONSE,
    "description": (
        "Layers some new groups can't read (`detail.code` "
        "`layers_hidden_from_groups`), or another change to the map holding "
        "its lock (no `detail.code`); branch on `detail.code`."
    ),
}


@router.put(
    "/{map_id}/groups", response_model=MapGroupsResponse, include_in_schema=False
)
@router.put(
    "/{map_id}/groups/",
    response_model=MapGroupsResponse,
    responses={403: FORBIDDEN_RESPONSE, 409: _CONFLICT},
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

    409 (`detail.code` `layers_hidden_from_groups`, the layers under
    `detail.layers`) when new groups can't read some layers; see `confirm`.
    A lock wait that times out also answers 409, without `detail.code`.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    roles = await check_map_ownership(map_obj, user, db)
    try:
        result = await set_map_groups(
            db,
            map_obj,
            body.group_ids,
            actor=user,
            is_admin="admin" in roles,
            confirm=body.confirm,
        )
    except LayersHiddenFromGroupsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "layers_hidden_from_groups",
                "message": str(exc),
                "layers": [gap.model_dump(mode="json") for gap in exc.layers],
            },
        )
    except UnknownGroupsError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "Group not found",
                "group_ids": [str(group_id) for group_id in exc.group_ids],
            },
        )
    except DatasetGroupNotJoinedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can share a dataset only with groups you belong to.",
        )
    except GroupNotJoinedError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can share a map only with groups you belong to.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        )
    visibility = map_obj.visibility
    for dataset_id, (group_ids, dataset_visibility) in result.shared_datasets.items():
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="metadata.edit",
                resource_type="dataset",
                resource_id=dataset_id,
                details={
                    "group_ids": [str(group_id) for group_id in group_ids],
                    "visibility": dataset_visibility,
                    "shared_with_map": str(map_id),
                },
                ip_address=get_client_ip(request),
            ),
        )
    if result.previous is not None:
        await record_map_groups_change(
            db,
            map_id,
            map_obj.name,
            previous=result.previous,
            group_ids=result.group_ids,
            actor=user,
            visibility=visibility,
            ip_address=get_client_ip(request),
        )
    groups = await map_groups(db, map_id)
    await db.commit()
    if result.shared_datasets:
        await invalidate_catalog_cache()
    return MapGroupsResponse(
        visibility=visibility,
        groups=groups,
        shared_dataset_ids=list(result.shared_datasets),
        hidden_layers=result.hidden_layers,
    )
