"""Procrastinate task definitions for vector file and service ingestion."""

import asyncio
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import or_, text, update
from sqlalchemy.exc import DBAPIError

from app.core.db.tenant_session import tenant_task
from app.core.failure_reason import redact_failure_reason
from app.core.url_redaction import scrub_secret_from_exception
from app.platform.dataset_origin import service_layer_identity
from app.platform.jobs.heartbeat import (
    JOB_ERROR_WRITE_TIMEOUT_MS,
    attempt_scoped_staging_table,
    claim_job_attempt_and_start_heartbeat,
    log_job_error_write_failure,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    update_ingest_job_for_attempt,
    stop_ingest_job_heartbeat,
)
from app.processing.ingest.metadata import _qtable
from app.processing.ingest.source_format import derive_source_format
from app.processing.ingest.tasks_common import (
    IngestContext,
    cleanup_step,
    _append_job_warning,
    _bind_task_log_context,
    _current_tenant_schema,
    _detect_and_override_geometry,
    _emit_billing_event,
    _finalize_ingest,
    _job_phase_session,
    _resolve_effective_srid,
    _run_service_import_with_wfs_fallback,
    purge_token_on_failure,
    rename_pkey_to_match_table,
    resolve_service_type,
    task_app,
)
from app.processing.ingest.tasks_staging import (
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
    _archive_original_file,
    _cleanup_staging_on_failure,
    _validate_upload_file_safety,
)
from app.platform.jobs.models import owned_presigned_staging_key


_SERVICE_IMPORT_INITIAL_PROGRESS = 0.1
_SERVICE_IMPORT_HEARTBEAT_INTERVAL_SECONDS = 5.0
_SERVICE_IMPORT_HEARTBEAT_INCREMENT = 0.05
_SERVICE_IMPORT_HEARTBEAT_MAX_PROGRESS = 0.65
# Bound each heartbeat transaction inside PostgreSQL so a blocked commit
# releases its connection instead of exhausting the pool.
_SERVICE_IMPORT_HEARTBEAT_TICK_DB_TIMEOUT_SECONDS = 3.0
# This outer timeout covers failures before PostgreSQL can apply its limits,
# such as a connection stalled by a network partition.
_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS = 10.0
_ARCGIS_SERVICE_IMPORT_CHUNK_SIZE = 2000


async def _publish_attempt_staging_table(
    session,
    *,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    staging_table: str,
    live_table: str,
) -> None:
    """Publish one attempt's physical table while holding its job-row lease."""
    await require_ingest_job_update(
        session,
        job_id,
        attempt_id,
        values={"heartbeat_at": datetime.now(timezone.utc)},
    )
    await session.execute(
        text(
            f"ALTER TABLE {_qtable(staging_table, schema=_current_tenant_schema())} "
            f'RENAME TO "{live_table}"'
        )
    )
    # RENAME TO keeps the staging-era pkey name; fix it while we hold the lock.
    await rename_pkey_to_match_table(session, live_table)


async def _drop_attempt_staging_table(staging_table: str) -> None:
    """Best-effort cleanup limited to the caller's attempt-owned table."""
    if not staging_table:
        return

    from app.core.db import async_session

    try:
        async with async_session() as session:
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS "
                    f"{_qtable(staging_table, schema=_current_tenant_schema())} CASCADE"
                )
            )
            await session.commit()
    except Exception:  # broad: cleanup must not mask the ingest result
        structlog.get_logger().warning(
            "attempt_staging_cleanup_failed",
            staging_table=staging_table,
            exc_info=True,
        )


