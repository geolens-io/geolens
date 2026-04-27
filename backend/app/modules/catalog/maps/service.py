"""Maps service layer.

Handles CRUD operations for maps and map layers, plus default style generation.
"""

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import NamedTuple

import structlog
from fastapi import HTTPException, status
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.auth.models import User, UserRole
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.maps.models import Map, MapLayer, MapShareToken
from app.modules.catalog.maps.schemas import MapLayerInput
from app.processing.raster.models import RasterAsset

logger = structlog.stdlib.get_logger(__name__)


class DatasetMeta(NamedTuple):
    """Metadata returned by get_dataset_meta — one row per dataset."""

    record_type: str | None
    title: str | None
    geometry_type: str | None
    table_name: str | None
    extent: object | None
    column_info: list | None
    feature_count: int | None
    sample_values: dict | None
    is_3d: bool | None


class LayerRow(NamedTuple):
    """One joined row from the map-layer SELECT in _fetch_layer_rows_ordered.

    Used by ``get_map_with_layers`` (read path) and ``update_map`` /
    ``duplicate_map`` (save path) to denormalize layer + record + dataset
    metadata into a single response.
    """

    layer: MapLayer
    title: str | None
    geometry_type: str | None
    table_name: str | None
    spatial_extent: object | None
    column_info: list | None
    feature_count: int | None
    sample_values: dict | None
    record_type: str | None
    is_3d: bool | None


async def check_map_ownership(map_obj: Map, user: User, db: AsyncSession) -> None:
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


