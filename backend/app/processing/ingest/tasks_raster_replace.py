"""Procrastinate task: replace the COG behind an existing raster dataset.

feat(#1221). Before this, a raster dataset could only be "refreshed" by
deleting it and importing again, which threw away the dataset id and with it
the metadata, the grants, and every map layer pointing at it. This task is the
raster peer of ``tasks_reupload.reupload_file``: same door, same admission
gate, same refresh-run bookkeeping — a different swap, because a raster
dataset has no staging table to rename. What it swaps is the ``RasterAsset``
pointer.

**Invariant 10, last-known-good is sacred.** The previous COG is not deleted or
overwritten until the replacement has been written to storage AND read back
successfully. The new asset lands under keys derived from its own content hash,
so it cannot collide with the live asset's; the pointer moves in a single
transaction alongside the tile-cache bump; and only after that transaction
commits are the superseded objects reaped. Every failure before the commit
leaves the old COG serving tiles, which is what the dataset's map layers keep
rendering.

**ADR-002 Decision 7** governs the *incoming* file rather than the outgoing
asset: the pre-conversion upload is deleted once conversion succeeds, and
retained (bounded by the retention purge) when it fails, because a failed
conversion makes those bytes the operator's only diagnostic copy. The tail
below states which is which; ``RUNBOOK.md`` section 9 states it for operators.
"""

import asyncio
import io
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import func, select, text

from app.core.db.tenant_session import tenant_task
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.dataset_origin import set_dataset_origin
from app.platform.jobs.heartbeat import (
    claim_job_attempt_and_start_heartbeat,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.platform.jobs.models import owned_presigned_staging_key
from app.platform.refresh.service import (
    claim_run_for_job,
    record_refresh_failure,
    record_refresh_success,
)
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.raster.cog import (
    _scratch_dir,
    check_and_prepare_cog,
    extract_raster_metadata,
    sha256_file,
)
from app.processing.raster.quicklook import generate_quicklook

from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _job_phase_session,
    _validate_upload_file_safety,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
    task_app,
)
from app.processing.ingest.tasks_raster import (
    _cleanup_orphaned_storage_keys,
    _enforce_strict_cog,
    _resolve_managed_raster_storage_keys,
)

logger = structlog.get_logger(__name__)


class RasterReplaceError(Exception):
    """A raster replace that failed for a reason the user can act on."""


async def _verify_cog_readable(cog_path: str) -> None:
    """Read the freshly written COG back before anything points at it.

    This is the "verified readable" half of invariant 10. Conversion reporting
    success is not the same fact as the output being openable: a truncated
    write, an out-of-space overview pass, or a driver quirk all produce a file
    on disk that ``gdal_translate`` exited 0 for. Since the very next steps
    discard the last-known-good asset, the check has to be explicit here rather
    than left as a side effect of quicklook generation, which is a step someone
    could reasonably make non-fatal later.

    Goes through ``extract_raster_metadata`` — one rasterio open pass, already
    the reader every other raster path uses, so this adds no new GDAL seam for
    Rule 2 to police.
    """
    try:
        await asyncio.to_thread(extract_raster_metadata, cog_path)
    except Exception as exc:  # broad: any read failure means do not publish
        raise RasterReplaceError(
            f"Converted COG could not be read back: {exc}. "
            "The dataset still serves its previous raster."
        ) from exc


async def _stamp_progress(
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    phase: str,
    step: str,
    progress: float,
) -> None:
    """Advance the job's mid-flight progress in its own brief session.

    REMED-02 / REMED-03: COG conversion and quicklook generation are the two
    multi-minute steps, and without a checkpoint between them the UI shows a
    dead spinner. The session is opened and closed around the write only — the
    GDAL work either side of it must never see a live session (gh #100).
    """
    async with _job_phase_session(job_uuid, phase=phase, attempt_id=attempt_uuid) as (
        session,
        job,
    ):
        if job is None:
            return
        job.current_step = step
        job.progress = progress
        await session.commit()


