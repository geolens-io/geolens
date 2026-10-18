"""Facet count queries for catalog search."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import Row, String as SAString, func, literal, null, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordKeyword,
)
from app.modules.catalog.search.service_candidates import select_candidates
from app.modules.catalog.search.service_filters import FacetCounts, SearchFilters


async def get_facet_counts(
    session: AsyncSession,
    user: Identity | None,
    user_roles: set[str],
    filters: SearchFilters,
) -> FacetCounts:
    """Return multi-group facet counts over the query's candidate set.

    Returns dict with keys: record_type, keywords, source_organization, srid,
    collections. The candidate set is the one /search/datasets/ counts, minus
    the result-only filters: record_type is never applied, so the type counts
    cover every type.
    """
    candidates = await select_candidates(
        session,
        select(Dataset.id.label("dataset_id"), Record.id.label("record_id"))
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id),
        user,
        user_roles,
        filters,
        search_only=False,
        # Facets need no ranks; depth 1 is the probe that decides the mode.
        depth=1,
    )
    # MATERIALIZED: the five groups read one evaluation of the candidate
    # selection rather than each re-running its filters.
    filtered_cte = candidates.stmt.cte("filtered_ids").prefix_with("MATERIALIZED")

    # No "collection" record_type value: collections live in their own table,
    # so it would always filter to 0. The collections group covers them.
    type_stmt = (
        select(
            literal("record_type").label("facet"),
            Record.record_type.label("value"),
            null().label("name"),
            func.count().label("count"),
        )
        .select_from(filtered_cte)
        .join(Record, Record.id == filtered_cte.c.record_id)
        .group_by(Record.record_type)
    )
    kw_stmt = (
        select(literal("keywords"), RecordKeyword.keyword, null(), func.count())
        .select_from(filtered_cte)
        .join(RecordKeyword, RecordKeyword.record_id == filtered_cte.c.record_id)
        .group_by(RecordKeyword.keyword)
        .order_by(func.count().desc())
        .limit(20)
    )
    org_stmt = (
        select(
            literal("source_organization"),
            Record.source_organization,
            null(),
            func.count(),
        )
        .select_from(filtered_cte)
        .join(Record, Record.id == filtered_cte.c.record_id)
        .where(Record.source_organization.isnot(None), Record.source_organization != "")
        .group_by(Record.source_organization)
        .order_by(func.count().desc())
        .limit(50)
    )
    srid_stmt = (
        select(literal("srid"), func.cast(Dataset.srid, SAString), null(), func.count())
        .select_from(filtered_cte)
        .join(Dataset, Dataset.id == filtered_cte.c.dataset_id)
        .where(Dataset.srid.isnot(None))
        .group_by(Dataset.srid)
        .order_by(func.count().desc())
        .limit(50)
    )
    coll_facet_stmt = (
        select(
            literal("collections"),
            func.cast(Collection.id, SAString),
            Collection.name,
            func.count(CollectionDataset.dataset_id),
        )
        .select_from(Collection)
        .join(CollectionDataset, CollectionDataset.collection_id == Collection.id)
        .join(filtered_cte, filtered_cte.c.dataset_id == CollectionDataset.dataset_id)
        .group_by(Collection.id, Collection.name)
    )
    result = await session.execute(
        union_all(type_stmt, kw_stmt, org_stmt, srid_stmt, coll_facet_stmt)
    )
    groups: dict[str, list[Row]] = defaultdict(list)
    # A UNION ALL keeps no order across or within its branches.
    for row in sorted(result.all(), key=lambda row: row.count, reverse=True):
        groups[row.facet].append(row)

    return {
        "record_type": {row.value: row.count for row in groups["record_type"]},
        "keywords": [
            {"value": row.value, "count": row.count} for row in groups["keywords"]
        ],
        "source_organization": [
            {"value": row.value, "count": row.count}
            for row in groups["source_organization"]
        ],
        "srid": [{"value": row.value, "count": row.count} for row in groups["srid"]],
        "collections": [
            {"id": row.value, "name": row.name, "dataset_count": row.count}
            for row in groups["collections"]
        ],
    }
