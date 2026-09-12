"""Dataset relationship operations."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import DatasetRelationship
    from app.modules.catalog.datasets.domain.schemas import (
        DatasetRelationshipCreate,
    )

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain._sql_safety import SAFE_COLUMN_NAME_RE
from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    DatasetGrant,
    Record,
)
from app.modules.catalog.datasets.domain.service_query import get_dataset
from app.platform.extensions import get_catalog_port, get_permission_extension

logger = structlog.stdlib.get_logger(__name__)

__all__ = [
    "auto_detect_relationships",
    "create_relationship",
    "delete_relationship",
    "get_related_datasets",
    "get_related_records",
    "get_relationship_datasets",
    "list_relationships",
]


async def _load_self_record_and_embedding(
    db: AsyncSession, dataset_id: uuid.UUID
) -> tuple[uuid.UUID, tuple[list[float], str, str | None]] | None:
    """Return (record_id, anchor) for the dataset, or None if either is absent.

    ``anchor`` is ``(embedding, model_name, config_fingerprint)``
    -- the vector alone doesn't say which model produced it, so every later
    read on this path compares inside that same space.

    Callers MUST gate visibility on the seed dataset BEFORE calling
    this -- the embedding read has no permission filter and would otherwise
    be a cosine-similarity oracle on private record content. The API router
    (datasets/api/router_data.py:list_related_datasets) already does this;
    a new caller must replicate that gate.
    """
    record_id_row = (
        await db.execute(select(Dataset.record_id).where(Dataset.id == dataset_id))
    ).first()
    if record_id_row is None:
        return None
    record_id = record_id_row[0]

    anchor = await get_catalog_port().get_record_embedding(db, record_id)
    if anchor is None:
        return None
    return record_id, anchor


async def _compute_neighbor_distances(
    db: AsyncSession,
    anchor: tuple[list[float], str, str | None],
    neighbor_record_ids: list[uuid.UUID],
) -> dict[uuid.UUID, float]:
    """Cosine-distance every neighbor against the seed embedding.

    Scored inside the anchor's own vector space -- a neighbour
    holding a row under another model would otherwise be scored off
    whichever row came back last, so the selection could be right while
    the printed similarity is wrong.
    """
    embedding, model_name, config_fingerprint = anchor
    return await get_catalog_port().get_embedding_distances(
        db,
        embedding,
        neighbor_record_ids,
        model_name=model_name,
        config_fingerprint=config_fingerprint,
    )


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
    try:
        seed = await _load_self_record_and_embedding(db, dataset_id)
        if seed is None:
            return []
        record_id, anchor = seed

        # Selection and scoring stay in one vector space AND on
        # one ROW -- the anchor read above is handed in rather than taken
        # again, since two reads under READ COMMITTED can straddle a worker
        # committing a newer row, ranking against one vector and scoring
        # against another.
        neighbor_record_ids = await get_catalog_port().get_nearest_record_ids(
            db, record_id, anchor=anchor, limit=limit * 3, max_distance=0.7
        )
        if not neighbor_record_ids:
            return []

        neighbor_map = await _compute_neighbor_distances(
            db, anchor, neighbor_record_ids
        )

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

    except Exception:  # broad: related-datasets is informational; any DB/scoring error degrades to empty list
        logger.exception("Error fetching related datasets for %s", dataset_id)
        return []


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


async def _visible_relationships(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    user: Identity | None,
    user_roles: set[str],
) -> list[dict]:
    """Return ALL relationships whose target the caller may access (pre-pagination).

    Visibility is enforced per-row (a public source must not leak the id/title of
    a private target), so this is the authoritative ``total`` basis: callers
    paginate the returned list with skip/limit.
    """
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    # FK columns store record_id, but dereferenceable endpoints resolve by
    # Dataset.id, so resolve the source's Dataset.id here (dataset_id is its
    # record_id). Create-input still takes target_dataset_id as a
    # record_id -- intentional asymmetry, unchanged here.
    source_dataset_id = (
        await session.execute(select(Dataset.id).where(Dataset.record_id == dataset_id))
    ).scalar_one_or_none()

    # Inner-join Dataset so relationships whose target has no backing
    # Dataset are dropped (fail-closed).
    stmt = (
        select(DatasetRelationship, Dataset, Record.title)
        .join(Dataset, DatasetRelationship.target_dataset_id == Dataset.record_id)
        .join(Record, Dataset.record_id == Record.id)
        .where(DatasetRelationship.source_dataset_id == dataset_id)
        .order_by(DatasetRelationship.created_at)
    )
    result = await session.execute(stmt)
    rows = result.all()

    permission_ext = get_permission_extension()
    visible_items: list[dict] = []
    for rel, target_ds, title in rows:
        if not await permission_ext.can_access_dataset(
            session, target_ds, target_ds.id, user, user_roles=user_roles
        ):
            continue
        visible_items.append(
            {
                "id": rel.id,
                # Emit dereferenceable Dataset.id, not the stored record_id.
                "source_dataset_id": source_dataset_id,
                "target_dataset_id": target_ds.id,
                "source_column": rel.source_column,
                "target_column": rel.target_column,
                "relationship_type": rel.relationship_type,
                "label": rel.label,
                "target_dataset_title": title,
            }
        )
    return visible_items


async def list_relationships(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    user: Identity | None = None,
    user_roles: set[str] | None = None,
    skip: int = 0,
    limit: int | None = None,
) -> list:
    """List FK relationships where this dataset is the source.

    Per-row visibility filtering means a public source never leaks a private
    target's id/title; ``skip``/``limit`` apply to the visible subset.
    Thin wrapper over :func:`list_relationships_with_total` (drops the count).
    """
    page, _ = await list_relationships_with_total(
        session, dataset_id, user=user, user_roles=user_roles, skip=skip, limit=limit
    )
    return page


async def list_relationships_with_total(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    *,
    user: Identity | None = None,
    user_roles: set[str] | None = None,
    skip: int = 0,
    limit: int | None = None,
) -> tuple[list, int]:
    """Return paginated relationships plus the total visible count.

    Returns ``(page_items, total)`` where ``total`` is the number of visible
    relationships before ``skip``/``limit`` so callers can detect more pages.
    Mirrors the ``{<entity>: [...], total: N}`` list-envelope convention.
    """
    visible_items = await _visible_relationships(
        session, dataset_id, user=user, user_roles=user_roles or set()
    )
    total = len(visible_items)
    page = visible_items
    if skip:
        page = page[skip:]
    if limit is not None:
        page = page[:limit]
    return page, total


async def get_relationship_datasets(
    session: AsyncSession,
    relationship_id: uuid.UUID,
) -> tuple["DatasetRelationship", Dataset, Dataset] | None:
    """Load a relationship together with its source and target Dataset objects.

    Returns ``None`` if the relationship is missing or either endpoint has no
    backing Dataset. Used by the API layer to enforce source-binding and
    target-visibility checks before exposing related records.
    """
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    result = await session.execute(
        select(DatasetRelationship).where(DatasetRelationship.id == relationship_id)
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        return None

    source_result = await session.execute(
        select(Dataset).where(Dataset.record_id == rel.source_dataset_id)
    )
    source_ds = source_result.scalar_one_or_none()
    target_result = await session.execute(
        select(Dataset).where(Dataset.record_id == rel.target_dataset_id)
    )
    target_ds = target_result.scalar_one_or_none()
    if source_ds is None or target_ds is None:
        return None
    return rel, source_ds, target_ds


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


async def _detect_fk_candidates(
    session: AsyncSession,
    record_id: uuid.UUID,
    column_info: list[dict],
) -> dict[str, list[uuid.UUID]]:
    """Find FK candidates: ``*_id`` columns matching identifier-role attrs in other datasets.

    Returns a dict mapping each source column name to the list of target record_ids
    that have a matching identifier attribute. Empty dict if no candidates.

    Uses one bulk ``IN`` match instead of a query per candidate.
    """
    candidates = [
        col["name"]
        for col in column_info
        if col["name"].endswith("_id") and col["name"].lower() not in _PK_COLUMN_NAMES
    ]
    if not candidates:
        return {}

    # A public source must not auto-link to private/unpublished targets --
    # the relationship would let anonymous callers reach the target's rows
    # via related-records. Restrict to public+published targets when the
    # source itself is public+published.
    source_visibility_result = await session.execute(
        select(Record.visibility, Record.record_status).where(Record.id == record_id)
    )
    source_visibility = source_visibility_result.one_or_none()
    source_is_public = (
        source_visibility is not None
        and source_visibility[0] == "public"
        and source_visibility[1] == "published"
    )

    match_stmt = (
        select(
            AttributeMetadata.field_name,
            Dataset.record_id,
        )
        .join(Dataset, AttributeMetadata.dataset_id == Dataset.id)
        .join(Record, Dataset.record_id == Record.id)
        .where(
            AttributeMetadata.field_name.in_(candidates),
            AttributeMetadata.semantic_role == "identifier",
            Dataset.record_id != record_id,  # skip self-references
        )
    )
    if source_is_public:
        match_stmt = match_stmt.where(
            Record.visibility == "public",
            Record.record_status == "published",
        )

    match_result = await session.execute(match_stmt)

    matches_by_col: dict[str, list[uuid.UUID]] = {}
    for field_name, target_record_id in match_result.all():
        matches_by_col.setdefault(field_name, []).append(target_record_id)
    return matches_by_col


async def _persist_new_relationships(
    session: AsyncSession,
    record_id: uuid.UUID,
    matches_by_col: dict[str, list[uuid.UUID]],
) -> list:
    """Insert one DatasetRelationship per (col, target) pair not already present.

    PERF: one bulk SELECT for existing keys instead of per-pair lookup.
    """
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

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
            existing_keys.add((col_name, target_record_id))  # avoid dup
    return created


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
    matches_by_col = await _detect_fk_candidates(session, record_id, column_info)
    if not matches_by_col:
        return []

    created = await _persist_new_relationships(session, record_id, matches_by_col)

    if created:
        await session.flush()
        logger.info(
            "Auto-detected %d FK relationship(s) for dataset %s",
            len(created),
            dataset_id,
        )

    return created


async def _fetch_fk_value(
    session: AsyncSession, source_table: str, source_column: str, feature_gid: int
) -> object | None:
    """Read the FK value from the source feature row, or None if absent."""
    table_ref = get_catalog_port().quote_table(source_table)
    result = await session.execute(
        text(f"SELECT {source_column} FROM {table_ref} WHERE gid = :gid").bindparams(
            gid=feature_gid
        )
    )
    return result.scalar_one_or_none()


async def _count_target_rows(
    session: AsyncSession, target_table: str, target_column: str, fk_value: object
) -> int:
    table_ref = get_catalog_port().quote_table(target_table)
    result = await session.execute(
        text(
            f"SELECT COUNT(*) FROM {table_ref} WHERE {target_column} = :fk_val"
        ).bindparams(fk_val=fk_value)
    )
    return int(result.scalar_one())


async def _fetch_target_rows(
    session: AsyncSession,
    target_table: str,
    target_column: str,
    fk_value: object,
    limit: int,
    after: int,
) -> list[dict]:
    """Window-fetch matching target rows as gid+properties dicts."""
    # Project the row before to_jsonb -- serializing t.* first
    # passes a curved source `geom` through the geometry->jsonb cast, which
    # raises even though the subtraction then discards it.
    from app.modules.catalog.features.service import live_property_columns

    prop_cols = await live_property_columns(session, target_table)
    prop_sel = f", {prop_cols}" if prop_cols else ""
    table_ref = get_catalog_port().quote_table(target_table)
    # The match runs against the BASE table, inside the
    # projection -- a relationship may legitimately target a column the
    # projection drops (e.g. `geom`/`geom_4326`), and predicating on the
    # projected alias made such a fetch an undefined-column error.
    qcol = '"' + target_column.replace('"', '""').replace(":", "\\:") + '"'
    rows_result = await session.execute(
        text(
            f"SELECT gid, to_jsonb(t.*) - 'gid' AS properties "
            f"FROM (SELECT gid{prop_sel} FROM {table_ref} "
            f"      WHERE {qcol} = :fk_val "
            f"      ORDER BY gid LIMIT :lim OFFSET :off) t"
        ).bindparams(fk_val=fk_value, lim=limit, off=after)
    )
    return [
        {"gid": row[0], **(row[1] if isinstance(row[1], dict) else {})}
        for row in rows_result.all()
    ]


async def get_related_records(
    session: AsyncSession,
    dataset_id: uuid.UUID,
    feature_gid: int,
    relationship_id: uuid.UUID,
    *,
    source_record_id: uuid.UUID | None = None,
    limit: int = 50,
    after: int = 0,
) -> dict:
    """Get related records for a feature via FK relationship.

    Looks up the FK value in the source table, then queries the target table
    for matching rows.

    ``source_record_id`` binds the relationship to the source dataset in the
    URL: a relationship id cannot be replayed through an unrelated source
    dataset to read its target. Callers (the API layer) must pass the
    authorized source record id; access to the target dataset is authorized
    separately at the call site.
    """
    from app.modules.catalog.datasets.domain.models import DatasetRelationship

    result = await session.execute(
        select(DatasetRelationship).where(DatasetRelationship.id == relationship_id)
    )
    rel = result.scalar_one_or_none()
    if rel is None:
        raise ValueError("Relationship not found")
    if source_record_id is not None and rel.source_dataset_id != source_record_id:
        raise ValueError("Relationship not found")

    source_ds = await get_dataset(session, dataset_id)
    if source_ds is None:
        raise ValueError("Source dataset not found")
    if rel.source_dataset_id != source_ds.record_id:
        raise ValueError("Relationship not found")

    # target_dataset_id points to a Record; find its Dataset.
    target_result = await session.execute(
        select(Dataset).where(Dataset.record_id == rel.target_dataset_id)
    )
    target_ds = target_result.scalar_one_or_none()
    if target_ds is None:
        raise ValueError("Target dataset not found")

    if not SAFE_COLUMN_NAME_RE.match(
        rel.source_column
    ) or not SAFE_COLUMN_NAME_RE.match(rel.target_column):
        raise ValueError("Invalid column name in relationship")

    # A raster/VRT endpoint dataset (or a cold-evicted/partial
    # vector table) resolves to a missing data.<table>, raising
    # UndefinedTableError. Map that to 503 instead of an uncaught 500 that
    # holds the DB connection.
    try:
        fk_value = await _fetch_fk_value(
            session, source_ds.table_name, rel.source_column, feature_gid
        )
        if fk_value is None:
            return {
                "rows": [],
                "approximate_total": 0,
                "next_cursor": None,
                "columns": [],
            }

        total = await _count_target_rows(
            session, target_ds.table_name, rel.target_column, fk_value
        )
        rows = await _fetch_target_rows(
            session, target_ds.table_name, rel.target_column, fk_value, limit, after
        )

        columns = await get_catalog_port().get_column_info(
            session, target_ds.table_name
        )
    except (ProgrammingError, OperationalError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A related dataset table is temporarily unavailable",
        )
    col_list = [{"name": c["name"], "type": c["type"]} for c in columns]

    next_cursor = after + limit if after + limit < total else None

    return {
        "rows": rows,
        "approximate_total": total,
        "next_cursor": next_cursor,
        "columns": col_list,
    }
