"""Procrastinate task definitions for file and service re-upload workflows."""

import asyncio
import uuid
from datetime import datetime, timezone
from functools import partial, wraps
from pathlib import Path

import structlog
from sqlalchemy import select, text

from app.core.db.tenant_session import tenant_task
from app.core.upload_errors import geometry_loss_refusal
from app.core.url_redaction import scrub_secret_from_exception
from app.platform.catalog_locks import (
    CATALOG_LOCK_CONFLICT_CODE,
    CatalogLockConflict,
)
from app.platform.dataset_origin import classify_origin, service_layer_identity
from app.processing.raster.cog import sha256_file

from app.platform.jobs.models import owned_presigned_staging_key
from app.platform.refresh import verification as refresh_policy
from app.platform.refresh.credentials import resolve_worker_credential
from app.platform.refresh.service import (
    drift_status_from_diff,
    record_refresh_blocked,
    record_refresh_failure,
)
from app.processing.ingest import catalog_projection
from app.processing.ingest.publication import (
    PUBLISH,
    Failure,
    PublicationCommit,
    Published,
    Verdict,
    settle_replacement,
    settle_timed_out_execution,
)
from app.processing.ingest.source_format import derive_source_format
from app.processing.ingest.tasks_common import (
    SourceURLRefused,
    _append_job_warning,
    cleanup_step,
    _append_mercator_clip_warning,
    _bind_task_log_context,
    _current_tenant_schema,
    _install_reupload_table,
    _run_service_import_with_wfs_fallback,
    _write_reupload_catalog,
    apply_manifest_record_metadata,
    purge_token_on_failure,
    resolve_service_type,
    task_app,
)
from app.processing.ingest.tasks_staging import (
    StagingResult,
    _archive_original_file,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
    _run_staging_pipeline,
    _validate_upload_file_safety,
)


# A keyed admitted occurrence has its own wall-clock budget.  The queue claim
# deadline ends at the pending -> running CAS; it must not terminate a
# legitimate fetch that started before that deadline.
_KEYED_REFRESH_EXECUTION_TIMEOUT_SECONDS = 1_800.0


def require_scheduled_execution_claim(fn):
    """Fence direct/late scheduled invocations before they contact a source."""

    @wraps(fn)
    async def _wrapped(*args, **kwargs):
        scheduled_execution_key = kwargs.get("scheduled_execution_key")
        if scheduled_execution_key is not None:
            try:
                execution_key = uuid.UUID(str(scheduled_execution_key))
                job_id = uuid.UUID(str(kwargs["job_id"]))
                attempt_id = uuid.UUID(str(kwargs["attempt_id"]))
            except (KeyError, TypeError, ValueError):
                structlog.get_logger().warning(
                    "scheduled_refresh_execution_claim_invalid"
                )
                return None

            from app.core.db import async_session
            from app.platform.refresh.models import DatasetRefreshRun

            async with async_session() as session:
                matching_run = await session.scalar(
                    select(DatasetRefreshRun).where(
                        DatasetRefreshRun.ingest_job_id == job_id,
                        DatasetRefreshRun.status == "running",
                        DatasetRefreshRun.execution_key == execution_key,
                    )
                )
            if matching_run is None:
                structlog.get_logger().warning(
                    "scheduled_refresh_execution_not_claimed", job_id=str(job_id)
                )
                return None
            try:
                async with asyncio.timeout(_KEYED_REFRESH_EXECUTION_TIMEOUT_SECONDS):
                    return await fn(*args, **kwargs)
            except TimeoutError:
                # ``asyncio.timeout`` injects cancellation, so the service
                # task's ordinary Exception handler does not get a chance to
                # settle the admitted run. Terminalize it here before the
                # queue sees the timeout; a late worker cannot publish after
                # this transition.
                await settle_timed_out_execution(
                    job_id, attempt_id, matching_run.dataset_id, task=fn.__name__
                )
                raise
        return await fn(*args, **kwargs)

    return _wrapped


def _assert_geometry_survives(
    *, record_type: str | None, geometry_type: str | None, has_geometry: bool
) -> None:
    """Raise the preview door's refusal when a replacement would strip geometry.

    fix(#2031): both worker paths reach the same ``record_type`` re-derivation —
    the file path knows from ogrinfo, the service path from the staging table.
    """
    geometry_loss = geometry_loss_refusal(
        record_type=record_type,
        dataset_geometry_type=geometry_type,
        source_has_geometry=has_geometry,
    )
    if geometry_loss:
        from app.processing.ingest.ogr import IngestionError

        raise IngestionError(geometry_loss)


