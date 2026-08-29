"""Backfill embeddings for records that don't have them yet.

Processes every record with no RecordEmbedding row under the ACTIVE embedding
model (fix #1506) — a vector left behind by a superseded model is unusable to
semantic search, so the record counts as missing until it has a current one.
fix(#448): texts are embedded in batches of _BATCH_SIZE per provider call
(the embeddings endpoint accepts input lists) instead of one call per
record — a 50-200x reduction in API round trips on bulk backfills.
A failed batch is retried per record so a single rejected input doesn't
sink its batchmates; only the individually-failing records count as errors.

Can be run as a module: python -m app.embeddings.backfill
"""

from typing import Any

import structlog
from sqlalchemy import delete, func, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import AI_ENABLED, EMBEDDING_DIMS
from app.core.url_redaction import redact_url_credentials
from app.platform.extensions import get_processing_port
from app.processing.embeddings.helpers import embedding_config_fingerprint
from app.processing.embeddings.models import RecordEmbedding
from app.processing.embeddings.service import (
    build_content_text,
    compute_content_hash,
    generate_embeddings_batch,
    resolve_embedding_base_url,
)

logger = structlog.stdlib.get_logger(__name__)

# fix(#448): texts per provider call. OpenAI accepts up to 2048 inputs per
# request; 128 keeps request bodies modest for compatible providers (Ollama,
# Groq, Together) while still collapsing a 10K-record backfill to ~80 calls.
_BATCH_SIZE = 128

# Text for the force-path pre-flight embedding. Short, so the call is cheap,
# and constant, so a provider's cache can serve it.
_PREFLIGHT_TEXT = "geolens embedding preflight"

# fix(#1544): how much of a caught exception's message survives into a log line.
# Everything an operator acts on is at the front ("expected 1536 dimensions, not
# 768"); the tail is the statement and its bound parameters, one of which is the
# vector.
_MAX_ERROR_CHARS = 200


def _compact_error(exc: BaseException) -> str:
    """Describe an exception in one short line, without its bound parameters.

    Prefers the driver's own message (`DBAPIError.orig`), which names the actual
    failure and carries neither the statement nor the parameters. For anything
    else — a provider error, say — cut at the marker SQLAlchemy puts before the
    statement, collapse to one line, truncate.

    Redacted because this message now reaches the log on its own rather than
    buried in one traceback among thousands: a provider error names its
    endpoint, and an endpoint can carry a key in its query string.

    fix(#1577 reviews r1 and r2, codex P1 twice): THE REDACTOR RUNS FIRST, ON
    THE RAW STRING. Nothing may be inserted above it. Both rounds found the same
    bug at a different transformation, because every one of them can break the
    pattern the redactor matches on:

    - Truncating first (r1) cuts the `@` that terminates userinfo, leaving
      `https://alice:hunter2`, which reads as a host and a port and passes
      through untouched.
    - Collapsing whitespace first (r2) turns a tab, CR or LF inside a URL into a
      space, and `URL_LIKE_RE` stops at whitespace. `https://alice:hun\\nter2@…`
      becomes `https://alice:hun ter2@…` and the match dies before the `@`. A
      split in the HOST is worse still: the match ends there and a query-string
      key further along is never even reached.

    The `[SQL:` cut moved below for the same reason — it is a cut, and the rule
    cannot have exceptions and still be a rule. Cost of redacting the untrimmed
    string instead: measured below.

    What is left above the redactor is choosing `orig` over `exc` and calling
    `str()`. Neither can split a match: `orig` is a different, shorter string
    rather than a mangled one, so it can only omit a credential the SQL tail
    would have carried, never expose a split one. A driver that itself hands us
    a message already cut mid-URL is out of reach of any ordering here.
    """
    origin = getattr(exc, "orig", None)
    message = redact_url_credentials(str(origin if origin is not None else exc))
    marker = message.find("[SQL:")
    if marker != -1:
        message = message[:marker]
    message = " ".join(message.split())
    if len(message) > _MAX_ERROR_CHARS:
        message = message[: _MAX_ERROR_CHARS - 3] + "..."
    return message


def _error_fields(exc: BaseException, traced: set[str]) -> dict[str, Any]:
    """Log fields for a caught exception; MUTATES `traced` to spend the traceback.

    fix(#1544): a failing backfill used to cost more than a succeeding one, and
    all of it was inside the log formatter. Measured end to end on the #1533
    failure shape — a run where every insert fails the column's typmod, so the
    batch falls into this retry and every record raises a `DataError` out of the
    ORM flush. `exc_info=True` per record cost 964 ms and 60.6 KiB of output per
    record under the dev console renderer, and 3.1 ms and 12.7 KiB under the JSON
    renderer production uses. A 200-record run took 194 s before and 1.5 s after;
    a 1,000-record one wrote 12.4 MB of log output before and 0.35 MB after.

    The vector is in that rendering, but it is not the expensive part: SQLAlchemy
    already truncates a long bound parameter to about 150 characters a side, so
    the ~6 KB vector reaches the log as ~440 characters. The traceback is what
    costs — 33 frames over a three-exception chain, 12 KB of text before any
    renderer decorates it — which is why this drops the traceback rather than
    only the parameters.

    One traceback per distinct exception type per run, not per run: the same type
    raised repeatedly on this path has the same stack, while a second type is a
    second failure mode and its stack is new information. Types are tracked by
    qualified name so two `DataError`s from different libraries stay distinct.
    The set is owned by `backfill_embeddings`, so the budget spans the whole run
    rather than resetting at each batch boundary, and one type first seen at the
    batch level does not then spend a second traceback on the retry path.
    """
    error_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    first_of_type = error_type not in traced
    traced.add(error_type)
    return {
        "error_type": error_type,
        "error": _compact_error(exc),
        "exc_info": first_of_type,
    }


async def _live_column_dims(session: AsyncSession) -> int | None:
    """Read the declared width of the embedding column, straight from storage.

    pgvector puts the declared dimension straight in `atttypmod` (no -4 offset),
    and -1 means an unconstrained `vector`, which accepts any width.

    Storage rather than `EMBEDDING_DIMS`, because the two are written by
    different code at different times and the whole point of asking is that they
    can disagree. Measured on the scratch catalog: 0.32 ms median, against 2.7 ms
    for the config reads it runs beside.
    """
    return (
        await session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'catalog.record_embeddings'::regclass "
                "AND attname = 'embedding' AND NOT attisdropped"
            )
        )
    ).scalar_one_or_none()


class _AnomalousVectorWidth(RuntimeError):
    """ONE record's vector does not fit a column that has not moved.

    fix(#1579 review, codex P2): a bad record, not a broken run. Deliberately
    NOT a `_PinDrift`, so the per-record handler counts it and carries on, which
    is the #449 isolation this module has defended since. It is named rather
    than a bare `RuntimeError` only so the compact per-record log line says what
    happened (#1544 puts the qualified type in `error_type`).
    """


def _column_rejects_width(generated: int, pinned_column_dims: int | None) -> str | None:
    """Describe a generated width the column will not take, or None if it will.

    The fit test on its own, with no opinion about what the mismatch MEANS. Its
    two callers supply that: agreement across a batch on one path, a storage
    read on the other. Splitting it out is what stops the two rules from having
    to share one predicate, which is how a change meant for the batch path
    silently disarmed the retry path once already.

    `isinstance` rather than `is not None`, because `scalar_one_or_none` answers
    `int | None` and -1 means an unconstrained `vector`, which accepts any width
    and so can never mismatch.
    """
    if not isinstance(pinned_column_dims, int) or pinned_column_dims <= 0:
        return None
    if generated == pinned_column_dims:
        return None
    return (
        f"the model produced {generated}-dimension vectors but "
        f"catalog.record_embeddings.embedding is vector({pinned_column_dims})"
    )


