"""Collection search helpers for catalog search."""

from __future__ import annotations

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
) -> list[dict]:
    """Search collections by text and return with visible member counts.

    When q is empty, returns all collections (up to limit).
    """
    coll_stmt = select(Collection).limit(limit)

    if q and q.strip():
        q_like = f"%{q.strip().lower()}%"
        coll_stmt = coll_stmt.where(
            or_(
                func.lower(Collection.name).like(q_like),
                func.lower(func.coalesce(Collection.description, "")).like(q_like),
            )
        )
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
