"""Backfill embeddings for records that don't have them yet.

Processes all records missing a corresponding RecordEmbedding row.
fix(#448): texts are embedded in batches of _BATCH_SIZE per provider call
(the embeddings endpoint accepts input lists) instead of one call per
record — a 50-200x reduction in API round trips on bulk backfills.
A failed batch is retried per record so a single rejected input doesn't
sink its batchmates; only the individually-failing records count as errors.

Can be run as a module: python -m app.embeddings.backfill
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistent_config import AI_ENABLED, EMBEDDING_MODEL
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


async def backfill_embeddings(session: AsyncSession, *, force: bool = False) -> dict:
    """Generate embeddings for records.

    Args:
        session: Database session.
        force: If True, delete all existing embeddings first and regenerate
               for every record. Useful when the model or dimensions change.

    Returns:
        Dict with counts: processed, created, skipped, errors.
    """
    if force:
        from sqlalchemy import delete

        # The HNSW index lives in Alembic migration 0012 (and is recreated
        # by service.rebuild_embedding_column on dimension change). On
        # force=True we just clear the rows; no need to drop the index.
        await session.execute(delete(RecordEmbedding))
        await session.commit()
        logger.info("Backfill: cleared all existing embeddings (force=True)")

    # Find records that have no embedding row, eager-load keywords
    port = get_processing_port()
    records = await port.get_records_without_embeddings(session, force=False)

    # Extract all data upfront so rollback/commit won't trigger lazy loads
    # (rollback expires all ORM instances → accessing attrs causes MissingGreenlet)
    record_data = [
        {
            "id": r.id,
            "title": r.title,
            "summary": r.summary,
            "keywords": [kw.keyword for kw in r.keywords] if r.keywords else [],
            "lineage": r.lineage_summary,
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

    model_name = await EMBEDDING_MODEL.get(session)

    # Build embeddable (record_id, content_text) pairs; empty content skips.
    skipped = 0
    items: list[tuple[object, str]] = []
    for rd in record_data:
        content_text = build_content_text(
            title=rd["title"],
            summary=rd["summary"],
            keywords=rd["keywords"],
            lineage=rd["lineage"],
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
                [content for _, content in batch], session
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
                    [vector] = await generate_embeddings_batch([content], session)
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

    from app.core.db import async_session

    async def _run():
        async with async_session() as session:
            result = await backfill_embeddings(session)
            logger.info("Backfill complete", result=result)

    asyncio.run(_run())
