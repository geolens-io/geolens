"""Procrastinate task definitions for VRT creation and regeneration.

Storage portability (STOR-03/04, Phase 1210):
  VRTs are stored with provider-agnostic SourceFilename nodes (logical keys +
  relativeToVRT="1"). The rewrite pass (rewrite_vrt_sources) runs AFTER metadata
  extraction and quicklook generation at each store site — the in-flight tmp .vrt
  used by read_vrt_metadata / render_vrt_quicklook must hold concrete,
  resolvable paths; only the stored copy is normalised to logical keys.

  At open-time, resolve_open_path (app.platform.storage.titiler_url) reconstructs
  the concrete VSI path from the logical key + current STORAGE_PROVIDER config, so
  a provider swap (s3 -> azure -> local) requires no changes to stored VRT XML.
"""

import uuid
from datetime import datetime, timezone

import structlog

from sqlalchemy import select

from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.heartbeat import (
    claim_job_attempt_and_start_heartbeat,
    maintain_vrt_generation_heartbeat,
    require_ingest_job_update,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.core.db import tenant_task
from app.processing.embeddings.helpers import defer_embedding
from app.processing.raster.cog import sha256_file
from app.processing.raster.vrt import (
    build_vrt,
    read_vrt_metadata,
    render_vrt_quicklook,
    resolve_vrt_source_path,
)
from app.processing.raster.vrt_rewrite import rewrite_vrt_sources
from app.platform.storage import get_storage

from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _cleanup_staging_on_failure,
    task_app,
)
from app.processing.ingest.tasks_raster_common import (
    absorb_cancellation,
    publish_commit_landed,
)


