"""Embedding generation service: provider-agnostic vector generation via OpenAI-compatible API."""

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.processing.embeddings.helpers import build_openai_client, resolve_embedding_base_url
from app.processing.embeddings.models import RecordEmbedding
from app.core.persistent_config import AI_ENABLED, EMBEDDING_DIMS, EMBEDDING_MODEL

logger = structlog.stdlib.get_logger(__name__)

# Max characters to send to the embedding API (defensive truncation)
_MAX_INPUT_CHARS = 100_000


class EmbeddingUnavailableError(Exception):
    """Raised when no embedding provider is configured."""


async def generate_embedding(text: str, session: AsyncSession) -> list[float]:
    """Generate an embedding vector for the given text.

    Uses an OpenAI-compatible API (OpenAI, Ollama, Groq, Together, etc.).
    Model, dimensions, and base URL are read from PersistentConfig.

    Args:
        text: The text to embed.
        session: Database session for reading PersistentConfig values.

    Returns:
        A list of floats representing the embedding vector.

    Raises:
        EmbeddingUnavailableError: If no OpenAI-compatible API key is configured.
    """
    if not settings.openai_api_key:
        raise EmbeddingUnavailableError(
            "Embedding generation requires an OpenAI-compatible API key. "
            "Anthropic does not provide an embedding API. "
            "Set OPENAI_API_KEY and optionally OPENAI_BASE_URL for a compatible "
            "provider (OpenAI, Ollama, Groq, Together)."
        )

    model = await EMBEDDING_MODEL.get(session)
    dims = await EMBEDDING_DIMS.get(session)
    base_url = await resolve_embedding_base_url(session)

    # Truncate very long input
    if len(text) > _MAX_INPUT_CHARS:
        text = text[:_MAX_INPUT_CHARS]

    logger.info(
        "Generating embedding",
        model=model,
        dimensions=dims,
        text_length=len(text),
    )

    client = build_openai_client(base_url)

    try:
        response = await asyncio.to_thread(
            client.embeddings.create,
            model=model,
            input=text,
            dimensions=dims,
        )
    except Exception as exc:
        logger.error(
            "Embedding API call failed", error=str(exc), model=model, exc_info=True
        )
        raise EmbeddingUnavailableError(f"Embedding API call failed: {exc}") from exc

    return response.data[0].embedding


async def probe_embedding_dimensions(session: AsyncSession) -> int:
    """Probe the configured embedding model to detect its natural output dimensions.

    Sends a short test string *without* a dimensions parameter to discover the
    model's native vector size.

    Raises:
        EmbeddingUnavailableError: If no provider is configured or the API call fails.
    """
    if not settings.openai_api_key:
        raise EmbeddingUnavailableError(
            "Embedding generation requires an OpenAI-compatible API key."
        )

    model = await EMBEDDING_MODEL.get(session)
    base_url = await resolve_embedding_base_url(session)

    client = build_openai_client(base_url)

    try:
        response = await asyncio.to_thread(
            client.embeddings.create,
            model=model,
            input="dimension probe",
        )
    except Exception as exc:
        raise EmbeddingUnavailableError(f"Embedding probe failed: {exc}") from exc

    return len(response.data[0].embedding)


# ---------------------------------------------------------------------------
# Embedding column DDL helpers
# ---------------------------------------------------------------------------


