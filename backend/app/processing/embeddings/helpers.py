"""Shared embedding helpers used across AI, search, admin, and ingest modules."""

import time
import uuid

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.embeddings.models import RecordEmbedding

logger = structlog.stdlib.get_logger(__name__)

# Short-lived cache for has_embeddings check (avoids DB round-trip per search)
_has_embeddings_cache: tuple[bool, float] | None = None
_HAS_EMBEDDINGS_TTL = 30.0  # seconds


async def set_hnsw_recall(session: AsyncSession, *, ef: int = 100) -> None:
    """Tune HNSW ef_search for the current transaction.

    Default ``ef_search`` (40) misses relevant matches in recall-sensitive
    queries like related-items and semantic-search. ``SET LOCAL`` scopes the
    change to this transaction so other queries are unaffected.
    """
    await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(ef)}"))


async def has_embeddings(session: AsyncSession) -> bool:
    """Check whether any rows exist in catalog.record_embeddings.

    Result is cached in-memory for 30 seconds to avoid a DB round-trip
    on every semantic search call.
    """
    global _has_embeddings_cache
    now = time.monotonic()
    if _has_embeddings_cache and (now - _has_embeddings_cache[1]) < _HAS_EMBEDDINGS_TTL:
        return _has_embeddings_cache[0]
    result = await session.execute(
        text("SELECT EXISTS(SELECT 1 FROM catalog.record_embeddings)")
    )
    value = result.scalar_one()
    _has_embeddings_cache = (value, now)
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

        await embed_record.defer_async(record_id=str(dataset.record.id))
    except Exception:
        logger.warning("Failed to defer embedding task", dataset_id=str(dataset.id))
