"""Embedding generation service: provider-agnostic vector generation via OpenAI-compatible API."""

import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import settings
from app.platform.extensions import get_embedding_provider, get_processing_port
from app.processing.embeddings.helpers import resolve_live_embedding_config
from app.processing.embeddings.models import RecordEmbedding
from app.core.persistent_config import (
    AI_ENABLED,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    apply_side_effects_batch,
)

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
    ``asyncio.wait_for`` instead — see service_semantic (fix(#448)).

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


class EmbeddingColumnRebuildError(RuntimeError):
    """The column rebuild failed and the embedding settings were put back."""


class EmbeddingChangeBusyError(RuntimeError):
    """Another embedding model or width change still holds the lock."""


_CHANGE_LOCK_SQL = (
    "SELECT pg_try_advisory_xact_lock(hashtextextended('geolens:embedding_change', 0))"
)


@asynccontextmanager
async def embedding_change_lock(
    needed: bool = True, *, db: AsyncSession | None = None
) -> AsyncIterator[None]:
    """Run one embedding model or width change at a time, from reading the old
    pair to the rebuild or restore. Does nothing unless ``needed``.

    The lock holds a connection of its own, outside the request pool: the
    change commits between those steps, and a burst of requests as large as
    the pool would otherwise each wait at checkout for a connection the others
    hold. ``db``, the request's session, has its read-only transaction ended
    first, so under transaction pooling a request trying the lock holds no
    other server connection. A second change is refused with
    EmbeddingChangeBusyError rather than queued.
    """
    if not needed:
        yield
        return
    if db is not None:
        await db.commit()
    from sqlalchemy import text as sa_text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.db import engine  # late-bound so a test engine applies

    lock_engine = create_async_engine(
        engine.url, poolclass=NullPool, connect_args=settings.database_connect_args
    )
    try:
        async with lock_engine.connect() as lock_connection:
            locked = await lock_connection.execute(sa_text(_CHANGE_LOCK_SQL))
            if not locked.scalar():
                raise EmbeddingChangeBusyError(
                    "Another embedding configuration change is in progress. "
                    "Retry once it finishes."
                )
            yield
    finally:
        await lock_engine.dispose()


@dataclass(frozen=True)
class CommittedEmbeddingPair:
    """The embedding settings a failed column rebuild puts back.

    ``model`` is None when the settings batch leaves the model alone. The
    ``*_overridden`` flags record whether the key had a stored override, so a
    restore deletes one the batch created instead of pinning the default.
    """

    dims: int
    model: str | None
    dims_overridden: bool
    model_overridden: bool


async def read_committed_embedding_pair(
    db: AsyncSession, *, with_model: bool
) -> CommittedEmbeddingPair:
    """Read before a settings batch writes. Uncached, so a rollback restores
    what is committed rather than a cache entry that may already be stale."""
    from app.core.db.models import AppSetting

    dims = await EMBEDDING_DIMS.get_uncached(db)
    model = await EMBEDDING_MODEL.get_uncached(db) if with_model else None
    overridden = set(
        (
            await db.execute(
                select(AppSetting.key).where(
                    AppSetting.key.in_((EMBEDDING_DIMS.key, EMBEDDING_MODEL.key))
                )
            )
        ).scalars()
    )
    return CommittedEmbeddingPair(
        dims=dims,
        model=model,
        dims_overridden=EMBEDDING_DIMS.key in overridden,
        model_overridden=EMBEDDING_MODEL.key in overridden,
    )


async def _restore_setting(
    db: AsyncSession,
    cfg: Any,
    value: Any,
    overridden: bool,
    *,
    user_id: uuid.UUID,
    ip_address: str | None,
) -> None:
    if overridden:
        await cfg.set(db, value, user_id=user_id, ip_address=ip_address, commit=False)
    else:
        await cfg.reset(db, user_id=user_id, ip_address=ip_address, commit=False)


async def rebuild_column_or_restore(
    db: AsyncSession,
    new_dims: int,
    previous: CommittedEmbeddingPair,
    *,
    user_id: uuid.UUID,
    ip_address: str | None,
) -> None:
    """Rebuild the column to the width a settings batch just committed.

    Callers hold ``embedding_change_lock`` from before they read
    ``previous``. On failure, restores ``previous`` and raises
    EmbeddingColumnRebuildError, so published settings never name a width the
    column does not have.
    """
    try:
        await rebuild_embedding_column(db, new_dims)
    except Exception as exc:  # broad: DDL rebuild can fail for schema/lock reasons; roll setting back atomically
        # A failure before the rebuild's own rollback leaves the transaction
        # aborted, and the restore below would fail on it.
        await db.rollback()
        # One transaction, then one side-effect step, so no reader sees the
        # new model beside the old width. Evicting before the commit would let
        # a concurrent reader re-cache the value being rolled back.
        await _restore_setting(
            db,
            EMBEDDING_DIMS,
            previous.dims,
            previous.dims_overridden,
            user_id=user_id,
            ip_address=ip_address,
        )
        rolled_back: list[tuple] = [(EMBEDDING_DIMS, previous.dims)]
        if previous.model is not None:
            await _restore_setting(
                db,
                EMBEDDING_MODEL,
                previous.model,
                previous.model_overridden,
                user_id=user_id,
                ip_address=ip_address,
            )
            rolled_back.append((EMBEDDING_MODEL, previous.model))
        await db.commit()
        await apply_side_effects_batch(rolled_back)
        logger.exception(
            "Embedding column rebuild failed, rolling back the embedding pair",
            old_dims=previous.dims,
            new_dims=new_dims,
            old_model=previous.model,
            rolled_back_model=previous.model is not None,
        )
        raise EmbeddingColumnRebuildError(
            "Embedding column rebuild failed. The embedding settings have "
            "been reverted to their previous values."
        ) from exc


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


def content_fields(record) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """The fields ``build_content_text`` reads, pulled off a record eagerly.

    Eager, because a rollback expires every ORM instance and a later attribute
    access raises ``MissingGreenlet``. One function for every reader so "is
    this record empty" and "is this record unchanged" are asked the same way.
    """
    return {
        "title": record.title,
        "summary": record.summary,
        "keywords": [kw.keyword for kw in record.keywords] if record.keywords else [],
        "lineage": record.lineage_summary,
        "localized_texts": [
            "\n".join(
                part
                for part in (
                    f"{translation.language}: {translation.title}",
                    translation.summary,
                )
                if part
            )
            for translation in record.translations
        ],
    }


async def raster_summary_of(session: AsyncSession, record) -> str | None:  # type: ignore[no-untyped-def]
    """The raster facts a raster dataset's embedded text carries, if any."""
    from app.processing.raster.models import RasterAsset

    if record.record_type != "raster_dataset":
        return None
    dataset_orm = get_processing_port().get_dataset_orm_class()
    ra = (
        await session.execute(
            select(
                RasterAsset.size_bytes,
                RasterAsset.res_x,
                RasterAsset.band_count,
                RasterAsset.dtype,
                RasterAsset.epsg,
                RasterAsset.compression,
            )
            .join(dataset_orm, RasterAsset.dataset_id == dataset_orm.id)
            .where(dataset_orm.record_id == record.id)
        )
    ).first()
    if ra is None:
        return None
    size_str = (
        f"{ra.size_bytes / (1024 * 1024):.1f}MB" if ra.size_bytes else "unknown size"
    )
    # res_x may be NULL, which the float format would raise on.
    res_str = f"{ra.res_x:.6f} resolution, " if ra.res_x is not None else ""
    return (
        f"GeoTIFF, {ra.band_count} band(s), {ra.dtype}, "
        f"{res_str}EPSG:{ra.epsg}, "
        f"{ra.compression} compression, {size_str}"
    )


def _comparable(fields: dict[str, Any]) -> dict[str, Any]:
    # Keywords have no load order, so two reads of the same set may differ.
    return {**fields, "keywords": sorted(fields["keywords"])}


async def records_still_current(
    session: AsyncSession, observed: dict[Any, dict[str, Any]]
) -> set[Any]:
    """The observed records whose ``content_fields`` are unchanged.

    An observed ``raster_summary`` is compared as well. The records stay
    share-locked until the caller commits, so an edit waits for the embedding
    write and then queues its own re-embed; raster publishes lock the record
    row too. A deleted record is not current.
    """
    record_orm = get_processing_port().get_record_orm_class()
    ids = list(observed)
    # Lock, then read in a later statement: a locking statement that waited on
    # an edit returns joined rows from the snapshot it started with.
    await session.execute(
        select(record_orm.id)
        .where(record_orm.id.in_(ids))
        .order_by(record_orm.id)
        .with_for_update(read=True)
    )
    result = await session.execute(
        select(record_orm)
        .options(joinedload(record_orm.keywords), selectinload(record_orm.translations))
        .where(record_orm.id.in_(ids))
        # The caller's identity map may still hold these records as first read.
        .execution_options(populate_existing=True)
    )
    current = {}
    for record in result.unique().scalars().all():
        fields = content_fields(record)
        if "raster_summary" in observed.get(record.id, {}):
            fields["raster_summary"] = await raster_summary_of(session, record)
        current[record.id] = _comparable(fields)
    return {
        record_id
        for record_id, fields in observed.items()
        if current.get(record_id) == _comparable(fields)
    }


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
    observed: dict[str, Any] | None = None,
) -> bool:
    """Orchestrate embedding generation and storage.

    Non-fatal: catches all errors and logs warnings instead of raising.
    Skips silently when AI is disabled, content is empty, or hash is unchanged.
    ``observed`` is what the text was built from: the record's
    ``content_fields``, plus its ``raster_summary`` when that was included.
    When given, the vector is stored only if the record still holds them.

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

    if observed is not None and record_id not in await records_still_current(
        session, {record_id: observed}
    ):
        logger.info(
            "Record changed while embedding, skipping", record_id=str(record_id)
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
