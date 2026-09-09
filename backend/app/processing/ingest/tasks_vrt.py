"""Procrastinate task definitions for VRT creation and regeneration.

Storage portability (STOR-03/04, Phase 1210):
  VRTs are stored with provider-agnostic SourceFilename nodes (logical keys +
  relativeToVRT="1"). The rewrite pass (rewrite_vrt_sources) runs AFTER metadata
  extraction and quicklook generation at each store site — the in-flight tmp .vrt
  used by extract_raster_metadata / generate_quicklook must hold concrete,
  resolvable paths; only the stored copy is normalised to logical keys.

  At open-time, resolve_open_path (app.platform.storage.titiler_url) reconstructs
  the concrete VSI path from the logical key + current STORAGE_PROVIDER config, so
  a provider swap (s3 -> azure -> local) requires no changes to stored VRT XML.
"""

import time
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.exc import DBAPIError

from sqlalchemy import select

from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.heartbeat import (
    arm_job_error_write_budget,
    claim_job_attempt_and_start_heartbeat,
    log_job_error_write_failure,
    maintain_vrt_generation_heartbeat,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.core.db import tenant_task
from app.processing.embeddings.helpers import defer_embedding
from app.processing.raster.cog import extract_raster_metadata, sha256_file
from app.processing.raster.quicklook import generate_quicklook
from app.processing.raster.vrt import (
    build_vrt,
    gdal_safe_open_env,
    resolve_vrt_source_path,
)
from app.processing.raster.vrt_rewrite import rewrite_vrt_sources
from app.platform.storage import get_storage

from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    cleanup_step,
    _cleanup_staging_on_failure,
    load_job_for_error_write,
    task_app,
)
from app.processing.ingest.tasks_raster_common import (
    absorb_cancellation,
    publish_commit_landed,
    record_unpublished_storage_keys,
)

# fix(#1938): the budget for the publish transaction's catalog.records wait.
# Its only holders are request handlers that dirty the record and hold it from
# flush to commit; nothing caps that, so this is a stuck-not-queued threshold.
_PUBLISH_CATALOG_TIMEOUT = "15s"


def _log_publish_wait_failure(
    conflict: BaseException, *, job_id: str, dataset_id: str, waited_ms: int
) -> None:
    """Report a failed publish catalog wait, classified by its SQLSTATE.

    ``dataset_id`` must be read BEFORE the acquisition: ``lock_catalog_rows``
    rolls back before it raises, and that expires every loaded instance.
    """
    from app.platform.catalog_locks import lock_conflict_report

    log_event, hint, code = lock_conflict_report(
        conflict, event_prefix="vrt_publish_catalog"
    )
    structlog.get_logger().warning(
        log_event,
        job_id=job_id,
        dataset_id=dataset_id,
        waited_ms=waited_ms,
        budget=_PUBLISH_CATALOG_TIMEOUT,
        sqlstate=code,
        hint=hint,
    )


def read_vrt_metadata(vrt_path: str) -> dict:
    """``extract_raster_metadata`` on a built VRT, under the safe open env.

    fix(#1778): steps 6 and 8 below open every ``/vsis3`` source the
    assembled VRT names in-process rather than through a subprocess, so
    they're the one place ``GDAL_SUBPROCESS_TIMEOUT_SECONDS`` doesn't
    reach. A rasterio ``Env`` sets thread-local GDAL config, so
    ``_VRT_SAFE_ENV`` must be entered INSIDE the ``asyncio.to_thread`` call
    rather than around it — the whole reason this is a function, not a
    ``with`` block at the call site.

    fix(#1778): lives in THIS module and calls
    ``extract_raster_metadata`` through the module global (not a local
    import) because that name is a patch target for
    ``test_regenerate_vrt_integration``; a function-level import there
    made the patch a no-op.
    """
    with gdal_safe_open_env():
        return extract_raster_metadata(vrt_path)


def render_vrt_quicklook(vrt_path: str, size: int) -> bytes:
    """``generate_quicklook`` on a built VRT, under the safe open env.

    fix(#1778): the peer of :func:`read_vrt_metadata` and the heavier of the
    two, since it reads pixels from every source rather than headers. Same
    module-global call for the same reason.
    """
    with gdal_safe_open_env():
        return generate_quicklook(vrt_path, size)


async def _reap_superseded_generation_objects(
    *,
    prior_storage_keys: list[str],
    written_storage_keys: list[str],
    job_id: str,
) -> None:
    """Delete the objects the published generation superseded.

    fix(#1778): shared because ``regenerate_vrt`` reaches it from
    two places (the success path and the stand-down for a lost commit ack)
    — the ONLY deletion of the previous generation's artifact, so a path
    that skips it strands bytes no row references and no quota counts.

    The ``not in written`` filter makes a byte-identical regeneration a
    no-op rather than a self-inflicted delete.
    """
    from app.processing.ingest.tasks_raster import _cleanup_orphaned_storage_keys

    await _cleanup_orphaned_storage_keys(
        [key for key in prior_storage_keys if key not in written_storage_keys],
        job_id=job_id,
    )


async def _settle_failed_vrt_asset(
    vrt_dataset_id: uuid.UUID,
    generation_uuid: uuid.UUID | None,
    *,
    job_id: str,
) -> bool:
    """Repoint the VRT asset off a generation that failed, in its own transaction.

    Fenced on the pointer, so a newer retry that already owns it keeps its
    status. Does nothing when this attempt never bound a generation: there is
    no pointer to release, and the fence would otherwise read as ``IS NULL``.

    Never raises. Returns whether the asset is provably no longer pointing at
    *generation_uuid*; on False the caller MUST leave the generation
    non-terminal, or the pair becomes unreachable to the stale sweep.
    """
    from sqlalchemy import update as sa_update

    from app.core.db import async_session
    from app.processing.raster.models import RasterAsset

    if generation_uuid is None:
        return True
    try:
        async with async_session() as session:
            await arm_job_error_write_budget(session)
            await session.execute(
                sa_update(RasterAsset)
                .where(
                    RasterAsset.dataset_id == vrt_dataset_id,
                    RasterAsset.current_generation_id == generation_uuid,
                )
                .values(status="failed", current_generation_id=None)
            )
            await session.commit()
    except DBAPIError as write_failure:
        log_job_error_write_failure(write_failure, job_id=job_id, task="regenerate_vrt")
        return False
    return True


def _prior_generation_storage_keys_to_reap(
    *,
    vrt_key: str,
    quicklook_256_key: str | None,
    quicklook_512_key: str | None,
    replace_quicklook_256: bool,
    replace_quicklook_512: bool,
    tenant_id: str | None,
) -> list[str]:
    """Resolve only prior objects whose catalog pointers will be replaced."""
    from app.platform.storage.titiler_url import resolve_storage_key

    logical_keys = [vrt_key]
    if replace_quicklook_256 and quicklook_256_key is not None:
        logical_keys.append(quicklook_256_key)
    if replace_quicklook_512 and quicklook_512_key is not None:
        logical_keys.append(quicklook_512_key)
    return [resolve_storage_key(key, tenant_id=tenant_id) for key in logical_keys]


