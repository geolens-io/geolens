"""Map sharing, public viewer, and dataset-in-use helpers."""

import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.edition import is_enterprise
from app.core.identity import Identity
from app.modules.auth.models import User
from app.modules.catalog._ilike import escape_ilike
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.maps.models import Map, MapLayer, MapShareToken
from app.modules.catalog.maps.schemas import ADVANCED_SHARING_ERROR
from app.modules.catalog.maps.service_crud import get_map
from app.modules.catalog.maps.service_shared import (
    _apply_map_visibility_filter,
    _extract_dem_vertical_units,
)
from app.modules.embed_tokens.models import EmbedToken
from app.platform.extensions import get_catalog_port


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
    if not is_enterprise() and expires_at is not None:
        raise ValueError(ADVANCED_SHARING_ERROR)

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
            # SEC-10 / L-60: 32-byte (256-bit) entropy parity with embed tokens.
            # Existing 16-byte tokens already in the DB continue to validate
            # — the lookup is by sha256 hash, not raw length.
            raw_token = secrets.token_urlsafe(32)
            token_obj.token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            token_obj.token_hint = raw_token[:8]
            token_obj._raw_token = raw_token  # transient, not persisted
        return token_obj
    # 32 bytes per SEC-10
    raw_token = secrets.token_urlsafe(32)
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
    if not is_enterprise() and expires_at is not None:
        raise ValueError(ADVANCED_SHARING_ERROR)

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
    ds_dem_vertical_units: str | None,
) -> tuple[dict, bool]:
    """Build a shared-layer response dict from a joined layer row.

    Returns ``(layer_dict, is_non_public)``.
    """
    is_public = ds_visibility == "public"
    if ds_record_type in ("raster_dataset", "vrt_dataset"):
        tile_url = f"/raster-tiles/{layer.dataset_id}/tiles/{{z}}/{{x}}/{{y}}.png"
    else:
        # Phase 273 SEC-16 / L-62: previous public-vs-private branch produced
        # `/tiles/public/data.{table_name}/...`, but no such route is mounted
        # — `app.processing.tiles.router` only registers the prefix `/tiles`
        # with a catch-all `{table_path:path}/{z}/{x}/{y}.pbf` whose handler
        # rejects anything not starting with literal `data.`. The auth path
        # for public datasets is handled inside that single endpoint
        # (visibility check + HMAC-or-anonymous), so all consumers (raster
        # excluded) can use one URL. The `is_public` flag is still returned
        # alongside the dict (`not is_public` below) — leaving it bound here.
        tile_url = f"/tiles/data.{ds_table_name}/{{z}}/{{x}}/{{y}}.pbf"
    return {
        "id": str(layer.id),
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
        "dem_vertical_units": ds_dem_vertical_units,
        "is_3d": bool(ds_is_3d) if ds_is_3d else None,
        "feature_count": ds_feature_count,
    }, not is_public


async def get_shared_map(
    session: AsyncSession,
    token: str,
    user: Identity | None = None,
    user_roles: set[str] | None = None,
) -> tuple[dict, list[dict], list[str] | None] | str | None:
    """Fetch a shared map by token.

    Returns:
        tuple: (map_dict, layers, allowed_origins) on success.
            ``allowed_origins`` is the active EmbedToken.allowed_origins for the
            map (``None`` when no active EmbedToken exists; ``[]`` when the
            token exists but no origins are configured). Callers use this to
            emit a ``Content-Security-Policy: frame-ancestors`` header on the
            API response (SEC-S08 / Phase 1062-05).
        "expired": token found but expired or revoked
        None: token not found

    Applies visibility filtering based on the optional user/roles:
    - Anonymous: only public datasets
    - Authenticated: datasets visible per apply_visibility_filter()
    Tile URLs: vector datasets use /tiles/data.{table_name}/... — the tile
    endpoint internally distinguishes public (anonymous-allowed) vs
    private (HMAC-signature-required) at request time. Raster datasets
    use /raster-tiles/{dataset_id}/tiles/... (separate router). See
    Phase 273 SEC-16 for prior `/tiles/public/...` URL hint cleanup.
    """
    if user_roles is None:
        user_roles = set()

    token_obj = await _validate_share_token(session, token)
    if token_obj is None:
        return None
    if isinstance(token_obj, str):
        return token_obj  # "expired"

    # SEC-S08 (Phase 1062-05): query the active EmbedToken for this map to
    # surface allowed_origins. The router uses this to emit a per-token
    # frame-ancestors CSP header. ShareToken and EmbedToken are distinct
    # primitives — a map may have one without the other.
    #
    # CR-04 (Phase 1062 review): include non-expiring tokens (expires_at IS NULL)
    # in the query. In PostgreSQL, NULL > now() evaluates to NULL (falsy), so
    # the original `expires_at > func.now()` predicate silently excluded
    # non-expiring EmbedTokens, causing the CSP header to fall back to
    # "frame-ancestors 'self'" and breaking embed framing for community-edition
    # tokens (which default to no expiry).
    embed_stmt = (
        select(EmbedToken.allowed_origins)
        .where(
            EmbedToken.map_id == token_obj.map_id,
            EmbedToken.is_active == True,  # noqa: E712
            or_(
                EmbedToken.expires_at.is_(None),
                EmbedToken.expires_at > func.now(),
            ),
        )
        .order_by(EmbedToken.created_at.desc())
        .limit(1)
    )
    allowed_origins: list[str] | None = (
        await session.execute(embed_stmt)
    ).scalar_one_or_none()

    RasterAsset = get_catalog_port().raster_asset_orm_class()

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
            RasterAsset.band_info,
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
            "basemap_config": map_obj.basemap_config,
            "terrain_config": map_obj.terrain_config,
            "has_non_public_layers": False,
        }
        return map_data, [], allowed_origins

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
        ds_band_info,
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
            _extract_dem_vertical_units(ds_band_info),
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
        "basemap_config": map_row.basemap_config,
        "terrain_config": map_row.terrain_config,
        "has_non_public_layers": has_non_public,
    }

    return map_data, layers, allowed_origins


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
        conditions.append(Map.name.ilike(f"%{escape_ilike(search)}%", escape="\\"))
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
