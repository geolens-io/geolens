"""Semantic search, RRF merge, and search-result actor enrichment helpers."""

from __future__ import annotations

import time
import uuid as uuid_mod
from collections import OrderedDict

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import Label
from sqlalchemy.sql.selectable import Select

from app.core.persistent_config import EMBEDDING_MODEL
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.search.service_filters import SearchFilters
from app.platform.extensions import get_catalog_port

logger = structlog.stdlib.get_logger(__name__)
EmbeddingUnavailableError = get_catalog_port().embedding_unavailable_error_class()


# Phase 269 H-22: TTL LRU cache for query embeddings.
# Per-query embedding generation calls the configured AI provider (e.g.,
# OpenAI text-embedding-3-small at 200-800 ms per call). Repeated identical
# queries within ~5 minutes are common during user sessions and should not
# pay that cost on every request. The cache key is `(query_text.lower(),
# model_name)` so case variations and accidental whitespace collide. TTL is
# 300 seconds (matches audit recommendation), max 512 entries.
_EMBEDDING_CACHE_TTL_SECONDS = 300.0
_EMBEDDING_CACHE_MAX_SIZE = 512
_embedding_cache: "OrderedDict[tuple[str, str], tuple[float, list[float]]]" = (
    OrderedDict()
)


def _embedding_cache_get(key: tuple[str, str]) -> list[float] | None:
    """Return a cached embedding if present and not expired; else None."""
    entry = _embedding_cache.get(key)
    if entry is None:
        return None
    expires_at, vector = entry
    if expires_at < time.monotonic():
        _embedding_cache.pop(key, None)
        return None
    # Move to end so LRU-eviction picks the truly oldest entry.
    _embedding_cache.move_to_end(key)
    return vector


def _embedding_cache_put(key: tuple[str, str], vector: list[float]) -> None:
    """Insert with TTL; evict oldest when over capacity."""
    expires_at = time.monotonic() + _EMBEDDING_CACHE_TTL_SECONDS
    _embedding_cache[key] = (expires_at, vector)
    _embedding_cache.move_to_end(key)
    while len(_embedding_cache) > _EMBEDDING_CACHE_MAX_SIZE:
        _embedding_cache.popitem(last=False)


def _embedding_cache_clear() -> None:
    """Clear the cache (test-helper)."""
    _embedding_cache.clear()


async def generate_embedding(text: str, session: AsyncSession) -> list[float]:
    """Generate an embedding through the configured CatalogPort provider.

    Phase 269 H-22: results are memoized in a TTL LRU cache keyed on
    `(text.strip().lower(), model_name)`, TTL 300s. Cache write only happens
    on the success path; provider errors propagate to callers as before.
    """
    normalized = text.strip().lower()
    if not normalized:
        # Don't cache empty inputs — let the provider raise its usual error.
        return await get_catalog_port().generate_embedding(text, session)

    model_name = await EMBEDDING_MODEL.get(session)
    cache_key = (normalized, model_name)

    cached = _embedding_cache_get(cache_key)
    if cached is not None:
        return cached

    vector = await get_catalog_port().generate_embedding(text, session)
    _embedding_cache_put(cache_key, vector)
    return vector


async def _attach_updated_actor_identities(
    session: AsyncSession,
    datasets: list[Dataset],
) -> None:
    actor_ids = {
        dataset.record.updated_by
        for dataset in datasets
        if dataset.record.updated_by is not None
    }
    if not actor_ids:
        return

    result = await session.execute(select(User).where(User.id.in_(actor_ids)))
    users_by_id = {user.id: user for user in result.scalars().all()}

    for dataset in datasets:
        record = dataset.record
        actor_id = record.updated_by
        if actor_id is None:
            continue
        # Attach the optional row once so serializers don't need extra DB lookups.
        setattr(record, "_provenance_updated_user", users_by_id.get(actor_id))


async def _get_vector_ranks(
    session: AsyncSession,
    query_text: str,
    limit: int,
) -> dict[str, int]:
    """Run vector similarity search and return {record_id_hex: rank} mapping.

    Returns an empty dict on any failure (silent fallback).
    """
    # Check if any embeddings exist at all
    if not await get_catalog_port().has_embeddings(session):
        return {}

    # Generate query embedding
    try:
        query_vector = await generate_embedding(query_text.strip(), session)
    except EmbeddingUnavailableError:
        logger.warning("Embedding unavailable for semantic search, falling back to FTS")
        return {}
    except Exception:  # broad: third-party embedding SDK can throw provider-specific errors; fall back to FTS
        logger.warning(
            "Failed to generate query embedding, falling back to FTS", exc_info=True
        )
        return {}

    try:
        # Get current model name for filtering
        model_name = await EMBEDDING_MODEL.get(session)

        # Tune HNSW recall -- default ef_search=40 may miss relevant results
        await get_catalog_port().set_hnsw_recall(session)
        RecordEmbedding = get_catalog_port().record_embedding_orm_class()

        # Vector similarity query: cosine distance <= 0.7 means similarity >= 0.3
        vector_stmt = (
            select(
                RecordEmbedding.record_id,
                RecordEmbedding.embedding.cosine_distance(query_vector).label(
                    "distance"
                ),
            )
            .where(
                RecordEmbedding.model_name == model_name,
                RecordEmbedding.embedding.cosine_distance(query_vector) <= 0.7,
            )
            .order_by("distance")
            .limit(limit)
        )

        result = await session.execute(vector_stmt)
        rows = result.all()
    except Exception:  # broad: pgvector/HNSW failures are diverse — degrade to FTS rather than 500 the search
        # pgvector extension missing, HNSW SET error, or DB execute failure --
        # honor the docstring contract and degrade to FTS-only
        logger.warning(
            "Vector similarity query failed, falling back to FTS", exc_info=True
        )
        return {}

    # Assign positional ranks (1-based)
    return {str(row.record_id): rank + 1 for rank, row in enumerate(rows)}


