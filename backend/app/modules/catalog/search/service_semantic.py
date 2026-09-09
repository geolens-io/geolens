"""Semantic search, RRF merge, and search-result actor enrichment helpers."""

from __future__ import annotations

import asyncio
import time
import uuid as uuid_mod
from collections import OrderedDict
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement, Label
from sqlalchemy.sql.selectable import Select

from app.core.persistent_config import SEMANTIC_SEARCH_ENABLED
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.search.service_filters import SearchFilters
from app.platform.cache import tenant_cache_context_available, tenant_cache_key
from app.platform.extensions import get_catalog_port
from app.platform.ratelimit_claims import get_shared_claim_store

logger = structlog.stdlib.get_logger(__name__)
EmbeddingUnavailableError = get_catalog_port().embedding_unavailable_error_class()


# TTL LRU cache for query embeddings, keyed on (tenant-scoped text, model,
# config fingerprint). fix(#1546): the fingerprint is load-bearing, not
# decoration — omitting it lets a config change serve a stale-space vector.
_EMBEDDING_CACHE_TTL_SECONDS = 300.0
_EMBEDDING_CACHE_MAX_SIZE = 512

# fix(#448): above this many stored embeddings the exact vector arm (a full
# cosine scan) gives way to a nearest-first window.
_EXACT_SEMANTIC_COUNT_MAX_ROWS = 5000

# fix(#1855): above the row gate results and facets take the same window, so
# a first page of any size agrees with the facet counts.
_APPROXIMATE_CANDIDATE_WINDOW = 200

# fix(#625): search-as-you-type spent one paid embedding call per keystroke
# prefix ("u", "us", "usa"), each missing the 0.7 cutoff and falling back to FTS
# anyway; the 300s cache can't help, every prefix is a distinct key. Shorter
# queries skip the vector path entirely.
_MIN_SEMANTIC_QUERY_LEN = 4
_embedding_cache: "OrderedDict[tuple[str, str, str], tuple[float, list[float]]]" = (
    OrderedDict()
)


def _embedding_cache_get(key: tuple[str, str, str]) -> list[float] | None:
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


def _embedding_cache_put(key: tuple[str, str, str], vector: list[float]) -> None:
    """Insert with TTL; evict oldest when over capacity."""
    expires_at = time.monotonic() + _EMBEDDING_CACHE_TTL_SECONDS
    _embedding_cache[key] = (expires_at, vector)
    _embedding_cache.move_to_end(key)
    while len(_embedding_cache) > _EMBEDDING_CACHE_MAX_SIZE:
        _embedding_cache.popitem(last=False)


def _embedding_cache_clear() -> None:
    """Clear the cache (test-helper)."""
    _embedding_cache.clear()


# fix(#1903): coordinates the SPA's unordered results/facets pair so only
# one request pays the SEC-S11 token; keyed on (client, tenant, text),
# single-use, bounded by TTL + LRU. fix(#2018): a configured shared store
# answers first, so this is the fallback for one that does not answer.
_QUERY_CLAIM_TTL_SECONDS = 5.0
_QUERY_CLAIM_MAX_SIZE = 256
_query_claims: "OrderedDict[tuple[str, str], tuple[str, float]]" = OrderedDict()


def _query_claim_key(client_key: str, text: str) -> tuple[str, str] | None:
    """fix(#1903): a tuple, not an f-string join -- ``client_key`` is an IPv6
    address, which contains ``:`` too, so a joined string lets one /64
    holder's query text collide with a neighbour's address.

    Also fails closed on an unscoped multi-tenant host: ``tenant_cache_key``
    raises when there is no verified tenant context, so this checks
    ``tenant_cache_context_available()`` first, same as the search cache.
    """
    normalized = text.strip().lower()
    if not normalized or not tenant_cache_context_available():
        return None
    return (client_key, tenant_cache_key(normalized))


