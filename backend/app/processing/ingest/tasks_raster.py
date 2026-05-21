"""Procrastinate task definitions for raster/COG file ingestion."""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.platform.cache.tiles import invalidate_catalog_cache
from app.processing.raster.cog import (
    check_and_prepare_cog,
    check_cog_compliance,
    extract_raster_metadata,
    sha256_file,
)
from app.processing.raster.quicklook import generate_quicklook

from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _job_phase_session,
    _parse_temporal_fields,
    _validate_upload_file_safety,
    task_app,
)


def _is_manifest_vrt_job(job: Any) -> bool:
    """Return true when a raster queue job represents a manifest VRT source."""
    metadata = job.user_metadata or {}
    source_filename = (job.source_filename or "").lower()
    return metadata.get("manifest_source_type") == "vrt" or source_filename.endswith(
        ".vrt"
    )


async def _enforce_strict_cog(
    file_path: str,
    *,
    expected_compression: str | None,
    is_manifest_vrt: bool,
    strict_cog: bool,
) -> None:
    """Strict-mode COG gate for ING-07 / P2-09.

    When the user opted in via ``RasterCommitRequest.strict_cog=True``,
    reject non-COG TIFFs here instead of silently routing through
    ``check_and_prepare_cog`` conversion.

    Manifest-VRT jobs are excluded (VRTs are XML, not TIFFs — the COG
    compliance check would fail for unrelated reasons).

    On non-compliance, raises ``ValueError`` whose message contains the
    compliance reason. The existing ``ingest_raster`` outer
    ``except Exception`` handler writes the failure to the job via
    ``_job_phase_session("error_write")``.
    """
    import asyncio

    if not strict_cog or is_manifest_vrt:
        return

    compliant, reason = await asyncio.to_thread(
        check_cog_compliance, file_path, expected_compression=expected_compression
    )
    if not compliant:
        raise ValueError(
            f"Strict-COG mode rejected upload: {reason}. "
            "Disable strict_cog or upload a COG-compliant TIFF."
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
    record_status: str = "published",
) -> tuple:
    """Create Record + Dataset + RasterAsset records for a raster ingest.

    Returns (record, dataset, raster_asset).
    """
    from sqlalchemy import func

    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset

    _port = get_processing_port()
    Dataset = _port.get_dataset_orm_class()
    Record = _port.get_record_orm_class()

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
        record_status=record_status,
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


