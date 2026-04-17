"""Procrastinate task definitions for raster/COG file ingestion."""

import uuid
from datetime import datetime, timezone

import structlog

from sqlalchemy import select

from app.platform.cache.tiles import invalidate_catalog_cache
from app.core.db import async_session
from app.processing.raster.cog import check_and_prepare_cog, extract_raster_metadata, sha256_file
from app.processing.raster.quicklook import generate_quicklook
from app.platform.storage import get_storage

from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _parse_temporal_fields,
    _validate_upload_file_safety,
    task_app,
)


async def create_raster_dataset(
    session,
    *,
    meta: dict,
    source_sha256: str,
    asset_sha256: str,
    cog_status: str,
    cog_size: int,
    source_filename: str | None,
    created_by: uuid.UUID,
    title: str,
    summary: str | None,
    visibility: str,
) -> tuple:
    """Create Record + Dataset + RasterAsset records for a raster ingest.

    Returns (record, dataset, raster_asset).
    """
    from sqlalchemy import func

    from app.modules.catalog.datasets.domain.models import Dataset, Record
    from app.processing.raster.models import RasterAsset

    # Mirror the vector ingest path (datasets/service.py
    # `create_dataset_record`) which commits directly to `published`.
    # Without this the raster stayed in `draft` and the anonymous public
    # tile-access check at tiles/router.py `_resolve_raster_access`
    # returned 404 for every raster tile fetch, so every public demo map
    # containing a raster layer (Earth as Seen from Space, Global
    # Bathymetry, …) was broken for anonymous users.
    record = Record(
        title=title,
        summary=summary,
        record_type="raster_dataset",
        visibility=visibility,
        record_status="published",
        updated_by=created_by,
    )
    if meta.get("bbox_wkt"):
        record.spatial_extent = func.ST_GeomFromText(meta["bbox_wkt"], 4326)
    session.add(record)
    await session.flush()

    table_name = f"raster_{record.id.hex[:16]}"
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format="geotiff",
        source_filename=source_filename,
        srid=meta.get("epsg"),
    )
    session.add(dataset)
    await session.flush()

    nodata_val = meta.get("nodata")
    nodata_str = str(nodata_val) if nodata_val is not None else None

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri="",  # updated after storage put
        sha256=asset_sha256,
        size_bytes=cog_size,
        driver=meta.get("driver"),
        storage_backend="local",
        ingested_at=datetime.now(timezone.utc),
        crs_wkt=meta.get("crs_wkt"),
        epsg=meta.get("epsg"),
        band_count=meta.get("band_count"),
        dtype=meta.get("dtype"),
        nodata=nodata_str,
        res_x=meta.get("res_x"),
        res_y=meta.get("res_y"),
        width=meta.get("width"),
        height=meta.get("height"),
        compression=meta.get("compression"),
        source_sha256=source_sha256,
        cog_status=cog_status,
        band_info=meta.get("band_info"),
        is_rotated=meta.get("is_rotated", False),
        is_dem=meta.get("is_dem_candidate", False),
    )
    session.add(raster_asset)
    await session.flush()

    return record, dataset, raster_asset


