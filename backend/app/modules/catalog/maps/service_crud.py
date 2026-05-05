"""Map CRUD, listing, update, delete, and duplicate helpers."""

import re
import uuid
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.identity import Identity
from app.modules.auth.models import User
from app.modules.catalog.authorization import get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.service_layers import bulk_check_dataset_access
from app.modules.catalog.maps.service_shared import (
    LayerRow,
    _apply_map_visibility_filter,
    _fetch_layer_rows_ordered,
    _infer_layer_type,
    _resolve_save_response_metadata,
    generate_default_style,
)

_COPY_SUFFIX_RE = re.compile(r"\s*\(copy(?:\s+(\d+))?\)\s*$")
_UNSET = object()


async def check_map_ownership(map_obj: Map, user: Identity, db: AsyncSession) -> None:
    """Verify user owns the map or is admin. Raises 403 if neither."""
    if map_obj.created_by == user.id:
        return
    user_roles = await get_user_roles(db, user)
    if "admin" in user_roles:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized to modify this map",
    )


async def create_map(
    session: AsyncSession,
    name: str,
    description: str | None,
    created_by: uuid.UUID,
    notes: str | None = None,
) -> Map:
    """Create a map. Does NOT commit."""
    map_obj = Map(
        name=name,
        description=description,
        notes=notes,
        created_by=created_by,
    )
    session.add(map_obj)
    await session.flush()
    return map_obj


async def get_map(
    session: AsyncSession,
    map_id: uuid.UUID,
) -> Map | None:
    """Fetch single map by ID."""
    result = await session.execute(select(Map).where(Map.id == map_id))
    return result.scalar_one_or_none()


async def get_map_with_layers(
    session: AsyncSession,
    map_id: uuid.UUID,
) -> tuple[Map | None, list[LayerRow], str | None, str | None]:
    """Fetch map and its layers with dataset info, forked_from_name, and owner_username.

    Returns (map, [(layer, dataset_name, geometry_type, table_name, extent, column_info, feature_count, sample_values, record_type, is_3d), ...], forked_from_name, owner_username)
    or (None, [], None, None).

    Read path uses a single combined Map+ForkedMap+User LEFT JOIN to keep
    the public GET /maps/{id} hot path at 2 queries total (matches
    pre-PERF-6 behavior; the helper-based pattern is reserved for the
    save path where map_obj is already in-session).
    """
    ForkedMap = aliased(Map)
    map_stmt = (
        select(
            Map,
            ForkedMap.name.label("forked_from_name"),
            User.username.label("owner_username"),
        )
        .outerjoin(ForkedMap, Map.forked_from == ForkedMap.id)
        .outerjoin(User, Map.created_by == User.id)
        .where(Map.id == map_id)
    )
    map_row = (await session.execute(map_stmt)).one_or_none()
    if map_row is None:
        return None, [], None, None
    map_obj, forked_from_name, owner_username = map_row
    layer_rows = await _fetch_layer_rows_ordered(session, map_id)
    return map_obj, layer_rows, forked_from_name, owner_username


