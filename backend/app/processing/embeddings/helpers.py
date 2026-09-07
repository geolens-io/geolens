"""Shared embedding helpers used across AI, search, admin, and ingest modules."""

import hashlib
import json
import time
import uuid

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import defer_async_with_tenant
from app.platform.cache import tenant_cache_context_available, tenant_cache_key
from app.processing.embeddings.models import RecordEmbedding

logger = structlog.stdlib.get_logger(__name__)

# Cache key partitions on active embedding model name
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

# fix(#1546): the sibling of the above for the whole configuration. Not a hex
# digest, so it can never collide with a real fingerprint and therefore matches
# no STAMPED row. It does still match an unstamped one, which is the same
# grandfathering `RecordEmbedding.usable_by_config` applies everywhere else.
UNKNOWN_EMBEDDING_CONFIG = "__config_unknown__"


# fix(#1546): ceiling on how far an iterative scan will go
# looking for rows that survive the filter. pgvector's own default is 20000;
# stating it here makes the bound visible at the one place iterative scan is
# turned on, and keeps a pathological catalog from turning one search into a
# full index walk.
_HNSW_MAX_SCAN_TUPLES = 20000


async def set_hnsw_recall(session: AsyncSession, *, ef: int = 100) -> None:
    """Tune HNSW recall for the current transaction.

    Default ``ef_search`` (40) misses relevant matches in recall-sensitive
    queries (related-items, semantic-search). ``SET LOCAL`` scope only.

    fix(#1546): iterative scan too, because every caller filters the
    index's output AFTER the approximate scan picks candidates — without
    it, a catalog whose nearest rows are mostly filtered out (partial
    regenerate, or two models in one index) can have every candidate
    discarded before a usable one is visited, and search silently
    degrades to FTS while matching vectors sit in the table.

    ``relaxed_order``: the caller re-ranks distances and merges with FTS
    via RRF, so reordering costs nothing. Needs pgvector >= 0.8.0
    (shipped: 0.8.5); older pgvector degrades to an inert placeholder GUC
    rather than erroring.

    One statement, not three — ``SET LOCAL`` carries only one setting.
    """
    await session.execute(
        text(
            "SELECT set_config('hnsw.ef_search', :ef, true), "
            "set_config('hnsw.iterative_scan', 'relaxed_order', true), "
            "set_config('hnsw.max_scan_tuples', :max_scan_tuples, true)"
        ),
        {"ef": str(int(ef)), "max_scan_tuples": str(_HNSW_MAX_SCAN_TUPLES)},
    )


