"""Backfill embeddings for records that don't have them yet.

Processes all records missing a corresponding RecordEmbedding row,
calling generate_and_store_embedding for each. Individual failures
are logged and counted but do not halt the backfill.

Can be run as a module: python -m app.embeddings.backfill
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.extensions import get_processing_port
from app.processing.embeddings.models import RecordEmbedding
from app.processing.embeddings.service import generate_and_store_embedding

logger = structlog.stdlib.get_logger(__name__)


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

        # The HNSW index lives in Alembic migration 0011 (and is recreated
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
    created = 0
    errors = 0
    skipped = 0

    if total == 0:
        logger.info("Backfill: no records without embeddings found")
        return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    logger.info("Backfill: starting", total_records=total)

    for i, rd in enumerate(record_data, 1):
        try:
            stored = await generate_and_store_embedding(
                session=session,
                record_id=rd["id"],
                title=rd["title"],
                summary=rd["summary"],
                keywords=rd["keywords"],
                lineage=rd["lineage"],
            )
            if stored:
                await session.commit()
                created += 1
            else:
                await session.rollback()
                skipped += 1
        except Exception:
            await session.rollback()
            errors += 1
            logger.warning(
                "Backfill: error processing record",
                record_id=str(rd["id"]),
                exc_info=True,
            )

        # Log progress every 10 records
        if i % 10 == 0:
            logger.info(
                "Backfill progress",
                processed=i,
                total=total,
                created=created,
                errors=errors,
            )

    # The HNSW index is created by Alembic migration 0011 (and by
    # service.rebuild_embedding_column when the dimension is first set or
    # changes). The backfill no longer needs to recreate it.

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
