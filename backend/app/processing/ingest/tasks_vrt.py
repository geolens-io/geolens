"""Procrastinate task definitions for VRT creation and regeneration.

VRTs are stored with provider-agnostic SourceFilename nodes (logical keys +
relativeToVRT="1"). ``rewrite_vrt_sources`` runs after metadata extraction and
quicklook generation at each store site, because the in-flight .vrt those
probes open must hold concrete paths; only the stored copy is normalised.

At open time, ``resolve_open_path`` (app.platform.storage.titiler_url)
rebuilds the concrete VSI path from the logical key and the current
STORAGE_PROVIDER, so a provider swap needs no change to stored VRT XML.
"""

import time
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from sqlalchemy import select

from app.platform.extensions import RecordAudienceQuery
from app.platform.jobs import ledger
from app.platform.jobs.models import ADMITTED_CAPABILITY_METADATA_KEY
from app.platform.jobs.heartbeat import (
    JOB_ERROR_WRITE_TIMEOUT_MS,
    arm_job_error_write_budget,
    claim_job_attempt_and_start_heartbeat,
    log_job_error_write_failure,
    maintain_vrt_generation_heartbeat,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
)
from app.core.failure_reason import redact_failure_reason
from app.core.db import tenant_task
from app.processing.raster.cog import sha256_file
from app.processing.raster.probe import (
    RENDER_TIMEOUT_SECONDS,
    read_raster_metadata,
    render_quicklook,
)
from app.processing.raster.vrt import build_vrt, resolve_vrt_source_path
from app.processing.raster.vrt_members import note_vrt_members
from app.processing.raster.vrt_rewrite import rewrite_vrt_sources
from app.platform.storage import get_storage

from app.processing.ingest.publication import (
    WriteAccessRevoked,
    require_submitter_can_write,
)
from app.processing.ingest.publish_followups import (
    note_publish_followups,
    owed_followups,
    run_publish_followups,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    cleanup_step,
    load_job_for_error_write,
    task_app,
)
from app.processing.ingest.tasks_staging import _cleanup_staging_on_failure
from app.processing.ingest.tasks_raster_common import (
    absorb_cancellation,
    note_publishing_xid,
    observe_publish_commit,
    publish_commit_landed,
    publishing_xid,
    PublishObservation,
    record_unpublished_storage_keys,
)

# The budget for the publish transaction's catalog.records wait. Its only
# holders are request handlers that dirty the record and hold it from flush to
# commit; nothing caps that, so this is a stuck-not-queued threshold.
_PUBLISH_CATALOG_TIMEOUT = "15s"

# Builds re-check members against the mosaic's audience: access may have
# changed since the request was admitted.
_MEMBER_AUDIENCE_FAILURE = (
    "A source dataset is not visible to everyone this VRT would reach"
)