async def snapshot_member_sources(
    session, dataset_ids, *, raster_asset_cls, dataset_cls
):
    """Stamp the instant, THEN read the members. Returns ``(snapshot_at, assets)``.

    fix(#1290): ``last_regenerated_at`` names the state a VRT was
    built FROM, which only holds if the instant predates the read — shared
    by both VRT tails so neither can get the order wrong.

    Direction matters: stamping BEFORE the read means a replacement
    landing in the tiny stamp-to-read window is already visible, so at
    worst the parent reports `stale` when it's fine (a cheap, self-
    correcting extra regenerate). Stamping after would let a parent whose
    VRT references a reaped COG report `healthy` — a masked broken mosaic.
    """
    snapshot_at = datetime.now(timezone.utc)
    result = await session.execute(
        select(raster_asset_cls)
        .join(dataset_cls, raster_asset_cls.dataset_id == dataset_cls.id)
        .where(dataset_cls.id.in_(dataset_ids))
    )
    asset_map = {a.dataset_id: a for a in result.scalars().all()}
    ordered = [asset_map[sid] for sid in dataset_ids if sid in asset_map]
    return snapshot_at, ordered


def built_from_map(ordered_assets) -> dict:
    """``{dataset_id: asset_uri}`` for the members a build is assembling.

    fix(#1290). This is what makes staleness a STATE question. The
    health endpoint compares each member's current committed ``asset_uri``
    against the entry recorded here, so "the stored VRT references a superseded
    COG" is answered by comparing what-is to what-was-built-from rather than by
    racing two clocks. Derived from the same ``ordered_assets`` the build reads,
    so the recorded set is by construction the set that was used.
    """
    return {str(a.dataset_id): a.asset_uri for a in ordered_assets}


def staged_source_ids_or_none(generation) -> list[uuid.UUID] | None:
    """The generation's staged member set as UUIDs, or None when it stages none.

    fix(#1327): NULL means "this generation changes no membership" — a
    plain regenerate, or one queued before ``staged_source_ids`` existed.
    Both build from the live link rows, so one fallback covers two
    producers. A JSONB ``null`` also reads back as Python ``None``
    (the same trap #1322 hit in SQL), and a non-list value falls to the
    same None answer.

    Everything else about the value is checked HERE, at claim time,
    before a single byte is built: an empty set, an unparseable id, or a
    repeated id fails now (costing a job) rather than at apply time
    (costing a GDAL build plus an obscure ON CONFLICT error).
    """
    staged = getattr(generation, "staged_source_ids", None)
    if not isinstance(staged, list):
        return None
    source_ids = [
        value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        for value in staged
    ]
    if not source_ids:
        raise ValueError("Staged VRT source set is empty")
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("Staged VRT source set repeats a source dataset")
    return source_ids


async def apply_staged_source_links(session, vrt_dataset_id, source_ids) -> None:
    """Make ``vrt_source_links`` equal ``source_ids``, positions from order.

    fix(#1327): called only from the publish transaction that also swaps
    ``asset_uri`` and writes ``built_from``, so the declared composition
    becomes visible at the instant the built artifact does.

    A replace, not a diff: upsert the whole staged set, then delete
    everything else for this VRT — idempotent (safe to retry), and the
    upsert preserves ``created_at`` on surviving rows. The empty guard
    stops an empty list from compiling into ``NOT IN ()`` and deleting
    every link a VRT has (the caller already refuses an empty staged set
    at claim time; this is a precondition, not a second validation).
    """
    from sqlalchemy import delete
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.processing.raster.models import VrtSourceLink

    if not source_ids:
        raise ValueError(f"VRT {vrt_dataset_id} staged an empty source set")

    stmt = pg_insert(VrtSourceLink).values(
        [
            {
                "vrt_dataset_id": vrt_dataset_id,
                "source_dataset_id": source_id,
                "position": position,
            }
            for position, source_id in enumerate(source_ids)
        ]
    )
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_vsl_vrt_source",
            set_={"position": stmt.excluded.position},
        )
    )
    await session.execute(
        delete(VrtSourceLink).where(
            VrtSourceLink.vrt_dataset_id == vrt_dataset_id,
            VrtSourceLink.source_dataset_id.notin_(source_ids),
        )
    )


async def create_vrt_dataset(
    session,
    *,
    meta: dict,
    asset_sha256: str,
    vrt_size: int,
    source_filename: str | None,
    created_by: uuid.UUID,
    title: str,
    summary: str | None,
    visibility: str,
    vrt_type: str,
    resolution_strategy: str,
    source_dataset_ids: list[uuid.UUID],
    record_status: str = "published",
    snapshot_at: datetime | None = None,
    built_from: dict | None = None,
    dataset_id: uuid.UUID | None = None,
) -> tuple:
    """Create Record + Dataset + RasterAsset records for a VRT dataset.

    Similar to create_raster_dataset but:
    - record_type="vrt_dataset"
    - source_format=None (avoids chk_datasets_source_format constraint)
    - Sets vrt_type and resolution_strategy on RasterAsset
    - Inserts vrt_source_links rows with position ordering

    fix(#1778): ``dataset_id`` has the same job it has on
    ``create_raster_dataset``: let the manifest-VRT tail name its object keys
    on the durable job row before this transaction opens.

    Returns (record, dataset, raster_asset).
    """
    from sqlalchemy import func, text

    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()
    Record = port.get_record_orm_class()

    # fix(#302): authoritative count-cap check in the same transaction that
    # inserts the Record (the upload-time pre-check is not atomic).
    from app.modules.quota.service import reserve_dataset_slot

    await reserve_dataset_slot(session, created_by)

    record = Record(
        title=title,
        summary=summary,
        record_type="vrt_dataset",
        visibility=visibility,
        # Mirrors the vector ingest path and the raster ingest helper
        # above, which commit directly to `published` — otherwise a public
        # VRT stayed in `draft` and 404'd on public tile access.
        record_status=record_status,
        # fix(#302): created_by was never set on VRT records, leaving them
        # NULL and invisible to the per-user quota count and owner checks.
        created_by=created_by,
        updated_by=created_by,
    )
    if meta.get("bbox_wkt"):
        record.spatial_extent = func.ST_GeomFromText(meta["bbox_wkt"], 4326)
    session.add(record)
    await session.flush()

    table_name = f"vrt_{record.id.hex[:16]}"
    dataset = Dataset(
        **({"id": dataset_id} if dataset_id is not None else {}),
        record_id=record.id,
        table_name=table_name,
        source_format=None,  # VRT datasets have no source_format (avoids chk constraint)
        source_filename=source_filename,
        srid=meta.get("epsg"),
        # fix(#1218): stamped like every other creation path —
        # assembling a VRT IS a successful materialization. Python value,
        # not func.now(): a SQL expression leaves the attribute expired.
        last_refreshed_at=datetime.now(timezone.utc),
    )
    session.add(dataset)
    await session.flush()

    nodata_val = meta.get("nodata")
    nodata_str = str(nodata_val) if nodata_val is not None else None

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri="",  # updated after storage put
        sha256=asset_sha256,
        size_bytes=vrt_size,
        driver="VRT",
        storage_backend="local",
        ingested_at=datetime.now(timezone.utc),
        # fix(#1290): the instant the members were READ, so a
        # never-regenerated parent doesn't fall back to publish-time
        # `ingested_at` in the staleness comparison. Optional only because
        # the manifest-VRT caller has no snapshot; the build path always
        # supplies it.
        last_regenerated_at=snapshot_at,
        # fix(#1290): the authoritative staleness input. The timestamp
        # above stays for legacy rows that have no built-from set.
        built_from=built_from,
        crs_wkt=meta.get("crs_wkt"),
        epsg=meta.get("epsg"),
        band_count=meta.get("band_count"),
        dtype=meta.get("dtype"),
        # A VRT mosaic of single-band float DEM tiles is itself a DEM. Mirror the
        # raster ingest path (tasks_raster) so terrain + hillshade light up; without
        # this the mosaic lands is_dem=false and is unusable as terrain (#185).
        is_dem=meta.get("is_dem_candidate", False),
        nodata=nodata_str,
        res_x=meta.get("res_x"),
        res_y=meta.get("res_y"),
        width=meta.get("width"),
        height=meta.get("height"),
        compression=meta.get("compression"),
        is_rotated=meta.get("is_rotated", False),
        vrt_type=vrt_type,
        resolution_strategy=resolution_strategy,
        status="ready",
    )
    session.add(raster_asset)
    await session.flush()

    # Insert vrt_source_links with position ordering. Single executemany
    # batch (one round trip) instead of N per-row INSERTs (PERF-2).
    if source_dataset_ids:
        await session.execute(
            text(
                "INSERT INTO catalog.vrt_source_links "
                "(vrt_dataset_id, source_dataset_id, position) "
                "VALUES (:vrt_id, :src_id, :pos)"
            ),
            [
                {"vrt_id": str(dataset.id), "src_id": str(src_id), "pos": idx}
                for idx, src_id in enumerate(source_dataset_ids)
            ],
        )

    return record, dataset, raster_asset


