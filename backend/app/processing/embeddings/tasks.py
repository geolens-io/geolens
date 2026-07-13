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
    from app.processing.embeddings.service import generate_and_store_embedding
    from app.processing.raster.models import RasterAsset
    from sqlalchemy import select

    import uuid

    port = get_processing_port()
    Record = port.get_record_orm_class()
    Dataset = port.get_dataset_orm_class()

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

        keyword_list = (
            [kw.keyword for kw in record.keywords] if record.keywords else None
        )

        # Build raster summary for raster_dataset records
        raster_summary: str | None = None
        if record.record_type == "raster_dataset":
            ds_result = await session.execute(
                select(Dataset).where(Dataset.record_id == record.id)
            )
            dataset = ds_result.scalar_one_or_none()
            if dataset is not None:
                ra_result = await session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
                )
                ra = ra_result.scalar_one_or_none()
                if ra is not None:
                    size_str = (
                        f"{ra.size_bytes / (1024 * 1024):.1f}MB"
                        if ra.size_bytes
                        else "unknown size"
                    )
                    # fix(#430 BA-11): res_x may be NULL; formatting None with :.6f raised
                    # TypeError and left the raster with no embedding.
                    res_str = (
                        f"{ra.res_x:.6f} resolution, " if ra.res_x is not None else ""
                    )
                    raster_summary = (
                        f"GeoTIFF, {ra.band_count} band(s), {ra.dtype}, "
                        f"{res_str}EPSG:{ra.epsg}, "
                        f"{ra.compression} compression, {size_str}"
                    )

        await generate_and_store_embedding(
            session=session,
            record_id=record.id,
            title=record.title,
            summary=record.summary,
            keywords=keyword_list,
            lineage=record.lineage_summary,
            raster_summary=raster_summary,
            localized_texts=[
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
        )

        await session.commit()