async def _service_import_heartbeat_tick(
    job_uuid: uuid.UUID, attempt_id: uuid.UUID
) -> bool:
    """One heartbeat write: open a session, advance progress, commit, close.

    Returns ``False`` when the caller's loop must stop (job vanished, or
    moved off the step this heartbeat belongs to), ``True`` otherwise. Split
    out of ``_heartbeat_service_import_progress`` so that function can
    ``shield`` the whole tick from cancellation — see its
    docstring.

    Passes ``lock_timeout``/``statement_timeout`` INTO
    ``_job_phase_session`` (``lock_and_statement_timeout_ms``) rather than
    setting them after entering it, so they also cover the SELECT the
    helper runs internally — a SELECT can itself stall behind a lock the
    later UPDATE would never see. A blocked commit then raises inside
    Postgres within seconds; ``_job_phase_session``'s rollback-and-reraise
    releases the connection normally rather than leaving the caller to
    choose between waiting forever or abandoning it.

    The earlier SELECT is a snapshot, not a lock. If this
    tick's own connection then stalls for a reason the DB timeout doesn't
    catch (e.g. before it reaches Postgres) past the caller's cancellation
    drain, the caller moves on while this shielded tick keeps running in
    the background — meanwhile ``_finalize_ingest`` could commit
    ``status="complete"`` or a retry could rotate ``attempt_id``. So the
    UPDATE below re-checks every fact atomically in its own WHERE clause
    (same attempt still owns the row, still "running"/"ogr2ogr", and
    CURRENT progress still below what's about to be written) instead of
    trusting the earlier read. Zero rows affected means the job moved on:
    log and do nothing.
    """
    from app.platform.jobs.models import IngestJob

    _timeout_ms = int(_SERVICE_IMPORT_HEARTBEAT_TICK_DB_TIMEOUT_SECONDS * 1000)
    async with _job_phase_session(
        job_uuid,
        phase="service_import_heartbeat",
        attempt_id=attempt_id,
        lock_and_statement_timeout_ms=_timeout_ms,
    ) as (session, job):
        if job is None:
            return False
        if job.status != "running" or job.current_step != "ogr2ogr":
            return False

        existing_progress = (
            job.progress
            if job.progress is not None
            else _SERVICE_IMPORT_INITIAL_PROGRESS
        )
        next_progress = min(
            _SERVICE_IMPORT_HEARTBEAT_MAX_PROGRESS,
            existing_progress + _SERVICE_IMPORT_HEARTBEAT_INCREMENT,
        )
        if next_progress <= existing_progress:
            return True

        result = await session.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job_uuid,
                IngestJob.attempt_id == attempt_id,
                IngestJob.status == "running",
                IngestJob.current_step == "ogr2ogr",
                or_(
                    IngestJob.progress.is_(None),
                    IngestJob.progress < next_progress,
                ),
            )
            .values(progress=next_progress)
        )
        await session.commit()
        if not result.rowcount:  # type: ignore[attr-defined]
            structlog.get_logger().debug(
                "service_import_heartbeat_tick_stale",
                job_id=str(job_uuid),
                attempt_id=str(attempt_id),
            )
        return True


async def _heartbeat_service_import_progress(
    job_uuid: uuid.UUID, attempt_id: uuid.UUID
) -> None:
    """Advance service-ingest progress while GDAL loads remote features.

    Each tick runs under ``asyncio.shield`` so the caller's
    ``.cancel()`` can only land at the ``asyncio.sleep`` below, never
    mid-connect/write/close on the tick's own session. Without this, a
    cancel landing inside asyncpg's connection teardown left the
    connection outliving its coroutine, surfacing later against unrelated
    work as ``ConnectionError: unexpected connection_lost() call``.
    Shielding costs at most one tick's worth of extra shutdown latency.

    The ``_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS``
    drain that lets a shielded tick finish is a SAFETY NET, not the
    primary bound — that's the tick's own DB-side ``lock_timeout``/
    ``statement_timeout`` (see ``_service_import_heartbeat_tick``), which
    resolves the common case well inside this window. The drain timeout
    only covers what a DB-side timeout can't: a connection stuck before it
    ever reaches Postgres. The tick still isn't cancelled on that rarer
    timeout — the caller just moves on while it finishes in the
    background — since the heartbeat write is best-effort progress UI
    sugar the import's own result never reads back.
    """
    while True:
        await asyncio.sleep(_SERVICE_IMPORT_HEARTBEAT_INTERVAL_SECONDS)
        tick = asyncio.ensure_future(
            _service_import_heartbeat_tick(job_uuid, attempt_id)
        )
        try:
            try:
                keep_going = await asyncio.shield(tick)
            except asyncio.CancelledError:
                # Give an already-open tick bounded time to close its connection.
                # Shielding stops this wait without cancelling the tick itself.
                if not tick.done():
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(tick),
                            timeout=_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        # The database timeout did not engage, usually because
                        # the connection never reached PostgreSQL.
                        structlog.get_logger().warning(
                            "service_import_heartbeat_drain_timed_out",
                            job_id=str(job_uuid),
                            timeout=_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS,
                        )
                    except BaseException:  # broad: draining an already-shielded tick's own connection cleanup; whatever it raises must not replace the pending cancellation `raise` below
                        pass
                raise
        except Exception:  # broad: best-effort heartbeat must not fail ingest
            # Heartbeat progress is best-effort and must not mask ingest work.
            structlog.get_logger().warning(
                "service_import_progress_heartbeat_failed",
                job_id=str(job_uuid),
                exc_info=True,
            )
            continue

        if not keep_going:
            return


