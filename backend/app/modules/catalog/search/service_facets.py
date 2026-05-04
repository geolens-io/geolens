"""Facet count queries for catalog search."""

from __future__ import annotations

from sqlalchemy import String as SAString, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
    RecordKeyword,
)
from app.modules.catalog.search.service_filters import (
    FacetCounts,
    SearchFilters,
    _apply_common_filters,
)


async def get_facet_counts(
    session: AsyncSession,
    user: Identity | None,
    user_roles: set[str],
    filters: SearchFilters,
) -> FacetCounts:
    """Return multi-group facet counts for datasets matching the given filters.

    Returns dict with keys: record_type, keywords, source_organization, srid.
    Does NOT filter by record_type itself (facets show counts for all types).
    Separately counts matching collections from the collections table.
    """
    # Build a CTE that materializes the filtered (dataset_id, record_id) pairs
    # once. Both the record_type counts and per-facet queries join against it
    # instead of each independently re-evaluating the full filter stack.
    filtered_base = (
        select(Dataset.id.label("dataset_id"), Record.id.label("record_id"))
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
    )
    filtered_base = apply_visibility_filter(
        filtered_base, user, user_roles, Record, DatasetGrant
    )
    filtered_base = _apply_common_filters(filtered_base, filters)
    filtered_cte = filtered_base.cte("filtered_ids")

    # Record-type counts from the CTE (replaces duplicate filter stack)
    type_stmt = (
        select(Record.record_type, func.count().label("count"))
        .select_from(filtered_cte)
        .join(Record, Record.id == filtered_cte.c.record_id)
        .group_by(Record.record_type)
    )
    result = await session.execute(type_stmt)
    counts = {row.record_type: row.count for row in result.all()}

    # Separately count collections from the collections table
    coll_stmt = select(func.count()).select_from(Collection)
    if filters.q and filters.q.strip():
        q_like = f"%{filters.q.strip().lower()}%"
        coll_stmt = coll_stmt.where(
            or_(
                func.lower(Collection.name).like(q_like),
                func.lower(func.coalesce(Collection.description, "")).like(q_like),
            )
        )
    coll_count = (await session.execute(coll_stmt)).scalar_one()
    if coll_count > 0:
        counts["collection"] = coll_count

    # Facet queries are intentionally sequential -- SQLAlchemy AsyncSession
    # is not safe for concurrent execute() on a shared connection.
    # Each query joins the CTE instead of re-applying all filters.

    # --- Keyword facets (top 20) ---
    kw_stmt = (
        select(RecordKeyword.keyword, func.count().label("count"))
        .select_from(filtered_cte)
        .join(RecordKeyword, RecordKeyword.record_id == filtered_cte.c.record_id)
        .group_by(RecordKeyword.keyword)
        .order_by(func.count().desc())
        .limit(20)
    )
    kw_result = await session.execute(kw_stmt)
    keyword_facets = [
        {"value": row.keyword, "count": row.count} for row in kw_result.all()
    ]

    # --- Source organization facets ---
    org_stmt = (
        select(Record.source_organization, func.count().label("count"))
        .select_from(filtered_cte)
        .join(Record, Record.id == filtered_cte.c.record_id)
        .where(Record.source_organization.isnot(None), Record.source_organization != "")
        .group_by(Record.source_organization)
        .order_by(func.count().desc())
        .limit(50)
    )
    org_result = await session.execute(org_stmt)
    org_facets = [
        {"value": row.source_organization, "count": row.count}
        for row in org_result.all()
    ]

    # --- SRID facets ---
    srid_stmt = (
        select(
            func.cast(Dataset.srid, SAString).label("srid_str"),
            func.count().label("count"),
        )
        .select_from(filtered_cte)
        .join(Dataset, Dataset.id == filtered_cte.c.dataset_id)
        .where(Dataset.srid.isnot(None))
        .group_by(Dataset.srid)
        .order_by(func.count().desc())
        .limit(50)
    )
    srid_result = await session.execute(srid_stmt)
    srid_facets = [
        {"value": row.srid_str, "count": row.count} for row in srid_result.all()
    ]

    # --- Collections facet (lightweight: id, name, visible member count) ---
    coll_facet_stmt = (
        select(
            Collection.id,
            Collection.name,
            func.count(CollectionDataset.dataset_id).label("dataset_count"),
        )
        .select_from(Collection)
        .join(CollectionDataset, CollectionDataset.collection_id == Collection.id)
        .join(filtered_cte, filtered_cte.c.dataset_id == CollectionDataset.dataset_id)
        .group_by(Collection.id, Collection.name)
        .order_by(func.count(CollectionDataset.dataset_id).desc())
    )
    coll_facet_result = await session.execute(coll_facet_stmt)
    collections_facet = [
        {"id": str(row.id), "name": row.name, "dataset_count": row.dataset_count}
        for row in coll_facet_result.all()
    ]

    return {
        "record_type": counts,
        "keywords": keyword_facets,
        "source_organization": org_facets,
        "srid": srid_facets,
        "collections": collections_facet,
    }
