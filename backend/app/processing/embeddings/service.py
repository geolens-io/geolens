"""Embedding generation service: provider-agnostic vector generation via OpenAI-compatible API."""

import hashlib
import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.platform.extensions import get_embedding_provider
from app.processing.embeddings.helpers import resolve_live_embedding_config
from app.processing.embeddings.models import RecordEmbedding
from app.core.persistent_config import AI_ENABLED, EMBEDDING_DIMS, EMBEDDING_MODEL

logger = structlog.stdlib.get_logger(__name__)

# Max characters to send to the embedding API (defensive truncation)
_MAX_INPUT_CHARS = 100_000


class EmbeddingUnavailableError(Exception):
    """Raised when no embedding provider is configured."""


class _Unset:
    """Sentinel type: "the caller pinned nothing", distinct from a pinned None.

    fix(#1525): `None` is a legitimate RESOLVED endpoint — the provider
    interface lets an extension answer `{"base_url": None}` meaning "use
    the client default", and a run that snapshots that has pinned a real
    value. Testing `base_url is None` would read that pin as an omission
    and re-resolve per batch, defeating the pin for exactly the providers
    with an unusual endpoint config.

    `model`/`dimensions` keep their `is None` test: for those, `None`
    isn't something the config resolves to.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unset>"


_UNSET = _Unset()


async def generate_embedding(text: str, session: AsyncSession) -> list[float]:
    """Generate an embedding vector for the given text.

    Uses an OpenAI-compatible API (OpenAI, Ollama, Groq, Together, etc.).
    Model, dimensions, and base URL are read from PersistentConfig and the
    EmbeddingProviderExtension's resolve_runtime_config.

    The 130s provider timeout suits background paths (ingest, backfill);
    request-hot-path callers (semantic search) wrap this call in a short
    ``asyncio.wait_for`` instead — see service_semantic (fix #448).

    Raises:
        EmbeddingUnavailableError: if no OpenAI-compatible API key is configured.
    """
    vectors = await generate_embeddings_batch([text], session)
    return vectors[0]


async def resolve_embedding_base_url(session: AsyncSession) -> str | None:
    """Resolve the provider endpoint exactly as generate_embeddings_batch does.

    fix(#1525): a caller pinning a configuration for a whole run needs the
    endpoint too, from the provider rather than reading
    ``EMBEDDING_BASE_URL`` itself — the fallback chain (EMBEDDING_BASE_URL
    -> OPENAI_BASE_URL -> operator default, plus credential binding in
    ``app/core/ai_credentials.py``) belongs to the provider extension; a
    second copy here would drift from whatever provider is registered.
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

    fix(#448): callers chunk to a sane batch size (backfill uses 128; the
    OpenAI endpoint accepts up to 2048 inputs) instead of one record per API
    call. generate_embedding() delegates here with a one-element list.

    fix(#1511, #1525): ``model``/``dimensions``/``base_url`` let a caller
    that already resolved the config pin it for the whole run instead of
    re-reading on every call. Pinned by presence, not by not-None, because
    ``None`` is itself a resolved value (see ``_Unset``); omit an argument
    to keep the old per-call resolution.

    **A caller that writes its own ``model_name`` label MUST pass all
    three.** Without pinning, an admin swap mid-run has the provider
    generate from model B while rows stay labelled model A — search reads
    only active-model rows, so those vectors become invisible. A PARTIAL
    pin is worse than none: model A with model B's dimensions, or model A
    against a repointed endpoint, names a vector space nothing in the
    catalog can describe.

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

    # Hardcode "openai_compatible" — community ships one embedding provider;
    # overlays add more under different names.
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

    # Retry/backoff lives in DefaultOpenAIEmbeddingProvider.embed().
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
    model's native vector size.

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

    # dimensions=None means "discover natural dim size".
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


async def rebuild_embedding_column(db: AsyncSession, new_dims: int) -> bool:
    """Resize the embedding column to new_dims if it currently differs.

    Deletes all existing embeddings, drops the HNSW index, alters the
    column type, then recreates the index (skipped above pgvector's
    2000-dim HNSW limit — the column stays unindexed, searches use exact
    scans). Commits on success; rolls back on failure.

    The HNSW DDL is also issued by migration 0001_baseline for
    fresh-install/migrated-up environments; this handles the config-time
    dimension-change path the migration can't reproduce (dimension is set
    at runtime when a model is first configured). Both use ``CREATE INDEX
    IF NOT EXISTS`` semantics so they never conflict. Single
    implementation: the settings UI dimension-change handler imports and
    calls THIS function rather than keeping its own divergent copy.

    Returns True if rebuilt, False if dimensions were unchanged.
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
            # fix(#1287): the runtime role deliberately cannot own or
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
            # fix(#449): pgvector rejects HNSW on vector columns over 2000
            # dims; leave the column unindexed (exact-scan fallback) instead
            # of failing the whole dimension change.
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

    # fix(#1546): this function writes its own `model_name` label — the
    # case `generate_embeddings_batch` says MUST pin all three values. It
    # didn't: it labelled rows from `EMBEDDING_MODEL.get()` while letting
    # the provider re-read the config itself, so a swap between the two
    # calls produced a row labelled with one model holding another's
    # vector.
    #
    # The pin must be ONE verified set, resolved before anything depends
    # on the model name — assembling it from separate reads (a
    # `model_name` here, dimensions/endpoint further down) lets a settings
    # publish land in between and pin a triple that was never live, whose
    # fingerprint no live configuration will ever equal: the row is
    # invisible for good while looking stamped, worse than the unstamped
    # rows this column exists to tell apart.
    #
    # The model must come from the same verified set, not a separate
    # read, because the lookup below uses it to find the row this call
    # may UPDATE — a lookup under one model and a pin under another would
    # write the new model's vector into the old model's row (the #1511
    # bug by another route).
    # Costs the resolution on the record-touched, text-unchanged path; reading
    # the model first is what made the pin composable from two instants.
    resolved = await resolve_live_embedding_config(session, uncached=True, verify=True)
    if resolved is None:
        logger.warning(
            "Embedding configuration could not be resolved, skipping",
            record_id=str(record_id),
        )
        return False
    model_name, dimensions, base_url, config_fingerprint = resolved

    # Check existing embedding for hash match
    result = await session.execute(
        select(RecordEmbedding).where(
            RecordEmbedding.record_id == record_id,
            RecordEmbedding.model_name == model_name,
        )
    )
    existing = result.scalar_one_or_none()
    unchanged = existing is not None and existing.content_hash == content_hash

    # fix(#1546): an UNSTAMPED row predates the configuration stamp. Semantic
    # search still matches it on model name alone, so unchanged content is
    # still a skip — a record does not get re-embedded at provider cost just to
    # earn a stamp. A force regenerate is what replaces those.
    if unchanged and existing.config_fingerprint is None:
        logger.debug(
            "Hash unchanged, skipping embedding",
            record_id=str(record_id),
            content_hash=content_hash,
        )
        return False

    # fix(#1546): unchanged content is only a skip when the stored vector also
    # came from the configuration that is live now. A row stamped with another
    # one is invisible to semantic search, so leaving it in place would report
    # coverage the search cannot use — the same relocation of the bug that the
    # backfill's skip predicate had to close.
    if unchanged and existing.config_fingerprint == config_fingerprint:
        logger.debug(
            "Hash unchanged, skipping embedding",
            record_id=str(record_id),
            content_hash=content_hash,
        )
        return False

    # Generate embedding vector
    try:
        [vector] = await generate_embeddings_batch(
            [content_text],
            session,
            model=model_name,
            dimensions=dimensions,
            base_url=base_url,
        )
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
        # fix(#1546): re-stamp. The row is keyed (record_id, model_name), so a
        # configuration change that keeps the model lands HERE rather than on
        # the insert branch — leaving the old stamp would label the new vector
        # with the configuration of the one it replaced.
        existing.config_fingerprint = config_fingerprint
        # fix(#1580): the DB clock, not the app's — related items anchors
        # on a record's most recently written row, and a worker whose
        # clock runs behind the database's could write a row that sorts
        # BEFORE the one it replaced. `clock_timestamp()`, not `now()`:
        # `now()` is TRANSACTION-START time, so a slow job can commit a
        # LATER write with an EARLIER stamp. Both branches stamp
        # explicitly since the column's `server_default` is `now()` too,
        # and an INSERT taking the default would disagree with an UPDATE
        # that didn't.
        existing.updated_at = func.clock_timestamp()
    else:
        session.add(
            RecordEmbedding(
                record_id=record_id,
                embedding=vector,
                model_name=model_name,
                config_fingerprint=config_fingerprint,
                content_hash=content_hash,
                updated_at=func.clock_timestamp(),
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