async def rebuild_embedding_column(db: AsyncSession, new_dims: int) -> bool:
    """Resize the embedding column to new_dims if it currently differs.

    Deletes all existing embeddings, drops the HNSW index, alters the column
    type, then recreates the index. Commits on success; rolls back on failure.

    Returns True if the column was rebuilt, False if dimensions were unchanged.
    """
    from sqlalchemy import text as sa_text

    col_check = await db.execute(
        sa_text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    current_dims = col_check.scalar_one_or_none()
    if current_dims is None or current_dims == new_dims:
        return False

    try:
        await db.execute(sa_text("DELETE FROM catalog.record_embeddings"))
        await db.execute(
            sa_text("DROP INDEX IF EXISTS catalog.ix_record_embeddings_hnsw")
        )
        await db.execute(
            sa_text(
                f"ALTER TABLE catalog.record_embeddings "
                f"ALTER COLUMN embedding TYPE vector({new_dims}) "
                f"USING embedding::vector({new_dims})"
            )
        )
        await db.execute(
            sa_text(
                "CREATE INDEX ix_record_embeddings_hnsw "
                "ON catalog.record_embeddings USING hnsw (embedding vector_cosine_ops) "
                "WITH (m=16, ef_construction=64)"
            )
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.error("Failed to rebuild embedding column", exc_info=True)
        raise

    return True


# ---------------------------------------------------------------------------
# Embedding pipeline helpers
# ---------------------------------------------------------------------------


def build_content_text(
    *,
    title: str | None,
    summary: str | None,
    keywords: list[str] | None,
    lineage: str | None,
    raster_summary: str | None = None,
) -> str:
    """Concatenate non-None metadata fields into a single text for embedding."""
    parts: list[str] = []
    if title:
        parts.append(title)
    if summary:
        parts.append(summary)
    if keywords:
        parts.append(", ".join(keywords))
    if lineage:
        parts.append(lineage)
    if raster_summary:
        parts.append(raster_summary)
    return "\n".join(parts)


def compute_content_hash(text: str) -> str:
    """Return SHA-256 hex digest of text."""
    return hashlib.sha256(text.encode()).hexdigest()


async def generate_and_store_embedding(
    *,
    session: AsyncSession,
    record_id: uuid.UUID,
    title: str | None,
    summary: str | None,
    keywords: list[str] | None,
    lineage: str | None,
    raster_summary: str | None = None,
) -> bool:
    """Orchestrate embedding generation and storage.

    Non-fatal: catches all errors and logs warnings instead of raising.
    Skips silently when AI is disabled, content is empty, or hash is unchanged.

    Returns:
        True if an embedding was created/updated, False otherwise.
    """
    # Gate: AI must be enabled
    if not await AI_ENABLED.get(session):
        logger.debug("AI disabled, skipping embedding", record_id=str(record_id))
        return False

    # Build content and hash
    content_text = build_content_text(
        title=title,
        summary=summary,
        keywords=keywords,
        lineage=lineage,
        raster_summary=raster_summary,
    )
    if not content_text:
        logger.debug("Empty content, skipping embedding", record_id=str(record_id))
        return False

    content_hash = compute_content_hash(content_text)
    model_name = await EMBEDDING_MODEL.get(session)

    # Check existing embedding for hash match
    result = await session.execute(
        select(RecordEmbedding).where(
            RecordEmbedding.record_id == record_id,
            RecordEmbedding.model_name == model_name,
        )
    )
    existing = result.scalar_one_or_none()

    if existing and existing.content_hash == content_hash:
        logger.debug(
            "Hash unchanged, skipping embedding",
            record_id=str(record_id),
            content_hash=content_hash,
        )
        return False

    # Generate embedding vector
    try:
        vector = await generate_embedding(content_text, session)
    except EmbeddingUnavailableError:
        logger.warning(
            "Embedding unavailable, skipping",
            record_id=str(record_id),
        )
        return False
    except Exception:
        logger.error(
            "Embedding generation failed",
            record_id=str(record_id),
            exc_info=True,
        )
        return False

    # Upsert
    if existing:
        existing.embedding = vector
        existing.content_hash = content_hash
        existing.updated_at = datetime.now(timezone.utc)
    else:
        session.add(
            RecordEmbedding(
                record_id=record_id,
                embedding=vector,
                model_name=model_name,
                content_hash=content_hash,
            )
        )

    await session.flush()
    logger.info(
        "Embedding stored",
        record_id=str(record_id),
        model_name=model_name,
        action="update" if existing else "insert",
    )
    return True
