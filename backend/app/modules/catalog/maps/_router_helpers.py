"""Shared pure helpers for the maps router (response builders + access checks).

No dependency on ``router.py``, so importing these back does not create a
circular import.
"""

import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.geo import extent_to_bbox
from app.core.identity import Identity
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.schemas import (
    DatasetMetaKwargs,
    MapLayerResponse,
    MapResponse,
)
from app.modules.catalog.maps.service import LayerRow

logger = structlog.stdlib.get_logger(__name__)


def _build_frame_ancestors(origins: list[str] | None) -> str:
    """Build a CSP frame-ancestors directive value from an allowed_origins list.

    SEC-S08: two defense-in-depth filters on top of the schema-layer 422 at
    create/update time, guarding any stale DB row that bypassed it — CRLF
    entries (would split the response header) and wildcard entries ('*' in
    frame-ancestors disables clickjacking protection entirely, SHARE-06).
    """
    if not origins:
        return "frame-ancestors 'self'"
    safe: list[str] = []
    for o in origins:
        if "\r" in o or "\n" in o or "*" in o or not o.strip():
            # Silently drop malformed or wildcard entries — see docstring.
            continue
        safe.append(o.strip())
    if not safe:
        return "frame-ancestors 'self'"
    return f"frame-ancestors 'self' {' '.join(safe)}"


def _meta_to_kwargs(meta) -> DatasetMetaKwargs:
    """Map a DatasetMeta tuple (or None) to the kwargs _build_layer_response expects (centralizes Unknown/empty/None defaults)."""
    if meta is None:
        return DatasetMetaKwargs(
            dataset_name="Unknown",
            geometry_type=None,
            table_name="",
            extent=None,
            column_info=None,
            feature_count=None,
            sample_values=None,
            record_type=None,
            is_3d=None,
            is_dem=None,
            dem_vertical_units=None,
            band_count=None,
            tile_version=None,
            publication_version=None,
            dataset_visibility=None,
            dataset_status=None,
            dataset_attribution=None,
        )
    return DatasetMetaKwargs(
        dataset_name=meta.title,
        geometry_type=meta.geometry_type,
        table_name=meta.table_name,
        extent=meta.extent,
        column_info=meta.column_info,
        feature_count=meta.feature_count,
        sample_values=meta.sample_values,
        record_type=meta.record_type,
        is_3d=meta.is_3d,
        is_dem=meta.is_dem,
        dem_vertical_units=meta.dem_vertical_units,
        band_count=meta.band_count,
        tile_version=meta.tile_version,
        publication_version=meta.publication_version,
        dataset_visibility=meta.visibility,
        dataset_status=meta.record_status,
        dataset_attribution=meta.attribution,
    )


def _build_layer_response(
    layer: MapLayer,
    meta: DatasetMetaKwargs,
) -> MapLayerResponse:
    return MapLayerResponse(
        id=layer.id,
        dataset_id=layer.dataset_id,
        dataset_name=meta.get("dataset_name", ""),
        dataset_geometry_type=meta.get("geometry_type"),
        dataset_table_name=meta.get("table_name", ""),
        # fix(#1112): RFC 7946 §5.2 bbox (west > east on a crossing) — the
        # builder fit paths unwrap it past 180, while normalizeRasterBounds
        # re-spans it at the source boundary (an inverted pair matches no tile).
        dataset_extent_bbox=extent_to_bbox(meta.get("extent")),
        dataset_column_info=meta.get("column_info"),
        dataset_feature_count=meta.get("feature_count"),
        dataset_sample_values=meta.get("sample_values"),
        display_name=layer.display_name,
        sort_order=layer.sort_order,
        visible=layer.visible,
        opacity=layer.opacity,
        paint=layer.paint,
        layout=layer.layout,
        layer_type=getattr(layer, "layer_type", "vector_geolens") or "vector_geolens",
        dataset_record_type=meta.get("record_type"),
        filter=layer.filter,
        label_config=layer.label_config,
        popup_config=layer.popup_config,
        style_config=layer.style_config,
        show_in_legend=layer.show_in_legend,
        is_3d=meta.get("is_3d"),
        is_dem=meta.get("is_dem"),
        dem_vertical_units=meta.get("dem_vertical_units"),
        band_count=meta.get("band_count"),
        tile_version=meta.get("tile_version"),
        publication_version=meta.get("publication_version"),
        dataset_visibility=meta.get("dataset_visibility"),
        dataset_status=meta.get("dataset_status"),
        dataset_attribution=meta.get("dataset_attribution"),
    )


def _layers_from_tuples(layer_rows: list[LayerRow]) -> list[MapLayerResponse]:
    """Build a list of MapLayerResponse from the LayerRow tuples returned by get_map_with_layers."""
    return [
        _build_layer_response(
            row.layer,
            DatasetMetaKwargs(
                dataset_name=row.title,
                geometry_type=row.geometry_type,
                table_name=row.table_name,
                extent=row.spatial_extent,
                column_info=row.column_info,
                feature_count=row.feature_count,
                sample_values=row.sample_values,
                record_type=row.record_type,
                is_3d=row.is_3d,
                is_dem=row.is_dem,
                dem_vertical_units=row.dem_vertical_units,
                band_count=row.band_count,
                tile_version=row.tile_version,
                publication_version=row.publication_version,
                dataset_visibility=row.visibility,
                dataset_status=row.record_status,
                dataset_attribution=row.attribution,
            ),
        )
        for row in layer_rows
    ]


