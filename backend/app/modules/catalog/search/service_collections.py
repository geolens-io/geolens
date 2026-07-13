"""Collection search helpers for catalog search."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record


async def search_collections(
    session: AsyncSession,
    q: str,
    user: Identity | None,
    user_roles: set[str],
    *,
    limit: int = 10,
    offset: int = 0,
    collection_ids: Sequence[uuid.UUID] | None = None,
) -> list[dict]:
    """Search collections by text/ID and return with visible member counts.

    When q and collection_ids are absent, returns all collections (up to limit).
    """
    coll_stmt = (
        select(Collection)
        .order_by(Collection.name, Collection.id)
        .offset(offset)
        .limit(limit)
    )

    if q and q.strip():
        q_like = f"%{q.strip().lower()}%"
        coll_stmt = coll_stmt.where(
            or_(
                func.lower(Collection.name).like(q_like),
                func.lower(func.coalesce(Collection.description, "")).like(q_like),
            )
        )
    if collection_ids is not None:
        coll_stmt = coll_stmt.where(Collection.id.in_(collection_ids))
    coll_result = await session.execute(coll_stmt)
    collections = coll_result.scalars().all()

    if not collections:
        return []

    # Get visible member counts in a single query
    coll_ids = [c.id for c in collections]
    member_stmt = (
        select(
            CollectionDataset.collection_id,
            func.count().label("cnt"),
        )
        .select_from(CollectionDataset)
        .join(Dataset, CollectionDataset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(CollectionDataset.collection_id.in_(coll_ids))
    )
    member_stmt = apply_visibility_filter(
        member_stmt, user, user_roles, Record, DatasetGrant
    )
    member_stmt = member_stmt.group_by(CollectionDataset.collection_id)
    member_result = await session.execute(member_stmt)
    count_map = {row.collection_id: row.cnt for row in member_result.all()}

    return [
        {
            "id": str(c.id),
            "name": c.name,
            "description": c.description,
            "dataset_count": count_map.get(c.id, 0),
            "created_at": c.created_at.isoformat(),
        }
        for c in collections
    ]


async def count_collections(
    session: AsyncSession,
    q: str,
    *,
    collection_ids: Sequence[uuid.UUID] | None = None,
) -> int:
    """Count collections matching the text filter used by ``search_collections``.

    Page-independent total used to compute a stable ``numberMatched``. Mirrors
    the filters in ``search_collections`` exactly (no LIMIT, no visibility
    filter on the Collection rows themselves — consistent with the search).
    """
    count_stmt = select(func.count()).select_from(Collection)
    if q and q.strip():
        q_like = f"%{q.strip().lower()}%"
        count_stmt = count_stmt.where(
            or_(
                func.lower(Collection.name).like(q_like),
                func.lower(func.coalesce(Collection.description, "")).like(q_like),
            )
        )
    if collection_ids is not None:
        count_stmt = count_stmt.where(Collection.id.in_(collection_ids))
    return (await session.execute(count_stmt)).scalar_one()
