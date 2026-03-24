"""Maps service layer.

Handles CRUD operations for maps and map layers, plus default style generation.
"""

import re
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.auth.visibility import apply_visibility_filter, get_user_roles
from app.datasets.models import Dataset, DatasetGrant, Record
from app.maps.models import Map, MapLayer, MapShareToken


async def check_map_ownership(map_obj, user: User, db: AsyncSession) -> None:
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


def generate_default_style(geometry_type: str | None) -> dict:
    """Generate MapLibre-native default paint/layout for a geometry type.

    Returns {"paint": {...}, "layout": {...}} ready to store in map_layers.
    """
    gt = (geometry_type or "").upper()

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
                "fill-outline-color": "#1d4ed8",
            },
            "layout": {},
        }


async def create_map(
    session: AsyncSession,
    name: str,
    description: str | None,
    created_by: uuid.UUID,
) -> Map:
    """Create a map. Does NOT commit."""
    map_obj = Map(
        name=name,
        description=description,
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
) -> tuple[Map | None, list[tuple]]:
    """Fetch map and its layers with dataset info.

    Returns (map, [(layer, dataset_name, geometry_type, table_name, extent, column_info, feature_count, sample_values), ...])
    or (None, []).
    """
    map_obj = await get_map(session, map_id)
    if map_obj is None:
        return None, []

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
        )
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(MapLayer.map_id == map_id)
        .order_by(MapLayer.sort_order)
    )
    result = await session.execute(stmt)
    rows = result.all()

    return map_obj, [tuple(row) for row in rows]


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
    - If user_id is provided without roles, falls back to owner-only (legacy).
    - search: ILIKE filter on name and description.
    - sort_by: name, created_at, updated_at (default). Unknown values fall back to updated_at.
    - sort_dir: asc or desc.
    - visibility: additional filter on Map.visibility (additive on top of RBAC).

    Returns (list of dicts with map fields + layer_count + created_by_username, total).
    """
    if user_roles is None:
        user_roles = set()

    is_admin = "admin" in user_roles

    # Build visibility filter (RBAC)
    def _apply_vis_filter(stmt):
        if is_admin:
            return stmt  # admins see everything
        if user_id is not None:
            return stmt.where(
                or_(
                    Map.created_by == user_id,
                    Map.visibility.in_(["internal", "public"]),
                )
            )
        # No user context -- legacy fallback (shouldn't happen in practice)
        return stmt

    # Build search/visibility filters (applied to both count and data queries)
    def _apply_extra_filters(stmt):
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
                "thumbnail": map_obj.thumbnail,
                "layer_count": row[1],
                "created_by_username": row[2],
                "created_at": map_obj.created_at,
                "updated_at": map_obj.updated_at,
            }
        )

    return maps, total


# Backward-compatible aliases
async def list_maps_by_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
    user_roles: set[str] | None = None,
) -> tuple[list[dict], int]:
    return await list_maps(session, skip, limit, user_id=user_id, user_roles=user_roles)


async def list_all_maps(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 20,
    user_roles: set[str] | None = None,
) -> tuple[list[dict], int]:
    return await list_maps(session, skip, limit, user_roles=user_roles)


async def update_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    **kwargs,
) -> Map:
    """Update map fields. If 'layers' key present, replace all layers.

    Raises ValueError if not found. Flushes but does NOT commit --
    callers must own the commit lifecycle.
    """
    result = await session.execute(select(Map).where(Map.id == map_id))
    map_obj = result.scalar_one_or_none()
    if map_obj is None:
        raise ValueError(f"Map {map_id} not found")

    # Extract layers before updating scalar fields
    layers = kwargs.pop("layers", None)

    # Update scalar fields (skip None values)
    for key, value in kwargs.items():
        if value is not None and hasattr(map_obj, key):
            setattr(map_obj, key, value)

    # Replace layers if provided
    if layers is not None:
        await _replace_layers(session, map_id, layers)

    await session.flush()
    await session.refresh(map_obj)
    return map_obj


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

    # Create new layers
    for layer_data in layers:
        dataset_id = layer_data["dataset_id"]

        # Resolve layer_type (auto-detect from record_type if not supplied)
        resolved_layer_type = await _resolve_layer_type(
            session, dataset_id, layer_data.get("layer_type")
        )

        # Look up dataset geometry type for default style
        ds_result = await session.execute(
            select(Dataset.geometry_type).where(Dataset.id == dataset_id)
        )
        geometry_type = ds_result.scalar_one_or_none()

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
            style_config=layer_data.get("style_config"),
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


async def _can_access_layer_dataset(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    user: User,
    user_roles: set[str],
) -> bool:
    """Check if user can access a dataset. Returns bool (no exceptions)."""
    if "admin" in user_roles:
        return True

    # Fetch the dataset with its record
    result = await session.execute(
        select(Record.visibility, Record.created_by)
        .join(Dataset, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    row = result.one_or_none()
    if row is None:
        return False

    visibility, created_by = row

    if visibility == "public":
        return True
    if visibility == "private":
        return created_by == user.id
    if visibility == "restricted":
        grant_result = await session.execute(
            select(DatasetGrant.dataset_id)
            .join(UserRole, DatasetGrant.role_id == UserRole.role_id)
            .where(
                DatasetGrant.dataset_id == dataset_id,
                UserRole.user_id == user.id,
            )
        )
        return grant_result.scalar_one_or_none() is not None

    return False


async def duplicate_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    user: User,
) -> tuple[Map, int]:
    """Deep-copy a map with RBAC-filtered layers. Does NOT commit.

    Returns (new_map, excluded_layer_count).
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
        center_lng=source.center_lng,
        center_lat=source.center_lat,
        zoom=source.zoom,
        bearing=source.bearing,
        pitch=source.pitch,
        basemap_style=source.basemap_style,
        thumbnail=None,
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

    excluded_count = 0
    for layer in layers:
        if not await _can_access_layer_dataset(
            session, layer.dataset_id, user, user_roles
        ):
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
            style_config=layer.style_config,
        )
        session.add(new_layer)

    await session.flush()
    return new_map, excluded_count