async def resolve_embedding_model_name(
    session: AsyncSession, *, uncached: bool = False
) -> str:
    """Return the active embedding model name, or a sentinel on failure.

    fix(#1525): ``uncached`` reads straight from the DB, for the one
    caller gating a destructive operation on this value; cached is the
    default otherwise (see ``_snapshot_embedding_config`` in backfill.py
    for why the pre-delete snapshot can't use it).

    Partitions the has_embeddings cache so a model swap forces a fresh
    lookup. Resolution errors fall back to ``"__model_unknown__"`` for a
    correct EXISTS result instead of a crash.

    fix(#1506): the sentinel's "matches no row" property reads OPPOSITE
    directions per caller — a coverage COUNT under-reports (safe), but a
    "which records still need work" SELECT over-reports (every record
    looks unembedded), so the backfill caller compares against
    ``UNKNOWN_EMBEDDING_MODEL`` directly rather than scoping a query by it.
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


def embedding_config_fingerprint(
    model_name: str, dimensions: int | None, base_url: str | None
) -> str:
    """Identity of the configuration a stored vector came out of (#1546).

    The three arguments are the whole of what decides the vector space: the
    model, the width it was asked for, and the endpoint that served it. Two
    rows with the same fingerprint are comparable; two with different ones
    are not, whatever their `model_name` says.

    SHA-256 over a canonical JSON array, not Python's `hash()` (salted per
    interpreter via `PYTHONHASHSEED`, so rows stamped by one worker would be
    invisible to the next after a restart). JSON, not a delimiter join,
    keeps `None` distinct from `"None"`/`""` and escapes strings so
    `("a|b", None)` can't collide with `("a", "b|None")`.

    A change to WHICH values make up the identity changes every fingerprint
    and requires a catalog-wide re-embed — do not extend this lightly.
    """
    payload = json.dumps(
        [model_name, dimensions, base_url],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def resolve_live_embedding_config(
    session: AsyncSession,
    *,
    model_name: str | None = None,
    uncached: bool = False,
    verify: bool = False,
) -> tuple[str, int | None, str | None, str] | None:
    """The live (model, dimensions, endpoint, fingerprint), or None if unresolvable.

    fix(#1546): callers need the TRIPLE, not just the fingerprint — search
    filters stored rows on the fingerprint and must generate its query
    vector under the SAME configuration, so returning all four as one read
    (not two) stops a settings change mid-resolve from comparing vector B
    against fingerprint A. None means unresolvable: no safe comparison, and
    the next provider call would fail the same way.

    ``verify`` is for callers that STAMP what they resolve: three separate
    ``get`` calls can straddle a config publish and pin a triple that was
    never live. Self-correcting for a READER (fingerprints to nothing
    stored, search degrades to FTS once); permanent for a WRITER (the row
    is stamped invisible-for-good while looking stamped). So ``verify``
    resolves twice, requires agreement, pairs with ``uncached`` — the same
    guarantee `_snapshot_embedding_config` gives the ingest writer — and
    retries once before answering None.

    Readers skip ``verify``: doubling config reads on the search hot path
    would buy a fallback they already have.
    """
    for _ in range(2):
        resolved = await _resolve_live_embedding_config(
            session, model_name=model_name, uncached=uncached
        )
        if resolved is None or not verify:
            return resolved
        confirmation = await _resolve_live_embedding_config(
            session, model_name=model_name, uncached=uncached
        )
        if confirmation == resolved:
            return resolved
        logger.warning(
            "embedding_config_changed_while_being_read",
            first=resolved[3],
            second=None if confirmation is None else confirmation[3],
        )
    return None


async def resolve_embedding_config_fingerprint(
    session: AsyncSession,
    *,
    model_name: str | None = None,
    uncached: bool = False,
) -> str:
    """Fingerprint the LIVE embedding configuration, or answer with a sentinel.

    fix(#1546): the read-side counterpart of `embedding_config_fingerprint`
    — writers stamp from the configuration they PINNED; readers ask this
    what the live configuration is. ``model_name``, when a caller already
    resolved it, makes the model they filter on and the model inside the
    fingerprint one read that can't straddle a config change.

    Never raises: the shipped provider's endpoint resolution raises when
    the DB endpoint diverges from the operator-approved URL
    (`ai_credentials.bind_openai_credential_base_url`), so an unresolvable
    configuration answers `UNKNOWN_EMBEDDING_CONFIG` instead (same safe
    under-report as `resolve_embedding_model_name`'s sentinel) rather than
    taking search down over a setting it's only consulting to be careful.

    Cached by default, unlike the backfill's pre-delete snapshot — a
    reader has nothing to destroy, so a stale entry only degrades search
    to FTS for one cache TTL and heals itself.

    Trap: "never raises" doesn't cover a DATABASE error on `session`,
    which aborts the transaction regardless. Every caller today sits
    inside a broad handler that degrades anyway, so this changes nothing;
    a caller that wants to keep using the session needs a SAVEPOINT.
    """
    resolved = await _resolve_live_embedding_config(
        session, model_name=model_name, uncached=uncached
    )
    return UNKNOWN_EMBEDDING_CONFIG if resolved is None else resolved[3]


async def _resolve_live_embedding_config(
    session: AsyncSession,
    *,
    model_name: str | None = None,
    uncached: bool = False,
) -> tuple[str, int | None, str | None, str] | None:
    """Read the live configuration once, or answer None. Never raises."""
    from app.core.persistent_config import EMBEDDING_DIMS

    try:
        if model_name is None:
            model_name = await resolve_embedding_model_name(session, uncached=uncached)
        if model_name == UNKNOWN_EMBEDDING_MODEL:
            return None
        dimensions = await (
            EMBEDDING_DIMS.get_uncached(session)
            if uncached
            else EMBEDDING_DIMS.get(session)
        )
        # Imported in-function because the edge runs the other way at module
        # level: `service` imports `embedding_config_fingerprint` from here, so
        # a module-level import back would be a cycle.
        from app.processing.embeddings.service import resolve_embedding_base_url

        base_url = await resolve_embedding_base_url(session)
    except Exception:  # broad: config/provider resolution fails for many reasons; a reader must degrade, not raise
        logger.warning("embedding_config_unresolved", exc_info=True)
        return None
    return (
        model_name,
        dimensions,
        base_url,
        embedding_config_fingerprint(model_name, dimensions, base_url),
    )


async def has_embeddings(session: AsyncSession) -> bool:
    """Check whether any rows exist in catalog.record_embeddings.

    Result is cached in-memory for 30 seconds, partitioned by the
    active embedding model name (PERF-10) so a model
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


async def get_anchor_embedding_row(
    session: AsyncSession, record_id: uuid.UUID
) -> tuple[list[float], str, str | None] | None:
    """The stored row a similarity comparison for ``record_id`` is anchored on.

    Returns ``(embedding, model_name, config_fingerprint)``, or None when the
    record has no vector at all.

    fix(#1580): ONE definition of "the anchor row", read once. Two separate
    reads (rank against one, score against another) could land on different
    models after a model swap, since a record holds one row per model
    (``uq_record_embedding_model``). The identity travels with the vector
    because a bare list of floats doesn't say which model produced it;
    downstream filters with ``RecordEmbedding.usable_by_stored_anchor``.

    Row choice, in order: the live-usable row (so related items agrees with
    search by construction, including after a model rollback), then most
    recent, then model name for stability. Recency is a weak tiebreak only:
    ``now()`` is transaction-START time, so a slow job can commit a LATER
    write with an EARLIER stamp; ``clock_timestamp()`` fixes new writes (see
    ``service.py``) but older rows still carry the old semantics.

    RLS boundary: ``record_embeddings`` carries no ``tenant_id`` of its own,
    so the join to ``catalog.records`` is what scopes it — see
    ``test_embedding_helper_queries_join_rls_visible_records``.
    """
    live_model = await resolve_embedding_model_name(session)
    live_fingerprint = await resolve_embedding_config_fingerprint(
        session, model_name=live_model
    )
    result = await session.execute(
        select(
            RecordEmbedding.embedding,
            RecordEmbedding.model_name,
            RecordEmbedding.config_fingerprint,
        )
        .join(RecordEmbedding.record)
        .where(RecordEmbedding.record_id == record_id)
        .order_by(
            RecordEmbedding.usable_by_config(live_model, live_fingerprint).desc(),
            RecordEmbedding.updated_at.desc(),
            RecordEmbedding.model_name,
        )
        .limit(1)
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    return (row[0], row[1], row[2])


async def get_nearest_record_ids(
    session: AsyncSession,
    record_id: uuid.UUID,
    *,
    anchor: tuple[list[float], str, str | None] | None = None,
    limit: int = 5,
    max_distance: float = 0.7,
) -> list[uuid.UUID]:
    """Return record IDs of the nearest neighbors by cosine distance.

    Excludes the given record_id. Returns an empty list when the record
    has no embedding or no neighbors are within the distance threshold.

    fix(#1580): neighbours are restricted to the anchor row's own vector
    space via ``usable_by_stored_anchor`` — same model AND same stamp as
    the ANCHOR, not the live configuration, so a record embedded under a
    superseded configuration still finds its own neighbours instead of
    being compared against a space it was never in. Without this a catalog
    holding two models' rows returned well-formed, meaningless distances.

    Relies on ``set_hnsw_recall``'s iterative scan (already called by the
    time this runs) so this predicate doesn't starve the approximate scan:
    without it, a catalog whose nearest rows are mostly foreign-space
    returns nothing while usable vectors sit in the table.
    """
    # fix(#1580): the caller may hand its anchor in (the one that scores
    # results afterwards does), avoiding a second READ COMMITTED read that
    # could land a newer row than the one just ranked. Optional because
    # metadata_service reads neighbours with no anchor of its own to disagree
    # with.
    if anchor is None:
        anchor = await get_anchor_embedding_row(session, record_id)
    if anchor is None:
        return []
    embedding, model_name, config_fingerprint = anchor

    await set_hnsw_recall(session)

    # Find nearest neighbors (exclude self)
    nn_stmt = (
        select(RecordEmbedding.record_id)
        .join(RecordEmbedding.record)
        .where(RecordEmbedding.record_id != record_id)
        .where(RecordEmbedding.usable_by_stored_anchor(model_name, config_fingerprint))
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