@task_app.task(queue="raster", retry=0, aliases=["app.ingest.tasks.ingest_vrt"])
@tenant_task
async def ingest_vrt(
    job_id: str,
    user_id: str,
    source_dataset_ids: str,
    vrt_type: str,
    resolution_strategy: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: build a VRT, extract metadata, and register as a catalog dataset.

    Full pipeline:
    1. Update job status to running
    2. Parse source_dataset_ids JSON
    3. Load RasterAsset rows for each source dataset
    4. Resolve asset_uri -> filesystem/S3 paths
    5. Build VRT via gdalbuildvrt (spatial mosaic or band stack)
    6. Extract metadata from assembled VRT via rasterio
    7. Hash VRT file
    8. Generate quicklooks (non-fatal)
    9. Create DB records (Record + Dataset + RasterAsset + vrt_source_links)
    10. Store VRT and quicklooks to managed storage
    11. Update asset URIs and create distribution record
    12. Set job.dataset_id on completion
    13. Invalidate cache, defer embedding

    Session lifecycle (gh #100): the AsyncSession is split into two
    short-lived blocks so it is NOT held open across the long-running CPU
    work in steps 5-8 (each runs via ``asyncio.to_thread``).
    """
    _bind_task_log_context(task_name="ingest_vrt", job_id=job_id)
    import asyncio
    import io
    import json as _json
    import os
    import shutil
    import tempfile

    from app.core.db import async_session  # fix(#909): late-bind for tests
    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from app.processing.raster.models import RasterAsset

    _port = get_processing_port()
    Dataset = _port.get_dataset_orm_class()
    RecordDistribution = _port.get_record_distribution_orm_class()

    logger_vrt = __import__("logging").getLogger(__name__)

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="vrt"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    tmp_dir: str | None = None
    # fix(#430): track storage puts so a failure after put (terminal commit /
    # later phase-2 step) reaps the VRT + quicklook bytes instead of orphaning
    # them forever — the GAP-017 guard ingest_raster already has.
    written_storage_keys: list[str] = []
    # fix(#1778): "the VRT and its quicklooks are published", set at the
    # terminal commit and nowhere else. It replaces the `final_status` string
    # this reap used to read, because that string was set on the line after the
    # commit: a commit whose acknowledgement was lost left it "failed" and the
    # reap deleted the artifact a durably committed RasterAsset names. See
    # `publish_commit_landed`.
    publish_committed: bool = False
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session): load job, mark running, load source
        # asset rows. Snapshot all values needed for phase 2.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            result = await session.execute(
                select(IngestJob).where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                )
            )
            job = result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job not found, skipping", job_id=job_id
                )
                return

            # 1. Mark running
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid
            )
            if heartbeat_task is None:
                return

            # 2. Parse source dataset IDs
            ids = [uuid.UUID(sid) for sid in _json.loads(source_dataset_ids)]

            # 3. Load RasterAsset rows for source datasets, stamped first.
            # fix(#1290): the creation tail had NO snapshot instant, so
            # a member replaced during the initial build was masked exactly as
            # it was on regenerate — the status comparison falls back to the
            # parent's `ingested_at` when `last_regenerated_at` is NULL, and
            # that was stamped at publish.
            snapshot_at, ordered_assets = await snapshot_member_sources(
                session, ids, raster_asset_cls=RasterAsset, dataset_cls=Dataset
            )

            # 4. Resolve paths (snapshot to plain strings before closing session)
            from app.core.db.tenant_session import current_tenant_var

            source_paths = [
                resolve_vrt_source_path(
                    asset.asset_uri, tenant_id=current_tenant_var.get()
                )
                for asset in ordered_assets
            ]

            # Snapshot job fields needed in phase 2.
            um: dict = job.user_metadata or {}

        # ----------------------------------------------------------------- #
        # CPU work — NO session open. asyncio.to_thread calls run GDAL/numpy
        # in the thread pool.
        # ----------------------------------------------------------------- #

        # 5. Build VRT
        tmp_dir = tempfile.mkdtemp()
        vrt_path = os.path.join(tmp_dir, "source.vrt")
        await asyncio.to_thread(
            build_vrt, vrt_type, source_paths, vrt_path, resolution_strategy
        )

        # 6. Extract metadata from assembled VRT
        meta = await asyncio.to_thread(read_vrt_metadata, vrt_path)
        if not meta.get("crs_wkt"):
            raise ValueError("Assembled VRT has no coordinate reference system.")

        # 7. Hash and size VRT file
        asset_sha256 = await asyncio.to_thread(sha256_file, vrt_path)
        vrt_size = os.path.getsize(vrt_path)

        # fix(#1778): same treatment as `ingest_raster`. Steps 10-11
        # put the VRT/quicklooks before the terminal commit, and
        # `written_storage_keys` is a local list — a kill between put and
        # commit loses it with the process and rolls back the dataset row
        # whose id the keys embed. Recording the intended keys on the
        # durable job row first is what makes both stale-job sweeps able to
        # reap them. The id is decided here (not the phase-2 INSERT) since
        # the keys embed it before the transaction that could roll it away
        # opens, and it's generated per invocation so a retry can't
        # reproduce one — this tail's attempt fence, same as `ingest_raster`.
        planned_dataset_id = uuid.uuid4()
        _vrt_base_key = f"rasters/{planned_dataset_id}/{asset_sha256}"
        if not await record_unpublished_storage_keys(
            job_uuid,
            attempt_uuid,
            keys=[
                f"{_vrt_base_key}/source.vrt",
                f"{_vrt_base_key}/quicklook_256.png",
                f"{_vrt_base_key}/quicklook_512.png",
            ],
            # A brand new dataset id: no row can already name one of these.
            already_published=(),
            attempt_scope=str(planned_dataset_id),
            job_id=job_id,
            task="ingest_vrt",
        ):
            # fix(#1778): a confirmed fence miss. Phase 2's own
            # attempt-fenced load below would catch this too, but stopping
            # here is what actually keeps the recorder's contract ("do not
            # write what nothing records") rather than depending on a second
            # guard downstream to make it true, and it skips the quicklook
            # generation this dead attempt no longer needs.
            return

        # 8. Generate quicklooks (non-fatal)
        ql256: bytes | None = None
        ql512: bytes | None = None
        try:
            ql256 = await asyncio.to_thread(render_vrt_quicklook, vrt_path, 256)
            ql512 = await asyncio.to_thread(render_vrt_quicklook, vrt_path, 512)
        except Exception:  # broad: quicklook generation is non-fatal
            logger_vrt.warning(
                "Quicklook generation failed for VRT %s", job_id, exc_info=True
            )

        # Phase 2 (short-lived session): create DB records, store assets,
        # commit job. This tail never adopted `_job_phase_session`, so the
        # fence is matched by hand: fix(#1778) joins status ==
        # "running" to the attempt fence (same require_status trap as
        # `_job_phase_session`'s docstring — a paused, not dead, worker can
        # still match an (id, attempt)-only fence and put the VRT/quicklooks
        # to storage, which no rollback can undo); fix(#1778)
        # adds `.with_for_update(key_share=True)` to close the SELECT-is-
        # not-a-lock window between this read and the puts completing.
        async with async_session() as session:
            result = await session.execute(
                select(IngestJob)
                .where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                    IngestJob.status == "running",
                )
                .with_for_update(key_share=True)
            )
            job = result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job vanished between phases, skipping",
                    job_id=job_id,
                )
                return

            try:
                # 9. Create DB records
                title = um.get("title") or f"vrt_{vrt_type}"
                record, dataset, raster_asset = await create_vrt_dataset(
                    session,
                    snapshot_at=snapshot_at,
                    built_from=built_from_map(ordered_assets),
                    meta=meta,
                    asset_sha256=asset_sha256,
                    vrt_size=vrt_size,
                    source_filename=None,
                    created_by=uuid.UUID(user_id),
                    title=title,
                    summary=um.get("summary"),
                    visibility=um.get("visibility", "private"),
                    vrt_type=vrt_type,
                    resolution_strategy=resolution_strategy,
                    source_dataset_ids=ids,
                    dataset_id=planned_dataset_id,
                )

                # 10. Store VRT and quicklooks to managed storage
                from pathlib import Path as _Path

                from app.platform.storage import get_storage

                storage = get_storage()
                # fix(#1778): the same value the durable record above
                # named, since `dataset.id` IS `planned_dataset_id`. Written as
                # the dataset's own id rather than the local so the key still
                # reads as a property of the row it belongs to.
                base_key = f"rasters/{dataset.id}/{asset_sha256}"
                vrt_key = f"{base_key}/source.vrt"

                from app.core.db.tenant_session import current_tenant_var
                from app.platform.storage.titiler_url import resolve_storage_key

                _storage_vrt_key = resolve_storage_key(
                    vrt_key, tenant_id=current_tenant_var.get()
                )

                # ORDERING: rewrite_vrt_sources runs AFTER metadata extraction
                # (step 6) and quicklook generation (step 8) — the in-flight
                # tmp .vrt must hold concrete resolvable paths for GDAL to open.
                # Only the STORED copy is rewritten to logical relativeToVRT="1"
                # keys so the XML is provider-agnostic at rest (STOR-03).
                # CR-01: supply vrt_storage_key so the rewrite computes paths
                # relative to the VRT's own directory (not the full logical key).
                _vrt_rewrite_changes = rewrite_vrt_sources(
                    _Path(vrt_path), vrt_storage_key=_storage_vrt_key
                )
                if _vrt_rewrite_changes:
                    logger_vrt.info(
                        "VRT store-path rewrite: %d SourceFilename(s) normalised to logical keys",
                        len(_vrt_rewrite_changes),
                        extra={"changes": _vrt_rewrite_changes, "job_id": job_id},
                    )
                ql256_key = f"{base_key}/quicklook_256.png"
                ql512_key = f"{base_key}/quicklook_512.png"

                # CR-02 (Phase 1210): in multi_tenant mode the serve path
                # prepends tenants/{tenant_id}/ to the logical key.  Ingest
                # must store at the SAME prefixed key so stored key == served key.
                # single_tenant: tenant_id=None → keys unchanged (byte-identical).
                _storage_ql256_key = resolve_storage_key(
                    ql256_key, tenant_id=current_tenant_var.get()
                )
                _storage_ql512_key = resolve_storage_key(
                    ql512_key, tenant_id=current_tenant_var.get()
                )

                # fix(#1778): registered before the put, per
                # archive_lossy_original's rule. A cancelled put can have
                # completed, and CancelledError skips every statement below it.
                written_storage_keys.append(_storage_vrt_key)
                with open(vrt_path, "rb") as fobj:
                    await storage.put(_storage_vrt_key, fobj)

                if ql256 is not None:
                    written_storage_keys.append(_storage_ql256_key)
                    await storage.put(_storage_ql256_key, io.BytesIO(ql256))
                if ql512 is not None:
                    written_storage_keys.append(_storage_ql512_key)
                    await storage.put(_storage_ql512_key, io.BytesIO(ql512))

                # 11. Update asset URIs and create distribution.
                # asset_uri stays as the logical (un-prefixed) key — the tenant
                # prefix is injected at serve-time by resolve_open_path.
                raster_asset.asset_uri = vrt_key
                if ql256 is not None:
                    raster_asset.quicklook_256_uri = ql256_key
                if ql512 is not None:
                    raster_asset.quicklook_512_uri = ql512_key
                await session.flush()

                distribution = RecordDistribution(
                    record_id=record.id,
                    distribution_type="download",
                    format="vrt",
                    url=vrt_key,
                )
                session.add(distribution)

                # 12. Finalize job
                await require_ingest_job_update(
                    session,
                    job_uuid,
                    attempt_uuid,
                    values={
                        "status": "complete",
                        "dataset_id": dataset.id,
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
                try:
                    await session.commit()
                except BaseException as exc:
                    if not await publish_commit_landed(
                        job_uuid, attempt_uuid, job_id=job_id, task="ingest_vrt"
                    ):
                        raise
                    # fix(#1778): stand down rather than re-raise
                    # (same decision `regenerate_vrt` makes below) — the
                    # dataset and its VRT object are durable, so the failure
                    # handler would be writing about a job that succeeded.
                    # fix(#1778): unlike `regenerate_vrt` there's
                    # nothing to reap here; the skipped followups (cache
                    # purge, embedding defer) are both recoverable.
                    publish_committed = True
                    absorb_cancellation(exc)
                    return
                publish_committed = True

                # Invalidate cache
                await invalidate_catalog_cache()

                # 13. Generate embedding (non-fatal)
                from app.processing.embeddings.helpers import defer_embedding

                await defer_embedding(dataset)

            except Exception:  # broad: re-raised below; rollback first so the
                # outer handler can write a clean failure record via a fresh session.
                await session.rollback()
                raise

    except Exception as exc:  # broad: VRT pipeline includes GDAL subprocesses and rasterio — any step can fail
        if publish_committed:
            # fix(#1778): the second way this handler is reached with
            # a durable publish behind it, and the one the stand-down above
            # cannot cover: `invalidate_catalog_cache` and `defer_embedding`
            # run inside the same try, so a Valkey outage or a busy queue lands
            # here after the dataset is live and the writes below would report
            # a build that succeeded as failed.
            structlog.get_logger().warning(
                "vrt_post_publish_followup_failed",
                job_id=job_id,
                task="ingest_vrt",
                exc_info=True,
            )
            return
        # fix(#1778): write failure status via a fresh session, through the
        # same shared helper the re-upload doors use. This tail used to paste a
        # narrower copy of the UPDATE and emitted no `ingest_failed`
        # notification, so a VRT build failure was silent to an operator who
        # had failure mail on. `staging_table=""` because a VRT build has no
        # staging table — its artifacts are the object keys the `finally`
        # below reaps.
        async with async_session() as err_session:
            err_job = await load_job_for_error_write(
                err_session, job_uuid, attempt_uuid, task_name="ingest_vrt"
            )
            if err_job is not None:
                await _cleanup_staging_on_failure(
                    err_session,
                    staging_table="",
                    job=err_job,
                    exc=exc,
                    task_name="ingest_vrt",
                    attempt_id=attempt_uuid,
                )
            else:
                structlog.get_logger().exception(
                    "Ingest task failed",
                    extra={"job_id": job_id, "task": "ingest_vrt"},
                )
        raise
    finally:
        async with cleanup_step("ingest_vrt heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("ingest_vrt temp dir", job_id=job_id):
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        # fix(#430): reap storage bytes written before a terminal commit
        # that never became durable (mirrors ingest_raster's GAP-017 guard).
        async with cleanup_step("ingest_vrt orphaned storage keys", job_id=job_id):
            if not publish_committed and written_storage_keys:
                from app.processing.ingest.tasks_raster import (
                    _cleanup_orphaned_storage_keys,
                )

                await _cleanup_orphaned_storage_keys(
                    written_storage_keys, job_id=job_id
                )


@task_app.task(queue="raster", retry=0, aliases=["app.ingest.tasks.regenerate_vrt"])
@tenant_task
async def regenerate_vrt(
    job_id: str,
    vrt_dataset_id: str,
    attempt_id: str | None = None,
    generation_id: str | None = None,
    triggered_by: str = "system",
    **kwargs,
) -> None:
    """Background task: rebuild a VRT file after source add/remove and update metadata.

    Atomic publish: the rebuilt VRT is written to generation-specific
    immutable keys. The RasterAsset pointer changes only in the same
    transaction that verifies job attempt and generation ownership, then
    prior objects are reaped.

    Composition source (fix(#1327)): the generation's ``staged_source_ids``
    when it carries one (``add_vrt_source``/``remove_vrt_source`` record
    the intended post-mutation member set there rather than writing
    ``vrt_source_links`` up front), else the live link rows. Applied to
    ``vrt_source_links`` in step 12, inside the publish transaction, so
    declared composition and built artifact become visible in one commit.

    Full pipeline:
    1. Mark job running
    2. Load VRT RasterAsset
    3. Load the member set: staged set if any, else vrt_source_links by position
    4. Load source RasterAsset rows, resolve paths
    5. Build new VRT to temp path
    6. Post-validate via rasterio
    7. Extract metadata from new VRT
    8. Hash and size new VRT
    9. Generate quicklooks (non-fatal)
    10. Write immutable generation storage keys
    11. Update RasterAsset metadata fields
    12. Set status='ready', last_regenerated_at, built_from, clear
        current_generation_id, apply the staged member set to vrt_source_links
    13. Update dataset footprint geometry
    14. Mark job complete
    15. Invalidate cache, defer embedding

    Session lifecycle (gh #100): same two-phase split as ``ingest_vrt`` —
    the session is closed before the GDAL subprocess + asyncio.to_thread
    work and reopened for the metadata updates.
    """
    import asyncio

    from app.core.db import async_session  # fix(#909): late-bind for tests

    _bind_task_log_context(
        task_name="regenerate_vrt",
        job_id=job_id,
        vrt_dataset_id=vrt_dataset_id,
    )
    import io
    import os
    import shutil
    import tempfile

    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from sqlalchemy import func, select, text, update

    Dataset = get_processing_port().get_dataset_orm_class()

    logger_regen = __import__("logging").getLogger(__name__)

    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="vrt"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    vrt_id = uuid.UUID(vrt_dataset_id)
    tmp_dir: str | None = None
    generation_uuid: uuid.UUID | None = None
    # fix(#1327): the member set this attempt is publishing, when its
    # generation staged one. Set in phase 1 (and used for the build there),
    # applied to vrt_source_links in phase 2's publish transaction.
    staged_source_ids: list[uuid.UUID] | None = None
    vrt_asset_snapshot = None
    heartbeat_task: asyncio.Task[None] | None = None
    generation_heartbeat_task: asyncio.Task[None] | None = None
    written_storage_keys: list[str] = []
    prior_storage_keys: list[str] = []
    # fix(#1778): same fence as `ingest_vrt` above, for the same reason — the
    # generation swap and the job's terminal write share one transaction, so a
    # lost acknowledgement must not let the reap delete the generation the
    # RasterAsset now points at. See `publish_commit_landed`.
    publish_committed: bool = False

    try:
        # ----------------------------------------------------------------- #
        # Phase 1 (short-lived session): load job, mark running, load VRT
        # asset + source links + source assets, create generation record.
        # Snapshot all values needed for phase 2.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            result = await session.execute(
                select(IngestJob).where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                )
            )
            job = result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job not found, skipping", job_id=job_id
                )
                return

            # 1. Mark running
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid
            )
            if heartbeat_task is None:
                return

            # 2. Load VRT RasterAsset
            asset_result = await session.execute(
                select(RasterAsset)
                .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                .where(Dataset.id == vrt_id)
            )
            vrt_asset_row = asset_result.scalar_one_or_none()
            if vrt_asset_row is None:
                raise ValueError(f"VRT dataset {vrt_dataset_id} not found")
            vrt_asset_snapshot = vrt_asset_row

            # 3. Load vrt_source_links ordered by position — the composition
            # currently being SERVED. fix(#1327): still read first and still
            # required to be non-empty, for both paths. It is the default
            # member set (step 3c may replace it with the generation's staged
            # one), and a VRT with no links at all is a broken row either way:
            # nothing legitimately creates one, and building "whatever the
            # staged set says" over it would quietly repair a state worth
            # failing on.
            links_result = await session.execute(
                text(
                    "SELECT source_dataset_id FROM catalog.vrt_source_links "
                    "WHERE vrt_dataset_id = :vrt_id ORDER BY position ASC"
                ),
                {"vrt_id": vrt_id},
            )
            source_ids = [row.source_dataset_id for row in links_result.fetchall()]
            if not source_ids:
                raise ValueError(f"VRT {vrt_dataset_id} has no source links")

            # 3b. Claim the single generation created by the enqueueing API.
            # Legacy queued deliveries may not carry generation_id; they may
            # adopt only the exact pointer already stored on the asset. The
            # compare-and-swap below prevents an old delivery from taking over
            # a newer generation.
            requested_generation_id = (
                uuid.UUID(generation_id)
                if generation_id is not None
                else vrt_asset_row.current_generation_id
            )
            legacy_pointer = vrt_asset_row.current_generation_id
            generation = None
            if requested_generation_id is not None:
                gen_result = await session.execute(
                    select(VrtGeneration).where(
                        VrtGeneration.id == requested_generation_id,
                        VrtGeneration.vrt_dataset_id == vrt_id,
                    )
                )
                generation = gen_result.scalar_one_or_none()

            if generation is None:
                if generation_id is not None:
                    raise ValueError(
                        f"VrtGeneration {generation_id} not found for {vrt_dataset_id}"
                    )
                generation = VrtGeneration(
                    vrt_dataset_id=vrt_id,
                    status="running",
                    started_at=datetime.now(timezone.utc),
                    heartbeat_at=datetime.now(timezone.utc),
                    source_count=len(source_ids),
                    triggered_by=triggered_by,
                )
                session.add(generation)
                await session.flush()
                generation_uuid = generation.id
                asset_claim = await session.execute(
                    update(RasterAsset)
                    .where(
                        RasterAsset.dataset_id == vrt_id,
                        RasterAsset.status == "regenerating",
                        RasterAsset.current_generation_id == legacy_pointer,
                    )
                    .values(current_generation_id=generation_uuid)
                    .returning(RasterAsset.dataset_id)
                )
                if asset_claim.scalar_one_or_none() is None:
                    raise ValueError("VRT generation ownership changed before claim")
            else:
                generation_uuid = generation.id
                generation_claim = await session.execute(
                    update(VrtGeneration)
                    .where(
                        VrtGeneration.id == generation_uuid,
                        VrtGeneration.status == "pending",
                    )
                    .values(
                        status="running",
                        started_at=datetime.now(timezone.utc),
                        heartbeat_at=datetime.now(timezone.utc),
                    )
                    .returning(VrtGeneration.id)
                )
                if generation_claim.scalar_one_or_none() is None:
                    raise ValueError("VRT generation is no longer pending")
                if vrt_asset_row.current_generation_id != generation_uuid:
                    raise ValueError("VRT generation ownership changed before claim")

            # 3c. fix(#1327): build from the STAGED member set when this
            # generation carries one — the live link rows read above still
            # describe the VRT currently being served, not the one this
            # attempt is being asked to publish. Building from the links
            # would rebuild the existing composition and then apply a set
            # the artifact doesn't contain. A generation that stages
            # nothing (plain regenerate) keeps the live links.
            staged_source_ids = staged_source_ids_or_none(generation)
            if staged_source_ids is not None:
                source_ids = staged_source_ids

            await session.commit()
            generation_heartbeat_task = asyncio.create_task(
                maintain_vrt_generation_heartbeat(generation_uuid)
            )

            # 4. Load source RasterAsset rows and resolve paths
            snapshot_at, ordered_assets = await snapshot_member_sources(
                session, source_ids, raster_asset_cls=RasterAsset, dataset_cls=Dataset
            )
            # fix(#1327): every member of the set being built must still be
            # loadable, or the build silently publishes a mosaic missing a
            # member it claims (snapshot_member_sources drops what it cannot
            # find). A LIVE link cannot vanish — vrt_source_links pins its
            # source with ON DELETE RESTRICT — but a STAGED id is not a link
            # row yet, so the window between staging and applying is the one
            # place a member can disappear underneath an attempt. Failing here
            # leaves the links untouched and the served VRT intact; the caller
            # re-issues the add or remove against the set that survived.
            if len(ordered_assets) != len(source_ids):
                found = {asset.dataset_id for asset in ordered_assets}
                missing = [str(sid) for sid in source_ids if sid not in found]
                raise ValueError(
                    f"VRT {vrt_dataset_id} member sources are no longer "
                    f"available: {', '.join(missing)}"
                )
            from app.core.db.tenant_session import current_tenant_var

            source_paths = [
                resolve_vrt_source_path(a.asset_uri, tenant_id=current_tenant_var.get())
                for a in ordered_assets
            ]

            # Snapshot the VRT asset's invariant config for phase 2
            # (the existing storage key + quicklook keys + VRT type/strategy).
            vrt_storage_key: str = vrt_asset_row.asset_uri  # unchanged across regen
            vrt_ql256_uri: str | None = vrt_asset_row.quicklook_256_uri
            vrt_ql512_uri: str | None = vrt_asset_row.quicklook_512_uri
            vrt_type: str = vrt_asset_row.vrt_type or "mosaic"
            resolution_strategy: str = vrt_asset_row.resolution_strategy or "finest"

        # ----------------------------------------------------------------- #
        # CPU work — NO session open.
        # ----------------------------------------------------------------- #

        # 5. Build VRT to temp path
        tmp_dir = tempfile.mkdtemp()
        vrt_path = os.path.join(tmp_dir, "source.vrt")

        await asyncio.to_thread(
            build_vrt, vrt_type, source_paths, vrt_path, resolution_strategy
        )

        # 6 & 7. Extract metadata (also serves as post-validation)
        meta = await asyncio.to_thread(read_vrt_metadata, vrt_path)
        if not meta.get("crs_wkt"):
            raise ValueError("Regenerated VRT has no coordinate reference system.")

        # 8. Hash and size
        new_sha256 = await asyncio.to_thread(sha256_file, vrt_path)
        new_size = os.path.getsize(vrt_path)

        # 9. Generate quicklooks (non-fatal)
        ql256: bytes | None = None
        ql512: bytes | None = None
        try:
            ql256 = await asyncio.to_thread(render_vrt_quicklook, vrt_path, 256)
            ql512 = await asyncio.to_thread(render_vrt_quicklook, vrt_path, 512)
        except Exception:  # broad: quicklook generation is non-fatal
            logger_regen.warning(
                "Quicklook regeneration failed for VRT %s",
                vrt_dataset_id,
                exc_info=True,
            )

        assert generation_uuid is not None
        generation_base_key = f"rasters/{vrt_id}/generations/{generation_uuid}"
        next_vrt_storage_key = f"{generation_base_key}/source.vrt"
        next_ql256_uri = f"{generation_base_key}/quicklook_256.png"
        next_ql512_uri = f"{generation_base_key}/quicklook_512.png"

        # 10. Write immutable generation objects. The catalog pointer switches
        # only after the job lease and current_generation_id are checked
        # together in phase 2, so a stale worker can never overwrite the
        # live generation.
        #
        # ORDERING: rewrite_vrt_sources runs AFTER metadata extraction and
        # quicklook generation — the in-flight tmp .vrt must hold concrete
        # resolvable paths for GDAL; only the STORED copy is rewritten to
        # logical relativeToVRT="1" keys (STOR-03). CR-01: vrt_storage_key
        # is supplied so paths compute relative to the VRT's own directory.
        import pathlib as _pathlib

        from app.core.db.tenant_session import current_tenant_var as _ctv
        from app.platform.storage.titiler_url import resolve_storage_key

        next_vrt_physical_key = resolve_storage_key(
            next_vrt_storage_key, tenant_id=_ctv.get()
        )

        _regen_rewrite_changes = rewrite_vrt_sources(
            _pathlib.Path(vrt_path), vrt_storage_key=next_vrt_physical_key
        )
        if _regen_rewrite_changes:
            logger_regen.info(
                "VRT regen store-path rewrite: %d SourceFilename(s) normalised to logical keys",
                len(_regen_rewrite_changes),
                extra={
                    "changes": _regen_rewrite_changes,
                    "vrt_dataset_id": vrt_dataset_id,
                },
            )

        storage = get_storage()

        next_ql256_physical_key = resolve_storage_key(
            next_ql256_uri, tenant_id=_ctv.get()
        )
        next_ql512_physical_key = resolve_storage_key(
            next_ql512_uri, tenant_id=_ctv.get()
        )

        # fix(#1778): registered before the put, per archive_lossy_original's
        # rule. A cancelled put can have completed, and CancelledError skips
        # every statement below it.
        written_storage_keys.append(next_vrt_physical_key)
        with open(vrt_path, "rb") as fobj:
            await storage.put(next_vrt_physical_key, fobj)

        if ql256 is not None:
            written_storage_keys.append(next_ql256_physical_key)
            await storage.put(next_ql256_physical_key, io.BytesIO(ql256))
        if ql512 is not None:
            written_storage_keys.append(next_ql512_physical_key)
            await storage.put(next_ql512_physical_key, io.BytesIO(ql512))

        prior_storage_keys = _prior_generation_storage_keys_to_reap(
            vrt_key=vrt_storage_key,
            quicklook_256_key=vrt_ql256_uri,
            quicklook_512_key=vrt_ql512_uri,
            replace_quicklook_256=ql256 is not None,
            replace_quicklook_512=ql512 is not None,
            tenant_id=_ctv.get(),
        )

        # Phase 2 (short-lived session): update RasterAsset metadata, mark
        # job complete, update dataset footprint.
        #
        # fix(#1778): status == "running" joins the attempt fence.
        # The `current_generation_id` check below refuses a NEWER
        # generation's publish, but says nothing about a job the stale
        # sweep already failed with no newer generation existing yet — that
        # sweep never touches `vrt_asset.current_generation_id`. Without
        # this, a worker only paused (not dead) could still complete the
        # job and switch the live pointer after the sweep declared it dead.
        # The objects written above are unaffected either way — reaped by
        # `sweep_stale_vrt_assets` on its own timeout.
        #
        # fix(#1847): job row first, then asset — the order every worker
        # phase, `cancel_job`, and the dataset delete hold.
        async with async_session() as session:
            result = await session.execute(
                select(IngestJob)
                .where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == attempt_uuid,
                    IngestJob.status == "running",
                )
                .with_for_update(key_share=True)
            )
            job = result.scalar_one_or_none()
            if job is None:
                structlog.get_logger().warning(
                    "Ingest job vanished between phases, skipping",
                    job_id=job_id,
                )
                return

            try:
                # Re-load VRT asset in the new session.
                asset_result = await session.execute(
                    select(RasterAsset)
                    .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                    .where(Dataset.id == vrt_id)
                    .with_for_update()
                )
                vrt_asset = asset_result.scalar_one_or_none()
                if vrt_asset is None:
                    raise ValueError(
                        f"VRT dataset {vrt_dataset_id} disappeared between phases"
                    )
                if vrt_asset.current_generation_id != generation_uuid:
                    raise ValueError("VRT generation ownership changed before publish")

                # Re-load generation record.
                gen_result = await session.execute(
                    select(VrtGeneration).where(VrtGeneration.id == generation_uuid)
                )
                generation = gen_result.scalar_one_or_none()
                if generation is None:
                    raise ValueError(
                        f"VrtGeneration {generation_uuid} disappeared between phases"
                    )

                # 11. Update RasterAsset metadata fields
                nodata_val = meta.get("nodata")
                vrt_asset.sha256 = new_sha256
                vrt_asset.asset_uri = next_vrt_storage_key
                if ql256 is not None:
                    vrt_asset.quicklook_256_uri = next_ql256_uri
                if ql512 is not None:
                    vrt_asset.quicklook_512_uri = next_ql512_uri
                vrt_asset.size_bytes = new_size
                vrt_asset.crs_wkt = meta.get("crs_wkt")
                vrt_asset.epsg = meta.get("epsg")
                vrt_asset.band_count = meta.get("band_count")
                vrt_asset.dtype = meta.get("dtype")
                # Recompute the DEM flag on regenerate so adding/removing a source
                # flips it correctly when the band/dtype profile changes (#185).
                vrt_asset.is_dem = meta.get("is_dem_candidate", False)
                vrt_asset.nodata = str(nodata_val) if nodata_val is not None else None
                vrt_asset.res_x = meta.get("res_x")
                vrt_asset.res_y = meta.get("res_y")
                vrt_asset.width = meta.get("width")
                vrt_asset.height = meta.get("height")
                vrt_asset.compression = meta.get("compression")

                # 12. Status transitions
                vrt_asset.status = "ready"
                # fix(#1290): the snapshot instant, NOT now(). See the
                # capture site in phase 1 for why the field names the state the
                # artifact was built from.
                vrt_asset.last_regenerated_at = snapshot_at
                # fix(#1290): recorded from the SAME ordered_assets the
                # build used, in the publish transaction, so the stored set and
                # the stored VRT always describe each other.
                vrt_asset.built_from = built_from_map(ordered_assets)
                vrt_asset.current_generation_id = None
                if vrt_asset_snapshot is not None:
                    vrt_asset_snapshot.status = vrt_asset.status
                    vrt_asset_snapshot.last_regenerated_at = (
                        vrt_asset.last_regenerated_at
                    )
                    vrt_asset_snapshot.current_generation_id = None

                # 12a. fix(#1327): the staged member set lands HERE, in the
                # transaction that publishes the artifact built from it and
                # writes built_from — never at request time — so
                # vrt_source_links can never describe a composition the
                # served bytes don't have. Applies the SAME list phase 1
                # built from, not a re-read of the generation row, so the
                # link set and artifact can't disagree even in principle.
                if staged_source_ids is not None:
                    await apply_staged_source_links(session, vrt_id, staged_source_ids)

                # 12b. Update generation record
                generation.status = "completed"
                generation.completed_at = datetime.now(timezone.utc)
                # `started_at` is set at record creation in phase 1 — guarded
                # here so mypy/runtime don't crash if a future refactor drops it.
                if generation.started_at is not None:
                    generation.duration_seconds = (
                        generation.completed_at - generation.started_at
                    ).total_seconds()

                # 13. Update dataset footprint geometry
                dataset_result = await session.execute(
                    select(Dataset).where(Dataset.id == vrt_id)
                )
                vrt_dataset = dataset_result.scalar_one_or_none()
                if vrt_dataset is not None:
                    # fix(#1847, #1938): the writes below dirty both rows. The
                    # asset SELECT above took the datasets row through its join;
                    # catalog.records is not in that query, so it is a real wait.
                    from app.platform.catalog_locks import (
                        CatalogLockConflict,
                        lock_catalog_rows,
                    )

                    # fix(#1938): read before the wait — the rollback inside a
                    # failed acquisition expires every loaded instance.
                    log_dataset_id = str(vrt_dataset.id)
                    pre_wait_lock_timeout = await session.scalar(
                        text("SELECT current_setting('lock_timeout')")
                    )
                    wait_started = time.perf_counter()
                    try:
                        await lock_catalog_rows(
                            session,
                            dataset_cls=Dataset,
                            record_cls=type(vrt_dataset.record),
                            dataset_id=vrt_dataset.id,
                            record_id=vrt_dataset.record_id,
                            lock_timeout=_PUBLISH_CATALOG_TIMEOUT,
                        )
                    except CatalogLockConflict as conflict:
                        _log_publish_wait_failure(
                            conflict,
                            job_id=job_id,
                            dataset_id=log_dataset_id,
                            waited_ms=round(
                                (time.perf_counter() - wait_started) * 1000
                            ),
                        )
                        raise
                    # fix(#1938): the budget ends with the wait it was sized
                    # for. The UPDATEs below sit outside lock_catalog_rows, so
                    # an expiry there would raise a bare DBAPIError.
                    await session.execute(
                        text("SELECT set_config('lock_timeout', :value, true)"),
                        {"value": pre_wait_lock_timeout},
                    )
                    # feat(#1267) / ADR-002 Decision 5a: project the
                    # generation's completion instant into last_refreshed_at,
                    # in the SAME transaction as the generation swap, so
                    # source_freshness (#1224) reads a live signal for a NULL
                    # origin (VRT) instead of the creation-time floor forever.
                    # Same instant as generation.completed_at, not a fresh
                    # now() — one swap, one timestamp, no clock skew between
                    # the two records of it.
                    vrt_dataset.last_refreshed_at = generation.completed_at
                    # fix(#1329): the VRT swap is the third
                    # pointer-swap door and never rolled the version the way
                    # raster replace does (tasks_raster_swap). Without the
                    # bump, pre-swap tiles stay valid in every version-keyed
                    # cache (the nginx tile cache via the URL `v=`, the
                    # per-process raster meta cache) until their TTLs, so a
                    # regeneration that changes band shape can render wrong
                    # until they expire. Same transaction as the pointer swap,
                    # same as every other door.
                    vrt_dataset.bump_tile_cache_version()
                    if meta.get("bbox_wkt"):
                        vrt_dataset.record.spatial_extent = func.ST_GeomFromText(
                            meta["bbox_wkt"], 4326
                        )

                # Keep download/STAC references aligned with the newly published
                # immutable generation keys in the same transaction.
                await session.execute(
                    text(
                        "UPDATE catalog.record_distributions SET url = :url "
                        "WHERE record_id = (SELECT record_id FROM catalog.datasets "
                        "WHERE id = :dataset_id) AND format = 'vrt'"
                    ),
                    {"url": next_vrt_storage_key, "dataset_id": vrt_id},
                )
                await session.execute(
                    text(
                        "UPDATE catalog.dataset_assets SET href = CASE key "
                        "WHEN 'vrt' THEN :vrt_key "
                        "WHEN 'thumbnail' THEN :ql256_key "
                        "WHEN 'overview' THEN :ql512_key ELSE href END, "
                        "size_bytes = CASE WHEN key = 'vrt' THEN :size ELSE size_bytes END "
                        "WHERE dataset_id = :dataset_id AND key IN ('vrt', 'thumbnail', 'overview')"
                    ),
                    {
                        "vrt_key": next_vrt_storage_key,
                        "ql256_key": next_ql256_uri
                        if ql256 is not None
                        else vrt_ql256_uri,
                        "ql512_key": next_ql512_uri
                        if ql512 is not None
                        else vrt_ql512_uri,
                        "size": new_size,
                        "dataset_id": vrt_id,
                    },
                )

                # 14. Finalize job
                await require_ingest_job_update(
                    session,
                    job_uuid,
                    attempt_uuid,
                    values={
                        "status": "complete",
                        "dataset_id": vrt_id,
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
                try:
                    await session.commit()
                except BaseException as exc:
                    if not await publish_commit_landed(
                        job_uuid, attempt_uuid, job_id=job_id, task="regenerate_vrt"
                    ):
                        raise
                    # fix(#1778): stand down rather than re-raise. The
                    # generation swap is durable, so every write the failure
                    # handler would make is a statement about a job that
                    # succeeded, and the generation row it stamps `failed` is
                    # not fenced the way the job and asset writes are.
                    publish_committed = True
                    absorb_cancellation(exc)
                    # fix(#1778): standing down from the FAILURE
                    # handler is not standing down from the success work. This
                    # is the only deletion of the superseded generation's
                    # objects, and the committed asset already names the new
                    # ones, so returning without it strands bytes no row
                    # references and no quota counts. No guard: the reaper
                    # swallows a missing provider and every per-key error, so
                    # it cannot turn a durable publish back into a failure.
                    await _reap_superseded_generation_objects(
                        prior_storage_keys=prior_storage_keys,
                        written_storage_keys=written_storage_keys,
                        job_id=job_id,
                    )
                    return
                publish_committed = True

                await _reap_superseded_generation_objects(
                    prior_storage_keys=prior_storage_keys,
                    written_storage_keys=written_storage_keys,
                    job_id=job_id,
                )

                # 15. Invalidate cache and defer embedding
                await invalidate_catalog_cache()
                if vrt_dataset is not None:
                    await defer_embedding(vrt_dataset)

            except Exception:  # broad: re-raised below; rollback first so the
                # outer handler can write a clean failure record via a fresh session.
                await session.rollback()
                raise

    except Exception as exc:  # broad: VRT regeneration includes GDAL subprocesses and rasterio — any step can fail
        if publish_committed:
            # fix(#1778): the second way this handler is reached with
            # a durable publish behind it, and the one the stand-down above
            # cannot cover: the prior-key reap, `invalidate_catalog_cache` and
            # `defer_embedding` all run inside the same try. The generation
            # write below is not fenced the way the job and asset writes are,
            # so reaching here after the swap stamped a `completed` generation
            # `failed`, which `get_vrt_status` reads as "no completed
            # generation" and the stale-generation sweep reads as evidence the
            # asset was unhealthy.
            structlog.get_logger().warning(
                "vrt_post_publish_followup_failed",
                job_id=job_id,
                task="regenerate_vrt",
                exc_info=True,
            )
            return
        structlog.get_logger().exception(
            "Ingest task failed",
            job_id=job_id,
            task="regenerate_vrt",
        )
        # fix(#1962): the asset settles first and alone. `sweep_stale_vrt_assets`
        # fences its asset UPDATE on the generations it just failed, so an asset
        # still pointing at a terminal one is the state it can never reach.
        asset_settled = await _settle_failed_vrt_asset(
            vrt_id, generation_uuid, job_id=job_id
        )
        # The job and generation rows follow in one transaction. Losing both to
        # a contended job row is recoverable: the sweep fails a generation whose
        # heartbeat went stale, and the stale-job sweep settles the job.
        try:
            async with async_session() as err_session:
                # fix(#1950): the publish wait above gives up on a held
                # catalog row, so this handler runs while the job row may be
                # contended too. Both writes below share the budget.
                await arm_job_error_write_budget(err_session)
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
                # fix(#1962): only once the asset is off this generation. A
                # terminal generation under an asset still pointing at it is
                # the state `sweep_stale_vrt_assets` fences itself out of.
                if generation_uuid is not None and asset_settled:
                    gen_result = await err_session.execute(
                        select(VrtGeneration).where(VrtGeneration.id == generation_uuid)
                    )
                    gen = gen_result.scalar_one_or_none()
                    # fix(#1778): fenced at the statement, not only
                    # at the caller — a future path into this handler cannot
                    # relabel a generation whose artifact is published.
                    if gen and gen.status != "completed":
                        gen.status = "failed"
                        gen.completed_at = datetime.now(timezone.utc)
                        if gen.started_at:
                            gen.duration_seconds = (
                                gen.completed_at - gen.started_at
                            ).total_seconds()
                        gen.error_message = str(exc)

                await err_session.commit()
        except DBAPIError as write_failure:
            # fix(#1950): swallowed so the `raise` below re-raises the cause
            # this handler was called for. Letting an expiry out would hand
            # the operator a lock timeout in place of the build failure.
            log_job_error_write_failure(
                write_failure, job_id=job_id, task="regenerate_vrt"
            )
        raise
    finally:
        async with cleanup_step("regenerate_vrt generation heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(generation_heartbeat_task)
        async with cleanup_step("regenerate_vrt heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("regenerate_vrt temp dir", job_id=job_id):
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        async with cleanup_step("regenerate_vrt orphaned storage keys", job_id=job_id):
            if not publish_committed and written_storage_keys:
                from app.processing.ingest.tasks_raster import (
                    _cleanup_orphaned_storage_keys,
                )

                await _cleanup_orphaned_storage_keys(
                    written_storage_keys, job_id=job_id
                )


# fix(#1327): a SECOND registered name for the SAME regeneration,
# used only by staged mutations (add/remove source), to close a rolling-
# upgrade skew: a pre-#1327 worker doesn't know `staged_source_ids`, would
# rebuild from the live links, and mark the generation COMPLETE — silently
# losing an accepted add/remove. A kwarg can't fence this off (the pre-#1327
# signature ends in `**kwargs`, swallowed silently), but the task NAME can:
# a worker without it raises TaskNotFound and fails the job (status
# 'failed', attempts 1, no retry — see tests/test_vrt_staged_task_skew.py).
#
# That failure leaves a state the existing machinery already handles: the
# task never ran, so vrt_source_links is untouched, the generation stays
# 'pending', and the asset stays 'regenerating' until
# `sweep_stale_vrt_assets` restores 'ready'. The mutation is refused
# rather than half-applied; the caller re-issues it once the roll finishes.
#
# Plain regeneration keeps the legacy name — it changes no membership, so
# a pre-#1327 worker executes it correctly during the roll.
@task_app.task(queue="raster", retry=0)
async def regenerate_vrt_staged(**kwargs) -> None:
    """Regenerate a VRT whose generation carries a staged member set.

    Byte-identical work to ``regenerate_vrt``: one implementation, two
    registered names, and the staged set is read from the generation row on
    either path. The name gates WHICH WORKERS may run it, nothing else.
    ``regenerate_vrt.func`` is the ``tenant_task``-wrapped body, so the tenant
    kwarg is popped and bound exactly once, here at the forward.
    """
    await regenerate_vrt.func(**kwargs)
