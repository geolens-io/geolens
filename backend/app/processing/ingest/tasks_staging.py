"""Staging acquisition and cleanup for ingest tasks.

Holds the half of the ingest task helpers that gets a source into a staging
table and tears the attempt down when it dies: the ``StagingResult`` bundle,
the two staging-object reapers, the upload-safety gauntlet, the original-file
archive, the post-ogr2ogr staging pipeline, and the shared terminal-failure
handler. ``tasks_common`` keeps the job lifecycle, metadata extraction, and
the finalize pipeline.
"""

import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from app.core.async_io import await_draining, run_in_thread_draining
from app.core.failure_reason import redact_failure_reason
from app.platform.storage import get_storage
from app.processing.ingest.source_format import derive_source_format
from app.processing.ingest.tasks_common import (
    _append_job_warning,
    _current_tenant_role,
    _current_tenant_schema,
    _detect_and_override_geometry,
)


@dataclass
class StagingResult:
    """Intermediate staging outputs before dataset creation."""

    metadata: dict
    sample_values: dict
    three_d: dict
    has_geometry: bool
    geometry_type: str | None
    # fix(#888): clip_to_mercator_bounds accounting, so the caller (which owns
    # the job row) can warn the user about geometry the clamp destroyed.
    mercator_clip: dict | None = None


async def reap_downloaded_staging_source(
    job_id: str,
    *,
    original_file_path: str,
    final_status: str,
    failed_source_replayable: bool,
    is_fan_out_child: bool = False,
) -> None:
    """Delete the storage object this task DOWNLOADED its source from.

    fix(#430): without this the `staging/{job_id}/` key a task downloaded
    from lives forever when a run fails before creating a dataset.

    fix(#1213): after a presigned completion, `original_file_path` is the
    FROZEN copy, not the client-writable original. This reaps the frozen
    object; `reap_presigned_staging_object` reaps the client's key. Both
    are required — shared between vector and reupload tails so they can't
    drift (reupload previously shipped without this reaper).

    fix(#1213): the reap signal is the `staging/` PREFIX on
    `original_file_path`, not `file_path != original_file_path` — a
    download that raises never performs that rewrite, so the equality
    check skipped reaping on exactly the error path, leaking a possibly
    multi-GB frozen snapshot. The prefix alone is a sound discriminator:
    only a presigned completion (S3-only) produces a `staging/`-shaped
    path. Fan-out children are skipped (siblings share the original; a
    retention policy reaps those).

    fix(#1213): `failed_source_replayable` is required, not defaulted, so
    each caller states whether a FAILED job may be reaped. Ordinary
    imports pass True and retain on failure (`_retry_capability` in
    `platform/jobs/router.py` allows retrying them while the object still
    exists); the reupload caller passes False because `_retry_capability`
    refuses reupload jobs outright, so nothing else will ever reap them.

    Never raises — a failed sweep leaves an orphan, which beats failing a
    job whose work is already committed.
    """
    if final_status not in ("complete", "failed"):
        return
    if final_status == "failed" and failed_source_replayable:
        return
    if is_fan_out_child or not original_file_path.startswith("staging/"):
        return
    try:
        from app.platform.storage import get_storage
        from app.platform.storage.titiler_url import resolve_current_storage_key

        await await_draining(
            get_storage().delete(resolve_current_storage_key(original_file_path))
        )
    except (
        BaseException
    ):  # broad: terminal cleanup must complete through cancellation (KISS-N9)
        structlog.get_logger().warning(
            "Failed to delete staging source object",
            job_id=job_id,
            storage_key=original_file_path,
        )