@task_app.task(queue="raster", retry=2, aliases=["app.ingest.tasks.ingest_raster"])
async def ingest_raster(job_id: str, file_path: str, user_id: str, **kwargs) -> None:
    """Background task: validate GeoTIFF, convert to COG, extract metadata, register dataset.

    Full pipeline:
    1. Update job status to running
    2. Resolve file path
    3. Validate file content and size
    4. Hash source file (source_sha256)
    5. Extract raster metadata
    6. Check/convert to COG profile
    7. Hash COG file (asset_sha256)
    8. Generate quicklooks (256, 512)
    9. Create Dataset + RasterAsset + Record in DB
    10. Store COG and quicklooks to managed storage
    11. Update asset URIs and create distribution record
    12. Update job to complete
    13. Invalidate cache, defer embedding
    """
    _bind_task_log_context(task_name="ingest_raster", job_id=job_id)
    import asyncio
    import io
    import os
    import shutil
    import tempfile
    from pathlib import Path as _Path

    # Register all FK target models so SQLAlchemy can resolve FKs on IngestJob
    from app.modules.auth.models import User  # noqa: F401
    from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401

    from app.platform.jobs.models import IngestJob

    async with async_session() as session:
        result = await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(job_id))
        )
        job = result.scalar_one()

        local_cog_path: str | None = None
        tmp_dir: str | None = None
        original_file_path = file_path

        try:
            # 1. Mark running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # 2. Resolve file path
            from app.processing.ingest.service import resolve_file_path

            file_path = await resolve_file_path(file_path, job_id)

            # 3. Validate file content and size (KISS-6). Raster uploads
            # are .tif/.tiff/.vrt so the .zip branch of the helper is a no-op.
            try:
                await _validate_upload_file_safety(
                    session,
                    file_path=file_path,
                    source_filename=job.source_filename,
                )
            except ValueError as exc:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.now(timezone.utc)
                await session.commit()
                _Path(file_path).unlink(missing_ok=True)
                return

            # 4. Hash source file
            source_sha256 = await asyncio.to_thread(sha256_file, file_path)

            # 5. Extract metadata
            meta = await asyncio.to_thread(extract_raster_metadata, file_path)

            # Read GDAL options from user_metadata (set at commit time)
            um = job.user_metadata or {}
            assign_crs = um.get("srid_override")
            user_compression = um.get("compression") or "DEFLATE"
            user_resampling = um.get("resampling") or None
            user_nodata = um.get("nodata_override")
            crs_missing = um.get("crs_missing", False)

            if not meta.get("crs_wkt") and not assign_crs:
                if crs_missing:
                    raise ValueError(
                        "Missing CRS: raster has no coordinate reference system. "
                        "Provide a CRS override (EPSG code) at import time."
                    )
                raise ValueError(
                    "Missing CRS: raster has no coordinate reference system."
                )

            # 6. Check/convert to COG
            tmp_dir = tempfile.mkdtemp()
            local_cog_path, cog_status = await asyncio.to_thread(
                check_and_prepare_cog,
                file_path,
                tmp_dir,
                compression=user_compression,
                resampling=user_resampling,
                nodata=user_nodata,
                assign_crs=assign_crs if assign_crs and crs_missing else None,
            )
            assert (
                local_cog_path is not None
            )  # check_and_prepare_cog always returns a path

            # 7. Hash COG
            asset_sha256 = await asyncio.to_thread(sha256_file, local_cog_path)
            cog_size = os.path.getsize(local_cog_path)

            # 8. Generate quicklooks
            ql256 = await asyncio.to_thread(generate_quicklook, local_cog_path, 256)
            ql512 = await asyncio.to_thread(generate_quicklook, local_cog_path, 512)

            # 9. Create DB records
            um = job.user_metadata or {}
            title = um.get("title") or job.source_filename or "raster_dataset"
            record, dataset, raster_asset = await create_raster_dataset(
                session,
                meta=meta,
                source_sha256=source_sha256,
                asset_sha256=asset_sha256,
                cog_status=cog_status,
                cog_size=cog_size,
                source_filename=job.source_filename,
                created_by=uuid.UUID(user_id),
                title=title,
                summary=um.get("summary"),
                visibility=um.get("visibility", "private"),
            )

            # 9b. Set temporal fields on Record (N5 extraction to _parse_temporal_fields).
            parsed_start, parsed_end, temporal_errors = _parse_temporal_fields(
                temporal_start=um.get("temporal_start") or meta.get("temporal_start"),
                temporal_end=um.get("temporal_end"),
            )
            if parsed_start is not None:
                record.temporal_start = parsed_start
            if parsed_end is not None:
                record.temporal_end = parsed_end
            if temporal_errors:
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "temporal_parse_errors": temporal_errors,
                }
            await session.flush()

            # 10. Store COG and quicklooks to managed storage
            from app.platform.storage import get_storage

            storage = get_storage()
            base_key = f"rasters/{dataset.id}/{asset_sha256}"
            cog_key = f"{base_key}/source.cog.tif"
            ql256_key = f"{base_key}/quicklook_256.png"
            ql512_key = f"{base_key}/quicklook_512.png"

            with open(local_cog_path, "rb") as fobj:
                await storage.put(cog_key, fobj)
            await storage.put(ql256_key, io.BytesIO(ql256))
            await storage.put(ql512_key, io.BytesIO(ql512))

            # 11. Update asset URIs and create distribution
            raster_asset.asset_uri = cog_key
            raster_asset.quicklook_256_uri = ql256_key
            raster_asset.quicklook_512_uri = ql512_key
            await session.flush()

            from app.modules.catalog.datasets.domain.models import RecordDistribution

            distribution = RecordDistribution(
                record_id=record.id,
                distribution_type="download",
                format="geotiff",
                url=cog_key,
            )
            session.add(distribution)

            # 12. Finalize job
            job.status = "complete"
            job.dataset_id = dataset.id
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

            # Invalidate cache
            await invalidate_catalog_cache()

            # 13. Generate embedding (non-fatal)
            from app.processing.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

        except Exception as exc:
            await session.rollback()
            job.status = "failed"
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            structlog.get_logger().exception(
                "Ingest task failed",
                job_id=str(job.id),
                task="ingest_raster",
            )
            await session.commit()
            raise
        finally:
            # Clean up temp COG dir
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            # Clean up local staging file
            if job.status == "complete":
                _Path(file_path).unlink(missing_ok=True)
            elif file_path != original_file_path:
                _Path(file_path).unlink(missing_ok=True)
