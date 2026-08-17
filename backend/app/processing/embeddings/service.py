"""Embedding generation service: provider-agnostic vector generation via OpenAI-compatible API."""

import hashlib
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.platform.extensions import get_embedding_provider
from app.processing.embeddings.models import RecordEmbedding
from app.core.persistent_config import AI_ENABLED, EMBEDDING_DIMS, EMBEDDING_MODEL

logger = structlog.stdlib.get_logger(__name__)

# Max characters to send to the embedding API (defensive truncation)
_MAX_INPUT_CHARS = 100_000


class EmbeddingUnavailableError(Exception):
    """Raised when no embedding provider is configured."""


class _Unset:
    """Sentinel type: "the caller pinned nothing", distinct from a pinned None.

    fix(#1525 review, codex P2): `None` is a legitimate RESOLVED endpoint. The
    provider interface lets an extension answer `{"base_url": None}`, meaning
    "use the client default", and a run that snapshots that has pinned a real
    value. Testing `base_url is None` would read that pin as an omission and
    re-resolve per batch, so the providers most likely to have an unusual
    endpoint config are exactly the ones the pin would stop protecting.

    `model` and `dimensions` keep their `is None` test: for those, `None` is
    not something the config resolves to, and the falsy fallback below already
    covers the resolved-but-empty case.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unset>"


_UNSET = _Unset()


async def generate_embedding(text: str, session: AsyncSession) -> list[float]:
    """Generate an embedding vector for the given text.

    Uses an OpenAI-compatible API (OpenAI, Ollama, Groq, Together, etc.).
    Model, dimensions, and base URL are read from PersistentConfig and the
    EmbeddingProviderExtension's resolve_runtime_config (Phase 231 D-21).

    The 130s provider timeout suits background paths (ingest, backfill);
    request-hot-path callers (semantic search) wrap this call in a short
    ``asyncio.wait_for`` instead — see service_semantic (fix #448).

    Args:
        text: The text to embed.
        session: Database session for reading PersistentConfig values.

    Returns:
        A list of floats representing the embedding vector.

    Raises:
        EmbeddingUnavailableError: If no OpenAI-compatible API key is configured.
    """
    vectors = await generate_embeddings_batch([text], session)
    return vectors[0]


async def resolve_embedding_base_url(session: AsyncSession) -> str | None:
    """Resolve the provider endpoint exactly as generate_embeddings_batch does.

    fix(#1525): a caller pinning a configuration for a whole run needs the
    endpoint too, and has to get it from the provider rather than reading
    ``EMBEDDING_BASE_URL`` itself. The fallback chain (EMBEDDING_BASE_URL ->
    OPENAI_BASE_URL -> the operator-approved default, plus the credential
    binding in ``app/core/ai_credentials.py``) belongs to the provider
    extension; a second copy of it in the caller would drift from whatever
    provider is actually registered.
    """
    provider_ext = get_embedding_provider("openai_compatible")
    runtime_config = await provider_ext.resolve_runtime_config(session)
    return runtime_config.get("base_url")


async def generate_embeddings_batch(
    texts: list[str],
    session: AsyncSession,
    *,
    model: str | None = None,
    dimensions: int | None = None,
    base_url: str | None | _Unset = _UNSET,
) -> list[list[float]]:
    """Generate embedding vectors for many texts in ONE provider call.

    fix(#448): the backfill previously embedded one record per API call even
    though the provider accepts input lists. Callers chunk to a sane batch
    size (backfill uses 128; the OpenAI endpoint accepts up to 2048 inputs).
    Config resolution and retry semantics are identical to the single-text
    path — generate_embedding() delegates here with a one-element list.

    fix(#1511 review): ``model`` and ``dimensions`` let a caller that already
    resolved the pair pin it for the whole run instead of having this function
    re-read the config on every call. fix(#1525): ``base_url`` completes the
    set — the label a run writes names a model, and which endpoint served that
    model is part of what the label promises. It is pinned by presence rather
    than by not-None, because ``None`` is a value the config can resolve TO
    (see ``_Unset``); omit the argument to keep the old per-call resolution.

    **A caller that writes its own ``model_name`` label MUST pass all three.**
    Such a caller resolves the model once to label its rows; without pinning,
    this function re-reads the config per call, so an admin swap mid-run has the
    provider generate from model B while the rows are labelled model A. Search
    reads only active-model rows, so those vectors are invisible to the model
    that supposedly produced them. Passing a subset is worse than passing none:
    model A with model B's dimensions is a pair that never existed in config,
    and model A against a repointed endpoint is a vector space nothing in the
    catalog can name. Today `processing/embeddings/backfill.py` is the only such
    caller; `generate_embedding` above makes a single call and labels nothing,
    so it deliberately does not pin.

    Omitting them keeps the pre-existing per-call resolution, which is correct
    for a single-call caller and silently racy for a multi-call labelling one.
    Nothing enforces that distinction mechanically, so it is stated here.

    Returns vectors in the same order as ``texts``.

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

    # Phase 231 D-12: hardcode "openai_compatible" — community ships one
    # embedding provider; overlays add more under different names.
    provider_ext = get_embedding_provider("openai_compatible")
    # fix(#1525): resolve the live config only when something below would still
    # come out of it. A fully pinned call needs nothing from it, and asking
    # anyway reopens the window the pin exists to close: the shipped provider's
    # resolve RAISES (not diverges) once an admin repoints the endpoint, because
    # `bind_openai_credential_base_url` refuses to aim the environment API key at
    # a database-supplied URL. Every batch after such an edit then failed, was
    # retried per record, failed again and counted as an error — a run pinned to
    # a configuration it had already validated, abandoning the catalog over a
    # value it was no longer going to use.
    #
    # The gate is the exact set of conditions under which a value is taken from
    # `runtime_config` below, so nothing else about resolution order changes.
    runtime_config: dict[str, object] = {}
    if not model or not dimensions or isinstance(base_url, _Unset):
        runtime_config = await provider_ext.resolve_runtime_config(session)
    # `is None` rather than falsy: a pinned value the caller supplied is
    # honored as given, and only an absent one re-reads the config. Both then
    # fall back to the provider default exactly as an empty config value does.
    if model is None:
        model = await EMBEDDING_MODEL.get(session)
    model = model or runtime_config.get("default_model")
    if dimensions is None:
        dimensions = await EMBEDDING_DIMS.get(session)
    dimensions = dimensions or runtime_config.get("default_dims")
    if isinstance(base_url, _Unset):
        base_url = runtime_config.get("base_url")

    # Truncate very long inputs
    texts = [t[:_MAX_INPUT_CHARS] if len(t) > _MAX_INPUT_CHARS else t for t in texts]

    logger.info(
        "Generating embeddings",
        model=model,
        dimensions=dimensions,
        batch_size=len(texts),
        text_length=sum(len(t) for t in texts),
    )

    # Phase 231 D-22: retry/backoff lives in DefaultOpenAIEmbeddingProvider.embed().
    # The provider raises EmbeddingUnavailableError on terminal failure (no
    # service-level retry needed — single source of truth).
    return await provider_ext.embed(
        texts=texts,
        model=model,
        dimensions=dimensions,
        base_url=base_url,
        timeout=130.0,
    )


async def probe_embedding_dimensions(session: AsyncSession) -> int:
    """Probe the configured embedding model to detect its natural output dimensions.

    Sends a short test string *without* a dimensions parameter to discover the
    model's native vector size (Phase 231 D-21).

    Raises:
        EmbeddingUnavailableError: If no provider is configured or the API call fails.
    """
    if not settings.openai_api_key:
        raise EmbeddingUnavailableError(
            "Embedding generation requires an OpenAI-compatible API key."
        )

    provider_ext = get_embedding_provider("openai_compatible")
    runtime_config = await provider_ext.resolve_runtime_config(session)
    model = await EMBEDDING_MODEL.get(session) or runtime_config.get("default_model")
    base_url = runtime_config.get("base_url")

    # Phase 231 D-02: dimensions=None means "discover natural dim size".
    # The provider's retry/backoff loop handles transient failures.
    vectors = await provider_ext.embed(
        texts=["dimension probe"],
        model=model,
        dimensions=None,
        base_url=base_url,
        timeout=30.0,
    )
    embedding = vectors[0] if vectors else []
    if not embedding:
        raise EmbeddingUnavailableError(
            f"Embedding probe for model '{model}' returned empty vector."
        )
    return len(embedding)


# ---------------------------------------------------------------------------
# Embedding column DDL helpers
# ---------------------------------------------------------------------------


async def rebuild_embedding_column(db: AsyncSession, new_dims: int) -> bool:
    """Resize the embedding column to new_dims if it currently differs.

    Deletes all existing embeddings, drops the HNSW index, alters the column
    type, then recreates the index (skipped above pgvector's 2000-dim HNSW
    limit — the column stays unindexed and searches use exact scans).
    Commits on success; rolls back on failure.

    DBM-07 (Phase 271): The HNSW DDL is also issued by migration 0001_baseline for
    fresh-install / migrated-up environments. This function handles the
    config-time dimension-change path that the migration cannot reproduce
    (column dimension is set at runtime when an embedding model is first
    configured). Both paths use ``CREATE INDEX IF NOT EXISTS`` semantics
    (the migration uses an explicit ``IF NOT EXISTS``; this function
    recreates the index after a DROP) so they are idempotent and never
    conflict. This is the single implementation: the settings UI
    dimension-change handler in ``backend/app/modules/settings/router.py``
    imports and calls THIS function (BUG-029 removed the divergent
    error-swallowing copy that previously shadowed it there).

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
        if settings.geolens_runtime_db_role:
            # fix(#1287 review): the runtime role deliberately cannot own or
            # alter catalog relations. The privileged reconciler installs this
            # bounded SECURITY DEFINER operation with PUBLIC execute revoked.
            rebuild_result = await db.execute(
                sa_text("SELECT catalog.geolens_rebuild_embedding_column(:new_dims)"),
                {"new_dims": new_dims},
            )
            rebuilt = bool(rebuild_result.scalar_one())
            await db.commit()
            return rebuilt

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
        if new_dims <= 2000:
            await db.execute(
                sa_text(
                    "CREATE INDEX ix_record_embeddings_hnsw "
                    "ON catalog.record_embeddings USING hnsw (embedding vector_cosine_ops) "
                    "WITH (m=16, ef_construction=64)"
                )
            )
        else:
            # fix(#449, codex P1): pgvector rejects HNSW on vector columns over
            # 2000 dims; leave the column unindexed (exact-scan fallback)
            # instead of failing the whole dimension change.
            logger.warning(
                "Skipping HNSW index: %s dims exceeds pgvector's 2000-dim limit",
                new_dims,
            )
        await db.commit()
    except Exception:  # broad: DDL (DROP INDEX, ALTER COLUMN) can fail for schema/lock reasons; re-raise to caller
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
    localized_texts: list[str] | None = None,
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
    if localized_texts:
        parts.extend(localized_texts)
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
    localized_texts: list[str] | None = None,
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
        localized_texts=localized_texts,
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
    except Exception:  # broad: embedding API can throw beyond EmbeddingUnavailableError; non-fatal, log and skip
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
