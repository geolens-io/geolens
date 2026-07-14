"""Maps API endpoints: CRUD, duplication, and layer management."""

import base64
import uuid
from datetime import UTC, datetime
from io import BytesIO
from typing import Literal

from PIL import Image, UnidentifiedImageError

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.core.identity import Identity
from app.modules.auth.dependencies import (
    get_current_active_user,
    get_optional_user,
    require_permission,
)
from app.modules.catalog.authorization import get_user_roles
from app.core.dependencies import get_db
from app.modules.catalog.maps.schemas import (
    BulkDeleteLayersRequest,
    BulkDeleteLayersResponse,
    BulkDeleteLayersFailure,
    DuplicateMapResponse,
    MapCreate,
    MapLayerDiffRequest,
    MapLayerInput,
    MapLayerResponse,
    MapHistoryListResponse,
    MapListResponse,
    MapResponse,
    MapAccessResponse,
    MapStyleImportRequest,
    MapStyleImportResponse,
    MapSummaryResponse,
    MapUpdate,
    MapVisibility,
    OgImageUploadRequest,
    ThumbnailUploadRequest,
)
from app.modules.catalog.maps.router_assets import router as assets_router
from app.modules.catalog.maps.router_sharing import router as sharing_router
from app.modules.catalog.maps.style_json import parse_maplibre_style_import
from app.modules.catalog.maps.service import (
    bulk_check_dataset_access,
    add_layer,
    apply_layer_diff,
    check_map_ownership,
    create_map,
    delete_map,
    filter_layer_rows_by_dataset_visibility,
    get_dataset_meta,
    duplicate_map,
    get_map,
    get_map_with_layers,
    list_map_history,
    list_maps,
    record_map_history_event,
    remove_layer,
    revoke_share_token_by_map,
    update_map,
    validate_public_visibility,
)
from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.maps.service import remove_layers_bulk
from app.modules.embed_tokens.service import (
    revoke_embed_tokens_by_map,
    revoke_embed_tokens_for_dropped_datasets,
)
from app.platform.storage.titiler_url import (
    resolve_current_storage_key as _map_asset_storage_key,
)
from app.standards.ogc.errors import BAD_GATEWAY_RESPONSE, ERROR_RESPONSES_WRITE
from app.modules.catalog.maps._router_helpers import (
    _build_layer_response,
    _build_map_response,
    _can_edit_map,
    _check_map_read_access,
    _layer_history_name,
    _layer_patch_history_actions,
    _layer_rows_by_id,
    _layers_from_tuples,
    _meta_to_kwargs,
    _visibility_value,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/maps", tags=["Maps"], responses=ERROR_RESPONSES_WRITE)
router.include_router(assets_router)
router.include_router(sharing_router)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ROUTE-01 (Phase 1092): dual-shape decorator — both trailing-slash and
# no-trailing-slash variants register against the same handler. Slash form
# stays canonical (already in OpenAPI); no-slash is a hidden alias closing
# the 404 regression introduced by redirect_slashes=False (api/main.py).
@router.post(
    "",
    response_model=MapResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post("/", response_model=MapResponse, status_code=status.HTTP_201_CREATED)
async def create_map_endpoint(
    body: MapCreate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapResponse:
    """Create a new map."""
    terrain_config = (
        body.terrain_config.model_dump(mode="json")
        if body.terrain_config is not None
        else None
    )
    basemap_config = (
        body.basemap_config.model_dump(mode="json")
        if body.basemap_config is not None
        else None
    )
    map_obj = await create_map(
        db,
        body.name,
        body.description,
        user.id,
        notes=body.notes,
        terrain_config=terrain_config,
        basemap_config=basemap_config,
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.create",
            resource_type="map",
            resource_id=map_obj.id,
            details={"name": body.name},
            ip_address=request.client.host if request.client else None,
        ),
    )
    await record_map_history_event(
        db,
        map_id=map_obj.id,
        actor=user,
        target_type="map",
        target_id=map_obj.id,
        target_name=map_obj.name,
        action="map.create",
        summary=f"Created map {map_obj.name}",
        details={"name": map_obj.name},
    )
    await db.commit()
    await db.refresh(map_obj)
    return _build_map_response(map_obj, [], created_by_username=user.username)


# ROUTE-01 (Phase 1092): dual-shape decorator — see POST /maps above.
@router.get("", response_model=MapListResponse, include_in_schema=False)
@router.get("/", response_model=MapListResponse)
async def list_maps_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = None,
    sort_by: Literal["name", "created_at", "updated_at"] = "updated_at",
    sort_dir: Literal["asc", "desc"] = "desc",
    visibility: str | None = None,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> MapListResponse:
    """List maps. Admins see all; authenticated users see own + internal + public; anonymous see public only.

    Supports search (ILIKE on name+description), sort_by (name/created_at/updated_at),
    sort_dir (asc/desc), and visibility filter (private/internal/public).
    """
    if user is not None:
        user_roles = await get_user_roles(db, user)
        uid = user.id
    else:
        user_roles = set()
        uid = None
    maps, total = await list_maps(
        db,
        skip=skip,
        limit=limit,
        user_id=uid,
        user_roles=user_roles,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        visibility=visibility,
    )

    summaries = [MapSummaryResponse(**m) for m in maps]
    return MapListResponse(maps=summaries, total=total)


@router.post(
    "/import",
    response_model=MapStyleImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_map_style_endpoint(
    body: MapStyleImportRequest,
    request: Request = None,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapStyleImportResponse:
    """Import a MapLibre style JSON document into a new GeoLens map.

    API-01 (M-05): the request body is now a typed Pydantic model instead of
    a bare ``dict``. ``MapStyleImportRequest`` mirrors the MapLibre style
    spec top-level keys with ``extra="allow"``, so existing payloads keep
    working byte-identically while the OpenAPI schema gains a named class
    and the auto-generated SDKs stop emitting an opaque ``Mapping[str, Any]``
    request type.
    """
    # builder-audit #338 STYLE-08: MapStyleImportRequest defines no field aliases, so
    # the prior by_alias=True was a no-op that implied aliasing that doesn't exist.
    style = body.model_dump(exclude_none=True)
    try:
        imported = parse_maplibre_style_import(style)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if imported.layers:
        user_roles = await get_user_roles(db, user)
        requested_ids = [layer.dataset_id for layer in imported.layers]
        accessible = await bulk_check_dataset_access(
            db,
            requested_ids,
            user,
            user_roles,
        )
        inaccessible = [str(did) for did in requested_ids if did not in accessible]
        if inaccessible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "Cannot access one or more imported layer datasets",
                    "datasets": inaccessible,
                },
            )

    map_obj = await create_map(
        db,
        imported.name,
        imported.description,
        user.id,
    )
    map_obj.center_lng = imported.center_lng
    map_obj.center_lat = imported.center_lat
    if imported.zoom is not None:
        map_obj.zoom = imported.zoom
    if imported.bearing is not None:
        map_obj.bearing = imported.bearing
    if imported.pitch is not None:
        map_obj.pitch = imported.pitch
    if imported.basemap_style:
        map_obj.basemap_style = imported.basemap_style
    if imported.terrain_config is not None:
        map_obj.terrain_config = imported.terrain_config
    if imported.basemap_config is not None:
        map_obj.basemap_config = imported.basemap_config

    imported_layer_ids: list[uuid.UUID] = []
    for layer in imported.layers:
        layer_obj = await add_layer(db, map_obj.id, layer)
        imported_layer_ids.append(layer_obj.id)

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.import_style",
            resource_type="map",
            resource_id=map_obj.id,
            details={
                "name": imported.name,
                "layers_imported": imported.summary.layers_imported,
                "layers_skipped": imported.summary.layers_skipped,
            },
            ip_address=request.client.host if request and request.client else None,
        ),
    )
    await record_map_history_event(
        db,
        map_id=map_obj.id,
        actor=user,
        target_type="map",
        target_id=map_obj.id,
        target_name=map_obj.name,
        action="map.import_style",
        summary=f"Imported style JSON with {len(imported_layer_ids)} layer(s)",
        details={
            "name": imported.name,
            "layers_imported": imported.summary.layers_imported,
            "layers_skipped": imported.summary.layers_skipped,
            "layer_ids": [str(layer_id) for layer_id in imported_layer_ids],
        },
    )
    await db.commit()

    map_obj, layer_tuples, forked_name, owner_username = await get_map_with_layers(
        db,
        map_obj.id,
    )
    layers = _layers_from_tuples(layer_tuples)
    assert map_obj is not None
    return MapStyleImportResponse(
        map=_build_map_response(
            map_obj,
            layers,
            forked_from_name=forked_name,
            created_by_username=owner_username,
        ),
        summary=imported.summary,
    )


