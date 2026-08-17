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
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import AI_ENABLED, EMBEDDING_DIMS
from app.core.url_redaction import redact_url_credentials
from app.platform.extensions import get_processing_port
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
      path `_preflight_embedding` runs BEFORE the DELETE, so the run aborts
      with every existing vector still in place.

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
            await _raise_on_pin_drift(
                session,
                pinned,
                created + made,
                pinned_column_dims=pinned_column_dims,
                error=_PinDrift,
            )
            session.add(
                RecordEmbedding(
                    record_id=record_id,
                    embedding=vector,
                    model_name=model_name,
                    content_hash=compute_content_hash(content),
                )
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


async def backfill_embeddings(session: AsyncSession, *, force: bool = False) -> dict:
    """Generate embeddings for records.

    Args:
        session: Database session.
        force: If True, delete all existing embeddings first and regenerate
               for every record. Useful when the model or dimensions change.

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

    if force:
        Record = port.get_record_orm_class()

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
        # could not cover this branch: by the time that query runs on the force
        # path the vectors are already gone.
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

        # DESTRUCTIVE-FIRST, DELIBERATELY (#1549). This commits before the run
        # knows it can finish, so a drift abort in the batch loop below leaves
        # the table empty and the operator has to re-run. That is the chosen
        # side of the trade, not an oversight: rows record only `model_name`,
        # so a run that carried on under a stale pin would leave a FULL table
        # whose vectors live in a space the active search silently fails to
        # match. Empty is loud and one re-run away; populated-and-wrong looks
        # healthy and is not. Removing the destructive-first shape needs
        # per-batch delete-and-replace in one transaction (which wants #1546's
        # per-row configuration stamp first, or it trades a loud failure for a
        # silent one), a shadow table and swap, or the job lifecycle in #1542 —
        # none of which belong in a PR about pinning a configuration.
        #
        # The HNSW index lives in Alembic migration 0012 (and is recreated
        # by service.rebuild_embedding_column on dimension change). On
        # force=True we just clear the active tenant's rows; no need to drop
        # the index. RecordEmbedding is not RLS-scoped itself, so the Record
        # subquery is the required tenant boundary in hosted mode. `Record` is
        # resolved at the top of this branch, for the emptiness check.
        await session.execute(
            delete(RecordEmbedding).where(
                RecordEmbedding.record_id.in_(select(Record.id))
            )
        )
        await session.commit()
        logger.info("Backfill: cleared visible embeddings (force=True)")

    # Find the records still needing a vector, eager-loading keywords.
    # fix(#1506): pass `force` through instead of hardcoding False. On the
    # force path the delete above already emptied the table, so both flags
    # select the same rows today — but the port's non-force branch now has to
    # resolve the active model, and routing a post-delete regenerate through
    # it would make a run that already destroyed its input depend on that
    # resolution succeeding. force=True asks for "every record" directly,
    # which is what this branch has always meant.
    records = await port.get_records_without_embeddings(session, force=force)

    # Extract all data upfront so rollback/commit won't trigger lazy loads
    # (rollback expires all ORM instances → accessing attrs causes MissingGreenlet)
    record_data = [
        {
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "keywords": [kw.keyword for kw in r.keywords] if r.keywords else [],
            "lineage": r.lineage_summary,
            "localized_texts": [
                "\n".join(
                    part
                    for part in (
                        f"{translation.language}: {translation.title}",
                        translation.summary,
                    )
                    if part
                )
                for translation in r.translations
            ],
        }
        for r in records
    ]

    total = len(record_data)

    if total == 0:
        logger.info("Backfill: no records without embeddings found")
        return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    # Gate once for the whole run (the per-record path checked this per call).
    # fix(#1511): force already gated above, ahead of its delete. Re-reading
    # here could only produce the one outcome that path must never have —
    # everything deleted, then skipped — so force does not ask twice.
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

    # Build embeddable (record_id, content_text) pairs; empty content skips.
    skipped = 0
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
            skipped += 1
            continue
        items.append((rd["id"], content_text))

    logger.info("Backfill: starting", total_records=total, batch_size=_BATCH_SIZE)

    created = 0
    errors = 0
    # fix(#1544): the run's traceback budget, one per distinct exception type.
    traced_errors: set[str] = set()

    for start in range(0, len(items), _BATCH_SIZE):
        # fix(#1525 review r4, codex P2): the pin protects each batch from the
        # config moving underneath it, but nothing was noticing that it HAD
        # moved. A run pinned to endpoint A that keeps going after the active
        # endpoint becomes B writes A-space vectors for the rest of the
        # catalog, and `RecordEmbedding` records only `model_name`, so semantic
        # search later builds its query vector from the live endpoint and
        # filters stored rows by model alone — B-space queries against A-space
        # documents under one label, and the backfill reported success. Persisting
        # an endpoint identity per row so search can filter on it is #1546.
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
            # fix(#1525 review r5, codex P2): and again before ACCEPTING the
            # batch, not only before requesting it. The check above has no
            # successor for the LAST batch, so an edit landing during that
            # final provider call was never observed: the vectors were written
            # and the run reported success while the active endpoint had moved.
            # Checking here means the batch in flight is discarded rather than
            # committed, so the run stops without adding a row nothing will
            # match. `_PinDrift` is re-raised past the batch handler below.
            await _raise_on_pin_drift(
                session,
                pinned,
                created,
                pinned_column_dims=pinned_column_dims,
                error=_PinDrift,
            )
            for (record_id, content), vector in zip(batch, vectors):
                session.add(
                    RecordEmbedding(
                        record_id=record_id,
                        embedding=vector,
                        model_name=model_name,
                        content_hash=compute_content_hash(content),
                    )
                )
            await session.commit()
            created += len(batch)
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