async def reap_presigned_staging_object(
    job_id: str, owned_staging_key: str | None, *, final_status: str
) -> None:
    """Best-effort delete of a job's OWN presigned staging object.

    fix(#1202): a completed presigned upload points ``file_path`` at the
    frozen copy, so a reaper keyed off ``file_path`` misses the staging key
    the client's PUT URL can still recreate outside size/quota accounting.
    Called by every terminal task tail.

    Pass the result of ``owned_presigned_staging_key``, which declines a
    fan-out child's inherited parent key so a child can't reap the
    original its siblings still read.

    Never raises — a failed sweep leaves an orphan, better than failing a
    job whose work is already committed.
    """
    # fix(#1207): terminal-status guard lives HERE, not per tail — a
    # non-terminal exit (missing job/dataset, lost heartbeat claim) must not
    # sweep, since the attempt may be re-claimed and still need these bytes.
    if final_status not in ("complete", "failed") or not owned_staging_key:
        return
    try:
        from app.platform.storage import get_storage
        from app.platform.storage.titiler_url import resolve_current_storage_key

        await await_draining(
            get_storage().delete(resolve_current_storage_key(owned_staging_key))
        )
    except (
        BaseException
    ):  # broad: terminal cleanup must complete through cancellation (KISS-N9)
        structlog.get_logger().warning(
            "Failed to delete presigned staging object",
            job_id=job_id,
            storage_key=owned_staging_key,
        )


async def _validate_upload_file_safety(
    session,
    *,
    file_path: str,
    source_filename: str | None,
) -> None:
    """Run the three-step upload-safety gauntlet before ogr2ogr touches a file.

    - content validation (magic bytes, extension match, CSV parse)
    - size validation (against the persistent_config max)
    - ZIP-container bomb / path-traversal validation

    Shared by ``ingest_file``, ``reupload_file``, and ``ingest_raster``
    (KISS-3/5/6 consolidation). Raises ``ValueError`` on any check so
    each caller can map to its own job-failure handling.
    """
    from app.processing.ingest.validation import (
        validate_file_content,
        validate_file_size,
        validate_archive_safety,
        validate_content_directives,
    )
    from app.core.persistent_config import UPLOAD_MAX_SIZE_MB

    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(session)

    # validate_file_content wants a non-None filename for extension parsing;
    # fall back to the file's own basename so the content-check still runs.
    effective_filename = source_filename or Path(file_path).name
    validate_file_content(file_path, effective_filename)
    validate_file_size(file_path, max_size_mb * 1024 * 1024)
    validate_archive_safety(file_path, effective_filename)
    # fix(#1846, GHSA-hrf5-v3cq-frx5): what the file says to do is as much a
    # property of the upload as its shape is. Off the event loop: the linear
    # schema walk is still real work on a request thread.
    await run_in_thread_draining(
        validate_content_directives, file_path, effective_filename
    )


async def _archive_original_file(
    session,
    *,
    job,
    dataset_id,
    file_path: str,
    log_message: str = "Failed to archive original file to storage",
    commit: bool = True,
    archive_name: str | None = None,
) -> bool:
    """Upload the original source file to the storage provider (best-effort).

    Returns True when the archive landed. fix(#1290): raster tails call this
    to satisfy ADR-002 Decision 7 when a conversion was lossy and must not
    delete the staged upload unless the durable copy exists — for them the
    return value is a decision input, not just a breadcrumb. Vector callers
    ignore it.

    Archive failures must NOT fail the ingest (the dataset is already
    committed) — instead the failure is recorded on ``job.user_metadata``
    for UI/operator audit (R-2). ``commit=False`` lets ``reupload_file``'s
    caller fold that metadata write into its own ``job.status="complete"``
    commit instead of a second round trip.

    When ``commit`` is True, the metadata-update commit is wrapped in its
    own try/except: a transient DB error there must not flip an
    already-successful ingest into a ``failed`` job — on failure this logs
    and gives up, and the operator just loses the ``archive_failed``
    breadcrumb.
    """

    logger = structlog.get_logger()
    # fix(#1290): `file_path` is a temp download on any object-store
    # deployment, so deriving the name from it archives the upload under a
    # generated filename nobody recognises. Callers that know what the user
    # actually uploaded pass it.
    archive_key = f"originals/{dataset_id}/{archive_name or Path(file_path).name}"
    try:
        from app.core.db.tenant_session import current_tenant_var
        from app.platform.storage.titiler_url import resolve_storage_key

        storage = get_storage()
        physical_archive_key = resolve_storage_key(
            archive_key, tenant_id=current_tenant_var.get()
        )
        with open(file_path, "rb") as fobj:
            await storage.put(physical_archive_key, fobj)
        return True
    except Exception as archive_exc:  # broad: archive is best-effort; S3/local I/O can fail for any reason
        logger.warning(
            log_message,
            archive_key=archive_key,
            dataset_id=str(dataset_id),
            error=str(archive_exc)[:500],
        )
        job.user_metadata = {
            **(job.user_metadata or {}),
            "archive_failed": True,
            "archive_error": str(archive_exc)[:500],
        }
        if not commit:
            return False
        try:
            await session.commit()
        except Exception as commit_exc:  # broad: transient DB errors (deadlock, pooler drop) during flag persistence
            await session.rollback()
            logger.warning(
                "Failed to persist archive_failed flag on job",
                archive_key=archive_key,
                dataset_id=str(dataset_id),
                error=str(commit_exc)[:500],
            )
        return False


