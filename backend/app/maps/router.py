"""Maps API endpoints: CRUD, duplication, and layer management."""

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from geoalchemy2.shape import to_shape

from app.audit.service import log_action
from app.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
    require_permission,
)
from app.auth.models import User
from app.auth.visibility import get_user_roles
from app.datasets.models import Dataset, Record
from app.dependencies import get_db
from app.maps.schemas import (
    DuplicateMapResponse,
    MapCreate,
    MapLayerInput,
    MapLayerResponse,
    MapListResponse,
    MapResponse,
    MapSummaryResponse,
    MapUpdate,
    MapVisibility,
    ShareTokenRequest,
    SharedMapResponse,
    ShareTokenResponse,
)
from app.maps.service import (
    add_layer,
    check_map_ownership,
    create_map,
    create_share_token,
    delete_map,
    get_active_share_token,
    duplicate_map,
    get_map,
    get_map_with_layers,
    get_shared_map,
    list_maps,
    remove_layer,
    resolve_forked_from_name,
    revoke_share_token_by_map,
    update_map,
    update_share_token,
    validate_public_visibility,
)

router = APIRouter(prefix="/maps", tags=["Maps"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extent_to_bbox(extent) -> list[float] | None:
    """Convert a GeoAlchemy2 geometry extent to a [minx, miny, maxx, maxy] bbox."""
    if extent is None:
        return None
    try:
        shape = to_shape(extent)
        return list(shape.bounds)
    except Exception:
        return None


def _build_layer_response(
    layer,
    dataset_name: str,
    geometry_type: str | None,
    table_name: str = "",
    extent=None,
    column_info=None,
    feature_count: int | None = None,
    sample_values: dict | None = None,
    record_type: str | None = None,
) -> MapLayerResponse:
    """Build a MapLayerResponse from a layer tuple."""
    return MapLayerResponse(
        id=layer.id,
        dataset_id=layer.dataset_id,
        dataset_name=dataset_name,
        dataset_geometry_type=geometry_type,
        dataset_table_name=table_name,
        dataset_extent_bbox=_extent_to_bbox(extent),
        dataset_column_info=column_info,
        dataset_feature_count=feature_count,
        dataset_sample_values=sample_values,
        display_name=layer.display_name,
        sort_order=layer.sort_order,
        visible=layer.visible,
        opacity=layer.opacity,
        paint=layer.paint,
        layout=layer.layout,
        layer_type=getattr(layer, "layer_type", "vector_geolens") or "vector_geolens",
        dataset_record_type=record_type,
        filter=layer.filter,
        label_config=layer.label_config,
        style_config=layer.style_config,
    )


def _build_map_response(
    map_obj,
    layers: list[MapLayerResponse],
    forked_from_name: str | None = None,
    created_by_username: str | None = None,
) -> MapResponse:
    """Build a MapResponse from a map object and layer list."""
    return MapResponse(
        id=map_obj.id,
        name=map_obj.name,
        description=map_obj.description,
        center_lng=map_obj.center_lng,
        center_lat=map_obj.center_lat,
        zoom=map_obj.zoom,
        bearing=map_obj.bearing,
        pitch=map_obj.pitch,
        basemap_style=map_obj.basemap_style,
        visibility=map_obj.visibility,
        thumbnail=map_obj.thumbnail,
        forked_from_id=map_obj.forked_from,
        forked_from_name=forked_from_name,
        created_by=map_obj.created_by,
        created_by_username=created_by_username,
        created_at=map_obj.created_at,
        updated_at=map_obj.updated_at,
        layers=layers,
        layer_count=len(layers),
    )


async def _resolve_owner_username(db: AsyncSession, created_by) -> str | None:
    """Resolve username from a user UUID."""
    if not created_by:
        return None
    row = await db.execute(select(User.username).where(User.id == created_by))
    return row.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=MapResponse, status_code=status.HTTP_201_CREATED)
async def create_map_endpoint(
    body: MapCreate,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapResponse:
    """Create a new map."""
    map_obj = await create_map(db, body.name, body.description, user.id)
    await log_action(
        db,
        user_id=user.id,
        action="map.create",
        resource_type="map",
        resource_id=map_obj.id,
        details={"name": body.name},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    await db.refresh(map_obj)
    return _build_map_response(map_obj, [], created_by_username=user.username)


@router.get("/", response_model=MapListResponse)
async def list_maps_endpoint(
    skip: int = 0,
    limit: int = 20,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    visibility: str | None = None,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MapListResponse:
    """List maps. Admins see all; others see own private + all internal/public.

    Supports search (ILIKE on name+description), sort_by (name/created_at/updated_at),
    sort_dir (asc/desc), and visibility filter (private/internal/public).
    """
    user_roles = await get_user_roles(db, user)
    maps, total = await list_maps(
        db,
        skip=skip,
        limit=limit,
        user_id=user.id,
        user_roles=user_roles,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        visibility=visibility,
    )

    summaries = [MapSummaryResponse(**m) for m in maps]
    return MapListResponse(maps=summaries, total=total)


@router.get("/shared/{token}", response_model=SharedMapResponse)
async def get_shared_map_endpoint(
    token: str,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> SharedMapResponse:
    """Get a shared map by token. Optionally authenticated for non-public layers."""
    user_roles: set[str] = set()
    if user is not None:
        user_roles = await get_user_roles(db, user)
    result = await get_shared_map(db, token, user=user, user_roles=user_roles)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared map not found",
        )
    if result == "expired":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This shared map link has expired or been revoked",
        )
    map_data, layers = result
    return SharedMapResponse(**map_data, layers=layers)


@router.get("/{map_id}/visibility-check")
async def visibility_check_endpoint(
    map_id: uuid.UUID,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Check if a map has non-public datasets. Informational only."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    non_public_names = await validate_public_visibility(db, map_id)
    return {
        "non_public_datasets": non_public_names,
        "has_non_public": len(non_public_names) > 0,
    }


@router.get("/{map_id}", response_model=MapResponse)
async def get_map_endpoint(
    map_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MapResponse:
    """Get a single map with its layers."""
    map_obj, layer_tuples = await get_map_with_layers(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    layers = [
        _build_layer_response(
            layer,
            name,
            gt,
            tn,
            ext,
            col_info,
            feat_count,
            samples,
            rec_type,
        )
        for layer, name, gt, tn, ext, col_info, feat_count, samples, rec_type in layer_tuples
    ]
    forked_name = await resolve_forked_from_name(db, map_obj.forked_from)
    owner_username = await _resolve_owner_username(db, map_obj.created_by)
    return _build_map_response(
        map_obj,
        layers,
        forked_from_name=forked_name,
        created_by_username=owner_username,
    )


@router.put("/{map_id}", response_model=MapResponse)
async def update_map_endpoint(
    map_id: uuid.UUID,
    body: MapUpdate,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapResponse:
    """Update a map's metadata and/or replace its layers."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    # Hard block: prevent publishing maps with non-public datasets
    if body.visibility and body.visibility == MapVisibility.public:
        non_public = await validate_public_visibility(db, map_id)
        if non_public:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot set visibility to public: datasets are not public: {', '.join(non_public)}",
            )

    # Build update kwargs from non-None fields
    kwargs = body.model_dump(exclude_none=True)
    if "layers" in kwargs:
        kwargs["layers"] = [layer.model_dump() for layer in body.layers]

    await update_map(db, map_id, **kwargs)

    await log_action(
        db,
        user_id=user.id,
        action="map.update",
        resource_type="map",
        resource_id=map_id,
        details={"changed_fields": list(body.model_dump(exclude_none=True).keys())},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    # Re-fetch with layers for full response
    map_obj, layer_tuples = await get_map_with_layers(db, map_id)
    layers = [
        _build_layer_response(
            layer,
            name,
            gt,
            tn,
            ext,
            col_info,
            feat_count,
            samples,
            rec_type,
        )
        for layer, name, gt, tn, ext, col_info, feat_count, samples, rec_type in layer_tuples
    ]
    forked_name = await resolve_forked_from_name(db, map_obj.forked_from)
    owner_username = await _resolve_owner_username(db, map_obj.created_by)
    return _build_map_response(
        map_obj,
        layers,
        forked_from_name=forked_name,
        created_by_username=owner_username,
    )


@router.delete("/{map_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_map_endpoint(
    map_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a map. Only the owner or an admin can delete."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    map_name = await delete_map(db, map_id)
    await log_action(
        db,
        user_id=user.id,
        action="map.delete",
        resource_type="map",
        resource_id=map_id,
        details={"name": map_name},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{map_id}/duplicate",
    response_model=DuplicateMapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_map_endpoint(
    map_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DuplicateMapResponse:
    """Fork a map with RBAC-filtered layers. Any authenticated user can fork."""
    try:
        new_map, excluded_count = await duplicate_map(db, map_id, user)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    await log_action(
        db,
        user_id=user.id,
        action="map.duplicate",
        resource_type="map",
        resource_id=new_map.id,
        details={
            "source_map_id": str(map_id),
            "new_name": new_map.name,
            "excluded_layers": excluded_count,
        },
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    # Re-fetch with layers for full response
    map_obj, layer_tuples = await get_map_with_layers(db, new_map.id)
    layers = [
        _build_layer_response(
            layer,
            name,
            gt,
            tn,
            ext,
            col_info,
            feat_count,
            samples,
            rec_type,
        )
        for layer, name, gt, tn, ext, col_info, feat_count, samples, rec_type in layer_tuples
    ]
    forked_name = await resolve_forked_from_name(db, map_obj.forked_from)
    owner_username = await _resolve_owner_username(db, map_obj.created_by)
    base_resp = _build_map_response(
        map_obj,
        layers,
        forked_from_name=forked_name,
        created_by_username=owner_username,
    )
    return DuplicateMapResponse(
        **base_resp.model_dump(),
        excluded_layer_count=excluded_count,
    )


@router.get("/{map_id}/share", response_model=ShareTokenResponse | None)
async def get_map_share_token_endpoint(
    map_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ShareTokenResponse | None:
    token_obj = await get_active_share_token(db, map_id)
    if token_obj is None:
        return None
    return ShareTokenResponse(
        token=token_obj.token,
        share_url=f"/m/{token_obj.token}",
        expires_at=token_obj.expires_at,
        is_active=token_obj.is_active,
    )


@router.post("/{map_id}/share", response_model=ShareTokenResponse)
async def share_map_endpoint(
    map_id: uuid.UUID,
    request: Request,
    body: ShareTokenRequest | None = Body(default=None),
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ShareTokenResponse:
    """Create or retrieve a share token for a public map."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)
    if map_obj.visibility != "public":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Map must be public before sharing",
        )
    token_obj = await create_share_token(
        db, map_id, user.id, expires_at=body.expires_at if body else None
    )
    await log_action(
        db,
        user_id=user.id,
        action="map.share",
        resource_type="map",
        resource_id=map_id,
        details={"token": token_obj.token},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return ShareTokenResponse(
        token=token_obj.token,
        share_url=f"/m/{token_obj.token}",
        expires_at=token_obj.expires_at,
        is_active=token_obj.is_active,
    )


@router.patch("/{map_id}/share", response_model=ShareTokenResponse)
async def update_map_share_token_endpoint(
    map_id: uuid.UUID,
    body: ShareTokenRequest,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> ShareTokenResponse:
    """Update expiration on an existing share token. Owner or admin only."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)
    token_obj = await update_share_token(db, map_id, body.expires_at)
    if token_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active share token found",
        )
    await log_action(
        db,
        user_id=user.id,
        action="map.update_share_token",
        resource_type="map",
        resource_id=map_id,
        details={"expires_at": str(body.expires_at)},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return ShareTokenResponse(
        token=token_obj.token,
        share_url=f"/m/{token_obj.token}",
        expires_at=token_obj.expires_at,
        is_active=token_obj.is_active,
    )


@router.delete("/{map_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_map_share_endpoint(
    map_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Revoke share token(s) for a map. Owner or admin only."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)
    revoked = await revoke_share_token_by_map(db, map_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active share token found",
        )
    await log_action(
        db,
        user_id=user.id,
        action="map.revoke_share",
        resource_type="map",
        resource_id=map_id,
        details={},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{map_id}/thumbnail", status_code=status.HTTP_204_NO_CONTENT)
async def upload_thumbnail(
    map_id: uuid.UUID,
    data_uri: str = Body(..., media_type="text/plain"),
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Upload a base64 thumbnail for a map."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    if not data_uri.startswith("data:image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body must be a data:image/ URI",
        )
    if len(data_uri) > 100_000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Thumbnail too large (max 100KB)",
        )

    map_obj.thumbnail = data_uri
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{map_id}/layers/",
    response_model=MapLayerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_layer_endpoint(
    map_id: uuid.UUID,
    body: MapLayerInput,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapLayerResponse:
    """Add a layer to a map."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    layer = await add_layer(
        db,
        map_id,
        body.dataset_id,
        body.sort_order,
        body.visible,
        body.opacity,
        body.paint,
        body.layout,
        body.layer_type,
    )

    await log_action(
        db,
        user_id=user.id,
        action="map.add_layer",
        resource_type="map",
        resource_id=map_id,
        details={"dataset_id": str(body.dataset_id)},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    # Get dataset fields for the response
    ds_result = await db.execute(
        select(
            Record.title,
            Dataset.geometry_type,
            Dataset.table_name,
            Record.spatial_extent,
            Dataset.column_info,
            Dataset.feature_count,
            Dataset.sample_values,
            Record.record_type,
        )
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == body.dataset_id)
    )
    ds_row = ds_result.one_or_none()
    dataset_name = ds_row[0] if ds_row else "Unknown"
    geometry_type = ds_row[1] if ds_row else None
    table_name = ds_row[2] if ds_row else ""
    extent = ds_row[3] if ds_row else None
    col_info = ds_row[4] if ds_row else None
    feat_count = ds_row[5] if ds_row else None
    samples = ds_row[6] if ds_row else None
    rec_type = ds_row[7] if ds_row else None

    return _build_layer_response(
        layer,
        dataset_name,
        geometry_type,
        table_name,
        extent,
        col_info,
        feat_count,
        samples,
        rec_type,
    )


@router.delete("/{map_id}/layers/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_layer_endpoint(
    map_id: uuid.UUID,
    layer_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Remove a layer from a map."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    removed = await remove_layer(db, layer_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Layer not found",
        )

    await log_action(
        db,
        user_id=user.id,
        action="map.remove_layer",
        resource_type="map",
        resource_id=map_id,
        details={"layer_id": str(layer_id)},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
