"""Shared embedding helpers used across AI, search, admin, and ingest modules."""

import time
import uuid

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import defer_async_with_tenant
from app.platform.cache import tenant_cache_context_available, tenant_cache_key
from app.processing.embeddings.models import RecordEmbedding

logger = structlog.stdlib.get_logger(__name__)

# PERF-10 (Phase 274): cache key partitions on active embedding model name
# so an admin model swap invalidates stale yes/no answers within one cache
# miss. Without the partition, switching e.g. text-embedding-3-small ->
# all-MiniLM-L6-v2 in admin Settings would return the previous model's
# answer for up to 30 seconds.
_has_embeddings_cache: dict[str, tuple[bool, float]] = {}
_HAS_EMBEDDINGS_TTL = 30.0  # seconds
_HAS_EMBEDDINGS_MAX = 8  # bounded; operators rarely run more than 2-3 models

# fix(#1506): named so a caller can branch on "the model is unknown" without
# repeating the literal. Read-side callers may keep treating it as a name that
# matches no stored row; a WRITE-side caller has to check for it explicitly
# (see DefaultProcessingPort.get_records_without_embeddings).
UNKNOWN_EMBEDDING_MODEL = "__model_unknown__"


async def set_hnsw_recall(session: AsyncSession, *, ef: int = 100) -> None:
    """Tune HNSW ef_search for the current transaction.

    Default ``ef_search`` (40) misses relevant matches in recall-sensitive
    queries like related-items and semantic-search. ``SET LOCAL`` scopes the
    change to this transaction so other queries are unaffected.
    """
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef)}"))


async def resolve_embedding_model_name(
    session: AsyncSession, *, uncached: bool = False
) -> str:
    """Return the active embedding model name, or a sentinel on failure.

    fix(#1525 review r2, codex P1): ``uncached`` reads straight from the DB via
    ``PersistentConfig.get_uncached``, for the one caller that gates a
    destructive operation on this value. The cached read is right for
    everything else and stays the default; see `_snapshot_embedding_config` in
    `backfill.py` for why the backfill's pre-delete snapshot cannot use it.

    PERF-10 (Phase 274): the resolved name partitions the has_embeddings
    cache so a model swap forces a fresh DB lookup. Errors during
    persistent_config resolution (e.g. uninitialized cache, transient
    DB issue) fall back to ``"__model_unknown__"`` so the caller still
    gets a correct EXISTS result instead of a NoneType crash.

    fix(#1503): promoted from `_resolve_embedding_model_name` when admin's
    embedding-coverage stats became its second caller. The sentinel matches
    no stored `model_name`, so a caller that scopes a query by this value
    reports zero current-model coverage while the model is unknown — the
    same thing semantic search does in that state (its vector arm resolves
    the model too, and degrades to FTS-only when it cannot).

    fix(#1506): that "matches no row" property reads in opposite directions
    depending on which side of the query the caller is on. For a coverage
    COUNT it under-reports, which is the safe direction. For a "which records
    still need work" SELECT it over-reports — every record looks unembedded —
    so the backfill's caller compares against `UNKNOWN_EMBEDDING_MODEL` and
    refuses to run rather than scoping by it.
    """
    try:
        from app.core.persistent_config import EMBEDDING_MODEL

        value = await (
            EMBEDDING_MODEL.get_uncached(session)
            if uncached
            else EMBEDDING_MODEL.get(session)
        )
        return value or UNKNOWN_EMBEDDING_MODEL
    except Exception:  # broad: persistent_config resolution can fail for any DB/cache reason; fall back to sentinel
        logger.warning("has_embeddings_model_resolution_failed", exc_info=True)
        return UNKNOWN_EMBEDDING_MODEL


async def has_embeddings(session: AsyncSession) -> bool:
    """Check whether any rows exist in catalog.record_embeddings.

    Result is cached in-memory for 30 seconds, partitioned by the
    active embedding model name (PERF-10 / Phase 274) so a model
    swap in admin Settings invalidates stale answers. Unscoped
    multi-tenant requests fail closed before consulting either the
    database or the process-wide cache.
    """
    global _has_embeddings_cache
    now = time.monotonic()

    if not tenant_cache_context_available():
        return False

    model_key = tenant_cache_key(await resolve_embedding_model_name(session))
    entry = _has_embeddings_cache.get(model_key)
    if entry and (now - entry[1]) < _HAS_EMBEDDINGS_TTL:
        return entry[0]

    result = await session.execute(
        text(
            "SELECT EXISTS("
            "SELECT 1 FROM catalog.record_embeddings AS embedding "
            "JOIN catalog.records AS visible_record "
            "ON visible_record.id = embedding.record_id"
            ")"
        )
    )
    value = result.scalar_one()

    # Bounded eviction: drop oldest entry by stored monotonic timestamp
    # before insert when we're at capacity.
    if len(_has_embeddings_cache) >= _HAS_EMBEDDINGS_MAX:
        oldest = min(_has_embeddings_cache, key=lambda k: _has_embeddings_cache[k][1])
        del _has_embeddings_cache[oldest]
    _has_embeddings_cache[model_key] = (value, now)
    return value


async def get_nearest_record_ids(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    limit: int = 5,
    max_distance: float = 0.7,
) -> list[uuid.UUID]:
    """Return record IDs of the nearest neighbors by cosine distance.

    Excludes the given record_id. Returns an empty list when the record
    has no embedding or no neighbors are within the distance threshold.
    """
    # Get this record's embedding
    emb_result = await session.execute(
        select(RecordEmbedding.embedding)
        .join(RecordEmbedding.record)
        .where(RecordEmbedding.record_id == record_id)
        .limit(1)
    )
    embedding = emb_result.scalar_one_or_none()
    if embedding is None:
        return []

    await set_hnsw_recall(session)

    # Find nearest neighbors (exclude self)
    nn_stmt = (
        select(RecordEmbedding.record_id)
        .join(RecordEmbedding.record)
        .where(RecordEmbedding.record_id != record_id)
        .where(RecordEmbedding.embedding.cosine_distance(embedding) <= max_distance)
        .order_by(RecordEmbedding.embedding.cosine_distance(embedding))
        .limit(limit)
    )
    nn_result = await session.execute(nn_stmt)
    return [row[0] for row in nn_result.all()]


async def defer_embedding(dataset) -> None:
    """Defer an embedding generation task for a dataset. Non-fatal on failure."""
    try:
        from app.processing.embeddings.tasks import embed_record

        await defer_async_with_tenant(embed_record, record_id=str(dataset.record.id))
    except Exception:  # broad: defer is non-fatal; any job-runner/DB error should not block the parent flow
        logger.warning("Failed to defer embedding task", dataset_id=str(dataset.id))
