"""Map edit history recording and retrieval helpers."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.maps.models import MapEditHistoryEvent


def _actor_id(actor: Identity | None) -> uuid.UUID | None:
    return actor.id if actor is not None else None


def _actor_username(actor: Identity | None) -> str | None:
    return actor.username if actor is not None else None


async def record_map_history_event(
    session: AsyncSession,
    *,
    map_id: uuid.UUID,
    actor: Identity | None,
    target_type: str,
    action: str,
    summary: str,
    target_id: uuid.UUID | None = None,
    target_name: str | None = None,
    details: dict[str, Any] | None = None,
) -> MapEditHistoryEvent:
    """Add a map edit history row to the current transaction.

    ``created_at`` is the database's clock when the row is inserted, not the
    API host's and not the transaction's start, and always after the map's
    newest event, whatever time an older row carries or however the clock
    stepped. Writers record their event while holding the map row, so the
    times order the events as the lock did.
    """
    newest = (
        select(func.max(MapEditHistoryEvent.created_at))
        .where(MapEditHistoryEvent.map_id == map_id)
        .scalar_subquery()
    )
    event = MapEditHistoryEvent(
        map_id=map_id,
        actor_id=_actor_id(actor),
        actor_username=_actor_username(actor),
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        action=action,
        summary=summary,
        details=jsonable_encoder(details or {}),
        created_at=func.greatest(
            func.clock_timestamp(),
            newest + literal_column("interval '1 microsecond'"),
        ),
    )
    session.add(event)
    await session.flush()
    return event


async def list_map_history(
    session: AsyncSession,
    map_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[MapEditHistoryEvent], int]:
    """Return newest-first map history events and total count."""
    total_result = await session.execute(
        select(func.count())
        .select_from(MapEditHistoryEvent)
        .where(MapEditHistoryEvent.map_id == map_id)
    )
    total = total_result.scalar_one()

    events_result = await session.execute(
        select(MapEditHistoryEvent)
        .where(MapEditHistoryEvent.map_id == map_id)
        .order_by(MapEditHistoryEvent.created_at.desc(), MapEditHistoryEvent.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(events_result.scalars().all()), total