async def _write_service_import_progress(
    job_uuid: uuid.UUID,
    attempt_id: uuid.UUID,
    *,
    imported_rows: int,
    feature_count: int,
) -> None:
    if feature_count <= 0:
        return

    completed_ratio = min(1.0, imported_rows / feature_count)
    next_progress = min(
        _SERVICE_IMPORT_HEARTBEAT_MAX_PROGRESS,
        _SERVICE_IMPORT_INITIAL_PROGRESS
        + (_SERVICE_IMPORT_HEARTBEAT_MAX_PROGRESS - _SERVICE_IMPORT_INITIAL_PROGRESS)
        * completed_ratio,
    )

    async with _job_phase_session(
        job_uuid, phase="service_import_chunk_progress", attempt_id=attempt_id
    ) as (
        session,
        job,
    ):
        if job is None:
            return
        if job.status != "running" or job.current_step != "ogr2ogr":
            return
        existing_progress = (
            job.progress
            if job.progress is not None
            else _SERVICE_IMPORT_INITIAL_PROGRESS
        )
        if next_progress <= existing_progress:
            return
        job.progress = next_progress
        await session.commit()


async def _fetch_arcgis_import_page_info(
    source_url: str, layer_id: int | str | None, token: str | None
) -> tuple[int | None, int | None, bool, str | None]:
    if layer_id is None:
        return None, None, False, None

    from app.modules.catalog.sources.adapters.arcgis import (
        ArcGISTokenError,
        fetch_arcgis_feature_count,
        fetch_arcgis_pagination_info,
    )
    from app.platform.security import make_safe_client
    from app.processing.ingest.ogr import IngestionError

    try:
        async with make_safe_client(timeout=30.0) as client:
            (
                max_record_count,
                supports_pagination,
                order_field,
            ) = await fetch_arcgis_pagination_info(
                source_url, layer_id, client, token=token
            )
            if (
                not supports_pagination
                or max_record_count is None
                or order_field is None
            ):
                return None, max_record_count, supports_pagination, order_field
            feature_count = await fetch_arcgis_feature_count(
                source_url, layer_id, client, token=token
            )
            return feature_count, max_record_count, supports_pagination, order_field
    except ArcGISTokenError as exc:
        raise IngestionError(str(exc)) from exc
    except Exception as exc:  # broad: count is an optimization; import can fall back
        structlog.get_logger().warning(
            "arcgis_import_page_info_fetch_failed",
            source_url=source_url,
            layer_id=str(layer_id),
            error=str(exc),
        )
        return None, None, False, None


def _should_unlink_staging(
    *,
    file_path: str,
    original_file_path: str,
    final_status: str,
    is_fan_out_child: bool,
) -> bool:
    """Decide whether the local staging file should be unlinked on task exit.

    Three cases:
      - Per-child S3 download (``file_path != original_file_path``): a private
        copy resolved by ``resolve_file_path`` as ``{job_id}_{name}``. No
        sibling shares it, so it is always safe to unlink — including for
        fan-out children and on failure because S3 is the source of truth.
      - Shared local-staging file (``file_path == original_file_path``) of a
        fan-out child: NEVER unlink — siblings read the same file; the staging
        retention policy reaps it later.
      - Shared local-staging file of a non-fan-out job: unlink only on success;
        keep on failure so a retry can re-read it.
    """
    is_private_s3_download = file_path != original_file_path
    if is_private_s3_download:
        return True
    if is_fan_out_child:
        return False
    return final_status == "complete"