@router.get("/{map_id}", response_model=MapResponse)
async def get_map_endpoint(
    map_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> MapResponse:
    """Get a single map with its layers."""
    map_obj, layer_tuples, forked_name, owner_username = await get_map_with_layers(
        db, map_id
    )
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    await _check_map_read_access(map_obj, user, db)
    layer_tuples = await filter_layer_rows_by_dataset_visibility(db, layer_tuples, user)
    layers = _layers_from_tuples(layer_tuples)
    return _build_map_response(
        map_obj,
        layers,
        forked_from_name=forked_name,
        created_by_username=owner_username,
    )


@router.get("/{map_id}/access/", response_model=MapAccessResponse)
async def get_map_access_endpoint(
    map_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> MapAccessResponse:
    """Return server-confirmed route access for the map viewer gate."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await _check_map_read_access(map_obj, user, db)
    return MapAccessResponse(
        can_view=True,
        can_edit=await _can_edit_map(map_obj, user, db),
    )


@router.get("/{map_id}/history", response_model=MapHistoryListResponse)
async def get_map_history_endpoint(
    map_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapHistoryListResponse:
    """Return recent builder edit history for a map."""
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)
    events, total = await list_map_history(db, map_id, skip=skip, limit=limit)
    return MapHistoryListResponse(
        events=events,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.put("/{map_id}", response_model=MapResponse)
async def update_map_endpoint(
    map_id: uuid.UUID,
    body: MapUpdate,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
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

    # Auto-revoke share tokens when visibility moves away from public
    if body.visibility is not None and body.visibility != MapVisibility.public:
        if map_obj.visibility == "public":
            await revoke_share_token_by_map(db, map_id)
            # builder-audit #338 P0-01: a public->non-public downgrade must also revoke
            # embed tokens, which previously survived (only the share token was
            # flipped) and kept serving tiles for a now-private map until expiry.
            await revoke_embed_tokens_by_map(db, map_id)

    # Hard block: prevent publishing maps with non-public datasets
    if body.visibility == MapVisibility.public:
        non_public = await validate_public_visibility(db, map_id)
        if non_public:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Cannot set visibility to public: map contains non-public datasets",
                    "datasets": ", ".join(non_public),
                },
            )

    # RBAC: when replacing layers, verify the user can access every dataset
    # referenced. Without this, a map owner could insert MapLayer rows pointing
    # at restricted datasets — RBAC at render time hides them, but the dangling
    # rows are still a data-integrity / leakage hazard.
    if body.layers is not None and body.layers:
        user_roles = await get_user_roles(db, user)
        requested_ids = [layer.dataset_id for layer in body.layers]
        accessible = await bulk_check_dataset_access(
            db, requested_ids, user, user_roles
        )
        inaccessible = [str(did) for did in requested_ids if did not in accessible]
        if inaccessible:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "Cannot access one or more layer datasets",
                    "datasets": inaccessible,
                },
            )

    changed_fields = list(body.model_dump(exclude_unset=True).keys())
    previous_values = {
        "name": map_obj.name,
        "visibility": map_obj.visibility,
        "terrain_config": map_obj.terrain_config,
        "basemap_config": map_obj.basemap_config,
    }

    # Build update kwargs from fields the client actually sent. This preserves
    # explicit plugins=null, which restores client-default plugin behavior.
    kwargs = body.model_dump(exclude_unset=True)
    if "terrain_config" in kwargs and body.terrain_config is not None:
        kwargs["terrain_config"] = body.terrain_config.model_dump(mode="json")
    if "basemap_config" in kwargs and body.basemap_config is not None:
        kwargs["basemap_config"] = body.basemap_config.model_dump(mode="json")
    if "layers" in kwargs and body.layers is not None:
        kwargs["layers"] = [layer.model_dump() for layer in body.layers]

    try:
        map_obj, layer_tuples, forked_name, owner_username = await update_map(
            db, map_id, **kwargs
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    layers = _layers_from_tuples(layer_tuples)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.update",
            resource_type="map",
            resource_id=map_id,
            details={"changed_fields": changed_fields},
            ip_address=request.client.host if request.client else None,
        ),
    )
    # builder-audit #338 STYLE-06: the per-field history events were six near-identical
    # copy-pasted record_map_history_event blocks. Drive them from one table of
    # (changed, action, summary, details) and loop uniformly so a new
    # history-tracked field is a single row, not another hand-written block. The
    # emitted events/semantics are identical to the previous blocks.
    new_visibility = (
        _visibility_value(kwargs["visibility"])
        if "visibility" in kwargs and kwargs["visibility"] is not None
        else None
    )
    config_fields = sorted(
        set(changed_fields)
        - {"name", "visibility", "terrain_config", "basemap_config", "layers"}
    )
    history_events = [
        (
            "name" in kwargs
            and bool(kwargs["name"])
            and kwargs["name"] != previous_values["name"],
            "map.rename",
            f"Renamed map to {map_obj.name}",
            {
                "field": "name",
                "previous": previous_values["name"],
                "current": map_obj.name,
            },
        ),
        (
            "visibility" in kwargs
            and kwargs["visibility"] is not None
            and new_visibility != previous_values["visibility"],
            "map.visibility_update",
            f"Changed visibility to {map_obj.visibility}",
            {
                "field": "visibility",
                "previous": previous_values["visibility"],
                "current": map_obj.visibility,
            },
        ),
        (
            "terrain_config" in kwargs
            and kwargs["terrain_config"] != previous_values["terrain_config"],
            "map.terrain_update",
            "Updated terrain settings",
            {
                "field": "terrain_config",
                "previous": previous_values["terrain_config"],
                "current": map_obj.terrain_config,
            },
        ),
        (
            "basemap_config" in kwargs
            and kwargs["basemap_config"] != previous_values["basemap_config"],
            "map.basemap_update",
            "Updated basemap appearance",
            {
                "field": "basemap_config",
                "previous": previous_values["basemap_config"],
                "current": map_obj.basemap_config,
            },
        ),
        (
            "layers" in kwargs,
            "layer.replace",
            f"Replaced map layers with {len(layers)} layer(s)",
            {"layer_count": len(layers)},
        ),
        (
            bool(config_fields),
            "map.config_update",
            "Updated map settings",
            {"changed_fields": config_fields},
        ),
    ]
    for changed, action, summary, details in history_events:
        if not changed:
            continue
        await record_map_history_event(
            db,
            map_id=map_id,
            actor=user,
            target_type="map",
            target_id=map_id,
            target_name=map_obj.name,
            action=action,
            summary=summary,
            details=details,
        )

    if "layers" in kwargs:
        # builder-audit #338 P0-01: replacing the layer set can drop a dataset an
        # embed token is scoped to; revoke any orphaned embed tokens so they
        # stop serving tiles for content the map no longer exposes.
        await revoke_embed_tokens_for_dropped_datasets(db, map_id)
    await db.commit()

    return _build_map_response(
        map_obj,
        layers,
        forked_from_name=forked_name,
        created_by_username=owner_username,
    )


@router.patch("/{map_id}/layers", response_model=MapResponse)
@router.patch(
    "/{map_id}/layers/",
    response_model=MapResponse,
    include_in_schema=False,
)
async def patch_map_layers_endpoint(
    map_id: uuid.UUID,
    body: MapLayerDiffRequest,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapResponse:
    """Apply incremental layer additions, patches, removals, and ordering.

    v13.14 fixup: declared on both slash variants directly (mirrors the
    Phase 280 fix on POST). FastAPI's default redirect_slashes builds a
    relative Location header that resolves against the request's Host
    header, which would leak the in-container ``api:8000`` hostname
    through Vite's dev proxy on a 307 redirect. The canonical
    (OpenAPI-published) form is the no-slash sub-collection convention
    documented in the GeoLens API guide (https://docs.getgeolens.com/guides/api/);
    the trailing-slash form is a hidden alias.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    _, before_layer_tuples, _, _ = await get_map_with_layers(db, map_id)
    before_rows_by_id = _layer_rows_by_id(before_layer_tuples)

    user_roles = await get_user_roles(db, user)
    try:
        map_obj, layer_tuples, forked_name, owner_username = await apply_layer_diff(
            db,
            map_id,
            added=[layer.model_dump() for layer in body.added],
            updated=[layer.model_dump(exclude_unset=True) for layer in body.updated],
            removed=body.removed,
            order=body.order,
            user=user,
            user_roles=user_roles,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Cannot access one or more layer datasets",
            },
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if detail.startswith("Map ") and detail.endswith("not found")
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=detail)

    layers = _layers_from_tuples(layer_tuples)
    after_rows_by_id = _layer_rows_by_id(layer_tuples)
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.patch_layers",
            resource_type="map",
            resource_id=map_id,
            details={
                "added": len(body.added),
                "updated": [str(layer.id) for layer in body.updated],
                "removed": [str(layer_id) for layer_id in body.removed],
                "order": [str(layer_id) for layer_id in body.order]
                if body.order is not None
                else None,
                "fallback_full_replace": body.fallback_full_replace,
            },
            ip_address=request.client.host if request.client else None,
        ),
    )
    for row in layer_tuples:
        if row.layer.id not in before_rows_by_id:
            await record_map_history_event(
                db,
                map_id=map_id,
                actor=user,
                target_type="layer",
                target_id=row.layer.id,
                target_name=_layer_history_name(row.layer, row.title),
                action="layer.add",
                summary=f"Added {_layer_history_name(row.layer, row.title)} layer",
                details={
                    "dataset_id": str(row.layer.dataset_id),
                    "sort_order": row.layer.sort_order,
                },
            )

    for patch_model in body.updated:
        patch = patch_model.model_dump(exclude_unset=True)
        patch.pop("id", None)
        if not patch:
            continue
        row = after_rows_by_id.get(patch_model.id) or before_rows_by_id.get(
            patch_model.id
        )
        if row is None:
            continue
        target_name = _layer_history_name(row.layer, row.title)
        for action, summary in _layer_patch_history_actions(patch):
            await record_map_history_event(
                db,
                map_id=map_id,
                actor=user,
                target_type="layer",
                target_id=patch_model.id,
                target_name=target_name,
                action=action,
                summary=summary
                if action != "layer.rename"
                else f"Renamed layer to {target_name}",
                details={"changed_fields": sorted(patch)},
            )

    for layer_id in body.removed:
        row = before_rows_by_id.get(layer_id)
        await record_map_history_event(
            db,
            map_id=map_id,
            actor=user,
            target_type="layer",
            target_id=layer_id,
            target_name=_layer_history_name(row.layer, row.title) if row else None,
            action="layer.remove",
            summary=f"Removed {_layer_history_name(row.layer, row.title)} layer"
            if row
            else "Removed layer",
            details={
                "dataset_id": str(row.layer.dataset_id) if row else None,
                "sort_order": row.layer.sort_order if row else None,
            },
        )

    if body.order is not None:
        await record_map_history_event(
            db,
            map_id=map_id,
            actor=user,
            target_type="map",
            target_id=map_id,
            target_name=map_obj.name,
            action="layer.reorder",
            summary="Reordered layers",
            details={"order": [str(layer_id) for layer_id in body.order]},
        )
    # builder-audit #338 P0-01: a diff that removes layers can drop a dataset an embed
    # token is scoped to; revoke any now-orphaned embed tokens.
    if body.removed:
        await revoke_embed_tokens_for_dropped_datasets(db, map_id)
    await db.commit()

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
    user: Identity = Depends(require_permission("edit_metadata")),
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
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.delete",
            resource_type="map",
            resource_id=map_id,
            details={"name": map_name},
            ip_address=request.client.host if request.client else None,
        ),
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{map_id}/duplicate/",
    response_model=DuplicateMapResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_map_endpoint(
    map_id: uuid.UUID,
    request: Request,
    # Any authenticated user may fork — does not require editor role
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DuplicateMapResponse:
    """Fork a map with RBAC-filtered layers. Any authenticated user can fork."""
    try:
        (
            new_map,
            layer_tuples,
            forked_name,
            owner_username,
            excluded_count,
        ) = await duplicate_map(db, map_id, user)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )

    await audit_emit(
        db,
        AuditEvent(
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
        ),
    )
    await db.commit()

    layers = _layers_from_tuples(layer_tuples)
    base_resp = _build_map_response(
        new_map,
        layers,
        forked_from_name=forked_name,
        created_by_username=owner_username,
    )
    return DuplicateMapResponse(
        **base_resp.model_dump(),
        excluded_layer_count=excluded_count,
    )