async def resolve_forked_from_name(
    session: AsyncSession, forked_from_id: uuid.UUID | None
) -> str | None:
    """Resolve the name of the source map. Returns None if deleted/missing."""
    if forked_from_id is None:
        return None
    result = await session.execute(select(Map.name).where(Map.id == forked_from_id))
    row = result.one_or_none()
    return row[0] if row else None


async def _resolve_layer_type(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    layer_type: str | None,
) -> str:
    """Resolve layer_type from explicit value or auto-detect from record_type.

    Returns 'raster_geolens' for raster_dataset records, 'vector_geolens' otherwise.
    """
    if layer_type is not None:
        return layer_type
    result = await session.execute(
        select(Record.record_type)
        .join(Dataset, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    record_type = result.scalar_one_or_none()
    return "raster_geolens" if record_type in ("raster_dataset", "vrt_dataset") else "vector_geolens"


async def add_layer(
    session: AsyncSession,
    map_id: uuid.UUID,
    dataset_id: uuid.UUID,
    sort_order: int = 0,
    visible: bool = True,
    opacity: float = 1.0,
    paint: dict | None = None,
    layout: dict | None = None,
    layer_type: str | None = None,
) -> MapLayer:
    """Add a layer to a map. Applies default style if paint/layout is None.

    Does NOT commit.
    """
    # Auto-detect layer_type from record_type if not provided
    resolved_layer_type = await _resolve_layer_type(session, dataset_id, layer_type)

    # Look up dataset geometry type
    ds_result = await session.execute(
        select(Dataset.geometry_type).where(Dataset.id == dataset_id)
    )
    geometry_type = ds_result.scalar_one_or_none()

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
        dataset_id=dataset_id,
        sort_order=sort_order,
        visible=visible,
        opacity=opacity,
        paint=paint,
        layout=layout,
        layer_type=resolved_layer_type,
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
    return result.rowcount > 0


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
        return token_obj
    token_obj = MapShareToken(
        map_id=map_id,
        token=secrets.token_urlsafe(16),
        created_by=created_by,
        expires_at=expires_at,
    )
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
    result = await session.execute(
        select(MapShareToken).where(
            MapShareToken.map_id == map_id,
            MapShareToken.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


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

    # Look up the share token
    result = await session.execute(
        select(MapShareToken).where(MapShareToken.token == token)
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

    # Load the map
    map_obj = await get_map(session, token_obj.map_id)
    if map_obj is None or map_obj.visibility != "public":
        return None

    # Load layers with dataset info, applying visibility filter
    stmt = (
        select(
            MapLayer,
            Record.title,
            Dataset.geometry_type,
            Dataset.table_name,
            Dataset.column_info,
            Record.visibility,
            Record.record_type,
        )
        .join(Dataset, MapLayer.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(MapLayer.map_id == map_obj.id)
        .order_by(MapLayer.sort_order)
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    layer_result = await session.execute(stmt)
    layer_rows = layer_result.all()

    has_non_public = False
    layers = []
    for (
        layer,
        ds_name,
        ds_geom_type,
        ds_table_name,
        ds_column_info,
        ds_visibility,
        ds_record_type,
    ) in layer_rows:
        is_public = ds_visibility == "public"
        if not is_public:
            has_non_public = True
        tile_url = (
            f"/tiles/public/data.{ds_table_name}/{{z}}/{{x}}/{{y}}.pbf"
            if is_public
            else f"/tiles/data.{ds_table_name}/{{z}}/{{x}}/{{y}}.pbf"
        )
        layers.append(
            {
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
                "style_config": layer.style_config,
                "tile_url": tile_url,
            }
        )

    map_data = {
        "name": map_obj.name,
        "description": map_obj.description,
        "center_lng": map_obj.center_lng or 0.0,
        "center_lat": map_obj.center_lat or 0.0,
        "zoom": map_obj.zoom or 2.0,
        "bearing": map_obj.bearing,
        "pitch": map_obj.pitch,
        "basemap_style": map_obj.basemap_style,
        "has_non_public_layers": has_non_public,
    }

    return map_data, layers


async def list_share_tokens(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[dict], int]:
    """List all share tokens with map names and embed token counts for admin view."""
    from app.embed_tokens.models import EmbedToken

    count_stmt = select(func.count()).select_from(MapShareToken)
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
    result = await session.execute(stmt)
    rows = result.all()

    tokens = []
    for token_obj, map_name, embed_token_count, creator_username in rows:
        tokens.append(
            {
                "id": token_obj.id,
                "map_id": token_obj.map_id,
                "map_name": map_name,
                "token": token_obj.token,
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
) -> bool:
    """Soft-revoke a share token by setting is_active=False. Returns True if found."""
    result = await session.execute(
        select(MapShareToken).where(MapShareToken.id == token_id)
    )
    token_obj = result.scalar_one_or_none()
    if token_obj is None:
        return False
    token_obj.is_active = False
    return True


async def get_maps_for_dataset(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    user_roles: set[str] | None = None,
) -> list[dict]:
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

    # RBAC filter
    if not is_admin:
        if user_id is not None:
            stmt = stmt.where(
                or_(
                    Map.created_by == user_id,
                    Map.visibility.in_(["internal", "public"]),
                )
            )
        else:
            stmt = stmt.where(Map.visibility == "public")

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
                "thumbnail": map_obj.thumbnail,
                "layer_count": row[1],
                "created_by_username": row[2],
                "created_at": map_obj.created_at,
                "updated_at": map_obj.updated_at,
            }
        )

    return maps


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
