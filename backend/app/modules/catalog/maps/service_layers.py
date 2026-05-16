"""Map layer access checks and mutation helpers."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.auth.models import UserRole
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.maps.models import MapLayer
from app.modules.catalog.maps.schemas import MapLayerInput, split_legacy_builder_paint
from app.modules.catalog.maps.service_shared import (
    _infer_layer_type,
    generate_default_style,
    get_dataset_meta,
)


async def bulk_check_dataset_access(
    session: AsyncSession,
    dataset_ids: list[uuid.UUID],
    user: Identity,
    user_roles: set[str],
) -> set[uuid.UUID]:
    """Return the subset of dataset_ids the user can access. Single round-trip."""
    if not dataset_ids:
        return set()

    if "admin" in user_roles:
        return set(dataset_ids)

    # Fetch visibility info for all datasets at once
    result = await session.execute(
        select(Dataset.id, Record.visibility, Record.created_by)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id.in_(dataset_ids))
    )
    rows = result.all()

    accessible = set()
    restricted_ids = []
    for ds_id, visibility, created_by in rows:
        if visibility == "public":
            accessible.add(ds_id)
        elif visibility == "private" and created_by == user.id:
            accessible.add(ds_id)
        elif visibility == "restricted":
            restricted_ids.append(ds_id)

    # Batch-check grants for restricted datasets
    if restricted_ids:
        grant_result = await session.execute(
            select(DatasetGrant.dataset_id)
            .join(UserRole, DatasetGrant.role_id == UserRole.role_id)
            .where(
                DatasetGrant.dataset_id.in_(restricted_ids),
                UserRole.user_id == user.id,
            )
        )
        accessible.update(row[0] for row in grant_result.all())

    return accessible


async def add_layer(
    session: AsyncSession,
    map_id: uuid.UUID,
    body: MapLayerInput,
) -> MapLayer:
    """Add a layer to a map. Applies default style if paint/layout is None.

    Does NOT commit.
    """
    # Single query for record_type + geometry_type (replaces two separate queries)
    meta = await get_dataset_meta(session, body.dataset_id)
    record_type = meta.record_type if meta else None
    geometry_type = meta.geometry_type if meta else None

    resolved_layer_type = body.layer_type or _infer_layer_type(record_type)

    paint = body.paint
    layout = body.layout
    style_config = body.style_config
    # Raster layers use empty paint/layout (no vector style defaults)
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
    sort_order = body.sort_order
    if "sort_order" not in body.model_fields_set:
        result = await session.execute(
            select(MapLayer.sort_order)
            .where(MapLayer.map_id == map_id)
            .order_by(MapLayer.sort_order.desc())
            .limit(1)
        )
        highest_sort_order = result.scalar_one_or_none()
        sort_order = 0 if highest_sort_order is None else highest_sort_order + 1

    layer = MapLayer(
        map_id=map_id,
        dataset_id=body.dataset_id,
        sort_order=sort_order,
        visible=body.visible,
        opacity=body.opacity,
        paint=paint,
        layout=layout,
        layer_type=resolved_layer_type,
        display_name=body.display_name,
        filter=body.filter,
        label_config=body.label_config,
        popup_config=body.popup_config.model_dump() if body.popup_config else None,
        style_config=style_config,
        show_in_legend=body.show_in_legend,
    )
    session.add(layer)
    await session.flush()
    return layer


async def remove_layer(
    session: AsyncSession,
    layer_id: uuid.UUID,
    *,
    map_id: uuid.UUID | None = None,
) -> bool:
    """Delete a map layer by ID. Returns True if deleted, False if not found."""
    stmt = delete(MapLayer).where(MapLayer.id == layer_id)
    if map_id is not None:
        stmt = stmt.where(MapLayer.map_id == map_id)
    result = await session.execute(stmt)
    # SQLAlchemy CursorResult exposes rowcount for DML; the async Result
    # type stub is less specific so mypy can't narrow it here.
    return result.rowcount > 0  # type: ignore[attr-defined]


async def remove_layers_bulk(
    session: AsyncSession,
    layer_ids: list[uuid.UUID],
    map_id: uuid.UUID,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Batch-delete multiple layers from a map in a single transaction.

    Fetches all matching MapLayer rows in one SELECT, then removes them
    with a single DELETE WHERE id=ANY(...) AND map_id=:map_id. Layer ids
    that were not found in the SELECT are returned in the failure list.

    Returns:
        (deleted_ids, failed_pairs) where:
        - deleted_ids: list[str] — UUIDs of successfully deleted layers.
        - failed_pairs: list[(str, str)] — (layer_id_str, reason) for each
          layer that could not be found (reason="not_found").

    NOTE: The caller is responsible for committing the transaction. This
    function does NOT call session.commit() so that audit/history can be
    written in the same transaction before the commit.
    """
    if not layer_ids:
        return [], []

    # Fetch all matching rows in one round-trip to discover which ids exist
    existing_result = await session.execute(
        select(MapLayer.id).where(
            MapLayer.map_id == map_id,
            MapLayer.id.in_(layer_ids),
        )
    )
    existing_ids: set[uuid.UUID] = set(existing_result.scalars().all())

    # Determine failures (ids not in the map)
    failed_pairs: list[tuple[str, str]] = [
        (str(lid), "not_found")
        for lid in layer_ids
        if lid not in existing_ids
    ]

    if not existing_ids:
        return [], failed_pairs

    # Single DELETE for all found rows
    await session.execute(
        delete(MapLayer).where(
            MapLayer.map_id == map_id,
            MapLayer.id.in_(existing_ids),
        )
    )

    deleted_ids = [str(lid) for lid in layer_ids if lid in existing_ids]
    return deleted_ids, failed_pairs
