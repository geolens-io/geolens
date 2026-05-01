"""Dataset relationship operations (extracted from service.py — Phase 224)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import DatasetRelationship
    from app.modules.catalog.datasets.domain.schemas import (
        DatasetRelationshipCreate,
    )

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    DatasetGrant,
    Record,
)

logger = structlog.stdlib.get_logger(__name__)

__all__ = [
    "auto_detect_relationships",
    "create_relationship",
    "delete_relationship",
    "get_related_datasets",
    "get_related_records",
    "list_relationships",
]


async def get_related_datasets(
    db: AsyncSession,
    dataset_id: uuid.UUID,
    user: Identity | None,
    user_roles: set[str],
    *,
    limit: int = 5,
) -> list[dict]:
    """Return top-N datasets similar to the given dataset by embedding cosine distance.

    Returns an empty list when the dataset has no embedding or no neighbors
    exceed the similarity threshold (0.3, i.e. cosine distance <= 0.7).
    Results are RBAC-filtered to only include datasets visible to the requesting user.
    """
    from app.processing.embeddings.models import RecordEmbedding

    try:
        # Get the dataset's record_id
        record_id_row = (
            await db.execute(select(Dataset.record_id).where(Dataset.id == dataset_id))
        ).first()
        if record_id_row is None:
            return []
        record_id = record_id_row[0]

        # Get the dataset's embedding for distance calculation
        emb_row = (
            await db.execute(
                select(RecordEmbedding.embedding)
                .where(RecordEmbedding.record_id == record_id)
                .limit(1)
            )
        ).first()
        if emb_row is None:
            return []
        embedding = emb_row[0]

        # Find nearest neighbors using shared helper (over-fetch for RBAC filtering)
        from app.processing.embeddings.helpers import get_nearest_record_ids

        neighbor_record_ids = await get_nearest_record_ids(
            db, record_id, limit=limit * 3, max_distance=0.7
        )

        if not neighbor_record_ids:
            return []

        # Compute distances for the neighbors (needed for similarity score).
        # Tune HNSW recall (default ef_search=40 may miss relevant matches).
        from app.processing.embeddings.helpers import set_hnsw_recall

        await set_hnsw_recall(db)
        nn_dist_stmt = select(
            RecordEmbedding.record_id,
            RecordEmbedding.embedding.cosine_distance(embedding).label("distance"),
        ).where(RecordEmbedding.record_id.in_(neighbor_record_ids))
        nn_dist_result = await db.execute(nn_dist_stmt)
        neighbor_map = {r.record_id: r.distance for r in nn_dist_result.all()}

        # Join to Dataset + Record to get metadata, apply visibility filter.
        # Use a fresh local `ds_stmt` so mypy re-infers `Dataset` as the row
        # type (the earlier `select(Dataset.record_id)` bound `ds_result` to
        # `Result[UUID]` which leaked into the reassignment).
        ds_stmt = (
            select(Dataset)
            .join(Record, Dataset.record_id == Record.id)
            .where(Record.id.in_(neighbor_record_ids))
            .options(joinedload(Dataset.record))
        )
        ds_stmt = apply_visibility_filter(
            ds_stmt, user, user_roles, Record, DatasetGrant
        )
        dataset_result = await db.execute(ds_stmt)
        datasets = list(dataset_result.scalars().unique().all())

        # Build response items sorted by similarity (descending). `similarity`
        # is always a float (the list is only appended to when distance is
        # not None), but mypy widens the dict value type to the union of all
        # keys; pin it on the sort key to keep the lambda return typed.
        items: list[dict] = []
        for ds in datasets:
            distance = neighbor_map.get(ds.record_id)
            if distance is not None:
                items.append(
                    {
                        "id": str(ds.id),
                        "name": ds.record.title,
                        "geometry_type": ds.geometry_type,
                        "similarity": round(1.0 - float(distance), 4),
                        "record_type": ds.record.record_type if ds.record else None,
                        "feature_count": ds.feature_count,
                    }
                )

        items.sort(key=lambda x: float(x["similarity"]), reverse=True)
        return items[:limit]

    except Exception:
        logger.exception("Error fetching related datasets for %s", dataset_id)
        return []


# ---------------------------------------------------------------------------
# Dataset FK relationships
# ---------------------------------------------------------------------------


async def create_relationship(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    rel: "DatasetRelationshipCreate",
) -> "DatasetRelationship":
    """Create FK relationship from source dataset to target dataset."""
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    obj = DatasetRelationship(
        source_dataset_id=dataset_id,
        target_dataset_id=rel.target_dataset_id,
        source_column=rel.source_column,
        target_column=rel.target_column,
        label=rel.label,
    )
    session.add(obj)
    await session.flush()
    await session.refresh(obj)
    return obj


async def list_relationships(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int | None = None,
) -> list:
    """List FK relationships where this dataset is the source.

    Joins with records table to include target_dataset_title. Supports
    optional ``skip``/``limit`` pagination (PERF-N16) to bound response
    size for datasets with hundreds of auto-detected relationships.
    """
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    stmt = (
        select(DatasetRelationship, Record.title)
        .outerjoin(Record, DatasetRelationship.target_dataset_id == Record.id)
        .where(DatasetRelationship.source_dataset_id == dataset_id)
        .order_by(DatasetRelationship.created_at)
    )
    if skip:
        stmt = stmt.offset(skip)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    rows = result.all()
    items = []
    for rel, title in rows:
        items.append(
            {
                "id": rel.id,
                "source_dataset_id": rel.source_dataset_id,
                "target_dataset_id": rel.target_dataset_id,
                "source_column": rel.source_column,
                "target_column": rel.target_column,
                "relationship_type": rel.relationship_type,
                "label": rel.label,
                "target_dataset_title": title,
            }
        )
    return items


async def delete_relationship(
    session: AsyncSession,
    relationship_id: uuid.UUID,
) -> None:
    """Delete a relationship by ID."""
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    result = await session.execute(
        select(DatasetRelationship).where(DatasetRelationship.id == relationship_id)
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise ValueError("Relationship not found")
    await session.delete(obj)
    await session.flush()


# Primary-key column names to exclude from FK candidate detection
_PK_COLUMN_NAMES = {"gid", "ogc_fid", "fid", "objectid", "id"}


async def auto_detect_relationships(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    column_info: list[dict],
) -> list:
    """Auto-detect FK relationships based on *_id column name matching.

    For each column ending with ``_id`` (excluding common PK names), look for
    other datasets that have an attribute with the same name marked as
    ``semantic_role='identifier'``.  When a match is found a
    ``DatasetRelationship`` row is created (idempotently via ON CONFLICT DO
    NOTHING on the existing unique constraint).
    """
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    candidates = [
        col["name"]
        for col in column_info
        if col["name"].endswith("_id") and col["name"].lower() not in _PK_COLUMN_NAMES
    ]
    if not candidates:
        return []

    # PERF-N4: collapse the previous per-candidate loop (N queries for the
    # identifier match + N queries for the existence check) into two bulk
    # queries using IN (...). For a dataset with 30 *_id candidates that's
    # 60 round trips → 2 round trips.
    match_result = await session.execute(
        select(
            AttributeMetadata.field_name,
            Dataset.record_id,
        )
        .join(Dataset, AttributeMetadata.dataset_id == Dataset.id)
        .where(
            AttributeMetadata.field_name.in_(candidates),
            AttributeMetadata.semantic_role == "identifier",
            Dataset.record_id != record_id,  # skip self-references
        )
    )
    # Group matches by column name so we can produce one relationship per
    # (source_column, target_record_id).
    matches_by_col: dict[str, list[uuid.UUID]] = {}
    for field_name, target_record_id in match_result.all():
        matches_by_col.setdefault(field_name, []).append(target_record_id)

    if not matches_by_col:
        return []

    # Pre-fetch existing relationships in one query so the idempotency check
    # doesn't require another round trip per candidate match.
    existing_result = await session.execute(
        select(
            DatasetRelationship.source_column,
            DatasetRelationship.target_dataset_id,
        ).where(
            DatasetRelationship.source_dataset_id == record_id,
            DatasetRelationship.source_column.in_(matches_by_col.keys()),
        )
    )
    existing_keys: set[tuple[str, uuid.UUID]] = {
        (col, tgt) for col, tgt in existing_result.all()
    }

    created: list[DatasetRelationship] = []
    for col_name, target_record_ids in matches_by_col.items():
        for target_record_id in target_record_ids:
            if (col_name, target_record_id) in existing_keys:
                continue
            obj = DatasetRelationship(
                source_dataset_id=record_id,
                target_dataset_id=target_record_id,
                source_column=col_name,
                target_column=col_name,
                label=None,
            )
            session.add(obj)
            created.append(obj)
            existing_keys.add(
                (col_name, target_record_id)
            )  # avoid dup if same col/target

    if created:
        await session.flush()
        logger.info(
            "Auto-detected %d FK relationship(s) for dataset %s",
            len(created),
            dataset_id,
        )

    return created


async def get_related_records(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    feature_gid: int,
    relationship_id: uuid.UUID,
    *,
    limit: int = 50,
    after: int = 0,
) -> dict:
    """Get related records for a feature via FK relationship.

    Looks up the FK value in the source table, then queries the target table
    for matching rows.
    """
    import re as _re

    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    # 1. Load relationship
    result = await session.execute(
        select(DatasetRelationship).where(DatasetRelationship.id == relationship_id)
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        raise ValueError("Relationship not found")

    # 2. Load source dataset to get table_name
    # Deferred import to avoid circular dependency: service.py re-exports
    # symbols from this module, so we cannot import get_dataset at module
    # top level. Function-local import matches the established pattern in
    # this file (see DatasetRelationship imports above).
    from app.modules.catalog.datasets.domain.service import get_dataset

    source_ds = await get_dataset(session, dataset_id)
    if source_ds is None:
        raise ValueError("Source dataset not found")

    # 3. Load target dataset to get table_name
    # target_dataset_id points to a Record, need to find its Dataset
    target_result = await session.execute(
        select(Dataset).where(Dataset.record_id == rel.target_dataset_id)
    )
    target_ds = target_result.scalar_one_or_none()
    if target_ds is None:
        raise ValueError("Target dataset not found")

    # Validate column names
    safe_col = _re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    if not safe_col.match(rel.source_column) or not safe_col.match(rel.target_column):
        raise ValueError("Invalid column name in relationship")

    # 4. Get FK value from source table
    fk_result = await session.execute(
        text(
            f"SELECT {rel.source_column} FROM data.{source_ds.table_name} WHERE gid = :gid"
        ).bindparams(gid=feature_gid)
    )
    fk_value = fk_result.scalar_one_or_none()
    if fk_value is None:
        return {"rows": [], "approximate_total": 0, "next_cursor": None, "columns": []}

    # 5. Query target table for matching rows
    count_result = await session.execute(
        text(
            f"SELECT COUNT(*) FROM data.{target_ds.table_name} "
            f"WHERE {rel.target_column} = :fk_val"
        ).bindparams(fk_val=fk_value)
    )
    total = count_result.scalar_one()

    rows_result = await session.execute(
        text(
            f"SELECT gid, to_jsonb(t.*) - 'gid' - 'geom' - 'geom_4326' AS properties "
            f"FROM data.{target_ds.table_name} t "
            f"WHERE t.{rel.target_column} = :fk_val "
            f"ORDER BY gid LIMIT :lim OFFSET :off"
        ).bindparams(fk_val=fk_value, lim=limit, off=after)
    )
    rows = [
        {"gid": row[0], **(row[1] if isinstance(row[1], dict) else {})}
        for row in rows_result.all()
    ]

    # Get column info for target table
    from app.processing.ingest.metadata import get_column_info

    columns = await get_column_info(session, target_ds.table_name)
    col_list = [{"name": c["name"], "type": c["type"]} for c in columns]

    next_cursor = after + limit if after + limit < total else None

    return {
        "rows": rows,
        "approximate_total": total,
        "next_cursor": next_cursor,
        "columns": col_list,
    }
