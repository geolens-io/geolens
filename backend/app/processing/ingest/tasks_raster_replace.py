"""Procrastinate task: replace the COG behind an existing raster dataset.

feat(#1221): replaces a raster's ``RasterAsset`` pointer in place rather
than deleting and re-importing (which loses the dataset id, grants, and
every map layer pointing at it). Raster peer of
``tasks_reupload.reupload_file`` — same door, same admission gate, same
refresh-run bookkeeping, but no staging table to rename.

**Invariant 10, last-known-good is sacred.** The previous COG is not
deleted or overwritten until the replacement is written to storage AND
read back successfully. The new asset lands under keys derived from this
attempt's id and content hash (collides with neither the live asset's nor
another attempt's — see ``attempt_scoped_raster_base_key``); the pointer
moves in one transaction alongside the tile-cache bump; superseded
objects are reaped only after that commit. Every failure before the
commit leaves the old COG serving tiles.

**ADR-002 Decision 7** governs the *incoming* file: the pre-conversion
upload is deleted once conversion succeeds, retained (bounded by the
retention purge) when it fails — a failed conversion makes those bytes
the operator's only diagnostic copy. See ``RUNBOOK.md`` section 9.
"""

import asyncio
import io
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import structlog
from sqlalchemy import select

from app.core.db.tenant_session import tenant_task
from app.platform.catalog_locks import CATALOG_LOCK_CONFLICT_CODE, CatalogLockConflict
from app.platform.jobs.heartbeat import StaleIngestAttempt
from app.platform.jobs.models import owned_presigned_staging_key
from app.processing.raster.cog import (
    _scratch_dir,
    check_and_prepare_cog,
    cog_preserves_source,
    resolve_crs_assignment,
    sha256_file,
)
from app.processing.raster.probe import (
    RasterProbeError,
    read_raster_metadata,
    render_quicklook,
)

from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    cleanup_step,
    _job_phase_session,
    task_app,
)
from app.processing.ingest.tasks_staging import (
    _validate_upload_file_safety,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
)
from app.processing.ingest.publication import (
    PUBLISH,
    Failure,
    PublicationCommit,
    Published,
    Verdict,
    settle_replacement,
)
from app.processing.ingest.tasks_raster_common import (
    _cleanup_orphaned_storage_keys,
    _enforce_strict_cog,
    _resolve_managed_raster_storage_keys,
    attempt_scoped_raster_base_key,
    inspect_source_raster,
    record_unpublished_storage_keys,
)
from app.processing.ingest.tasks_raster_swap import (
    _prior_asset_keys_to_reap,
    archive_lossy_original,
    archived_original_asset_key,
    upsert_archived_original_row,
    reserve_replacement_bytes,
    _upsert_managed_asset_rows,
    _write_swapped_fields,
)

logger = structlog.get_logger(__name__)


def _raster_refresh_error_code(exc: BaseException) -> str:
    """Map a raster-replace failure onto its run ``error_code``.

    A contended catalog row reports as contention: nothing was written, and
    the reader's next step is to find the holder, not to inspect the raster.
    """
    if isinstance(exc, CatalogLockConflict):
        return CATALOG_LOCK_CONFLICT_CODE
    return "raster_refresh_failed"


class RasterReplaceError(Exception):
    """A raster replace that failed for a reason the user can act on."""


async def _read_published_cog(cog_path: str) -> dict:
    """Read the freshly written COG back, and return what it actually says.

    Two jobs, one read, on purpose.

    First is the "verified readable" half of invariant 10 — conversion
    exiting 0 isn't the same fact as the output being openable (truncated
    write, out-of-space overview pass, driver quirk), and the next steps
    discard the last-known-good asset, so this must be an explicit check.

    Second (fix(#1290)) is the catalog's metadata: reading it from
    the artifact that WILL serve, once, means no second seam that can
    drift from the first — the pre-conversion source describes a file the
    dataset no longer serves (compression always changes, nodata/CRS/
    footprint change under an override).

    fix(#1291): footprint stays on that list even though ``srid_override``
    no longer moves the corner coordinates — it changes what they MEAN, so
    reading them off the source would place the dataset at the wrong spot
    with no field visibly disagreeing.

    Goes through the probe child, like every other raster read.
    """
    try:
        return await asyncio.to_thread(read_raster_metadata, cog_path)
    except RasterProbeError as exc:
        raise RasterReplaceError(
            f"Converted COG could not be read back. {exc} "
            "The dataset still serves its previous raster."
        ) from None


