"""Dataset search query orchestration for catalog search."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, case, collate, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement, Label

from app.core.identity import Identity
from app.core.persistent_config import SEMANTIC_SEARCH_ENABLED
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    DatasetGrant,
    Record,
    RecordTranslation,
)
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
    ts_query_simple = parts["ts_query_simple"]
    vector_match = parts["english_vector_match"]
    simple_vector_match = parts["simple_vector_match"]
    record_simple_vector = parts["record_simple_vector"]
    title_match = parts["title_match"]
    summary_match = parts["summary_match"]
    keyword_exists = parts["keyword_exists"]
    keyword_partial_exists = parts["keyword_partial_exists"]
    contact_exists = parts["contact_exists"]
    contact_partial_exists = parts["contact_partial_exists"]
    translation_exists = parts["translation_exists"]
    translation_partial_exists = parts["translation_partial_exists"]

    # Composite ranking: ts_rank_cd for vector matches + fixed boosts for child-table matches
    rank_col = (
        func.coalesce(
            case(
                (vector_match, func.ts_rank_cd(Record.search_vector, ts_query)),
                else_=literal(0.0),
            ),
            literal(0.0),
        )
        + func.coalesce(
            case(
                (
                    simple_vector_match,
                    func.ts_rank_cd(record_simple_vector, ts_query_simple)
                    * literal(0.35),
                ),
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
        + case((translation_exists, literal(0.3)), else_=literal(0.0))
        + case((translation_partial_exists, literal(0.2)), else_=literal(0.0))
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
    preferred_languages: Sequence[str] | None = None,
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
        title = _negotiated_title_expression(preferred_languages)
        if _desc:
            stmt = stmt.order_by(
                collate(func.lower(title), "C").desc(),
                collate(title, "C").desc(),
            )
        else:
            # Keep title ordering deterministic and case-insensitive across collations.
            stmt = stmt.order_by(
                collate(func.lower(title), "C").asc(),
                collate(title, "C").asc(),
            )
    elif filters.sort_by == "last_updated":
        _desc = filters.sort_desc if filters.sort_desc is not None else True
        stmt = stmt.order_by(
            Record.updated_at.desc() if _desc else Record.updated_at.asc()
        )
    else:
        stmt = stmt.order_by(Record.created_at.desc())
    # Deterministic final tiebreaker: Record.id is the UUID PK and is unique, so
    # rows tying on every other key get a stable order. SQLAlchemy appends this
    # after the per-branch ORDER BY, keeping OFFSET/LIMIT pagination stable
    # (no dupes / dropped rows across pages).
    stmt = stmt.order_by(Record.id.desc())
    return stmt


def _negotiated_title_expression(
    preferred_languages: Sequence[str] | None,
) -> ColumnElement[str]:
    """Build a correlated title selector matching record negotiation order."""
    primary_language = func.lower(
        func.replace(func.coalesce(Record.language, "en"), "_", "-")
    )
    translation_language = func.lower(RecordTranslation.language)
    primary_whens: list[tuple[ColumnElement[bool], int]] = []
    translation_whens: list[tuple[ColumnElement[bool], int]] = []
    translation_conditions: list[ColumnElement[bool]] = []
    priority = 0
    for requested in preferred_languages or ():
        parts = requested.lower().split("-")
        while parts:
            tag = "-".join(parts)
            primary_whens.append((primary_language == tag, priority))
            priority += 1
            condition = translation_language == tag
            translation_whens.append((condition, priority))
            translation_conditions.append(condition)
            priority += 1
            parts.pop()

        base = requested.split("-", 1)[0].lower()
        primary_base = func.split_part(primary_language, "-", 1) == base
        primary_whens.append((primary_base, priority))
        priority += 1
        translation_base = func.split_part(translation_language, "-", 1) == base
        translation_whens.append((translation_base, priority))
        translation_conditions.append(translation_base)
        priority += 1

    if not primary_whens:
        return Record.title

    no_match_rank = priority + 1
    primary_rank = case(*primary_whens, else_=no_match_rank)
    translation_rank = case(*translation_whens, else_=no_match_rank)
    translation_query = (
        select(RecordTranslation.title)
        .where(
            RecordTranslation.record_id == Record.id,
            or_(*translation_conditions),
        )
        .order_by(translation_rank, translation_language)
        .limit(1)
        .correlate(Record)
    )
    translated_title = translation_query.scalar_subquery()
    translated_rank = (
        select(translation_rank)
        .where(
            RecordTranslation.record_id == Record.id,
            or_(*translation_conditions),
        )
        .order_by(translation_rank, translation_language)
        .limit(1)
        .correlate(Record)
        .scalar_subquery()
    )
    return case(
        (
            primary_rank <= func.coalesce(translated_rank, no_match_rank),
            Record.title,
        ),
        else_=func.coalesce(translated_title, Record.title),
    )


async def search_datasets(
    session: AsyncSession,
    user: Identity | None,
    user_roles: set[str],
    filters: SearchFilters,
    preferred_languages: Sequence[str] | None = None,
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
            selectinload(Dataset.record).selectinload(Record.translations),
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
        # Vetting query for semantic vector-only candidates: identical visibility +
        # common + search-only filters as the FTS `stmt`, but WITHOUT the text
        # clause (vector-only hits match by meaning, not lexically). _run_rrf_merge
        # constrains it to the candidate ids so a surfaced vector-only match
        # satisfies every active filter (visibility, bbox, geometry_type, srid,
        # keywords, dates, CQL) -- never leaking or violating a filter.
        vet_stmt = (
            select(Record.id)
            .select_from(Dataset)
            .join(Record, Dataset.record_id == Record.id)
        )
        vet_stmt = apply_visibility_filter(
            vet_stmt, user, user_roles, Record, DatasetGrant
        )
        vet_stmt = _apply_common_filters(vet_stmt, filters, skip_text=True)
        vet_stmt = _apply_search_only_filters(vet_stmt, filters)
        if rrf_result := await _run_rrf_merge(
            session, filters, stmt, rank_col, total, vet_stmt
        ):
            return rrf_result
    # 6. Sort (standard FTS-only path or semantic=False)
    stmt = _resolve_sort_order(
        stmt, filters, has_text_search, rank_col, preferred_languages
    )
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
