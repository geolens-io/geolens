"""Clearing the stored images of maps whose layers changed under them."""

import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

import structlog
from sqlalchemy import Row, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.service_crud import (
    discard_map_asset_objects,
    lock_map_for_asset_write,
)

logger = structlog.stdlib.get_logger(__name__)

_DATASET_DELETE_IMAGE_BUDGET_S = 2.0


async def clear_map_images(
    session: AsyncSession, map_id: uuid.UUID, locked: Row
) -> list[str]:
    """Point the map at no thumbnail or social card image without marking
    it edited. ``locked`` is the row ``lock_map_for_asset_write`` returned in
    this transaction. Does not commit.

    For a map whose layers no longer show a dataset its images may show,
    while readers are authorized against the datasets it shows now.
    Returns the keys the map pointed at, which the caller passes to
    ``discard_map_asset_objects`` once it has committed.
    """
    keys = [key for key in (locked.thumbnail_uri, locked.og_image_uri) if key]
    if keys:
        await session.execute(
            update(Map)
            .where(Map.id == map_id)
            .values(
                thumbnail_uri=None,
                og_image_uri=None,
                thumbnail_updated_at=datetime.now(UTC),
                updated_at=Map.updated_at,
            )
        )
    return keys


async def map_ids_drawing_dataset(
    session: AsyncSession, dataset_id: uuid.UUID
) -> tuple[uuid.UUID, ...]:
    """The ids of the maps with a layer on the dataset, read without locking them."""
    result = await session.scalars(
        select(MapLayer.map_id)
        .where(MapLayer.dataset_id == dataset_id)
        .distinct()
        .order_by(MapLayer.map_id)
    )
    return tuple(result)


async def clear_images_after_dataset_delete(
    session: AsyncSession, map_ids: Iterable[uuid.UUID]
) -> int:
    """Clear the stored images of maps that drew a deleted dataset, once the
    delete has committed, and return how many maps were cleared.

    Best effort: each map is cleared and committed in a transaction of its
    own, and all of them share one wait budget; once it is spent, a map that
    is held is skipped at once. A skipped or failed map is logged and keeps
    its images. Taking these rows inside the delete would deadlock with a
    builder save, which holds the map and then waits on the dataset. Call it
    last: a failure rolls the session back, which expires its instances.
    """
    ids = sorted(set(map_ids))
    if not ids:
        return 0
    deadline = time.monotonic() + _DATASET_DELETE_IMAGE_BUDGET_S
    cleared: list[tuple[uuid.UUID, list[str]]] = []
    try:
        with_images = list(
            await session.scalars(
                select(Map.id)
                .where(
                    Map.id.in_(ids),
                    or_(Map.thumbnail_uri.is_not(None), Map.og_image_uri.is_not(None)),
                )
                .order_by(Map.id)
            )
        )
    except Exception:  # broad: the delete has committed; try every map instead
        await session.rollback()
        with_images = ids
    for map_id in with_images:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        try:
            locked = await lock_map_for_asset_write(
                session, map_id, lock_timeout=f"{remaining_ms}ms"
            )
            keys = await clear_map_images(session, map_id, locked)
            await session.commit()
        except Exception:  # broad: the delete has committed; this map keeps them
            await session.rollback()
            logger.warning(
                "map_images_after_dataset_delete_skipped",
                map_id=str(map_id),
                exc_info=True,
            )
            continue
        if keys:
            cleared.append((map_id, keys))
    # Storage last, so no object round trip delays another map's clear.
    for map_id, keys in cleared:
        await discard_map_asset_objects(session, map_id, keys)
    return len(cleared)
