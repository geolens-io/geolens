"""Dataset search query orchestration for catalog search."""

from __future__ import annotations

from sqlalchemy import Select, case, collate, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement, Label

from app.core.identity import Identity
from app.core.persistent_config import SEMANTIC_SEARCH_ENABLED
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.search.service_filters import (
    SearchFilters,
    _apply_common_filters,
    _build_text_filter,
)
from app.modules.catalog.search.service_semantic import (
    _attach_updated_actor_identities,
    _run_rrf_merge,
)


def _build_fts_rank_col(
    filters: SearchFilters,
) -> tuple[ColumnElement[bool], Label[float]]:
    """Build the FTS composite rank column + matching WHERE clause.

    Returns ``(text_clause, rank_col)``. Caller should attach both to the
    base SELECT via ``.add_columns(rank_col).where(text_clause)``.
    """
    text_clause, parts = _build_text_filter(filters.q)
    ts_query = parts["ts_query"]
    vector_match = parts["vector_match"]
    title_match = parts["title_match"]
    summary_match = parts["summary_match"]
    keyword_exists = parts["keyword_exists"]
    keyword_partial_exists = parts["keyword_partial_exists"]
    contact_exists = parts["contact_exists"]
    contact_partial_exists = parts["contact_partial_exists"]

    # Composite ranking: ts_rank_cd for vector matches + fixed boosts for child-table matches
    rank_col = (
        func.coalesce(
            case(
                (vector_match, func.ts_rank_cd(Record.search_vector, ts_query)),
                else_=literal(0.0),
            ),
            literal(0.0),
        )
        + case((keyword_exists, literal(0.1)), else_=literal(0.0))
        + case((contact_exists, literal(0.05)), else_=literal(0.0))
        + case((title_match, literal(0.3)), else_=literal(0.0))
        + case((summary_match, literal(0.12)), else_=literal(0.0))
        + case((keyword_partial_exists, literal(0.08)), else_=literal(0.0))
        + case((contact_partial_exists, literal(0.04)), else_=literal(0.0))
    ).label("rank")
    return text_clause, rank_col


def _apply_search_only_filters(stmt: Select, filters: SearchFilters) -> Select:
    """Apply filters that belong to /search but NOT to /facets.

    Handles record_type, date_from, date_to, vintage_start, vintage_end,
    and cql2_filter. Spatial / keyword / org / srid filters are already
    applied via _apply_common_filters and stay shared.
    """
    if filters.record_type:
        stmt = stmt.where(Record.record_type == filters.record_type)
    if filters.date_from:
        stmt = stmt.where(Record.created_at >= filters.date_from)
    if filters.date_to:
        stmt = stmt.where(Record.created_at <= filters.date_to)
    if filters.vintage_start:
        stmt = stmt.where(Record.temporal_start >= filters.vintage_start)
    if filters.vintage_end:
        stmt = stmt.where(Record.temporal_end <= filters.vintage_end)

    # CQL2 structured filter (applied AFTER visibility + facets)
    if filters.cql2_filter:
        from app.standards.ogc.filtering import apply_cql2_filter

        stmt = apply_cql2_filter(stmt, filters.cql2_filter, filters.cql2_filter_lang)
    return stmt