async def _detect_reupload_crs(
    file_path: str,
    layer_name: str | None,
    user_metadata: dict,
    *,
    original_filename: str | None = None,
    record_type: str | None,
    dataset_geometry_type: str | None,
) -> tuple[dict, int]:
    """Detect CRS/geometry for a reupload file and resolve the effective SRID.

    GPKG-01 Phase 1058: ``layer_name`` targets the user-chosen layer in a
    multi-layer GPKG rather than defaulting to ``layers[0]``.

    fix(#541): applies the same missing-CRS gate as ``ingest_file``,
    raising ``IngestionError`` rather than silently falling through to the
    4326 default and corrupting the replacement dataset.

    fix(#2031): and the preview door's geometry-loss refusal, for the client
    that skipped the preview. ``record_type`` is the dataset's CURRENT one.

    Returns (ogrinfo result dict, effective_srid).
    """
    from app.processing.ingest.ogr import IngestionError, run_ogrinfo
    from app.processing.ingest.tasks_common import check_missing_crs

    info = await run_ogrinfo(
        file_path, layer_name=layer_name, original_filename=original_filename
    )
    srid = info.get("srid")
    geometry_type = info.get("geometry_type")
    srid_override = user_metadata.get("srid_override")

    missing_crs = check_missing_crs(
        file_path=file_path,
        has_geometry=geometry_type is not None,
        detected_srid=srid,
        srid_override=srid_override,
    )
    if missing_crs:
        raise IngestionError(missing_crs)

    _assert_geometry_survives(
        record_type=record_type,
        geometry_type=dataset_geometry_type,
        has_geometry=geometry_type is not None,
    )

    effective_srid = (
        srid_override
        if srid_override is not None
        else (srid if srid is not None else 4326)
    )
    return info, effective_srid