@task_app.task(queue="ingest", retry=0, aliases=["app.ingest.tasks.ingest_file"])
@tenant_task
async def ingest_file(
    job_id: str,
    file_path: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: run ogr2ogr, extract metadata, register dataset.

    Full pipeline:
    1. Update job status to running
    2. Run ogrinfo to detect CRS
    3. Run ogr2ogr to load file into PostGIS
    4. Add geom_4326 column via ST_Transform
    5. Grant geolens_reader SELECT access
    6. Extract metadata (extent, columns, row count, geometry type)
    7. Create Dataset record in catalog
    8. Update job status to complete
    9. Clean up staging file

    Keep sessions closed during ``run_ogr2ogr``: holding one across the
    subprocess can leave the next database operation raising ``MissingGreenlet``.
    """
    _bind_task_log_context(task_name="ingest_file", job_id=job_id)
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo
    from app.processing.ingest.service import generate_table_name

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="ingest"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    original_file_path = file_path
    final_status: str = "pending"
    staging_table_name = ""
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 uses a short-lived session to load the job, mark it running,
        # validate it, detect CRS, and generate the
        # table name. Snapshot values needed for phase 2 into local
        # variables so the ogr2ogr subprocess can run without a session
        # held open.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(
            job_uuid, phase="phase1", attempt_id=attempt_uuid
        ) as (session, job):
            if job is None:
                return

            # Update the job and its validating step in the same commit.
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid, job=job, current_step="validating"
            )
            if heartbeat_task is None:
                return

            # Resolve S3 key to local file for ogr2ogr
            from app.processing.ingest.service import resolve_file_path

            file_path = await resolve_file_path(file_path, job_id)

            # Validate file content and safety before ogr2ogr.
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
                        "error_message": redact_failure_reason(exc),
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
                await session.commit()
                # Let final cleanup distinguish staging from the only managed
                # copy, which must survive validation failure for a retry.
                final_status = "failed"
                return

            # Check for user-supplied metadata from commit step
            um = job.user_metadata or {}
            srid_override = um.get("srid_override")
            layer_name = um.get("layer_name")
            source_filename = job.source_filename

            # 2. Detect CRS via ogrinfo
            info = await run_ogrinfo(
                file_path, layer_name=layer_name, original_filename=source_filename
            )
            srid = info.get("srid")
            geometry_type = info.get("geometry_type")
            has_geometry = geometry_type is not None

            # Check for missing CRS (CSV and GeoJSON default to EPSG:4326)
            # Non-spatial files don't need CRS at all
            from app.processing.ingest.tasks_common import ASSUMES_4326_SUFFIXES

            assumes_4326 = file_path.lower().endswith(ASSUMES_4326_SUFFIXES)
            if (
                has_geometry
                and srid is None
                and not assumes_4326
                and srid_override is None
            ):
                await update_ingest_job_for_attempt(
                    session,
                    job_uuid,
                    attempt_uuid,
                    values={
                        "status": "failed",
                        "error_message": (
                            "Missing CRS: no coordinate system detected. "
                            "Ensure the file includes CRS information "
                            "(e.g., .prj file for Shapefiles)."
                        ),
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
                await session.commit()
                final_status = "failed"
                return

            # 3. Generate table name
            dataset_name = um.get("title") or source_filename or "dataset"
            table_name, collision_warning = await generate_table_name(
                dataset_name, session
            )
            staging_table_name = attempt_scoped_staging_table(table_name, attempt_uuid)
            if collision_warning:
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "collision_warning": collision_warning,
                }
                await session.commit()

        # ----------------------------------------------------------------- #
        # ogr2ogr subprocess — NO session open. ogr2ogr writes to PostgreSQL
        # via its own libpq connection (db_conn_str), independent of the
        # SQLAlchemy session. Holding a session open across this subprocess
        # can corrupt SQLAlchemy's greenlet bridge.
        # ----------------------------------------------------------------- #
        db_conn_str = build_pg_conn_str()

        # Check for user-specified geometry columns (override)
        # Lowercase column names: ogr2ogr lowercases them in PostGIS.
        # The individual column values are re-derived inside
        # ``_detect_and_override_geometry`` from ``um``, so we only need
        # the boolean here to gate the import-as-non-spatial branch.
        user_wants_geom = bool(
            ((um.get("x_column") or "") and (um.get("y_column") or ""))
            or (um.get("geom_column") or "")
        )

        # When user specifies geometry columns, import as non-spatial
        # then construct geometry post-import. This ensures the override
        # works even for CSVs where GDAL would auto-detect geometry.
        ogr_geometry_type = None if user_wants_geom else geometry_type
        effective_srid = _resolve_effective_srid(
            detected_srid=srid,
            srid_override=srid_override,
        )

        # Write current_step="ogr2ogr" before the long subprocess so the UI
        # sees the transition even if ogr2ogr hangs. A brief session avoids
        # holding a session open across run_ogr2ogr,
        # but the progress write must commit so it cannot be lost on
        # rollback if ogr2ogr raises.
        async with _job_phase_session(
            job_uuid, phase="progress_write_ogr2ogr", attempt_id=attempt_uuid
        ) as (
            _progress_session,
            _progress_job,
        ):
            if _progress_job is not None:
                _progress_job.current_step = "ogr2ogr"
                _progress_job.progress = 0.1
                await _progress_session.commit()

        await run_ogr2ogr(
            file_path,
            staging_table_name,
            db_conn_str,
            source_srid=srid,
            geometry_type=ogr_geometry_type,
            layer_name=layer_name,
            schema=_current_tenant_schema(),
            effective_srid=effective_srid,
            original_filename=source_filename,
        )

        # Resolve archive formats before phase 2 because ZIP inspection reads
        # the central directory.
        source_format = await asyncio.to_thread(derive_source_format, file_path)

        # Finalize in a fresh session using the snapshotted job attributes.
        # Requiring running status fences out attempts already failed by a sweep.
        async with _job_phase_session(
            job_uuid,
            phase="phase2",
            attempt_id=attempt_uuid,
            require_status="running",
        ) as (session, job):
            if job is None:
                return

            # This progress signal shares the finalization transaction; the
            # earlier ogr2ogr write is the durable checkpoint.
            job.current_step = "finalize"
            job.progress = 0.7

            # 3a. Rename any source column that collides with a GeoLens-internal
            #     name (gid, geom, geometry, geom_4326, fid, ogc_fid). Runs BEFORE
            #     the user-geometry-override and _finalize_ingest steps so that
            #     construct_point_geometry / add_4326_column cannot clash with a
            #     source attribute of the same name.
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(
                session, staging_table_name, schema=_current_tenant_schema()
            )
            if reserved_renames:
                from app.processing.ingest.warnings import (
                    make_reserved_rename_warning,
                )

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            # 3b. Shapefile-only: detect DBF 10-char truncation collisions using
            #     the source column list from ogrinfo (stored in info["columns"]).
            if source_format == "shapefile":
                from app.processing.ingest.metadata import (
                    detect_dbf_truncation_collisions,
                )
                from app.processing.ingest.ogr import run_ogrinfo_preview
                from app.processing.ingest.warnings import (
                    make_dbf_truncation_warning,
                )

                preview_cols = info.get("columns") or []
                if not preview_cols:
                    preview_info = await run_ogrinfo_preview(
                        file_path, sample_limit=0, layer_name=layer_name
                    )
                    preview_cols = preview_info.get("columns") or []
                dbf_collisions = detect_dbf_truncation_collisions(preview_cols)
                if dbf_collisions:
                    _append_job_warning(
                        job, make_dbf_truncation_warning(dbf_collisions)
                    )
                    structlog.get_logger().warning(
                        "Shapefile DBF 10-char truncation collision detected",
                        table=staging_table_name,
                        collisions=dbf_collisions,
                    )

            if user_wants_geom:
                override_geom_type = await _detect_and_override_geometry(
                    session,
                    table_name=staging_table_name,
                    user_metadata=um,
                    effective_srid=effective_srid,
                )
                if override_geom_type is not None:
                    has_geometry = True
                    geometry_type = override_geom_type

            # ogr2ogr writes only to an attempt-owned physical table. Acquire
            # the job row under the attempt predicate before publishing it;
            # the rename and _finalize_ingest's terminal update commit in the
            # same transaction, so a stale worker can never expose its table.
            await _publish_attempt_staging_table(
                session,
                job_id=job_uuid,
                attempt_id=attempt_uuid,
                staging_table=staging_table_name,
                live_table=table_name,
            )

            # 5-9. Shared post-ogr2ogr pipeline
            dataset = await _finalize_ingest(
                IngestContext(
                    session=session,
                    job=job,
                    table_name=table_name,
                    user_id=user_id,
                    has_geometry=has_geometry,
                    effective_srid=effective_srid,
                    source_format=source_format,
                    source_filename=source_filename,
                    original_srid=srid,
                    user_metadata=um,
                    attempt_id=attempt_uuid,
                    # No file_hash — it is computed on the
                    # re-upload path only, and the allowlist omits absent keys.
                    origin_ref={"filename": source_filename},
                )
            )

            # Archive the original file to the storage provider.
            await _archive_original_file(
                session,
                job=job,
                dataset_id=dataset.id,
                file_path=file_path,
            )

            # Billing is best-effort through the extension seam. Using job_id as
            # event_id keeps task retries idempotent.
            from app.core.db.tenant_session import current_tenant_var

            await _emit_billing_event(
                str(current_tenant_var.get()) if current_tenant_var.get() else None,
                "ingest_jobs",
                event_id=job_id,
            )

            final_status = "complete"

    except (
        Exception
    ) as exc:  # broad: pipeline spans GDAL/PostGIS/S3/FS — any step can fail
        # Record failure in a fresh session and emit the shared notification.
        # A concurrently deleted job has no row left to update.
        try:
            async with _job_phase_session(
                job_uuid,
                phase="error_write",
                attempt_id=attempt_uuid,
                lock_and_statement_timeout_ms=JOB_ERROR_WRITE_TIMEOUT_MS,
            ) as (
                err_session,
                err_job,
            ):
                if err_job is not None:
                    await _cleanup_staging_on_failure(
                        err_session,
                        staging_table=staging_table_name,
                        job=err_job,
                        exc=exc,
                        task_name="ingest_file",
                        attempt_id=attempt_uuid,
                    )
                else:
                    structlog.get_logger().exception(
                        "Ingest task failed",
                        job_id=job_id,
                        task="ingest_file",
                    )
        except DBAPIError as write_failure:
            # The budget covers the helper's own load, so
            # an expiry there arrives here. Swallowed for the reason the helper
            # swallows its UPDATE's: the cause below is the task's outcome.
            log_job_error_write_failure(
                write_failure, job_id=job_id, task="ingest_file"
            )
        finally:
            # The `finally` reapers gate on THIS
            # variable, so every exit from this handler sets it — the bounded
            # error write above can raise past a positional assignment.
            final_status = "failed"
        raise
    finally:
        async with cleanup_step("ingest_file heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("ingest_file staging table", job_id=job_id):
            await _drop_attempt_staging_table(staging_table_name)
        # Local-file cleanup decision: see `_should_unlink_staging`'s
        # docstring for the three cases.
        #
        # Default TRUE (treat unknown as fan-out child) so a
        # failed/absent lookup SKIPS destructive cleanup — deleting the
        # shared S3 staging original on a misdetected child would break
        # every sibling (retry=0). Cost: an orphan the retention policy reaps.
        is_fan_out_child = True
        # The presigned staging key, swept below.
        owned_staging_key: str | None = None
        try:
            # Route through _job_phase_session. The helper
            # yields the IngestJob row directly, so we just check user_metadata.
            async with _job_phase_session(
                job_uuid, phase="cleanup_check", attempt_id=attempt_uuid
            ) as (
                _check_session,
                _check_job,
            ):
                if _check_job is not None:
                    is_fan_out_child = bool(
                        (_check_job.user_metadata or {}).get("fan_out_parent_id")
                    )
                    owned_staging_key = owned_presigned_staging_key(
                        _check_job.id,
                        _check_job.user_metadata,
                        _check_job.file_path,
                    )
        except Exception:  # broad: cleanup decision is best-effort, never block completion on this query
            is_fan_out_child = True

        async with cleanup_step("ingest_file local file", job_id=job_id):
            if _should_unlink_staging(
                file_path=file_path,
                original_file_path=original_file_path,
                final_status=final_status,
                is_fan_out_child=is_fan_out_child,
            ):
                Path(file_path).unlink(missing_ok=True)

        # Shared with the reupload tail — after a
        # presigned completion this reaps the FROZEN copy the job is bound to.
        async with cleanup_step("ingest_file downloaded source", job_id=job_id):
            await reap_downloaded_staging_source(
                job_id,
                original_file_path=original_file_path,
                final_status=final_status,
                # Ordinary imports: a failed job stays retryable while its
                # source exists (_retry_capability), so retain on failure and
                # let the stale purge own it.
                failed_source_replayable=True,
                is_fan_out_child=is_fan_out_child,
            )

        # Sweep the presigned staging key too. The block
        # above only reaps `original_file_path`, which after a presigned
        # completion is the FROZEN copy — so the key the client still holds a
        # PUT URL for was never touched. Shared with the raster tail so the
        # two cannot drift.
        async with cleanup_step("ingest_file presigned staging object", job_id=job_id):
            await reap_presigned_staging_object(
                job_id, owned_staging_key, final_status=final_status
            )


@task_app.task(
    queue="ingest",
    retry=0,
    # The context is how the task learns its own queue-row id, so
    # a terminal failure can strip the raw token out of its own kwargs.
    pass_context=True,
    aliases=["app.ingest.tasks.ingest_service"],
)
@tenant_task
@purge_token_on_failure
async def ingest_service(
    job_id: str,
    source_url: str,
    source_layer: str,
    user_id: str,
    attempt_id: str | None = None,
    token: str | None = None,
    credential_ref: str | None = None,
    **kwargs,
) -> None:
    """Background task: import a remote service layer via ogr2ogr.

    ``credential_ref`` is a one-use reference redeemed exactly once below;
    ``token`` is the durable task argument, produced only when no shared
    credential store is configured. At most one is ever set — see
    ``resolve_worker_credential``/``resolve_dispatch_credential``.

    Pipeline: update job to running; determine service type; build GDAL
    source and run ogr2ogr; post-process (clip, geom_4326, grants,
    metadata, samples); create Dataset record; compute quality score;
    update job to complete.

    The session uses the same two-phase split as ``ingest_file`` —
    closed before the ogr2ogr subprocess runs, reopened for finalization,
    so the SQLAlchemy greenlet bridge never has to survive across it.
    """
    _bind_task_log_context(task_name="ingest_service", job_id=job_id)
    from app.platform.security import (
        SSRFError,
        validate_url_for_ssrf,
    )
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr_service
    from app.processing.ingest.service import generate_table_name
    from app.platform.refresh.credentials import resolve_worker_credential

    # Revalidate source_url at fetch time as defense in depth.
    # The route-level check at commit_import covers the preview→commit
    # TOCTOU, but manifest-path jobs skip that route entirely. This
    # second check ensures all service-URL fetches see fresh DNS.
    try:
        await validate_url_for_ssrf(source_url)
    except SSRFError as exc:
        raise RuntimeError(
            f"source_url failed safety check at worker fetch time: {exc}"
        ) from exc

    port = get_processing_port()
    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="ingest"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    staging_table_name = ""
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        # Phase 1 uses a short-lived session to load the job, mark it running,
        # generate the table name, and snapshot values needed for phase 2.
        async with _job_phase_session(
            job_uuid, phase="phase1", attempt_id=attempt_uuid
        ) as (session, job):
            if job is None:
                return

            # Mirror ingest_file's progress writes so the polling UI shows
            # step transitions for service
            # ingests too. The service path has the same step boundaries as
            # the file path (validating -> ogr2ogr -> finalize -> complete)
            # except there is no "archiving" — services don't archive originals.
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid, job=job, current_step="validating"
            )
            if heartbeat_task is None:
                return

            # 2. Determine service type from job metadata
            um = job.user_metadata or {}
            service_type_raw = um.get("service_type", "")
            layer_id = um.get("layer_id")
            service_type, source_format = resolve_service_type(service_type_raw)

            # Detect non-spatial tables from preview metadata stored at job creation.
            # When geometry_type is None/null/absent, the layer has no geometry —
            # skip geometry-specific ogr2ogr flags to preserve attribute columns.
            _preview_geom_type = um.get("geometry_type")
            is_non_spatial = _preview_geom_type is None

            # 3. Resolve service parameters
            object_id_field = um.get("object_id_field") or None

            # 4. Generate table name
            source_filename = job.source_filename
            dataset_name = um.get("title") or source_filename or "dataset"
            table_name, collision_warning = await generate_table_name(
                dataset_name, session
            )
            staging_table_name = attempt_scoped_staging_table(table_name, attempt_uuid)
            if collision_warning:
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "collision_warning": collision_warning,
                }
                await session.commit()

        # Redeem the one-use credential AFTER phase 1, not
        # before — a single-use secret must only be spent on an attempt
        # that's really going to run (phase 1's `claim_job_attempt_and_
        # start_heartbeat` returns None for a superseded one), and the
        # failure write below is fenced on `status == 'running'`, which
        # phase 1 sets; claiming before it would leave a
        # `credential_expired` failure unrecorded until the stale sweep.
        # Placed outside the phase-1 session so the store round trip
        # doesn't hold a DB session open.
        token = await resolve_worker_credential(token, credential_ref)

        # ogr2ogr subprocess — NO session open (would trigger MissingGreenlet).
        db_conn_str = build_pg_conn_str()

        # Stamp current_step="ogr2ogr" before the long remote-service fetch,
        # using the same brief-session pattern as ingest_file.
        async with _job_phase_session(
            job_uuid, phase="progress_write_ogr2ogr", attempt_id=attempt_uuid
        ) as (
            _progress_session,
            _progress_job,
        ):
            if _progress_job is not None:
                _progress_job.current_step = "ogr2ogr"
                _progress_job.progress = _SERVICE_IMPORT_INITIAL_PROGRESS
                await _progress_session.commit()

        # Retry WFS namespaces through the shared helper.
        async def _do_import(layer_name: str) -> None:
            feature_count = None
            page_size = _ARCGIS_SERVICE_IMPORT_CHUNK_SIZE
            supports_pagination = False
            pagination_order_field = None
            if service_type == "arcgis_featureserver":
                (
                    feature_count,
                    max_record_count,
                    supports_pagination,
                    pagination_order_field,
                ) = await _fetch_arcgis_import_page_info(source_url, layer_id, token)
                if max_record_count is not None:
                    page_size = max(1, min(page_size, max_record_count))

            if (
                service_type == "arcgis_featureserver"
                and supports_pagination
                and pagination_order_field is not None
                and feature_count is not None
                and feature_count > page_size
            ):
                # The shared guarded loop also serves refreshes; this import
                # supplies its per-page progress callback.
                async def _publish_page_progress(
                    imported_rows: int, total: int
                ) -> None:
                    await _write_service_import_progress(
                        job_uuid,
                        attempt_uuid,
                        imported_rows=imported_rows,
                        feature_count=total,
                    )

                from app.processing.ingest.tasks_common import (
                    run_paged_arcgis_service_fetch,
                )

                await run_paged_arcgis_service_fetch(
                    service_type_raw=service_type_raw,
                    service_type=service_type,
                    source_url=source_url,
                    layer_name=layer_name,
                    layer_id=layer_id,
                    token=token,
                    staging_table=staging_table_name,
                    db_conn_str=db_conn_str,
                    schema=_current_tenant_schema(),
                    feature_count=feature_count,
                    page_size=page_size,
                    order_field=pagination_order_field,
                    is_non_spatial=is_non_spatial,
                    on_page=_publish_page_progress,
                )
                return

            _src, _layer = port.build_gdal_source(
                service_type_raw,
                source_url,
                layer_name,
                layer_id,
                token=token,
                order_field=object_id_field,
            )
            await run_ogr2ogr_service(
                _src,
                _layer,
                staging_table_name,
                db_conn_str,
                service_type,
                token=token,
                is_non_spatial=is_non_spatial,
                schema=_current_tenant_schema(),
            )

        service_progress_task = asyncio.create_task(
            _heartbeat_service_import_progress(job_uuid, attempt_uuid)
        )
        try:
            await _run_service_import_with_wfs_fallback(
                _do_import, source_layer, token=token
            )
        finally:
            async with cleanup_step("ingest_service progress heartbeat", job_id=job_id):
                service_progress_task.cancel()
                with suppress(asyncio.CancelledError):
                    await service_progress_task

        # Requiring running status fences finalization against a failed attempt.
        async with _job_phase_session(
            job_uuid,
            phase="phase2",
            attempt_id=attempt_uuid,
            require_status="running",
        ) as (session, job):
            if job is None:
                return

            # Finalization owns the transaction, including this progress write.
            job.current_step = "finalize"
            job.progress = 0.7

            # 4a. Rename any source column that collides with a GeoLens-internal
            #     name. Runs BEFORE _finalize_ingest (which calls add_4326_column).
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(
                session, staging_table_name, schema=_current_tenant_schema()
            )
            if reserved_renames:
                from app.processing.ingest.warnings import (
                    make_reserved_rename_warning,
                )

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            # 5-8. Shared post-ogr2ogr pipeline
            dataset_source_url = (
                f"{source_url}/{layer_id}" if layer_id is not None else source_url
            )
            await _publish_attempt_staging_table(
                session,
                job_id=job_uuid,
                attempt_id=attempt_uuid,
                staging_table=staging_table_name,
                live_table=table_name,
            )
            await _finalize_ingest(
                IngestContext(
                    session=session,
                    job=job,
                    table_name=table_name,
                    user_id=user_id,
                    has_geometry=False if is_non_spatial else None,
                    effective_srid=None if is_non_spatial else 4326,
                    source_format=source_format,
                    source_filename=source_filename,
                    original_srid=None,
                    user_metadata=um,
                    source_url=dataset_source_url,
                    attempt_id=attempt_uuid,
                    # Keep the base URL and service-specific layer identifier
                    # separate so refresh can reconstruct the source after the
                    # ingest job expires.
                    origin_ref={
                        "service_type": source_format,
                        "url": source_url,
                        "layer_id": service_layer_identity(
                            source_format,
                            layer_id=layer_id,
                            layer_name=source_layer,
                        ),
                        # This records token use, not proof that the origin
                        # requires authentication; refresh probes without a
                        # token before refusing.
                        "auth_required": True if token else None,
                    },
                )
            )

            # Emit ingest billable event.
            from app.core.db.tenant_session import current_tenant_var

            await _emit_billing_event(
                str(current_tenant_var.get()) if current_tenant_var.get() else None,
                "ingest_jobs",
                event_id=job_id,
            )

    except Exception as exc:  # broad: PostGIS/DB ingest can fail at any step; mark job failed and re-raise
        # Scrub the exact claimed token from any echoed error; pattern-based
        # redaction cannot recognize arbitrary secret values. Mutate in place
        # so the exception class survives the bare re-raise.
        scrub_secret_from_exception(exc, token)
        # Record failure in a fresh session after exact-value scrubbing; the
        # shared helper adds pattern-based redaction and notification handling.
        try:
            async with _job_phase_session(
                job_uuid,
                phase="error_write",
                attempt_id=attempt_uuid,
                lock_and_statement_timeout_ms=JOB_ERROR_WRITE_TIMEOUT_MS,
            ) as (
                err_session,
                err_job,
            ):
                if err_job is not None:
                    await _cleanup_staging_on_failure(
                        err_session,
                        staging_table=staging_table_name,
                        job=err_job,
                        exc=exc,
                        task_name="ingest_service",
                        attempt_id=attempt_uuid,
                    )
                else:
                    structlog.get_logger().exception(
                        "Ingest task failed",
                        job_id=job_id,
                        task="ingest_service",
                    )
        except DBAPIError as write_failure:
            # The budget covers the helper's own load, so
            # an expiry there arrives here. Swallowed for the reason the helper
            # swallows its UPDATE's: the cause below is the task's outcome.
            log_job_error_write_failure(
                write_failure, job_id=job_id, task="ingest_service"
            )
        raise
    finally:
        # `purge_token_on_failure` (`tasks_common.py`), the
        # decorator around this task, must still see whatever exception
        # `ingest_service` itself raised, not one from a cleanup step.
        async with cleanup_step("ingest_service heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("ingest_service staging table", job_id=job_id):
            await _drop_attempt_staging_table(staging_table_name)
