"""Procrastinate task definitions for VRT creation and regeneration."""

import uuid
from datetime import datetime, timezone

import structlog

from sqlalchemy import select

from app.platform.cache.tiles import invalidate_catalog_cache
from app.core.db import async_session
from app.processing.embeddings.helpers import defer_embedding
from app.processing.raster.cog import extract_raster_metadata, sha256_file
from app.processing.raster.quicklook import generate_quicklook
from app.processing.raster.vrt import build_vrt, resolve_vrt_source_path
from app.platform.storage import get_storage

from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    task_app,
)


async def create_vrt_dataset(
    session,
    *,
    meta: dict,
    asset_sha256: str,
    vrt_size: int,
    source_filename: str | None,
    created_by: uuid.UUID,
    title: str,
    summary: str | None,
    visibility: str,
    vrt_type: str,
    resolution_strategy: str,
    source_dataset_ids: list[uuid.UUID],
    record_status: str = "published",
) -> tuple:
    """Create Record + Dataset + RasterAsset records for a VRT dataset.

    Similar to create_raster_dataset but:
    - record_type="vrt_dataset"
    - source_format=None (avoids chk_datasets_source_format constraint)
    - Sets vrt_type and resolution_strategy on RasterAsset
    - Inserts vrt_source_links rows with position ordering

    Returns (record, dataset, raster_asset).
    """
    from sqlalchemy import func, text

    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()
    Record = port.get_record_orm_class()

    record = Record(
        title=title,
        summary=summary,
        record_type="vrt_dataset",
        visibility=visibility,
        # Mirror the vector ingest path (datasets/service.py
        # `create_dataset_record`) and the raster ingest helper above, which
        # commit directly to `published`.
        # Without this a public VRT stayed in `draft`, and the anonymous
        # raster tile-access check at tiles/router.py `_resolve_raster_access`
        # returned 404 for every public VRT tile request.
        record_status=record_status,
        updated_by=created_by,
    )
    if meta.get("bbox_wkt"):
        record.spatial_extent = func.ST_GeomFromText(meta["bbox_wkt"], 4326)
    session.add(record)
    await session.flush()

    table_name = f"vrt_{record.id.hex[:16]}"
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        source_format=None,  # VRT datasets have no source_format (avoids chk constraint)
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
        size_bytes=vrt_size,
        driver="VRT",
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
        is_rotated=meta.get("is_rotated", False),
        vrt_type=vrt_type,
        resolution_strategy=resolution_strategy,
        status="ready",
    )
    session.add(raster_asset)
    await session.flush()

    # Insert vrt_source_links with position ordering. Single executemany
    # batch (one round trip) instead of N per-row INSERTs (PERF-2).
    if source_dataset_ids:
        await session.execute(
            text(
                "INSERT INTO catalog.vrt_source_links "
                "(vrt_dataset_id, source_dataset_id, position) "
                "VALUES (:vrt_id, :src_id, :pos)"
            ),
            [
                {"vrt_id": str(dataset.id), "src_id": str(src_id), "pos": idx}
                for idx, src_id in enumerate(source_dataset_ids)
            ],
        )

    return record, dataset, raster_asset


