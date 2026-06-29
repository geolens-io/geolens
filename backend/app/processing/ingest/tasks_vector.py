"""Procrastinate task definitions for vector file and service ingestion."""

import asyncio
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import text

from app.core.db.tenant_session import tenant_task
from app.processing.ingest.metadata import _qtable
from app.processing.ingest.tasks_common import (
    IngestContext,
    _append_job_warning,
    _archive_original_file,
    _bind_task_log_context,
    _current_tenant_schema,
    _detect_and_override_geometry,
    _emit_billing_event,
    _finalize_ingest,
    _job_phase_session,
    _resolve_effective_srid,
    _run_service_import_with_wfs_fallback,
    _validate_upload_file_safety,
    resolve_service_type,
    task_app,
)


_SERVICE_IMPORT_INITIAL_PROGRESS = 0.1
_SERVICE_IMPORT_HEARTBEAT_INTERVAL_SECONDS = 5.0
_SERVICE_IMPORT_HEARTBEAT_INCREMENT = 0.05
_SERVICE_IMPORT_HEARTBEAT_MAX_PROGRESS = 0.65
_ARCGIS_SERVICE_IMPORT_CHUNK_SIZE = 2000


async def _heartbeat_service_import_progress(job_uuid: uuid.UUID) -> None:
    """Advance service-ingest progress while GDAL loads remote features."""
    while True:
        await asyncio.sleep(_SERVICE_IMPORT_HEARTBEAT_INTERVAL_SECONDS)
        try:
            async with _job_phase_session(
                job_uuid, phase="service_import_heartbeat"
            ) as (session, job):
                if job is None:
                    return
                if job.status != "running" or job.current_step != "ogr2ogr":
                    return

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
                    continue

                job.progress = next_progress
                await session.commit()
        except Exception:
            # Heartbeat progress is best-effort and must not mask ingest work.
            structlog.get_logger().warning(
                "service_import_progress_heartbeat_failed",
                job_id=str(job_uuid),
                exc_info=True,
            )


