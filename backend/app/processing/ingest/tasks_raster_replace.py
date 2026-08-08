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
from sqlalchemy import func, select

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
    cog_preserves_source,
    extract_raster_metadata,
    resolve_crs_assignment,
    sha256_file,
)
from app.processing.raster.quicklook import generate_quicklook

from app.processing.ingest.tasks_common import (
    _archive_original_file,
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


def _write_swapped_fields(
    raster_asset,
    dataset,
    *,
    cog_meta: dict,
    cog_key: str,
    ql256_key: str,
    ql512_key: str,
    asset_sha256: str,
    source_sha256: str,
    source_meta: dict,
    cog_size: int,
    cog_status: str,
    source_filename: str | None,
    user_id: str,
) -> int:
    """Move every catalog field the swap owns, and return the new version.

    Extracted from ``reupload_raster`` when the round-3 archive step pushed
    that function back over the McCabe gate. Pure field assignment on two
    attached ORM instances — the caller's transaction is what makes it atomic
    with the storage puts and the job's terminal write.
    """
    nodata_val = cog_meta.get("nodata")
    raster_asset.asset_uri = cog_key
    raster_asset.quicklook_256_uri = ql256_key
    raster_asset.quicklook_512_uri = ql512_key
    raster_asset.sha256 = asset_sha256
    raster_asset.size_bytes = cog_size
    raster_asset.source_sha256 = source_sha256
    raster_asset.cog_status = cog_status
    # fix(#1290 review): a STAC-origin row carries
    # storage_backend="remote" because its asset_uri WAS an external
    # href. The swap has just replaced that with a managed
    # `rasters/...` key, so leaving the backend alone tells every
    # consumer to treat a managed key as a URL: the COG download
    # endpoint SSRF-validates it and proxies it, and VRT health probes
    # it over HTTP. "local" is what `create_raster_dataset` writes for
    # every managed raster — the value means "GeoLens owns these
    # bytes", and `resolve_open_path` does the local/S3/Azure dispatch
    # from the key itself.
    raster_asset.storage_backend = "local"
    raster_asset.driver = cog_meta.get("driver")
    raster_asset.ingested_at = datetime.now(timezone.utc)
    raster_asset.crs_wkt = cog_meta.get("crs_wkt")
    raster_asset.epsg = cog_meta.get("epsg")
    raster_asset.band_count = cog_meta.get("band_count")
    raster_asset.dtype = cog_meta.get("dtype")
    raster_asset.nodata = str(nodata_val) if nodata_val is not None else None
    raster_asset.res_x = cog_meta.get("res_x")
    raster_asset.res_y = cog_meta.get("res_y")
    raster_asset.width = cog_meta.get("width")
    raster_asset.height = cog_meta.get("height")
    raster_asset.compression = cog_meta.get("compression")
    raster_asset.band_info = cog_meta.get("band_info")
    raster_asset.is_rotated = cog_meta.get("is_rotated", False)
    # Recomputed, not carried over: replacing a single-band float
    # elevation raster with an RGB orthophoto has to stop rendering as
    # terrain. Same reasoning as the VRT regenerate path (#185).
    raster_asset.is_dem = cog_meta.get("is_dem_candidate", False)

    new_version = dataset.current_version + 1
    dataset.current_version = new_version
    dataset.srid = cog_meta.get("epsg")
    # fix(#1290 review): the two fields answer different questions and
    # round 1 collapsed them onto one read. `srid` is what the dataset
    # serves, which is the converted COG's; `original_srid` is
    # documented as the SRID of the uploaded file, so under an override
    # it must still report what the upload declared. Collapsing them
    # made a 4326 source with srid_override=3857 record 3857 twice and
    # lose the only record of what arrived.
    dataset.original_srid = source_meta.get("epsg")
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
    if cog_meta.get("bbox_wkt"):
        dataset.record.spatial_extent = func.ST_GeomFromText(cog_meta["bbox_wkt"], 4326)

    return new_version


async def _upsert_managed_asset_rows(
    session,
    *,
    dataset_id: uuid.UUID,
    record_id: uuid.UUID,
    cog_key: str,
    ql256_key: str,
    ql512_key: str,
    cog_size: int,
) -> None:
    """Point the STAC/search/download surfaces at the newly published COG.

    fix(#1290 review). This was two UPDATEs, which is correct only for a
    dataset that already has the rows — true of an upload-origin raster, false
    of a STAC-imported one, whose import writes the dataset and the raster
    asset and nothing else. Against those the UPDATEs matched zero rows and
    reported success, so a replaced STAC raster advertised no data asset and no
    quicklooks at all.

    Upserting makes the outcome the same either way, which is the property
    worth having: after this runs the four rows exist and describe the live
    asset, whatever the dataset's origin was. The ``dataset_assets`` rows are
    built by ``_build_dataset_asset_rows`` — the same helper first ingest uses
    — so the two paths cannot describe the same asset differently.

    ``record_distributions`` is delete-then-insert rather than ON CONFLICT
    because its unique constraint includes ``url``: the replacement has a new
    URL by construction, so a conflict target keyed on it can never match the
    row that needs replacing.
    """
    from sqlalchemy import delete as sa_delete
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.platform.extensions import get_catalog_port, get_processing_port
    from app.processing.ingest.tasks_raster_common import _build_dataset_asset_rows

    DatasetAsset = get_catalog_port().dataset_asset_orm_class()
    RecordDistribution = get_processing_port().get_record_distribution_orm_class()

    for row in _build_dataset_asset_rows(
        dataset_id=dataset_id,
        cog_key=cog_key,
        ql256_key=ql256_key,
        ql512_key=ql512_key,
        cog_size=cog_size,
        is_manifest_vrt=False,
    ):
        stmt = pg_insert(DatasetAsset).values(**row)
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_dataset_assets_key",
                # Only the columns this row actually carries: the quicklook
                # rows have no size_bytes, and listing it would overwrite a
                # stored value with NULL.
                set_={
                    k: stmt.excluded[k] for k in row if k not in ("dataset_id", "key")
                },
            )
        )

    await session.execute(
        sa_delete(RecordDistribution).where(
            RecordDistribution.record_id == record_id,
            RecordDistribution.format == "geotiff",
        )
    )
    session.add(
        RecordDistribution(
            record_id=record_id,
            distribution_type="download",
            format="geotiff",
            url=cog_key,
        )
    )