def _resolve_sort_order(
    stmt: Select,
    filters: SearchFilters,
    has_text_search: bool,
    rank_col: Label[float] | None,
) -> Select:
    """Apply ORDER BY clauses for the standard (non-RRF) sort path.

    Handles the 5 sort modes: relevance, date_added, title/name,
    last_updated, and the default fallback. ``rank_col`` may be None
    when no text query is present.
    """
    # Ranking boosts: published status + freshness (last 30 days)
    # Only applied when sort_by == "relevance"; explicit sorts are unchanged.
    published_boost = case(
        (Record.record_status == "published", literal(2.0)),
        else_=literal(1.0),
    )
    freshness_boost = case(
        (Record.updated_at >= func.now() - text("interval '30 days'"), literal(1.5)),
        else_=literal(1.0),
    )

    if filters.sort_by == "relevance" and has_text_search:
        boosted_rank = rank_col * published_boost * freshness_boost
        stmt = stmt.order_by(boosted_rank.desc())
    elif filters.sort_by == "relevance":
        # No text search -- use boost factors with updated_at tiebreaker
        stmt = stmt.order_by(
            (published_boost * freshness_boost).desc(),
            Record.updated_at.desc(),
        )
    elif filters.sort_by == "date_added":
        _desc = filters.sort_desc if filters.sort_desc is not None else True
        stmt = stmt.order_by(
            Record.created_at.desc() if _desc else Record.created_at.asc()
        )
    elif filters.sort_by in {"title", "name"}:
        _desc = filters.sort_desc if filters.sort_desc is not None else False
        if _desc:
            stmt = stmt.order_by(
                collate(func.lower(Record.title), "C").desc(),
                collate(Record.title, "C").desc(),
            )
        else:
            # Keep title ordering deterministic and case-insensitive across collations.
            stmt = stmt.order_by(
                collate(func.lower(Record.title), "C").asc(),
                collate(Record.title, "C").asc(),
            )
    elif filters.sort_by == "last_updated":
        _desc = filters.sort_desc if filters.sort_desc is not None else True
        stmt = stmt.order_by(
            Record.updated_at.desc() if _desc else Record.updated_at.asc()
        )
    else:
        stmt = stmt.order_by(Record.created_at.desc())
    return stmt


async def search_datasets(
    session: AsyncSession,
    user: Identity | None,
    user_roles: set[str],
    filters: SearchFilters,
) -> tuple[list[Dataset], int]:
    """Search datasets with combined FTS + spatial + faceted filtering.

    When SEMANTIC_SEARCH_ENABLED is on and a text query is provided,
    automatically augments FTS results with vector similarity via
    Reciprocal Rank Fusion (k=60).

    Returns a tuple of (matching_datasets, total_count).
    """
    has_text_search = False
    rank_col = None
    # Base query always joins Record with eager-loaded keywords/contacts/distributions
    base_join = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(
            selectinload(Dataset.record).selectinload(Record.keywords),
            selectinload(Dataset.record).selectinload(Record.contacts),
            selectinload(Dataset.record).selectinload(Record.distributions),
        )
    )
    # 1. Full-text search (search_vector now on Record + child-table EXISTS)
    if filters.q and filters.q.strip():
        text_clause, rank_col = _build_fts_rank_col(filters)
        stmt = base_join.add_columns(rank_col).where(text_clause)
        has_text_search = True
    else:
        stmt = base_join
    # 2. RBAC visibility filter (uses Record.visibility/created_by)
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    # 3. Shared filters (spatial, keywords, geometry_type, srid, org, datetime, etc.)
    # skip_text=True because text search is already applied above with ranking
    stmt = _apply_common_filters(stmt, filters, skip_text=True)
    # 4. Search-only filters (not applied to facet counts)
    stmt = _apply_search_only_filters(stmt, filters)
    # 5. Count total matches -- lightweight query without eager loads or ORDER BY.
    # Re-apply the same WHERE clauses from stmt (stored on the compiled whereclause).
    count_base = (
        select(func.count())
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id)
    )
    if stmt.whereclause is not None:
        count_base = count_base.where(stmt.whereclause)
    total = (await session.execute(count_base)).scalar_one()
    # -- Hybrid semantic search with RRF --
    semantic_enabled = await SEMANTIC_SEARCH_ENABLED.get(session)
    if semantic_enabled and has_text_search and filters.q and filters.q.strip():
        if rrf_result := await _run_rrf_merge(session, filters, stmt, rank_col, total):
            return rrf_result
    # 6. Sort (standard FTS-only path or semantic=False)
    stmt = _resolve_sort_order(stmt, filters, has_text_search, rank_col)
    # 7. Paginate + execute
    stmt = stmt.offset(filters.skip).limit(filters.limit)
    result = await session.execute(stmt)
    if has_text_search:
        rows = result.unique().all()
        datasets = [row[0] for row in rows]
    else:
        datasets = list(result.unique().scalars().all())
    await _attach_updated_actor_identities(session, datasets)
    return datasets, total