def _structural_width_mismatch(
    vectors: list[list[float]], pinned_column_dims: int | None
) -> str | None:
    """Describe vectors that UNIFORMLY do not fit the column, or None otherwise.

    fix(#1533): the sibling class to drift, and the one the non-force path is
    otherwise blind to. Drift is a width that MOVES; this is a width that was
    already wrong when the run started, which every comparison guard is
    correctly silent about because nothing changed. The force path catches it in
    `_preflight_embedding`, before it has spent a single provider call on the
    catalog. The non-force path has no
    pre-flight, so the first batch insert failed the typmod, the batch was
    retried per record, and each retry spent a provider call before dying on the
    same error.

    Deliberately NOT a pre-flight on the non-force path, which is the obvious
    symmetry and is wrong twice over. It costs a provider call per run, on a
    path that destroys nothing and therefore has nothing to promise. Worse, it
    aborts a run that a single transient provider failure would otherwise
    survive: `test_batch_errors_do_not_stop_backfill` and
    `test_failed_batch_retries_per_record` pin the #449 contract that a failed
    batch is retried per record and only the bad records count, and a pre-flight
    consuming the first provider call turns a partial success into no run at
    all. Measured on the tree: adding one there fails 5 of the 7 tests in
    `test_embedding_backfill.py`, two of them for that reason rather than for
    test-double churn.

    Asking the vectors the provider ACTUALLY returned costs nothing extra, and
    it answers the same question the pre-flight asks: will storage take this.

    fix(#1579 review, codex P2): UNIFORMLY is the whole distinction, and an
    earlier revision missed it — any single wrong-width vector stopped the run,
    which broke the same #449 isolation the paragraph above defends. What makes
    a mismatch structural is AGREEMENT ACROSS INPUTS: a provider does not answer
    one anomalous width for all 128 texts by accident, whereas a column that was
    already wrong, or that has just been rebuilt, produces exactly that. Mixed
    widths mean one bad input among good ones, so this returns None and lets the
    batch fail into the per-record retry, where each vector is judged alone.
    """
    # fix(#1579 review r2, codex P2): TWO vectors minimum. Agreement is the
    # evidence, and one input agrees with itself vacuously — the same reason
    # `_raise_on_retry_vector_width` asks storage instead of counting widths.
    # A final batch of one, which is any catalog sized 1 mod _BATCH_SIZE, was
    # otherwise read as structural and stopped the whole run over a single bad
    # record: the isolation bug the previous round fixed on the retry path,
    # surviving at the one batch size where the batch path cannot tell the two
    # apart either.
    #
    # It falls through instead of growing a branch here. The insert fails, the
    # record is retried, and the retry rule decides it from storage, which is
    # the evidence that does work for one input. The cost is one extra provider
    # call for that one record, which is what a mixed-width batch already pays.
    #
    # An empty response lands here too, and for the same reason rather than by
    # accident: no vectors, no agreement, nothing structural to claim.
    if len(vectors) < 2:
        return None
    widths = {len(vector) for vector in vectors}
    if len(widths) != 1:
        return None
    return _column_rejects_width(widths.pop(), pinned_column_dims)


def _raise_on_structural_width(
    vectors: list[list[float]], pinned_column_dims: int | None, processed: int
) -> None:
    """Stop the run when a whole batch's vectors do not fit the column."""
    detail = _structural_width_mismatch(vectors, pinned_column_dims)
    if detail is None:
        return
    logger.error("backfill_aborted_width_mismatch", detail=detail, processed=processed)
    raise _PinDrift(
        f"Embedding regeneration stopped after {processed} records: {detail}. "
        "Re-save the embedding configuration in Settings so the column is "
        "rebuilt, then re-run."
    )


async def _raise_on_retry_vector_width(
    session: AsyncSession,
    pinned: tuple[str, int | None, str | None],
    vector: list[float],
    pinned_column_dims: int | None,
    processed: int,
) -> None:
    """The retry's post-call bracket, plus a judgement on the vector it returned.

    Two questions, in this order, because the second only makes sense once the
    first is answered:

    1. Is the pinned configuration still the active one? This is the post-call
       bracket #1525 review r6 installed on this path, restored here. It went
       missing when the r3 review moved the batch's post-call check below the
       flush so it could hold the relation lock: the check is still there, but
       it now sits after an insert that raises on its own when the column has
       moved to a different fixed width, so it never runs.
    2. Does THIS vector fit that column? A mismatch against a column that has
       not moved is one bad record, raised as `_AnomalousVectorWidth` so the
       caller counts it and carries on (#449).

    fix(#1579 review r4, codex P2): the earlier revision asked (2) first and
    returned early when the vector matched, so (1) went unasked whenever the
    provider answered at the pinned width. A column that moved to a DIFFERENT
    fixed width during the provider call then reached the flush, which raised
    the typmod error, which the broad handler counted as a bad record. Every
    record but the last was covered anyway, by the next one's pre-call check —
    but on the last there is no next one, and the run reported "complete with
    one error" for a configuration change. A misreport rather than a bad row,
    and narrow, but the rule is easier to hold when it has no exceptions.

    Asking `_raise_on_pin_drift` rather than reading the width here and
    phrasing the abort locally. The cheaper read (0.32 ms against ~3 ms) would
    put a second author of "the column moved" in the module, and two places
    that decide the same thing drift apart. One rule, one message.

    Cost is one more full drift check per retried record: about 9 ms against the
    ~0.22 s that record's provider call costs, so roughly 4% of a legitimate
    per-record retry, and nothing at all on the storm this PR exists to stop,
    which now ends on its first record.
    """
    await _raise_on_pin_drift(
        session,
        pinned,
        processed,
        pinned_column_dims=pinned_column_dims,
        error=_PinDrift,
    )
    detail = _column_rejects_width(len(vector), pinned_column_dims)
    if detail is None:
        return
    raise _AnomalousVectorWidth(detail)


def _upsert_embeddings(rows: list[dict[str, Any]]):  # type: ignore[no-untyped-def]
    """INSERT the batch, replacing any row this record already has for the model.

    fix(#1546): a plain INSERT stopped being safe once rows carry a
    configuration stamp. `uq_record_embedding_model` is `(record_id,
    model_name)`, and the non-force run now offers a record whose only row for
    the ACTIVE model was written under a different configuration — that row is
    invisible to search, so the record genuinely is uncovered — which a plain
    INSERT would answer with a unique violation instead of a vector.

    Replacing in place rather than widening the constraint: one row per
    (record, model) keeps the table's size independent of how many
    configurations an instance has been through, and leaves the key that #1549
    needs for a per-batch delete-and-replace intact.

    `updated_at` is set explicitly because `onupdate=` is an ORM-level default
    and this is a Core statement.
    """
    # fix(#1583 review): stamp the INSERT branch too. `set_` below only governs
    # the ON CONFLICT path; a row that does not collide takes the column's
    # `server_default`, which is `now()` — so half the writes kept the
    # transaction-start stamp and the fix would have covered replacements but
    # not first-time inserts. The server_default stays as it is for writers
    # that have no opinion; this states one.
    stmt = pg_insert(RecordEmbedding).values(
        [row | {"updated_at": func.clock_timestamp()} for row in rows]
    )
    return stmt.on_conflict_do_update(
        index_elements=["record_id", "model_name"],
        set_={
            "embedding": stmt.excluded.embedding,
            "content_hash": stmt.excluded.content_hash,
            "config_fingerprint": stmt.excluded.config_fingerprint,
            # fix(#1583 review): `clock_timestamp()`, not `now()`. `now()` is
            # TRANSACTION-START time, and a backfill transaction opens, spends
            # the length of a provider call in it, and only then writes — so a
            # row written at the end of that gets a stamp EARLIER than a job
            # which started and committed while the provider was still
            # thinking. #1583 orders the related-items anchor by `updated_at
            # DESC`, which makes that inversion visible as the wrong anchor.
            # The column's server_default stays as it is; this is about the
            # value a write of ours records.
            "updated_at": func.clock_timestamp(),
        },
    )


