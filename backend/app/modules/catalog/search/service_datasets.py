"""Dataset search query orchestration for catalog search."""

from __future__ import annotations

from collections.abc import Sequence

from typing import Any

from sqlalchemy import Select, case, collate, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement, Label

from app.core.identity import Identity
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordTranslation,
)
from app.modules.catalog.search.service_candidates import (
    select_candidates,
    vetting_filters,
)
from app.modules.catalog.search.service_filters import SearchFilters
from app.modules.catalog.search.service_semantic import (
    _attach_updated_actor_identities,
    _run_rrf_merge,
)


def _build_fts_rank_col(parts: dict[str, Any]) -> Label[float]:
    """Build the FTS composite rank column from ``_build_text_filter`` parts.

    The caller attaches it next to the text clause the parts came from via
    ``.add_columns(rank_col).where(text_clause)``.
    """
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
    return rank_col


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

    The candidate set (and so ``total``) comes from ``select_candidates``, the
    same selection /search/facets/ counts over. In semantic mode the page is
    the RRF merge of FTS ranks and the vector arm.

    Returns a tuple of (matching_datasets, total_count).
    """
    candidates = await select_candidates(
        session,
        select(func.count())
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id),
        user,
        user_roles,
        filters,
        search_only=True,
        depth=filters.skip + filters.limit,
    )
    total = (await session.execute(candidates.stmt)).scalar_one()

    has_text_search = candidates.text_clause is not None
    rank_col = None
    # Base query always joins Record with eager-loaded keywords/contacts/distributions
    stmt = (
        select(Dataset)
        .join(Record, Dataset.record_id == Record.id)
        .options(
            selectinload(Dataset.record).selectinload(Record.keywords),
            selectinload(Dataset.record).selectinload(Record.contacts),
            selectinload(Dataset.record).selectinload(Record.distributions),
            selectinload(Dataset.record).selectinload(Record.translations),
        )
    )
    if has_text_search:
        rank_col = _build_fts_rank_col(candidates.text_parts)
        stmt = stmt.add_columns(rank_col).where(candidates.text_clause)
    stmt = vetting_filters(stmt, user, user_roles, filters, search_only=True)

    if candidates.semantic is not None:
        return await _run_rrf_merge(
            session, filters, stmt, rank_col, total, candidates.semantic
        )
    stmt = _resolve_sort_order(
        stmt, filters, has_text_search, rank_col, preferred_languages
    )
    stmt = stmt.offset(filters.skip).limit(filters.limit)
    result = await session.execute(stmt)
    if has_text_search:
        rows = result.unique().all()
        datasets = [row[0] for row in rows]
    else:
        datasets = list(result.unique().scalars().all())
    await _attach_updated_actor_identities(session, datasets)
    return datasets, total
