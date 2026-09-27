"""Stable map-owned query contracts for cross-domain sharing consumers.

Embed-token code uses these scalar/DTO helpers instead of importing catalog ORM
models. Keeping this module independent from the maps service facade also
prevents a maps-sharing/embed-token import cycle.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.text import escape_ilike
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.maps.models import Map, MapLayer
from app.core.public_urls import (
    get_public_api_url,
    get_public_app_url,
    join_public_url,
)

if TYPE_CHECKING:
    from starlette.requests import Request


class MapEmbedScope(NamedTuple):
    """Current layer snapshot and tenant binding for an embed token."""

    dataset_ids: tuple[uuid.UUID, ...]
    tenant_id: uuid.UUID | None


async def can_read_every_map_dataset(
    session: AsyncSession, map_obj: Map, user: Identity | None
) -> bool:
    """Whether ``user`` can read every dataset the map draws, terrain included."""
    dataset_ids = set(
        (
            await session.execute(
                select(MapLayer.dataset_id).where(MapLayer.map_id == map_obj.id)
            )
        ).scalars()
    )
    terrain = map_obj.terrain_config if isinstance(map_obj.terrain_config, dict) else {}
    if terrain.get("enabled") and terrain.get("source_dataset_id"):
        dataset_ids.add(uuid.UUID(str(terrain["source_dataset_id"])))
    if not dataset_ids:
        return True
    user_roles = await get_user_roles(session, user) if user is not None else set()
    stmt = (
        select(Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id.in_(dataset_ids))
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    return dataset_ids <= set((await session.execute(stmt)).scalars())


async def get_share_card_image_url(
    session: AsyncSession,
    request: "Request",
    map_obj: Map,
) -> str:
    """Resolve a card image against the correct public API or app root.

    Crawlers are anonymous, so a stored image is used only when an anonymous
    caller can read every dataset the map draws.
    """
    if (map_obj.og_image_uri or map_obj.thumbnail_uri) and (
        await can_read_every_map_dataset(session, map_obj, None)
    ):
        api_base = await get_public_api_url(session, request=request)
        kind = "og-image" if map_obj.og_image_uri else "thumbnail"
        return join_public_url(api_base, f"/maps/{map_obj.id}/{kind}/")
    app_base = await get_public_app_url(session, request=request)
    return join_public_url(app_base, "/og-image.png")


async def get_map_embed_scope(
    session: AsyncSession, map_id: uuid.UUID
) -> MapEmbedScope | None:
    """Return the current dataset ids and tenant id for a map."""
    result = await session.execute(
        select(Map.tenant_id, MapLayer.dataset_id)
        .outerjoin(MapLayer, MapLayer.map_id == Map.id)
        .where(Map.id == map_id)
        .order_by(MapLayer.sort_order)
    )
    rows = result.all()
    if not rows:
        return None
    return MapEmbedScope(
        dataset_ids=tuple(row.dataset_id for row in rows if row.dataset_id is not None),
        tenant_id=rows[0].tenant_id,
    )


async def map_contains_dataset(
    session: AsyncSession, map_id: uuid.UUID, dataset_id: uuid.UUID
) -> bool:
    """Return whether a dataset is still a live layer on a map."""
    result = await session.execute(
        select(MapLayer.id)
        .where(MapLayer.map_id == map_id, MapLayer.dataset_id == dataset_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def find_map_ids_by_name(session: AsyncSession, search: str) -> set[uuid.UUID]:
    """Resolve map ids matching a literal, case-insensitive name fragment."""
    pattern = f"%{escape_ilike(search)}%".lower()
    result = await session.execute(
        select(Map.id).where(func.lower(Map.name).like(pattern, escape="\\"))
    )
    return set(result.scalars().all())


async def get_map_names(
    session: AsyncSession, map_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Return map names for an embed-token administration page."""
    if not map_ids:
        return {}
    result = await session.execute(select(Map.id, Map.name).where(Map.id.in_(map_ids)))
    return {row.id: row.name for row in result.all()}