async def _run_staging_pipeline(
    session,
    *,
    table_name: str,
    has_geometry: bool,
    effective_srid: int | None,
) -> StagingResult:
    """Run the post-ogr2ogr staging pipeline on a table.

    fix(#1018): the only production caller is ``tasks_reupload.reupload_file``.
    ``_ingest_vector_into_staging`` also calls it but is test-only; NEW
    vector ingest does NOT — ``_finalize_ingest`` reruns these same steps
    inline instead.

    Performs: ensure_geom_column,
    clip_to_mercator_bounds, add_4326_column, grant_reader_access,
    extract_metadata, detect_3d_metadata, promote_z_to_elev, and
    get_sample_values. Does not commit.
    """
    from app.processing.ingest.metadata import (
        add_4326_column,
        clip_to_mercator_bounds,
        detect_3d_metadata,
        ensure_geom_column,
        extract_metadata,
        get_sample_values,
        grant_reader_access,
        promote_z_to_elev,
    )

    _schema = _current_tenant_schema()
    mercator_clip = None
    if has_geometry:
        has_geometry = await ensure_geom_column(session, table_name, schema=_schema)
        if has_geometry:
            mercator_clip = await clip_to_mercator_bounds(
                session, table_name, schema=_schema
            )
            if effective_srid is not None:
                await add_4326_column(
                    session, table_name, effective_srid, schema=_schema
                )

    await grant_reader_access(
        session,
        table_name,
        schema=_schema,
        role=_current_tenant_role(),
    )

    metadata = await extract_metadata(session, table_name, schema=_schema)
    three_d = await detect_3d_metadata(session, table_name, schema=_schema)

    if three_d.get("is_3d"):
        elev_promoted = await promote_z_to_elev(
            session, table_name, metadata.get("geometry_type"), schema=_schema
        )
        if elev_promoted:
            from app.processing.ingest.metadata import get_column_info

            metadata["column_info"] = await get_column_info(
                session, table_name, schema=_schema
            )

    sample_values = await get_sample_values(
        session, table_name, metadata.get("column_info", []), schema=_schema
    )

    return StagingResult(
        metadata=metadata,
        sample_values=sample_values,
        three_d=three_d,
        has_geometry=has_geometry,
        geometry_type=metadata.get("geometry_type"),
        mercator_clip=mercator_clip,
    )