@task_app.task(queue="raster", retry=0, aliases=["app.ingest.tasks.ingest_raster"])
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

    Session lifecycle (gh #100): the AsyncSession is split into two short-lived
    blocks so it is NOT held open across the long-running CPU work in steps 4-8
    (sha256, GDAL metadata extraction, COG conversion, quicklook generation —
    each runs via ``asyncio.to_thread``). Holding a session open across those
    ``to_thread`` calls in Python 3.14 + SQLAlchemy 2.0 + greenlet 3.3 corrupts
    the greenlet bridge state and the next ``session.flush()`` raises
    ``MissingGreenlet``. See ``.planning/debug/worker-missing-greenlet-100.md``
    for the full diagnosis.
    """
    _bind_task_log_context(task_name="ingest_raster", job_id=job_id)
    import asyncio
    import io
    import os
    import shutil
    import tempfile
    from pathlib import Path as _Path

    from app.platform.jobs.models import IngestJob

    job_uuid = uuid.UUID(job_id)
    local_cog_path: str | None = None
    tmp_dir: str | None = None
    original_file_path = file_path
    final_status: str = "pending"

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session via _job_phase_session — REMED-03 /
        # P2-05): load job, mark running, validate. Snapshot the values
        # needed for CPU work into local variables so phase 2 can re-load
        # the job in a fresh session without depending on attached ORM
        # state surviving the asyncio.to_thread calls.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(job_uuid, phase="phase1") as (session, job):
            if job is None:
                return

            # 1. Mark running.
            # REMED-02 / ingest-audit P2-07: stamp current_step + progress so
            # the polling UI sees a fresh "validating" signal on the first
            # poll after pickup. Raster ingests are the prime motivator —
            # 10-min COG conversion + quicklook generation otherwise looks
            # like a dead spinner.
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.current_step = "validating"
            job.progress = 0.0
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
                final_status = "failed"
                return

            # Snapshot job attributes needed in phase 2 (after CPU work).
            # These plain Python values do not require an attached ORM session.
            um: dict = job.user_metadata or {}
            source_filename: str | None = job.source_filename
            is_manifest_vrt = _is_manifest_vrt_job(job)

        # ----------------------------------------------------------------- #
        # CPU work — NO session open. asyncio.to_thread calls run GDAL/numpy
        # in the thread pool. Holding a session open here is what triggers
        # the MissingGreenlet bug (gh #100).
        # ----------------------------------------------------------------- #

        # 4. Hash source file
        source_sha256 = await asyncio.to_thread(sha256_file, file_path)

        # 5. Extract metadata
        meta = await asyncio.to_thread(extract_raster_metadata, file_path)

        # Read GDAL options from user_metadata (set at commit time)
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
            raise ValueError("Missing CRS: raster has no coordinate reference system.")

        # ING-07 / P2-09: strict-mode COG gating. When the user opted in via
        # RasterCommitRequest.strict_cog=True, reject non-COG TIFFs here
        # instead of silently routing through check_and_prepare_cog
        # conversion. Manifest-VRT jobs are excluded (VRTs are XML, not
        # TIFFs — the COG compliance check would fail for unrelated reasons).
        await _enforce_strict_cog(
            file_path,
            expected_compression=user_compression,
            is_manifest_vrt=is_manifest_vrt,
            strict_cog=bool(um.get("strict_cog")),
        )

        # REMED-02 / ingest-audit P2-07: stamp current_step="cog_convert"
        # before the branch so both paths exit with the same progress
        # checkpoint. Manifest-VRT skips the actual COG work but the UI
        # signal must still advance — keeps the step name consistent.
        # Brief-session pattern via _job_phase_session (REMED-03) — no
        # session held open across the asyncio.to_thread CPU work below.
        async with _job_phase_session(
            job_uuid, phase="progress_write_cog_convert"
        ) as (_progress_session, _progress_job):
            if _progress_job is not None:
                _progress_job.current_step = "cog_convert"
                _progress_job.progress = 0.2
                await _progress_session.commit()

        if is_manifest_vrt:
            local_cog_path = file_path
            cog_status = "verified"
        else:
            # 6. Check/convert to COG. Verify disk space first — COG conversion
            # can produce output up to ~3× source size (decompressed + tiled +
            # overviews); a stretched disk crashes here with opaque IOError and
            # may leave concurrent ingests in a half-converted state.
            tmp_dir = tempfile.mkdtemp()
            source_bytes = os.path.getsize(file_path)
            free_bytes = shutil.disk_usage(tmp_dir).free
            min_free = source_bytes * 3
            if free_bytes < min_free:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise ValueError(
                    f"Insufficient disk space for COG conversion: need ~{min_free // (1024 * 1024)} MB, "
                    f"have {free_bytes // (1024 * 1024)} MB free at staging directory."
                )
            local_cog_path, cog_status = await asyncio.to_thread(
                check_and_prepare_cog,
                file_path,
                tmp_dir,
                compression=user_compression,
                resampling=user_resampling,
                nodata=user_nodata,
                assign_crs=assign_crs if assign_crs and crs_missing else None,
            )
        assert local_cog_path is not None  # check_and_prepare_cog always returns a path

        # 7. Hash COG
        asset_sha256 = await asyncio.to_thread(sha256_file, local_cog_path)
        cog_size = os.path.getsize(local_cog_path)

        # REMED-02 / ingest-audit P2-07: quicklook generation is the other
        # multi-second hotspot. Brief-session write before the two
        # generate_quicklook calls so the UI advances. Routed through
        # _job_phase_session per REMED-03.
        async with _job_phase_session(
            job_uuid, phase="progress_write_quicklook"
        ) as (_progress_session, _progress_job):
            if _progress_job is not None:
                _progress_job.current_step = "quicklook"
                _progress_job.progress = 0.6
                await _progress_session.commit()

        # 8. Generate quicklooks
        ql256 = await asyncio.to_thread(generate_quicklook, local_cog_path, 256)
        ql512 = await asyncio.to_thread(generate_quicklook, local_cog_path, 512)

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session via _job_phase_session — REMED-03 /
        # P2-05): create DB records, store assets, commit job. Re-load the
        # job in a fresh session — its attributes were already snapshotted
        # into ``um`` / ``source_filename`` above.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(job_uuid, phase="phase2") as (session, job):
            if job is None:
                return

            # REMED-02 / ingest-audit P2-07: phase-2 progress signal.
            # Uncommitted — participates in the existing rollback shape
            # so a phase-2 failure cleans up the progress write too.
            # The brief-session "quicklook" write above is the durable
            # mid-flight checkpoint.
            # REMED-03 / P2-05: _job_phase_session owns the rollback-on-
            # exception shape that used to live as a manual try/except.
            job.current_step = "finalize"
            job.progress = 0.8

            # 9. Create DB records
            title = um.get("title") or source_filename or "raster_dataset"
            if is_manifest_vrt:
                from app.processing.ingest.tasks_vrt import create_vrt_dataset

                record, dataset, raster_asset = await create_vrt_dataset(
                    session,
                    meta=meta,
                    asset_sha256=asset_sha256,
                    vrt_size=cog_size,
                    source_filename=source_filename,
                    created_by=uuid.UUID(user_id),
                    title=title,
                    summary=um.get("summary"),
                    visibility=um.get("visibility", "private"),
                    record_status=um.get("record_status", "published"),
                    vrt_type=um.get("vrt_type", "mosaic"),
                    resolution_strategy=um.get("resolution_strategy", "finest"),
                    source_dataset_ids=[],
                )
            else:
                record, dataset, raster_asset = await create_raster_dataset(
                    session,
                    meta=meta,
                    source_sha256=source_sha256,
                    asset_sha256=asset_sha256,
                    cog_status=cog_status,
                    cog_size=cog_size,
                    source_filename=source_filename,
                    created_by=uuid.UUID(user_id),
                    title=title,
                    summary=um.get("summary"),
                    visibility=um.get("visibility", "private"),
                    record_status=um.get("record_status", "published"),
                )

            # 9b. Set temporal fields on Record (N5 extraction to _parse_temporal_fields).
            parsed_start, parsed_end, temporal_errors = _parse_temporal_fields(
                temporal_start=um.get("temporal_start")
                or meta.get("temporal_start"),
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
            cog_key = (
                f"{base_key}/source.vrt"
                if is_manifest_vrt
                else f"{base_key}/source.cog.tif"
            )
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

            from app.platform.extensions import get_processing_port as _get_port

            RecordDistribution = _get_port().get_record_distribution_orm_class()

            distribution = RecordDistribution(
                record_id=record.id,
                distribution_type="download",
                format="vrt" if is_manifest_vrt else "geotiff",
                url=cog_key,
            )
            session.add(distribution)

            # 12. Finalize job.
            # REMED-02 / ingest-audit P2-07: stamp terminal progress
            # alongside status. ``rows_processed`` stays NULL — raster
            # ingests have no rows (the COG and quicklooks ARE the
            # asset). Vector ingests set rows_processed in
            # tasks_common._finalize_ingest from metadata["feature_count"].
            job.status = "complete"
            job.dataset_id = dataset.id
            job.completed_at = datetime.now(timezone.utc)
            job.current_step = "complete"
            job.progress = 1.0
            await session.commit()
            final_status = "complete"

            # Invalidate cache
            await invalidate_catalog_cache()

            # 13. Generate embedding (non-fatal)
            from app.processing.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

    except Exception as exc:  # broad: raster ingest spans GDAL/COG/Titiler — any step can fail; record failure
        structlog.get_logger().exception(
            "Ingest task failed",
            job_id=job_id,
            task="ingest_raster",
        )
        # Write failure status via a fresh session — phase 1/2 sessions are
        # already closed (or rolled back) by the time we get here.
        # REMED-03 / P2-05: route through _job_phase_session.
        async with _job_phase_session(job_uuid, phase="error_write") as (
            err_session,
            _err_job,
        ):
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
        final_status = "failed"
        raise
    finally:
        # Clean up temp COG dir
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        # Clean up local staging file
        if final_status == "complete":
            _Path(file_path).unlink(missing_ok=True)
        elif file_path != original_file_path:
            _Path(file_path).unlink(missing_ok=True)