async def _stamp_progress(
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    *,
    phase: str,
    step: str,
    progress: float,
) -> None:
    """Advance the job's mid-flight progress in its own brief session.

    Conversion and quicklooks are the two multi-minute steps, and without a
    checkpoint between them the UI shows a dead spinner. Only a running job is
    stamped, so the step a cancel or sweep wrote stands. The session never
    spans the GDAL work either side of it.
    """
    async with _job_phase_session(
        job_uuid, phase=phase, attempt_id=attempt_uuid, require_status="running"
    ) as (session, job):
        if job is None:
            return
        job.current_step = step
        job.progress = progress
        await session.commit()


async def _convert_and_verify_cog(
    file_path: str,
    tmp_dir: str,
    *,
    inspection: dict,
    compression: str,
    resampling: str | None,
    nodata: object,
    assign_crs: int | None,
) -> tuple[str, str, dict]:
    """Convert to COG and read the result back.

    Returns ``(path, cog_status, metadata_of_the_converted_file)`` — that
    third element is what the catalog persists (fix(#1290)); see
    ``_read_published_cog`` for why it comes from here, not the source.

    Disk-space precheck lives here because it guards this conversion
    specifically: COG output can reach ~3x the source. fix(#448): the
    scratch directory must already be on the staging volume, not the
    container's RAM-backed /tmp, or this measures the wrong filesystem.
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
        inspection=inspection,
        compression=compression,
        resampling=resampling,
        nodata=nodata,
        assign_crs=assign_crs,
    )
    # Invariant 10's gate. Everything before this line is reversible;
    # everything after it starts moving pointers.
    cog_meta = await _read_published_cog(local_cog_path)
    return local_cog_path, cog_status, cog_meta


class _RasterReplace:
    """An uploaded raster, converted to a COG and put under this attempt's keys."""

    task = "reupload_raster"
    staging = False
    raster_row = True
    catalog_event = "raster_replace_catalog"

    def __init__(self, *, job_id: str, dataset_id: str, file_path: str, user_id: str):
        self.job_id = job_id
        self.job_uuid = uuid.UUID(job_id)
        self.dataset_uuid = uuid.UUID(dataset_id)
        self.file_path = file_path
        self.original_file_path = file_path
        self.user_id = user_id
        # Set when the upload fails the safety checks: recorded, not raised.
        self.refused = False
        self.owned_staging_key: str | None = None
        self.tmp_dir: str | None = None
        # Each reap takes one list minus the other, so no path deletes a key
        # the live asset names. Attempt-scoped keys never overlap the live
        # ones, so this is a second guard.
        self.written_storage_keys: list[str] = []
        self.prior_physical_keys: list[str] = []
        # The upload may be deleted only once the COG is known to carry
        # everything it did, or its original is archived.
        self.source_preserved_in_cog = False
        self.lossy_original_archived = False
        self.job = None

    def prepare(self, job, dataset, staging_table: str) -> None:
        self.attempt_uuid = job.attempt_id
        # Read off the row, not the local `file_path` a download rebinds.
        self.owned_staging_key = owned_presigned_staging_key(
            job.id, job.user_metadata, job.file_path
        )
        self.source_filename = job.source_filename
        self.options = job.user_metadata or {}

    async def fetch(self) -> None:
        from app.core.db import async_session
        from app.processing.ingest.service import resolve_file_path
        from app.processing.raster.models import RasterAsset

        await self._progress("validating", 0.0)
        async with async_session() as session:
            raster_asset = await session.scalar(
                select(RasterAsset).where(RasterAsset.dataset_id == self.dataset_uuid)
            )
            if raster_asset is None:
                raise RasterReplaceError(
                    f"Raster dataset {self.dataset_uuid} has no raster asset to replace."
                )
            live = (
                raster_asset.asset_uri,
                raster_asset.quicklook_256_uri,
                raster_asset.quicklook_512_uri,
            )
        self.prior_physical_keys = _prior_asset_keys_to_reap(
            asset_uri=live[0], quicklook_256_uri=live[1], quicklook_512_uri=live[2]
        )

        self.file_path = await resolve_file_path(self.file_path, self.job_id)
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

        self.source_sha256 = await asyncio.to_thread(sha256_file, self.file_path)
        # The source read decides only whether the conversion needs a CRS
        # assignment; every stored field comes from the converted COG.
        compression = self.options.get("compression") or "DEFLATE"
        inspection = await asyncio.to_thread(
            inspect_source_raster,
            self.file_path,
            original_filename=self.source_filename,
            expected_compression=compression,
        )
        self.source_meta = inspection["metadata"]
        assign_crs = resolve_crs_assignment(
            crs_wkt=self.source_meta.get("crs_wkt"),
            srid_override=self.options.get("srid_override"),
        )
        _enforce_strict_cog(
            inspection,
            is_manifest_vrt=False,
            strict_cog=bool(self.options.get("strict_cog")),
        )

        await self._progress("cog_convert", 0.2)
        self.tmp_dir = tempfile.mkdtemp(dir=_scratch_dir())
        (
            self.local_cog_path,
            self.cog_status,
            self.cog_meta,
        ) = await _convert_and_verify_cog(
            self.file_path,
            self.tmp_dir,
            inspection=inspection,
            compression=compression,
            resampling=self.options.get("resampling") or None,
            nodata=self.options.get("nodata_override"),
            assign_crs=assign_crs,
        )
        self.source_preserved_in_cog = cog_preserves_source(
            self.cog_status, compression
        )
        self.asset_sha256 = await asyncio.to_thread(sha256_file, self.local_cog_path)
        self.cog_size = os.path.getsize(self.local_cog_path)

        # Named on the job row before any put, so a worker killed between the
        # puts and its cleanup leaves them to the stale-job reaper. Excluding
        # the live keys is defensive: attempt-scoped keys never match them.
        base_key = attempt_scoped_raster_base_key(
            self.dataset_uuid, self.attempt_uuid, self.asset_sha256
        )
        if not await record_unpublished_storage_keys(
            self.job_uuid,
            self.attempt_uuid,
            keys=[
                f"{base_key}/source.cog.tif",
                f"{base_key}/quicklook_256.png",
                f"{base_key}/quicklook_512.png",
            ],
            already_published=[key for key in live if key],
            attempt_scope=str(self.attempt_uuid),
            job_id=self.job_id,
            task=self.task,
        ):
            raise StaleIngestAttempt(
                f"Ingest attempt {self.attempt_uuid} no longer owns job {self.job_id}"
            )

        await self._progress("quicklook", 0.6)
        self.ql256 = await asyncio.to_thread(render_quicklook, self.local_cog_path, 256)
        self.ql512 = await asyncio.to_thread(render_quicklook, self.local_cog_path, 512)

    async def stage(self, session, job, dataset) -> Verdict:
        self.job = job
        return PUBLISH

    async def install(self, session, dataset) -> None:
        from app.platform.storage import get_storage

        storage = get_storage()
        base_key = attempt_scoped_raster_base_key(
            dataset.id, self.attempt_uuid, self.asset_sha256
        )
        cog_key = f"{base_key}/source.cog.tif"
        ql256_key = f"{base_key}/quicklook_256.png"
        ql512_key = f"{base_key}/quicklook_512.png"
        self.catalog_keys = {
            "cog_key": cog_key,
            "ql256_key": ql256_key,
            "ql512_key": ql512_key,
        }
        (
            _storage_cog_key,
            _storage_ql256_key,
            _storage_ql512_key,
        ) = _resolve_managed_raster_storage_keys(cog_key, ql256_key, ql512_key)
        # Each key is registered before its put: a cancelled put can have
        # completed, and CancelledError skips anything below it.
        self.written_storage_keys.append(_storage_cog_key)
        with open(self.local_cog_path, "rb") as fobj:
            await storage.put(_storage_cog_key, fobj)
        self.written_storage_keys.append(_storage_ql256_key)
        await storage.put(_storage_ql256_key, io.BytesIO(self.ql256))
        self.written_storage_keys.append(_storage_ql512_key)
        await storage.put(_storage_ql512_key, io.BytesIO(self.ql512))

        # The kept original's bytes are part of what `write` reserves.
        (
            self.lossy_original_archived,
            self.archived_key,
            self.archived_bytes,
            _new_archive_key,
        ) = await archive_lossy_original(
            session,
            job=self.job,
            dataset_id=dataset.id,
            file_path=self.file_path,
            source_sha256=self.source_sha256,
            filename=self.source_filename,
            log_message=(
                "Failed to archive the lossy replacement original; the "
                "staged upload will be retained in place instead"
            ),
            needed=not self.source_preserved_in_cog,
            written_storage_keys=self.written_storage_keys,
        )

    async def write(self, session, dataset) -> Published:
        from app.modules.audit.service import AuditEvent, audit_emit
        from app.platform.extensions import get_processing_port
        from app.processing.raster.models import RasterAsset

        raster_asset = (
            await session.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
            )
        ).scalar_one()
        new_version = _write_swapped_fields(
            raster_asset,
            dataset,
            cog_meta=self.cog_meta,
            **self.catalog_keys,
            asset_sha256=self.asset_sha256,
            source_sha256=self.source_sha256,
            source_meta=self.source_meta,
            cog_size=self.cog_size,
            cog_status=self.cog_status,
            source_filename=self.source_filename,
            user_id=self.user_id,
        )
        archived_asset_key = (
            archived_original_asset_key(self.source_sha256)
            if self.archived_key
            else None
        )
        # Before the upserts: the live recount would otherwise count them twice.
        await reserve_replacement_bytes(
            session,
            dataset_id=dataset.id,
            owner_id=dataset.record.created_by,
            new_size=self.cog_size,
            archived_bytes=self.archived_bytes,
            archived_asset_key=archived_asset_key,
        )
        await upsert_archived_original_row(
            session,
            dataset_id=dataset.id,
            logical_key=self.archived_key,
            asset_key=archived_asset_key,
            size_bytes=self.archived_bytes,
            source_filename=self.source_filename,
        )
        await _upsert_managed_asset_rows(
            session,
            dataset_id=dataset.id,
            record_id=dataset.record_id,
            **self.catalog_keys,
            cog_size=self.cog_size,
        )

        DatasetVersion = get_processing_port().get_dataset_version_orm_class()
        version = DatasetVersion(
            dataset_id=dataset.id,
            version_number=new_version,
            source_filename=self.source_filename,
            source_format="geotiff",
            srid=self.cog_meta.get("epsg"),
            # A raster has neither a feature count nor a geometry type.
            file_hash=self.source_sha256,
            uploaded_by=uuid.UUID(self.user_id),
        )
        session.add(version)
        await session.flush()
        # The vector swap's action: one user-visible operation, one vocabulary.
        await audit_emit(
            session,
            AuditEvent(
                user_id=uuid.UUID(self.user_id),
                action="reupload.commit",
                resource_type="dataset",
                resource_id=dataset.id,
                details={
                    "version_number": new_version,
                    "source_type": "file",
                    "source_format": "geotiff",
                    "source_filename": self.source_filename,
                },
            ),
        )
        # The bytes came from the browser, so no origin was contacted.
        return Published(
            dataset_version_id=version.id,
            feature_count=None,
            schema_diff=None,
            contacted_origin=False,
            job_values={"current_step": "complete", "progress": 1.0},
        )

    def classify(self, exc: BaseException) -> Failure:
        if self.refused:
            return Failure("validation_failed", refused=True)
        return Failure(_raster_refresh_error_code(exc))

    async def release(
        self, *, publication: PublicationCommit | None, failed: bool
    ) -> None:
        # A cancelled reap must not skip the cleanup after it.
        try:
            if publication is None:
                async with cleanup_step(
                    "reupload_raster orphaned storage keys", job_id=self.job_id
                ):
                    orphans = [
                        key
                        for key in self.written_storage_keys
                        if key not in self.prior_physical_keys
                    ]
                    if orphans:
                        await _cleanup_orphaned_storage_keys(
                            orphans, job_id=self.job_id
                        )
            elif publication.confirmed:
                # After an unconfirmed publish the superseded keys may still
                # be the live raster, so they are kept.
                async with cleanup_step(
                    "reupload_raster superseded objects", job_id=self.job_id
                ):
                    await _cleanup_orphaned_storage_keys(
                        [
                            key
                            for key in self.prior_physical_keys
                            if key not in self.written_storage_keys
                        ],
                        job_id=self.job_id,
                    )
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
        # staged upload.
        async with cleanup_step("reupload_raster temp dir", job_id=self.job_id):
            if self.tmp_dir:
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
        # A downloaded copy is scratch. An upload staged in place is the
        # durable original, kept until the COG carries it or it is archived.
        async with cleanup_step("reupload_raster local file", job_id=self.job_id):
            if self.file_path != self.original_file_path or (
                final_status == "complete"
                and (self.source_preserved_in_cog or self.lossy_original_archived)
            ):
                Path(self.file_path).unlink(missing_ok=True)
        # The client-writable key, recreatable through an unexpired PUT URL.
        async with cleanup_step(
            "reupload_raster presigned staging object", job_id=self.job_id
        ):
            await reap_presigned_staging_object(
                self.job_id, self.owned_staging_key, final_status=final_status
            )
        # Kept on failure as the operator's only diagnostic copy, and after a
        # lossy conversion until its original is archived.
        async with cleanup_step(
            "reupload_raster downloaded source", job_id=self.job_id
        ):
            if self.source_preserved_in_cog or self.lossy_original_archived:
                await reap_downloaded_staging_source(
                    self.job_id,
                    original_file_path=self.original_file_path,
                    final_status=final_status,
                    failed_source_replayable=True,
                )

    async def _progress(self, step: str, progress: float) -> None:
        await _stamp_progress(
            self.job_uuid,
            self.attempt_uuid,
            phase=f"progress_write_{step}",
            step=step,
            progress=progress,
        )


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

    The replacement is converted, read back and put under keys of its own
    before the pointer moves, so the previous COG serves until the swap
    commits (invariant 10).
    """
    _bind_task_log_context(
        task_name="reupload_raster", job_id=job_id, dataset_id=dataset_id
    )
    await settle_replacement(
        _RasterReplace(
            job_id=job_id, dataset_id=dataset_id, file_path=file_path, user_id=user_id
        ),
        job_id=job_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
    )