def consume_paired_query_claim(client_key: str, text: str, route: str) -> bool:
    """True when the OTHER route already claimed this (client, text); consumes it.

    Read-only otherwise -- it never creates a claim. fix(#1903): claiming
    must not be a side effect of the rate-limit pre-check, which runs for a
    request the bucket goes on to reject too; only ``record_paired_query_
    claim``, called from a handler that is provably running (the rate limit
    admitted it), may create one.
    """
    key = _query_claim_key(client_key, text)
    if key is None:
        return False
    store = get_shared_claim_store()
    if store is not None:
        shared = store.consume(key, route)
        if shared is not None:
            return shared
    claimed = _query_claims.get(key)
    if claimed is None:
        return False
    claimant_route, expires_at = claimed
    if expires_at < time.monotonic() or claimant_route == route:
        return False
    del _query_claims[key]
    return True


def record_paired_query_claim(client_key: str, text: str, route: str) -> None:
    """Claim (client, text) for *route*. Call only once a request is admitted."""
    key = _query_claim_key(client_key, text)
    if key is None:
        return
    store = get_shared_claim_store()
    if store is not None and store.record(key, route) is not None:
        return
    _query_claims[key] = (route, time.monotonic() + _QUERY_CLAIM_TTL_SECONDS)
    _query_claims.move_to_end(key)
    while len(_query_claims) > _QUERY_CLAIM_MAX_SIZE:
        _query_claims.popitem(last=False)


def _query_claims_clear() -> None:
    """Clear the claim registry (test-helper)."""
    _query_claims.clear()


# fix(#448): the provider default timeout (130s) is sized for backfill; a hung
# provider must not hold a search request, and resolve_semantic_arm degrades to
# FTS on any error. wait_for keeps CatalogPort overlays source-compatible.
_QUERY_EMBED_TIMEOUT_SECONDS = 8.0


async def _embed_with_deadline(
    text: str,
    session: AsyncSession,
    pinned: tuple[str, int | None, str | None] | None = None,
) -> list[float]:
    return await asyncio.wait_for(
        get_catalog_port().generate_embedding(text, session, pinned=pinned),
        timeout=_QUERY_EMBED_TIMEOUT_SECONDS,
    )


# fix(#1903): coalesces concurrent embeds for one cache key into a single
# provider call, since a rate-limit exemption can be granted before either
# half of a paired request finishes embedding. Only used when the config is
# fully pinned (see generate_embedding); waiters shield so cancelling one
# participant can't cancel the shared task or its siblings.
_embedding_inflight: "dict[tuple[str, str, str], asyncio.Task[list[float]]]" = {}


def _embedding_inflight_clear() -> None:
    """Clear the in-flight registry (test-helper)."""
    _embedding_inflight.clear()


async def _embed_and_cache(
    text: str,
    session: AsyncSession,
    cache_key: tuple[str, str, str],
    pinned: tuple[str, int, str | None],
) -> list[float]:
    try:
        vector = await _embed_with_deadline(text, session, pinned)
        _embedding_cache_put(cache_key, vector)
        return vector
    finally:
        _embedding_inflight.pop(cache_key, None)


async def generate_embedding(
    text: str,
    session: AsyncSession,
    *,
    config: tuple[str, int | None, str | None, str] | None = None,
) -> list[float]:
    """Generate an embedding through the configured CatalogPort provider.

    Memoized in the TTL LRU cache above. ``config`` is normally pre-resolved
    once per search request by the caller; omit it to resolve here.

    fix(#1546): the first three config fields are handed to the PROVIDER,
    not just used to key the cache, so a settings change mid-call can't
    vector under one config while caching/ranking against another's rows.
    """
    normalized = text.strip().lower()
    if not normalized:
        # Don't cache empty inputs — let the provider raise its usual error.
        return await _embed_with_deadline(text, session)

    if config is None:
        config = await get_catalog_port().resolve_embedding_config(session)
    if config is None:
        # Nothing to pin and nothing safe to key a cache entry on.
        return await _embed_with_deadline(text, session)

    model_name, dimensions, base_url, fingerprint = config
    cache_key = (tenant_cache_key(normalized), model_name, fingerprint)

    cached = _embedding_cache_get(cache_key)
    if cached is not None:
        return cached

    if not model_name or not dimensions:
        # fix(#1903): mirrors generate_embeddings_batch's own session-read
        # gate (processing/embeddings/service.py) exactly, since a shared
        # task can outlive this request's session -- only a call THAT gate
        # would also treat as fully pinned may be shared; this one runs
        # standalone.
        vector = await _embed_with_deadline(
            text, session, (model_name, dimensions, base_url)
        )
        _embedding_cache_put(cache_key, vector)
        return vector

    task = _embedding_inflight.get(cache_key)
    if task is None:
        # No await between the cache/inflight reads above and this write,
        # so no other coroutine can interleave on this event loop and race
        # the same key into two tasks.
        task = asyncio.ensure_future(
            _embed_and_cache(
                text, session, cache_key, (model_name, dimensions, base_url)
            )
        )
        _embedding_inflight[cache_key] = task
    return await asyncio.shield(task)


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