@router.put(
    "/{map_id}/thumbnail/",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={502: BAD_GATEWAY_RESPONSE},
)
async def upload_thumbnail(
    map_id: uuid.UUID,
    request: ThumbnailUploadRequest,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Upload a base64 thumbnail for a map.

    Accepts a data:image/ URI, decodes the base64 payload, writes the image
    bytes to the configured storage provider, and stores the storage key.
    """
    from app.platform.storage.provider import get_storage

    data_uri = request.data_uri

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
    # Phase 254 IN-02: the 100KB length bound now lives on
    # ThumbnailUploadRequest.data_uri (Field(max_length=100_000)). Pydantic
    # rejects oversize payloads with a 422 at request validation time,
    # before this handler ever runs — so the previous manual
    # `if len(data_uri) > 100_000` check has been removed as redundant.

    # Decode base64 data URI → raw image bytes
    # Format: data:image/jpeg;base64,<payload>
    if ";base64," not in data_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body must be a base64-encoded data URI",
        )
    try:
        header, encoded = data_uri.split(",", 1)
        image_bytes = base64.b64decode(encoded)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid data URI or base64 encoding",
        )

    # SEC-12 / L-65: validate that the decoded bytes are a real image, not
    # arbitrary attacker-controlled content labeled as data:image/png. PIL's
    # Image.verify() walks the file header + structure without fully decoding
    # the pixel data — fast (<10ms for typical thumbnails) and rejects all
    # the obvious tampering vectors (random bytes, truncated images,
    # mismatched MIME). Without this gate, a user with edit_metadata could
    # store arbitrary bytes that GET /maps/{id}/thumbnail/ later serves back
    # with a media_type=image/* Content-Type — a stored-content tampering
    # primitive.
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        logger.warning(
            "thumbnail_upload_invalid_image",
            map_id=str(map_id),
            byte_length=len(image_bytes),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Thumbnail payload is not a valid image",
        )

    # Determine extension from MIME type
    ext = "jpg" if "jpeg" in header else "png"
    storage_key = f"maps/thumbnails/{map_id}.{ext}"

    storage = get_storage()
    try:
        await storage.put(_map_asset_storage_key(storage_key), image_bytes)
    except Exception:  # broad: storage backend (S3/MinIO/local) can throw varied SDK/I/O errors; map to 502
        logger.exception("thumbnail_upload_failed", map_id=str(map_id))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Thumbnail storage unavailable",
        )

    map_obj.thumbnail_uri = storage_key
    map_obj.updated_at = datetime.now(UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{map_id}/thumbnail/", response_class=Response)
async def get_thumbnail(
    map_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve map thumbnail image from storage (visibility-checked)."""
    from app.platform.storage.provider import get_storage

    map_obj = await get_map(db, map_id)
    if map_obj is None or not map_obj.thumbnail_uri:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not found",
        )

    await _check_map_read_access(map_obj, user, db)

    storage = get_storage()
    try:
        data = await storage.get(_map_asset_storage_key(map_obj.thumbnail_uri))
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not found",
        )
    media_type = "image/jpeg" if map_obj.thumbnail_uri.endswith(".jpg") else "image/png"
    cache_control = (
        "public, max-age=3600"
        if map_obj.visibility == "public"
        else "private, no-cache"
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": cache_control},
    )


