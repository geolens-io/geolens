"""Backfill embeddings for records that lack one under the ACTIVE model.

Texts are embedded in batches of _BATCH_SIZE per provider call; a failed batch
is retried per record so one rejected input does not sink its batchmates, and
only the individually failing records count as errors (#448, #449, #1506).

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

# fix(#448): 128 keeps request bodies modest for compatible providers while
# collapsing a 10K-record backfill to ~80 calls.
_BATCH_SIZE = 128

# Text for the force-path pre-flight embedding. Short, so the call is cheap,
# and constant, so a provider's cache can serve it.
_PREFLIGHT_TEXT = "geolens embedding preflight"

# fix(#1544): the actionable part of an error is at the front; the tail is the
# statement and its bound parameters, one of which is the vector.
_MAX_ERROR_CHARS = 200


def _compact_error(exc: BaseException) -> str:
    """Describe an exception in one short line, without its bound parameters.

    Prefers the driver's own message (`DBAPIError.orig`); otherwise cuts at
    SQLAlchemy's `[SQL:` marker, collapses whitespace and truncates.

    fix(#1577 r1/r2): THE REDACTOR RUNS FIRST, ON THE RAW STRING. Truncating
    first can cut the `@` that terminates userinfo; collapsing whitespace first
    can split a URL so the match dies before the `@`. Nothing may be inserted
    above it.
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

    fix(#1544): one traceback per distinct exception type per run, tracked by
    qualified name. The traceback, not the vector, is the expensive part of a
    failing backfill (a 200-record run took 194 s before and 1.5 s after).
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

    pgvector stores the dimension in `atttypmod` with no offset; -1 means an
    unconstrained `vector`. Storage rather than `EMBEDDING_DIMS`, because the
    two can disagree and that is the point of asking.
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

    fix(#1579): deliberately NOT a `_PinDrift`, so the per-record handler
    counts it and carries on (#449 isolation).
    """


def _column_rejects_width(generated: int, pinned_column_dims: int | None) -> str | None:
    """Describe a generated width the column will not take, or None if it will.

    The fit test only; callers decide what a mismatch means. `isinstance`
    rather than `is not None`, because -1 means unconstrained and never mismatches.
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

    fix(#1533): a width that was already wrong when the run started, which no
    comparison guard can see. Not a pre-flight on the non-force path: that
    would cost a provider call and abort a run one transient failure would
    otherwise survive (#449). fix(#1579): UNIFORMLY is the distinction; mixed
    widths are one bad input and fall to the per-record retry.
    """
    # fix(#1579 r2): TWO vectors minimum. One input agrees with itself
    # vacuously, and a final batch of one (any catalog sized 1 mod _BATCH_SIZE)
    # was read as structural; it falls through to the retry rule instead.
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

    Drift first, then fit (fix(#1579 r4)): asking fit first returned early on a
    matching vector and left the LAST record's drift unobserved. A mismatch
    against a column that has not moved raises `_AnomalousVectorWidth` so the
    caller counts it and carries on (#449). Delegates the drift wording to
    `_raise_on_pin_drift` so the module has one author of "the column moved".
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

    fix(#1546): `uq_record_embedding_model` is `(record_id, model_name)` and a
    non-force run may offer a record whose only row was written under another
    configuration, which a plain INSERT answers with a unique violation.
    `updated_at` is set explicitly because `onupdate=` is ORM-level only.
    """
    # fix(#1583): stamp the INSERT branch too; `set_` only governs ON CONFLICT
    # and the server_default is transaction-start `now()`.
    stmt = pg_insert(RecordEmbedding).values(
        [row | {"updated_at": func.clock_timestamp()} for row in rows]
    )
    return stmt.on_conflict_do_update(
        index_elements=["record_id", "model_name"],
        set_={
            "embedding": stmt.excluded.embedding,
            "content_hash": stmt.excluded.content_hash,
            "config_fingerprint": stmt.excluded.config_fingerprint,
            # fix(#1583): `clock_timestamp()`, not `now()`. `now()` is
            # transaction-start time, and a batch spends a provider call in its
            # transaction, which inverts the related-items `updated_at` order.
            "updated_at": func.clock_timestamp(),
        },
    )


def _content_fields(record) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """The fields ``build_content_text`` reads, pulled off a record eagerly.

    Eager, because a rollback expires every ORM instance and a later attribute
    access raises ``MissingGreenlet``. One function for both readers so "is
    this record empty" is asked the same way at both ends of the run.
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
    """Which of these records have no embeddable content RIGHT NOW, and hold them.

    fix(#1584 r4/r5): ``expire_all`` first, because this session's identity
    map still holds the instances the run loaded at its start. Records are
    locked ``FOR UPDATE`` and the caller keeps the transaction open through
    its DELETE, so an editor's restore lands on one side or the other. A
    record that no longer exists counts as empty.
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

    The `Record` subquery is the tenant boundary: `RecordEmbedding` has no RLS
    policy of its own (#1511). fix(#1584 r3): ``observed`` narrows the delete
    to the exact `(record_id, updated_at)` row versions the run saw, which no
    clock comparison can get wrong; only the end-of-run reclamation passes it.
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

    fix(#1549): the DELETE precedes the INSERT in the same transaction, so an
    aborted run has replaced some records and left the rest untouched. The
    delete clears every row the record holds under any model, which the
    upsert alone cannot reach. The COMMIT belongs to the caller (fix(#1579
    r3)): its drift check is only sound while it holds the RowExclusiveLock
    these statements take. ``record_orm`` is `Record` on a force run and None
    otherwise, which means "delete nothing".
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

    The values come from separate `PersistentConfig` reads, so they are
    captured, read again and compared (fix(#1511 r2)); a change inside the
    window shows up as a difference. fix(#1525): the endpoint is captured in
    the same window and resolved through the provider, whose fallback chain
    and credential binding it owns.

    Known residue (#1525 r2, tracked as #1543): the endpoint is read through
    the provider's per-key cache and cannot be read uncached from here. For
    the shipped provider a stale entry either resolves to the identical
    approved URL or fails loudly, so only an extension provider that resolves
    its endpoint from the database is exposed.

    Raises:
        RuntimeError: If the model cannot be resolved, or if any value changed
            while it was being captured. Call BEFORE anything destructive.
    """
    # Imported in-function, as the port does, so patching the module attribute
    # reaches this call site.
    from app.processing.embeddings.helpers import (
        UNKNOWN_EMBEDDING_MODEL,
        resolve_embedding_model_name,
    )

    # fix(#1525 r2): read uncached. `PersistentConfig.get` answers from a
    # per-key cache that `update_settings` evicts only after its commit, so two
    # cached reads can agree with each other on the far side of an update.
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

    # fix(#1525): ONE window over all three. A per-value capture-and-compare
    # leaves a gap in which "old model + new endpoint" is invisible to both.
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
    """A run-stopping condition found with a batch generated but not committed.

    A distinct type so the two broad handlers re-raise it instead of retrying
    per record or counting it as a bad input. fix(#1533): also carries a
    STRUCTURAL width mismatch; an ISOLATED one is `_AnomalousVectorWidth`.
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

    fix(#449): only the bad records count as errors. Split out because the
    drift bracketing pushed `backfill_embeddings` past the McCabe gate.
    `created` is the run's total so an abort message can report it;
    `pinned_column_dims` is the pinned storage width (fix(#1533));
    `traced_errors` is the run's traceback budget; `record_orm` carries the
    force flag (fix(#1549)) so a record that fails again keeps its old vector.
    """
    made = 0
    failed = 0
    for record_id, content in batch:
        try:
            # fix(#1525 r6): the drift checks bracket the retry's provider call
            # too. The pre-call check is not redundant with the previous
            # record's post-call one, which never ran if that record failed.
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
            # fix(#1533): per vector on this path, ahead of the write so a
            # typmod error cannot turn a named abort into a counted one. A
            # mismatch against an unmoved column is one bad record (#1579).
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
                        # fix(#1546): from `pinned`, the configuration this
                        # call was made under, never a fresh read.
                        "config_fingerprint": embedding_config_fingerprint(*pinned),
                        "content_hash": compute_content_hash(content),
                    }
                ],
                record_orm=record_orm,
            )
            # fix(#1579 r3): the row is SENT before the post-call check so the
            # check holds the RowExclusiveLock; fix(#1549): the delete inside
            # `_replace_embeddings` rolls back with it on abort.
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
            # fix(#1525 r6): drift is not a bad record; it stops the run.
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

    fix(#1525 r4): notices that the run has outlived its pinned configuration,
    read uncached for the reason `_snapshot_embedding_config` gives.
    fix(#1533): the storage width is checked too, because the column moves
    without a settings write (ENV_ONLY_CONFIG, a hand `ALTER TABLE`, a
    restored dump, a failed rebuild).

    NOT drift: an unresolvable model (a transient DB blip must not abort a
    long run) and a provider resolve that RAISES (for the shipped provider
    that is an endpoint edit diverging from the approved URL, and `embed`
    re-binds to the approved one, so the pin is still accurate).
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

    # fix(#1533): BEFORE the endpoint block, whose `except` returns None and
    # would hide this on a half-configured install. Any change counts,
    # including a widening: those inserts SUCCEED, so nothing else reports it.
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

    fix(#1511 r3): proves the capability instead of guarding failure modes one
    at a time; subsumes provider outages, revoked keys, exhausted quota and
    rejected dimensions for one provider call per force run. The cheaper
    guards stay because they fail earlier and name the problem better.

    Raises:
        RuntimeError: If the embedding cannot be generated or cannot be stored
            in the column as it stands. Run this BEFORE deleting anything.
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

    # fix(#1511 r4, #1533): the vector must also FIT the column, asked of
    # storage so it holds for any cause (failed rebuild, restored dump, hand
    # ALTER, ENV_ONLY_CONFIG), and read once by the caller so the run pins it.
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
               already holds, per batch inside the transaction that writes the
               batch (fix(#1549)); the table is never emptied up front.
        should_continue: Optional zero-argument async callable polled once per
               batch BEFORE its provider call; False stops the run at the
               boundary (fix(#1709 r6)). Opaque here: this module knows
               records and vectors, not jobs.

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
    # fix(#1533): the storage width the run commits to, read off `pg_attribute`
    # rather than `PersistentConfig`, because the two can disagree.
    pinned_column_dims: int | None = None
    # fix(#1549): non-None only on a force run; it is both the tenant boundary
    # for the per-batch delete and the flag that a batch replaces.
    record_orm = None

    if force:
        Record = port.get_record_orm_class()
        record_orm = Record

        # fix(#1511 r5): a tenant with no visible records has nothing the
        # DELETE could remove, so demanding a working provider first turned a
        # no-op into a 502 on a fresh install.
        if (await session.execute(select(Record.id).limit(1))).first() is None:
            logger.info("Backfill: no visible records, nothing to regenerate")
            return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

        # fix(#1511): everything that could stop this run must fail BEFORE the
        # first per-batch delete; `model_name` is NOT NULL, so a run started
        # under an unusable config could otherwise write nothing back.
        if not await AI_ENABLED.get(session):
            logger.error("backfill_force_aborted_ai_disabled")
            raise RuntimeError(
                "Cannot regenerate embeddings: AI features are disabled. "
                "Existing vectors were left untouched; enable AI and re-run."
            )

        # Fail-closed on an unresolvable model (#1506): force never consults the
        # model through get_records_without_embeddings.
        pinned = await _snapshot_embedding_config(session)
        pinned_column_dims = await _live_column_dims(session)

        # fix(#1511 r3): a comparison guard is blind to a pair that is wrong,
        # committed and stable; one real embedding tests the property itself.
        await _preflight_embedding(session, pinned, pinned_column_dims)

        # fix(#1549): no bulk DELETE here any more. Deletion is per batch, inside
        # the transaction that writes the replacements (`_replace_embeddings`),
        # so an aborted run leaves a MIX that #1546's stamp keeps readable.

    # fix(#1506): `force` passes through; the port's non-force branch answers a
    # different question. fix(#1584 r1/r3): the reclamation snapshot, taken
    # BEFORE the fetch that decides emptiness, as row versions, titleless only.
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

    # Gate once for the whole run. fix(#1511): force gated above, before the
    # pre-flight spent a provider call, and does not ask twice.
    if not force and not await AI_ENABLED.get(session):
        logger.info("Backfill: AI disabled, skipping", total_records=total)
        return {"processed": 0, "created": 0, "skipped": total, "errors": 0}

    # fix(#1511, #1525, #1533): force reuses the validated snapshot; all three
    # parts plus the storage width are pinned into every provider call so a
    # mid-run config change cannot store model B's vectors under A's label.
    if pinned is None:
        pinned = await _snapshot_embedding_config(session)
        pinned_column_dims = await _live_column_dims(session)
    model_name, embedding_dims, base_url = pinned
    # fix(#1546): every row is stamped with the PINNED configuration, never a
    # fresh read at write time.
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
        # fix(#1709 r6): cooperative stop for a run whose job was settled under
        # it; the cancel endpoint's queue abort is best-effort and the DB CAS
        # is the mechanism. Before the drift check so a stopped run pays nothing.
        if should_continue is not None and not await should_continue():
            logger.warning(
                "backfill_stopped_job_no_longer_running",
                created=created,
                errors=errors,
                remaining=len(items) - start,
            )
            break

        # fix(#1525 r4): stop when the pin is no longer active; a catalog
        # written into a stale vector space reports success and matches nothing.
        # Outside the try: this must stop the run, not count as a batch error.
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
            # fix(#1533): the whole batch, so mixed widths fall to the
            # per-record retry (#1579). Ahead of the inserts, so no lock needed.
            _raise_on_structural_width(vectors, pinned_column_dims, created)
            # fix(#1549): the batch's own old rows go in this same transaction.
            rows = [
                {
                    "record_id": record_id,
                    "embedding": vector,
                    "model_name": model_name,
                    # fix(#1546): stamped from the PIN that produced the vector.
                    "config_fingerprint": config_fingerprint,
                    "content_hash": compute_content_hash(content),
                }
                # fix(#1581): `strict=True`. A provider that skips a MIDDLE
                # input pairs a record with another text's vector under a
                # valid-looking hash; raising sends the batch to the retry.
                for (record_id, content), vector in zip(batch, vectors, strict=True)
            ]
            await _replace_embeddings(session, rows, record_orm=record_orm)
            # fix(#1579 r3): WRITE, then check, then commit: the write's
            # RowExclusiveLock makes an ALTER either visible or waiting.
            # fix(#1525 r5): the last batch has no successor check; drop it here.
            await _raise_on_pin_drift(
                session,
                pinned,
                created,
                pinned_column_dims=pinned_column_dims,
                error=_PinDrift,
            )
            await session.commit()
            # fix(#1581): count what was WRITTEN; with the strict zip this equals
            # the batch size on success.
            created += len(rows)
        except _PinDrift:
            # fix(#1525 r5): drift is not a batch failure; retrying per record
            # would commit the same stale vectors one at a time.
            await session.rollback()
            raise
        except Exception as exc:  # broad: per-batch backfill is isolated; embedding API/DB errors are counted not raised
            await session.rollback()
            # fix(#1544): shares the traceback budget with the per-record retry.
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

    # fix(#1549): records with no embeddable text have a stale vector and no
    # replacement to pair a delete with, so they are reclaimed LAST, bounded to
    # the row versions the run observed at its start (#1549 review).
    if record_orm is not None and skipped_ids:
        # NOT `skipped`: that name holds the run's skipped COUNT and is
        # reported back to the caller.
        skipped_set = set(skipped_ids)
        reclaimable = [pair for pair in observed_rows if pair[0] in skipped_set]
        # fix(#1584 r4/r5): an unchanged ROW is not an unchanged RECORD (the
        # ingest writer skips on an unchanged hash), so each record is re-read
        # and deleted under one FOR UPDATE lock, one chunk per transaction.
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