def _log_publish_wait_failure(
    conflict: BaseException, *, job_id: str, dataset_id: str, waited_ms: int
) -> None:
    """Report a failed publish catalog wait, classified by its SQLSTATE.

    ``dataset_id`` must be read before the acquisition: ``lock_catalog_rows``
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
    """Metadata of a built VRT, read in the probe child.

    Opening the VRT reads every ``/vsis3`` source it names, so it gets the
    render timeout rather than the read one.
    """
    return read_raster_metadata(vrt_path, timeout=RENDER_TIMEOUT_SECONDS)


async def _settle_failed_vrt_asset(
    vrt_dataset_id: uuid.UUID,
    generation_uuid: uuid.UUID | None,
    *,
    job_id: str,
) -> bool:
    """Release the VRT asset from the attempt that failed, in its own transaction.

    Releases it when it points at *generation_uuid*, and otherwise when it is
    ``regenerating`` with no live generation owning it. A newer attempt whose
    generation is pending or running keeps the asset, and a ``ready`` one is
    never touched.

    Never raises. Returns whether the asset is provably no longer pointing at
    *generation_uuid*; on False the caller must leave the generation
    non-terminal, or the pair becomes unreachable to the stale sweep.
    """
    import asyncio

    from sqlalchemy import and_, or_, select
    from sqlalchemy import update as sa_update

    from app.core.db import async_session
    from app.processing.raster.models import RasterAsset, VrtGeneration

    # The second arm is the whole rule: a `regenerating` asset is released
    # unless a live generation owns it, because the sweep reaches an asset only
    # through a pending/running generation. A phantom pointer left by a
    # rolled-back phase 1, a NULL one, and one naming a terminal generation are
    # states nothing else can settle.
    owned_by_a_live_generation = (
        select(VrtGeneration.id)
        .where(
            VrtGeneration.id == RasterAsset.current_generation_id,
            VrtGeneration.status.in_(("pending", "running")),
        )
        .exists()
    )
    arms = []
    if generation_uuid is not None:
        arms.append(RasterAsset.current_generation_id == generation_uuid)
    arms.append(and_(RasterAsset.status == "regenerating", ~owned_by_a_live_generation))
    try:
        async with async_session() as session:
            # See `write_job_failure_for_attempt`: SET LOCAL cannot bound the
            # pool checkout, and nothing is in flight yet, so it is bounded here.
            await asyncio.wait_for(
                session.connection(), timeout=JOB_ERROR_WRITE_TIMEOUT_MS / 1000
            )
            await arm_job_error_write_budget(session)
            await session.execute(
                sa_update(RasterAsset)
                .where(RasterAsset.dataset_id == vrt_dataset_id, or_(*arms))
                .values(status="failed", current_generation_id=None)
            )
            await session.commit()
    except (SQLAlchemyError, TimeoutError) as write_failure:
        # Wider than the budget's own DBAPIError: this runs outside the
        # handler's try, so a pool timeout escaping here would replace the
        # build failure and skip the job write.
        log_job_error_write_failure(write_failure, job_id=job_id, task="regenerate_vrt")
        return False
    return True


def _prior_generation_keys_to_reap(
    *,
    vrt_key: str,
    quicklook_256_key: str | None,
    quicklook_512_key: str | None,
    replace_quicklook_256: bool,
    replace_quicklook_512: bool,
) -> list[str]:
    """The logical keys of the prior objects whose catalog pointers will be replaced."""
    logical_keys = [vrt_key]
    if replace_quicklook_256 and quicklook_256_key is not None:
        logical_keys.append(quicklook_256_key)
    if replace_quicklook_512 and quicklook_512_key is not None:
        logical_keys.append(quicklook_512_key)
    return logical_keys


async def snapshot_member_sources(
    session, dataset_ids, *, raster_asset_cls, dataset_cls
):
    """Stamp the instant, then read the members. Returns ``(snapshot_at, assets)``.

    ``last_regenerated_at`` names the state a VRT was built from, which holds
    only if the instant predates the read. A replacement landing in the
    stamp-to-read window then at worst reports the parent `stale` when it's
    fine (a cheap extra regenerate); stamping after would let a parent whose
    VRT references a reaped COG report `healthy`.
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

    The health endpoint compares each member's committed ``asset_uri`` with
    the entry recorded here, so staleness is a state comparison rather than a
    race between two clocks. Derived from the ``ordered_assets`` the build
    reads, so the recorded set is the set that was used.
    """
    return {str(a.dataset_id): a.asset_uri for a in ordered_assets}


def staged_source_ids_or_none(generation) -> list[uuid.UUID] | None:
    """The generation's staged member set as UUIDs, or None when it stages none.

    NULL means "this generation changes no membership" (a plain regenerate),
    which builds from the live link rows. A JSONB ``null`` also reads back as
    ``None``, and a non-list value gets the same answer.

    The rest is checked at claim time, before anything is built: an empty
    set, an unparseable id or a repeated id fails now rather than after a
    GDAL build with an obscure ON CONFLICT error.
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

    Called only from the publish transaction that also swaps ``asset_uri``
    and writes ``built_from``, so the declared composition becomes visible
    with the built artifact.

    A replace, not a diff: upsert the whole staged set, then delete
    everything else for this VRT. Idempotent, and the upsert keeps
    ``created_at`` on surviving rows. The empty guard stops an empty list
    from compiling into ``NOT IN ()`` and deleting every link the VRT has.
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

    ``dataset_id`` lets the manifest-VRT tail name its object keys on the
    durable job row before this transaction opens, as on
    ``create_raster_dataset``.

    Returns (record, dataset, raster_asset).
    """
    from sqlalchemy import func, text

    from app.platform.extensions import get_processing_port
    from app.processing.raster.models import RasterAsset

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()
    Record = port.get_record_orm_class()

    # Authoritative count-cap check in the transaction that inserts the
    # Record (the upload-time pre-check is not atomic).
    from app.modules.quota.service import reserve_dataset_slot

    await reserve_dataset_slot(session, created_by)

    record = Record(
        title=title,
        summary=summary,
        record_type="vrt_dataset",
        visibility=visibility,
        # As in the vector and raster paths; a `draft` public VRT would 404
        # on public tile access.
        record_status=record_status,
        # Without it the record is invisible to the per-user quota count and
        # owner checks.
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
        # Assembling a VRT is a materialization, stamped like every other
        # creation path. A Python value, because a SQL expression leaves the
        # attribute expired.
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
        # The instant the members were read, so a never-regenerated parent
        # doesn't fall back to publish-time `ingested_at` in the staleness
        # comparison. The manifest-VRT caller has no snapshot.
        last_regenerated_at=snapshot_at,
        # The authoritative staleness input; the timestamp above serves rows
        # that have no built-from set.
        built_from=built_from,
        epsg=meta.get("epsg"),
        band_count=meta.get("band_count"),
        dtype=meta.get("dtype"),
        # A mosaic of single-band float DEM tiles is itself a DEM, usable for
        # terrain and hillshade.
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
    raster_asset.set_crs(meta)
    session.add(raster_asset)
    await session.flush()

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

    The AsyncSession is split into short-lived blocks so it is not held open
    across the CPU work in steps 5-8 (each runs via ``asyncio.to_thread``).
    """
    _bind_task_log_context(task_name="ingest_vrt", job_id=job_id)
    import asyncio
    import io
    import json as _json
    import os
    import shutil
    import tempfile

    from app.core.db import async_session  # late-bind for tests
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
    # Storage puts, so a failure after a put reaps the VRT and quicklook bytes
    # instead of orphaning them.
    written_storage_keys: list[str] = []
    # "The VRT and its quicklooks are published", set at the terminal commit
    # and nowhere else, so a commit whose acknowledgement was lost never lets
    # the reap delete what a committed RasterAsset names (see
    # `publish_commit_landed`).
    publish_committed: bool = False
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        # Phase 1: load the job, mark it running, load the source asset rows
        # and snapshot what phase 2 needs.
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
            # Committed before the members are read, so replacing one keeps the
            # COG this build may name until its VRT is published.
            await note_vrt_members(session, job_uuid, attempt_uuid, ids)
            await session.commit()

            um: dict = job.user_metadata or {}
            new_vrt = RecordAudienceQuery(
                dataset_id=None,
                record_id=None,
                owner_id=uuid.UUID(user_id),
                visibility=um.get("visibility", "private"),
                record_status="published",
            )
            if await _port.vrt_members_beyond_audience(session, ids, new_vrt):
                raise ValueError(_MEMBER_AUDIENCE_FAILURE)

            # 3. Load RasterAsset rows for source datasets, stamped first, so a
            # member replaced during the initial build shows as stale.
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

        # CPU work, with no session open.

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

        # As in `ingest_raster`: steps 10-11 put objects before the terminal
        # commit, and a kill between put and commit loses the local
        # `written_storage_keys` and rolls back the dataset row whose id the
        # keys embed. Recording the keys on the durable job row first lets the
        # stale-job sweeps reap them. The id is generated per invocation, so a
        # retry can't reproduce a key: this tail's attempt fence.
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
            # A confirmed fence miss. Stopping here keeps the recorder's
            # contract ("do not write what nothing records") without relying
            # on phase 2's own fence, and skips the quicklooks.
            return

        # 8. Generate quicklooks (non-fatal)
        ql256: bytes | None = None
        ql512: bytes | None = None
        try:
            ql256 = await asyncio.to_thread(render_quicklook, vrt_path, 256)
            ql512 = await asyncio.to_thread(render_quicklook, vrt_path, 512)
        except Exception:  # broad: quicklook generation is non-fatal
            logger_vrt.warning(
                "Quicklook generation failed for VRT %s", job_id, exc_info=True
            )

        # Phase 2: create DB records, store assets, commit the job. The fence
        # matches `_job_phase_session(require_status="running")` by hand: a
        # paused, not dead, worker can still match an (id, attempt)-only fence
        # and put objects no rollback can undo, and `key_share` locking closes
        # the window between this read and the puts completing.
        async with async_session() as session:
            await note_publishing_xid(session)
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
                # `dataset.id` is `planned_dataset_id`, the id the durable
                # record above named.
                base_key = f"rasters/{dataset.id}/{asset_sha256}"
                vrt_key = f"{base_key}/source.vrt"

                from app.core.db.tenant_session import current_tenant_var
                from app.platform.storage.titiler_url import resolve_storage_key

                _storage_vrt_key = resolve_storage_key(
                    vrt_key, tenant_id=current_tenant_var.get()
                )

                # After steps 6 and 8 (see the module docstring). The storage
                # key makes paths relative to the VRT's own directory.
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

                # Stored at the tenant-prefixed key the serve path reads; with
                # no tenant the key is unchanged.
                _storage_ql256_key = resolve_storage_key(
                    ql256_key, tenant_id=current_tenant_var.get()
                )
                _storage_ql512_key = resolve_storage_key(
                    ql512_key, tenant_id=current_tenant_var.get()
                )

                # Registered before the put: a cancelled put can have completed,
                # and CancelledError skips every statement below it.
                written_storage_keys.append(_storage_vrt_key)
                with open(vrt_path, "rb") as fobj:
                    await storage.put(_storage_vrt_key, fobj)

                if ql256 is not None:
                    written_storage_keys.append(_storage_ql256_key)
                    await storage.put(_storage_ql256_key, io.BytesIO(ql256))
                if ql512 is not None:
                    written_storage_keys.append(_storage_ql512_key)
                    await storage.put(_storage_ql512_key, io.BytesIO(ql512))

                # 11. Update asset URIs and create distribution. asset_uri keeps
                # the logical key; resolve_open_path adds the tenant prefix.
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
                await note_publish_followups(
                    session, job_uuid, attempt_uuid, "ingest_vrt"
                )
                await ledger.complete(
                    session, job_uuid, attempt_uuid, values={"dataset_id": dataset.id}
                )
                xid = publishing_xid(session)
                try:
                    await session.commit()
                except BaseException as exc:
                    if not await publish_commit_landed(
                        job_uuid,
                        attempt_uuid,
                        xid=xid,
                        error=exc,
                        job_id=job_id,
                        task="ingest_vrt",
                    ):
                        raise
                    # Stand down: the dataset may be live, so the failure handler
                    # would report a job that succeeded. The follow-ups run once
                    # the publish is visible, or the sweep runs them.
                    publish_committed = True
                    absorb_cancellation(exc)
                    await run_publish_followups(job_uuid)
                    return
                publish_committed = True

                await run_publish_followups(job_uuid)

            except Exception:  # broad: re-raised below; rollback first so the
                # outer handler can write a clean failure record via a fresh session.
                await session.rollback()
                raise

    except Exception as exc:  # broad: VRT pipeline includes GDAL subprocesses and rasterio — any step can fail
        if publish_committed:
            # A follow-up failed after the publish; the writes below would
            # report a build that succeeded as failed.
            structlog.get_logger().warning(
                "vrt_post_publish_followup_failed",
                job_id=job_id,
                task="ingest_vrt",
                exc_info=True,
            )
            return
        # A fresh session, through the shared helper that also sends
        # `ingest_failed`. `staging_table=""`: a VRT build has no staging
        # table; its artifacts are the object keys the `finally` reaps.
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

    Composition source: the generation's ``staged_source_ids`` when it
    carries one (``add_vrt_source``/``remove_vrt_source`` record the
    post-mutation member set there rather than writing ``vrt_source_links``
    up front), else the live link rows. Applied to ``vrt_source_links`` in
    step 12, inside the publish transaction, so declared composition and
    built artifact become visible in one commit.

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

    Same two-phase session split as ``ingest_vrt``: closed before the GDAL
    and asyncio.to_thread work, reopened for the metadata updates.
    """
    import asyncio

    from app.core.db import async_session  # late-bind for tests

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

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()

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
    # The member set this attempt publishes, when its generation staged one:
    # built from in phase 1, applied to vrt_source_links in phase 2.
    staged_source_ids: list[uuid.UUID] | None = None
    vrt_asset_snapshot = None
    heartbeat_task: asyncio.Task[None] | None = None
    generation_heartbeat_task: asyncio.Task[None] | None = None
    written_storage_keys: list[str] = []
    # As in `ingest_vrt`: the generation swap and the job's terminal write
    # share one transaction, so a lost acknowledgement must not let the reap
    # delete the generation the RasterAsset now points at.
    publish_committed: bool = False

    try:
        # Phase 1: load the job, mark it running, load the VRT asset, source
        # links and source assets, claim the generation, and snapshot what
        # phase 2 needs.
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

            # 3. Load vrt_source_links by position: the composition being
            # served, and the default member set (3c may replace it). Required
            # non-empty on both paths: nothing legitimately creates a VRT with
            # no links, and building the staged set over one would quietly
            # repair a state worth failing on.
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
            # A delivery without generation_id may adopt only the exact pointer
            # stored on the asset; the compare-and-swap below stops an old
            # delivery from taking over a newer generation.
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

            # 3c. Build from the staged member set when there is one: the live
            # links describe the VRT being served, and building from them would
            # then apply a set the artifact doesn't contain.
            served_ids = set(source_ids)
            staged_source_ids = staged_source_ids_or_none(generation)
            if staged_source_ids is not None:
                source_ids = staged_source_ids

            await session.commit()
            generation_heartbeat_task = asyncio.create_task(
                maintain_vrt_generation_heartbeat(generation_uuid)
            )

            vrt_record = (await port.get_dataset(session, vrt_id)).record
            vrt_audience = RecordAudienceQuery(
                dataset_id=vrt_id,
                record_id=vrt_record.id,
                owner_id=vrt_record.created_by,
                visibility=vrt_record.visibility,
                record_status=vrt_record.record_status,
            )
            # A pure removal links nothing new, so it may proceed while a kept
            # member is outside the audience; tiles stay refused until it fits.
            removal = staged_source_ids is not None and set(source_ids) <= served_ids
            if not removal and await port.vrt_members_beyond_audience(
                session, source_ids, vrt_audience
            ):
                raise ValueError(_MEMBER_AUDIENCE_FAILURE)

            # 4. Load source RasterAsset rows and resolve paths
            snapshot_at, ordered_assets = await snapshot_member_sources(
                session, source_ids, raster_asset_cls=RasterAsset, dataset_cls=Dataset
            )
            # Every member must still be loadable, or the build publishes a
            # mosaic missing a member it claims (snapshot_member_sources drops
            # what it cannot find). A live link is pinned by ON DELETE
            # RESTRICT, but a staged id is not a link row yet and can vanish
            # before it is applied. Failing here leaves the links and the
            # served VRT intact; the caller re-issues the add or remove.
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

            # The VRT asset's current keys and build config, for phase 2.
            vrt_storage_key: str = vrt_asset_row.asset_uri  # unchanged across regen
            vrt_ql256_uri: str | None = vrt_asset_row.quicklook_256_uri
            vrt_ql512_uri: str | None = vrt_asset_row.quicklook_512_uri
            vrt_type: str = vrt_asset_row.vrt_type or "mosaic"
            resolution_strategy: str = vrt_asset_row.resolution_strategy or "finest"

        # CPU work, with no session open.

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
            ql256 = await asyncio.to_thread(render_quicklook, vrt_path, 256)
            ql512 = await asyncio.to_thread(render_quicklook, vrt_path, 512)
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

        # The job row owes these until a sweep confirms them deleted or a live
        # pointer names them. A failed generation is out of the stale
        # generation sweep's reach, so it cannot be their only owner.
        if not await record_unpublished_storage_keys(
            job_uuid,
            attempt_uuid,
            keys=[
                next_vrt_storage_key,
                *([next_ql256_uri] if ql256 is not None else []),
                *([next_ql512_uri] if ql512 is not None else []),
            ],
            already_published=(
                key
                for key in (vrt_storage_key, vrt_ql256_uri, vrt_ql512_uri)
                if key is not None
            ),
            attempt_scope=str(generation_uuid),
            job_id=job_id,
            task="regenerate_vrt",
        ):
            return

        # 10. Write immutable generation objects. The catalog pointer switches
        # only after phase 2 checks the job lease and current_generation_id
        # together, so a stale worker can never overwrite the live generation.
        # The rewrite runs after metadata extraction and quicklook generation
        # (see the module docstring).
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

        # Registered before the put: a cancelled put can have completed, and
        # CancelledError skips every statement below it.
        written_storage_keys.append(next_vrt_physical_key)
        with open(vrt_path, "rb") as fobj:
            await storage.put(next_vrt_physical_key, fobj)

        if ql256 is not None:
            written_storage_keys.append(next_ql256_physical_key)
            await storage.put(next_ql256_physical_key, io.BytesIO(ql256))
        if ql512 is not None:
            written_storage_keys.append(next_ql512_physical_key)
            await storage.put(next_ql512_physical_key, io.BytesIO(ql512))

        # Recorded with the publish, so its follow-ups delete them once it
        # shows, whether or not this task can tell it landed.
        superseded_keys = [
            key
            for key in _prior_generation_keys_to_reap(
                vrt_key=vrt_storage_key,
                quicklook_256_key=vrt_ql256_uri,
                quicklook_512_key=vrt_ql512_uri,
                replace_quicklook_256=ql256 is not None,
                replace_quicklook_512=ql512 is not None,
            )
            if resolve_storage_key(key, tenant_id=_ctv.get())
            not in written_storage_keys
        ]

        # Phase 2: update RasterAsset metadata, mark the job complete, update
        # the dataset footprint.
        #
        # `status == "running"` joins the attempt fence. The
        # `current_generation_id` check refuses a newer generation's publish,
        # but not a job the stale sweep already failed with no newer
        # generation yet (that sweep never touches the pointer); without it a
        # paused worker could switch the live pointer after the sweep declared
        # it dead. The objects written above are reaped by
        # `sweep_stale_vrt_assets` either way. Job row first, then asset: the
        # order every worker phase, `cancel_job` and the dataset delete hold.
        async with async_session() as session:
            await note_publishing_xid(session)
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
                vrt_asset.set_crs(meta)
                vrt_asset.epsg = meta.get("epsg")
                vrt_asset.band_count = meta.get("band_count")
                vrt_asset.dtype = meta.get("dtype")
                # Recomputed, so adding or removing a source that changes the
                # band/dtype profile flips it.
                vrt_asset.is_dem = meta.get("is_dem_candidate", False)
                vrt_asset.nodata = str(nodata_val) if nodata_val is not None else None
                vrt_asset.res_x = meta.get("res_x")
                vrt_asset.res_y = meta.get("res_y")
                vrt_asset.width = meta.get("width")
                vrt_asset.height = meta.get("height")
                vrt_asset.compression = meta.get("compression")

                # 12. Status transitions
                vrt_asset.status = "ready"
                # The snapshot instant, not now() (see snapshot_member_sources).
                vrt_asset.last_regenerated_at = snapshot_at
                # From the ordered_assets the build used, in the publish
                # transaction, so the stored set and VRT describe each other.
                vrt_asset.built_from = built_from_map(ordered_assets)
                vrt_asset.current_generation_id = None
                if vrt_asset_snapshot is not None:
                    vrt_asset_snapshot.status = vrt_asset.status
                    vrt_asset_snapshot.last_regenerated_at = (
                        vrt_asset.last_regenerated_at
                    )
                    vrt_asset_snapshot.current_generation_id = None

                # 12a. The staged member set lands in the transaction that
                # publishes the artifact built from it, never at request time,
                # so vrt_source_links can't describe a composition the served
                # bytes lack. It is the list phase 1 built from, not a re-read
                # of the generation row.
                if staged_source_ids is not None:
                    await apply_staged_source_links(session, vrt_id, staged_source_ids)

                # 12b. Update generation record
                generation.status = "completed"
                generation.completed_at = datetime.now(timezone.utc)
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
                    # The writes below dirty both rows. The asset SELECT above
                    # took the datasets row through its join; catalog.records
                    # is not in that query, so this is a real wait.
                    from app.platform.catalog_locks import (
                        CatalogLockConflict,
                        lock_catalog_rows,
                    )

                    # Read before the wait: the rollback inside a failed
                    # acquisition expires every loaded instance.
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
                    # The budget ends with the wait it was sized for. The
                    # UPDATEs below sit outside lock_catalog_rows, so an expiry
                    # there would raise a bare DBAPIError.
                    await session.execute(
                        text("SELECT set_config('lock_timeout', :value, true)"),
                        {"value": pre_wait_lock_timeout},
                    )
                    await require_submitter_can_write(
                        session,
                        vrt_dataset,
                        job,
                        capability=(job.user_metadata or {}).get(
                            ADMITTED_CAPABILITY_METADATA_KEY
                        ),
                    )
                    # The generation's completion instant, in the swap's
                    # transaction, so source_freshness reads a live signal for
                    # a VRT (which has no origin). The same instant as
                    # generation.completed_at, so the two records agree.
                    vrt_dataset.last_refreshed_at = generation.completed_at
                    # In the pointer swap's transaction, as at every swap
                    # door: otherwise pre-swap tiles stay valid in every
                    # version-keyed cache (the nginx tile cache via the URL
                    # `v=`, the per-process raster meta cache) until their
                    # TTLs, and a regeneration that changes band shape renders
                    # wrong until then.
                    vrt_dataset.bump_tile_cache_version()
                    if meta.get("bbox_wkt"):
                        vrt_dataset.record.spatial_extent = func.ST_GeomFromText(
                            meta["bbox_wkt"], 4326
                        )

                # Download/STAC references follow the new generation keys in
                # the same transaction.
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
                await ledger.complete(
                    session,
                    job_uuid,
                    attempt_uuid,
                    values={
                        "dataset_id": vrt_id,
                        "user_metadata": owed_followups(
                            attempt_uuid,
                            "regenerate_vrt",
                            superseded_keys=superseded_keys,
                        ),
                    },
                )
                xid = publishing_xid(session)
                try:
                    await session.commit()
                except BaseException as exc:
                    observation = await observe_publish_commit(
                        job_uuid,
                        attempt_uuid,
                        xid=xid,
                        error=exc,
                        job_id=job_id,
                        task="regenerate_vrt",
                    )
                    if observation is PublishObservation.NOT_LANDED:
                        raise
                    # Stand down rather than re-raise: the generation swap is
                    # durable, so the failure handler would describe a job that
                    # succeeded, and the generation row it stamps `failed` is
                    # not fenced the way the job and asset writes are.
                    publish_committed = True
                    absorb_cancellation(exc)
                    # With the outcome unknown, the sweep runs the follow-ups
                    # once the commit shows.
                    if observation is PublishObservation.LANDED:
                        await run_publish_followups(job_uuid)
                    return
                publish_committed = True

                # 15. The follow-ups purge the catalog cache and refresh the
                # embedding, so the sweep runs them too when the task can't.
                await run_publish_followups(job_uuid)

            except Exception:  # broad: re-raised below; rollback first so the
                # outer handler can write a clean failure record via a fresh session.
                await session.rollback()
                raise

    except Exception as exc:  # broad: VRT regeneration includes GDAL subprocesses and rasterio — any step can fail
        if publish_committed:
            # The follow-ups failed after a durable publish. The generation
            # write below is unfenced and would stamp a `completed` generation
            # `failed`, which `get_vrt_status` reads as no completed generation.
            structlog.get_logger().warning(
                "vrt_post_publish_followup_failed",
                job_id=job_id,
                task="regenerate_vrt",
                exc_info=True,
            )
            return
        # A refused submitter is an outcome, recorded as a replacement's is.
        refused = isinstance(exc, WriteAccessRevoked)
        if refused:
            structlog.get_logger().warning(
                "vrt_publish_write_access_revoked", job_id=job_id
            )
        else:
            structlog.get_logger().exception(
                "Ingest task failed",
                job_id=job_id,
                task="regenerate_vrt",
            )
        # The asset settles first and alone. `sweep_stale_vrt_assets` fences its
        # asset UPDATE on the generations it just failed, so an asset still
        # pointing at a terminal one is a state it can never reach.
        asset_settled = await _settle_failed_vrt_asset(
            vrt_id, generation_uuid, job_id=job_id
        )
        # The job and generation rows follow in one transaction. Losing both to
        # a contended job row is recoverable: the sweep fails a generation whose
        # heartbeat went stale, and the stale-job sweep settles the job.
        try:
            async with async_session() as err_session:
                # The publish wait gives up on a held catalog row, so the job
                # row may be contended too. Both writes below share the budget.
                await arm_job_error_write_budget(err_session)
                await ledger.fail(err_session, job_uuid, attempt_uuid, reason=exc)
                # Only once the asset is off this generation: a terminal
                # generation under an asset still pointing at it is the state
                # `sweep_stale_vrt_assets` fences itself out of.
                if generation_uuid is not None and asset_settled:
                    gen_result = await err_session.execute(
                        select(VrtGeneration).where(VrtGeneration.id == generation_uuid)
                    )
                    gen = gen_result.scalar_one_or_none()
                    # Fenced here too, so no path into this handler can relabel
                    # a generation whose artifact is published.
                    if gen and gen.status != "completed":
                        gen.status = "failed"
                        gen.completed_at = datetime.now(timezone.utc)
                        if gen.started_at:
                            gen.duration_seconds = (
                                gen.completed_at - gen.started_at
                            ).total_seconds()
                        gen.error_message = redact_failure_reason(exc)

                await err_session.commit()
        except DBAPIError as write_failure:
            # Swallowed so the `raise` below re-raises the build failure, not a
            # lock timeout.
            log_job_error_write_failure(
                write_failure, job_id=job_id, task="regenerate_vrt"
            )
        if not refused:
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


# A second registered name for the same regeneration, used only by staged
# mutations (add/remove source), for rolling upgrades: a worker that doesn't
# know `staged_source_ids` would rebuild from the live links and mark the
# generation complete, losing an accepted add/remove. A kwarg can't fence
# that worker off (its signature ends in `**kwargs`), but the task name can:
# it raises TaskNotFound and fails the job. The task never ran, so
# vrt_source_links is untouched, the generation stays 'pending' and the asset
# 'regenerating' until `sweep_stale_vrt_assets` restores 'ready'; the caller
# re-issues the mutation once the roll finishes. Plain regeneration changes
# no membership, so it keeps the original name.
@task_app.task(queue="raster", retry=0)
async def regenerate_vrt_staged(**kwargs) -> None:
    """Regenerate a VRT whose generation carries a staged member set.

    The same work as ``regenerate_vrt``: one implementation, two registered
    names, and the staged set is read from the generation row on either path.
    The name gates which workers may run it, nothing else.
    ``regenerate_vrt.func`` is the ``tenant_task``-wrapped body, so the tenant
    kwarg is popped and bound exactly once, here at the forward.
    """
    await regenerate_vrt.func(**kwargs)