# ---------------------------------------------------------------------------
# OG-image upload/serve — SHARE-08 Path A
# ---------------------------------------------------------------------------


@router.put(
    "/{map_id}/og-image/",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={502: BAD_GATEWAY_RESPONSE},
)
async def upload_og_image(
    map_id: uuid.UUID,
    request: OgImageUploadRequest,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Upload a base64 OG social-card image (up to 750KB) for a map.

    Accepts a data:image/ URI, decodes the base64 payload, validates the
    bytes are a real image (PIL verify), writes to storage under
    ``maps/og-images/{map_id}.{ext}``, and persists the storage key to
    ``catalog.maps.og_image_uri``.

    Intended for 1200x630 JPEG captures (SHARE-08). The payload cap
    (750KB) is larger than the thumbnail cap (100KB) to accommodate the
    larger canvas export — they are separate schemas (OgImageUploadRequest
    vs ThumbnailUploadRequest) to avoid relaxing the locked thumbnail
    contract. Auth and PIL-verify rules are identical to upload_thumbnail.
    """
    from app.platform.storage.provider import get_storage

    data_uri = request.data_uri

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

    if ";base64," not in data_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body must be a base64-encoded data URI",
        )
    try:
        header, encoded = data_uri.split(",", 1)
        image_bytes = base64.b64decode(encoded)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid data URI or base64 encoding",
        )

    # Validate the decoded bytes are a real image (mirrors thumbnail PUT).
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        logger.warning(
            "og_image_upload_invalid_image",
            map_id=str(map_id),
            byte_length=len(image_bytes),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OG image payload is not a valid image",
        )

    ext = "jpg" if "jpeg" in header else "png"
    storage_key = f"maps/og-images/{map_id}.{ext}"

    storage = get_storage()
    try:
        await storage.put(_map_asset_storage_key(storage_key), image_bytes)
    except Exception:  # broad: S3/MinIO/local storage can throw varied errors -> 502
        logger.exception("og_image_upload_failed", map_id=str(map_id))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OG image storage unavailable",
        )

    map_obj.og_image_uri = storage_key
    map_obj.updated_at = datetime.now(UTC)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{map_id}/og-image/", response_class=Response)
async def get_og_image(
    map_id: uuid.UUID,
    user: Identity | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve the OG social-card image from storage (visibility-checked).

    Uses ``public, max-age=86400`` for public maps — OG images change
    less often than thumbnails (which use 3600s). Mirrors get_thumbnail
    but reads ``og_image_uri`` and uses the ``maps/og-images/`` key space.
    """
    from app.platform.storage.provider import get_storage

    map_obj = await get_map(db, map_id)
    if map_obj is None or not map_obj.og_image_uri:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OG image not found",
        )

    await _check_map_read_access(map_obj, user, db)

    storage = get_storage()
    try:
        data = await storage.get(_map_asset_storage_key(map_obj.og_image_uri))
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OG image not found",
        )
    media_type = "image/jpeg" if map_obj.og_image_uri.endswith(".jpg") else "image/png"
    cache_control = (
        "public, max-age=86400"
        if map_obj.visibility == "public"
        else "private, no-cache"
    )
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": cache_control},
    )