@task_app.task(queue="raster", retry=0, aliases=["app.ingest.tasks.ingest_vrt"])
async def ingest_vrt(
    job_id: str,
    user_id: str,
    source_dataset_ids: str,
    vrt_type: str,
    resolution_strategy: str,
    **kwargs,
) -> None:
    """Background task: build a VRT, extract metadata, and register as a catalog dataset.

    Full pipeline:
    1. Update job status to running
    2. Parse source_dataset_ids JSON
    3. Load RasterAsset rows for each source dataset
    4. Resolve asset_uri -> filesystem/S3 paths
    5. Build VRT via gdalbuildvrt (spatial mosaic or band stack)
    6. Extract metadata from assembled VRT via rasterio
    7. Hash VRT file
    8. Generate quicklooks (non-fatal)
    9. Create DB records (Record + Dataset + RasterAsset + vrt_source_links)
    10. Store VRT and quicklooks to managed storage
    11. Update asset URIs and create distribution record
    12. Set job.dataset_id on completion
    13. Invalidate cache, defer embedding

    Session lifecycle (gh #100): the AsyncSession is split into two short-lived
    blocks so it is NOT held open across the long-running CPU work in steps 5-8
    (gdalbuildvrt subprocess, rasterio metadata extraction, sha256, quicklook
    generation — each runs via ``asyncio.to_thread``). See
    ``.planning/debug/worker-missing-greenlet-100.md`` for the full diagnosis.
    """
    _bind_task_log_context(task_name="ingest_vrt", job_id=job_id)
    import asyncio
    import io
    import json as _json
    import os
    import shutil
    import tempfile

    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from app.processing.raster.models import RasterAsset

    _port = get_processing_port()
    Dataset = _port.get_dataset_orm_class()
    RecordDistribution = _port.get_record_distribution_orm_class()

    logger_vrt = __import__("logging").getLogger(__name__)

    job_uuid = uuid.UUID(job_id)
    tmp_dir: str | None = None

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session): load job, mark running, load source
        # asset rows. Snapshot all values needed for phase 2.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            result = await session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
            )
            job = result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job not found, skipping", job_id=job_id
                )
                return

            # 1. Mark running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # 2. Parse source dataset IDs
            ids = [uuid.UUID(sid) for sid in _json.loads(source_dataset_ids)]

            # 3. Load RasterAsset rows for source datasets
            asset_result = await session.execute(
                select(RasterAsset)
                .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                .where(Dataset.id.in_(ids))
            )
            asset_map = {
                asset.dataset_id: asset for asset in asset_result.scalars().all()
            }
            # Preserve insertion order
            ordered_assets = [asset_map[sid] for sid in ids if sid in asset_map]

            # 4. Resolve paths (snapshot to plain strings before closing session)
            source_paths = [
                resolve_vrt_source_path(asset.asset_uri) for asset in ordered_assets
            ]

            # Snapshot job fields needed in phase 2.
            um: dict = job.user_metadata or {}

        # ----------------------------------------------------------------- #
        # CPU work — NO session open. asyncio.to_thread calls run GDAL/numpy
        # in the thread pool.
        # ----------------------------------------------------------------- #

        # 5. Build VRT
        tmp_dir = tempfile.mkdtemp()
        vrt_path = os.path.join(tmp_dir, "source.vrt")
        await asyncio.to_thread(
            build_vrt, vrt_type, source_paths, vrt_path, resolution_strategy
        )

        # 6. Extract metadata from assembled VRT
        meta = await asyncio.to_thread(extract_raster_metadata, vrt_path)
        if not meta.get("crs_wkt"):
            raise ValueError("Assembled VRT has no coordinate reference system.")

        # 7. Hash and size VRT file
        asset_sha256 = await asyncio.to_thread(sha256_file, vrt_path)
        vrt_size = os.path.getsize(vrt_path)

        # 8. Generate quicklooks (non-fatal)
        ql256: bytes | None = None
        ql512: bytes | None = None
        try:
            ql256 = await asyncio.to_thread(generate_quicklook, vrt_path, 256)
            ql512 = await asyncio.to_thread(generate_quicklook, vrt_path, 512)
        except Exception:  # broad: quicklook generation is non-fatal; rasterio rendering can fail for any reason
            logger_vrt.warning(
                "Quicklook generation failed for VRT %s", job_id, exc_info=True
            )

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): create DB records, store assets,
        # commit job.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            result = await session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
            )
            job = result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job vanished between phases, skipping",
                    job_id=job_id,
                )
                return

            try:
                # 9. Create DB records
                title = um.get("title") or f"vrt_{vrt_type}"
                record, dataset, raster_asset = await create_vrt_dataset(
                    session,
                    meta=meta,
                    asset_sha256=asset_sha256,
                    vrt_size=vrt_size,
                    source_filename=None,
                    created_by=uuid.UUID(user_id),
                    title=title,
                    summary=um.get("summary"),
                    visibility=um.get("visibility", "private"),
                    vrt_type=vrt_type,
                    resolution_strategy=resolution_strategy,
                    source_dataset_ids=ids,
                )

                # 10. Store VRT and quicklooks to managed storage
                from app.platform.storage import get_storage

                storage = get_storage()
                base_key = f"rasters/{dataset.id}/{asset_sha256}"
                vrt_key = f"{base_key}/source.vrt"
                ql256_key = f"{base_key}/quicklook_256.png"
                ql512_key = f"{base_key}/quicklook_512.png"

                with open(vrt_path, "rb") as fobj:
                    await storage.put(vrt_key, fobj)

                if ql256 is not None:
                    await storage.put(ql256_key, io.BytesIO(ql256))
                if ql512 is not None:
                    await storage.put(ql512_key, io.BytesIO(ql512))

                # 11. Update asset URIs and create distribution
                raster_asset.asset_uri = vrt_key
                if ql256 is not None:
                    raster_asset.quicklook_256_uri = ql256_key
                if ql512 is not None:
                    raster_asset.quicklook_512_uri = ql512_key
                await session.flush()

                distribution = RecordDistribution(
                    record_id=record.id,
                    distribution_type="download",
                    format="vrt",
                    url=vrt_key,
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

            except Exception:  # broad: re-raised below; rollback first so the
                # outer handler can write a clean failure record via a fresh session.
                await session.rollback()
                raise

    except Exception as exc:  # broad: VRT pipeline includes GDAL subprocesses and rasterio — any step can fail
        structlog.get_logger().exception(
            "Ingest task failed",
            extra={"job_id": job_id, "task": "ingest_vrt"},
        )
        # Write failure status via a fresh session.
        async with async_session() as err_session:
            from sqlalchemy import update as sa_update

            await err_session.execute(
                sa_update(IngestJob)
                .where(IngestJob.id == job_uuid)
                .values(
                    status="failed",
                    error_message=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await err_session.commit()
        raise
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


@task_app.task(queue="raster", retry=0, aliases=["app.ingest.tasks.regenerate_vrt"])
async def regenerate_vrt(
    job_id: str, vrt_dataset_id: str, triggered_by: str = "system", **kwargs
) -> None:
    """Background task: rebuild a VRT file after source add/remove and update metadata.

    Atomic swap: new VRT is built to a temp path, then written to the SAME storage key
    as the existing VRT (asset_uri stays unchanged). Titiler continues serving the old
    file until the overwrite completes.

    Full pipeline:
    1. Mark job running
    2. Load VRT RasterAsset
    3. Load vrt_source_links ordered by position -> source dataset IDs
    4. Load source RasterAsset rows, resolve paths
    5. Build new VRT to temp path
    6. Post-validate via rasterio
    7. Extract metadata from new VRT
    8. Hash and size new VRT
    9. Generate quicklooks (non-fatal)
    10. Overwrite existing storage key (atomic swap)
    11. Update RasterAsset metadata fields
    12. Set status='ready', last_regenerated_at, clear current_generation_id
    13. Update dataset footprint geometry
    14. Mark job complete
    15. Invalidate cache, defer embedding

    Session lifecycle (gh #100): same two-phase split as ``ingest_vrt`` —
    the session is closed before the GDAL subprocess + asyncio.to_thread
    work and reopened for the metadata updates.
    """
    import asyncio

    _bind_task_log_context(
        task_name="regenerate_vrt",
        job_id=job_id,
        vrt_dataset_id=vrt_dataset_id,
    )
    import io
    import os
    import shutil
    import tempfile

    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from sqlalchemy import func, select, text

    Dataset = get_processing_port().get_dataset_orm_class()

    logger_regen = __import__("logging").getLogger(__name__)

    job_uuid = uuid.UUID(job_id)
    vrt_id = uuid.UUID(vrt_dataset_id)
    tmp_dir: str | None = None
    generation_id: uuid.UUID | None = None
    vrt_asset_snapshot = None

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session): load job, mark running, load VRT
        # asset + source links + source assets, create generation record.
        # Snapshot all values needed for phase 2.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            result = await session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
            )
            job = result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job not found, skipping", job_id=job_id
                )
                return

            # 1. Mark running
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            # 2. Load VRT RasterAsset
            asset_result = await session.execute(
                select(RasterAsset)
                .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                .where(Dataset.id == vrt_id)
            )
            vrt_asset_row = asset_result.scalar_one_or_none()
            if vrt_asset_row is None:
                raise ValueError(f"VRT dataset {vrt_dataset_id} not found")
            vrt_asset_snapshot = vrt_asset_row

            # 3. Load vrt_source_links ordered by position
            links_result = await session.execute(
                text(
                    "SELECT source_dataset_id FROM catalog.vrt_source_links "
                    "WHERE vrt_dataset_id = :vrt_id ORDER BY position ASC"
                ),
                {"vrt_id": vrt_id},
            )
            source_ids = [row.source_dataset_id for row in links_result.fetchall()]
            if not source_ids:
                raise ValueError(f"VRT {vrt_dataset_id} has no source links")

            # 3b. Create VrtGeneration record
            generation = VrtGeneration(
                vrt_dataset_id=vrt_id,
                status="running",
                started_at=datetime.now(timezone.utc),
                source_count=len(source_ids),
                triggered_by=triggered_by,
            )
            session.add(generation)
            await session.flush()
            generation_id = generation.id
            vrt_asset_row.current_generation_id = generation.id
            await session.commit()

            # 4. Load source RasterAsset rows and resolve paths
            source_assets_result = await session.execute(
                select(RasterAsset)
                .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                .where(Dataset.id.in_(source_ids))
            )
            asset_map = {a.dataset_id: a for a in source_assets_result.scalars().all()}
            ordered_assets = [asset_map[sid] for sid in source_ids if sid in asset_map]
            source_paths = [
                resolve_vrt_source_path(a.asset_uri) for a in ordered_assets
            ]

            # Snapshot the VRT asset's invariant config for phase 2
            # (the existing storage key + quicklook keys + VRT type/strategy).
            vrt_storage_key: str = vrt_asset_row.asset_uri  # unchanged across regen
            vrt_ql256_uri: str | None = vrt_asset_row.quicklook_256_uri
            vrt_ql512_uri: str | None = vrt_asset_row.quicklook_512_uri
            vrt_type: str = vrt_asset_row.vrt_type or "mosaic"
            resolution_strategy: str = vrt_asset_row.resolution_strategy or "finest"

        # ----------------------------------------------------------------- #
        # CPU work — NO session open.
        # ----------------------------------------------------------------- #

        # 5. Build VRT to temp path
        tmp_dir = tempfile.mkdtemp()
        vrt_path = os.path.join(tmp_dir, "source.vrt")

        await asyncio.to_thread(
            build_vrt, vrt_type, source_paths, vrt_path, resolution_strategy
        )

        # 6 & 7. Extract metadata (also serves as post-validation)
        meta = await asyncio.to_thread(extract_raster_metadata, vrt_path)
        if not meta.get("crs_wkt"):
            raise ValueError("Regenerated VRT has no coordinate reference system.")

        # 8. Hash and size
        new_sha256 = await asyncio.to_thread(sha256_file, vrt_path)
        new_size = os.path.getsize(vrt_path)

        # 9. Generate quicklooks (non-fatal)
        ql256: bytes | None = None
        ql512: bytes | None = None
        try:
            ql256 = await asyncio.to_thread(generate_quicklook, vrt_path, 256)
            ql512 = await asyncio.to_thread(generate_quicklook, vrt_path, 512)
        except Exception:  # broad: quicklook generation is non-fatal; rasterio rendering can fail for any reason
            logger_regen.warning(
                "Quicklook regeneration failed for VRT %s",
                vrt_dataset_id,
                exc_info=True,
            )

        # 10. Overwrite existing storage key (atomic swap -- same URI, new content)
        storage = get_storage()

        with open(vrt_path, "rb") as fobj:
            await storage.put(vrt_storage_key, fobj)

        if ql256 is not None and vrt_ql256_uri:
            await storage.put(vrt_ql256_uri, io.BytesIO(ql256))
        if ql512 is not None and vrt_ql512_uri:
            await storage.put(vrt_ql512_uri, io.BytesIO(ql512))

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): update RasterAsset metadata, mark
        # job complete, update dataset footprint.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            result = await session.execute(
                select(IngestJob).where(IngestJob.id == job_uuid)
            )
            job = result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job vanished between phases, skipping",
                    job_id=job_id,
                )
                return

            try:
                # Re-load VRT asset in the new session.
                asset_result = await session.execute(
                    select(RasterAsset)
                    .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                    .where(Dataset.id == vrt_id)
                )
                vrt_asset = asset_result.scalar_one_or_none()
                if vrt_asset is None:
                    raise ValueError(
                        f"VRT dataset {vrt_dataset_id} disappeared between phases"
                    )

                # Re-load generation record.
                gen_result = await session.execute(
                    select(VrtGeneration).where(VrtGeneration.id == generation_id)
                )
                generation = gen_result.scalar_one_or_none()
                if generation is None:
                    raise ValueError(
                        f"VrtGeneration {generation_id} disappeared between phases"
                    )

                # 11. Update RasterAsset metadata fields
                nodata_val = meta.get("nodata")
                vrt_asset.sha256 = new_sha256
                vrt_asset.size_bytes = new_size
                vrt_asset.crs_wkt = meta.get("crs_wkt")
                vrt_asset.epsg = meta.get("epsg")
                vrt_asset.band_count = meta.get("band_count")
                vrt_asset.dtype = meta.get("dtype")
                vrt_asset.nodata = str(nodata_val) if nodata_val is not None else None
                vrt_asset.res_x = meta.get("res_x")
                vrt_asset.res_y = meta.get("res_y")
                vrt_asset.width = meta.get("width")
                vrt_asset.height = meta.get("height")
                vrt_asset.compression = meta.get("compression")

                # 12. Status transitions
                vrt_asset.status = "ready"
                vrt_asset.last_regenerated_at = datetime.now(timezone.utc)
                vrt_asset.current_generation_id = None
                if vrt_asset_snapshot is not None:
                    vrt_asset_snapshot.status = vrt_asset.status
                    vrt_asset_snapshot.last_regenerated_at = (
                        vrt_asset.last_regenerated_at
                    )
                    vrt_asset_snapshot.current_generation_id = None

                # 12b. Update generation record
                generation.status = "completed"
                generation.completed_at = datetime.now(timezone.utc)
                # `started_at` is set at record creation in phase 1 — guarded
                # here so mypy/runtime don't crash if a future refactor drops it.
                if generation.started_at is not None:
                    generation.duration_seconds = (
                        generation.completed_at - generation.started_at
                    ).total_seconds()

                # 13. Update dataset footprint geometry
                dataset_result = await session.execute(
                    select(Dataset).where(Dataset.id == vrt_id)
                )
                vrt_dataset = dataset_result.scalar_one_or_none()
                if vrt_dataset is not None and meta.get("bbox_wkt"):
                    vrt_dataset.record.spatial_extent = func.ST_GeomFromText(
                        meta["bbox_wkt"], 4326
                    )

                # 14. Finalize job
                job.status = "complete"
                job.dataset_id = vrt_id
                job.completed_at = datetime.now(timezone.utc)
                await session.commit()

                # 15. Invalidate cache and defer embedding
                await invalidate_catalog_cache()
                if vrt_dataset is not None:
                    await defer_embedding(vrt_dataset)

            except Exception:  # broad: re-raised below; rollback first so the
                # outer handler can write a clean failure record via a fresh session.
                await session.rollback()
                raise

    except Exception as exc:  # broad: VRT regeneration includes GDAL subprocesses and rasterio — any step can fail
        structlog.get_logger().exception(
            "Ingest task failed",
            job_id=job_id,
            task="regenerate_vrt",
        )
        if vrt_asset_snapshot is not None:
            vrt_asset_snapshot.status = "failed"
            vrt_asset_snapshot.current_generation_id = None
        # Failure handler runs via a fresh session: mark vrt asset failed,
        # mark generation failed, mark job failed.
        async with async_session() as err_session:
            from sqlalchemy import update as sa_update

            # Mark VRT asset failed and clear the generation pointer.
            await err_session.execute(
                sa_update(RasterAsset)
                .where(RasterAsset.dataset_id == vrt_id)
                .values(status="failed", current_generation_id=None)
            )

            # Update generation record on failure.
            if generation_id is not None:
                gen_result = await err_session.execute(
                    select(VrtGeneration).where(VrtGeneration.id == generation_id)
                )
                gen = gen_result.scalar_one_or_none()
                if gen:
                    gen.status = "failed"
                    gen.completed_at = datetime.now(timezone.utc)
                    if gen.started_at:
                        gen.duration_seconds = (
                            gen.completed_at - gen.started_at
                        ).total_seconds()
                    gen.error_message = str(exc)

            await err_session.execute(
                sa_update(IngestJob)
                .where(IngestJob.id == job_uuid)
                .values(
                    status="failed",
                    error_message=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await err_session.commit()
        raise
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