async def _cleanup_staging_on_failure(
    session,
    *,
    staging_table: str,
    job,
    exc: Exception,
    task_name: str,
    attempt_id: uuid.UUID | None = None,
) -> None:
    """Mark the job failed, then drop the staging table, in that order.

    The single terminal-write site for ``reupload_file``/``reupload_service``
    and the import tasks: applies the ``redact_failure_reason`` backstop,
    the ``pending``-inclusive attempt fence (fix(#1274): a worker-time refusal
    that raises before the claim must still finalize the job it owns rather
    than leave it for the stale sweep), and the ``ingest_failed`` notification.

    fix(#1778): ``staging_table`` is "" for paths with none (the VRT tail
    reaps its object keys in its own ``finally``) — an empty name skips the
    DROP rather than interpolating and raising inside the best-effort guard.

    fix(#1778): ORDER is the contract — the failure row is written and
    committed BEFORE the drop, because a statement error aborts the whole
    transaction and every later statement on that session raises until
    rolled back. Drop-first previously left a job ``running`` with no
    reason recorded when the drop hit a lock/statement timeout. Anything
    added here that can fail goes after the commit, in its own guarded
    block with its own rollback.

    fix(#1950): the failure UPDATE runs under ``JOB_ERROR_WRITE_TIMEOUT_MS``;
    on a contended row it logs ``job_error_write_timeout`` and returns
    rather than waiting — the job stays ``running`` and the caller re-raises
    the failure it was already handling.
    """
    from sqlalchemy import text
    from sqlalchemy import update as sa_update
    from sqlalchemy.exc import DBAPIError

    from app.platform.jobs.heartbeat import (
        arm_job_error_write_budget,
        log_job_error_write_failure,
    )
    from app.processing.ingest.metadata import _qtable

    job_id = job.id
    completed_at = datetime.now(timezone.utc)
    # fix(#1277): last boundary before this text becomes durable — feeds the
    # persisted error_message, the log record, and the notification reason,
    # so redacting once here covers all three for every caller.
    # fix(#1953): ADR-002 Decision 3 now covers this sink, and it is the
    # exception rather than its text that crosses, so a library exception
    # becomes a code instead of its statement-and-parameters dump.
    error_message = redact_failure_reason(exc)
    await session.rollback()

    failure_update = sa_update(type(job)).where(type(job).id == job_id)
    if attempt_id is not None:
        # The fence is the attempt-id equality — a superseded attempt carries
        # a different token and can never match. `pending` is included
        # because a failure BEFORE the claim (fix(#1274) review: the worker-
        # time SSRF refusal) must still finalize the job it owns; requiring
        # `running` made the legitimate attempt's pre-claim failures
        # invisible, leaving the job pending until the stale sweep.
        failure_update = failure_update.where(
            type(job).attempt_id == attempt_id,
            type(job).status.in_(("pending", "running")),
        )
    # fix(#1950): an expired budget must not become the task's outcome. Swallowed
    # and logged as its own event, so the caller re-raises the ingest failure and
    # the report below still runs; `written` gates what the write earned.
    written = False
    result = None
    try:
        # fix(#1950): armed AFTER the rollback that would discard it and before
        # the UPDATE, which is the statement that blocks on a contended job row;
        # inside the guard because arming can fail on a lost connection too.
        await arm_job_error_write_budget(session)
        result = await session.execute(
            failure_update.values(
                status="failed",
                error_message=error_message,
                completed_at=completed_at,
            )
        )
        await session.commit()
        written = True
    except DBAPIError as write_failure:
        # Same reason as the loader's: the callers below re-raise the ingest
        # failure, and a rollback that raises would take its place.
        with suppress(Exception):  # broad: best-effort, the caller re-raises
            await session.rollback()
        log_job_error_write_failure(write_failure, job_id=str(job_id), task=task_name)

    # DROP after commit — see docstring. Runs before the rowcount return so
    # this attempt's (attempt-scoped) table is dropped even when a newer
    # attempt already owns the job row.
    if staging_table:
        try:
            await session.execute(
                text(
                    f"DROP TABLE IF EXISTS {_qtable(staging_table, schema=_current_tenant_schema())}"
                )
            )
            await session.commit()
        except Exception as cleanup_exc:  # broad: best-effort cleanup
            structlog.get_logger().warning(
                f"Staging-table cleanup failed during {task_name} failure",
                staging_table=staging_table,
                cleanup_error=str(cleanup_exc),
                original_error=str(exc),
            )
            try:
                await session.rollback()
            except Exception:  # broad: a dead connection cannot be rolled back
                structlog.get_logger().warning(
                    "staging_cleanup_rollback_failed",
                    staging_table=staging_table,
                    task=task_name,
                )

    if written and attempt_id is not None and not result.rowcount:
        return
    if written:
        job.status = "failed"
        job.error_message = error_message
        job.completed_at = completed_at
    structlog.get_logger().exception(
        "Ingest task failed",
        job_id=str(job_id),
        task=task_name,
    )

    # EVENT-03: notify on ingest failed (non-fatal, after commit — deferred import discipline).
    # status="failed" + error_message are already committed above so a notification
    # error can never roll back or alter the terminal job write (T-1230-09 / fail-safe).
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    _job_id_str = str(job_id)
    _reason = error_message
    _task = task_name
    await emit_event_safe(
        event_key="ingest_failed",
        build=lambda: build_event_notification(
            "ingest_failed",
            subject=f"Ingest failed: {_task}",
            body=f"Ingest job (task={_task}) failed.",
            reason=_reason,
            extra={"job_id": _job_id_str, "task": _task},
        ),
    )


