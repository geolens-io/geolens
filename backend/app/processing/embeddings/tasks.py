"""Procrastinate task for async embedding generation."""

import structlog
from sqlalchemy.orm import joinedload, selectinload

from app.core.db.tenant_session import tenant_task
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)


@task_app.task(queue="ingest", retry=1, aliases=["app.embeddings.tasks.embed_record"])
@tenant_task
async def embed_record(record_id: str) -> None:
    """Generate and store an embedding for a catalog record.

    Loads the record with keywords, builds content text, and calls the
    embedding pipeline. For raster_dataset records, enriches the embedding
    text with raster metadata (bands, dtype, resolution, CRS, compression).
    All errors are caught internally -- this task never raises to the caller.
    """
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.processing.embeddings.service import (
        content_fields,
        generate_and_store_embedding,
        raster_summary_of,
    )
    from sqlalchemy import select

    import uuid

    port = get_processing_port()
    Record = port.get_record_orm_class()

    async with async_session() as session:
        result = await session.execute(
            select(Record)
            .options(
                joinedload(Record.keywords),
                selectinload(Record.translations),
            )
            .where(Record.id == uuid.UUID(record_id))
        )
        record = result.unique().scalar_one_or_none()

        if record is None:
            logger.warning("Record not found for embedding", record_id=record_id)
            return

        fields = content_fields(record)
        raster_summary = await raster_summary_of(session, record)

        await generate_and_store_embedding(
            session=session,
            record_id=record.id,
            raster_summary=raster_summary,
            observed={**fields, "raster_summary": raster_summary},
            **fields,
        )

        await session.commit()
