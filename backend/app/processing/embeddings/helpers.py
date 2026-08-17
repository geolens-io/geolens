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

# fix(#1546): the sibling of the above for the whole configuration. Not a hex
# digest, so it can never collide with a real fingerprint and therefore matches
# no STAMPED row. It does still match an unstamped one, which is the same
# grandfathering `RecordEmbedding.usable_by_config` applies everywhere else.
UNKNOWN_EMBEDDING_CONFIG = "__config_unknown__"


# fix(#1546 review r2, codex P2): ceiling on how far an iterative scan will go
# looking for rows that survive the filter. pgvector's own default is 20000;
# stating it here makes the bound visible at the one place iterative scan is
# turned on, and keeps a pathological catalog from turning one search into a
# full index walk.
_HNSW_MAX_SCAN_TUPLES = 20000


async def set_hnsw_recall(session: AsyncSession, *, ef: int = 100) -> None:
    """Tune HNSW recall for the current transaction.

    Default ``ef_search`` (40) misses relevant matches in recall-sensitive
    queries like related-items and semantic-search. These are transaction-local
    (``set_config(..., is_local => true)`` is ``SET LOCAL``), so other queries
    are unaffected.

    fix(#1546 review r2, codex P2): iterative scan, because every caller filters
    the index's output AFTER the approximate scan has chosen its candidates.
    Semantic search asks for rows a configuration can use; related-items asks
    for a record's neighbours. With a fixed ``ef_search`` and no iterative scan
    the index hands back at most that many candidates and the filter runs on
    them, so a catalog whose nearest neighbours are mostly rows the filter
    rejects can have every candidate discarded before a usable one is visited.
    Semantic search then returns nothing and silently falls back to FTS while
    matching vectors sit in the table.

    A partly complete regenerate after a configuration change is the realistic
    way to get there: most rows carry the superseded stamp, and they are exactly
    as near the query as their replacements would be. #1546 widened the
    predicate, so it widened this, but it did not create it — a model-only
    filter starves the same way on a catalog holding two models' rows in one
    index, which is the state #1506 was written for.

    ``relaxed_order`` rather than ``strict_order``: the caller turns distances
    into positional ranks and merges them with FTS through RRF, so a slight
    reordering inside the returned window costs nothing, and relaxed is the
    cheaper mode. Needs pgvector >= 0.8.0; the shipped image installs
    ``postgresql-18-pgvector`` from PGDG (0.8.5 at time of writing). On an older
    pgvector the setting is accepted as an inert placeholder rather than an
    error, because Postgres allows any ``prefix.name`` GUC, so this degrades to
    the previous behaviour instead of failing the query.

    One statement rather than three: this runs on the search hot path, and
    ``SET LOCAL`` cannot carry more than one setting.
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


def embedding_config_fingerprint(
    model_name: str, dimensions: int | None, base_url: str | None
) -> str:
    """Identity of the configuration a stored vector came out of (#1546).

    The three arguments are the whole of what decides the vector space: the
    model, the width it was asked for, and the endpoint that served it. Two
    rows with the same fingerprint are comparable; two with different ones are
    not, whatever their `model_name` says.

    Stable across restarts and across processes. SHA-256 over a canonical JSON
    array, deliberately NOT Python's `hash()`, which is salted per interpreter
    (`PYTHONHASHSEED`) and would give the same configuration a different
    identity after every restart — rows stamped by one worker would then be
    invisible to the next.

    JSON rather than a delimiter join: it keeps `None` distinct from the string
    `"None"` and from `""` (all three are reachable — an unset endpoint
    resolves to `None`, an unset width to `None`), and it escapes the strings,
    so ("a|b", None) cannot collide with ("a", "b|None").

    A change to WHICH values make up the identity changes every fingerprint,
    which reads as a configuration change to every reader and makes existing
    rows invisible until they are regenerated. That is the honest outcome — a
    different notion of identity really does mean the old stamps are not
    comparable — but it is a catalog-wide re-embed, so do not extend this
    lightly.
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

    fix(#1546 review r1, codex P1): callers need the TRIPLE, not only its
    fingerprint. Semantic search filters stored rows on the fingerprint and
    must generate its query vector under the very same configuration; handing
    it the fingerprint alone left the provider call free to re-resolve, so a
    settings change between the two produced a vector from configuration B
    cached under, and compared against, configuration A. Returning all four
    together is what makes "the identity I filtered on" and "the identity that
    produced the vector" one object rather than two reads.

    None means the configuration could not be resolved. A caller that cannot
    name the configuration cannot safely compare vectors against anything, and
    the provider call it would make next resolves through the same machinery
    and would fail too, so the honest answer is to stop rather than to guess.

    fix(#1546 review r3, codex P2): ``verify`` is for callers that STAMP what
    they resolve. The three values come from three ``get`` calls, and
    `PersistentConfig.set` says the quiet part out loud: committing then
    evicting as one step makes the WRITER atomic and does nothing for a reader,
    whose separate ``get`` calls sample at different instants and can straddle
    the whole step. Composing a pin that way can produce (old model, new
    dimensions, new endpoint) — a triple that was never live.

    For a READER that mismatch is self-correcting: it fingerprints to something
    no stored row carries, so semantic search matches nothing and degrades to
    FTS for one request. For a WRITER it is permanent. The row is stamped with
    a fingerprint no live configuration will ever equal, so it is invisible for
    good and looks stamped while being so, which is worse than the unstamped
    rows this column was added to distinguish.

    So ``verify`` resolves the set twice and requires the two to agree, and
    writers pair it with ``uncached`` — the same two mechanisms
    `_snapshot_embedding_config` uses in `backfill.py`, for the same reason,
    which is what gives the ingest writer the guarantee the backfill already
    had. One retry, because a settings publish settles: the second attempt
    reads the new state consistently. Two inconsistent attempts answer None,
    and the caller declines to write rather than writing a triple nobody chose.

    Readers stay on the cheap path deliberately. Doubling their config reads on
    the search hot path would buy a fallback they already have.
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

    fix(#1546): the read-side counterpart of `embedding_config_fingerprint`.
    Writers stamp from the configuration they PINNED (that is the whole point —
    the stamp has to name what actually produced the vector); readers ask this
    what the live configuration is so they can ignore rows from another one.

    ``model_name`` is for callers that already resolved it. They pass it rather
    than let this read it again, so the model they filter on and the model
    inside the fingerprint are one read and cannot straddle a config change.

    Never raises. The endpoint resolves through the provider extension, and for
    the shipped provider that call raises whenever the database endpoint
    diverges from the operator-approved environment URL
    (`ai_credentials.bind_openai_credential_base_url`). A reader that turned
    that into a 500 would take search down over a setting it is only consulting
    to be careful, so an unresolvable configuration answers with
    `UNKNOWN_EMBEDDING_CONFIG` and every stamped row reads as foreign — the
    same under-report `resolve_embedding_model_name`'s sentinel produces, in
    the same safe direction.

    The read is CACHED by default, unlike the backfill's pre-delete snapshot.
    A reader has nothing to destroy: the worst a stale cache entry does here is
    make stamped rows briefly invisible, which degrades semantic search to FTS
    for one cache TTL and heals itself. An uncached read costs a DB round trip
    on the search hot path for that.

    One thing "never raises" does NOT mean: if the failure was a DATABASE error
    on `session`, that session's transaction is aborted and the caller's next
    statement will fail too. Swallowing here cannot undo that, and the same is
    already true of `resolve_embedding_model_name` above. Every caller today
    sits inside a broad handler that degrades — search falls back to FTS, the
    admin panel reads zeros, the backfill selection returns nothing — so the
    poisoned transaction changes nothing about the outcome. A future caller
    that wants to keep using the session after a failure here needs a
    SAVEPOINT; that is not paid for on the search hot path for a mode the
    runtime role cannot reach (it reads `app_settings` on every request).
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


async def get_anchor_embedding_row(
    session: AsyncSession, record_id: uuid.UUID
) -> tuple[list[float], str, str | None] | None:
    """The stored row a similarity comparison for ``record_id`` is anchored on.

    Returns ``(embedding, model_name, config_fingerprint)``, or None when the
    record has no vector at all.

    fix(#1580): ONE definition of which row that is, because the related-items
    path used to arrive at it twice and separately. ``get_nearest_record_ids``
    read the anchor to rank against; ``CatalogPort.get_record_embedding`` read it
    again to score the survivors. Each took ``LIMIT 1`` off an unordered query,
    and a record can hold one row per model (``uq_record_embedding_model`` is
    ``(record_id, model_name)``), so on a catalog that has been through a model
    swap the two reads could return vectors from DIFFERENT spaces. The
    neighbours were then ranked in one space and the similarity the user sees
    computed in another.

    fix(#1580 review r2): related-items now makes ONE call to this and hands the
    answer to everything downstream, so for that path the guarantee is literally
    one read rather than two statements that agree. This function still has a
    second caller — ``metadata_service`` asks for neighbours with no anchor of
    its own — and that one has nothing downstream to disagree with.

    The identity comes back with the vector for the same reason the caller
    cannot re-derive it: a list of floats does not say which model or endpoint
    produced it. Everything downstream filters with
    ``RecordEmbedding.usable_by_stored_anchor(model_name, config_fingerprint)``, so the
    comparison stays inside the anchor's own space.

    WHICH row, when a record has several: the one SEARCH would use, then the
    most recently written, then model name for stability.

    fix(#1580 review r3): the live-usable row goes first, and that ordering does
    two things. It makes related items and search agree by construction —
    whenever a record has a row search itself can retrieve, this anchors on that
    row, including after a model rollback, where "newest" would have picked the
    rolled-back one and the two readers would have disagreed about the same
    record. And it demotes the timestamp to a tiebreak among rows NONE of which
    are live-usable, where the choice is between two stale spaces and either
    answer is defensible.

    That demotion matters because the timestamp is not as ordered as it looks.
    PostgreSQL ``now()`` is TRANSACTION-START time, and both the column default
    and the ingest re-stamp used it, so a job that opened its transaction, spent
    thirty seconds in a provider call and committed after another model's job
    carries the EARLIER stamp despite being the later write. Ordering on it alone
    could leave related items anchored to a row that lost the race it won.
    ``clock_timestamp()`` fixes the explicit writers (see ``service.py``), but a
    row written before that change still carries a transaction stamp, so the
    ordering had to stop depending on it being right.

    An anchor with no live-usable row keeps the #1580 property as the FALLBACK:
    it finds its own-space neighbours or finds none, and never crosses into
    another space. That is still the difference between this reader and search,
    where one side is a fresh vector; it is just no longer the first question
    asked.

    The join to ``catalog.records`` is the tenant boundary.
    ``record_embeddings`` carries no ``tenant_id`` of its own, so RLS reaches it
    only through the record it belongs to; ``test_embedding_helper_queries_join
    _rls_visible_records`` asserts every embedding helper crosses it.
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

    fix(#1580): the neighbours are restricted to the anchor row's own vector
    space, through ``usable_by_stored_anchor`` — the stored-vs-stored reading of
    the same rule, which is where fix(#1580 review r2) argues out what a NULL
    side may be compared against and why the answer is the lenient one.
    Both sides of this comparison are STORED rows, so the rule is "same model
    and same stamp as the ANCHOR", not "same as the live configuration" —
    a record embedded under a superseded configuration should still find its own
    neighbours rather than be silently compared against a space it was never in.
    Without the predicate a catalog holding two models' rows returned cosine
    distances that were well-formed and meaningless.

    ``set_hnsw_recall`` turns on pgvector's iterative scan, which is what keeps
    this predicate from starving the approximate scan the way fix(#1546 review
    r2) describes: the filter runs on the candidates the index already chose, so
    without iterative scan a catalog whose nearest rows are mostly foreign-space
    returns nothing while usable vectors sit in the table. That call was already
    here and already covers this; the docstring there names related-items by
    name.
    """
    # fix(#1580 review r2): the caller may hand its anchor in, and the one
    # caller that scores the results afterwards does. Reading it here a second
    # time is two reads under READ COMMITTED, so a worker committing a newer
    # row for this record between them left the ranking anchored on the new
    # vector while the scoring used the old one — wrong distances, or an empty
    # answer when the two spaces do not overlap. Passing it makes "the same
    # row" a property of the call rather than of the isolation level.
    #
    # Optional because `metadata_service` reads neighbours with no anchor of
    # its own; that caller has nothing downstream to disagree with, so it lets
    # this read for it.
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