def _compute_rrf_scores(
    fts_ids: list[str],
    vector_ranks: dict[str, int],
    k: int = 60,
) -> list[str]:
    """Merge FTS and vector results using Reciprocal Rank Fusion.

    Returns record IDs sorted by RRF score descending.
    """
    scores: dict[str, float] = {}

    # FTS contribution (positional rank 1-based)
    for rank, record_id in enumerate(fts_ids, start=1):
        scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (k + rank)

    # Vector contribution
    for record_id, v_rank in vector_ranks.items():
        scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (k + v_rank)

    # Sort by RRF score descending
    return sorted(scores.keys(), key=lambda rid: scores[rid], reverse=True)


async def _run_rrf_merge(
    session: AsyncSession,
    filters: SearchFilters,
    stmt: Select,
    rank_col: Label[float],
    total: int,
) -> tuple[list[Dataset], int] | None:
    """Execute hybrid FTS+vector RRF merge and return paginated results.

    Returns ``None`` when RRF doesn't apply (vector backend empty/failed).
    Caller falls through to the standard sort path on None.

    Returns ``([], total)`` rather than ``None`` when the FTS-cap query
    yields zero ids -- caller returns that tuple as-is. Preserved from
    pre-refactor behavior; do not change to ``None`` (would alter
    observable behavior by falling through to the standard sort path).
    """
    if filters.q is None:
        raise ValueError("_run_rrf_merge requires filters.q to be non-None")
    q_stripped = filters.q.strip()
    # Get vector similarity ranks (empty dict on any failure = FTS-only)
    vector_ranks = await _get_vector_ranks(session, q_stripped, filters.limit)

    if not vector_ranks:
        logger.info(
            "rrf_fallback_to_fts",
            extra={"reason": "empty_vector_ranks", "q_prefix": q_stripped[:50]},
        )
        return None

    # Get FTS-ranked record IDs (up to a reasonable cap for merging).
    # Strip the inherited eager-loads -- only record_id is needed at
    # this stage, so 4 wasted selectinload queries per request are
    # avoided (PERF-8).
    fts_cap = max(filters.limit * 3, 100)
    fts_stmt = (
        stmt.with_only_columns(Dataset.record_id)
        .order_by(rank_col.desc())
        .limit(fts_cap)
    )
    fts_result = await session.execute(fts_stmt)
    fts_ids = [str(row[0]) for row in fts_result.all()]

    # Compute RRF-ranked order (only includes IDs from FTS results + vector results)
    # Filter vector_ranks to only include IDs that appear in FTS results
    # (vector-only results are excluded to keep it simple per plan)
    fts_id_set = set(fts_ids)
    filtered_vector_ranks = {
        rid: rank for rid, rank in vector_ranks.items() if rid in fts_id_set
    }

    rrf_ordered = _compute_rrf_scores(fts_ids, filtered_vector_ranks)

    # Apply pagination to RRF-ordered list
    page_ids = rrf_ordered[filters.skip : filters.skip + filters.limit]

    if page_ids:
        # Fetch full Dataset objects for the final page
        fetch_stmt = (
            select(Dataset)
            .join(Record, Dataset.record_id == Record.id)
            .options(
                selectinload(Dataset.record).selectinload(Record.keywords),
                selectinload(Dataset.record).selectinload(Record.contacts),
                selectinload(Dataset.record).selectinload(Record.distributions),
            )
            .where(Record.id.in_([uuid_mod.UUID(rid) for rid in page_ids]))
        )
        fetch_result = await session.execute(fetch_stmt)
        datasets_by_id = {
            str(d.record_id): d for d in fetch_result.unique().scalars().all()
        }
        # Preserve RRF order
        datasets = [datasets_by_id[rid] for rid in page_ids if rid in datasets_by_id]
    else:
        datasets = []

    await _attach_updated_actor_identities(session, datasets)
    return datasets, total