async def _write_service_import_progress(
    job_uuid: uuid.UUID, *, imported_rows: int, feature_count: int
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

    async with _job_phase_session(job_uuid, phase="service_import_chunk_progress") as (
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


async def _count_service_import_rows(table_name: str) -> int:
    from app.core import db as db_module

    async with db_module.async_session() as session:
        result = await session.execute(
            text(
                f"SELECT COUNT(*) FROM "
                f"{_qtable(table_name, schema=_current_tenant_schema())}"
            )
        )
        return int(result.scalar_one())


async def _fetch_arcgis_import_page_info(
    source_url: str, layer_id: int | str | None, token: str | None
) -> tuple[int | None, int | None]:
    if layer_id is None:
        return None, None

    from app.modules.catalog.sources.adapters.arcgis import (
        ArcGISTokenError,
        fetch_arcgis_feature_count,
        fetch_arcgis_max_record_count,
    )
    from app.modules.catalog.sources.security import make_safe_client
    from app.processing.ingest.ogr import IngestionError

    try:
        async with make_safe_client(timeout=30.0) as client:
            max_record_count = await fetch_arcgis_max_record_count(
                source_url, layer_id, client, token=token
            )
            feature_count = await fetch_arcgis_feature_count(
                source_url, layer_id, client, token=token
            )
            return feature_count, max_record_count
    except ArcGISTokenError as exc:
        raise IngestionError(str(exc)) from exc
    except Exception as exc:  # broad: count is an optimization; import can fall back
        structlog.get_logger().warning(
            "arcgis_import_page_info_fetch_failed",
            source_url=source_url,
            layer_id=str(layer_id),
            error=str(exc),
        )
        return None, None


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
        fan-out children (GAP-018) and on failure (S3 is the source of truth).
      - Shared local-staging file (``file_path == original_file_path``) of a
        fan-out child: NEVER unlink — siblings read the same file; the staging
        retention policy reaps it later (GPKG-03 close-gate fix).
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
async def ingest_file(job_id: str, file_path: str, user_id: str, **kwargs) -> None:
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

    Session lifecycle (gh #100): the AsyncSession is split into two short-lived
    blocks so it is NOT held open across the long-running ``run_ogr2ogr``
    asyncio subprocess. Holding a session open across that subprocess in
    Python 3.14 + SQLAlchemy 2.0 + greenlet 3.3 corrupts the greenlet bridge
    state and the next ``session.execute()`` (e.g. ``clip_to_mercator_bounds``
    when it actually modifies rows) raises ``MissingGreenlet``. See
    ``.planning/debug/worker-missing-greenlet-100.md`` for the full diagnosis.
    """
    _bind_task_log_context(task_name="ingest_file", job_id=job_id)
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr, run_ogrinfo
    from app.processing.ingest.service import generate_table_name
    from app.platform.jobs.models import IngestJob

    job_uuid = uuid.UUID(job_id)
    original_file_path = file_path
    final_status: str = "pending"

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session via _job_phase_session — REMED-03 /
        # P2-05): load job, mark running, validate, detect CRS, generate
        # table name. Snapshot values needed for phase 2 into local
        # variables so the ogr2ogr subprocess can run without a session
        # held open (#100 greenlet rule lives in the helper docstring).
        # ----------------------------------------------------------------- #
        async with _job_phase_session(job_uuid, phase="phase1") as (session, job):
            if job is None:
                return

            # 1. Update job to running.
            # REMED-02 / ingest-audit P2-07: stamp current_step + progress
            # together with status so the polling UI gets a fresh "validating"
            # signal on the very first poll after the worker picks up the job.
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.current_step = "validating"
            job.progress = 0.0
            await session.commit()

            # Resolve S3 key to local file for ogr2ogr
            from app.processing.ingest.service import resolve_file_path

            file_path = await resolve_file_path(file_path, job_id)

            # Validate file content and safety before ogr2ogr (KISS-3).
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
                # retry=0: no retry will ever occur, so unlink the staging
                # file to prevent permanent orphaning.
                Path(file_path).unlink(missing_ok=True)
                final_status = "failed"
                return

            # Check for user-supplied metadata from commit step
            um = job.user_metadata or {}
            srid_override = um.get("srid_override")
            layer_name = um.get("layer_name")
            source_filename = job.source_filename

            # 2. Detect CRS via ogrinfo
            info = await run_ogrinfo(file_path, layer_name=layer_name)
            srid = info.get("srid")
            geometry_type = info.get("geometry_type")
            has_geometry = geometry_type is not None

            # Check for missing CRS (CSV and GeoJSON default to EPSG:4326)
            # Non-spatial files don't need CRS at all
            lower_path = file_path.lower()
            assumes_4326 = any(
                lower_path.endswith(ext)
                for ext in (".csv", ".geojson", ".json", ".xlsx", ".xls")
            )
            if (
                has_geometry
                and srid is None
                and not assumes_4326
                and srid_override is None
            ):
                job.status = "failed"
                job.error_message = (
                    "Missing CRS: no coordinate system detected. "
                    "Ensure the file includes CRS information "
                    "(e.g., .prj file for Shapefiles)."
                )
                job.completed_at = datetime.now(timezone.utc)
                await session.commit()
                final_status = "failed"
                return

            # 3. Generate table name
            dataset_name = um.get("title") or source_filename or "dataset"
            table_name, collision_warning = await generate_table_name(
                dataset_name, session
            )
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
        # is what triggers the MissingGreenlet bug (gh #100).
        # ----------------------------------------------------------------- #
        db_conn_str = build_pg_conn_str()

        # Check for user-specified geometry columns (override)
        # Lowercase column names: ogr2ogr lowercases them in PostGIS.
        # CLEANUP-2: the individual column locals are re-derived inside
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

        # REMED-02 / ingest-audit P2-07: write current_step="ogr2ogr" BEFORE
        # the long subprocess so the UI sees the transition even if ogr2ogr
        # hangs. Brief-session pattern via _job_phase_session — the #100
        # greenlet rule forbids holding a session open across run_ogr2ogr,
        # but the progress write must commit so it cannot be lost on
        # rollback if ogr2ogr raises.
        async with _job_phase_session(job_uuid, phase="progress_write_ogr2ogr") as (
            _progress_session,
            _progress_job,
        ):
            if _progress_job is not None:
                _progress_job.current_step = "ogr2ogr"
                _progress_job.progress = 0.1
                await _progress_session.commit()

        await run_ogr2ogr(
            file_path,
            table_name,
            db_conn_str,
            source_srid=srid,
            geometry_type=ogr_geometry_type,
            layer_name=layer_name,
        )

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session via _job_phase_session — REMED-03 /
        # P2-05): post-ogr2ogr finalization. Re-load the job in a fresh
        # session — its attributes were already snapshotted into
        # ``um`` / ``source_filename`` / ``layer_name`` above.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(job_uuid, phase="phase2") as (session, job):
            if job is None:
                return

            # REMED-02 / ingest-audit P2-07: progress signal for phase-2 work.
            # Intentionally NOT committed here — participates in the same
            # transaction as _finalize_ingest's terminal commit so a rollback
            # cleans this up too. The brief-session "ogr2ogr" write above
            # is the durable mid-flight checkpoint.
            #
            # REMED-03 / P2-05: _job_phase_session owns the rollback-on-exception
            # shape that used to live here as a manual try/except. If any
            # statement below raises, the helper rolls the session back and
            # re-raises; the outer `except Exception as exc` handler then
            # writes the failure record via a fresh session.
            job.current_step = "finalize"
            job.progress = 0.7

            # 3a. Rename any source column that collides with a GeoLens-internal
            #     name (gid, geom, geometry, geom_4326, fid, ogc_fid). Runs BEFORE
            #     the user-geometry-override and _finalize_ingest steps so that
            #     construct_point_geometry / add_4326_column cannot clash with a
            #     source attribute of the same name.
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(
                session, table_name, schema=_current_tenant_schema()
            )
            if reserved_renames:
                from app.processing.ingest.warnings import (
                    make_reserved_rename_warning,
                )

                _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

            # 3b. Shapefile-only: detect DBF 10-char truncation collisions using
            #     the source column list from ogrinfo (stored in info["columns"]).
            if file_path.lower().endswith(".zip"):
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
                        table=table_name,
                        collisions=dbf_collisions,
                    )

            if user_wants_geom:
                override_geom_type = await _detect_and_override_geometry(
                    session,
                    table_name=table_name,
                    user_metadata=um,
                )
                if override_geom_type is not None:
                    has_geometry = True
                    geometry_type = override_geom_type

            # Use srid_override if provided
            effective_srid = _resolve_effective_srid(
                detected_srid=srid,
                srid_override=srid_override,
            )

            # 4. Determine source format from file extension
            suffix = Path(file_path).suffix.lower()
            # Strip leading dot for format name; handle .zip -> look inside filename
            source_format = suffix.lstrip(".")
            if source_format == "zip":
                source_format = "shapefile"

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
                )
            )

            # 9c. Archive original file to storage provider (R-2).
            await _archive_original_file(
                session,
                job=job,
                dataset_id=dataset.id,
                file_path=file_path,
            )

            # METER-01 (Phase 1213-02): emit ingest billable event through the
            # billing-import-free seam.  Best-effort fire-and-forget — errors
            # logged inside _emit_billing_event; ingest outcome unaffected.
            # tenant_id from current_tenant_var (set by 1208/1209 middleware).
            # event_id = job_id so task retries stay idempotent at the DB layer.
            from app.core.db.tenant_session import current_tenant_var

            await _emit_billing_event(
                str(current_tenant_var.get()) if current_tenant_var.get() else None,
                "ingest_jobs",
                event_id=job_id,
            )

            final_status = "complete"

    except Exception as exc:  # broad: ingest pipeline spans GDAL/PostGIS/S3/FS — any step can fail; record failure status
        structlog.get_logger().exception(
            "Ingest task failed",
            job_id=job_id,
            task="ingest_file",
        )
        # Write failure status via a fresh session — phase 1/2 sessions are
        # already closed (or rolled back) by the time we get here.
        # REMED-03 / P2-05: route through _job_phase_session so the helper
        # owns the session-lifecycle boilerplate. The yielded job is
        # ignored — we issue a SQL UPDATE rather than mutating the ORM row
        # so a NULL job (race with row delete) still produces a clean
        # no-op update instead of an AttributeError.
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
        # Clean up local file on success always; on failure only if it was
        # a resolve_file_path download (source of truth is S3, not the
        # local copy). Local-only uploads are kept for retry.
        #
        # Phase 1060 close-gate fix (GPKG-03 fan-out): multiple fan-out
        # sibling jobs that read from the SHARED LOCAL staging file
        # (file_path == original_file_path) must not unlink it — when one
        # sibling completes and unlinks, the next sibling fails with
        # FileNotFoundError. So the shared-local-staging file is preserved
        # for fan-out children and reaped later by the staging retention
        # policy.
        #
        # GAP-018 (Tier-2): in S3 mode each child resolves its OWN per-child
        # download (resolve_file_path -> "{child_job_id}_{name}", so
        # file_path != original_file_path). That copy is PRIVATE to this
        # child — no sibling shares it — so it is always safe to unlink even
        # for fan-out children. Previously the is_fan_out_child guard skipped
        # cleanup unconditionally, leaking every child's S3 download on disk.
        is_fan_out_child = False
        try:
            # REMED-03 / P2-05: route through _job_phase_session. The helper
            # yields the IngestJob row directly, so we just check user_metadata.
            async with _job_phase_session(job_uuid, phase="cleanup_check") as (
                _check_session,
                _check_job,
            ):
                if _check_job is not None and (_check_job.user_metadata or {}).get(
                    "fan_out_parent_id"
                ):
                    is_fan_out_child = True
        except Exception:  # broad: cleanup decision is best-effort, never block completion on this query
            is_fan_out_child = False

        if _should_unlink_staging(
            file_path=file_path,
            original_file_path=original_file_path,
            final_status=final_status,
            is_fan_out_child=is_fan_out_child,
        ):
            Path(file_path).unlink(missing_ok=True)


@task_app.task(queue="ingest", retry=0, aliases=["app.ingest.tasks.ingest_service"])
@tenant_task
async def ingest_service(
    job_id: str,
    source_url: str,
    source_layer: str,
    user_id: str,
    token: str | None = None,
    **kwargs,
) -> None:
    """Background task: import a remote service layer via ogr2ogr.

    Full pipeline:
    1. Update job status to running
    2. Determine service type from job metadata
    3. Build GDAL source string and run ogr2ogr
    4. Post-process (clip, geom_4326, grants, metadata, samples)
    5. Create Dataset record with source_format and source_url
    6. Compute quality score
    7. Update job status to complete

    Session lifecycle (gh #100): same two-phase split as ``ingest_file`` —
    the session is closed before the ogr2ogr subprocess runs and reopened
    for finalization, so the SQLAlchemy greenlet bridge is never asked to
    survive across a long asyncio subprocess.
    """
    _bind_task_log_context(task_name="ingest_service", job_id=job_id)
    from app.modules.catalog.sources.security import (
        SSRFError,
        validate_url_for_ssrf,
    )
    from app.platform.extensions import get_processing_port
    from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr_service
    from app.processing.ingest.service import generate_table_name
    from app.platform.jobs.models import IngestJob

    # IA-P0-03 defense-in-depth: revalidate source_url at fetch time.
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
    job_uuid = uuid.UUID(job_id)

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session via _job_phase_session — REMED-03 /
        # P2-05): load job, mark running, generate table name. Snapshot all
        # values needed for phase 2.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(job_uuid, phase="phase1") as (session, job):
            if job is None:
                return

            # 1. Update job to running.
            # REMED-02 / ingest-audit P2-07: mirror ingest_file's progress
            # writes so the polling UI shows step transitions for service
            # ingests too. The service path has the same step boundaries as
            # the file path (validating -> ogr2ogr -> finalize -> complete)
            # except there is no "archiving" — services don't archive originals.
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            job.current_step = "validating"
            job.progress = 0.0
            await session.commit()

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
            if collision_warning:
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "collision_warning": collision_warning,
                }
                await session.commit()

        # ----------------------------------------------------------------- #
        # ogr2ogr subprocess — NO session open. Holding a session open
        # across this subprocess is what triggers the MissingGreenlet bug.
        # ----------------------------------------------------------------- #
        db_conn_str = build_pg_conn_str()

        # REMED-02 / ingest-audit P2-07: stamp current_step="ogr2ogr" before
        # the long remote-service fetch (same brief-session pattern as
        # ingest_file). Routed through _job_phase_session per REMED-03.
        async with _job_phase_session(job_uuid, phase="progress_write_ogr2ogr") as (
            _progress_session,
            _progress_job,
        ):
            if _progress_job is not None:
                _progress_job.current_step = "ogr2ogr"
                _progress_job.progress = _SERVICE_IMPORT_INITIAL_PROGRESS
                await _progress_session.commit()

        # WFS namespace retry via shared helper (KISS-8).
        async def _do_import(layer_name: str) -> None:
            feature_count = None
            page_size = _ARCGIS_SERVICE_IMPORT_CHUNK_SIZE
            if service_type == "arcgis_featureserver":
                feature_count, max_record_count = await _fetch_arcgis_import_page_info(
                    source_url, layer_id, token
                )
                if max_record_count is not None:
                    page_size = max(1, min(page_size, max_record_count))

            if (
                service_type == "arcgis_featureserver"
                and feature_count is not None
                and feature_count > page_size
            ):
                imported_rows = 0
                append = False
                for offset in range(0, feature_count, page_size):
                    _src, _layer = port.build_gdal_source(
                        service_type_raw,
                        source_url,
                        layer_name,
                        layer_id,
                        token=token,
                        order_field=object_id_field,
                        result_limit=page_size,
                        result_offset=offset,
                    )
                    await run_ogr2ogr_service(
                        _src,
                        _layer,
                        table_name,
                        db_conn_str,
                        service_type,
                        token=token,
                        is_non_spatial=is_non_spatial,
                        append=append,
                    )
                    next_imported_rows = await _count_service_import_rows(table_name)
                    if next_imported_rows <= imported_rows:
                        from app.processing.ingest.ogr import IngestionError

                        raise IngestionError(
                            "ArcGIS service import made no row-count progress "
                            f"at offset {offset}; upstream pagination may be "
                            "unsupported or returned an empty page."
                        )
                    imported_rows = next_imported_rows
                    await _write_service_import_progress(
                        job_uuid,
                        imported_rows=imported_rows,
                        feature_count=feature_count,
                    )
                    append = True
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
                table_name,
                db_conn_str,
                service_type,
                token=token,
                is_non_spatial=is_non_spatial,
            )

        service_progress_task = asyncio.create_task(
            _heartbeat_service_import_progress(job_uuid)
        )
        try:
            await _run_service_import_with_wfs_fallback(
                _do_import, source_layer, token=token
            )
        finally:
            service_progress_task.cancel()
            with suppress(asyncio.CancelledError):
                await service_progress_task

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): post-ogr2ogr finalization.
        # ----------------------------------------------------------------- #
        async with _job_phase_session(job_uuid, phase="phase2") as (session, job):
            if job is None:
                return

            # REMED-02 / ingest-audit P2-07: mirror ingest_file's phase-2
            # progress write. Uncommitted — _finalize_ingest's terminal
            # commit owns the transaction lifecycle.
            # REMED-03 / P2-05: helper owns the rollback-on-exception shape
            # that used to live as a manual try/except around this block.
            job.current_step = "finalize"
            job.progress = 0.7

            # 4a. Rename any source column that collides with a GeoLens-internal
            #     name. Runs BEFORE _finalize_ingest (which calls add_4326_column).
            from app.processing.ingest.metadata import rename_reserved_columns

            reserved_renames = await rename_reserved_columns(
                session, table_name, schema=_current_tenant_schema()
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
                )
            )

            # METER-01 (Phase 1213-02): emit ingest billable event.
            from app.core.db.tenant_session import current_tenant_var

            await _emit_billing_event(
                str(current_tenant_var.get()) if current_tenant_var.get() else None,
                "ingest_jobs",
                event_id=job_id,
            )

    except Exception as exc:  # broad: PostGIS/DB ingest can fail at any step; mark job failed and re-raise
        structlog.get_logger().exception(
            "Ingest task failed",
            job_id=job_id,
            task="ingest_service",
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
        raise