async def _convert_and_verify_cog(
    file_path: str,
    tmp_dir: str,
    *,
    compression: str,
    resampling: str | None,
    nodata: object,
    assign_crs: int | None,
) -> tuple[str, str]:
    """Convert to COG and read the result back. Returns (path, cog_status).

    The disk-space precheck is here rather than at the call site because it
    guards this conversion specifically: COG output can reach ~3x the source
    (decompressed, tiled, plus overviews), and a stretched volume otherwise
    fails inside GDAL with an opaque IOError.

    fix(#448): the scratch directory must already live on the staging volume,
    not the container's RAM-backed /tmp, or this measures the wrong filesystem.
    """
    source_bytes = os.path.getsize(file_path)
    free_bytes = shutil.disk_usage(tmp_dir).free
    min_free = source_bytes * 3
    if free_bytes < min_free:
        raise RasterReplaceError(
            f"Insufficient disk space for COG conversion: need "
            f"~{min_free // (1024 * 1024)} MB, have "
            f"{free_bytes // (1024 * 1024)} MB free at the staging directory."
        )
    local_cog_path, cog_status = await asyncio.to_thread(
        check_and_prepare_cog,
        file_path,
        tmp_dir,
        compression=compression,
        resampling=resampling,
        nodata=nodata,
        assign_crs=assign_crs,
    )
    # Invariant 10's gate. Everything before this line is reversible;
    # everything after it starts moving pointers.
    await _verify_cog_readable(local_cog_path)
    return local_cog_path, cog_status


def _prior_asset_keys_to_reap(
    *,
    asset_uri: str | None,
    quicklook_256_uri: str | None,
    quicklook_512_uri: str | None,
) -> list[str]:
    """Resolve the superseded objects, in the same physical form as the puts.

    Mirrors ``tasks_vrt._prior_generation_storage_keys_to_reap``: catalog rows
    hold logical keys and storage holds tenant-prefixed ones, so the two lists
    the caller compares must both be physical or a same-key replace would reap
    the object it just wrote.
    """
    return [
        resolve_current_storage_key(key)
        for key in (asset_uri, quicklook_256_uri, quicklook_512_uri)
        if key
    ]


