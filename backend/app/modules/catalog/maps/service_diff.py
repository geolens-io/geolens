"""Map layer-diff and full-replace helpers, private to service_crud.

Internal-helper-only: not re-exported by the maps service facade
(``service.py``). Direct imports of this module are blocked by the
architecture guard (``test_layering.py``).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.schemas import (
    _MAX_LAYERS_PER_MAP,
    split_legacy_builder_paint,
)
from app.modules.catalog.maps.service_layers import (
    bulk_check_dataset_access,
    lock_map_layers,
)
from app.modules.catalog.maps.service_shared import (
    LayerRow,
    _fetch_layer_rows_ordered,
    _infer_layer_type,
    _resolve_save_response_metadata,
    generate_default_style,
    normalize_dem_style_config,
    readable_dataset_ids,
)
from app.platform.extensions import get_catalog_port

_NULLABLE_PATCH_FIELDS = {
    "display_name",
    "filter",
    "label_config",
    "popup_config",
    "style_config",
}


def _coerce_uuid(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


async def _unreadable_layer_ids(
    session: AsyncSession, layers: list[MapLayer], user: Identity | None
) -> set[uuid.UUID]:
    """Ids of ``layers`` that map reads hide from ``user``; a save leaves them be."""
    readable = await readable_dataset_ids(
        session, {layer.dataset_id for layer in layers}, user
    )
    return {layer.id for layer in layers if layer.dataset_id not in readable}


def _restack(
    stack: list[MapLayer], hidden_ids: set[uuid.UUID], visible: list[MapLayer]
) -> None:
    """Keep each hidden layer at its index in ``stack``; ``visible`` fills the rest."""
    hidden_at = {i: layer for i, layer in enumerate(stack) if layer.id in hidden_ids}
    rest = iter(visible)
    for position in range(len(hidden_at) + len(visible)):
        layer = hidden_at[position] if position in hidden_at else next(rest)
        layer.sort_order = position


def _prepare_layer_storage(
    layer_data: dict,
    ds_meta: dict[uuid.UUID, tuple[str | None, str | None, bool | None]],
) -> dict:
    """Normalize one *added* layer's storage shape before it is persisted.

    The single normalization boundary on the add/full-replace write path:
    resolves layer_type, fills default paint/layout/style_config, runs
    ``split_legacy_builder_paint`` (idempotent; already split once at the API
    boundary), and normalizes DEM style_config. Both ``apply_layer_diff`` and
    ``_replace_layers`` route new layers here.
    """
    dataset_id = layer_data["dataset_id"]
    record_type, geometry_type, is_dem = ds_meta.get(dataset_id, (None, None, None))

    # Asked even when the caller names a layer type, so a dataset that cannot
    # be a layer is refused either way.
    dataset_layer_type = _infer_layer_type(record_type)
    explicit_lt = layer_data.get("layer_type")
    resolved_layer_type = explicit_lt if explicit_lt is not None else dataset_layer_type

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
            # The default outline belongs to the default paint; with a sent
            # paint it would outrank the paint's own fill-outline-color.
            if style_config is None:
                style_config = defaults.get("style_config")
        if layout is None:
            layout = defaults["layout"]

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
    await lock_map_layers(session, map_id)
    result = await session.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if map_obj is None:
        raise ValueError(f"Map {map_id} not found")

    layers_result = await session.execute(
        select(MapLayer)
        .where(MapLayer.map_id == map_id)
        .order_by(MapLayer.sort_order, MapLayer.id)  # Deterministic tie-break
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
        surviving = [layer for layer in existing_layers if layer.id not in removed_ids]
        hidden_ids = await _unreadable_layer_ids(session, surviving, user)
        listed = [existing_by_id[layer_id] for layer_id in order]
        unlisted = [layer for layer in surviving if layer.id not in ordered_set]
        _restack(
            surviving,
            hidden_ids,
            [layer for layer in listed + unlisted if layer.id not in hidden_ids],
        )

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
    user: Identity | None,
) -> dict[uuid.UUID, uuid.UUID]:
    """Reconcile a map's layers against ``layers`` by id.

    Existing rows are updated in place by id, so layer UUIDs that embed
    configs and bookmarks hold stay stable; unknown ids create rows.
    A stored layer ``layers`` leaves out is kept, in its place in the stack,
    when map reads hide its dataset from ``user``.
    Applies default styles if paint/layout is None. Flushes but does NOT commit.

    Returns ``{sent id: new id}`` for the rows this call created from a sent
    id. An id sent for two new layers is left out, since it names neither.
    """
    existing_result = await session.execute(
        select(MapLayer)
        .where(MapLayer.map_id == map_id)
        .order_by(MapLayer.sort_order, MapLayer.id)
    )
    stored = list(existing_result.scalars().all())
    existing_by_id = {layer.id: layer for layer in stored}
    requested_ids = {_coerce_uuid(layer_data.get("id")) for layer_data in layers}
    hidden_ids = await _unreadable_layer_ids(
        session, [layer for layer in stored if layer.id not in requested_ids], user
    )
    if len(layers) + len(hidden_ids) > _MAX_LAYERS_PER_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Layer count exceeds maximum {_MAX_LAYERS_PER_MAP}",
        )

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

    kept_ids = set(hidden_ids)
    placed: list[tuple[int, MapLayer]] = []
    created: list[tuple[uuid.UUID, MapLayer]] = []
    for layer_data in layers:
        prepared = _prepare_layer_storage(layer_data, ds_meta)
        raw_id = _coerce_uuid(layer_data.get("id"))
        existing = existing_by_id.get(raw_id) if raw_id is not None else None

        if existing is not None:
            kept_ids.add(existing.id)
            existing.dataset_id = prepared["dataset_id"]
            existing.sort_order = prepared.get("sort_order", 0)
            existing.visible = prepared.get("visible", True)
            existing.opacity = prepared.get("opacity", 1.0)
            existing.paint = prepared["paint"]
            existing.layout = prepared["layout"]
            existing.layer_type = prepared["layer_type"]
            existing.display_name = prepared["display_name"]
            existing.filter = prepared.get("filter")
            existing.label_config = prepared.get("label_config")
            existing.popup_config = prepared.get("popup_config")
            existing.style_config = prepared["style_config"]
            existing.show_in_legend = prepared.get("show_in_legend", True)
        else:
            existing = MapLayer(
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
            session.add(existing)
            if raw_id is not None:
                created.append((raw_id, existing))
        placed.append((existing.sort_order, existing))

    if hidden_ids:
        _restack(
            [layer for layer in stored if layer.id in kept_ids],
            hidden_ids,
            [layer for _, layer in sorted(placed, key=lambda item: item[0])],
        )

    stale_ids = set(existing_by_id) - kept_ids
    if stale_ids:
        await session.execute(
            delete(MapLayer).where(
                MapLayer.map_id == map_id, MapLayer.id.in_(stale_ids)
            )
        )

    await session.flush()
    created_ids: dict[uuid.UUID, uuid.UUID] = {}
    repeated: set[uuid.UUID] = set()
    for sent_id, row in created:
        if sent_id in created_ids:
            repeated.add(sent_id)
        created_ids[sent_id] = row.id
    return {k: v for k, v in created_ids.items() if k not in repeated}