async def list_maps(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
    user_id: uuid.UUID | None = None,
    user_roles: set[str] | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    visibility: str | None = None,
) -> tuple[list[dict], int]:
    """List maps with layer counts, filtered by visibility rules.

    - Admins see ALL maps (no filter).
    - Authenticated non-admin users see: their own private maps + all internal + all public.
    - If user_roles is omitted, treats user as non-admin (still sees own + internal + public).
    - search: ILIKE filter on name and description.
    - sort_by: name, created_at, updated_at (default). Unknown values fall back to updated_at.
    - sort_dir: asc or desc.
    - visibility: additional filter on Map.visibility (additive on top of RBAC).

    Returns (list of dicts with map fields + layer_count + created_by_username, total).
    """
    if user_roles is None:
        user_roles = set()

    is_admin = "admin" in user_roles

    def _apply_vis_filter(stmt: Select) -> Select:
        return _apply_map_visibility_filter(stmt, user_id, is_admin)

    # Build search/visibility filters (applied to both count and data queries)
    def _apply_extra_filters(stmt: Select) -> Select:
        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(
                or_(
                    Map.name.ilike(pattern),
                    Map.description.ilike(pattern),
                )
            )
        if visibility:
            stmt = stmt.where(Map.visibility == visibility)
        return stmt

    # Resolve sort column
    sort_column_map = {
        "name": Map.name,
        "created_at": Map.created_at,
        "updated_at": Map.updated_at,
    }
    col = sort_column_map.get(sort_by, Map.updated_at)
    order_clause = col.asc() if sort_dir == "asc" else col.desc()

    # Subquery for layer count
    layer_count_sq = (
        select(
            MapLayer.map_id,
            func.count(MapLayer.id).label("layer_count"),
        )
        .group_by(MapLayer.map_id)
        .subquery()
    )

    # Total count (with RBAC + search/visibility filters)
    count_base = select(func.count()).select_from(Map)
    count_base = _apply_vis_filter(count_base)
    count_base = _apply_extra_filters(count_base)
    total_result = await session.execute(count_base)
    total = total_result.scalar_one()

    # Paginated maps with layer count and author username
    stmt = (
        select(
            Map,
            func.coalesce(layer_count_sq.c.layer_count, 0).label("layer_count"),
            User.username.label("created_by_username"),
        )
        .outerjoin(layer_count_sq, Map.id == layer_count_sq.c.map_id)
        .outerjoin(User, Map.created_by == User.id)
        .order_by(order_clause)
        .offset(skip)
        .limit(limit)
    )
    stmt = _apply_vis_filter(stmt)
    stmt = _apply_extra_filters(stmt)

    result = await session.execute(stmt)
    rows = result.all()

    maps = []
    for row in rows:
        map_obj = row[0]
        maps.append(
            {
                "id": map_obj.id,
                "name": map_obj.name,
                "description": map_obj.description,
                "visibility": map_obj.visibility,
                "thumbnail_url": f"/maps/{map_obj.id}/thumbnail/"
                if map_obj.thumbnail_uri
                else None,
                "layer_count": row[1],
                "created_by_username": row[2],
                "created_at": map_obj.created_at,
                "updated_at": map_obj.updated_at,
            }
        )

    return maps, total


async def update_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    center_lng: float | None = None,
    center_lat: float | None = None,
    zoom: float | None = None,
    bearing: float | None = None,
    pitch: float | None = None,
    basemap_style: str | None = None,
    show_basemap_labels: bool | None = None,
    visibility: str | None = None,
    widgets: list[str] | None | object = _UNSET,
    layers: list[dict] | None = None,
) -> tuple[Map, list[LayerRow], str | None, str | None]:
    """Update map fields. If 'layers' key present, replace all layers.

    Raises ValueError if not found. Flushes but does NOT commit --
    callers must own the commit lifecycle.

    Returns the same 4-tuple shape as ``get_map_with_layers``:
    ``(Map, layer_rows, forked_from_name, owner_username)``. Built from
    in-session ORM state so callers don't need a post-save re-fetch.
    """
    result = await session.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if map_obj is None:
        raise ValueError(f"Map {map_id} not found")

    # Update scalar fields (skip None values, except explicit widgets=null which
    # restores client-default widget behavior).
    scalar_fields = {
        "name": name,
        "description": description,
        "notes": notes,
        "center_lng": center_lng,
        "center_lat": center_lat,
        "zoom": zoom,
        "bearing": bearing,
        "pitch": pitch,
        "basemap_style": basemap_style,
        "show_basemap_labels": show_basemap_labels,
        "visibility": visibility,
    }
    for key, value in scalar_fields.items():
        if value is not None:
            setattr(map_obj, key, value)
    if widgets is not _UNSET:
        map_obj.widgets = cast(list[str] | None, widgets)

    # Replace layers if provided
    if layers is not None:
        await _replace_layers(session, map_id, layers)

    await session.flush()
    # Combined LEFT JOIN reads forked_name + owner_username + DB-side
    # updated_at in one round-trip — eliminates the explicit
    # ``session.refresh(map_obj)`` previously needed for ``updated_at``.
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
    ds_meta_result = await session.execute(
        select(Dataset.id, Record.record_type, Dataset.geometry_type)
        .join(Record, Record.id == Dataset.record_id)
        .where(Dataset.id.in_(dataset_ids))
    )
    ds_meta = {row[0]: (row[1], row[2]) for row in ds_meta_result.all()}

    # Create new layers
    for layer_data in layers:
        dataset_id = layer_data["dataset_id"]
        record_type, geometry_type = ds_meta.get(dataset_id, (None, None))

        # Resolve layer_type from explicit value or bulk-fetched record_type
        explicit_lt = layer_data.get("layer_type")
        if explicit_lt is not None:
            resolved_layer_type = explicit_lt
        else:
            resolved_layer_type = _infer_layer_type(record_type)

        paint = layer_data.get("paint")
        layout = layer_data.get("layout")

        if resolved_layer_type == "raster_geolens":
            # Raster layers use empty paint/layout
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

        # Normalize empty display_name to None
        display_name = layer_data.get("display_name") or None

        new_layer = MapLayer(
            map_id=map_id,
            dataset_id=dataset_id,
            sort_order=layer_data.get("sort_order", 0),
            visible=layer_data.get("visible", True),
            opacity=layer_data.get("opacity", 1.0),
            paint=paint,
            layout=layout,
            layer_type=resolved_layer_type,
            display_name=display_name,
            filter=layer_data.get("filter"),
            label_config=layer_data.get("label_config"),
            popup_config=layer_data.get("popup_config"),
            style_config=layer_data.get("style_config"),
            show_in_legend=layer_data.get("show_in_legend", True),
        )
        session.add(new_layer)

    await session.flush()