@router.post(
    "/{map_id}/layers",
    response_model=MapLayerResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/{map_id}/layers/",
    response_model=MapLayerResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def add_layer_endpoint(
    map_id: uuid.UUID,
    body: MapLayerInput,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> MapLayerResponse:
    """Add a layer to a map.

    Phase 280: declared on both slash variants directly so neither emits a
    307. FastAPI's default redirect_slashes builds a relative Location
    header that resolves against the request's Host header, leaking the
    in-container ``api:8000`` hostname through Vite's dev proxy. The
    canonical (OpenAPI-published) form is the no-slash sub-collection
    convention documented in the GeoLens API guide
    (https://docs.getgeolens.com/guides/api/); the trailing-slash form is a
    hidden alias for callers that send the slash.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    # Verify the user can access the target dataset
    user_roles = await get_user_roles(db, user)
    accessible = await bulk_check_dataset_access(
        db, [body.dataset_id], user, user_roles
    )
    if body.dataset_id not in accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access this dataset",
        )

    layer = await add_layer(db, map_id, body)
    meta = await get_dataset_meta(db, body.dataset_id)
    target_name = _layer_history_name(layer, meta.title if meta else None)

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.add_layer",
            resource_type="map",
            resource_id=map_id,
            details={"dataset_id": str(body.dataset_id)},
            ip_address=request.client.host if request.client else None,
        ),
    )
    await record_map_history_event(
        db,
        map_id=map_id,
        actor=user,
        target_type="layer",
        target_id=layer.id,
        target_name=target_name,
        action="layer.add",
        summary=f"Added {target_name} layer",
        details={
            "dataset_id": str(body.dataset_id),
            "sort_order": layer.sort_order,
        },
    )
    await db.commit()

    return _build_layer_response(layer, _meta_to_kwargs(meta))


@router.delete("/{map_id}/layers/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_layer_endpoint(
    map_id: uuid.UUID,
    layer_id: uuid.UUID,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
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

    layer_result = await db.execute(
        select(MapLayer).where(MapLayer.map_id == map_id, MapLayer.id == layer_id)
    )
    layer = layer_result.scalar_one_or_none()
    if layer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Layer not found",
        )
    meta = await get_dataset_meta(db, layer.dataset_id)
    target_name = _layer_history_name(layer, meta.title if meta else None)

    removed = await remove_layer(db, layer_id, map_id=map_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Layer not found",
        )

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.remove_layer",
            resource_type="map",
            resource_id=map_id,
            details={"layer_id": str(layer_id)},
            ip_address=request.client.host if request.client else None,
        ),
    )
    await record_map_history_event(
        db,
        map_id=map_id,
        actor=user,
        target_type="layer",
        target_id=layer_id,
        target_name=target_name,
        action="layer.remove",
        summary=f"Removed {target_name} layer",
        details={
            "dataset_id": str(layer.dataset_id),
            "sort_order": layer.sort_order,
        },
    )
    # builder-audit #338 P0-01: removing a layer can drop a dataset an embed token is
    # scoped to; revoke any now-orphaned embed tokens for the map.
    await revoke_embed_tokens_for_dropped_datasets(db, map_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{map_id}/layers/bulk-delete",
    response_model=BulkDeleteLayersResponse,
    status_code=status.HTTP_200_OK,
)
async def bulk_delete_layers_endpoint(
    map_id: uuid.UUID,
    body: BulkDeleteLayersRequest,
    request: Request,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> BulkDeleteLayersResponse:
    """Batch-delete multiple layers from a map in a single request.

    Milestone exception (v1010 Phase 1047): one additive endpoint permitted
    per REQUIREMENTS.md Out-of-Scope to reduce N sequential DELETEs to one
    batched call for bulk-delete UX (PB-03 / PERF-03).

    Returns 200 with deleted/failed arrays in all cases (partial failures
    surface inline, not as HTTP errors).  Full rollback is the caller's
    responsibility if all ids fail.
    """
    map_obj = await get_map(db, map_id)
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Map not found",
        )
    await check_map_ownership(map_obj, user, db)

    deleted_ids, failed_pairs = await remove_layers_bulk(db, body.layer_ids, map_id)

    deleted_count = len(deleted_ids)

    # Phase 20260526-builder-audit #338 BLD-20260526-11: only emit audit/history when something was actually deleted.
    # A request where all IDs are not_found produces deleted_count=0; emitting
    # audit rows in that case creates false positives for monitoring systems.
    if deleted_count > 0:
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="map.bulk_remove_layers",
                resource_type="map",
                resource_id=map_id,
                details={
                    "layer_ids": [str(lid) for lid in body.layer_ids],
                    "deleted_count": deleted_count,
                },
                ip_address=request.client.host if request.client else None,
            ),
        )

        # Phase 20260526-builder-audit #338 BLD-20260526-11: use target_type="map" with target_id=map_id since there is no
        # single layer target for a bulk operation.  Mirrors how layer.replace is
        # recorded elsewhere and prevents broken "jump to layer" links in history.
        await record_map_history_event(
            db,
            map_id=map_id,
            actor=user,
            target_type="map",
            target_id=map_id,
            target_name=map_obj.name,
            action="layer.bulk_remove",
            summary=f"Removed {deleted_count} layers",
            details={
                "deleted_count": deleted_count,
                "failed_count": len(failed_pairs),
            },
        )

        # builder-audit #338 P0-01: a bulk delete can drop a dataset an embed token is
        # scoped to; revoke any now-orphaned embed tokens for the map.
        await revoke_embed_tokens_for_dropped_datasets(db, map_id)

    await db.commit()

    return BulkDeleteLayersResponse(
        deleted=deleted_ids,
        failed=[
            BulkDeleteLayersFailure(id=fid, reason=reason)
            for fid, reason in failed_pairs
        ],
    )