@dataclass(frozen=True, slots=True)
class SemanticArm:
    """The vector arm of a query's candidate set, resolved once per request.

    ``ordered_ids`` are the nearest-first vetted record ids within the cosine
    cutoff: every one of them below the row gate (``exact``), the nearest
    ``window`` above it. One scan per request; the clause is a list of ids, so
    the statements it lands in never touch the embeddings table.
    """

    query_vector: list[float]
    model_name: str
    config_fingerprint: str
    ordered_ids: tuple[str, ...]
    window: int
    exact: bool

    @property
    def window_full(self) -> bool:
        return len(self.ordered_ids) >= self.window

    def ranks(self, depth: int) -> dict[str, int]:
        """Positional (1-based) ranks of the nearest ``depth`` ids."""
        return {rid: rank + 1 for rank, rid in enumerate(self.ordered_ids[:depth])}

    def clause(self) -> ColumnElement[bool]:
        """Record.id predicate for the vector arm; the caller applies vetting."""
        return Record.id.in_([uuid_mod.UUID(rid) for rid in self.ordered_ids])


async def resolve_semantic_arm(
    session: AsyncSession,
    filters: SearchFilters,
    vet_stmt: Select,
    *,
    depth: int,
) -> SemanticArm | None:
    """Decide whether a query runs in semantic mode and resolve its vector arm.

    Returns None (lexical mode) on any disqualifier: search disabled, query
    too short, no embeddings, unresolvable config, an embedding/query
    failure, or no row within the cosine cutoff. ``depth`` is how many
    nearest ids the caller needs; below the row gate every match is fetched.
    """
    query_text = (filters.q or "").strip()
    if len(query_text) < _MIN_SEMANTIC_QUERY_LEN:
        return None
    if not await SEMANTIC_SEARCH_ENABLED.get(session):
        return None
    if not await get_catalog_port().has_embeddings(session):
        return None

    try:
        # fix(#1546): the query vector and the row filter come from ONE reading
        # of the configuration, resolved under the fallback guard.
        config = await get_catalog_port().resolve_embedding_config(session)
        if config is None:
            logger.warning(
                "Embedding configuration unresolved for semantic search, "
                "falling back to FTS"
            )
            return None
        query_vector = await generate_embedding(query_text, session, config=config)
    except EmbeddingUnavailableError:
        logger.warning("Embedding unavailable for semantic search, falling back to FTS")
        return None
    except Exception:  # broad: third-party embedding SDK can throw provider-specific errors; fall back to FTS
        logger.warning(
            "Failed to generate query embedding, falling back to FTS", exc_info=True
        )
        return None

    model_name, _dimensions, _base_url, config_fingerprint = config
    RecordEmbedding = get_catalog_port().record_embedding_orm_class()
    usable = RecordEmbedding.usable_by_config(model_name, config_fingerprint)
    try:
        # fix(#448): the row gate is measured under the same predicate the
        # ranks and counts use, so foreign-configuration rows cannot trip it.
        emb_rows = (
            await session.execute(
                select(func.count())
                .select_from(RecordEmbedding)
                .join(Record, RecordEmbedding.record_id == Record.id)
                .where(usable)
            )
        ).scalar_one()
        exact = emb_rows <= _EXACT_SEMANTIC_COUNT_MAX_ROWS
        window = depth if exact else max(depth, _APPROXIMATE_CANDIDATE_WINDOW)
        await get_catalog_port().set_hnsw_recall(session)
        distance = RecordEmbedding.embedding.cosine_distance(query_vector)
        # Restricting to the vetted set BEFORE the top-k cut keeps a nearer
        # private or filtered-out row from displacing a valid match.
        vector_stmt = (
            select(RecordEmbedding.record_id)
            .where(usable, distance <= 0.7, RecordEmbedding.record_id.in_(vet_stmt))
            .order_by(distance)
        )
        # Exact: every match, bounded by the row gate. The one scan per request.
        if not exact:
            vector_stmt = vector_stmt.limit(window)
        rows = (await session.execute(vector_stmt)).all()
    except Exception:  # broad: pgvector/HNSW failures are diverse; degrade to FTS rather than 500 the search
        logger.warning(
            "Vector similarity query failed, falling back to FTS", exc_info=True
        )
        return None
    if not rows:
        logger.info(
            "rrf_fallback_to_fts",
            extra={"reason": "empty_vector_ranks", "q_prefix": query_text[:50]},
        )
        return None
    return SemanticArm(
        query_vector=query_vector,
        model_name=model_name,
        config_fingerprint=config_fingerprint,
        ordered_ids=tuple(str(row.record_id) for row in rows),
        window=window,
        exact=exact,
    )


