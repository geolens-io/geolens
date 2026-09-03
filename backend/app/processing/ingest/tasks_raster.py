"""Procrastinate task definitions for raster/COG file ingestion."""

import uuid
from datetime import datetime, timezone

import structlog

from app.core.db.tenant_session import current_tenant_var, tenant_task
from app.core.tenancy import is_multi_tenant
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.heartbeat import (
    claim_job_attempt_and_start_heartbeat,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
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

from app.platform.jobs.models import owned_presigned_staging_key
from app.processing.ingest.tasks_raster_swap import (
    archive_lossy_original,
    archived_original_asset_key,
    archived_original_uri,
    upsert_archived_original_row,
)
from app.processing.ingest.tasks_raster_common import (
    _build_dataset_asset_rows,
    _cleanup_orphaned_storage_keys,
    _enforce_strict_cog,
    _is_manifest_vrt_job,
    _reject_raw_vrt_job,
    _resolve_managed_raster_storage_keys,
    absorb_cancellation,
    create_raster_dataset,
    extract_source_raster_metadata,
    publish_commit_landed,
    record_unpublished_storage_keys,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _emit_billing_event,
    _job_phase_session,
    _parse_temporal_fields,
    _validate_upload_file_safety,
    apply_manifest_record_metadata,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
    task_app,
)


@task_app.task(queue="raster", retry=0, aliases=["app.ingest.tasks.ingest_raster"])
@tenant_task
async def ingest_raster(
    job_id: str,
    file_path: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
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

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="raster"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    local_cog_path: str | None = None
    tmp_dir: str | None = None
    original_file_path = file_path
    final_status: str = "pending"
    # fix(#1290 review): False until a conversion is known to have kept every
    # sample. Decision 7's delete is licensed by that fact and nothing else, so
    # the default has to be the one that retains.
    source_preserved_in_cog: bool = False
    # fix(#1290 review): set when a lossy conversion's original has been copied
    # to the durable `originals/` prefix. Until it is true the staged upload is
    # the only faithful copy and nothing may delete it.
    lossy_original_archived: bool = False
    # fix(#1202 review r5): captured in phase 1, swept in the finally.
    owned_staging_key: str | None = None
    # GAP-017: storage keys written BEFORE the terminal DB commit. base_key
    # embeds dataset.id, a flushed-but-uncommitted UUID — if the commit (or any
    # step after the puts) fails the dataset row is rolled back, so delete_dataset
    # never reaps these assets. Track them and clean up on the failure path so a
    # crash mid-ingest doesn't orphan COG/quicklook bytes under rasters/.
    written_storage_keys: list[str] = []
    # fix(#1778): "the COG and quicklooks are published", set at the terminal
    # commit and nowhere else. The reap below keys off THIS rather than off
    # `final_status`, for the reason fix(#1290 review) gives in the replace
    # tail: `final_status` also carries "did anything go wrong afterwards",
    # which is not a question about the objects, and the broad handler sets it
    # to "failed" even when the failure happened after the swap was durable.
    publish_committed: bool = False
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session via _job_phase_session — REMED-03 /
        # P2-05): load job, mark running, validate. Snapshot the values
        # needed for CPU work into local variables so phase 2 can re-load
        # the job in a fresh session without depending on attached ORM
        # state surviving the asyncio.to_thread calls.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(
            job_uuid, phase="phase1", attempt_id=attempt_uuid
        ) as (session, job):
            if job is None:
                return

            # fix(#1202 review r7): captured HERE, first thing after the row is
            # in hand, so no exit from this block can precede it. It used to sit
            # with the phase-2 snapshot below, past three exits — the
            # heartbeat-claim bail, a `resolve_file_path` download failure, and
            # the validation `return` — each of which reached the terminal
            # `finally` with the key still None and left the staging object
            # behind. The validation path is the reachable one: lowering
            # UPLOAD_MAX_SIZE_MB between completion and worker pickup fails a
            # job whose bytes are already in the bucket. Reads the DB column,
            # not the local `file_path` that step 2 rebinds, so moving it
            # earlier changes the timing and nothing else.
            owned_staging_key = owned_presigned_staging_key(
                job.id, job.user_metadata, job.file_path
            )

            # 1. Mark running.
            # REMED-02 / ingest-audit P2-07: the fresh "validating" stamp rides
            # the claim commit (see the helper). Raster ingests are the prime
            # motivator — 10-min COG conversion + quicklook generation
            # otherwise looks like a dead spinner.
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid, job=job, current_step="validating"
            )
            if heartbeat_task is None:
                return

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
                # EVENT-03: notify on ingest failed (non-fatal, after commit — deferred import).
                # status="failed" is already committed so a notification error cannot
                # roll back or alter the terminal job write (T-1230-09 fail-safe).
                _early_reason = str(exc)
                _early_job_id = str(job_uuid)
                from app.platform.notifications.events import (
                    build_event_notification,
                    emit_event_safe,
                )

                await emit_event_safe(
                    event_key="ingest_failed",
                    build=lambda: build_event_notification(
                        "ingest_failed",
                        subject="Raster ingest failed: validation error",
                        body="Raster ingest job failed during validation.",
                        reason=_early_reason,
                        extra={"job_id": _early_job_id, "task": "ingest_raster"},
                    ),
                )
                return

            # Snapshot job attributes needed in phase 2 (after CPU work).
            # These plain Python values do not require an attached ORM session.
            um: dict = job.user_metadata or {}
            source_filename: str | None = job.source_filename
            _reject_raw_vrt_job(source_filename)
            is_manifest_vrt = _is_manifest_vrt_job(job)

        # ----------------------------------------------------------------- #
        # CPU work — NO session open. asyncio.to_thread calls run GDAL/numpy
        # in the thread pool. Holding a session open here is what triggers
        # the MissingGreenlet bug (gh #100).
        # ----------------------------------------------------------------- #

        # 4. Hash source file
        source_sha256 = await asyncio.to_thread(sha256_file, file_path)

        # 5. Extract metadata from the SOURCE. Only two things come from this
        # read now (fix(#1290 review)): whether a CRS assignment is needed, and
        # `original_srid`. Everything the catalog stores describes the COG.
        # fix(#1661): extract_source_raster_metadata (not extract_raster_metadata
        # directly) so an unopenable upload raises a friendly message built from
        # `source_filename` instead of leaking the staging path in `file_path`.
        source_meta = await asyncio.to_thread(
            extract_source_raster_metadata,
            file_path,
            original_filename=source_filename,
        )

        # Read GDAL options from user_metadata (set at commit time)
        assign_crs = um.get("srid_override")
        user_compression = um.get("compression") or "DEFLATE"
        user_resampling = um.get("resampling") or None
        user_nodata = um.get("nodata_override")
        # fix(#1186): derive this from the raster, not from an upload-time
        # stamp. `user_metadata["crs_missing"]` was written only by the
        # non-presigned upload endpoint, so it was absent for every S3
        # (presigned) upload — and `assign_crs` below was gated on it, meaning
        # a user-supplied srid_override was silently dropped and the COG came
        # out with no CRS. `meta` is read from the file itself, which is the
        # authority the flag was standing in for.
        #
        # fix(#1290 review): the missing-CRS gate and the override decision are
        # one rule now, shared with the replace tail. It also answers the
        # override differently: a supplied EPSG applies even when the source
        # declares a CRS, which is what the field's own description promises.
        assign_crs = resolve_crs_assignment(
            crs_wkt=source_meta.get("crs_wkt"), srid_override=assign_crs
        )

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
            job_uuid, phase="progress_write_cog_convert", attempt_id=attempt_uuid
        ) as (
            _progress_session,
            _progress_job,
        ):
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
            # fix(#448): mkdtemp() defaulted to /tmp — a 512 MB RAM-backed
            # tmpfs in the worker container — so the disk-space check below
            # was measuring the wrong filesystem AND a big conversion could
            # ENOSPC or eat the memory cap. Land it on the staging volume.
            tmp_dir = tempfile.mkdtemp(dir=_scratch_dir())
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
                assign_crs=assign_crs,
            )
        assert local_cog_path is not None  # check_and_prepare_cog always returns a path
        # fix(#1290 review): resolved state, not the request field — the branch
        # above can reach this line without converting at all, and a verified
        # COG loses nothing whatever codec it carries. Read in the terminal
        # `finally` to decide whether the uploaded file is still needed.
        # fix(#1291): no `reprojected=`. `assign_crs` now applies through
        # `gdal_translate -a_srs`, which relabels and resamples nothing, so an
        # override no longer makes the COG a lossy copy of the upload and no
        # longer forces a second permanent original. The codec is the only
        # sample-altering axis this pipeline still has; `cog_preserves_source`
        # keeps the parameter for a future reprojecting field to set.
        source_preserved_in_cog = cog_preserves_source(cog_status, user_compression)

        # fix(#1290 review): read the artifact that will actually serve. The
        # pre-conversion read describes a different file: the codec differs on
        # every conversion, and under an override the CRS differs too — with it
        # the footprint, because the same corner coordinates land somewhere
        # else on earth once they are read in the assigned CRS. Same defect the
        # replace tail fixed one round earlier, left behind because that
        # dispatch was scoped to replace only. The source read keeps exactly
        # two jobs: the CRS decision above, and `original_srid` below.
        #
        # fix(#1291): with assignment the pixel grid and the corner NUMBERS
        # survive the conversion unchanged — only the label on them changes —
        # so `extract_raster_metadata` reading the COG interprets those numbers
        # in the assigned CRS, which is exactly the reading the caller asked
        # for. Reading the source would interpret them in the CRS the caller
        # just called wrong.
        cog_meta = await asyncio.to_thread(extract_raster_metadata, local_cog_path)

        # 7. Hash COG
        asset_sha256 = await asyncio.to_thread(sha256_file, local_cog_path)
        cog_size = os.path.getsize(local_cog_path)

        # fix(#1778): the dataset id is decided HERE rather than by the phase-2
        # INSERT, because the object keys below embed it and the durable job
        # row has to be able to name them before the transaction that could
        # roll that id away ever opens. Nothing else changes: phase 2 hands
        # this id to create_*_dataset and `base_key` is built from the same
        # value it always was.
        planned_dataset_id = uuid.uuid4()
        _base_key = f"rasters/{planned_dataset_id}/{asset_sha256}"
        _unpublished_keys = [
            f"{_base_key}/source.vrt"
            if is_manifest_vrt
            else f"{_base_key}/source.cog.tif",
            f"{_base_key}/quicklook_256.png",
            f"{_base_key}/quicklook_512.png",
            # The kept original of a lossy conversion. Its key is content-
            # derived and the dataset id is brand new here, so this attempt is
            # necessarily the only writer of it - unlike the replace tail,
            # where the same key can already hold an earlier upload's archive
            # and must not be registered.
            archived_original_uri(planned_dataset_id, source_sha256=source_sha256),
        ]
        if not await record_unpublished_storage_keys(
            job_uuid,
            attempt_uuid,
            keys=_unpublished_keys,
            # fix(#1778 codex r1): empty, and provably so. Every key above is
            # under a dataset id generated three lines up, so no row can name
            # one. The replace tail passes the live asset's keys here, because
            # an identical re-upload derives the same content hash and would
            # otherwise register the objects the dataset is serving.
            already_published=(),
            # fix(#1778 codex r3): every key above sits under this id, and it
            # is generated per task invocation, so a retry cannot reproduce
            # one. That is this tail's attempt fence; the replace tail has a
            # fixed dataset id and uses its attempt id instead.
            attempt_scope=str(planned_dataset_id),
            job_id=job_id,
            task="ingest_raster",
        ):
            # fix(#1778 audit): a confirmed fence miss. Phase 2's own
            # attempt-fenced load below would catch this too, but stopping
            # here is what actually keeps the recorder's contract ("do not
            # write what nothing records") rather than depending on a second
            # guard downstream to make it true, and it skips the quicklook
            # generation this dead attempt no longer needs.
            return

        # REMED-02 / ingest-audit P2-07: quicklook generation is the other
        # multi-second hotspot. Brief-session write before the two
        # generate_quicklook calls so the UI advances. Routed through
        # _job_phase_session per REMED-03.
        async with _job_phase_session(
            job_uuid, phase="progress_write_quicklook", attempt_id=attempt_uuid
        ) as (
            _progress_session,
            _progress_job,
        ):
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
        async with _job_phase_session(
            job_uuid, phase="phase2", attempt_id=attempt_uuid
        ) as (session, job):
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
                    meta=cog_meta,
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
                    dataset_id=planned_dataset_id,
                )
            else:
                record, dataset, raster_asset = await create_raster_dataset(
                    session,
                    meta=cog_meta,
                    original_srid=source_meta.get("epsg"),
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
                    dataset_id=planned_dataset_id,
                )

            # feat(#1472): the manifest's credit line. Covers both branches
            # above — a manifest raster and a manifest-driven VRT alike, since
            # neither create_*_dataset takes the field.
            apply_manifest_record_metadata(record, um)

            # 9b. Set temporal fields on Record (N5 extraction to _parse_temporal_fields).
            parsed_start, parsed_end, temporal_errors = _parse_temporal_fields(
                temporal_start=um.get("temporal_start")
                or source_meta.get("temporal_start"),
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

            # Resolve every managed key through the same fail-closed seam used
            # by serve/delete/presign paths. The ORM fields below deliberately
            # retain the logical keys.
            (
                _storage_cog_key,
                _storage_ql256_key,
                _storage_ql512_key,
            ) = _resolve_managed_raster_storage_keys(
                cog_key,
                ql256_key,
                ql512_key,
            )

            # GAP-017: record each key so the failure path can delete exactly
            # what was written (and nothing more).
            #
            # fix(#1778): registered BEFORE the put, not after it, which is the
            # rule archive_lossy_original already follows (tasks_raster_swap.py).
            # Ownership is registered by INTENT: both providers drain their
            # worker thread before re-raising CancelledError, so a cancelled put
            # can have COMPLETED, and CancelledError is a BaseException, so an
            # append below it never runs and the finished object is left with
            # nothing naming it. Reaping a key the write never created is an
            # idempotent no-op, so the other direction costs nothing.
            written_storage_keys.append(_storage_cog_key)
            with open(local_cog_path, "rb") as fobj:
                await storage.put(_storage_cog_key, fobj)
            written_storage_keys.append(_storage_ql256_key)
            await storage.put(_storage_ql256_key, io.BytesIO(ql256))
            written_storage_keys.append(_storage_ql512_key)
            await storage.put(_storage_ql512_key, io.BytesIO(ql512))

            # 11. Update asset URIs and create distribution.
            # asset_uri stays as the logical (un-prefixed) key — the tenant
            # prefix is injected at serve-time by resolve_open_path so the
            # DB value is provider- and tenant-agnostic.
            raster_asset.asset_uri = cog_key
            raster_asset.quicklook_256_uri = ql256_key
            raster_asset.quicklook_512_uri = ql512_key
            await session.flush()

            # BUG-041: populate the STAC-aligned dataset_assets table. The read
            # path (search/STAC/OGC `_build_stac_assets`) was always operating on
            # an empty input because ingest never wrote these rows. Insert them
            # in this same transaction so STAC item assets are advertised
            # (data/vrt + thumbnail + overview). On local storage these still
            # resolve to None per GAP-031; on S3-published deployments they
            # become presigned hrefs.
            from app.platform.extensions import (
                get_catalog_port,
                get_processing_port as _get_port,
            )

            # dataset_asset_orm_class lives on the CatalogPort, not the
            # ProcessingPort — get it from get_catalog_port() (BUG-041 follow-up:
            # the original fix used the wrong port and crashed every COG ingest).
            DatasetAsset = get_catalog_port().dataset_asset_orm_class()
            for asset_row in _build_dataset_asset_rows(
                dataset_id=dataset.id,
                cog_key=cog_key,
                ql256_key=ql256_key,
                ql512_key=ql512_key,
                cog_size=cog_size,
                is_manifest_vrt=is_manifest_vrt,
            ):
                session.add(DatasetAsset(**asset_row))
            await session.flush()

            RecordDistribution = _get_port().get_record_distribution_orm_class()

            distribution = RecordDistribution(
                record_id=record.id,
                distribution_type="download",
                format="vrt" if is_manifest_vrt else "geotiff",
                url=cog_key,
            )
            session.add(distribution)

            # fix(#1290 review): same policy as the replace tail, through the
            # same helper. ADR-002 Decision 7's retained original lives under
            # `originals/<dataset_id>/` — the prefix the vector tails have
            # archived to since #430, which `delete_dataset` reaps and no purge
            # touches — and it now carries a counted `dataset_assets` row so
            # per-user storage can see the bytes it consumes.
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
                    "Failed to archive the lossy ingest original; the staged "
                    "upload will be retained in place instead"
                ),
                needed=not source_preserved_in_cog,
                written_storage_keys=written_storage_keys,
            )
            # fix(#1290 review): the helper registers the key itself, BEFORE
            # the cancellable write — appending here as well would double-add,
            # and appending here INSTEAD would restore the cancellation hole.
            _archive_asset_key = (
                archived_original_asset_key(source_sha256) if archived_key else None
            )
            # fix(#1290 review): BEFORE the upsert, not after.
            # `create_raster_dataset` reserved only the COG; the kept original
            # is additional and has to be admitted too. Reserving AFTER the row
            # was written made the live recount already contain those bytes, so
            # adding them again double-charged and falsely refused an ingest
            # that fits. This is the ordering rule the swap module's own
            # docstring states, violated in the other tail —
            # `test_both_tails_reserve_before_they_upsert` pins it now.
            if archived_bytes:
                from app.modules.quota.service import reserve_storage_bytes

                await reserve_storage_bytes(session, uuid.UUID(user_id), archived_bytes)
            await upsert_archived_original_row(
                session,
                dataset_id=dataset.id,
                logical_key=archived_key,
                asset_key=_archive_asset_key,
                size_bytes=archived_bytes,
                source_filename=source_filename,
            )

            # 12. Finalize job.
            # REMED-02 / ingest-audit P2-07: stamp terminal progress
            # alongside status. ``rows_processed`` stays NULL — raster
            # ingests have no rows (the COG and quicklooks ARE the
            # asset). Vector ingests set rows_processed in
            # tasks_common._finalize_ingest from metadata["feature_count"].
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
            try:
                await session.commit()
            except BaseException as exc:
                # fix(#1778): the one await on this path whose outcome is
                # genuinely unknown — see `publish_commit_landed`. A lost
                # acknowledgement left the reap below deleting the COG and
                # quicklooks the committed RasterAsset had just been pointed at.
                if not await publish_commit_landed(
                    job_uuid, attempt_uuid, job_id=job_id, task="ingest_raster"
                ):
                    raise
                # fix(#1778 codex r1): stand down rather than re-raise. The
                # dataset is durable, and the handler below would send the
                # operator an `ingest_failed` notification for an ingest that
                # succeeded. `final_status` deliberately stays non-complete:
                # it also licenses deleting the uploader's staged original,
                # and a probe answer must never reach that decision.
                #
                # fix(#1778 codex r2): nothing to reap on the way out. A first
                # ingest supersedes no asset, so the followups this skips are
                # the completion notification, the cache purge, the embedding
                # defer and the metering event: all recoverable, none of them
                # holding bytes that no row references.
                publish_committed = True
                absorb_cancellation(exc)
                return
            publish_committed = True
            final_status = "complete"

            # EVENT-02: notify on ingest complete (non-fatal, after commit — deferred import).
            # status="complete" is already committed above so a notification error cannot
            # roll back or alter the terminal job write (T-1230-09 fail-safe).
            _complete_title = title  # resolved at line ~486 in this session block
            _complete_job_id = str(job_uuid)
            from app.platform.notifications.events import (
                build_event_notification,
                emit_event_safe,
            )

            await emit_event_safe(
                event_key="ingest_complete",
                build=lambda: build_event_notification(
                    "ingest_complete",
                    subject=f"Raster ingest complete: {_complete_title}",
                    body=f"Raster dataset '{_complete_title}' has been successfully ingested.",
                    extra={"job_id": _complete_job_id, "dataset": _complete_title},
                ),
            )

            # Invalidate cache
            await invalidate_catalog_cache()

            # 13. Generate embedding (non-fatal)
            from app.processing.embeddings.helpers import defer_embedding

            await defer_embedding(dataset)

            # METER-01 (Phase 1213-02): emit raster ingest billable event through
            # the billing-import-free seam. Resolve the optional billing
            # dimension separately from provider keys; event_id = job_id keeps
            # task retries idempotent at the DB layer.
            billing_tenant_id = current_tenant_var.get() if is_multi_tenant() else None
            await _emit_billing_event(
                str(billing_tenant_id) if billing_tenant_id else None,
                "ingest_jobs",
                event_id=job_id,
            )

    except Exception as exc:  # broad: raster ingest spans GDAL/COG/Titiler — any step can fail; record failure
        if publish_committed:
            # fix(#1778 codex r1): the second way this handler is reached with
            # a durable publish behind it, and the one the stand-down above
            # cannot cover: the optional post-commit block runs inside the same
            # try, so a Valkey outage or a busy queue lands here after the
            # dataset is live. Everything below states that the ingest failed,
            # including the operator's `ingest_failed` mail, and none of it is
            # true. Log and finish.
            structlog.get_logger().warning(
                "raster_post_publish_followup_failed",
                job_id=job_id,
                task="ingest_raster",
                exc_info=True,
            )
            return
        structlog.get_logger().exception(
            "Ingest task failed",
            job_id=job_id,
            task="ingest_raster",
        )
        # Write failure status via a fresh session — phase 1/2 sessions are
        # already closed (or rolled back) by the time we get here.
        # REMED-03 / P2-05: route through _job_phase_session.
        async with _job_phase_session(
            job_uuid, phase="error_write", attempt_id=attempt_uuid
        ) as (
            err_session,
            _err_job,
        ):
            from sqlalchemy import update as sa_update

            await err_session.execute(
                sa_update(IngestJob)
                .where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                    IngestJob.status == "running",
                )
                .values(
                    status="failed",
                    error_message=str(exc),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await err_session.commit()
        final_status = "failed"
        # EVENT-03: notify on ingest failed (non-fatal, after commit — deferred import).
        # status="failed" is already committed above (err_session.commit) so a
        # notification error cannot roll back or alter the terminal job write
        # (T-1230-09 fail-safe).  Placed BEFORE the re-raise so the notification
        # fires on the terminal write without suppressing the re-raise (T-1230-10).
        _late_reason = str(exc)
        _late_job_id = job_id
        from app.platform.notifications.events import (
            build_event_notification,
            emit_event_safe,
        )

        await emit_event_safe(
            event_key="ingest_failed",
            build=lambda: build_event_notification(
                "ingest_failed",
                subject="Raster ingest failed",
                body="Raster ingest job failed.",
                reason=_late_reason,
                extra={"job_id": _late_job_id, "task": "ingest_raster"},
            ),
        )
        raise
    finally:
        await stop_ingest_job_heartbeat(heartbeat_task)
        # GAP-017: orphan-asset cleanup. If we wrote COG/quicklook bytes to
        # storage but did NOT reach a successful terminal commit, the dataset
        # row those keys belong to was rolled back — delete_dataset will never
        # reap them. Remove them here so a crash/commit-failure mid-ingest does
        # not leave bytes under a rasters/{dataset_id}/ prefix with no DB row.
        if not publish_committed and written_storage_keys:
            await _cleanup_orphaned_storage_keys(written_storage_keys, job_id=job_id)
        # Clean up temp COG dir
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        # Clean up local staging file
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
        if file_path != original_file_path:
            _Path(file_path).unlink(missing_ok=True)
        elif final_status == "complete" and (
            source_preserved_in_cog or lossy_original_archived
        ):
            _Path(file_path).unlink(missing_ok=True)
        # fix(#1202 review r5): sweep the presigned staging key. Raster has no
        # equivalent of the vector tail's #430 BA-09 block, so before this
        # nothing on this path ever deleted a storage object the client could
        # still overwrite — and the stale-job purge is not a backstop here,
        # because it exempts the newest complete job per dataset, which is
        # exactly what a successful ingest produces. Shared with the vector
        # tail so the two cannot drift.
        await reap_presigned_staging_object(
            job_id, owned_staging_key, final_status=final_status
        )
        # fix(#1210), ADR-002 Decision 7: the pre-conversion source object.
        # This is the vector tail's #430 BA-09 block, which raster never had —
        # so every raster ever ingested kept its uploaded bytes forever beside
        # a COG that already contains them losslessly. `final_status ==
        # "complete"` is reached only after the COG was written, read (metadata
        # + both quicklooks come off it) and its row committed, so the delete
        # can never race the verification it depends on.
        #
        # fix(#1290 review): "losslessly" is a claim about the profile that ran,
        # not about conversion. Under JPEG or WEBP — both offered by the import
        # UI — the COG has discarded detail the upload carried, which makes the
        # upload the only lossless copy in existence and deleting it data loss.
        # So the delete is gated on the resolved conversion, and the retention
        # purge owns the retained object exactly as it does on the failure path.
        #
        # failed_source_replayable=True is Decision 7's other exception: a
        # failed conversion leaves those bytes as the operator's only diagnostic
        # copy. It is now redundant with the gate (a failure never sets the flag)
        # and kept because it states the intent independently. RUNBOOK.md
        # section 9 states both windows for operators.
        if source_preserved_in_cog or lossy_original_archived:
            await reap_downloaded_staging_source(
                job_id,
                original_file_path=original_file_path,
                final_status=final_status,
                failed_source_replayable=True,
            )