async def _ingest_vector_into_staging(
    session,
    *,
    job,
    file_path: str,
    target_table: str,
    source_srid: int | None,
    ogr_geometry_type: str | None,
    has_geometry: bool,
    effective_srid: int | None,
    layer_name: str | None = None,
    ogrinfo_columns: list[dict] | None = None,
    user_wants_geom: bool = False,
    user_metadata: dict[str, Any] | None = None,
) -> StagingResult:
    """Load a vector source into staging and return extracted staging metadata.

    TEST-ONLY (#1018): nothing in ``app/`` calls this, only
    ``tests/test_staging_pipeline.py`` and ``test_staging_pipeline_integration
    .py``. Gives those tests a seam over vector ingest's pre-staging half,
    which production runs inline in its own job lifecycle. Mirrors
    ``run_ogr2ogr``, ``rename_reserved_columns``, the DBF-truncation check,
    then ``_detect_and_override_geometry`` under ``user_wants_geom`` — the
    same four as ``tasks_vector.ingest_file`` (the only production path with
    the override); ``tasks_reupload.reupload_file`` runs only the first
    three and passes its detected type straight to ``run_ogr2ogr``.

    Calls the real ``_run_staging_pipeline``, but that eight-step sequence
    also exists inlined in ``_finalize_ingest`` (used by ``tasks_vector.
    ingest_file``) and as a SHORTER copy (no 3D detection, no elevation
    promotion) in ``tasks_reupload.reupload_service`` — do not "fix" that
    shorter copy by symmetry without finding out why first. A change to the
    shared six steps has three sites; this test covers the one production
    reaches least.

    Performs no commits.
    """
    from app.processing.ingest.metadata import rename_reserved_columns
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr

    if user_wants_geom and user_metadata is None:
        raise ValueError("user_metadata is required when user_wants_geom=True")

    db_conn_str = build_pg_conn_str()
    await run_ogr2ogr(
        file_path,
        target_table,
        db_conn_str,
        source_srid=source_srid,
        geometry_type=ogr_geometry_type,
        layer_name=layer_name,
        schema=_current_tenant_schema(),
        effective_srid=effective_srid,
    )

    reserved_renames = await rename_reserved_columns(
        session, target_table, schema=_current_tenant_schema()
    )
    if reserved_renames:
        from app.processing.ingest.warnings import make_reserved_rename_warning

        _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

    # Shapefile-only. Keyed on the derived format, not the .zip suffix — a
    # File Geodatabase arrives in a .zip too and has no DBF to truncate.
    if derive_source_format(file_path) == "shapefile":
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions
        from app.processing.ingest.ogr import run_ogrinfo_preview
        from app.processing.ingest.warnings import make_dbf_truncation_warning

        preview_cols = ogrinfo_columns or []
        if not preview_cols:
            preview_info = await run_ogrinfo_preview(
                file_path, sample_limit=0, layer_name=layer_name
            )
            preview_cols = preview_info.get("columns") or []
        dbf_collisions = detect_dbf_truncation_collisions(preview_cols)
        if dbf_collisions:
            _append_job_warning(job, make_dbf_truncation_warning(dbf_collisions))

    geometry_type = ogr_geometry_type
    if user_wants_geom:
        override_geom_type = await _detect_and_override_geometry(
            session,
            table_name=target_table,
            user_metadata=user_metadata or {},
            effective_srid=effective_srid or 4326,
        )
        if override_geom_type is not None:
            has_geometry = True
            geometry_type = override_geom_type

    result = await _run_staging_pipeline(
        session,
        table_name=target_table,
        has_geometry=has_geometry,
        effective_srid=effective_srid,
    )

    # Preserve the original geometry_type fallback: if _run_staging_pipeline
    # returned a geometry_type from metadata, use it; otherwise fall back to
    # the ogr_geometry_type (possibly overridden by user_wants_geom).
    if result.geometry_type is None and geometry_type is not None:
        result.geometry_type = geometry_type

    return result
