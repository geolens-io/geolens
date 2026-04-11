"""Shared embedding helpers used across AI, search, admin, and ingest modules."""

import time
import uuid

import httpx
import structlog
from openai import OpenAI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import reveal, settings
from app.embeddings.models import RecordEmbedding
from app.persistent_config import EMBEDDING_BASE_URL, OPENAI_BASE_URL

logger = structlog.stdlib.get_logger(__name__)

# Module-level client cache keyed by base_url (matches llm_loop.py pattern)
_cached_openai_clients: dict[str, OpenAI] = {}

# Short-lived cache for has_embeddings check (avoids DB round-trip per search)
_has_embeddings_cache: tuple[bool, float] | None = None
_HAS_EMBEDDINGS_TTL = 30.0  # seconds


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


async def resolve_embedding_base_url(session: AsyncSession) -> str:
    """Resolve the base URL for the embedding API with standard fallback chain."""
    embedding_url = await EMBEDDING_BASE_URL.get(session)
    return (
        embedding_url
        or await OPENAI_BASE_URL.get(session)
        or "https://api.openai.com/v1"
    )


def build_openai_client(base_url: str) -> OpenAI:
    """Return a cached OpenAI client for the given base URL."""
    if base_url not in _cached_openai_clients:
        _cached_openai_clients[base_url] = OpenAI(
            api_key=reveal(settings.openai_api_key),
            base_url=base_url,
            timeout=httpx.Timeout(60.0, connect=10.0),
            max_retries=2,
        )
    return _cached_openai_clients[base_url]


async def defer_embedding(dataset) -> None:
    """Defer an embedding generation task for a dataset. Non-fatal on failure."""
    try:
        from app.embeddings.tasks import embed_record

        await embed_record.defer_async(record_id=str(dataset.record.id))
    except Exception:
        logger.warning("Failed to defer embedding task", dataset_id=str(dataset.id))
