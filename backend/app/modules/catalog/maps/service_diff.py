"""Map layer-diff and full-replace helpers extracted from service_crud (Phase 252 LAYERING-03).

Internal-helper-only: not re-exported by the maps service facade
(``service.py``). External callers must use the facade's public API; direct
imports of this module are blocked by the BOUND-01 architecture guard
(see ``test_layering.py::test_no_external_imports_of_maps_private_service_modules``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.schemas import (
    _MAX_LAYERS_PER_MAP,
    split_legacy_builder_paint,
)
from app.modules.catalog.maps.service_layers import bulk_check_dataset_access
from app.modules.catalog.maps.service_shared import (
    LayerRow,
    _fetch_layer_rows_ordered,
    _infer_layer_type,
    _resolve_save_response_metadata,
    generate_default_style,
    normalize_dem_style_config,
)
from app.platform.extensions import get_catalog_port

_NULLABLE_PATCH_FIELDS = {
    "display_name",
    "filter",
    "label_config",
    "popup_config",
    "style_config",
}


def _prepare_layer_storage(
    layer_data: dict,
    ds_meta: dict[uuid.UUID, tuple[str | None, str | None, bool | None]],
) -> dict:
    """Normalize one *added* layer's storage shape before it is persisted.

    builder-audit #338 STYLE-08: this is the single normalization boundary on the
    add / full-replace write path — it resolves the layer_type, fills default
    paint/layout/style_config for vector geometries, runs
    ``split_legacy_builder_paint`` (the MapLibre paint storage boundary), and
    normalizes DEM style_config. Both ``apply_layer_diff`` (added) and
    ``_replace_layers`` route every new layer through here.

    The ``split_legacy_builder_paint`` call below is idempotent: ``layer_data``
    has already been split once by ``MapLayerInput._normalize_paint_boundary``
    at the API boundary (which is also where unknown private paint keys are
    rejected and where the PATCH/updated path — which does NOT pass through this
    function — gets normalized). Re-running it here keeps this function correct
    for any caller and covers the default styles synthesized just above. Do not
    remove it without making this the only write path.
    """
    dataset_id = layer_data["dataset_id"]
    record_type, geometry_type, is_dem = ds_meta.get(dataset_id, (None, None, None))

    explicit_lt = layer_data.get("layer_type")
    if explicit_lt is not None:
        resolved_layer_type = explicit_lt
    else:
        resolved_layer_type = _infer_layer_type(record_type)

    paint = layer_data.get("paint")
    layout = layer_data.get("layout")
    style_config = layer_data.get("style_config")

    if resolved_layer_type == "raster_geolens":
        if paint is None:
            paint = {}
        if layout is None:
            layout = {}
    elif paint is None or layout is None:
        defaults = generate_default_style(geometry_type)
        if paint is None:
            paint = defaults["paint"]
        if layout is None:
            layout = defaults["layout"]
        if style_config is None:
            style_config = defaults.get("style_config")

    paint, style_config = split_legacy_builder_paint(paint, style_config)
    style_config = normalize_dem_style_config(style_config, is_dem=is_dem)

    return {
        **layer_data,
        "paint": paint,
        "layout": layout,
        "style_config": style_config,
        "layer_type": resolved_layer_type,
        "display_name": layer_data.get("display_name") or None,
    }


async def apply_layer_diff(
    session: AsyncSession,
    map_id: uuid.UUID,
    *,
    added: list[dict],
    updated: list[dict],
    removed: list[uuid.UUID],
    order: list[uuid.UUID] | None,
    user: Identity,
    user_roles: set[str],
) -> tuple[Map, list[LayerRow], str | None, str | None]:
    """Apply an incremental layer diff. Flushes but does NOT commit."""
    result = await session.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if map_obj is None:
        raise ValueError(f"Map {map_id} not found")

    layers_result = await session.execute(
        select(MapLayer).where(MapLayer.map_id == map_id).order_by(MapLayer.sort_order)
    )
    existing_layers = list(layers_result.scalars().all())
    existing_by_id = {layer.id: layer for layer in existing_layers}

    updated_ids = {layer_data["id"] for layer_data in updated}
    removed_ids = set(removed)
    unknown_ids = (updated_ids | removed_ids) - set(existing_by_id)
    if unknown_ids:
        raise ValueError("Layer diff references layer ids outside this map")

    if order is not None:
        ordered_ids = set(order)
        unknown_order_ids = ordered_ids - set(existing_by_id)
        removed_order_ids = ordered_ids & removed_ids
        if unknown_order_ids or removed_order_ids:
            raise ValueError("Layer order references unknown or removed layers")

    final_layer_count = len(existing_layers) - len(removed_ids) + len(added)
    if final_layer_count > _MAX_LAYERS_PER_MAP:
        raise ValueError(f"Layer count exceeds maximum {_MAX_LAYERS_PER_MAP}")

    added_dataset_ids = [layer_data["dataset_id"] for layer_data in added]
    accessible = await bulk_check_dataset_access(
        session, added_dataset_ids, user, user_roles
    )
    inaccessible = [str(did) for did in added_dataset_ids if did not in accessible]
    if inaccessible:
        raise PermissionError("Cannot access one or more layer datasets")

    if removed_ids:
        await session.execute(
            delete(MapLayer).where(
                MapLayer.map_id == map_id,
                MapLayer.id.in_(removed_ids),
            )
        )

    style_patch_dataset_ids = {
        existing_by_id[layer_data["id"]].dataset_id
        for layer_data in updated
        if "style_config" in layer_data
    }
    dem_by_dataset_id: dict[uuid.UUID, bool | None] = {}
    if style_patch_dataset_ids:
        RasterAsset = get_catalog_port().raster_asset_orm_class()
        dem_result = await session.execute(
            select(RasterAsset.dataset_id, RasterAsset.is_dem).where(
                RasterAsset.dataset_id.in_(style_patch_dataset_ids)
            )
        )
        dem_by_dataset_id = {
            row[0]: bool(row[1]) if row[1] is not None else None
            for row in dem_result.all()
        }

    for layer_data in updated:
        layer = existing_by_id[layer_data["id"]]
        patch = {
            key: value
            for key, value in layer_data.items()
            if key != "id" and (value is not None or key in _NULLABLE_PATCH_FIELDS)
        }
        if "display_name" in layer_data:
            patch["display_name"] = layer_data["display_name"] or None
        if "popup_config" in patch and patch["popup_config"] is not None:
            popup_config = patch["popup_config"]
            if hasattr(popup_config, "model_dump"):
                patch["popup_config"] = popup_config.model_dump()
        if "style_config" in patch:
            patch["style_config"] = normalize_dem_style_config(
                patch["style_config"],
                is_dem=dem_by_dataset_id.get(layer.dataset_id),
            )
        for key, value in patch.items():
            setattr(layer, key, value)

    if added:
        RasterAsset = get_catalog_port().raster_asset_orm_class()
        ds_meta_result = await session.execute(
            select(
                Dataset.id,
                Record.record_type,
                Dataset.geometry_type,
                RasterAsset.is_dem,
            )
            .join(Record, Record.id == Dataset.record_id)
            .outerjoin(RasterAsset, RasterAsset.dataset_id == Dataset.id)
            .where(Dataset.id.in_(added_dataset_ids))
        )
        ds_meta = {
            row[0]: (row[1], row[2], bool(row[3]) if row[3] is not None else None)
            for row in ds_meta_result.all()
        }

        for layer_data in added:
            prepared = _prepare_layer_storage(layer_data, ds_meta)
            session.add(
                MapLayer(
                    map_id=map_id,
                    dataset_id=prepared["dataset_id"],
                    sort_order=prepared.get("sort_order", 0),
                    visible=prepared.get("visible", True),
                    opacity=prepared.get("opacity", 1.0),
                    paint=prepared["paint"],
                    layout=prepared["layout"],
                    layer_type=prepared["layer_type"],
                    display_name=prepared["display_name"],
                    filter=prepared.get("filter"),
                    label_config=prepared.get("label_config"),
                    popup_config=prepared.get("popup_config"),
                    style_config=prepared["style_config"],
                    show_in_legend=prepared.get("show_in_legend", True),
                )
            )

    if order is not None:
        ordered_set = set(order)
        surviving_existing = [
            layer for layer in existing_layers if layer.id not in removed_ids
        ]
        remaining = [
            layer for layer in surviving_existing if layer.id not in ordered_set
        ]
        order_index = 0
        for layer_id in order:
            existing_by_id[layer_id].sort_order = order_index
            order_index += 1
        for layer in remaining:
            layer.sort_order = order_index
            order_index += 1

    await session.flush()
    layer_rows = await _fetch_layer_rows_ordered(session, map_obj.id)
    forked_name, owner_username, db_updated_at = await _resolve_save_response_metadata(
        session, map_obj
    )
    if db_updated_at is not None:
        map_obj.updated_at = db_updated_at
    return map_obj, layer_rows, forked_name, owner_username


async def _replace_layers(
    session: AsyncSession,
    map_id: uuid.UUID,
    layers: list[dict],
) -> None:
    """Delete all existing layers for a map and create new ones.

    Applies default styles if paint/layout is None. Flushes but does NOT commit.
    """
    # Delete existing layers
    await session.execute(delete(MapLayer).where(MapLayer.map_id == map_id))

    # Bulk-fetch record_type + geometry_type for all datasets in one query
    dataset_ids = [ld["dataset_id"] for ld in layers]
    RasterAsset = get_catalog_port().raster_asset_orm_class()
    ds_meta_result = await session.execute(
        select(
            Dataset.id,
            Record.record_type,
            Dataset.geometry_type,
            RasterAsset.is_dem,
        )
        .join(Record, Record.id == Dataset.record_id)
        .outerjoin(RasterAsset, RasterAsset.dataset_id == Dataset.id)
        .where(Dataset.id.in_(dataset_ids))
    )
    ds_meta = {
        row[0]: (row[1], row[2], bool(row[3]) if row[3] is not None else None)
        for row in ds_meta_result.all()
    }

    for layer_data in layers:
        prepared = _prepare_layer_storage(layer_data, ds_meta)

        new_layer = MapLayer(
            map_id=map_id,
            dataset_id=prepared["dataset_id"],
            sort_order=prepared.get("sort_order", 0),
            visible=prepared.get("visible", True),
            opacity=prepared.get("opacity", 1.0),
            paint=prepared["paint"],
            layout=prepared["layout"],
            layer_type=prepared["layer_type"],
            display_name=prepared["display_name"],
            filter=prepared.get("filter"),
            label_config=prepared.get("label_config"),
            popup_config=prepared.get("popup_config"),
            style_config=prepared["style_config"],
            show_in_legend=prepared.get("show_in_legend", True),
        )
        session.add(new_layer)

    await session.flush()