async def _reap_superseded_generation_objects(
    *,
    prior_storage_keys: list[str],
    written_storage_keys: list[str],
    job_id: str,
) -> None:
    """Delete the objects the published generation superseded.

    fix(#1778 codex r2): named and shared because ``regenerate_vrt`` reaches
    it from two places now, the ordinary success path and the stand-down a
    lost commit acknowledgement takes. It is the ONLY deletion of the previous
    generation's artifact, and the committed asset already names the new one,
    so a path that skips it strands bytes no row references and no quota
    counts.

    The ``not in written`` filter is what makes a regeneration that produced
    byte-identical output a no-op rather than a self-inflicted delete.
    """
    from app.processing.ingest.tasks_raster import _cleanup_orphaned_storage_keys

    await _cleanup_orphaned_storage_keys(
        [key for key in prior_storage_keys if key not in written_storage_keys],
        job_id=job_id,
    )


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

    fix(#1290 review). ``last_regenerated_at`` names the state a VRT was built
    FROM, and that only works if the instant predates the read it describes.
    Both VRT tails need that ordering and neither could be trusted to keep it:
    the creation tail had no snapshot at all, and the regenerate tail captured
    one AFTER its member query. So the ordering lives here, inside the only
    function that does the read, where writing it the wrong way round is not
    possible rather than merely discouraged. Third instance of the two-tails
    class on this PR — after reserve-before-upsert and the COG policy — and the
    durable fix each time was one authority both tails must cross.

    The direction of the remaining error is the point. Stamping BEFORE the read
    means a replacement landing in the (tiny) stamp→read window is already
    visible to the read, so the build uses the NEW URI while ``ingested_at``
    postdates the stamp: the parent reports ``stale`` when it is in fact fine,
    and an operator regenerates once for nothing. Stamping after the read
    inverts that into a parent whose stored VRT references a reaped COG being
    reported ``healthy``. A needless regenerate is cheap and self-correcting; a
    masked broken mosaic is neither.
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

    fix(#1290 review). This is what makes staleness a STATE question. The
    health endpoint compares each member's current committed ``asset_uri``
    against the entry recorded here, so "the stored VRT references a superseded
    COG" is answered by comparing what-is to what-was-built-from rather than by
    racing two clocks. Derived from the same ``ordered_assets`` the build reads,
    so the recorded set is by construction the set that was used.
    """
    return {str(a.dataset_id): a.asset_uri for a in ordered_assets}


def staged_source_ids_or_none(generation) -> list[uuid.UUID] | None:
    """The generation's staged member set as UUIDs, or None when it stages none.

    fix(#1327). NULL means "this generation changes no membership" — a plain
    regenerate, or any generation queued before ``staged_source_ids`` existed.
    Both build from the live link rows and apply nothing, so the caller gets one
    fallback with two producers rather than a version check.

    A JSONB column also reads back Python ``None`` when it holds the JSON scalar
    ``null`` (SQLAlchemy's plain JSONB serializes an assigned ``None`` that way
    rather than as SQL NULL — the same trap #1322 hit in SQL), and a non-list
    value cannot be a member set either. Both fall to the same None answer as a
    genuinely absent one.

    Everything else about the value is checked HERE, at claim time, before a
    single byte is built: an empty set, an unparseable id or a repeated id is a
    staged intent that cannot be published, and failing on it now costs a job
    instead of a GDAL build plus an obscure ON CONFLICT error at apply time.
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

    fix(#1327). Called only from the publish transaction — the same one that
    swaps ``asset_uri`` and writes ``built_from`` — so the catalog's declared
    composition becomes visible at the instant the artifact built from it does,
    and never before.

    A replace, not a diff: an upsert over the whole staged set followed by a
    delete of everything else for this VRT. Re-running it is a no-op, which is
    what makes a retry safe, and it needs no knowledge of what the links held
    when the set was staged. The upsert (rather than delete-then-insert)
    preserves ``created_at`` on rows that survive the change, so a member's
    "linked since" is not reset by an unrelated add or remove.

    The empty guard is a precondition, not a second validation: the caller
    already refuses an empty staged set at claim time. Here it stops an empty
    list from compiling into ``NOT IN ()`` and deleting every link a VRT has.
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
        # Mirror the vector ingest path (datasets/service.py
        # `create_dataset_record`) and the raster ingest helper above, which
        # commit directly to `published`.
        # Without this a public VRT stayed in `draft`, and the anonymous
        # raster tile-access check at tiles/router.py `_resolve_raster_access`
        # returned 404 for every public VRT tile request.
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
        # fix(#1218 review): stamped like every other creation path. A VRT has
        # no origin (it is composed from other datasets), but assembling it IS
        # a successful materialization, and migration 0036 backfills a
        # timestamp onto pre-existing VRTs the same way. Python value, not
        # func.now(): a SQL expression leaves the attribute expired and the
        # next read lazy-loads.
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
        # fix(#1290 review): the instant the members were READ, so a
        # never-regenerated parent does not fall back to a publish-time
        # `ingested_at` in the staleness comparison. Optional only because the
        # manifest-VRT caller has no snapshot of its own; the build path always
        # supplies it.
        last_regenerated_at=snapshot_at,
        # fix(#1290 review): the authoritative staleness input. The timestamp
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

    Session lifecycle (gh #100): the AsyncSession is split into two short-lived
    blocks so it is NOT held open across the long-running CPU work in steps 5-8
    (gdalbuildvrt subprocess, rasterio metadata extraction, sha256, quicklook
    generation — each runs via ``asyncio.to_thread``). See
    ``.planning/debug/worker-missing-greenlet-100.md`` for the full diagnosis.
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
    # fix(#430 BA-30): track storage puts so a failure after put (terminal commit /
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
            # fix(#1290 review): the creation tail had NO snapshot instant, so
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

        # 8. Generate quicklooks (non-fatal)
        ql256: bytes | None = None
        ql512: bytes | None = None
        try:
            ql256 = await asyncio.to_thread(render_vrt_quicklook, vrt_path, 256)
            ql512 = await asyncio.to_thread(render_vrt_quicklook, vrt_path, 512)
        except Exception:  # broad: quicklook generation is non-fatal; rasterio rendering can fail for any reason
            logger_vrt.warning(
                "Quicklook generation failed for VRT %s", job_id, exc_info=True
            )

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): create DB records, store assets,
        # commit job.
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
                )

                # 10. Store VRT and quicklooks to managed storage
                from pathlib import Path as _Path

                from app.platform.storage import get_storage

                storage = get_storage()
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
                    # fix(#1778 codex r1): stand down rather than re-raise, the
                    # same decision `regenerate_vrt` makes below. The dataset
                    # and its VRT object are durable, so the failure handler
                    # would be writing about a job that succeeded.
                    #
                    # fix(#1778 codex r2): and unlike `regenerate_vrt` there is
                    # nothing to reap on the way out. A first build supersedes
                    # no generation, so the followups this skips are the cache
                    # purge and the embedding defer: both recoverable, neither
                    # holding bytes that no row references.
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
            # fix(#1778 codex r1): the second way this handler is reached with
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
            err_job = (
                await err_session.execute(
                    select(IngestJob).where(
                        IngestJob.id == job_uuid,
                        IngestJob.attempt_id == attempt_uuid,
                    )
                )
            ).scalar_one_or_none()
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
        await stop_ingest_job_heartbeat(heartbeat_task)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        # fix(#430 BA-30): reap storage bytes written before a terminal commit
        # that never became durable (mirrors ingest_raster's GAP-017 guard).
        if not publish_committed and written_storage_keys:
            from app.processing.ingest.tasks_raster import (
                _cleanup_orphaned_storage_keys,
            )

            await _cleanup_orphaned_storage_keys(written_storage_keys, job_id=job_id)


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

    Atomic publish: the rebuilt VRT is written to generation-specific immutable
    keys. The RasterAsset pointer changes only in the same transaction that verifies
    the job attempt and generation ownership, then prior objects are reaped.

    Composition source (fix(#1327)): the generation's ``staged_source_ids``
    when it carries one — ``add_vrt_source``/``remove_vrt_source`` record the
    intended post-mutation member set there instead of writing it into
    ``vrt_source_links`` up front — otherwise the live link rows. The staged set
    is applied to ``vrt_source_links`` in step 12, inside the publish
    transaction, so the catalog's declared composition and the artifact built
    from it become visible in the same commit.

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
            # generation carries one. add_vrt_source / remove_vrt_source no
            # longer touch vrt_source_links — they record the FULL intended
            # post-mutation set here — so the live link rows read above still
            # describe the VRT currently being served, not the one this attempt
            # is being asked to publish. Building from the links would rebuild
            # the existing composition and then apply a set the artifact does
            # not contain, which is the exact drift this pattern removes.
            # A generation that stages nothing (plain regenerate, or one queued
            # before the column existed) keeps the live links.
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
        except Exception:  # broad: quicklook generation is non-fatal; rasterio rendering can fail for any reason
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

        # 10. Write immutable generation objects. The catalog pointer is switched
        # only after the job lease and current_generation_id are checked together
        # in phase 2, so a stale worker can never overwrite the live generation.
        #
        # ORDERING: rewrite_vrt_sources runs AFTER metadata extraction (step 6/7)
        # and quicklook generation (step 9) — the in-flight tmp .vrt must hold
        # concrete resolvable paths for GDAL to open. Only the STORED copy is
        # rewritten to logical relativeToVRT="1" keys (STOR-03).
        # CR-01: supply vrt_storage_key so the rewrite computes paths relative
        # to the VRT's own directory (not the full logical key).
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

        # ----------------------------------------------------------------- #
        # Phase 2 (short-lived session): update RasterAsset metadata, mark
        # job complete, update dataset footprint.
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
                # fix(#1290 review): the snapshot instant, NOT now(). See the
                # capture site in phase 1 for why the field names the state the
                # artifact was built from.
                vrt_asset.last_regenerated_at = snapshot_at
                # fix(#1290 review): recorded from the SAME ordered_assets the
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
                # writes built_from — never at request time. That is the whole
                # invariant: vrt_source_links can never describe a composition
                # the served bytes do not have, because both become visible in
                # one commit. Death anywhere upstream leaves the links alone.
                #
                # Applies the SAME list phase 1 built from, not a re-read of
                # the generation row — the link set and the artifact then
                # cannot disagree even in principle, exactly as built_from is
                # derived from the ordered_assets the build used. Fenced by the
                # current_generation_id check above: a zombie worker whose
                # attempt the sweep already reconciled cannot reach this line.
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
                    # feat(#1267) / ADR-002 Decision 5a: project the
                    # generation's completion instant into last_refreshed_at,
                    # in the SAME transaction as the generation swap, so
                    # source_freshness (#1224) reads a live signal for a NULL
                    # origin (VRT) instead of the creation-time floor forever.
                    # Same instant as generation.completed_at, not a fresh
                    # now() — one swap, one timestamp, no clock skew between
                    # the two records of it.
                    vrt_dataset.last_refreshed_at = generation.completed_at
                    # fix(#1329 follow-up): the VRT swap is the third
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
                    # fix(#1778 codex r1): stand down rather than re-raise. The
                    # generation swap is durable, so every write the failure
                    # handler would make is a statement about a job that
                    # succeeded, and the generation row it stamps `failed` is
                    # not fenced the way the job and asset writes are.
                    publish_committed = True
                    absorb_cancellation(exc)
                    # fix(#1778 codex r2): standing down from the FAILURE
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
            # fix(#1778 codex r1): the second way this handler is reached with
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
        # Failure handler runs via a fresh session: mark vrt asset failed,
        # mark generation failed, mark job failed.
        async with async_session() as err_session:
            from sqlalchemy import update as sa_update

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
            # Mark only the asset that still points at this exact generation.
            # If a newer retry owns the pointer, leave its status untouched.
            await err_session.execute(
                sa_update(RasterAsset)
                .where(
                    RasterAsset.dataset_id == vrt_id,
                    RasterAsset.current_generation_id == generation_uuid,
                )
                .values(status="failed", current_generation_id=None)
            )

            # Update generation record on failure.
            if generation_uuid is not None:
                gen_result = await err_session.execute(
                    select(VrtGeneration).where(VrtGeneration.id == generation_uuid)
                )
                gen = gen_result.scalar_one_or_none()
                # fix(#1778 codex r1): and the same rule stated at the write
                # rather than only at the caller. The two guards above are
                # local flags; this one is a property of the statement, so a
                # future path into this handler cannot relabel a generation
                # whose artifact is published, whatever it believes about the
                # commit. It is the peer of the `current_generation_id` fence
                # on the asset update and the `running` fence on the job.
                if gen and gen.status != "completed":
                    gen.status = "failed"
                    gen.completed_at = datetime.now(timezone.utc)
                    if gen.started_at:
                        gen.duration_seconds = (
                            gen.completed_at - gen.started_at
                        ).total_seconds()
                    gen.error_message = str(exc)

            await err_session.commit()
        raise
    finally:
        await stop_ingest_job_heartbeat(generation_heartbeat_task)
        await stop_ingest_job_heartbeat(heartbeat_task)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if not publish_committed and written_storage_keys:
            from app.processing.ingest.tasks_raster import (
                _cleanup_orphaned_storage_keys,
            )

            await _cleanup_orphaned_storage_keys(written_storage_keys, job_id=job_id)


# fix(#1327 codex P1): a SECOND registered name for the SAME regeneration, used
# only by the staged mutations (add source / remove source).
#
# The skew it closes: during a rolling upgrade the API can be new while a worker
# is still pre-#1327. The new API records the membership change only in
# `staged_source_ids`; a pre-#1327 worker does not know that column, rebuilds
# from the live links, and marks the generation COMPLETE. An accepted add or
# remove is silently lost, with every state machine reporting success.
#
# Why the name and not a marker kwarg. The pre-#1327 task signature ends in
# `**kwargs`, and so does `tenant_task`'s wrapper, so an unknown keyword is
# swallowed rather than raising TypeError: a kwarg cannot fence a consumer that
# accepts anything. The task NAME can. Procrastinate resolves the name against
# the worker's own registry, and a worker without it raises TaskNotFound, which
# fails the job. Measured against the pinned procrastinate in
# tests/test_vrt_staged_task_skew.py: status 'failed', attempts 1, no retry
# scheduled (TaskNotFound never consults a retry strategy, because there is no
# task object to ask one for).
#
# What that failure leaves behind is deliberately a state the existing
# machinery already handles rather than a new one: the task never ran, so
# vrt_source_links is untouched, the generation stays 'pending' with a NULL
# heartbeat, and the asset stays 'regenerating' until `sweep_stale_vrt_assets`
# reconciles it. Composition is preserved, which is the whole point of staging,
# so the sweep restores 'ready' and the VRT keeps serving what it was serving.
# The mutation is refused rather than half-applied, and the caller re-issues it
# once the roll finishes.
#
# Plain regeneration deliberately keeps the legacy name: it changes no
# membership, so a pre-#1327 worker executes it correctly and those deliveries
# keep flowing during the roll.
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