class _FileReupload:
    """A browser upload's bytes, loaded by ogr2ogr into this attempt's table."""

    task = "reupload_file"
    staging = True
    raster_row = False
    catalog_event = "reupload_swap_catalog"

    def __init__(self, *, job_id: str, dataset_id: str, file_path: str, user_id: str):
        self.job_id = job_id
        self.dataset_uuid = uuid.UUID(dataset_id)
        self.file_path = file_path
        self.original_file_path = file_path
        self.user_id = user_id
        # Set when the upload fails the safety checks: recorded, not raised.
        self.refused = False
        self.owned_staging_key: str | None = None

    def prepare(self, job, dataset, staging_table: str) -> None:
        # Read off the row, not the local `file_path` a download rebinds.
        self.owned_staging_key = owned_presigned_staging_key(
            job.id, job.user_metadata, job.file_path
        )
        self.staging_table = staging_table
        self.source_filename = job.source_filename
        self.user_metadata = job.user_metadata or {}
        self.prior_record_type = dataset.record.record_type
        self.prior_geometry_type = dataset.geometry_type
        # The user-chosen layer of a multi-layer file.
        self.layer_name = job.source_layer

    async def fetch(self) -> None:
        from app.core.db import async_session
        from app.processing.ingest.ogr import build_pg_conn_str, run_ogr2ogr
        from app.processing.ingest.service import resolve_file_path

        self.file_path = await resolve_file_path(self.file_path, self.job_id)
        # Validate file content and safety before ogr2ogr.
        async with async_session() as session:
            try:
                await _validate_upload_file_safety(
                    session,
                    file_path=self.file_path,
                    source_filename=self.source_filename,
                )
            except ValueError:
                self.refused = True
                raise

        # Detect CRS from the new file, enforce the missing-CRS gate, and
        # resolve the effective SRID (override > detected > 4326).
        self.info, self.effective_srid = await _detect_reupload_crs(
            self.file_path,
            self.layer_name,
            self.user_metadata,
            original_filename=self.source_filename,
            record_type=self.prior_record_type,
            dataset_geometry_type=self.prior_geometry_type,
        )
        self.srid = self.info.get("srid")
        await run_ogr2ogr(
            self.file_path,
            self.staging_table,
            build_pg_conn_str(),
            source_srid=self.srid,
            geometry_type=self.info.get("geometry_type"),
            layer_name=self.layer_name,
            schema=_current_tenant_schema(),
            effective_srid=self.effective_srid,
            original_filename=self.source_filename,
        )
        self.file_hash = await asyncio.to_thread(sha256_file, self.file_path)
        self.source_format = await asyncio.to_thread(
            derive_source_format, self.file_path
        )

    async def stage(self, session, job, dataset) -> Verdict:
        # Rename source columns that collide with GeoLens-internal names,
        # before the post-process steps so they cannot clash.
        from app.processing.ingest.metadata import rename_reserved_columns

        reserved_renames = await rename_reserved_columns(
            session, self.staging_table, schema=_current_tenant_schema()
        )
        if reserved_renames:
            from app.processing.ingest.warnings import make_reserved_rename_warning

            _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

        # Shapefile-only: detect DBF 10-char truncation collisions. Keyed on
        # the derived format, not the .zip suffix: a File Geodatabase arrives
        # in a .zip too and has no DBF to truncate.
        if self.source_format == "shapefile":
            from app.processing.ingest.metadata import (
                detect_dbf_truncation_collisions,
            )
            from app.processing.ingest.ogr import run_ogrinfo_preview
            from app.processing.ingest.warnings import make_dbf_truncation_warning

            preview_cols = self.info.get("columns") or []
            if not preview_cols:
                preview_info = await run_ogrinfo_preview(
                    self.file_path, sample_limit=0, layer_name=self.layer_name
                )
                preview_cols = preview_info.get("columns") or []
            dbf_collisions = detect_dbf_truncation_collisions(preview_cols)
            if dbf_collisions:
                _append_job_warning(job, make_dbf_truncation_warning(dbf_collisions))
                structlog.get_logger().warning(
                    "Shapefile DBF 10-char truncation collision detected",
                    table=self.staging_table,
                    collisions=dbf_collisions,
                )

        staging_result = await _run_staging_pipeline(
            session,
            table_name=self.staging_table,
            has_geometry=self.info.get("geometry_type") is not None,
            effective_srid=self.effective_srid,
        )
        # The staging table, measured in the swap's transaction and never
        # carried forward from the preview, which can be minutes old.
        self.measurement = await catalog_projection.measure(
            session,
            dataset,
            table=self.staging_table,
            schema=_current_tenant_schema(),
            staged=staging_result,
        )
        # Tell the user when the Web Mercator clamp destroyed geometry,
        # instead of leaving them to discover it downstream.
        _append_mercator_clip_warning(job, staging_result.mercator_clip)
        return PUBLISH

    async def install(self, session, dataset) -> None:
        await _install_reupload_table(
            session,
            dataset=dataset,
            staging_table=self.staging_table,
            measurement=self.measurement,
        )

    async def write(self, session, dataset) -> Published:
        version, schema_diff = await _write_reupload_catalog(
            session,
            dataset=dataset,
            measurement=self.measurement,
            user_id=self.user_id,
            source_filename=self.source_filename,
            source_format=self.source_format,
            original_srid=self.srid,
            file_hash=self.file_hash,
            # The new bytes came from a file, so the binding says upload, even
            # when the dataset was a registered table or service.
            origin_ref={"filename": self.source_filename, "file_hash": self.file_hash},
        )
        # A manifest re-apply lands here carrying the manifest's current
        # attribution, which replaces the old credit.
        await apply_manifest_record_metadata(
            session, dataset.record, self.user_metadata
        )
        # The bytes came from the browser, so nothing remote was contacted.
        return Published(
            dataset_version_id=version.id,
            feature_count=self.measurement.metadata.get("feature_count"),
            schema_diff=schema_diff,
            contacted_origin=False,
            live_table=dataset.table_name,
        )

    def classify(self, exc: BaseException) -> Failure:
        if self.refused:
            return Failure("validation_failed", refused=True)
        return Failure(_file_refresh_error_code(exc))

    async def release(
        self, *, publication: PublicationCommit | None, failed: bool
    ) -> None:
        # A cancelled archive must not skip the cleanup after it.
        try:
            # The archive key is named after the file, so after an unconfirmed
            # publish it could overwrite the original of the version still live.
            if publication is not None and publication.confirmed:
                async with cleanup_step("reupload_file archive", job_id=self.job_id):
                    await self._archive()
        finally:
            await self._clean_up(
                "complete"
                if publication is PublicationCommit.ACKNOWLEDGED
                else "failed"
                if failed
                else "pending"
            )

    async def _clean_up(self, final_status: str) -> None:
        # A publish seen only through the probe is "pending", which keeps the
        # upload. The local file goes on success, and on failure only when it
        # was a download (storage holds the source) or an unsafe upload.
        async with cleanup_step("reupload_file local file", job_id=self.job_id):
            if (
                final_status == "complete"
                or self.refused
                or self.file_path != self.original_file_path
            ):
                Path(self.file_path).unlink(missing_ok=True)
        # The object the task downloaded from, which after a presigned
        # completion is the frozen copy the job is bound to.
        async with cleanup_step("reupload_file downloaded source", job_id=self.job_id):
            await reap_downloaded_staging_source(
                self.job_id,
                original_file_path=self.original_file_path,
                final_status=final_status,
                # _retry_capability refuses reupload jobs outright, so nothing
                # else will ever reap this; reap on failure too.
                failed_source_replayable=False,
            )
        # The presigned staging key, which no other reaper sweeps.
        async with cleanup_step(
            "reupload_file presigned staging object", job_id=self.job_id
        ):
            await reap_presigned_staging_object(
                self.job_id, self.owned_staging_key, final_status=final_status
            )

    async def _archive(self) -> None:
        from app.core.db import async_session
        from app.platform.jobs.models import IngestJob

        async with async_session() as session:
            job = await session.get(IngestJob, uuid.UUID(self.job_id))
            if job is not None:
                await _archive_original_file(
                    session,
                    job=job,
                    dataset_id=self.dataset_uuid,
                    file_path=self.file_path,
                    log_message="Failed to archive re-uploaded file to storage",
                )


