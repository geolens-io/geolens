"""Procrastinate task definitions for raster/COG file ingestion."""

import uuid

import structlog
from sqlalchemy.exc import DBAPIError

from app.core.failure_reason import FixedReason, redact_failure_reason
from app.core.db.tenant_session import tenant_task
from app.platform.jobs import ledger
from app.platform.jobs.heartbeat import (
    JOB_ERROR_WRITE_TIMEOUT_MS,
    claim_job_attempt_and_start_heartbeat,
    log_job_error_write_failure,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
)
from app.processing.raster.cog import (
    MissingRasterCrsError,
    _scratch_dir,
    check_and_prepare_cog,
    cog_preserves_source,
    resolve_crs_assignment,
    sha256_file,
)
from app.processing.raster.probe import read_raster_metadata, render_quicklook

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
    inspect_source_raster,
    publish_commit_landed,
    publishing_xid,
    record_unpublished_storage_keys,
)
from app.processing.ingest.publish_followups import (
    note_publish_followups,
    run_publish_followups,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    cleanup_step,
    _job_phase_session,
    _parse_temporal_fields,
    apply_manifest_record_metadata,
    task_app,
)
from app.processing.ingest.tasks_staging import (
    _validate_upload_file_safety,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
)


def _raster_ingest_failure_reason(exc: BaseException) -> str | BaseException:
    """The job's stored reason for a raster-ingest failure.

    A missing CRS is a stable reason a client can localize, not an
    exception's own text; the raster text differs from the vector gate's,
    so it carries its own code.
    """
    if isinstance(exc, MissingRasterCrsError):
        return FixedReason(str(exc), code="missing_crs_raster")
    return exc


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

    The AsyncSession is split into short-lived blocks so it is not held open
    across the CPU work in steps 4-8 (each runs via ``asyncio.to_thread``):
    holding one open there corrupts the greenlet bridge state and the next
    ``session.flush()`` raises ``MissingGreenlet``.
    """
    _bind_task_log_context(task_name="ingest_raster", job_id=job_id)
    import asyncio
    import io
    import os
    import shutil
    import tempfile
    from pathlib import Path as _Path

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
    # False until a conversion is known to have kept every sample. Decision 7's
    # delete is licensed by that fact alone, so the default retains.
    source_preserved_in_cog: bool = False
    # Set when a lossy conversion's original has been copied to the durable
    # `originals/` prefix. Until then the staged upload is the only faithful
    # copy and nothing may delete it.
    lossy_original_archived: bool = False
    owned_staging_key: str | None = None
    # Storage keys written before the terminal commit. If the commit (or any
    # step after the puts) fails, the dataset row is rolled back and
    # delete_dataset never reaps these, so the failure path deletes them.
    written_storage_keys: list[str] = []
    # "The COG and quicklooks are published", set at the terminal commit and
    # nowhere else. The reap keys off this rather than `final_status`, which
    # the broad handler sets to "failed" even after the publish was durable.
    publish_committed: bool = False
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        # Phase 1: load the job, mark it running, validate, and snapshot what
        # the CPU work needs, so phase 2 doesn't depend on attached ORM state
        # surviving the asyncio.to_thread calls.
        async with _job_phase_session(
            job_uuid, phase="phase1", attempt_id=attempt_uuid
        ) as (session, job):
            if job is None:
                return

            # Captured first, so no exit below (heartbeat-claim bail, download
            # failure, validation return) can skip reaping the staging object.
            # Reads the DB column, not the local `file_path` step 2 rebinds.
            owned_staging_key = owned_presigned_staging_key(
                job.id, job.user_metadata, job.file_path
            )

            # 1. Mark running. The "validating" stamp rides the claim commit,
            # so a 10-minute COG conversion doesn't look like a dead spinner.
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid, job=job, current_step="validating"
            )
            if heartbeat_task is None:
                return

            # 2. Resolve file path
            from app.processing.ingest.service import resolve_file_path

            file_path = await resolve_file_path(file_path, job_id)

            # 3. Validate file content and size.
            try:
                await _validate_upload_file_safety(
                    session,
                    file_path=file_path,
                    source_filename=job.source_filename,
                )
            except ValueError as exc:
                await ledger.fail(session, job_uuid, attempt_uuid, reason=exc)
                await session.commit()
                # No unlink here: on local storage this may be the only copy.
                # The terminal `finally` decides, and runs on this return.
                final_status = "failed"
                # After the commit, so a notification error cannot alter the
                # terminal job write.
                _early_reason = redact_failure_reason(exc)
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

            um: dict = job.user_metadata or {}
            source_filename: str | None = job.source_filename
            _reject_raw_vrt_job(source_filename)
            is_manifest_vrt = _is_manifest_vrt_job(job)

        # CPU work, with no session open (see the docstring).

        # 4. Hash source file
        source_sha256 = await asyncio.to_thread(sha256_file, file_path)

        assign_crs = um.get("srid_override")
        user_compression = um.get("compression") or "DEFLATE"

        # 5. Inspect the source in the probe child. Its metadata decides only
        # whether a CRS assignment is needed and `original_srid`; everything
        # the catalog stores describes the COG. Its compliance verdict,
        # against the requested compression, feeds the strict gate and the
        # conversion.
        source_inspection = await asyncio.to_thread(
            inspect_source_raster,
            file_path,
            original_filename=source_filename,
            expected_compression=user_compression,
        )
        source_meta = source_inspection["metadata"]
        user_resampling = um.get("resampling") or None
        user_nodata = um.get("nodata_override")
        # Derived from the raster, not an upload-time stamp, so an
        # srid_override applies on every upload path. One rule, shared with the
        # replace tail: a supplied EPSG applies even when the source declares a
        # CRS.
        assign_crs = resolve_crs_assignment(
            crs_wkt=source_meta.get("crs_wkt"), srid_override=assign_crs
        )

        # strict_cog rejects a non-COG TIFF instead of converting it.
        # Manifest-VRT jobs are excluded: a VRT is XML, and the COG compliance
        # check would fail for unrelated reasons.
        _enforce_strict_cog(
            source_inspection,
            is_manifest_vrt=is_manifest_vrt,
            strict_cog=bool(um.get("strict_cog")),
        )

        # Before the branch, so manifest-VRT (which skips the COG work) still
        # advances the UI. A brief session, closed before the CPU work.
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
            # 6. Check/convert to COG. Disk space first: the output can reach
            # ~3x the source (decompressed + tiled + overviews), and a full disk
            # fails with an opaque IOError and may leave concurrent ingests
            # half-converted. On the staging volume, because mkdtemp()'s /tmp
            # is a 512 MB RAM-backed tmpfs in the worker container.
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
                inspection=source_inspection,
                compression=user_compression,
                resampling=user_resampling,
                nodata=user_nodata,
                assign_crs=assign_crs,
            )
        assert local_cog_path is not None  # check_and_prepare_cog always returns a path
        # Resolved state, not the request field: the branch above may not
        # convert at all, and a verified COG loses nothing whatever its codec.
        # An override needs no `reprojected=`: `gdal_translate -a_srs`
        # relabels and resamples nothing.
        source_preserved_in_cog = cog_preserves_source(cog_status, user_compression)

        # Read the artifact that will serve: the pre-conversion read describes
        # a different file (the codec differs; under an override the CRS and
        # footprint do too). A CRS assignment keeps the pixel grid and corner
        # numbers, so reading the COG interprets them in the assigned CRS.
        cog_meta = (
            source_meta
            if local_cog_path == file_path
            else await asyncio.to_thread(read_raster_metadata, local_cog_path)
        )

        # 7. Hash COG
        asset_sha256 = await asyncio.to_thread(sha256_file, local_cog_path)
        cog_size = os.path.getsize(local_cog_path)

        # The dataset id is decided here rather than by the phase-2 INSERT,
        # because the object keys embed it and the durable job row must name
        # them before the transaction that could roll that id away opens.
        planned_dataset_id = uuid.uuid4()
        _base_key = f"rasters/{planned_dataset_id}/{asset_sha256}"
        _unpublished_keys = [
            f"{_base_key}/source.vrt"
            if is_manifest_vrt
            else f"{_base_key}/source.cog.tif",
            f"{_base_key}/quicklook_256.png",
            f"{_base_key}/quicklook_512.png",
            # The kept original of a lossy conversion. The dataset id is new,
            # so this attempt is its only writer, unlike the replace tail,
            # where the key can already hold an earlier upload's archive.
            archived_original_uri(planned_dataset_id, source_sha256=source_sha256),
        ]
        if not await record_unpublished_storage_keys(
            job_uuid,
            attempt_uuid,
            keys=_unpublished_keys,
            # Every key above is under a dataset id generated here, so no row
            # can name one. (The replace tail passes the live asset's keys,
            # since an identical re-upload derives the same content hash.)
            already_published=(),
            # Generated per task invocation, so a retry cannot reproduce a key:
            # this tail's attempt fence. The replace tail has a fixed dataset
            # id and uses its attempt id instead.
            attempt_scope=str(planned_dataset_id),
            job_id=job_id,
            task="ingest_raster",
        ):
            # A confirmed fence miss. Stopping here keeps the recorder's
            # contract ("do not write what nothing records") without relying
            # on phase 2's own fence, and skips the quicklooks.
            return

        # Quicklook generation is the other multi-second hotspot, so the UI
        # advances first.
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
        ql256 = await asyncio.to_thread(render_quicklook, local_cog_path, 256)
        ql512 = await asyncio.to_thread(render_quicklook, local_cog_path, 512)

        # Phase 2: create DB records, store assets, commit the job.
        # require_status="running" because this phase puts objects to storage,
        # which no rollback can undo, so a paused-not-dead worker must not
        # resume here.
        async with _job_phase_session(
            job_uuid,
            phase="phase2",
            attempt_id=attempt_uuid,
            require_status="running",
        ) as (session, job):
            if job is None:
                return

            # Uncommitted, so a phase-2 failure rolls it back too; the
            # "quicklook" write above is the durable mid-flight checkpoint.
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

            # The manifest's credit line, for both branches: neither
            # create_*_dataset takes the field.
            await apply_manifest_record_metadata(session, record, um)

            # 9b. Set temporal fields on Record.
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

            # The fail-closed seam serve/delete/presign use. The ORM fields
            # below keep the logical keys.
            (
                _storage_cog_key,
                _storage_ql256_key,
                _storage_ql512_key,
            ) = _resolve_managed_raster_storage_keys(
                cog_key,
                ql256_key,
                ql512_key,
            )

            # Each key is recorded before its put: a cancelled put can still
            # have completed (both providers drain their thread before
            # re-raising CancelledError, a BaseException), and an append after
            # it would leave the object with nothing naming it. Reaping a key
            # the write never created is a no-op.
            written_storage_keys.append(_storage_cog_key)
            with open(local_cog_path, "rb") as fobj:
                await storage.put(_storage_cog_key, fobj)
            written_storage_keys.append(_storage_ql256_key)
            await storage.put(_storage_ql256_key, io.BytesIO(ql256))
            written_storage_keys.append(_storage_ql512_key)
            await storage.put(_storage_ql512_key, io.BytesIO(ql512))

            # 11. Update asset URIs and create distribution. asset_uri keeps
            # the logical key; resolve_open_path adds the tenant prefix at
            # serve time.
            raster_asset.asset_uri = cog_key
            raster_asset.quicklook_256_uri = ql256_key
            raster_asset.quicklook_512_uri = ql512_key
            await session.flush()

            # The STAC-aligned dataset_assets rows `_build_stac_assets` reads,
            # in this transaction, so item assets are advertised (data/vrt +
            # thumbnail + overview). On local storage they resolve to None; on
            # S3 they become presigned hrefs.
            from app.platform.extensions import (
                get_catalog_port,
                get_processing_port as _get_port,
            )

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

            # The replace tail's policy, through the same helper. ADR-002
            # Decision 7's retained original lives under
            # `originals/<dataset_id>/`, which `delete_dataset` reaps and no
            # purge touches, with a counted `dataset_assets` row so per-user
            # storage sees its bytes.
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
            # The helper registers the key itself, before the cancellable write.
            _archive_asset_key = (
                archived_original_asset_key(source_sha256) if archived_key else None
            )
            # Before the upsert: `create_raster_dataset` reserved only the COG,
            # and reserving after the row is written would count the original
            # twice in the live recount and refuse an ingest that fits
            # (`test_both_tails_reserve_before_they_upsert`).
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

            # 12. Finalize job. ``rows_processed`` stays NULL: a raster has no
            # rows.
            await note_publish_followups(
                session,
                job_uuid,
                attempt_uuid,
                "ingest_raster",
                reaps_staged_upload=source_preserved_in_cog or lossy_original_archived,
            )
            await ledger.complete(
                session,
                job_uuid,
                attempt_uuid,
                values={
                    "dataset_id": dataset.id,
                    "current_step": "complete",
                    "progress": 1.0,
                },
            )
            xid = publishing_xid(session)
            try:
                await session.commit()
            except BaseException as exc:
                # The one await whose outcome is unknown (see
                # `publish_commit_landed`): after a lost acknowledgement the
                # reap below would delete the COG and quicklooks the committed
                # RasterAsset points at.
                if not await publish_commit_landed(
                    job_uuid,
                    attempt_uuid,
                    xid=xid,
                    error=exc,
                    job_id=job_id,
                    task="ingest_raster",
                ):
                    raise
                # Stand down: the dataset may be live, and the handler below
                # would mail `ingest_failed` for it. `final_status` stays
                # non-complete, so the cleanup below keeps the staged original;
                # the follow-ups delete it once the publish is visible, whether
                # they run here or from the sweep.
                publish_committed = True
                absorb_cancellation(exc)
                await run_publish_followups(job_uuid)
                return
            publish_committed = True
            final_status = "complete"

            await run_publish_followups(job_uuid)

    except Exception as exc:  # broad: raster ingest spans GDAL/COG/Titiler — any step can fail; record failure
        if publish_committed:
            # The post-commit follow-ups run inside the same try, so a Valkey
            # outage or a busy queue lands here after the dataset is live.
            # Everything below would say the ingest failed; log and finish.
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
        # A fresh session: phase 1/2 sessions are closed or rolled back. The
        # budget covers the UPDATE, the statement that blocks on a contended
        # job row. An expiry leaves the job `running` for the stale sweep; the
        # handler below keeps the cause as the outcome.
        try:
            async with _job_phase_session(
                job_uuid,
                phase="error_write",
                attempt_id=attempt_uuid,
                lock_and_statement_timeout_ms=JOB_ERROR_WRITE_TIMEOUT_MS,
            ) as (
                err_session,
                _err_job,
            ):
                reason = _raster_ingest_failure_reason(exc)
                await ledger.fail(err_session, job_uuid, attempt_uuid, reason=reason)
                await err_session.commit()
        except DBAPIError as write_failure:
            # Swallowed so the `raise` below re-raises the ingest failure rather
            # than a lock timeout, and the notification still runs.
            log_job_error_write_failure(
                write_failure, job_id=job_id, task="ingest_raster"
            )
        finally:
            # The `finally` reapers gate on this, and the bounded error write
            # above can raise past a positional assignment.
            final_status = "failed"
        # After the attempted terminal write, so a notification error cannot
        # roll back a committed failed status; if that write raised
        # DBAPIError, the job may still read running.
        _late_reason = redact_failure_reason(exc)
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
        async with cleanup_step("ingest_raster heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        # Without a terminal commit the dataset row these keys belong to was
        # rolled back, and delete_dataset will never reap them.
        async with cleanup_step("ingest_raster orphaned storage keys", job_id=job_id):
            if not publish_committed and written_storage_keys:
                await _cleanup_orphaned_storage_keys(
                    written_storage_keys, job_id=job_id
                )
        async with cleanup_step("ingest_raster temp dir", job_id=job_id):
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        # A path that differs from `original_file_path` is a scratch copy
        # downloaded from object storage. An equal one is the durable original
        # (local uploads land in the persistent `upload_staging` volume), so it
        # gets the object-store reaper's retention gate.
        async with cleanup_step("ingest_raster local file", job_id=job_id):
            if file_path != original_file_path:
                _Path(file_path).unlink(missing_ok=True)
            elif final_status == "complete" and (
                source_preserved_in_cog or lossy_original_archived
            ):
                _Path(file_path).unlink(missing_ok=True)
        async with cleanup_step(
            "ingest_raster presigned staging object", job_id=job_id
        ):
            await reap_presigned_staging_object(
                job_id, owned_staging_key, final_status=final_status
            )
        # ADR-002 Decision 7: the pre-conversion source object.
        # `final_status == "complete"` is reached only after the COG is
        # written, read and committed. Under JPEG/WEBP the COG discards detail,
        # making the upload the only lossless copy, so the delete is gated on
        # the resolved conversion, not on conversion having happened.
        # `failed_source_replayable=True`: a failed conversion leaves those
        # bytes as the operator's only diagnostic copy.
        async with cleanup_step("ingest_raster downloaded source", job_id=job_id):
            if source_preserved_in_cog or lossy_original_archived:
                await reap_downloaded_staging_source(
                    job_id,
                    original_file_path=original_file_path,
                    final_status=final_status,
                    failed_source_replayable=True,
                )
