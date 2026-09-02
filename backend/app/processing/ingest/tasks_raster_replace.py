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
from sqlalchemy import select

from app.core.db.tenant_session import tenant_task
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
from app.processing.raster.cog import (
    _scratch_dir,
    check_and_prepare_cog,
    cog_preserves_source,
    extract_raster_metadata,
    resolve_crs_assignment,
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
from app.processing.ingest.tasks_raster_common import (
    _cleanup_orphaned_storage_keys,
    _enforce_strict_cog,
    _resolve_managed_raster_storage_keys,
    absorb_cancellation,
    extract_source_raster_metadata,
    publish_commit_landed,
)
from app.processing.ingest.tasks_raster_swap import (
    _prior_asset_keys_to_reap,
    archive_lossy_original,
    archived_original_asset_key,
    upsert_archived_original_row,
    reserve_replacement_bytes,
    _run_post_swap_followups,
    _upsert_managed_asset_rows,
    _write_swapped_fields,
)

logger = structlog.get_logger(__name__)


class RasterReplaceError(Exception):
    """A raster replace that failed for a reason the user can act on."""


async def _read_published_cog(cog_path: str) -> dict:
    """Read the freshly written COG back, and return what it actually says.

    Two jobs, one rasterio open pass, on purpose.

    The first is the "verified readable" half of invariant 10. Conversion
    reporting success is not the same fact as the output being openable: a
    truncated write, an out-of-space overview pass, or a driver quirk all
    produce a file on disk that ``gdal_translate`` exited 0 for. Since the very
    next steps discard the last-known-good asset, the check has to be explicit
    here rather than left as a side effect of quicklook generation, which is a
    step someone could reasonably make non-fatal later.

    The second (fix(#1290 review)) is the catalog's metadata. It used to be
    extracted from the pre-conversion source, so every field conversion can
    change — ``compression`` always, ``nodata`` under an override, the CRS and
    the footprint under ``srid_override`` — described a file the dataset does
    not serve. Reading the artifact that WILL serve, once, means there is no
    second seam that can drift from the first and no question about which read
    is authoritative.

    fix(#1291): the footprint is still on that list after ``srid_override``
    became an assignment, and for a sharper reason. The conversion no longer
    moves the corner coordinates at all — it changes what they MEAN. The same
    numbers read in the assigned CRS land somewhere else on earth than they do
    in the CRS the caller just told us was wrong, so the source read would
    place the dataset at the wrong spot on the map with no field visibly
    disagreeing. ``extract_raster_metadata`` here reads them off the COG,
    under the CRS that COG now declares.

    Goes through ``extract_raster_metadata`` — already the reader every other
    raster path uses, so this adds no new GDAL seam for Rule 2 to police.
    """
    try:
        return await asyncio.to_thread(extract_raster_metadata, cog_path)
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
) -> tuple[str, str, dict]:
    """Convert to COG and read the result back.

    Returns ``(path, cog_status, metadata_of_the_converted_file)`` — that third
    element is what the catalog persists (fix(#1290 review)); see
    ``_read_published_cog`` for why it comes from here and not from the source.

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
    cog_meta = await _read_published_cog(local_cog_path)
    return local_cog_path, cog_status, cog_meta


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
    # fix(#1290 review): "the replacement is published", set at the commit and
    # nowhere else. The failure cleanup keys off THIS rather than off
    # `final_status`, because once the swap is committed the newly written
    # objects are the dataset's live raster and nothing that happens afterwards
    # can make them reapable.
    swap_committed: bool = False
    # fix(#1290 review): whether the COG carries everything the upload did.
    # False until a conversion proves otherwise — Decision 7's delete is
    # licensed by that fact and the default has to be the one that retains.
    source_preserved_in_cog: bool = False
    # fix(#1290 review): set when a lossy conversion's original has been copied
    # to the durable `originals/` prefix. Until it is true the staged upload is
    # the only faithful copy and nothing may delete it.
    lossy_original_archived: bool = False

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
                # fix(#1290 review): NO unlink here. This exit used to delete
                # the local file unconditionally, which on a local-storage
                # install is the durable original — so a worker-side validation
                # failure (canonically: UPLOAD_MAX_SIZE_MB lowered while the job
                # sat queued) destroyed the only copy of a file the job then
                # recorded as failed, with nothing to diagnose from. The
                # object-storage shape was already right because the thing it
                # deletes is a downloaded scratch copy.
                #
                # The terminal `finally` already knows that distinction, and it
                # runs on this return, so the correct fix is to have ONE exit
                # decide rather than teach a second one the same rule.
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
        # The SOURCE read, and its only remaining job: decide whether the
        # conversion needs a CRS assignment. Nothing here is persisted —
        # fix(#1290 review) moved every stored field onto the converted COG's
        # own metadata, which is the file the dataset will actually serve.
        # fix(#1661): extract_source_raster_metadata (not extract_raster_metadata
        # directly) so an unopenable upload raises a friendly message built from
        # `source_filename` instead of leaking the staging path in `file_path`.
        source_meta = await asyncio.to_thread(
            extract_source_raster_metadata,
            file_path,
            original_filename=source_filename,
        )

        user_compression = um.get("compression") or "DEFLATE"
        user_resampling = um.get("resampling") or None
        user_nodata = um.get("nodata_override")
        # fix(#1290 review): shared with the first-ingest tail, and it applies a
        # supplied override even when the source declares a CRS. Raises when the
        # source has none and no override was given.
        assign_crs = resolve_crs_assignment(
            crs_wkt=source_meta.get("crs_wkt"),
            srid_override=um.get("srid_override"),
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
        local_cog_path, cog_status, cog_meta = await _convert_and_verify_cog(
            file_path,
            tmp_dir,
            compression=user_compression,
            resampling=user_resampling,
            nodata=user_nodata,
            assign_crs=assign_crs,
        )
        # fix(#1290 review): resolved state, not the request field. Decided here
        # rather than in the tail because this is where the conversion that
        # actually ran is known — a `verified` COG loses nothing whatever codec
        # it carries, and the request field cannot tell you which happened.
        # fix(#1291): the second axis is gone with the warp. `assign_crs` now
        # reaches `gdal_translate -a_srs`, which writes a tag and passes every
        # band through, so an override no longer costs this dataset a second
        # permanent copy of the upload. See `cog_preserves_source`.
        source_preserved_in_cog = cog_preserves_source(cog_status, user_compression)

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

            # fix(#1290 review): every field below reads the CONVERTED COG's
            # own metadata. Persisting the source's described a file the
            # dataset does not serve — `compression` was wrong on every
            # converted replace, `nodata` wrong under an override, and the CRS
            # and footprint wrong under `srid_override`, which is exactly the
            # case a caller reaches for when the source's CRS is the problem.
            # fix(#1291): the footprint stays wrong from the source read now
            # that the override assigns rather than warps — the corner numbers
            # are identical either side of the conversion, so the ONLY thing
            # that decides where this dataset lands on the map is which CRS
            # they are read under. `original_srid` is the one field still taken
            # from `source_meta`, and it wants the upload's answer by design.
            new_version = _write_swapped_fields(
                raster_asset,
                dataset,
                cog_meta=cog_meta,
                cog_key=cog_key,
                ql256_key=ql256_key,
                ql512_key=ql512_key,
                asset_sha256=asset_sha256,
                source_sha256=source_sha256,
                source_meta=source_meta,
                cog_size=cog_size,
                cog_status=cog_status,
                source_filename=source_filename,
                user_id=user_id,
            )

            # Keep the download and STAC surfaces pointing at what is live.
            # fix(#1290 review): upserts, not UPDATEs. A STAC-imported raster
            # has neither of these rows — the import creates the dataset and
            # the asset and stops — so the UPDATEs matched nothing, succeeded,
            # and left the replaced dataset advertising no COG and no
            # quicklooks to search, STAC and the download endpoint. A zero-row
            # UPDATE reporting success is the same requested-vs-happened trap
            # as round 1, one level down.
            # fix(#1290 review): ADR-002 Decision 7's retained original lives
            # under `originals/<dataset_id>/`, the prefix the vector tails have
            # archived to since #430 and which `delete_dataset` already reaps.
            # It runs HERE — before the reservation — because its bytes are
            # part of the total being admitted and because a genuinely new
            # object has to join the written set before anything can fail.
            (
                lossy_original_archived,
                archived_key,
                archived_bytes,
                new_archive_key,
            ) = await archive_lossy_original(
                session,
                job=job,
                dataset_id=dataset.id,
                file_path=file_path,
                source_sha256=source_sha256,
                filename=source_filename,
                log_message=(
                    "Failed to archive the lossy replacement original; the "
                    "staged upload will be retained in place instead"
                ),
                needed=not source_preserved_in_cog,
                written_storage_keys=written_storage_keys,
            )
            # Only an object this attempt CREATED joins the written set. An
            # archive that already existed belongs to an earlier successful
            # replace, and reaping it on failure would destroy the original of
            # the raster that is still live.
            # fix(#1290 review): the helper registers the key itself, BEFORE
            # the cancellable write — appending here as well would double-add,
            # and appending here INSTEAD would restore the cancellation hole.

            # fix(#1290 review): BEFORE the upsert — see the helper's docstring
            # for why the ordering is load-bearing. Raises
            # StorageQuotaExceededError, which the task's broad handler records
            # as a failed run, leaving the previous raster serving.
            await reserve_replacement_bytes(
                session,
                dataset_id=dataset_uuid,
                owner_id=dataset.record.created_by,
                new_size=cog_size,
                archived_bytes=archived_bytes,
                archived_asset_key=(
                    archived_original_asset_key(source_sha256) if archived_key else None
                ),
            )
            await upsert_archived_original_row(
                session,
                dataset_id=dataset_uuid,
                logical_key=archived_key,
                asset_key=(
                    archived_original_asset_key(source_sha256) if archived_key else None
                ),
                size_bytes=archived_bytes,
                source_filename=source_filename,
            )
            await _upsert_managed_asset_rows(
                session,
                dataset_id=dataset_uuid,
                record_id=dataset.record_id,
                cog_key=cog_key,
                ql256_key=ql256_key,
                ql512_key=ql512_key,
                cog_size=cog_size,
            )

            DatasetVersion = port.get_dataset_version_orm_class()
            version = DatasetVersion(
                dataset_id=dataset.id,
                version_number=new_version,
                source_filename=source_filename,
                source_format="geotiff",
                srid=cog_meta.get("epsg"),
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
            try:
                await session.commit()
            except BaseException as exc:
                # fix(#1778): the one await on this path whose outcome is
                # genuinely unknown — see `publish_commit_landed`. A lost
                # acknowledgement left the flag below false, and the terminal
                # cleanup then deleted the three keys the committed
                # RasterAsset had just been pointed at.
                if not await publish_commit_landed(
                    job_uuid, attempt_uuid, job_id=job_id, task="reupload_raster"
                ):
                    raise
                # fix(#1778 codex r1): stand down rather than re-raise, the
                # same decision the other three tails make. `final_status`
                # deliberately stays non-complete: it also licenses deleting
                # the uploader's staged original, and a probe answer must
                # never reach that decision.
                swap_committed = True
                absorb_cancellation(exc)
                return
            # fix(#1290 review): set in the same breath as the commit, and read
            # by the terminal cleanup instead of `final_status`. These are two
            # different facts and the cleanup needs this one: "the replacement
            # is published" is what makes the newly written objects
            # unreapable, whereas `final_status` also carries "did anything go
            # wrong afterwards", which is not a question about the objects.
            # Keying the reap off the proxy meant a transient error in the
            # optional post-commit work below reaped the COG the committed
            # RasterAsset now points at.
            swap_committed = True
            final_status = "complete"

        # fix(#1290 review): everything from here is optional post-commit work,
        # fenced so it cannot be mistaken for a failed replace. The swap is
        # durable; a cache purge that cannot reach Valkey, a reap that cannot
        # reach storage, or an embedding defer against a busy queue are all
        # things to log and move on from, not reasons to fail a job whose
        # outcome is already committed and already reported as succeeded in the
        # run row. The `swap_committed` guard in the `finally` is the
        # structural half of this: the fence keeps today's code from raising,
        # and the guard keeps tomorrow's from destroying anything if it does.
        try:
            await _run_post_swap_followups(
                dataset_uuid=dataset_uuid,
                dataset_cls=Dataset,
                prior_physical_keys=prior_physical_keys,
                written_storage_keys=written_storage_keys,
                job_id=job_id,
            )
        except Exception:  # broad: nothing after the commit may fail the job
            logger.warning(
                "raster_replace_post_swap_followup_failed",
                job_id=job_id,
                dataset_id=dataset_id,
                exc_info=True,
            )

    except Exception as exc:  # broad: spans GDAL/COG/storage — any step can fail
        # fix(#1778 codex r1): the other three tails guard this handler on
        # their published flag, because each of them can reach it with a
        # durable publish behind it and then write something untrue about it.
        # This one carries no such write: `_run_post_swap_followups` has its
        # own fence, so nothing between the commit and here raises, and every
        # write below is already fenced against a completed job anyway
        # (`update_ingest_job_for_attempt` on `running`, `record_refresh_failure`
        # excludes terminal runs). A flag check would be a third fence with
        # nothing left to catch.
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
        # The failure mirror of the success reap, and the reason both filter
        # rather than delete outright: on this path the keys to remove are the
        # ones this attempt WROTE, minus any the live asset still points at.
        # Deleting the intersection would take out the raster the dataset is
        # still serving — the precise failure invariant 10 forbids.
        #
        # fix(#1290 review): gated on `swap_committed`, not `final_status`.
        # Those diverge in exactly one place and it is the dangerous one: after
        # the swap commits, the written keys ARE the live asset, so a later
        # error must never bring the task through here to delete them.
        if not swap_committed and written_storage_keys:
            await _cleanup_orphaned_storage_keys(
                [key for key in written_storage_keys if key not in prior_physical_keys],
                job_id=job_id,
            )
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        # fix(#1290 review): the local file is one of two different things and
        # only one of them is Decision 7's business. When it differs from
        # `original_file_path` it is a scratch copy this task downloaded from
        # object storage, and the durable copy is the object — always safe to
        # remove. When they are equal this IS the durable original: local-mode
        # uploads land in `settings.upload_staging_dir`, which is the named
        # `upload_staging` volume (not tmpfs), survives restarts and is what the
        # backup container archives. So on a local install it is the only
        # lossless copy, and it gets the same gate as the object-store reaper —
        # otherwise the RUNBOOK's retention promise held on S3 and quietly
        # failed on every local deployment.
        #
        # One condition rather than an `if`/`elif` that repeated the same
        # statement: the two branches always did the same thing, and merging
        # them is what pays for the stand-down branch above without loosening
        # the McCabe gate this function sits under.
        if file_path != original_file_path or (
            final_status == "complete"
            and (source_preserved_in_cog or lossy_original_archived)
        ):
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
        #
        # fix(#1290 review): and retained on SUCCESS too when the conversion
        # was lossy, because Decision 7's licence to delete rests on the COG
        # carrying everything the upload did — true of DEFLATE, false of the
        # JPEG and WEBP profiles the import UI also offers. Same gate as the
        # first-ingest tail, same shared predicate, so the two cannot drift.
        if source_preserved_in_cog or lossy_original_archived:
            await reap_downloaded_staging_source(
                job_id,
                original_file_path=original_file_path,
                final_status=final_status,
                failed_source_replayable=True,
            )