@task_app.task(queue="ingest", retry=0, aliases=["app.ingest.tasks.reupload_file"])
@tenant_task
async def reupload_file(
    job_id: str,
    dataset_id: str,
    file_path: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: replace dataset data via staging table swap."""
    _bind_task_log_context(
        task_name="reupload_file", job_id=job_id, dataset_id=dataset_id
    )
    await settle_replacement(
        _FileReupload(
            job_id=job_id, dataset_id=dataset_id, file_path=file_path, user_id=user_id
        ),
        job_id=job_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
    )


def _file_refresh_error_code(exc: BaseException) -> str:
    """Map a file-reupload failure onto its run ``error_code``.

    A contended catalog row reports as contention: nothing was written, and
    the reader's next step is to find the holder, not to inspect the file.
    """
    if isinstance(exc, CatalogLockConflict):
        return CATALOG_LOCK_CONFLICT_CODE
    return "file_refresh_failed"


async def _resolve_service_token(
    token: str | None, credential_ref: str | None
) -> str | None:
    """The credential this attempt will fetch with, redeeming a ref if given.

    feat(#1220); fix(#1676) moved the body to
    ``platform.refresh.credentials.resolve_worker_credential`` so
    ``ingest_service`` redeems the same way without either task module
    importing the other. Kept as the name this task and its tests reach for.
    """
    return await resolve_worker_credential(token, credential_ref)


async def _fetch_service_layer_with_paging_guard(
    *,
    service_type_raw: str,
    service_type: str,
    source_url: str,
    layer_name: str,
    layer_id,
    token: str | None,
    staging_table: str,
    db_conn_str: str,
    schema: str,
    fallback_order_field: str | None,
    on_spawn,
    verification_policy: str | None = None,
) -> tuple[int | None, object | None]:
    """Fetch a service layer into staging, paging large ArcGIS layers.

    fix(#1675): parity with the initial-import path. A refresh of a large
    ArcGIS layer used to do ONE unpaged fetch and trust GDAL driver paging —
    the exact behavior the import path's guarded loop exists to distrust.
    Same criteria, same shared loop (tasks_common); the page-info fetch
    resolves through tasks_vector's module attribute so test monkeypatches
    cover both doors.
    """
    from app.platform.extensions import get_processing_port
    from app.platform.security import make_safe_client
    from app.processing.ingest import tasks_vector as _tv
    from app.processing.ingest.ogr import run_ogr2ogr_service
    from app.processing.ingest.tasks_common import run_paged_arcgis_service_fetch

    port = get_processing_port()
    page_size = _tv._ARCGIS_SERVICE_IMPORT_CHUNK_SIZE
    feature_count = None
    supports_pagination = False
    pagination_order_field = None
    id_plan = None
    if service_type == "arcgis_featureserver":
        # fix(#1675): the page-info probe is the FIRST outbound
        # contact of a refresh and can fail before any subprocess exists to
        # fire on_spawn, so arm the contact stamp here too (monotonic OR —
        # later per-page spawns re-arming is harmless).
        if on_spawn is not None:
            on_spawn()
        (
            feature_count,
            max_record_count,
            supports_pagination,
            pagination_order_field,
        ) = await _tv._fetch_arcgis_import_page_info(source_url, layer_id, token)
        if max_record_count is not None:
            page_size = max(1, min(page_size, max_record_count))
        if verification_policy == "arcgis_id_set_v1":
            try:
                async with make_safe_client(timeout=30.0) as client:
                    id_plan = await port.fetch_arcgis_id_plan(
                        source_url,
                        layer_id,
                        client,
                        token=token,
                        expected_oid_field=(
                            pagination_order_field or fallback_order_field
                        ),
                    )
            except ValueError as exc:
                from app.processing.ingest.ogr import IngestionError

                raise IngestionError(f"ArcGIS ID plan unavailable: {exc}") from exc
            if id_plan.count:
                await run_paged_arcgis_service_fetch(
                    service_type_raw=service_type_raw,
                    service_type=service_type,
                    source_url=source_url,
                    layer_name=layer_name,
                    layer_id=layer_id,
                    token=token,
                    staging_table=staging_table,
                    db_conn_str=db_conn_str,
                    schema=schema,
                    feature_count=id_plan.count,
                    page_size=page_size,
                    order_field=id_plan.oid_field,
                    on_spawn=on_spawn,
                    planned_ids=id_plan.ids,
                )
                return feature_count, id_plan
    if (
        service_type == "arcgis_featureserver"
        and supports_pagination
        and pagination_order_field is not None
        and feature_count is not None
        and feature_count > page_size
    ):
        await run_paged_arcgis_service_fetch(
            service_type_raw=service_type_raw,
            service_type=service_type,
            source_url=source_url,
            layer_name=layer_name,
            layer_id=layer_id,
            token=token,
            staging_table=staging_table,
            db_conn_str=db_conn_str,
            schema=schema,
            feature_count=feature_count,
            page_size=page_size,
            order_field=pagination_order_field,
            on_spawn=on_spawn,
        )
        return feature_count, id_plan

    gdal_source, layer_arg = port.build_gdal_source(
        service_type_raw,
        source_url,
        layer_name,
        layer_id,
        token=token,
        order_field=fallback_order_field,
    )
    await run_ogr2ogr_service(
        gdal_source,
        layer_arg,
        staging_table,
        db_conn_str,
        service_type,
        token=token,
        schema=schema,
        on_spawn=on_spawn,
    )
    return feature_count, id_plan


async def _arcgis_id_coverage_evidence(
    session,
    *,
    initial_id_plan,
    schema: str,
    table_name: str,
    source_url: str,
    layer_id,
    token: str | None,
) -> dict | None:
    """Return compact pre/post ArcGIS membership evidence for a staged fetch."""
    if initial_id_plan is None:
        return None

    from app.platform.extensions import get_processing_port
    from app.platform.security import make_safe_client
    from app.processing.ingest.tasks_common import verify_arcgis_staged_oid_coverage

    coverage = await verify_arcgis_staged_oid_coverage(
        session,
        schema=schema,
        table_name=table_name,
        oid_field=initial_id_plan.oid_field,
        planned_ids=initial_id_plan.ids,
    )
    try:
        async with make_safe_client(timeout=30.0) as client:
            final_id_plan = await get_processing_port().fetch_arcgis_id_plan(
                source_url,
                layer_id,
                client,
                token=token,
                expected_oid_field=initial_id_plan.oid_field,
            )
    except ValueError:
        coverage["source_membership_status"] = "unavailable"
    else:
        coverage["source_membership_status"] = (
            "matched" if final_id_plan.digest == initial_id_plan.digest else "changed"
        )
        coverage["source_marker_before"] = initial_id_plan.source_marker
        coverage["source_marker_after"] = final_id_plan.source_marker
    return coverage


async def _staged_geometry_contract(
    session, *, schema: str, table: str
) -> tuple[str | None, int | None, int | None]:
    row = (
        await session.execute(
            text(
                "SELECT type, srid, coord_dimension FROM geometry_columns "
                "WHERE f_table_schema = :schema AND f_table_name = :table "
                "AND f_geometry_column = 'geom'"
            ),
            {"schema": schema, "table": table},
        )
    ).one_or_none()
    if row is None:
        return None, None, None
    return row.type, int(row.srid), int(row.coord_dimension)


def _matches_service_origin(
    bound: tuple,
    *,
    source_format: str,
    source_url: str,
    layer_id,
    layer_name: str,
) -> bool:
    """Return whether a fetch still describes the dataset's stored source."""
    stored_ref = bound[1] or {}
    return (
        classify_origin(bound[2]) == "service"
        and stored_ref.get("service_type") == source_format
        and stored_ref.get("url") == source_url
        and stored_ref.get("layer_id")
        == service_layer_identity(
            source_format,
            layer_id=layer_id,
            layer_name=layer_name,
        )
    )


def _require_service_source_url(value: str | None) -> str:
    """Return a usable service URL or fail the re-upload job."""
    if not value:
        from app.processing.ingest.ogr import IngestionError

        raise IngestionError("Missing service source URL for re-upload commit job.")
    return value


class RefreshPublicationFenceError(RuntimeError):
    """A durable source or local-edit publication fence refused the swap."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _service_refresh_error_code(exc: BaseException) -> str:
    """Map a service re-upload failure onto the refresh-run vocabulary."""
    from app.platform.refresh.credentials import (
        CredentialExpiredError,
        CredentialStoreUnavailable,
    )

    if isinstance(exc, CatalogLockConflict):
        return CATALOG_LOCK_CONFLICT_CODE
    if isinstance(exc, CredentialExpiredError):
        return "credential_expired"
    if isinstance(exc, CredentialStoreUnavailable):
        return "credential_store_unavailable"
    if isinstance(exc, RefreshPublicationFenceError):
        return exc.code
    if getattr(exc, "code", None) in (498, 499):
        return "credential_expired"
    return "service_refresh_failed"


async def _enforce_refresh_publication_fence(
    session,
    *,
    job_id: uuid.UUID,
    dataset,
    verification: dict | None,
) -> None:
    """Refuse a late swap after a scheduled source rebind or local edit."""
    if verification is None:
        return

    from app.platform.extensions import get_processing_port
    from app.platform.refresh.models import DatasetRefreshRun

    run = await session.scalar(
        select(DatasetRefreshRun).where(DatasetRefreshRun.ingest_job_id == job_id)
    )
    if run is None or run.source_binding_fingerprint is None:
        return

    record_cls = get_processing_port().get_record_orm_class()
    current_origin, current_record_modified_at = (
        await session.execute(
            select(dataset.__class__.origin_ref, record_cls.updated_at)
            .join(record_cls, record_cls.id == dataset.record_id)
            .where(dataset.__class__.id == dataset.id)
        )
    ).one()
    if not isinstance(current_origin, dict):
        raise RefreshPublicationFenceError(
            "source_changed", "Refresh source changed before publication."
        )
    try:
        current_fingerprint = (
            refresh_policy.canonical_service_source_binding_fingerprint(current_origin)
        )
    except ValueError as exc:
        raise RefreshPublicationFenceError(
            "source_changed", "Refresh source changed before publication."
        ) from exc
    if current_fingerprint != run.source_binding_fingerprint:
        raise RefreshPublicationFenceError(
            "source_changed", "Refresh source changed before publication."
        )
    if (
        run.local_edit_baseline is not None
        and current_record_modified_at is not None
        and current_record_modified_at > run.local_edit_baseline
    ):
        raise RefreshPublicationFenceError(
            "local_edits_changed", "Dataset changed locally before refresh publication."
        )


async def _stage_service_table(
    session, job, dataset, *, table: str, schema: str
) -> StagingResult:
    """Bring a fetched service layer's staging table to the shape first ingest builds."""
    from app.processing.ingest.metadata import rename_reserved_columns

    # Before staging, so no source column clashes with a GeoLens-internal name.
    reserved_renames = await rename_reserved_columns(session, table, schema=schema)
    if reserved_renames:
        from app.processing.ingest.warnings import make_reserved_rename_warning

        _append_job_warning(job, make_reserved_rename_warning(reserved_renames))

    # A service layer is fetched into 4326, and whether it has geometry is
    # learned from the staged table.
    staged = await _run_staging_pipeline(
        session, table_name=table, has_geometry=None, effective_srid=4326
    )
    # The file door's geometry-loss refusal, before the swap DDL.
    _assert_geometry_survives(
        record_type=dataset.record.record_type,
        geometry_type=dataset.geometry_type,
        has_geometry=staged.has_geometry,
    )
    _append_mercator_clip_warning(job, staged.mercator_clip)
    return staged


class _ServiceReupload:
    """A remote service layer, fetched by ogr2ogr into this attempt's table.

    A refresh is verified against its source binding before it publishes.
    """

    task = "reupload_service"
    staging = True
    raster_row = False
    catalog_event = "reupload_swap_catalog"

    def __init__(
        self,
        *,
        job_id: str,
        source_url: str,
        source_layer: str,
        user_id: str,
        token: str | None,
        credential_ref: str | None,
        options: dict,
    ):
        self.job_uuid = uuid.UUID(job_id)
        self.source_url = source_url
        self.source_layer = source_layer
        self.user_id = user_id
        self.token = token
        self.credential_ref = credential_ref
        self.options = options
        # Whether the outbound fetch was reached, so a failure can date the
        # contact.
        self.contacted = False
        self.measured_feature_count: int | None = None
        self.measured_schema_diff: dict | None = None
        self.verification: dict | None = None

    def prepare(self, job, dataset, staging_table: str) -> None:
        self.staging_table = staging_table
        # A failure's contact stamp lands only while the dataset keeps the
        # origin this attempt fetched from.
        self.bound = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)
        um = job.user_metadata or {}
        self.service_type_raw = um.get("service_type", "")
        self.layer_id = um.get("layer_id")
        self.job_source_url = job.source_url
        self.source_layer_value = job.source_layer or self.source_layer
        self.source_filename = job.source_filename
        self.oid_field = um.get("object_id_field") or None
        # router_refresh writes "refresh" into user_metadata, so the
        # auth-failure copy can name the call the operator made.
        self.is_refresh = bool(um.get("refresh"))
        self.accepted_fingerprint = um.get("accepted_refresh_fingerprint")
        self.accepted_run_id = um.get("accepted_refresh_run_id")
        self.verification_policy = self.options.get(
            "verification_policy", um.get("verification_policy")
        )

    async def fetch(self) -> None:
        from app.platform.security import SSRFError, validate_url_for_ssrf
        from app.processing.ingest.ogr import IngestionError, build_pg_conn_str

        self.source_url_value = _require_service_source_url(
            self.job_source_url or self.source_url
        )
        self.service_type, self.source_format = resolve_service_type(
            self.service_type_raw
        )
        # Checked again here, on the URL this fetch uses: the route-level check
        # covers the preview→commit TOCTOU, but manifest reuploads skip that
        # route entirely.
        try:
            await validate_url_for_ssrf(self.source_url_value)
        except SSRFError as exc:
            raise SourceURLRefused(
                f"source_url failed safety check at worker fetch time: {exc}"
            ) from exc
        self.token = await _resolve_service_token(self.token, self.credential_ref)

        # The stamp may only describe the stored origin, so it arms only
        # when the whole attempted binding equals the stored one.
        matches_binding = _matches_service_origin(
            self.bound,
            source_format=self.source_format,
            source_url=self.source_url_value,
            layer_id=self.layer_id,
            layer_name=self.source_layer_value,
        )

        def _arm_contact() -> None:
            # Fired the instant the subprocess exists, the first moment an
            # outbound attempt truthfully began. Monotonic, so a retry that
            # dies locally cannot erase its first attempt's contact.
            self.contacted = self.contacted or matches_binding

        db_conn_str = build_pg_conn_str()
        self.expected_feature_count: int | None = None
        self.initial_id_plan = None

        async def _run_service_import(layer_name: str) -> None:
            (
                self.expected_feature_count,
                self.initial_id_plan,
            ) = await _fetch_service_layer_with_paging_guard(
                service_type_raw=self.service_type_raw,
                service_type=self.service_type,
                source_url=self.source_url_value,
                layer_name=layer_name,
                layer_id=self.layer_id,
                token=self.token,
                staging_table=self.staging_table,
                db_conn_str=db_conn_str,
                schema=_current_tenant_schema(),
                fallback_order_field=self.oid_field,
                on_spawn=_arm_contact,
                verification_policy=self.verification_policy,
            )

        try:
            await _run_service_import_with_wfs_fallback(
                _run_service_import,
                self.source_layer_value,
                token=self.token,
                # Serves only the refresh endpoint and the re-upload commit, and
                # says "credential"/`auth` because a bearer token can't
                # authenticate a basic or named-key origin.
                auth_error_message=(
                    "Remote service authentication failed. Retry the refresh "
                    "with the credential in the request body's `auth` object; "
                    "credentials are request-only and are not stored between "
                    "runs."
                    if self.is_refresh
                    else "Remote service authentication failed. Retry the "
                    "re-upload with the credential in the commit request's "
                    "`auth` object; credentials are request-only and are not "
                    "stored between runs."
                ),
            )
        except ValueError as exc:
            raise IngestionError(str(exc)) from exc

    async def stage(self, session, job, dataset) -> Verdict:
        from app.processing.ingest.metadata import compute_table_content_digest

        schema = _current_tenant_schema()
        staged = await _stage_service_table(
            session, job, dataset, table=self.staging_table, schema=schema
        )
        self.metadata = staged.metadata
        self.measurement = await catalog_projection.measure(
            session,
            dataset,
            table=self.staging_table,
            schema=schema,
            staged=staged,
            score=False,
        )
        # Verification compares this fetch, not the preview's: a live
        # service can have changed since the preview was taken.
        self.measured_schema_diff = catalog_projection.schema_diff(
            dataset, self.measurement
        )
        self.measured_feature_count = staged.metadata.get("feature_count")
        if not self.is_refresh:
            return PUBLISH

        geometry_type, srid, coordinate_dimension = await _staged_geometry_contract(
            session, schema=schema, table=self.staging_table
        )
        credential_version = self.options.get("credential_version")
        source_binding = {
            "service_type": self.source_format,
            "url": self.source_url_value,
            "layer_id": service_layer_identity(
                self.source_format,
                layer_id=self.layer_id,
                layer_name=self.source_layer_value,
            ),
            "verification_policy": self.verification_policy,
            "credential_version": (
                credential_version if isinstance(credential_version, str) else None
            ),
            "arcgis_id_coverage": await _arcgis_id_coverage_evidence(
                session,
                initial_id_plan=self.initial_id_plan,
                schema=schema,
                table_name=self.staging_table,
                source_url=self.source_url_value,
                layer_id=self.layer_id,
                token=self.token,
            ),
        }
        self.verification = refresh_policy.verify_service_refresh(
            source_binding=source_binding,
            schema_diff=self.measured_schema_diff,
            expected_feature_count=self.expected_feature_count,
            fetched_feature_count=self.measured_feature_count,
            content_digest=await compute_table_content_digest(
                session,
                self.staging_table,
                schema=schema,
                has_geometry=staged.has_geometry,
            ),
            staged_geometry_type=geometry_type,
            staged_srid=srid,
            staged_coordinate_dimension=coordinate_dimension,
            accepted_fingerprint=self.accepted_fingerprint,
            accepted_run_id=self.accepted_run_id,
        )
        if self.verification["decision"] == "allowed":
            return PUBLISH
        rejected = self.verification["decision"] == "rejected"
        if rejected:
            error_code, message = refresh_policy.refresh_rejection_diagnostic(
                self.verification
            )
        else:
            error_code = "review_required"
            message = "Review the detected changes before publication."
        return Verdict(
            publish=False,
            reason=message,
            settle=partial(
                self._hold_back,
                dataset=dataset,
                rejected=rejected,
                error_code=error_code,
                message=message,
            ),
            # A blocked refresh waits for review; a rejected one has failed.
            notify=rejected,
        )

    async def _hold_back(
        self, session, *, dataset, rejected: bool, error_code: str, message: str
    ) -> None:
        dataset.last_checked_at = datetime.now(timezone.utc)
        dataset.schema_drift_status = drift_status_from_diff(self.measured_schema_diff)
        if rejected:
            await record_refresh_failure(
                session,
                ingest_job_id=self.job_uuid,
                error_code=error_code,
                error_message=message,
                feature_count_after=self.measured_feature_count,
                schema_diff=self.measured_schema_diff,
                verification=self.verification,
            )
        else:
            await record_refresh_blocked(
                session,
                ingest_job_id=self.job_uuid,
                feature_count_after=self.measured_feature_count,
                schema_diff=self.measured_schema_diff,
                verification=self.verification,
            )

    async def install(self, session, dataset) -> None:
        # Scored once publication is allowed: the quality scan reads the
        # whole staged table.
        self.measurement = await catalog_projection.scored(
            session,
            dataset,
            self.measurement,
            table=self.staging_table,
            schema=_current_tenant_schema(),
        )
        await _install_reupload_table(
            session,
            dataset=dataset,
            staging_table=self.staging_table,
            measurement=self.measurement,
        )

    async def write(self, session, dataset) -> Published:
        # Runs under the catalog rows, so a rebind or local edit that lands
        # first rolls back the rename before it is published.
        await _enforce_refresh_publication_fence(
            session,
            job_id=self.job_uuid,
            dataset=dataset,
            verification=self.verification,
        )
        source_binding_layer = service_layer_identity(
            self.source_format,
            layer_id=self.layer_id,
            layer_name=self.source_layer_value,
        )
        version, schema_diff = await _write_reupload_catalog(
            session,
            dataset=dataset,
            measurement=self.measurement,
            user_id=self.user_id,
            source_filename=self.source_filename or self.source_layer_value,
            source_format=self.source_format,
            original_srid=self.metadata.get("srid"),
            source_url=(
                f"{self.source_url_value}/{self.layer_id}"
                if self.layer_id is not None
                else self.source_url_value
            ),
            origin_ref={
                "service_type": self.source_format,
                "url": self.source_url_value,
                "layer_id": source_binding_layer,
                "auth_required": True if self.token else None,
            },
        )
        return Published(
            dataset_version_id=version.id,
            feature_count=self.measured_feature_count,
            schema_diff=schema_diff,
            contacted_origin=True,
            verification=self.verification,
            live_table=dataset.table_name,
        )

    def classify(self, exc: BaseException) -> Failure:
        # Exact-value scrub first, in place, before anything reads `exc`: only
        # this task knows the credential's literal value.
        scrub_secret_from_exception(exc, self.token)
        return Failure(
            _service_refresh_error_code(exc),
            feature_count_after=self.measured_feature_count,
            schema_diff=self.measured_schema_diff,
            verification=self.verification,
            contacted=self.bound if self.contacted else None,
        )

    async def release(
        self, *, publication: PublicationCommit | None, failed: bool
    ) -> None:
        return None


@task_app.task(
    queue="ingest",
    retry=0,
    # fix(#1746): the context is how the task learns its own queue-row id, so
    # a terminal failure can strip the raw token out of its own kwargs.
    pass_context=True,
    aliases=["app.ingest.tasks.reupload_service"],
)
@tenant_task
@purge_token_on_failure
@require_scheduled_execution_claim
async def reupload_service(
    job_id: str,
    dataset_id: str,
    source_url: str,
    source_layer: str,
    user_id: str,
    attempt_id: str | None = None,
    token: str | None = None,
    credential_ref: str | None = None,
    **kwargs,
) -> None:
    """Background task: replace dataset data from a remote service source.

    Two dispatching doors since feat(#1676) hand a credential the same
    way: ``credential_ref``, a single-use reference redeemed once here for
    a secret that never touched a committed row. ``token`` is the
    surviving durable argument, produced only when no shared credential
    store is configured (state 3 in ``platform/refresh/credentials``).
    Both optional, at most one ever set — the reference wins if both
    somehow are. Neither required: a public service needs no credential.
    """
    _bind_task_log_context(
        task_name="reupload_service", job_id=job_id, dataset_id=dataset_id
    )
    await settle_replacement(
        _ServiceReupload(
            job_id=job_id,
            source_url=source_url,
            source_layer=source_layer,
            user_id=user_id,
            token=token,
            credential_ref=credential_ref,
            options=kwargs,
        ),
        job_id=job_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
    )


# Verified refreshes use a task name introduced with the publication protocol;
# pre-change workers therefore cannot run them through the ordinary reupload door.
reupload_verified_refresh = task_app.task(
    reupload_service.func,
    queue="ingest",
    retry=0,
    name="app.ingest.tasks.reupload_verified_refresh",
    pass_context=True,
)