async def get_dataset_meta(
    session: AsyncSession,
    dataset_id: uuid.UUID,
) -> DatasetMeta | None:
    """Fetch dataset metadata for building a layer response. Single query."""
    result = await session.execute(
        select(
            Record.record_type,
            Record.title,
            Dataset.geometry_type,
            Dataset.table_name,
            Record.spatial_extent,
            Dataset.column_info,
            Dataset.feature_count,
            Dataset.sample_values,
            Dataset.is_3d,
        )
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    row = result.one_or_none()
    return DatasetMeta(*row) if row else None


def generate_default_style(geometry_type: str | None) -> dict[str, dict]:
    """Generate MapLibre-native default paint/layout for a geometry type.

    Returns {"paint": {...}, "layout": {...}} ready to store in map_layers.
    """
    gt = (geometry_type or "").upper()
    if not gt:
        logger.warning(
            "generate_default_style called with null geometry_type; defaulting to fill"
        )

    if "POINT" in gt:
        return {
            "paint": {
                "circle-radius": 5,
                "circle-color": "#3b82f6",
                "circle-stroke-color": "#1d4ed8",
                "circle-stroke-width": 1,
                "circle-opacity": 1,
            },
            "layout": {},
        }
    elif "LINE" in gt:
        return {
            "paint": {
                "line-color": "#3b82f6",
                "line-width": 2,
                "line-opacity": 1,
            },
            "layout": {
                "line-cap": "round",
                "line-join": "round",
            },
        }
    else:
        # Default to fill (polygon, geometry collection, unknown)
        return {
            "paint": {
                "fill-color": "#3b82f6",
                "fill-opacity": 0.3,
                # GeoLens-private keys consumed by the frontend layer-adapter;
                # not valid MapLibre paint properties.
                "_outline-color": "#1d4ed8",
                "_outline-width": 1,
            },
            "layout": {},
        }


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


async def _fetch_layer_rows_ordered(
    session: AsyncSession, map_id: uuid.UUID
) -> list[LayerRow]:
    """Fetch the joined layer-row tuples for a map, ordered by sort_order.

    Map has no relationship() to MapLayer, so the .order_by(MapLayer.sort_order)
    clause MUST live in the explicit SELECT — there is no relationship-level
    ordering to leverage.
    """
    stmt = (
        select(
            MapLayer,
            Record.title,
            Dataset.geometry_type,
            Dataset.table_name,
            Record.spatial_extent,
            Dataset.column_info,
            Dataset.feature_count,
            Dataset.sample_values,
            Record.record_type,
            Dataset.is_3d,
        )
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(MapLayer.map_id == map_id)
        .order_by(MapLayer.sort_order)
    )
    result = await session.execute(stmt)
    return [LayerRow(*row) for row in result.all()]


async def _resolve_save_response_metadata(
    session: AsyncSession, map_obj: Map
) -> tuple[str | None, str | None, datetime | None]:
    """Resolve forked_from_name + owner_username + DB-side updated_at via one LEFT JOIN.

    One atomic query (matches the pre-PERF-6 get_map_with_layers semantics
    under READ COMMITTED). Used by update_map / duplicate_map where map_obj
    is already in-session — get_map_with_layers issues its own combined
    query inline to keep the read path at 2 queries total.

    ``Map.updated_at`` is included so callers don't need a separate
    ``session.refresh(map_obj)`` round-trip to read the DB-side
    ``onupdate=func.now()`` value (PERF: saves one round-trip per save).
    """
    ForkedMap = aliased(Map)
    stmt = (
        select(ForkedMap.name, User.username, Map.updated_at)
        .select_from(Map)
        .outerjoin(ForkedMap, Map.forked_from == ForkedMap.id)
        .outerjoin(User, Map.created_by == User.id)
        .where(Map.id == map_obj.id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None, None, None
    return row[0], row[1], row[2]


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


def _apply_map_visibility_filter(
    stmt: Select,
    user_id: uuid.UUID | None,
    is_admin: bool,
) -> Select:
    """Apply RBAC visibility filter to a Map query.

    - Admins see everything (no filter).
    - Authenticated users see: their own private maps + all internal + all public.
    - Anonymous users see public only.
    """
    if is_admin:
        return stmt
    if user_id is not None:
        return stmt.where(
            or_(
                Map.created_by == user_id,
                Map.visibility.in_(["internal", "public"]),
            )
        )
    return stmt.where(Map.visibility == "public")


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
    widgets: list[str] | None = None,
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

    # Update scalar fields (skip None values)
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
        "widgets": widgets,
    }
    for key, value in scalar_fields.items():
        if value is not None:
            setattr(map_obj, key, value)

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


_COPY_SUFFIX_RE = re.compile(r"\s*\(copy(?:\s+(\d+))?\)\s*$")


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


async def bulk_check_dataset_access(
    session: AsyncSession,
    dataset_ids: list[uuid.UUID],
    user: User,
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


async def duplicate_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    user: User,
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


def _infer_layer_type(record_type: str | None) -> str:
    """Infer layer_type from record_type."""
    return (
        "raster_geolens"
        if record_type in ("raster_dataset", "vrt_dataset")
        else "vector_geolens"
    )


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

    layer = MapLayer(
        map_id=map_id,
        dataset_id=body.dataset_id,
        sort_order=body.sort_order,
        visible=body.visible,
        opacity=body.opacity,
        paint=paint,
        layout=layout,
        layer_type=resolved_layer_type,
        display_name=body.display_name,
        filter=body.filter,
        label_config=body.label_config,
        popup_config=body.popup_config.model_dump() if body.popup_config else None,
        style_config=body.style_config,
        show_in_legend=body.show_in_legend,
    )
    session.add(layer)
    await session.flush()
    return layer


async def remove_layer(
    session: AsyncSession,
    layer_id: uuid.UUID,
) -> bool:
    """Delete a map layer by ID. Returns True if deleted, False if not found."""
    result = await session.execute(delete(MapLayer).where(MapLayer.id == layer_id))
    # SQLAlchemy CursorResult exposes rowcount for DML; the async Result
    # type stub is less specific so mypy can't narrow it here.
    return result.rowcount > 0  # type: ignore[attr-defined]


async def validate_public_visibility(
    session: AsyncSession, map_id: uuid.UUID
) -> list[str]:
    """Return names of non-public datasets in this map. Empty = OK to publish."""
    stmt = (
        select(Record.title, Record.visibility)
        .select_from(MapLayer)
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(MapLayer.map_id == map_id)
        .where(Record.visibility != "public")
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def find_public_maps_using_dataset(
    session: AsyncSession, dataset_id: uuid.UUID
) -> list[str]:
    """Return names of public maps that contain the given dataset. Empty = safe to restrict."""
    stmt = (
        select(Map.name)
        .select_from(MapLayer)
        .join(Map, MapLayer.map_id == Map.id)
        .where(MapLayer.dataset_id == dataset_id)
        .where(Map.visibility == "public")
    )
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def create_share_token(
    session: AsyncSession,
    map_id: uuid.UUID,
    created_by: uuid.UUID,
    expires_at: datetime | None = None,
) -> MapShareToken:
    """Create a share token for a map. Reuses existing token if one exists. Does NOT commit."""
    # Check for existing token
    existing = await session.execute(
        select(MapShareToken).where(MapShareToken.map_id == map_id)
    )
    token_obj = existing.scalar_one_or_none()
    if token_obj is not None:
        # Update expiration if caller provided one
        if expires_at is not None:
            token_obj.expires_at = expires_at
        # Re-activate if previously revoked
        if not token_obj.is_active:
            token_obj.is_active = True
            raw_token = secrets.token_urlsafe(16)
            token_obj.token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            token_obj.token_hint = raw_token[:8]
            token_obj._raw_token = raw_token  # transient, not persisted
        return token_obj
    raw_token = secrets.token_urlsafe(16)
    token_obj = MapShareToken(
        map_id=map_id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        token_hint=raw_token[:8],
        created_by=created_by,
        expires_at=expires_at,
    )
    token_obj._raw_token = raw_token  # transient, not persisted
    session.add(token_obj)
    await session.flush()
    return token_obj


async def update_share_token(
    session: AsyncSession,
    map_id: uuid.UUID,
    expires_at: datetime | None,
) -> MapShareToken | None:
    """Update expiration on the active share token for a map. Returns None if no active token."""
    result = await session.execute(
        select(MapShareToken).where(
            MapShareToken.map_id == map_id,
            MapShareToken.is_active.is_(True),
        )
    )
    token_obj = result.scalar_one_or_none()
    if token_obj is None:
        return None
    token_obj.expires_at = expires_at
    return token_obj


async def get_active_share_token(
    session: AsyncSession,
    map_id: uuid.UUID,
) -> MapShareToken | None:
    """Return the active share token for a map, or None if no active token exists."""
    result = await session.execute(
        select(MapShareToken).where(
            MapShareToken.map_id == map_id,
            MapShareToken.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _validate_share_token(
    session: AsyncSession,
    token: str,
) -> MapShareToken | None | str:
    """Look up and validate a share token.

    Returns the MapShareToken on success, ``"expired"`` if revoked/expired,
    or ``None`` if the token does not exist.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await session.execute(
        select(MapShareToken).where(MapShareToken.token_hash == token_hash)
    )
    token_obj = result.scalar_one_or_none()
    if token_obj is None:
        return None
    if not token_obj.is_active:
        return "expired"
    if token_obj.expires_at is not None and token_obj.expires_at < datetime.now(
        timezone.utc
    ):
        return "expired"
    return token_obj


def _build_shared_layer_dict(
    layer: MapLayer,
    ds_name: str | None,
    ds_geom_type: str | None,
    ds_table_name: str | None,
    ds_column_info: list | None,
    ds_visibility: str | None,
    ds_record_type: str | None,
    ds_is_3d: bool | None,
    ds_feature_count: int | None,
    ds_is_dem: bool | None,
) -> tuple[dict, bool]:
    """Build a shared-layer response dict from a joined layer row.

    Returns ``(layer_dict, is_non_public)``.
    """
    is_public = ds_visibility == "public"
    if ds_record_type in ("raster_dataset", "vrt_dataset"):
        tile_url = f"/raster-tiles/{layer.dataset_id}/tiles/{{z}}/{{x}}/{{y}}.png"
    elif is_public:
        tile_url = f"/tiles/public/data.{ds_table_name}/{{z}}/{{x}}/{{y}}.pbf"
    else:
        tile_url = f"/tiles/data.{ds_table_name}/{{z}}/{{x}}/{{y}}.pbf"
    return {
        "dataset_id": str(layer.dataset_id),
        "dataset_name": ds_name,
        "display_name": layer.display_name,
        "table_name": ds_table_name,
        "geometry_type": ds_geom_type,
        "column_info": ds_column_info,
        "sort_order": layer.sort_order,
        "visible": layer.visible,
        "opacity": layer.opacity,
        "paint": layer.paint,
        "layout": layer.layout,
        "layer_type": layer.layer_type or "vector_geolens",
        "dataset_record_type": ds_record_type,
        "filter": layer.filter,
        "label_config": layer.label_config,
        "popup_config": layer.popup_config,
        "style_config": layer.style_config,
        "show_in_legend": layer.show_in_legend,
        "tile_url": tile_url,
        "is_dem": bool(ds_is_dem) if ds_is_dem else None,
        "is_3d": bool(ds_is_3d) if ds_is_3d else None,
        "feature_count": ds_feature_count,
    }, not is_public


async def get_shared_map(
    session: AsyncSession,
    token: str,
    user: User | None = None,
    user_roles: set[str] | None = None,
) -> tuple[dict, list[dict]] | str | None:
    """Fetch a shared map by token.

    Returns:
        tuple: (map_dict, layers) on success
        "expired": token found but expired or revoked
        None: token not found

    Applies visibility filtering based on the optional user/roles:
    - Anonymous: only public datasets
    - Authenticated: datasets visible per apply_visibility_filter()
    Tile URLs: public datasets use /tiles/public/, non-public use /tiles/ (auth required).
    """
    if user_roles is None:
        user_roles = set()

    token_obj = await _validate_share_token(session, token)
    if token_obj is None:
        return None
    if isinstance(token_obj, str):
        return token_obj  # "expired"

    # Single query: Map metadata + visible layers in one round trip.
    stmt = (
        select(
            Map,
            MapLayer,
            Record.title,
            Dataset.geometry_type,
            Dataset.table_name,
            Dataset.column_info,
            Record.visibility,
            Record.record_type,
            Dataset.is_3d,
            Dataset.feature_count,
            RasterAsset.is_dem,
        )
        .join(Map, Map.id == MapLayer.map_id)
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .outerjoin(RasterAsset, RasterAsset.dataset_id == Dataset.id)
        .where(MapLayer.map_id == token_obj.map_id, Map.visibility == "public")
        .order_by(MapLayer.sort_order)
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    layer_result = await session.execute(stmt)
    layer_rows = layer_result.all()

    if not layer_rows:
        # Map doesn't exist, is not public, or has no visible layers.
        # Fall back to map-only check to distinguish "not found" from "empty".
        map_obj = await get_map(session, token_obj.map_id)
        if map_obj is None or map_obj.visibility != "public":
            return None
        map_data = {
            "name": map_obj.name,
            "description": map_obj.description,
            "center_lng": map_obj.center_lng or 0.0,
            "center_lat": map_obj.center_lat or 0.0,
            "zoom": map_obj.zoom or 2.0,
            "bearing": map_obj.bearing,
            "pitch": map_obj.pitch,
            "basemap_style": map_obj.basemap_style,
            "show_basemap_labels": map_obj.show_basemap_labels,
            "has_non_public_layers": False,
        }
        return map_data, []

    has_non_public = False
    layers = []
    for (
        _map_obj,
        layer,
        ds_name,
        ds_geom_type,
        ds_table_name,
        ds_column_info,
        ds_visibility,
        ds_record_type,
        ds_is_3d,
        ds_feature_count,
        ds_is_dem,
    ) in layer_rows:
        layer_dict, is_non_public = _build_shared_layer_dict(
            layer,
            ds_name,
            ds_geom_type,
            ds_table_name,
            ds_column_info,
            ds_visibility,
            ds_record_type,
            ds_is_3d,
            ds_feature_count,
            ds_is_dem,
        )
        if is_non_public:
            has_non_public = True
        layers.append(layer_dict)

    map_row = layer_rows[0][0]  # Map ORM object — same for every row
    map_data = {
        "name": map_row.name,
        "description": map_row.description,
        "center_lng": map_row.center_lng or 0.0,
        "center_lat": map_row.center_lat or 0.0,
        "zoom": map_row.zoom or 2.0,
        "bearing": map_row.bearing,
        "pitch": map_row.pitch,
        "basemap_style": map_row.basemap_style,
        "show_basemap_labels": map_row.show_basemap_labels,
        "has_non_public_layers": has_non_public,
    }

    return map_data, layers


async def list_share_tokens(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 50,
    search: str | None = None,
    status_filter: str | None = None,
) -> tuple[list[dict], int]:
    """List all share tokens with map names and embed token counts for admin view."""
    from app.modules.embed_tokens.models import EmbedToken

    # Build base filter conditions.
    # Typed as the SQLAlchemy `ColumnElement[bool]` supertype so both
    # BinaryExpression (`col == val`) and combined OR expressions fit
    # without per-append type ignores.
    from sqlalchemy.sql import ColumnElement

    conditions: list[ColumnElement[bool]] = []
    if search:
        escaped = search.replace("%", r"\%").replace("_", r"\_")
        conditions.append(Map.name.ilike(f"%{escaped}%"))
    if status_filter == "active":
        conditions.append(MapShareToken.is_active.is_(True))
        conditions.append(
            or_(
                MapShareToken.expires_at.is_(None),
                MapShareToken.expires_at > func.now(),
            )
        )
    elif status_filter == "expired":
        conditions.append(MapShareToken.is_active.is_(True))
        conditions.append(MapShareToken.expires_at <= func.now())
    elif status_filter == "revoked":
        conditions.append(MapShareToken.is_active.is_(False))

    count_stmt = (
        select(func.count())
        .select_from(MapShareToken)
        .join(Map, MapShareToken.map_id == Map.id)
    )
    for cond in conditions:
        count_stmt = count_stmt.where(cond)
    total = (await session.execute(count_stmt)).scalar_one()

    embed_count_sub = (
        select(
            EmbedToken.map_id,
            func.count().label("embed_count"),
        )
        .where(EmbedToken.is_active.is_(True))
        .group_by(EmbedToken.map_id)
        .subquery()
    )

    stmt = (
        select(
            MapShareToken,
            Map.name.label("map_name"),
            func.coalesce(embed_count_sub.c.embed_count, 0).label("embed_token_count"),
            User.username.label("creator_username"),
        )
        .join(Map, MapShareToken.map_id == Map.id)
        .outerjoin(User, MapShareToken.created_by == User.id)
        .outerjoin(embed_count_sub, MapShareToken.map_id == embed_count_sub.c.map_id)
        .order_by(MapShareToken.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    for cond in conditions:
        stmt = stmt.where(cond)
    result = await session.execute(stmt)
    rows = result.all()

    tokens = []
    for token_obj, map_name, embed_token_count, creator_username in rows:
        tokens.append(
            {
                "id": token_obj.id,
                "map_id": token_obj.map_id,
                "map_name": map_name,
                "token": token_obj.token_hint,
                "is_active": token_obj.is_active,
                "expires_at": token_obj.expires_at,
                "created_at": token_obj.created_at,
                "created_by": creator_username,
                "embed_token_count": embed_token_count,
            }
        )
    return tokens, total


async def revoke_share_token(
    session: AsyncSession,
    token_id: uuid.UUID,
) -> MapShareToken | None:
    """Soft-revoke a share token by setting is_active=False. Returns token if found, None otherwise."""
    result = await session.execute(
        select(MapShareToken).where(MapShareToken.id == token_id)
    )
    token_obj = result.scalar_one_or_none()
    if token_obj is None:
        return None
    token_obj.is_active = False
    return token_obj


async def get_maps_for_dataset(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    user_roles: set[str] | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """Return maps containing a given dataset, filtered by RBAC visibility.

    - Admins see all maps.
    - Authenticated users see own maps + internal + public.
    - Anonymous (user_id is None) see public only.
    """
    if user_roles is None:
        user_roles = set()

    is_admin = "admin" in user_roles

    # Subquery for layer count per map
    layer_count_sq = (
        select(
            MapLayer.map_id,
            func.count(MapLayer.id).label("layer_count"),
        )
        .group_by(MapLayer.map_id)
        .subquery()
    )

    stmt = (
        select(
            Map,
            func.coalesce(layer_count_sq.c.layer_count, 0).label("layer_count"),
            User.username.label("created_by_username"),
        )
        .join(MapLayer, Map.id == MapLayer.map_id)
        .outerjoin(layer_count_sq, Map.id == layer_count_sq.c.map_id)
        .outerjoin(User, Map.created_by == User.id)
        .where(MapLayer.dataset_id == dataset_id)
        .distinct(Map.id)
        .order_by(Map.id, Map.updated_at.desc())
    )

    # RBAC filter (extracted helper — same logic also used by list_maps).
    stmt = _apply_map_visibility_filter(stmt, user_id, is_admin)

    # Total count before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    # Apply pagination
    stmt = stmt.offset(skip).limit(limit)
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


async def revoke_share_token_by_map(
    session: AsyncSession,
    map_id: uuid.UUID,
) -> bool:
    """Revoke all share tokens for a map. Returns True if any were revoked."""
    result = await session.execute(
        select(MapShareToken).where(
            MapShareToken.map_id == map_id,
            MapShareToken.is_active.is_(True),
        )
    )
    tokens = result.scalars().all()
    if not tokens:
        return False
    for t in tokens:
        t.is_active = False
    return True
