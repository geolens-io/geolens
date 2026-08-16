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

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import AI_ENABLED, EMBEDDING_DIMS
from app.platform.extensions import get_processing_port
from app.processing.embeddings.models import RecordEmbedding
from app.processing.embeddings.service import (
    build_content_text,
    compute_content_hash,
    generate_embeddings_batch,
)

logger = structlog.stdlib.get_logger(__name__)

# fix(#448): texts per provider call. OpenAI accepts up to 2048 inputs per
# request; 128 keeps request bodies modest for compatible providers (Ollama,
# Groq, Together) while still collapsing a 10K-record backfill to ~80 calls.
_BATCH_SIZE = 128


async def _snapshot_embedding_config(session: AsyncSession) -> tuple[str, int | None]:
    """Capture (model, dimensions) as one consistent pair, or refuse the run.

    The two values come from separate `PersistentConfig` reads — there is no
    combined read, and building one would bypass the per-key validation and
    cache machinery in `PersistentConfig.get`. So capture both, then read both
    again and compare. Any single admin change lands inside one of the two
    windows and shows up as a difference; only a change-and-revert inside the
    same few milliseconds slips through, which is not a case worth more code.

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

    model_name = await resolve_embedding_model_name(session)
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
    dimensions = await EMBEDDING_DIMS.get(session)

    if (
        await resolve_embedding_model_name(session) != model_name
        or await EMBEDDING_DIMS.get(session) != dimensions
    ):
        logger.error("backfill_aborted_embedding_config_changed")
        raise RuntimeError(
            "Cannot regenerate embeddings: the embedding model or dimensions "
            "changed while the run was starting. Existing vectors were left "
            "untouched; re-run to use the new configuration."
        )

    return model_name, dimensions


async def backfill_embeddings(session: AsyncSession, *, force: bool = False) -> dict:
    """Generate embeddings for records.

    Args:
        session: Database session.
        force: If True, delete all existing embeddings first and regenerate
               for every record. Useful when the model or dimensions change.

    Returns:
        Dict with counts: processed, created, skipped, errors.

    Raises:
        RuntimeError: If the active embedding model cannot be resolved, or if
            the model/dimensions change while the run is starting. On
            force=True nothing is deleted in either case.
    """
    port = get_processing_port()

    pinned: tuple[str, int | None] | None = None

    if force:
        # fix(#1511): snapshot the config BEFORE the delete below commits.
        # Every row this run writes back is stamped with the active model and
        # `model_name` is NOT NULL, so a force run started while
        # persistent-config resolution is failing clears the whole table and
        # then cannot insert a single replacement — a Regenerate All clicked
        # during a config blip converts full coverage into zero coverage.
        # This is the same fail-closed call documented in
        # DefaultProcessingPort.get_records_without_embeddings (#1506), which
        # could not cover this branch: by the time that query runs on the force
        # path the vectors are already gone, so the check has to happen here.
        # Placing it ahead of the DELETE is also what makes the snapshot's
        # abort-on-change free: there is nothing to undo.
        pinned = await _snapshot_embedding_config(session)

        # The HNSW index lives in Alembic migration 0012 (and is recreated
        # by service.rebuild_embedding_column on dimension change). On
        # force=True we just clear the active tenant's rows; no need to drop
        # the index. RecordEmbedding is not RLS-scoped itself, so the Record
        # subquery is the required tenant boundary in hosted mode.
        Record = port.get_record_orm_class()
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
    if not await AI_ENABLED.get(session):
        logger.info("Backfill: AI disabled, skipping", total_records=total)
        return {"processed": 0, "created": 0, "skipped": total, "errors": 0}

    # fix(#1511): on the force path reuse the snapshot the guard above already
    # validated. A second read here would reopen the window that guard closes —
    # resolution can fail between the two calls, and by then the delete has
    # committed. The non-force path has nothing to destroy, so it snapshots
    # here, where the original read lived.
    # fix(#1511 review, codex P1): both halves are pinned into every provider
    # call below. generate_embeddings_batch would otherwise re-read the config
    # per call, so an admin swapping models mid-run gets model B's vectors
    # stored under model A's label — search on the active model then skips rows
    # it believes it wrote.
    if pinned is None:
        pinned = await _snapshot_embedding_config(session)
    model_name, embedding_dims = pinned

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

    for start in range(0, len(items), _BATCH_SIZE):
        batch = items[start : start + _BATCH_SIZE]
        try:
            vectors = await generate_embeddings_batch(
                [content for _, content in batch],
                session,
                model=model_name,
                dimensions=embedding_dims,
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
        except Exception:  # broad: per-batch backfill is isolated; embedding API/DB errors are counted not raised
            await session.rollback()
            logger.warning(
                "Backfill: batch failed, retrying records individually",
                batch_start=start,
                batch_size=len(batch),
                exc_info=True,
            )
            # fix(#449, codex P2): one rejected input (e.g. a record over the
            # model's token limit) must not sink the other 127 — retry the
            # failed batch per record so only the bad ones count as errors.
            for record_id, content in batch:
                try:
                    [vector] = await generate_embeddings_batch(
                        [content],
                        session,
                        model=model_name,
                        dimensions=embedding_dims,
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
                    created += 1
                except Exception:  # broad: same isolation, per record
                    await session.rollback()
                    errors += 1
                    logger.warning(
                        "Backfill: error processing record",
                        record_id=record_id,
                        exc_info=True,
                    )

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