async def _run_post_swap_followups(
    *,
    dataset_uuid: uuid.UUID,
    dataset_cls: type,
    prior_physical_keys: list[str],
    written_storage_keys: list[str],
    job_id: str,
) -> None:
    """Work that happens once the replacement is durably published.

    Extracted (fix(#1290 review)) so the caller can fence the whole of it in
    one place — every statement here is optional, and none of it may be
    confused with a failed replace.

    Reaping the superseded objects is safe only now. Up to the commit every
    exit left the previous COG both pointed at and present; past it the pointer
    is durably elsewhere, so those objects have no reader left. The
    ``not in written`` filter is what makes re-uploading the identical file a
    no-op rather than a self-inflicted delete.

    "No reader left" is true of the DATABASE. An API process that served a tile
    in the last minute may still hold this dataset in the tile router's
    ``_resolve_raster_meta`` cache, whose entries carry the OLD asset_uri for up
    to ``_RASTER_META_CACHE_TTL`` (60s) — so raster tiles can fail for that
    window before the entry expires and the new pointer is read. Deliberately
    not worked around: ``regenerate_vrt`` reaps its superseded generation the
    same way against the same cache, the window is bounded and self-healing, and
    closing it needs cross-process invalidation neither path has. The bumped
    ``tile_cache_version`` already changes the tile URL, so browser and CDN
    caches roll over immediately.
    """
    from app.core.db import async_session
    from sqlalchemy.orm import joinedload

    await invalidate_catalog_cache()
    await _cleanup_orphaned_storage_keys(
        [key for key in prior_physical_keys if key not in written_storage_keys],
        job_id=job_id,
    )
    async with async_session() as embed_session:
        embed_dataset = (
            await embed_session.execute(
                select(dataset_cls)
                .options(joinedload(dataset_cls.record))
                .where(dataset_cls.id == dataset_uuid)
            )
        ).scalar_one_or_none()
        if embed_dataset is not None:
            from app.processing.embeddings.helpers import defer_embedding

            await defer_embedding(embed_dataset)


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
        # The SOURCE read, and its only remaining job: decide whether the
        # conversion needs a CRS assignment. Nothing here is persisted —
        # fix(#1290 review) moved every stored field onto the converted COG's
        # own metadata, which is the file the dataset will actually serve.
        source_meta = await asyncio.to_thread(extract_raster_metadata, file_path)

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
        # actually ran is known — including whether a warp ran, which a
        # lossless codec does not tell you and which resamples every pixel.
        source_preserved_in_cog = cog_preserves_source(
            cog_status, user_compression, reprojected=assign_crs is not None
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

            # fix(#1290 review): every field below reads the CONVERTED COG's
            # own metadata. Persisting the source's described a file the
            # dataset does not serve — `compression` was wrong on every
            # converted replace, `nodata` wrong under an override, and the CRS
            # and footprint wrong under `srid_override`, which is exactly the
            # case a caller reaches for when the source's CRS is the problem.
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

            # fix(#1290 review): ADR-002 Decision 7's retained original moves to
            # `originals/<dataset_id>/`, the prefix the vector tails have
            # archived to since #430 and which `delete_dataset` already reaps.
            # Keeping it under `staging/` made it a permanent artifact in a
            # namespace whose whole meaning is "transient": the retention purge
            # exempts only a dataset's most recent complete job, so the next
            # successful replace would have made this one purgeable and the
            # promise would have died silently. Relocating removes the class
            # instead of adding an exemption every future purge edit must know
            # about. Placed here, beside the vector path's own archive step, so
            # it runs with a session in hand and before the tail decides
            # whether the staged copy is still needed.
            if not source_preserved_in_cog:
                lossy_original_archived = await _archive_original_file(
                    session,
                    job=job,
                    dataset_id=dataset.id,
                    file_path=file_path,
                    log_message=(
                        "Failed to archive the lossy replacement original; "
                        "the staged upload will be retained in place instead"
                    ),
                    commit=False,
                    archive_name=source_filename,
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
        if file_path != original_file_path:
            Path(file_path).unlink(missing_ok=True)
        elif final_status == "complete" and (
            source_preserved_in_cog or lossy_original_archived
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