def _content_fields(record) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """The fields ``build_content_text`` reads, pulled off a record eagerly.

    Eager, because a rollback expires every ORM instance in the session and a
    later attribute access would lazy-load and raise ``MissingGreenlet``. One
    function for both readers — the run's fetch and the reclamation's re-check
    (fix(#1584 review r4)) — so "is this record empty" is asked the same way at
    both ends of the run.
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


async def _records_still_empty(session, port, record_orm, record_ids) -> set[Any]:  # type: ignore[no-untyped-def]
    """Which of these records have no embeddable content RIGHT NOW — and hold them.

    fix(#1584 review r4): the reclamation asks this immediately before it
    deletes, one read per record, through the same loader and the same field
    extraction the run used at its start. ``expire_all`` first, deliberately:
    this session does not expire on commit, so its identity map still holds the
    instances the run loaded at the start, and a re-select would hand back their
    pre-edit attributes rather than the row's. A record that no longer exists
    counts as empty; its rows are orphans either way.

    fix(#1584 review r5): the records are locked ``FOR UPDATE`` first, and the
    caller keeps this transaction open through its DELETE. Without the lock the
    re-read and the delete were two statements with a gap, and an editor who
    restored the content in that gap had the ingest writer skip on an unchanged
    hash while the row still existed — then the delete took it, and nothing
    would ever regenerate it. Held, the editor's write lands on one side or the
    other: before the read, and the record is spared; after the delete, and
    the writer finds no row and regenerates. The lock is on the records the
    caller is about to reclaim, one chunk at a time, released by its commit.
    """
    session.expire_all()
    await session.execute(
        select(record_orm.id)
        .where(record_orm.id.in_(list(record_ids)))
        .with_for_update()
    )
    still_empty: set[Any] = set()
    for record_id in record_ids:
        current = await port.get_record(session, record_id)
        if current is None or not build_content_text(**_content_fields(current)):
            still_empty.add(record_id)
    return still_empty


async def _reclaim_observed_rows(session, port, record_orm, reclaimable) -> int:  # type: ignore[no-untyped-def]
    """Delete the observed rows of records that are still empty; return how many.

    One chunk per transaction: lock the chunk's records, re-check them, delete
    the rows of those still empty, commit. See ``_records_still_empty`` for why
    the lock, and the caller for why the chunking.
    """
    removed = 0
    for offset in range(0, len(reclaimable), _BATCH_SIZE):
        chunk = reclaimable[offset : offset + _BATCH_SIZE]
        still_empty = await _records_still_empty(
            session, port, record_orm, {record_id for record_id, _ in chunk}
        )
        chunk = [pair for pair in chunk if pair[0] in still_empty]
        if chunk:
            await session.execute(
                _delete_embeddings_for(
                    record_orm,
                    [record_id for record_id, _ in chunk],
                    observed=chunk,
                )
            )
            removed += len(chunk)
        await session.commit()
    return removed


def _delete_embeddings_for(record_orm, record_ids: list[Any], *, observed=None):  # type: ignore[no-untyped-def]
    """Remove EVERY embedding these records hold, under any model.

    The `Record` subquery is the tenant boundary: `RecordEmbedding` carries no
    RLS policy of its own, so scoping through the records table is what keeps a
    force run inside the calling tenant (#1511). The ids already come from a
    tenant-scoped select, so this is the second half of a belt-and-braces pair
    rather than the only one, and it is bounded to the batch rather than the
    whole table.

    fix(#1584 review r3): ``observed`` narrows the delete to the exact row
    VERSIONS the run saw, as `(record_id, updated_at)` pairs. Only the
    end-of-run reclamation passes it, and it needs it, because that pass acts on
    an observation made much earlier and must not delete anything written since.

    This replaced a `updated_at < cutoff` comparison, which was the same idea
    expressed as a clock and got the answer wrong in both directions. It spared
    rows it should have reclaimed whenever a stored stamp was AHEAD of the
    cutoff — rows written before this release by an application clock running
    ahead of PostgreSQL, or by an older worker mid-rolling-deploy — and moving
    the writers to `clock_timestamp()` does nothing for stamps already on disk.
    Matching versions asks a question no clock can answer wrongly: has this row
    changed since I looked at it? Any write by any writer on any clock moves
    `updated_at`, so a fresh vector survives and a stale one is reclaimed,
    whatever wrote either of them and whatever clock it read.
    """
    predicate = RecordEmbedding.record_id.in_(
        select(record_orm.id).where(record_orm.id.in_(record_ids))
    )
    if observed is not None:
        return delete(RecordEmbedding).where(
            predicate,
            tuple_(RecordEmbedding.record_id, RecordEmbedding.updated_at).in_(observed),
        )
    return delete(RecordEmbedding).where(predicate)


async def _replace_embeddings(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    *,
    record_orm=None,  # type: ignore[no-untyped-def]
) -> None:
    """Remove what `rows` replace, then write them. Does NOT commit.

    fix(#1549): this ordering IS the fix, which is why both write sites go
    through one function rather than repeating it. A force run used to commit
    `DELETE FROM catalog.record_embeddings` before it had generated anything,
    so every abort after that point left the catalog with no vectors at all.
    Deleting inside the transaction that writes the replacements closes the
    window: either both land or neither does, and a run that dies between
    batches has replaced some records and left the rest untouched.

    The DELETE must precede the INSERT and must be in the same transaction.
    Reversed, it would remove the rows just written, since it clears every row
    the record holds under any model. That breadth is deliberate and is what
    the bulk delete used to provide: force means "replace what is there",
    including vectors left behind by a superseded model, which the upsert alone
    cannot reach because it is keyed on (record_id, model_name).

    The COMMIT belongs to the caller, deliberately, and it is the reason this
    function does not own one. fix(#1579 review r3): both callers run a drift
    check between writing and committing, and that check is only sound while it
    holds the RowExclusiveLock these statements take. Committing here would
    release the lock before the check ran and reopen the window that reorder
    closed, so the two fixes have to share one transaction rather than each
    owning theirs.

    ``record_orm`` is the `Record` class on a force run and None otherwise. A
    non-force run has nothing to replace: it only fills gaps, so it must not
    delete, and passing None is what says so.
    """
    if record_orm is not None:
        await session.execute(
            _delete_embeddings_for(record_orm, [row["record_id"] for row in rows])
        )
    await session.execute(_upsert_embeddings(rows))


async def _snapshot_embedding_config(
    session: AsyncSession,
) -> tuple[str, int | None, str | None]:
    """Capture (model, dimensions, endpoint) as one consistent set, or refuse.

    The values come from separate `PersistentConfig` reads — there is no
    combined read, and building one would bypass the per-key validation and
    cache machinery in `PersistentConfig.get`. So capture them, then read them
    again and compare. Any single admin change lands inside one of the windows
    and shows up as a difference; only a change-and-revert inside the same few
    milliseconds slips through, which is not a case worth more code.

    fix(#1525): the endpoint is captured and compared inside that same single
    window, for the reason below. It is resolved through the provider rather
    than read here, because the fallback chain and the credential binding
    belong to whichever provider extension is registered (see
    `resolve_embedding_base_url`).

    KNOWN RESIDUE (#1525 review r2): the model and dimensions are read
    uncached, so they are always the committed state. The endpoint is not, and
    cannot be from here — it is resolved BY THE PROVIDER, which reads its own
    keys through the same per-key cache. Making that read uncached needs either
    a copy of the provider's fallback chain and credential binding in this
    caller, which would be wrong for any extension resolving its endpoint from
    somewhere else, or an uncached mode on the extension interface itself.

    What that leaves open: a settings update that is committed but whose
    endpoint key is not yet evicted, so the provider answers from a stale entry
    beside an uncached model. For the SHIPPED provider it is unreachable, on
    both branches of `ai_credentials.bind_openai_credential_base_url`:

    - With an API key configured, the candidate value is used only to compare
      against the operator-approved environment URL. Equal returns that same
      approved string; unequal raises `OpenAICredentialDestinationError`. A
      stale cached endpoint therefore either resolves to the identical string
      or fails loudly, and can never silently pin a different destination.
    - With no API key, `DefaultOpenAIEmbeddingProvider.embed` raises
      `EmbeddingUnavailableError` before producing a vector, and on the force
      path `_preflight_embedding` runs before the batch loop, so the run aborts
      having written nothing and, since fix(#1549), having removed nothing
      either.

    So the residue is confined to an extension provider that resolves its
    endpoint from the database and applies no such binding. Closing it needs an
    uncached mode on the extension interface, which does not belong in a fix
    PR; the underlying per-key eviction window is #1543.

    A partial guard was tried here and removed: comparing the cached model and
    dimensions against the uncached ones detects the eviction window, but only
    the half where the model key has not been evicted yet, and it aborts
    whenever a caller mocks one read and not the other. A guard that fires on
    incomplete test doubles more often than on the hazard does not survive.

    fix(#1511 review r2, codex P1): without the comparison a run could pin
    model A with model B's dimensions, a pairing that never existed in config.
    A provider that rejects it fails every insert; one that accepts it writes
    vectors under a configuration nobody chose.

    The re-read observes a concurrent change because `PersistentConfig.set`
    commits and then deletes the cache entry (`apply_side_effects`,
    persistent_config.py), so the second `get` misses the cache and hits the
    DB. If a stale entry did survive, both reads would return the same stale
    pair and the provider is handed that same pair explicitly, so the run stays
    internally consistent and simply reflects the older config.

    Raises:
        RuntimeError: If the model cannot be resolved, or if either value
            changed while it was being captured. Callers must invoke this
            BEFORE anything destructive, which is what makes aborting safe.
    """
    # Imported in-function, as the port does, so patching the module attribute
    # reaches this call site.
    from app.processing.embeddings.helpers import (
        UNKNOWN_EMBEDDING_MODEL,
        resolve_embedding_model_name,
    )

    # fix(#1525 review r2, codex P1): read the pinned values straight from the
    # DB. `PersistentConfig.get` answers from a PER-KEY cache, and
    # `update_settings` commits the whole batch of setting writes before any
    # cache entry is evicted (`apply_side_effects_batch`, after the commit in
    # `update_settings`). A cached read can therefore land on the far side of a
    # committed update, and comparing two of them cannot see it: two reads
    # through the same stale entry agree with each other perfectly.
    # `get_uncached` neither reads nor writes the cache, so these observe the
    # committed state instead.
    #
    # The eviction was a per-key loop when this was written, which made the
    # window wider still: two keys could be read on opposite sides of one
    # update. #1543 made it a single batched step, which narrows the window
    # without closing it, and does not change what these reads have to do.
    model_name = await resolve_embedding_model_name(session, uncached=True)
    if model_name == UNKNOWN_EMBEDDING_MODEL:
        # Loud, not silent: the admin route maps this to a 502 and a "failed"
        # audit entry. Returning zero counts would look like a completed run
        # over an empty catalog.
        logger.error("backfill_aborted_unresolved_embedding_model")
        raise RuntimeError(
            "Cannot regenerate embeddings: the active embedding model could "
            "not be resolved. Existing vectors were left untouched; retry "
            "once the AI configuration resolves."
        )
    dimensions = await EMBEDDING_DIMS.get_uncached(session)
    base_url = await resolve_embedding_base_url(session)

    # fix(#1525 review, codex P1): ONE window over all three, not a window per
    # value. An earlier revision gave the endpoint its own capture-and-compare
    # after the pair had already been compared, which left a gap between the
    # two: an admin updating model and endpoint together in that gap produced
    # old model + new endpoint, a configuration that never existed, and neither
    # comparison could see it. Splitting a race guard by value does not close
    # the race, it relocates it. If values are pinned as a unit they have to be
    # verified as a unit.
    if (
        await resolve_embedding_model_name(session, uncached=True) != model_name
        or await EMBEDDING_DIMS.get_uncached(session) != dimensions
        or await resolve_embedding_base_url(session) != base_url
    ):
        logger.error("backfill_aborted_embedding_config_changed")
        raise RuntimeError(
            "Cannot regenerate embeddings: the embedding model, dimensions or "
            "endpoint changed while the run was starting. Existing vectors were "
            "left untouched; re-run to use the new configuration."
        )

    return model_name, dimensions, base_url


class _PinDrift(RuntimeError):
    """Drift detected with a batch already generated but not yet committed.

    A distinct type only so the two broad handlers below can re-raise it: the
    per-batch one instead of retrying the batch record by record, and the
    per-record one instead of counting it as a bad input. It is a
    `RuntimeError`, so every caller that already treats this module's aborts as
    one — the admin route included — is unaffected.

    fix(#1533): also carries a STRUCTURAL generated-width mismatch, which is not
    drift. The name is narrower than the job: what the two handlers need is "a
    run-stopping condition discovered with a batch already generated", and both
    conditions want exactly the same treatment from them. An ISOLATED width
    mismatch is `_AnomalousVectorWidth` instead, precisely so it does NOT get
    this treatment.
    """


async def _raise_on_pin_drift(
    session: AsyncSession,
    pinned: tuple[str, int | None, str | None],
    processed: int,
    *,
    pinned_column_dims: int | None,
    error: type[RuntimeError] = RuntimeError,
) -> None:
    """Stop the run if the configuration it pinned is no longer the active one."""
    drift = await _pinned_config_drift(session, pinned, pinned_column_dims)
    if drift is None:
        return
    logger.error("backfill_aborted_pin_drift", detail=drift, processed=processed)
    raise error(
        f"Embedding regeneration stopped after {processed} records: {drift} "
        "while the run was in progress. The rows already written are "
        "consistent with the configuration that produced them; re-run to "
        "cover the rest under the new one."
    )


async def _retry_batch_per_record(
    session: AsyncSession,
    batch: list[tuple[Any, str]],
    pinned: tuple[str, int | None, str | None],
    created: int,
    *,
    model_name: str,
    embedding_dims: int | None,
    base_url: str | None,
    pinned_column_dims: int | None,
    traced_errors: set[str],
    record_orm=None,  # type: ignore[no-untyped-def]
) -> tuple[int, int]:
    """Re-embed a failed batch one record at a time; return (created, errors).

    fix(#449, codex P2): one rejected input (e.g. a record over the model's
    token limit) must not sink the other 127, so only the bad ones count as
    errors. That behaviour is unchanged; what is new is the drift bracketing.
    It lives in its own function because adding that pushed
    `backfill_embeddings` past the McCabe gate, and the per-file burn-down list
    in pyproject.toml may shrink but never grow.

    `created` is the run's running total, passed in only so an abort message
    can say how many records the run had written before it stopped.

    `pinned_column_dims` is the storage width the run pinned, carried in so the
    bracketing below covers it too. fix(#1533): a width that moves is what puts
    this loop in its worst state, because the batch insert that failed and sent
    the run here fails again for every record, one provider call at a time.

    `traced_errors` is the run's traceback budget, shared with the batch handler
    that calls this. See `_error_fields`.

    fix(#1549): `record_orm` carries the force flag here, as `Record` or None,
    because the retry replaces per record for the same reason the batch path
    replaces per batch. It matters more on this path than on that one: the
    batch failed, which is exactly when a record can fail again, and a record
    that fails again must keep the vector it already had rather than lose it to
    a delete that was committed on the promise of a replacement never written.
    """
    made = 0
    failed = 0
    for record_id, content in batch:
        try:
            # fix(#1525 review r6, codex P2): the drift checks bracket the
            # retry's own provider call too. This path had none, so the window
            # the batch path closed survived one path over, and it is the
            # LIKELIER one: a provider outage is exactly when an operator goes
            # and edits the endpoint. The batch call raised, so the batch's
            # post-call check never ran, and every vector generated here would
            # otherwise be committed under a pin that had already stopped being
            # active.
            #
            # The check before the call is not redundant with the one after the
            # previous record's: that record may have FAILED, in which case its
            # post-call check never ran either.
            await _raise_on_pin_drift(
                session,
                pinned,
                created + made,
                pinned_column_dims=pinned_column_dims,
                error=_PinDrift,
            )
            [vector] = await generate_embeddings_batch(
                [content],
                session,
                model=model_name,
                dimensions=embedding_dims,
                base_url=base_url,
            )
            # fix(#1533): per vector on this path, not per batch. This loop is
            # where a mismatch costs a provider call per record, so it is the
            # one that has to stop on the first — but only when the column has
            # moved. One record's vector against a column that has not moved is
            # a bad record, and the handler below counts it (#1579 review).
            #
            # Ahead of the write, deliberately: it decides NOT to write, so it
            # needs no lock, and putting it after the write would let the write
            # raise the typmod error first and turn a named abort into a counted
            # one. It carries the post-call drift bracket for the same reason.
            await _raise_on_retry_vector_width(
                session, pinned, vector, pinned_column_dims, created + made
            )
            await _replace_embeddings(
                session,
                [
                    {
                        "record_id": record_id,
                        "embedding": vector,
                        "model_name": model_name,
                        # fix(#1546): from `pinned`, which IS the
                        # configuration this call was made under — the
                        # retry passes the same three values to the
                        # provider. Re-resolving here would stamp what the
                        # config says now rather than what produced the
                        # vector, which is the fabrication the whole column
                        # exists to avoid.
                        "config_fingerprint": embedding_config_fingerprint(*pinned),
                        "content_hash": compute_content_hash(content),
                    }
                ],
                record_orm=record_orm,
            )
            # fix(#1579 review r3, codex P2): the row is SENT before the
            # post-call check, so the check runs holding the lock its answer
            # depends on. See the same ordering on the batch path.
            #
            # fix(#1546): what sends it is a Core INSERT ... ON CONFLICT rather
            # than an ORM add followed by `session.flush()`. The ordering is
            # unchanged and so is the reason for it: the INSERT takes the same
            # RowExclusiveLock the flush did, so an ALTER TABLE still either
            # lands before the check and is seen, or waits for our commit.
            #
            # fix(#1549): and the delete that clears what this row replaces is
            # inside `_replace_embeddings`, in this same transaction, ahead of
            # the write. So the abort below rolls back the delete along with the
            # row, and a record whose replacement never commits keeps the vector
            # it already had.
            await _raise_on_pin_drift(
                session,
                pinned,
                created + made,
                pinned_column_dims=pinned_column_dims,
                error=_PinDrift,
            )
            await session.commit()
            made += 1
        except _PinDrift:
            # fix(#1525 review r6, codex P2): drift is not a bad record.
            # Counting it would leave the run reporting partial success with
            # the rest of the catalog written into a vector space the active
            # search cannot match — the silent outcome these checks exist to
            # prevent. It stops the run, as on the batch path.
            await session.rollback()
            raise
        except Exception as exc:  # broad: same isolation, per record
            await session.rollback()
            failed += 1
            logger.warning(
                "Backfill: error processing record",
                record_id=record_id,
                **_error_fields(exc, traced_errors),
            )
    return made, failed


async def _pinned_config_drift(
    session: AsyncSession,
    pinned: tuple[str, int | None, str | None],
    pinned_column_dims: int | None,
) -> str | None:
    """Describe how the live config has left the pinned one, or None if it has not.

    fix(#1525 review r4, codex P2): every guard on this path so far protects a
    run from config moving DURING a read. This one notices that the run itself
    has outlived the configuration it pinned, which no amount of care inside a
    single batch can see.

    Read the same way `_snapshot_embedding_config` reads, for the same reason:
    a cached read can agree with a stale entry and report no drift.

    fix(#1533): the storage width is checked alongside the settings, because the
    settings are only ONE of the routes it moves by. `update_settings` publishes
    `embedding_dims` and then rebuilds the column, so the dimensions comparison
    above catches that route within a batch. It catches nothing else, and the
    column moves without a settings write in an ENV_ONLY_CONFIG deployment
    (there is no settings row and no rebuild ever fires), after a hand
    `ALTER TABLE`, after a restored dump, and after a rebuild that failed
    partway. Measured on 1,000 records with the width moved by hand and the
    settings row untouched: 1,009 provider calls and 1,000 errors reported as if
    the provider were broken, against 2 calls and a named cause with this check.

    Two states are deliberately NOT treated as drift, because neither is
    evidence that the pinned configuration stopped being the right one:

    - An unresolvable model. `resolve_embedding_model_name` answers with its
      sentinel when persistent-config resolution fails for any reason, so
      treating it as a change would abort a long run on a transient DB blip.
    - A provider resolve that RAISES. For the shipped provider that is what an
      endpoint edit diverging from the operator-approved environment URL looks
      like (`ai_credentials.bind_openai_credential_base_url`), and it says
      nothing about where vectors are going: `embed` re-binds to that same
      approved URL, so the pin is still accurate. Aborting there would undo the
      abandon-the-catalog fix earlier in this PR. Only a resolve that SUCCEEDS
      and answers differently means the endpoint actually moved.
    """
    from app.processing.embeddings.helpers import (
        UNKNOWN_EMBEDDING_MODEL,
        resolve_embedding_model_name,
    )

    model_name, dimensions, base_url = pinned

    active_model = await resolve_embedding_model_name(session, uncached=True)
    if active_model not in (model_name, UNKNOWN_EMBEDDING_MODEL):
        return f"the embedding model changed from {model_name!r} to {active_model!r}"

    active_dims = await EMBEDDING_DIMS.get_uncached(session)
    if active_dims != dimensions:
        return (
            f"the embedding dimensions changed from {dimensions!r} to {active_dims!r}"
        )

    # fix(#1533): BEFORE the endpoint block, not after it, and not because of
    # message quality. That block returns None from its `except`, so a
    # deployment where the endpoint cannot be resolved would never reach a check
    # placed below it — and an endpoint that will not resolve is exactly the
    # kind of half-configured install where a column gets altered by hand. The
    # settings comparisons stay ahead of this one so that when both have moved,
    # the message names the admin action rather than its consequence.
    #
    # Any change counts, including one that widens the column or drops the
    # constraint. A run that carried on would leave the table holding two vector
    # widths under one model label, and the inserts that make that happen are
    # the ones that SUCCEED, so nothing else would report it.
    active_column_dims = await _live_column_dims(session)
    if active_column_dims != pinned_column_dims:
        return (
            f"the embedding column width changed from vector({pinned_column_dims}) "
            f"to vector({active_column_dims})"
        )

    try:
        active_base_url = await resolve_embedding_base_url(session)
    except (
        Exception
    ):  # broad: an endpoint that cannot be resolved is not an endpoint that moved
        return None
    if active_base_url != base_url:
        # Deliberately unquoted: an endpoint can name an internal host, and this
        # string reaches an audit log.
        return "the embedding endpoint changed"
    return None


async def _preflight_embedding(
    session: AsyncSession,
    pinned: tuple[str, int | None, str | None],
    pinned_column_dims: int | None,
) -> None:
    """Generate one throwaway embedding to prove regeneration can work.

    fix(#1511 review r3, codex P1): three rounds of this review each guarded a
    different way for a force run to destroy vectors it then could not rebuild
    — unresolvable model, model and dimensions disagreeing across reads, model
    and dimensions disagreeing in a committed and stable state. Guarding modes
    one at a time keeps finding another mode. This proves the capability
    instead: if the provider returns a vector for the pinned pair right now,
    regeneration works with the configuration as it actually stands, whatever
    the mode would have been.

    It subsumes the stable-mismatch case that no amount of re-reading can
    catch, and also provider outages, revoked keys, exhausted quota and
    dimensions the model rejects. The cost is one provider call per force run,
    against regenerating the entire catalog.

    The earlier guards are kept rather than replaced. They are cheaper, they
    fail before any provider round trip, and they name the problem better than
    a provider rejection would.

    Raises:
        RuntimeError: If the embedding cannot be generated, or cannot be stored
            in the column as it currently stands. The caller must run this
            BEFORE deleting anything.
    """
    model_name, dimensions, base_url = pinned
    try:
        vectors = await generate_embeddings_batch(
            [_PREFLIGHT_TEXT],
            session,
            model=model_name,
            dimensions=dimensions,
            base_url=base_url,
        )
    except Exception as exc:  # broad: any provider/config failure means the regenerate cannot be promised
        logger.error(
            "backfill_preflight_embedding_failed",
            model=model_name,
            dimensions=dimensions,
            exc_info=True,
        )
        raise RuntimeError(
            "Cannot regenerate embeddings: a test embedding failed with the "
            f"active configuration (model {model_name!r}, dimensions "
            f"{dimensions!r}). Existing vectors were left untouched; fix the "
            "embedding configuration or provider and re-run."
        ) from exc

    # fix(#1511 review r4, codex P1): generating a vector is only half the
    # promise — it also has to fit the column. The width a model produces and
    # the width the column declares are written by different code at different
    # times, so they can disagree, and when they do the provider answers
    # happily at the new width, this pre-flight passes, the DELETE commits and
    # every insert dies on the typmod.
    #
    # The case that found it was a settings write that persisted a newly
    # detected width without rebuilding the column, so switching model without
    # naming dimensions left storage at the old width. #1529 closed that route:
    # an auto-detected width now joins `validated_settings` and goes down the
    # same rebuild branch as one an admin typed, so the column follows every
    # width the settings API publishes.
    #
    # This check is deliberately NOT written against that route, which is why
    # closing it did not retire the check. It asks storage what it will accept,
    # so it holds for any cause. Still live after #1529: a rebuild that failed
    # partway, a restored dump, a column altered by hand, and ENV_ONLY_CONFIG
    # deployments, where the model comes from the environment, no settings
    # write happens, and therefore no rebuild is ever triggered.
    #
    # The width comes off the live column rather than EMBEDDING_DIMS (the
    # setting is what disagreed with storage in the first place), and it is the
    # caller's read rather than one of this function's own.
    #
    # fix(#1533): one read, deliberately. The caller pins that same value and
    # stops the run if the column stops matching it, so what this proves is not
    # "the width fitted a moment ago" but "the width fits, and the run will not
    # outlive it". Reading storage twice would put a window between the two: a
    # rebuild landing inside it passes this check against the old width and gets
    # pinned at the new one, so nothing afterwards has anything to notice.
    column_dims = pinned_column_dims

    generated = len(vectors[0])
    if column_dims is not None and column_dims > 0 and generated != column_dims:
        logger.error(
            "backfill_preflight_storage_mismatch",
            model=model_name,
            generated_dims=generated,
            column_dims=column_dims,
        )
        raise RuntimeError(
            f"Cannot regenerate embeddings: model {model_name!r} produces "
            f"{generated}-dimension vectors but catalog.record_embeddings."
            f"embedding is vector({column_dims}). Existing vectors were left "
            "untouched. Re-save the embedding configuration in Settings so the "
            f"column is rebuilt to {generated} dimensions, then re-run."
        )


async def backfill_embeddings(
    session: AsyncSession,
    *,
    force: bool = False,
    should_continue: Any = None,
) -> dict:
    """Generate embeddings for records.

    Args:
        session: Database session.
        force: If True, regenerate every record and replace whatever vectors it
               already holds. Useful when the model, dimensions or endpoint
               change. fix(#1549): "replace" is per batch, inside the
               transaction that writes the batch's new rows, so an aborted run
               leaves the records it reached rewritten and the rest exactly as
               they were. It no longer empties the table up front.
        should_continue: Optional zero-argument async callable polled once per
               batch, BEFORE that batch's provider call; a False answer stops
               the run at the boundary (fix(#1709 review r6)). The queued-run
               caller passes a fenced job-row read so a user cancel whose
               best-effort queue abort was lost stops the run within one batch
               of provider spend instead of the whole remaining catalog. Kept
               opaque here on purpose: this module knows records and vectors,
               not jobs.

    Returns:
        Dict with counts: processed, created, skipped, errors.

    Raises:
        RuntimeError: On force=True, if AI is disabled, if the embedding config
            cannot be resolved or moves while the run is starting, or if the
            pre-flight embedding fails. Nothing is deleted in any of those
            cases.
    """
    port = get_processing_port()

    pinned: tuple[str, int | None, str | None] | None = None
    # fix(#1533): the storage width the run commits to, pinned beside the config
    # rather than inside it. It is not configuration — it is read off
    # `pg_attribute` rather than `PersistentConfig`, and the two disagree often
    # enough that this whole check exists.
    pinned_column_dims: int | None = None
    # fix(#1549): non-None only on a force run, where it is both the tenant
    # boundary for the per-batch delete and the flag that says a batch replaces
    # rather than fills a gap. A non-force run must delete nothing, so it stays
    # None all the way down to `_replace_embeddings`.
    record_orm = None

    if force:
        Record = port.get_record_orm_class()
        record_orm = Record

        # fix(#1511 review r5, codex P2): every guard below exists to protect
        # rows from the DELETE. That DELETE is bounded by the record foreign
        # key, so a tenant with no visible records has nothing it could remove
        # and nothing to regenerate. Demanding a working provider just to
        # discover that turned a harmless no-op into a 502 on a fresh install.
        # Returning here matches what the old code produced by the longer route
        # (an empty select, then the `total == 0` return below) minus the
        # pointless provider call, delete and commit.
        if (await session.execute(select(Record.id).limit(1))).first() is None:
            logger.info("Backfill: no visible records, nothing to regenerate")
            return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

        # fix(#1511): everything that could stop this run from regenerating has
        # to happen BEFORE the delete below commits. Every row this run writes
        # back is stamped with the active model and `model_name` is NOT NULL,
        # so a force run started while the config is unusable clears the whole
        # table and then cannot insert a single replacement — a Regenerate All
        # clicked during a config blip converts full coverage into zero.
        #
        # The AI gate further down runs after the delete, which on this path
        # would mean deleting everything and then declining to regenerate it.
        if not await AI_ENABLED.get(session):
            logger.error("backfill_force_aborted_ai_disabled")
            raise RuntimeError(
                "Cannot regenerate embeddings: AI features are disabled. "
                "Existing vectors were left untouched; enable AI and re-run."
            )

        # Fail-closed on an unresolvable model, as documented in
        # DefaultProcessingPort.get_records_without_embeddings (#1506), which
        # could not cover this branch: force asks that query for every record
        # rather than for the ones a configuration cannot use, so it never
        # consults the model at all.
        pinned = await _snapshot_embedding_config(session)
        pinned_column_dims = await _live_column_dims(session)

        # fix(#1511 review r3, codex P1): the checks above test proxies for
        # "regeneration will work". This one tests the property itself, because
        # the proxies keep running out. A comparison-based guard can only catch
        # a value that MOVES. It is blind to a pair that is wrong, committed and
        # stable, because re-reading such a pair agrees with itself and learns
        # nothing. What made that concrete was a settings write publishing a new
        # model before its dimensions were known (that publish is the subject of
        # #1529), but the blindness belongs to comparing, not to that one writer.
        #
        # One real embedding proves the live config can produce a vector, and
        # covers the modes nobody has enumerated yet: provider down, revoked
        # key, exhausted quota, dimensions the model rejects.
        await _preflight_embedding(session, pinned, pinned_column_dims)

        # fix(#1549): there is no bulk DELETE here any more. It used to commit
        # before the run knew it could finish, so any failure after it — a
        # provider outage, drift detected mid-run, a worker restart — ended the
        # run with the old vectors gone and few or none written. Every guard
        # above sits correctly before that commit for the conditions it can see
        # at the start; none of them can see a change that lands after it.
        #
        # The delete now happens per batch, inside the transaction that writes
        # that batch's replacement rows (`_replace_embeddings`), so there is no
        # window in which the old rows are gone and the new ones are not
        # written. What an aborted run leaves is a MIX: replaced records hold
        # rows from this run's pinned configuration, untouched records hold
        # exactly what they held before it started.
        #
        # #1546 is what makes that mix readable rather than ambiguous for every
        # row it stamped: a row from a superseded configuration is invisible to
        # search instead of being silently compared across vector spaces. The
        # residue is the one #1546 documents — a row written before that column
        # existed carries no stamp and is still matched on model name alone, so
        # after an endpoint change it may be compared cross-space. That is not
        # something this change introduces. It is true of an unstamped catalog
        # from the moment the endpoint moves, whether or not anyone runs a
        # regenerate, and an aborted run now leaves those records no worse than
        # it found them rather than leaving them with nothing.
        #
        # The HNSW index lives in Alembic migration 0012 (and is recreated by
        # service.rebuild_embedding_column on dimension change); a per-batch
        # delete does not need it dropped either. RecordEmbedding is not
        # RLS-scoped itself, so the Record subquery inside `_replace_embeddings`
        # remains the required tenant boundary in hosted mode.

    # Find the records still needing a vector, eager-loading keywords.
    # fix(#1506): pass `force` through instead of hardcoding False. force=True
    # asks for "every record" directly, which is what this branch has always
    # meant, and the port's non-force branch would answer a different question:
    # it selects only records with no vector the live configuration can use, so
    # routing a regenerate through it would skip precisely the records that are
    # already covered and that force exists to rewrite.
    #
    # fix(#1549): this used to be able to lean on "the delete above already
    # emptied the table, so both flags select the same rows". It cannot any
    # more — nothing has been deleted at this point — which makes the explicit
    # force=True the only thing separating the two questions.
    # fix(#1549 review): the end-of-run reclamation acts on an observation made
    # here, at the start, and must not delete anything written since. What it
    # needs is not a clock but the IDENTITY of the rows it saw: `(record_id,
    # updated_at)` pairs, which any write by any writer changes.
    #
    # fix(#1584 review r1, codex P2): taken BEFORE the fetch below, not after.
    # The emptiness this protects against is decided BY that fetch — it is the
    # read that sees a record's title and summary — and materialising every
    # record takes as long as it takes. A snapshot taken afterwards leaves that
    # whole interval unguarded: a record read as empty, then edited and
    # re-embedded before the snapshot was taken, would be captured in its NEW
    # version and reclaimed. The snapshot has to precede the observation it
    # protects, not follow it.
    #
    # fix(#1584 review r3, codex P2): versions rather than a timestamp cutoff.
    # See `_delete_embeddings_for` for why a clock got this wrong in both
    # directions. Force-only: a non-force run reclaims nothing, so it does not
    # pay for this read.
    #
    # Narrowed to records with no TITLE, which is a superset of what the
    # reclamation can ever touch and is what keeps this from being a copy of the
    # whole table in worker memory. `build_content_text` returns "" only when
    # the title, summary, keywords, lineage and translations are ALL empty, so a
    # record carrying a title is never skipped and its rows are never
    # reclaimable. Titleless records are a rounding error on a real catalog,
    # where the unnarrowed form would be one (uuid, timestamp) pair per
    # embedding row. The one thing the narrowing gives up: a record whose title
    # is cleared between this snapshot and the fetch is skipped but was not
    # snapshotted, so its rows wait for the next force run, which sees it
    # titleless. The ingest writer already leaves such rows in place (it skips
    # empty content rather than deleting), so this defers a reclamation rather
    # than inventing a stale row.
    observed_rows: list[tuple[Any, Any]] = []
    if record_orm is not None:
        observed_rows = [
            (record_id, updated_at)
            for record_id, updated_at in (
                await session.execute(
                    select(RecordEmbedding.record_id, RecordEmbedding.updated_at).where(
                        RecordEmbedding.record_id.in_(
                            select(record_orm.id).where(
                                or_(
                                    record_orm.title.is_(None),
                                    record_orm.title == "",
                                )
                            )
                        )
                    )
                )
            ).all()
        ]

    records = await port.get_records_without_embeddings(session, force=force)

    # Extract all data upfront so rollback/commit won't trigger lazy loads
    # (rollback expires all ORM instances → accessing attrs causes MissingGreenlet)
    record_data = [{"id": r.id, **_content_fields(r)} for r in records]

    total = len(record_data)

    if total == 0:
        logger.info("Backfill: no records without embeddings found")
        return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    # Gate once for the whole run (the per-record path checked this per call).
    # fix(#1511): force already gated above, before the pre-flight spends a
    # provider call. Re-reading here could only turn a run that has already
    # proved it can embed into one that skips everything, so force does not ask
    # twice. fix(#1549): the original reason was blunter — the gate sat ahead of
    # a delete, and a second read could have left the catalog emptied and then
    # skipped. That delete is gone; the gate stays because paying for a
    # pre-flight and then declining to use it is still the wrong shape.
    if not force and not await AI_ENABLED.get(session):
        logger.info("Backfill: AI disabled, skipping", total_records=total)
        return {"processed": 0, "created": 0, "skipped": total, "errors": 0}

    # fix(#1511): on the force path reuse the snapshot the guard above already
    # validated. A second read here would reopen the window that guard closes —
    # resolution can fail between the two calls, and by then the delete has
    # committed. The non-force path has nothing to destroy, so it snapshots
    # here, where the original read lived.
    # fix(#1511 review, codex P1): all three parts are pinned into every provider
    # call below. generate_embeddings_batch would otherwise re-read the config
    # per call, so an admin swapping models mid-run gets model B's vectors
    # stored under model A's label — search on the active model then skips rows
    # it believes it wrote. fix(#1525): the endpoint is the third part. The rows
    # name a model, and a model served by two endpoints is two vector spaces
    # under one label; on the shipped provider the same edit instead makes every
    # remaining batch raise, which abandons the rest of the catalog.
    # fix(#1533): the storage width is pinned in the same two places and for the
    # same reason. On the force path it is the value the pre-flight was measured
    # against, so it is read up there rather than re-read here.
    if pinned is None:
        pinned = await _snapshot_embedding_config(session)
        pinned_column_dims = await _live_column_dims(session)
    model_name, embedding_dims, base_url = pinned
    # fix(#1546): every row this run writes is stamped with THIS, the identity
    # of the configuration the run pinned. Not a fresh read at write time: the
    # endpoint half in particular has to be the one the provider call was made
    # against, and `base_url` above is exactly the value passed to
    # `generate_embeddings_batch` below.
    config_fingerprint = embedding_config_fingerprint(*pinned)

    # Build embeddable (record_id, content_text) pairs; empty content skips.
    skipped_ids: list[Any] = []
    items: list[tuple[object, str]] = []
    for rd in record_data:
        content_text = build_content_text(
            title=rd["title"],
            summary=rd["summary"],
            keywords=rd["keywords"],
            lineage=rd["lineage"],
            localized_texts=rd["localized_texts"],
        )
        if not content_text:
            skipped_ids.append(rd["id"])
            continue
        items.append((rd["id"], content_text))
    skipped = len(skipped_ids)

    logger.info("Backfill: starting", total_records=total, batch_size=_BATCH_SIZE)

    created = 0
    errors = 0
    # fix(#1544): the run's traceback budget, one per distinct exception type.
    traced_errors: set[str] = set()

    for start in range(0, len(items), _BATCH_SIZE):
        # fix(#1709 review r6): the cooperative stop for a run whose job was
        # settled underneath it — a user cancel above all. Procrastinate's
        # abort for an async task IS asyncio cancellation and needs no polling
        # once the request reaches the worker; this check covers the request
        # that never landed (the cancel endpoint's queue abort is best-effort
        # by design — the DB CAS is the correctness mechanism). One indexed
        # read per batch bounds the post-cancel overlap to a single batch of
        # provider spend, instead of the whole remaining catalog running
        # concurrently with a successor run admitted by the freed
        # one-active-backfill slot. Before _raise_on_pin_drift so a stopped
        # run does not pay even the config read.
        if should_continue is not None and not await should_continue():
            logger.warning(
                "backfill_stopped_job_no_longer_running",
                created=created,
                errors=errors,
                remaining=len(items) - start,
            )
            break

        # fix(#1525 review r4, codex P2): the pin protects each batch from the
        # config moving underneath it, but nothing was noticing that it HAD
        # moved. A run pinned to endpoint A that keeps going after the active
        # endpoint becomes B writes A-space vectors for the rest of the
        # catalog, and `RecordEmbedding` recorded only `model_name`, so semantic
        # search later built its query vector from the live endpoint and
        # filtered stored rows by model alone — B-space queries against A-space
        # documents under one label, and the backfill reported success.
        #
        # fix(#1546): those rows are now stamped with the pin, so search skips
        # them rather than matching them. This check stays: invisible is better
        # than wrong, but not writing a whole catalog nobody can use is better
        # than either, and stopping is also what tells the operator to re-run
        # under the new configuration.
        #
        # Outside the try below, deliberately: this must stop the run, not be
        # counted as a batch error and retried per record. The sibling check
        # after the provider call cannot have that placement, so it raises
        # `_PinDrift` and the batch handler re-raises it to the same effect.
        #
        # Kept alongside that one rather than replaced by it: a post-call check
        # alone is sufficient for correctness, but drift that lands BETWEEN
        # batches would then only surface after the next batch had already been
        # generated and paid for. One config read per batch is the cheaper half
        # of that trade.
        await _raise_on_pin_drift(
            session, pinned, created, pinned_column_dims=pinned_column_dims
        )

        batch = items[start : start + _BATCH_SIZE]
        try:
            vectors = await generate_embeddings_batch(
                [content for _, content in batch],
                session,
                model=model_name,
                dimensions=embedding_dims,
                base_url=base_url,
            )
            # fix(#1533): the whole batch, not the first vector. Agreement
            # across inputs is what makes a width mismatch structural rather
            # than one bad record, so a batch of mixed widths deliberately does
            # NOT stop here: it fails its insert, drops into the retry loop, and
            # every vector is judged on its own down there (#1579 review).
            #
            # Ahead of the inserts because it decides not to write at all, so
            # unlike the drift check below it needs no lock to be sound.
            _raise_on_structural_width(vectors, pinned_column_dims, created)
            # fix(#1549): the batch's own old rows are removed HERE, in the
            # transaction that writes their replacements, rather than by a bulk
            # DELETE committed before the run generated anything.
            rows = [
                {
                    "record_id": record_id,
                    "embedding": vector,
                    "model_name": model_name,
                    # fix(#1546): stamped from the PIN. `pinned` is the triple
                    # that was handed to the provider call above, so the stamp
                    # names the configuration that actually produced this vector
                    # rather than whatever the live configuration happens to be
                    # by the time the row is written.
                    "config_fingerprint": config_fingerprint,
                    "content_hash": compute_content_hash(content),
                }
                # fix(#1581 review): `strict=True`, because `zip` silently
                # truncating is only the visible half of the problem. A provider
                # that skips a MIDDLE input answers `[v1, v3]` for
                # `[t1, t2, t3]` — the shipped `embed()` returns
                # `[item.embedding for item in response.data]` with no index
                # sort and no count check — and a truncating zip then pairs the
                # second record with the THIRD vector, writing a permanently
                # wrong vector under a valid-looking content hash and stamp. No
                # guard downstream can see that: the row is well formed, in the
                # right space, and simply not this record's.
                #
                # Raising instead sends the whole batch to the per-record retry,
                # where `[vector] = await generate_embeddings_batch(...)` is
                # alignment-safe by construction: a single-element unpack cannot
                # pair a text with another text's vector. Paying k provider
                # calls for that is the right trade in a failure mode where the
                # provider has already broken its contract.
                for (record_id, content), vector in zip(batch, vectors, strict=True)
            ]
            await _replace_embeddings(session, rows, record_orm=record_orm)
            # fix(#1579 review r3, codex P2): WRITE, then check, then commit.
            # The check reads `pg_attribute`, which locks nothing, so checking
            # before the rows were sent left a window in which an `ALTER TABLE`
            # could take ACCESS EXCLUSIVE, commit, and be missed entirely. When
            # that ALTER widened the column to an unconstrained `vector` the
            # old-width inserts then SUCCEEDED, and the run reported success
            # over a column that had moved under it — the one outcome
            # `_pinned_config_drift` says a widening change must not produce.
            #
            # The write takes RowExclusiveLock on the relation, which ACCESS
            # EXCLUSIVE conflicts with. So an ALTER that landed first is seen by
            # the check (and these rows roll back with the abort), and one that
            # arrives after waits for our commit. Check-then-act is only sound
            # while the thing checked cannot move, and this is what stops it
            # moving.
            #
            # fix(#1546): the write is a Core INSERT ... ON CONFLICT rather than
            # an ORM add plus `session.flush()`. It takes the same lock at the
            # same point, so everything above still holds; what changed is only
            # that the statement is emitted by `session.execute` directly.
            #
            # fix(#1549): the delete that clears what these rows replace is
            # inside `_replace_embeddings`, in this same transaction and ahead
            # of the write, so it takes the lock at the same moment and the
            # abort below rolls back both halves together. A batch whose
            # replacements never commit leaves its records holding the vectors
            # they already had.
            #
            # A write that RAISES because the column moved to a different fixed
            # width is not lost: the batch handler retries per record, and the
            # retry's pre-call check reads the new width and stops the run.
            #
            # fix(#1525 review r5, codex P2): and the drift check runs again
            # before ACCEPTING the batch, not only before requesting it. The
            # check above has no successor for the LAST batch, so an edit
            # landing during that final provider call was never observed: the
            # vectors were written and the run reported success while the active
            # endpoint had moved. Checking here means the batch in flight is
            # discarded rather than committed, so the run stops without adding a
            # row nothing will match. `_PinDrift` is re-raised past the batch
            # handler below.
            await _raise_on_pin_drift(
                session,
                pinned,
                created,
                pinned_column_dims=pinned_column_dims,
                error=_PinDrift,
            )
            await session.commit()
            # fix(#1581): count what was WRITTEN, not what was asked for. With
            # the strict zip above these are the same number on the success
            # path, which is the point: a batch either wrote a row for every
            # text or raised and wrote none. `created += len(batch)` was wrong
            # because it stayed true after a truncating zip had dropped the
            # tail, and #1550's "errors and nothing created" guard cannot fire
            # on a run claiming it created everything.
            created += len(rows)
        except _PinDrift:
            # fix(#1525 review r5, codex P2): not a batch failure. Retrying it
            # per record would generate the same vectors against the same stale
            # pin and commit them one at a time, which is the outcome the check
            # exists to prevent.
            await session.rollback()
            raise
        except Exception as exc:  # broad: per-batch backfill is isolated; embedding API/DB errors are counted not raised
            await session.rollback()
            # fix(#1544): the same treatment `_retry_batch_per_record` gives a
            # record, sharing its budget. One batch failure is 1/128th the volume
            # of the retry storm it opens, but a batch that fails usually fails
            # every one of its records too, so the two paths raise the same type
            # and the run should pay for that stack once between them, not twice.
            logger.warning(
                "Backfill: batch failed, retrying records individually",
                batch_start=start,
                batch_size=len(batch),
                **_error_fields(exc, traced_errors),
            )
            made, failed = await _retry_batch_per_record(
                session,
                batch,
                pinned,
                created,
                model_name=model_name,
                embedding_dims=embedding_dims,
                base_url=base_url,
                pinned_column_dims=pinned_column_dims,
                traced_errors=traced_errors,
                record_orm=record_orm,
            )
            created += made
            errors += failed

        logger.info(
            "Backfill progress",
            processed=min(start + _BATCH_SIZE, len(items)),
            total=len(items),
            created=created,
            errors=errors,
        )

    # fix(#1549): a record whose metadata no longer builds any embeddable text
    # has a stale vector and no replacement to pair a delete with. The bulk
    # DELETE used to reclaim those; per-batch replacement cannot, because these
    # records never reach a batch. Cleaning them up LAST rather than first is
    # what keeps the rest of this function's promise: an aborted run has not
    # touched them, and a completed one honours what force means. Nothing is
    # lost by the delay — regenerating them is impossible either way, so a
    # re-run would not bring these rows back at any point in the run.
    #
    # fix(#1549 review): but "last" is what makes the observation stale. The
    # emptiness was decided when the run read its records, and by the time this
    # pass runs an editor may have given one of them a title, in which case the
    # ingest path has already written it a fresh, correctly stamped vector. The
    # bulk delete could not hit that case because it ran before any such write.
    # `observed_rows` bounds this to the exact row versions the run saw before
    # it looked at the catalog, so a vector written DURING the run — by any
    # writer, on any clock — no longer matches and survives.
    if record_orm is not None and skipped_ids:
        # NOT `skipped`: that name holds the run's skipped COUNT and is
        # reported back to the caller.
        skipped_set = set(skipped_ids)
        reclaimable = [pair for pair in observed_rows if pair[0] in skipped_set]
        # fix(#1584 review r4, codex P2): an unchanged ROW is not proof of an
        # unchanged RECORD. The ingest writer skips its write when the content
        # hash is unchanged, so an editor who restores exactly the content a
        # row was computed from leaves the row, and its `updated_at`, untouched:
        # the pair still matches and the row would be reclaimed although it is
        # valid again. So every record whose rows are about to go is re-read
        # first, and only those still empty NOW are reclaimed. One read per
        # titleless record that holds vectors, which is the bound the snapshot
        # already has.
        #
        # fix(#1584 review r5): re-read and delete under one row lock, one
        # chunk per transaction. `_records_still_empty` locks the chunk's
        # records FOR UPDATE; the delete follows in the same transaction; the
        # commit releases them. Chunked for the same reason the run is: asyncpg
        # caps a statement at 32767 bind parameters, and each pair spends two
        # of them — and a chunk is also how long any one editor can be held.
        removed = await _reclaim_observed_rows(session, port, record_orm, reclaimable)
        logger.info(
            "Backfill: dropped vectors for records with no embeddable content",
            count=removed,
        )

    processed = created + errors
    result_dict = {
        "processed": processed,
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }

    logger.info("Backfill complete", **result_dict)
    return result_dict


if __name__ == "__main__":
    import asyncio

    async def _run():
        from app.core.db import async_session  # fix(#909): late-bind

        async with async_session() as session:
            result = await backfill_embeddings(session)
            logger.info("Backfill complete", result=result)

    asyncio.run(_run())