# No legacy alias: the sibling tasks carry `app.ingest.tasks.*` aliases because
# the package moved, and this task has never lived under the old path.
@task_app.task(queue="raster", retry=0)
@tenant_task
async def reupload_raster(
    job_id: str,
    dataset_id: str,
    file_path: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: replace an existing raster dataset's COG in place.

    Pipeline:
    1. Claim the job attempt and its refresh run; validate the uploaded file
    2. Hash the source, read its metadata, convert to COG
    3. Read the COG back (invariant 10 — nothing is discarded before this)
    4. Generate quicklooks
    5. Write the new objects under content-hash keys (the live ones are not
       touched: a different COG hashes to a different prefix)
    6. One transaction: swap ``asset_uri``/``sha256``/``size_bytes`` and the
       descriptive metadata, restamp the dataset origin, bump the tile-cache
       version, write the version + history rows, finalize the job
    7. Only after that commits: reap the superseded objects

    Session lifecycle (gh #100): the same two-phase split as ``ingest_raster``.
    The AsyncSession is never held open across ``asyncio.to_thread`` GDAL work
    — doing so corrupts the greenlet bridge and the next flush raises
    ``MissingGreenlet``.
    """
    _bind_task_log_context(
        task_name="reupload_raster", job_id=job_id, dataset_id=dataset_id
    )
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from sqlalchemy.orm import joinedload

    from app.processing.raster.models import RasterAsset

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="raster_replace"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    dataset_uuid = uuid.UUID(dataset_id)
    original_file_path = file_path
    final_status: str = "pending"
    owned_staging_key: str | None = None
    local_cog_path: str | None = None
    tmp_dir: str | None = None
    heartbeat_task: asyncio.Task[None] | None = None
    # The two lists whose DIFFERENCE decides every cleanup on this path.
    # `written` are objects this attempt created; `prior_physical` are the ones
    # the dataset was serving when it started. A replace whose COG hashes to
    # the live asset's key (re-uploading the identical file) puts the same
    # bytes back at the same key, so the key appears in both — and must be
    # reaped by neither the failure path nor the success path.
    written_storage_keys: list[str] = []
    prior_physical_keys: list[str] = []

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session): claim, validate, snapshot.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(
            job_uuid, phase="phase1", attempt_id=attempt_uuid
        ) as (session, job):
            if job is None:
                return

            owned_staging_key = owned_presigned_staging_key(
                job.id, job.user_metadata, job.file_path
            )

            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid, job=job, current_step="validating"
            )
            if heartbeat_task is None:
                return

            # After the claim, not before: the failure handler's job write is
            # fenced on `running`, so anything that raises while the row is
            # still `pending` leaves it pending for the stale sweep to find
            # rather than failing it with the reason.
            asset_result = await session.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == dataset_uuid)
            )
            raster_asset = asset_result.scalar_one_or_none()
            if raster_asset is None:
                raise RasterReplaceError(
                    f"Raster dataset {dataset_id} has no raster asset to replace."
                )
            prior_physical_keys = _prior_asset_keys_to_reap(
                asset_uri=raster_asset.asset_uri,
                quicklook_256_uri=raster_asset.quicklook_256_uri,
                quicklook_512_uri=raster_asset.quicklook_512_uri,
            )

            # feat(#1219): pending -> running on the run row this job's commit
            # door already reserved. Raster reuses that admission gate rather
            # than opening a second one, so there is nothing to create here.
            await claim_run_for_job(session, job_uuid)

            from app.processing.ingest.service import resolve_file_path

            file_path = await resolve_file_path(file_path, job_id)

            try:
                await _validate_upload_file_safety(
                    session,
                    file_path=file_path,
                    source_filename=job.source_filename,
                )
            except ValueError as exc:
                await update_ingest_job_for_attempt(
                    session,
                    job_uuid,
                    attempt_uuid,
                    values={
                        "status": "failed",
                        "error_message": str(exc),
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
                # This branch RETURNS rather than raising, so the broad handler
                # below never runs — the run has to be finalized here or it
                # sits `running` until the sweep cancels it an hour later.
                await record_refresh_failure(
                    session,
                    ingest_job_id=job_uuid,
                    error_code="validation_failed",
                    error_message=str(exc),
                    contacted_origin=False,
                )
                await session.commit()
                Path(file_path).unlink(missing_ok=True)
                final_status = "failed"
                return

            um: dict = job.user_metadata or {}
            source_filename: str | None = job.source_filename

            # The claim above rides its own commit, but `claim_run_for_job`
            # does not — and this session closes at the end of the block, so
            # without this the pending -> running transition rolls back. The
            # run then sits `pending` for the whole conversion, and
            # `record_refresh_success` (which expects `running`) declines to
            # finalize it: a successful replace would leave a stuck active
            # reservation that the admission index honors by refusing every
            # later refresh until the sweep. Same commit `reupload_file` ends
            # its phase 1 with.
            await session.commit()

        # ----------------------------------------------------------------- #
        # CPU work — NO session open (gh #100).
        # ----------------------------------------------------------------- #
        source_sha256 = await asyncio.to_thread(sha256_file, file_path)
        meta = await asyncio.to_thread(extract_raster_metadata, file_path)

        assign_crs = um.get("srid_override")
        user_compression = um.get("compression") or "DEFLATE"
        user_resampling = um.get("resampling") or None
        user_nodata = um.get("nodata_override")
        crs_missing = not meta.get("crs_wkt")
        if crs_missing and not assign_crs:
            raise RasterReplaceError(
                "Missing CRS: the replacement raster has no coordinate reference "
                "system. Provide a CRS override (EPSG code) and try again."
            )

        await _enforce_strict_cog(
            file_path,
            expected_compression=user_compression,
            is_manifest_vrt=False,
            strict_cog=bool(um.get("strict_cog")),
        )

        await _stamp_progress(
            job_uuid,
            attempt_uuid,
            phase="progress_write_cog_convert",
            step="cog_convert",
            progress=0.2,
        )

        tmp_dir = tempfile.mkdtemp(dir=_scratch_dir())
        local_cog_path, cog_status = await _convert_and_verify_cog(
            file_path,
            tmp_dir,
            compression=user_compression,
            resampling=user_resampling,
            nodata=user_nodata,
            assign_crs=assign_crs if assign_crs and crs_missing else None,
        )

        asset_sha256 = await asyncio.to_thread(sha256_file, local_cog_path)
        cog_size = os.path.getsize(local_cog_path)

        await _stamp_progress(
            job_uuid,
            attempt_uuid,
            phase="progress_write_quicklook",
            step="quicklook",
            progress=0.6,
        )

        ql256 = await asyncio.to_thread(generate_quicklook, local_cog_path, 256)
        ql512 = await asyncio.to_thread(generate_quicklook, local_cog_path, 512)

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): write the new objects, then swap the
        # pointer and all its dependent rows in ONE transaction.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(
            job_uuid, phase="phase2", attempt_id=attempt_uuid
        ) as (session, job):
            if job is None:
                return
            job.current_step = "finalize"
            job.progress = 0.8

            dataset = (
                await session.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == dataset_uuid)
                )
            ).scalar_one()
            raster_asset = (
                await session.execute(
                    select(RasterAsset)
                    .where(RasterAsset.dataset_id == dataset_uuid)
                    .with_for_update()
                )
            ).scalar_one()

            from app.platform.storage import get_storage

            storage = get_storage()
            base_key = f"rasters/{dataset.id}/{asset_sha256}"
            cog_key = f"{base_key}/source.cog.tif"
            ql256_key = f"{base_key}/quicklook_256.png"
            ql512_key = f"{base_key}/quicklook_512.png"
            (
                _storage_cog_key,
                _storage_ql256_key,
                _storage_ql512_key,
            ) = _resolve_managed_raster_storage_keys(cog_key, ql256_key, ql512_key)

            # The new content hash gives these a prefix the live asset does not
            # share, so these three puts cannot touch what is still serving.
            with open(local_cog_path, "rb") as fobj:
                await storage.put(_storage_cog_key, fobj)
            written_storage_keys.append(_storage_cog_key)
            await storage.put(_storage_ql256_key, io.BytesIO(ql256))
            written_storage_keys.append(_storage_ql256_key)
            await storage.put(_storage_ql512_key, io.BytesIO(ql512))
            written_storage_keys.append(_storage_ql512_key)

            nodata_val = meta.get("nodata")
            raster_asset.asset_uri = cog_key
            raster_asset.quicklook_256_uri = ql256_key
            raster_asset.quicklook_512_uri = ql512_key
            raster_asset.sha256 = asset_sha256
            raster_asset.size_bytes = cog_size
            raster_asset.source_sha256 = source_sha256
            raster_asset.cog_status = cog_status
            raster_asset.driver = meta.get("driver")
            raster_asset.ingested_at = datetime.now(timezone.utc)
            raster_asset.crs_wkt = meta.get("crs_wkt")
            raster_asset.epsg = meta.get("epsg")
            raster_asset.band_count = meta.get("band_count")
            raster_asset.dtype = meta.get("dtype")
            raster_asset.nodata = str(nodata_val) if nodata_val is not None else None
            raster_asset.res_x = meta.get("res_x")
            raster_asset.res_y = meta.get("res_y")
            raster_asset.width = meta.get("width")
            raster_asset.height = meta.get("height")
            raster_asset.compression = meta.get("compression")
            raster_asset.band_info = meta.get("band_info")
            raster_asset.is_rotated = meta.get("is_rotated", False)
            # Recomputed, not carried over: replacing a single-band float
            # elevation raster with an RGB orthophoto has to stop rendering as
            # terrain. Same reasoning as the VRT regenerate path (#185).
            raster_asset.is_dem = meta.get("is_dem_candidate", False)

            new_version = dataset.current_version + 1
            dataset.current_version = new_version
            dataset.srid = meta.get("epsg")
            dataset.original_srid = meta.get("epsg")
            dataset.source_filename = source_filename
            dataset.source_format = "geotiff"
            # fix(#525 B-038): the Valkey purge cannot reach CDN or browser
            # caches keyed on the tile URL, so the `_v=` buster has to roll in
            # the same transaction as the pointer it invalidates.
            dataset.bump_tile_cache_version()
            # feat(#1218) ADR-002 Decision 7: the dataset IS the COG and the
            # upload is a transient input, so the origin restamps to the new
            # file with no remote URI to point at.
            set_dataset_origin(
                dataset,
                "upload",
                filename=source_filename,
                file_hash=source_sha256,
            )
            swap_time = datetime.now(timezone.utc)
            dataset.last_refreshed_at = swap_time
            dataset.record.updated_by = uuid.UUID(user_id)
            if meta.get("bbox_wkt"):
                dataset.record.spatial_extent = func.ST_GeomFromText(
                    meta["bbox_wkt"], 4326
                )

            # Keep the download and STAC surfaces pointing at what is live.
            # Same two statements regenerate_vrt runs, for the same reason: a
            # pointer left behind here serves a key that is about to be reaped.
            await session.execute(
                text(
                    "UPDATE catalog.record_distributions SET url = :url "
                    "WHERE record_id = (SELECT record_id FROM catalog.datasets "
                    "WHERE id = :dataset_id) AND format = 'geotiff'"
                ),
                {"url": cog_key, "dataset_id": dataset_uuid},
            )
            await session.execute(
                text(
                    "UPDATE catalog.dataset_assets SET href = CASE key "
                    "WHEN 'data' THEN :cog_key "
                    "WHEN 'thumbnail' THEN :ql256_key "
                    "WHEN 'overview' THEN :ql512_key ELSE href END, "
                    "size_bytes = CASE WHEN key = 'data' THEN :size "
                    "ELSE size_bytes END "
                    "WHERE dataset_id = :dataset_id "
                    "AND key IN ('data', 'thumbnail', 'overview')"
                ),
                {
                    "cog_key": cog_key,
                    "ql256_key": ql256_key,
                    "ql512_key": ql512_key,
                    "size": cog_size,
                    "dataset_id": dataset_uuid,
                },
            )

            DatasetVersion = port.get_dataset_version_orm_class()
            version = DatasetVersion(
                dataset_id=dataset.id,
                version_number=new_version,
                source_filename=source_filename,
                source_format="geotiff",
                srid=meta.get("epsg"),
                # feature_count and geometry_type stay NULL: a raster has
                # neither, and inventing a pixel count for a column the vector
                # path uses for row counts would make the two unreadable side
                # by side.
                file_hash=source_sha256,
                uploaded_by=uuid.UUID(user_id),
            )
            session.add(version)
            await session.flush()

            from app.modules.audit.service import (  # LAZY — preserved per D-17
                AuditEvent,
                audit_emit,
            )

            # Same action as the vector swap. A provenance test asserts
            # `reupload.commit` for this door; a raster-specific action would
            # split one user-visible operation across two audit vocabularies.
            await audit_emit(
                session,
                AuditEvent(
                    user_id=uuid.UUID(user_id),
                    action="reupload.commit",
                    resource_type="dataset",
                    resource_id=dataset.id,
                    details={
                        "version_number": new_version,
                        "source_type": "file",
                        "source_format": "geotiff",
                        "source_filename": source_filename,
                    },
                ),
            )

            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={
                    "status": "complete",
                    "dataset_id": dataset.id,
                    "completed_at": datetime.now(timezone.utc),
                    "current_step": "complete",
                    "progress": 1.0,
                },
            )
            # feat(#1219): the run's terminal status commits WITH the job's and
            # with the pointer swap, so "job complete, run still running" and
            # "asset swapped, no history row" are both unreachable.
            # contacted_origin=False — these bytes came from the browser.
            # schema_diff is None: a raster has no attribute schema to drift.
            await record_refresh_success(
                session,
                ingest_job_id=job_uuid,
                dataset=dataset,
                dataset_version_id=version.id,
                feature_count_after=None,
                schema_diff=None,
                contacted_origin=False,
            )
            await session.commit()
            final_status = "complete"

        await invalidate_catalog_cache()
        # Only now. Up to this line every exit leaves the previous COG both
        # pointed at and present; past it the pointer is durably elsewhere, so
        # these objects have no reader left. The `not in written` filter is
        # what makes re-uploading the identical file a no-op rather than a
        # self-inflicted delete.
        #
        # "No reader left" is true of the DATABASE. An API process that served
        # a tile in the last minute may still hold this dataset in the tile
        # router's `_resolve_raster_meta` cache, whose entries carry the OLD
        # asset_uri for up to `_RASTER_META_CACHE_TTL` (60s) — so raster tiles
        # can fail for that window before the entry expires and the new pointer
        # is read. Deliberately not worked around: `regenerate_vrt` reaps its
        # superseded generation the same way against the same cache, the window
        # is bounded and self-healing, and closing it needs cross-process
        # invalidation that neither path has. The bumped `tile_cache_version`
        # already changes the tile URL, so browser and CDN caches roll over.

        await _cleanup_orphaned_storage_keys(
            [key for key in prior_physical_keys if key not in written_storage_keys],
            job_id=job_id,
        )

        async with async_session() as embed_session:
            embed_dataset = (
                await embed_session.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == dataset_uuid)
                )
            ).scalar_one_or_none()
            if embed_dataset is not None:
                from app.processing.embeddings.helpers import defer_embedding

                await defer_embedding(embed_dataset)

    except Exception as exc:  # broad: spans GDAL/COG/storage — any step can fail
        logger.exception("Raster replace failed", job_id=job_id, task="reupload_raster")
        async with _job_phase_session(
            job_uuid, phase="error_write", attempt_id=attempt_uuid
        ) as (err_session, _err_job):
            await update_ingest_job_for_attempt(
                err_session,
                job_uuid,
                attempt_uuid,
                values={
                    "status": "failed",
                    "error_message": str(exc),
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            # feat(#1219): last_refreshed_at is untouched by construction —
            # nothing on this path writes it — so a failed replace leaves the
            # dataset's freshness, its pointer, and its tiles exactly as they
            # were (invariant 10). contacted_origin=False: an upload reaches no
            # origin, so there is no contact to date and no binding to guard.
            await record_refresh_failure(
                err_session,
                ingest_job_id=job_uuid,
                error_code="raster_refresh_failed",
                error_message=str(exc),
                contacted_origin=False,
            )
            await err_session.commit()
        final_status = "failed"
        raise
    finally:
        await stop_ingest_job_heartbeat(heartbeat_task)
        # The failure mirror of the success reap above, and the reason both
        # filter rather than delete outright: on this path the keys to remove
        # are the ones this attempt WROTE, minus any the live asset still
        # points at. Deleting the intersection would take out the raster the
        # dataset is still serving — the precise failure invariant 10 forbids.
        if final_status != "complete" and written_storage_keys:
            await _cleanup_orphaned_storage_keys(
                [key for key in written_storage_keys if key not in prior_physical_keys],
                job_id=job_id,
            )
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if final_status == "complete":
            Path(file_path).unlink(missing_ok=True)
        elif file_path != original_file_path:
            Path(file_path).unlink(missing_ok=True)
        # fix(#1207): the client-writable staging key, which stays recreatable
        # through an unexpired PUT URL until it is swept.
        await reap_presigned_staging_object(
            job_id, owned_staging_key, final_status=final_status
        )
        # fix(#1210), ADR-002 Decision 7: the pre-conversion upload, deleted on
        # success and retained on failure as the operator's only diagnostic
        # copy — bounded by the retention purge, which reaps a failed job's
        # staged file because a failed job is not its dataset's latest-complete
        # row. RUNBOOK.md section 9 states that window.
        await reap_downloaded_staging_source(
            job_id,
            original_file_path=original_file_path,
            final_status=final_status,
            failed_source_replayable=True,
        )
