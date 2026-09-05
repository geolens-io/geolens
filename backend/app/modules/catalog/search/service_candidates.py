"""Candidate selection shared by dataset search and facet counts.

fix(#1855): the results and facets endpoints must agree on which records a
query matches, so both build their candidate set through ``select_candidates``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.modules.catalog.search.service_filters import (
    SearchFilters,
    _apply_common_filters,
    _build_text_filter,
)
from app.modules.catalog.search.service_semantic import (
    SemanticArm,
    resolve_semantic_arm,
)


def _apply_search_only_filters(stmt: Select, filters: SearchFilters) -> Select:
    """Apply filters that belong to /search but NOT to /facets.

    Handles record_type, record_ids, external_ids, date_from, date_to,
    vintage_start, vintage_end, and cql2_filter. Spatial / keyword / org /
    srid filters are already applied via _apply_common_filters and stay shared.
    """
    if filters.record_type:
        stmt = stmt.where(Record.record_type == filters.record_type)
    if filters.record_ids is not None:
        # An empty tuple (a standards type filter excluded every type this
        # collection emits) renders as a false predicate: an empty page.
        stmt = stmt.where(Dataset.id.in_(filters.record_ids))
    if filters.external_ids is not None:
        # externalIds names the resource in its SOURCE system. Only STAC imports
        # keep that id in source_filename; service imports store a layer title
        # there, so they stay excluded until their layer id is persisted.
        remote_formats = ("stac",)
        stmt = stmt.where(
            and_(
                Dataset.source_format.in_(remote_formats),
                Dataset.source_filename.in_(filters.external_ids),
            )
        )
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


def vetting_filters(
    stmt: Select,
    user: Identity | None,
    user_roles: set[str],
    filters: SearchFilters,
    *,
    search_only: bool,
) -> Select:
    """Apply what every candidate must satisfy, however it matched the query.

    Visibility (Rule 1) and the shared filters always; the result-only filters
    (record type, dates, CQL2) when ``search_only`` is set. Facets leave those
    off so the type counts cover every type.
    """
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    stmt = _apply_common_filters(stmt, filters, skip_text=True)
    if search_only:
        stmt = _apply_search_only_filters(stmt, filters)
    return stmt


@dataclass(frozen=True, slots=True)
class Candidates:
    """A query's candidate set and how its rows matched.

    ``stmt`` is the caller's base statement with the vetting filters and the
    match clause applied. ``text_clause``/``text_parts`` are None without a
    text query; ``semantic`` is None in lexical mode.
    """

    stmt: Select
    text_clause: ColumnElement[bool] | None
    text_parts: dict[str, Any] | None
    semantic: SemanticArm | None


async def select_candidates(
    session: AsyncSession,
    base: Select,
    user: Identity | None,
    user_roles: set[str],
    filters: SearchFilters,
    *,
    search_only: bool,
    depth: int,
) -> Candidates:
    """Apply the shared candidate selection to ``base``.

    Both /search/datasets/ and /search/facets/ call this, so they take the same
    visibility filter, the same shared filters, the same text clause and the
    same semantic mode decision for a query. In semantic mode a row matches by
    text OR by vector; ``depth`` is how many nearest vector ids the caller
    needs, at least 1.
    """
    stmt = vetting_filters(base, user, user_roles, filters, search_only=search_only)
    if not (filters.q and filters.q.strip()):
        return Candidates(stmt, None, None, None)
    text_clause, text_parts = _build_text_filter(filters.q)
    vet_stmt = vetting_filters(
        select(Record.id)
        .select_from(Dataset)
        .join(Record, Dataset.record_id == Record.id),
        user,
        user_roles,
        filters,
        search_only=search_only,
    )
    semantic = await resolve_semantic_arm(session, filters, vet_stmt, depth=depth)
    match = text_clause if semantic is None else or_(text_clause, semantic.clause())
    return Candidates(stmt.where(match), text_clause, text_parts, semantic)