def _layer_history_name(layer: MapLayer, dataset_name: str | None = None) -> str:
    return layer.display_name or dataset_name or "Layer"


def _layer_rows_by_id(layer_rows: list[LayerRow]) -> dict[uuid.UUID, LayerRow]:
    return {row.layer.id: row for row in layer_rows}


def _visibility_value(value: object) -> str:
    return getattr(value, "value", value)


def _style_config_mentions_symbol(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    stack: list[object] = [value]
    symbol_keys = {"symbol", "icon", "icon_id", "iconColor", "sprite_id"}
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                key_text = str(key)
                if key_text in symbol_keys or key_text.lower() in {
                    "symbol",
                    "icon",
                    "icon_id",
                    "sprite_id",
                    "render_mode",
                }:
                    return True
                if isinstance(item, str) and item.lower() == "symbol":
                    return True
                stack.append(item)
        elif isinstance(current, list):
            stack.extend(current)
    return False


def _layer_patch_history_actions(patch: dict) -> list[tuple[str, str]]:
    actions: list[tuple[str, str]] = []
    if "display_name" in patch:
        actions.append(("layer.rename", "Renamed layer"))
    if "visible" in patch:
        state = "shown" if patch["visible"] else "hidden"
        actions.append(("layer.visibility_update", f"Layer {state}"))
    if "opacity" in patch:
        actions.append(("layer.opacity_update", "Changed layer opacity"))
    if "filter" in patch:
        actions.append(("layer.filter_update", "Updated layer filter"))
    if "label_config" in patch:
        actions.append(("layer.label_update", "Updated layer labels"))
    if "popup_config" in patch:
        actions.append(("layer.popup_update", "Updated layer popup"))
    if "style_config" in patch and _style_config_mentions_symbol(patch["style_config"]):
        actions.append(("layer.symbol_update", "Updated symbol styling"))

    style_fields = {"paint", "layout", "style_config", "layer_type", "show_in_legend"}
    if style_fields & set(patch):
        actions.append(("layer.style_update", "Updated layer style"))
    if "sort_order" in patch:
        actions.append(("layer.reorder", "Reordered layer"))
    return actions


async def _check_map_read_access(
    map_obj: Map,
    user: Identity | None,
    db: AsyncSession,
) -> None:
    """Raise 404 if the user cannot read the map."""
    if user is None:
        if map_obj.visibility != "public":
            logger.warning("map_read_denied map_id=%s user=anon", map_obj.id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Map not found",
            )
    else:
        user_roles = await get_user_roles(db, user)
        is_admin = "admin" in user_roles
        is_owner = map_obj.created_by == user.id
        is_internal = map_obj.visibility == "internal"
        is_public = map_obj.visibility == "public"
        if not (is_public or is_owner or is_admin or is_internal):
            logger.warning("map_read_denied map_id=%s user_id=%s", map_obj.id, user.id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Map not found",
            )


async def _can_edit_map(
    map_obj: Map,
    user: Identity | None,
    db: AsyncSession,
) -> bool:
    if user is None:
        return False
    user_roles = await get_user_roles(db, user)
    is_admin = "admin" in user_roles
    is_editor = "editor" in user_roles
    is_owner = map_obj.created_by == user.id
    return is_admin or (is_editor and is_owner)


def _build_map_response(
    map_obj: Map,
    layers: list[MapLayerResponse],
    forked_from_name: str | None = None,
    created_by_username: str | None = None,
) -> MapResponse:
    thumbnail_url = f"/maps/{map_obj.id}/thumbnail/" if map_obj.thumbnail_uri else None
    og_image_url = f"/maps/{map_obj.id}/og-image/" if map_obj.og_image_uri else None
    return MapResponse(
        id=map_obj.id,
        name=map_obj.name,
        description=map_obj.description,
        notes=map_obj.notes,
        center_lng=map_obj.center_lng,
        center_lat=map_obj.center_lat,
        zoom=map_obj.zoom,
        bearing=map_obj.bearing,
        pitch=map_obj.pitch,
        basemap_style=map_obj.basemap_style,
        show_basemap_labels=map_obj.show_basemap_labels,
        basemap_config=map_obj.basemap_config,
        terrain_config=map_obj.terrain_config,
        visibility=map_obj.visibility,
        thumbnail_url=thumbnail_url,
        og_image_url=og_image_url,
        forked_from_id=map_obj.forked_from,
        forked_from_name=forked_from_name,
        created_by=map_obj.created_by,
        created_by_username=created_by_username,
        created_at=map_obj.created_at,
        updated_at=map_obj.updated_at,
        layers=layers,
        layer_count=len(layers),
        plugins=map_obj.plugins,
        legend_title=map_obj.legend_title,
    )
