"""Import an ArcGIS web map as a GeoLens map."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.core.persistent_config import BASEMAPS
from app.core.permissions import EDIT_METADATA
from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import (
    check_datasets_access_bulk,
    check_public_visibility_allowed,
    get_user_roles,
)
from app.modules.catalog.maps._router_helpers import (
    _visible_map_response,
)
from app.modules.catalog.maps.arcgis_webmap.translate import translate_webmap
from app.modules.catalog.maps.schemas_import_arcgis import (
    ArcgisLossReport,
    ArcgisUnmatchedLayer,
    ArcgisWebmapImportRequest,
    ArcgisWebmapImportResponse,
)
from app.modules.catalog.maps.service import (
    check_map_ownership,
    create_map,
    get_map_with_layers,
    record_map_history_event,
    update_map,
    validate_public_visibility,
    with_visible_vrt_extents,
)
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(prefix="/maps", tags=["Maps"], responses=ERROR_RESPONSES_WRITE)


async def _enabled_basemap_ids(db: AsyncSession) -> list[str]:
    return [
        entry["id"]
        for entry in await BASEMAPS.get(db)
        if entry.get("enabled", True) and isinstance(entry.get("id"), str)
    ]


def _refuse_non_public(titles: Iterable[str]) -> None:
    """400 naming the non-public datasets; one builder for the dry run and the import."""
    names = sorted(set(titles))
    if names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "A public map can't contain non-public datasets",
                "datasets": ", ".join(names),
            },
        )


# Declared on both the trailing-slash and no-slash paths, since the app sets
# redirect_slashes=False.
@router.post(
    "/import/arcgis-webmap",
    response_model=ArcgisWebmapImportResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
@router.post(
    "/import/arcgis-webmap/",
    response_model=ArcgisWebmapImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_arcgis_webmap_endpoint(
    body: ArcgisWebmapImportRequest,
    request: Request,
    user: Identity = Depends(require_permission(EDIT_METADATA)),
    db: AsyncSession = Depends(get_db),
) -> ArcgisWebmapImportResponse:
    """Import an ArcGIS web map as a new GeoLens map.

    Translates the web map's operational layers, renderers, labels, popups and
    scale ranges, and reports everything it could not carry over in
    `loss_report`. Only layers named in `dataset_matches` are imported, and
    every matched dataset must be readable by the caller (404 otherwise). The
    report is also written to the map's private notes. With `dry_run` nothing
    is created and `map` is null.
    """
    user_roles = await get_user_roles(db, user)
    # Reject before translating or writing: a map must never reference a
    # dataset the caller cannot read.
    datasets = await check_datasets_access_bulk(
        db, list(set(body.dataset_matches.values())), user, user_roles
    )
    visibility = body.visibility.value
    await check_public_visibility_allowed(db, user, visibility, user_roles=user_roles)

    translation = translate_webmap(
        body.webmap,
        name=body.name or body.title,
        dataset_matches=body.dataset_matches,
        basemap_map=body.basemap_map,
        available_basemaps=await _enabled_basemap_ids(db),
    )
    loss_report = ArcgisLossReport.model_validate(translation.loss.as_dict())
    unmatched = [
        ArcgisUnmatchedLayer.model_validate(vars(item))
        for item in translation.unmatched
    ]
    if body.dry_run:
        if visibility == "public":
            _refuse_non_public(
                datasets[layer.dataset_id].record.title
                for layer in translation.layers
                if datasets[layer.dataset_id].record.visibility != "public"
            )
        return ArcgisWebmapImportResponse(
            map=None,
            layers=translation.layers,
            loss_report=loss_report,
            unmatched_layers=unmatched,
        )

    notes = translation.loss.render_text(datetime.now(UTC).date().isoformat())
    map_obj = await create_map(db, translation.name, None, user.id, notes=notes)
    # Records the writer admission that update_map's lock re-checks.
    await check_map_ownership(map_obj, user, db)
    await update_map(
        db,
        map_obj.id,
        user=user,
        visibility=visibility,
        basemap_style=translation.basemap_style,
        center_lng=translation.center_lng,
        center_lat=translation.center_lat,
        zoom=translation.zoom,
        layers=[layer.model_dump() for layer in translation.layers],
    )
    if visibility == "public":
        _refuse_non_public(await validate_public_visibility(db, map_obj.id, user))

    details = {
        "name": translation.name,
        "layers_imported": len(translation.layers),
        "layers_unmatched": len(translation.unmatched),
        "loss_items": len(translation.loss.items),
    }
    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="map.import_arcgis_webmap",
            resource_type="map",
            resource_id=map_obj.id,
            details=details,
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
        action="map.import_arcgis_webmap",
        summary=f"Imported ArcGIS web map with {len(translation.layers)} layer(s)",
        details=details,
    )
    await db.commit()

    map_obj, layer_tuples, forked_name, owner_username = await get_map_with_layers(
        db, map_obj.id
    )
    if map_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    layer_tuples = await with_visible_vrt_extents(db, layer_tuples, user)
    response_map = await _visible_map_response(
        db,
        map_obj,
        layer_tuples,
        user,
        forked_name,
        owner_username,
        include_notes=True,
    )
    # Layers keep the translation index as sort_order, and the response may
    # omit rows the caller can no longer read, so pair by sort_order.
    sources = translation.layer_sources
    layer_ids = {
        sources[layer.sort_order]: layer.id
        for layer in response_map.layers
        if layer.sort_order < len(sources)
    }
    return ArcgisWebmapImportResponse(
        map=response_map,
        layer_ids=layer_ids,
        layers=translation.layers,
        loss_report=loss_report,
        unmatched_layers=unmatched,
    )