async def delete_map(
    session: AsyncSession,
    map_id: uuid.UUID,
) -> str:
    """Delete map by ID. CASCADE handles map_layers cleanup.

    Raises ValueError if not found. Returns map name for audit.
    Does NOT commit.
    """
    result = await session.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if map_obj is None:
        raise ValueError(f"Map {map_id} not found")

    name = map_obj.name
    await session.delete(map_obj)
    await session.flush()
    return name


async def _generate_fork_name(
    session: AsyncSession, source_name: str, user_id: uuid.UUID
) -> str:
    """Generate a collision-safe fork name.

    Strips existing '(copy)' / '(copy N)' suffix to avoid chaining, then
    finds the next available numeric suffix scoped to the user's maps.
    """
    base = _COPY_SUFFIX_RE.sub("", source_name).rstrip()

    # Find existing copies owned by this user
    result = await session.execute(
        select(Map.name).where(
            Map.created_by == user_id,
            Map.name.like(f"{base} (copy%"),
        )
    )
    existing_names = {row[0] for row in result.all()}

    candidate = f"{base} (copy)"
    if candidate not in existing_names:
        return candidate

    n = 2
    while True:
        candidate = f"{base} (copy {n})"
        if candidate not in existing_names:
            return candidate
        n += 1


async def duplicate_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    user: Identity,
) -> tuple[Map, list[LayerRow], str | None, str | None, int]:
    """Deep-copy a map with RBAC-filtered layers. Does NOT commit.

    Returns the 4-tuple shape from ``get_map_with_layers`` plus
    ``excluded_layer_count`` appended:
    ``(new_map, layer_rows, forked_from_name, owner_username,
       excluded_layer_count)``. Built from in-session ORM state so callers
    don't need a post-save re-fetch.
    """
    source = await get_map(session, map_id)
    if source is None:
        raise ValueError(f"Map {map_id} not found")

    user_roles = await get_user_roles(session, user)
    fork_name = await _generate_fork_name(session, source.name, user.id)

    # Create new map - always private, no thumbnail, track lineage
    new_map = Map(
        name=fork_name,
        description=source.description,
        notes=source.notes,
        center_lng=source.center_lng,
        center_lat=source.center_lat,
        zoom=source.zoom,
        bearing=source.bearing,
        pitch=source.pitch,
        basemap_style=source.basemap_style,
        show_basemap_labels=source.show_basemap_labels,
        widgets=source.widgets,
        thumbnail_uri=None,
        visibility="private",
        forked_from=source.id,
        created_by=user.id,
    )
    session.add(new_map)
    await session.flush()

    # Copy layers, filtering by RBAC
    layers_result = await session.execute(
        select(MapLayer).where(MapLayer.map_id == map_id).order_by(MapLayer.sort_order)
    )
    layers = layers_result.scalars().all()

    # Bulk-fetch dataset visibility info to avoid N+1 queries
    layer_dataset_ids = list({layer.dataset_id for layer in layers})
    accessible_ids = await bulk_check_dataset_access(
        session, layer_dataset_ids, user, user_roles
    )

    excluded_count = 0
    for layer in layers:
        if layer.dataset_id not in accessible_ids:
            excluded_count += 1
            continue
        new_layer = MapLayer(
            map_id=new_map.id,
            dataset_id=layer.dataset_id,
            sort_order=layer.sort_order,
            visible=layer.visible,
            opacity=layer.opacity,
            paint=layer.paint,
            layout=layer.layout,
            layer_type=layer.layer_type,
            display_name=layer.display_name,
            filter=layer.filter,
            label_config=layer.label_config,
            popup_config=layer.popup_config,
            style_config=layer.style_config,
            show_in_legend=layer.show_in_legend,
        )
        session.add(new_layer)

    await session.flush()
    layer_rows = await _fetch_layer_rows_ordered(session, new_map.id)
    forked_name, owner_username, _ = await _resolve_save_response_metadata(
        session, new_map
    )
    return new_map, layer_rows, forked_name, owner_username, excluded_count