def _compute_rrf_scores(
    fts_ids: list[str],
    vector_ranks: dict[str, int],
    k: int = 60,
) -> list[str]:
    """Merge FTS and vector results using Reciprocal Rank Fusion.

    Returns record IDs sorted by RRF score descending.
    """
    scores: dict[str, float] = {}

    for rank, record_id in enumerate(fts_ids, start=1):
        scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (k + rank)

    for record_id, v_rank in vector_ranks.items():
        scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (k + v_rank)

    return sorted(scores.keys(), key=lambda rid: scores[rid], reverse=True)


async def _run_rrf_merge(
    session: AsyncSession,
    filters: SearchFilters,
    stmt: Select,
    rank_col: Label[float],
    total: int,
    semantic: SemanticArm,
) -> tuple[list[Dataset], int]:
    """Merge FTS ranks with the vector arm through RRF and return one page.

    ``stmt`` is the vetted FTS statement (text clause only) and ``total`` the
    count over the shared candidate set. Above the row gate a full vector
    window reports one more than was counted so the router keeps emitting the
    ``next`` link; a non-full window is the exact tail.
    """
    page_end = filters.skip + filters.limit
    vector_ranks = semantic.ranks(page_end)

    # FTS-ranked ids, deep enough to cover the requested page plus RRF headroom.
    fts_cap = max(page_end * 3, 100)
    fts_stmt = (
        stmt.with_only_columns(Dataset.record_id)
        .order_by(rank_col.desc())
        .limit(fts_cap)
    )
    fts_result = await session.execute(fts_stmt)
    fts_ids = [str(row[0]) for row in fts_result.all()]

    if not semantic.exact and semantic.window_full:
        total += 1

    rrf_ordered = _compute_rrf_scores(fts_ids, vector_ranks)
    page_ids = rrf_ordered[filters.skip : page_end]

    if page_ids:
        fetch_stmt = (
            select(Dataset)
            .join(Record, Dataset.record_id == Record.id)
            .options(
                selectinload(Dataset.record).selectinload(Record.keywords),
                selectinload(Dataset.record).selectinload(Record.contacts),
                selectinload(Dataset.record).selectinload(Record.distributions),
                selectinload(Dataset.record).selectinload(Record.translations),
            )
            .where(Record.id.in_([uuid_mod.UUID(rid) for rid in page_ids]))
        )
        fetch_result = await session.execute(fetch_stmt)
        datasets_by_id = {
            str(d.record_id): d for d in fetch_result.unique().scalars().all()
        }
        datasets = [datasets_by_id[rid] for rid in page_ids if rid in datasets_by_id]
    else:
        datasets = []

    await _attach_updated_actor_identities(session, datasets)
    return datasets, total
