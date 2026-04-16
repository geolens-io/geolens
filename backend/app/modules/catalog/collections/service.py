"""Collection service layer.

Handles CRUD operations for collections and collection-dataset membership.

# Module structure
# ----------------
# 1. Core CRUD: create, update, delete, get, list collections
# 2. Membership: add/remove datasets in/out of collections
# 3. Visibility-aware reads: list collections and their datasets respecting RBAC
# 4. Stats: dataset counts per collection
#
# # Commit semantics
# Functions that take a session generally **flush** but do not commit.
# Callers (router endpoints) own the commit boundary so multiple service
# calls can be batched into a single transaction. The exception is
# `update_collection`, which commits internally for legacy reasons — if you
# add a new write function, prefer the flush-only pattern.
"""

import json
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.auth.models import User
from app.modules.auth.visibility import apply_visibility_filter
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record


async def create_collection(
    session: AsyncSession,
    name: str,
    description: str | None,
    created_by: uuid.UUID,
) -> Collection:
    """Create a collection. Does NOT commit."""
    collection = Collection(
        name=name,
        description=description,
        created_by=created_by,
    )
    session.add(collection)
    await session.flush()
    return collection


async def update_collection(
    session: AsyncSession,
    collection_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Collection:
    """Update non-None fields. Raise ValueError if not found. Commits and refreshes."""
    result = await session.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if collection is None:
        raise ValueError(f"Collection {collection_id} not found")

    if name is not None:
        collection.name = name
    if description is not None:
        collection.description = description

    await session.commit()
    await session.refresh(collection)
    return collection


async def delete_collection(
    session: AsyncSession,
    collection_id: uuid.UUID,
) -> str:
    """Delete collection by ID. CASCADE handles collection_datasets.

    Raise ValueError if not found. Return collection name for audit.
    Does NOT commit.
    """
    result = await session.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    collection = result.scalar_one_or_none()
    if collection is None:
        raise ValueError(f"Collection {collection_id} not found")

    name = collection.name
    await session.delete(collection)
    return name


async def get_collection(
    session: AsyncSession,
    collection_id: uuid.UUID,
) -> Collection | None:
    """Fetch single collection by ID."""
    result = await session.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    return result.scalar_one_or_none()


async def list_collections(
    session: AsyncSession,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Collection], int]:
    """Paginated list of all collections ordered by created_at desc.

    Returns (collections, total_count).
    """
    count_stmt = select(func.count()).select_from(Collection)
    total_result = await session.execute(count_stmt)
    total_count = total_result.scalar_one()

    stmt = (
        select(Collection)
        .order_by(Collection.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    collections = list(result.scalars().all())

    return collections, total_count


async def add_datasets_to_collection(
    session: AsyncSession,
    collection_id: uuid.UUID,
    dataset_ids: list[uuid.UUID],
    added_by: uuid.UUID,
) -> int:
    """Insert CollectionDataset rows. Skip duplicates. Return count of newly added.

    Raise ValueError if collection not found. Does NOT commit.
    """
    collection = await get_collection(session, collection_id)
    if collection is None:
        raise ValueError(f"Collection {collection_id} not found")

    # Fetch all existing memberships in one query to avoid N+1
    existing_result = await session.execute(
        select(CollectionDataset.dataset_id).where(
            CollectionDataset.collection_id == collection_id,
            CollectionDataset.dataset_id.in_(dataset_ids),
        )
    )
    existing_ids = {row[0] for row in existing_result.all()}

    new_ids = [did for did in dataset_ids if did not in existing_ids]
    for dataset_id in new_ids:
        session.add(
            CollectionDataset(
                collection_id=collection_id,
                dataset_id=dataset_id,
                added_by=added_by,
            )
        )
    added_count = len(new_ids)

    if added_count > 0:
        await session.flush()

    return added_count


async def remove_dataset_from_collection(
    session: AsyncSession,
    collection_id: uuid.UUID,
    dataset_id: uuid.UUID,
) -> bool:
    """Delete the CollectionDataset row. Return True if deleted, False if not found.

    Does NOT commit.
    """
    result = await session.execute(
        delete(CollectionDataset).where(
            CollectionDataset.collection_id == collection_id,
            CollectionDataset.dataset_id == dataset_id,
        )
    )
    return result.rowcount > 0


async def get_collection_datasets(
    session: AsyncSession,
    collection_id: uuid.UUID,
    user: User | None,
    user_roles: set[str],
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[Dataset], int]:
    """Fetch datasets in a collection with RBAC visibility filtering.

    Returns (datasets, total). Ordered by sort_order then added_at.
    """
    base_stmt = (
        select(Dataset)
        .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(CollectionDataset.collection_id == collection_id)
    )
    filtered_stmt = apply_visibility_filter(
        base_stmt, user, user_roles, Record, DatasetGrant
    )

    # Total count
    count_stmt = select(func.count()).select_from(filtered_stmt.subquery())
    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one()

    # Paginated results ordered by sort_order then added_at
    paginated_stmt = (
        filtered_stmt.options(joinedload(Dataset.record))
        .order_by(CollectionDataset.sort_order, CollectionDataset.added_at)
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(paginated_stmt)
    datasets = list(result.scalars().all())

    return datasets, total


async def get_dataset_collections(
    session: AsyncSession,
    dataset_id: uuid.UUID,
) -> list[Collection]:
    """Reverse lookup -- which collections contain this dataset?

    No RBAC needed on collections themselves (organizational, not access-controlled).
    """
    stmt = (
        select(Collection)
        .join(CollectionDataset, CollectionDataset.collection_id == Collection.id)
        .where(CollectionDataset.dataset_id == dataset_id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def batch_collection_extents(
    session: AsyncSession,
    collection_ids: list[uuid.UUID],
    user: User | None,
    user_roles: set[str],
) -> dict[uuid.UUID, dict]:
    """Compute aggregated spatial and temporal extents for multiple collections in one query.

    Returns {collection_id: {"extent_bbox": [...] | None, "temporal_start": ..., "temporal_end": ...}}.
    Collections with zero visible datasets will not appear in the result dict.
    """
    if not collection_ids:
        return {}

    stmt = (
        select(
            CollectionDataset.collection_id,
            func.ST_AsGeoJSON(
                func.ST_Envelope(func.ST_Collect(Record.spatial_extent))
            ).label("bbox_geojson"),
            func.min(Record.temporal_start).label("temporal_start"),
            func.max(Record.temporal_end).label("temporal_end"),
        )
        .select_from(Dataset)
        .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(CollectionDataset.collection_id.in_(collection_ids))
        .group_by(CollectionDataset.collection_id)
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)

    result = await session.execute(stmt)
    rows = result.all()

    extents: dict[uuid.UUID, dict] = {}
    for row in rows:
        coll_id = row.collection_id
        extent_bbox = None
        if row.bbox_geojson is not None:
            geojson = json.loads(row.bbox_geojson)
            coords = geojson["coordinates"][0]
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            extent_bbox = [min(xs), min(ys), max(xs), max(ys)]
        extents[coll_id] = {
            "extent_bbox": extent_bbox,
            "temporal_start": row.temporal_start,
            "temporal_end": row.temporal_end,
        }
    return extents


async def batch_collection_dataset_counts(
    session: AsyncSession,
    collection_ids: list[uuid.UUID],
    user: User | None,
    user_roles: set[str],
) -> dict[uuid.UUID, int]:
    """Count visible datasets for multiple collections in one query.

    Returns {collection_id: count}. Collections with zero visible datasets
    will not appear in the result dict.
    """
    if not collection_ids:
        return {}

    stmt = (
        select(
            CollectionDataset.collection_id,
            func.count().label("dataset_count"),
        )
        .select_from(Dataset)
        .join(CollectionDataset, CollectionDataset.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(CollectionDataset.collection_id.in_(collection_ids))
        .group_by(CollectionDataset.collection_id)
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)

    result = await session.execute(stmt)
    return {row.collection_id: row.dataset_count for row in result.all()}
