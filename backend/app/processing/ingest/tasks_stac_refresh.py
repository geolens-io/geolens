"""Procrastinate task: re-resolve a moved STAC item and its asset.

feat(#1266), ADR-002 Amendment A10 Decision 5a. A STAC dataset holds no
bytes of its own (``storage_backend='remote'``) — it is a pointer at a
publisher's bucket object, and publishers move those objects. #1222 observes
this (404/410 on the stored pointer -> ``missing``) but never rewrites; this
task is the actor. It re-reads the item document and, if the asset moved,
moves the dataset's pointer with it.

Not a fetch, a staging table, or a swap — the asset is remote before and
after, only the pointer changes. The admission gate, run ledger and history
are the same shared machinery the registered-PostGIS refresh uses (handoff
invariant 11): dispatch-then-finalize. All network I/O goes through
``catalog/sources/stac_resolve.py`` via ``ProcessingPort``, which owns Rule
2's safe client, the #1222 health classifier, and the storable-href gate —
leaving this module a transaction, a guard, and a ledger entry.

Invariant 10: nothing here writes ``last_refreshed_at``, ``origin_ref``,
``origin_uri`` or the asset row except the success block, so a refresh that
can't resolve leaves the dataset pointing exactly where it pointed before.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select, update

from app.core.geo import bbox_to_extent_wkt

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
from app.platform.refresh.service import (
    claim_run_for_job,
    record_refresh_failure,
    record_refresh_success,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    cleanup_step,
    stamp_failed_origin_health,
    task_app,
)

logger = structlog.get_logger(__name__)

# ADR-002's stored source_health values, retyped rather than imported —
# processing/ may not import app.modules.catalog
# (test_no_processing_imports_catalog) — and asserted against the probe's
# own vocabulary by test_stac_refresh_1266 so a divergence fails a test.
_MISSING = "missing"
# The two `missing` details this strategy can receive, mirrored for the same
# reason: they select which diagnosis the run reports.
_ITEM_WITHDRAWN = "item_withdrawn"
_NOT_FOUND = "not_found"

_ERROR_CODE_MISSING = "source_missing"
_ERROR_CODE_INACCESSIBLE = "source_inaccessible"
_ERROR_CODE_GENERIC = "stac_refresh_failed"
_ERROR_CODE_SUPERSEDED = "superseded"

# Written for the person reading the refresh history, and composed here
# rather than from anything the origin sent: ADR-002 Decision 3 forbids a
# provider's error text, a response body or a URL in a stored reason string,
# and an origin URI may legitimately carry a signed query.
# fix(#1266): says what is established on every path that reaches it, no
# more — reached both from a search that answered without the item and from
# a catalog offering no way to look, so it may not claim a search result.
_WITHDRAWN_MESSAGE = (
    "The STAC item this dataset was imported from is no longer at the "
    "address its catalog published, and GeoLens could not locate it "
    "anywhere else in its collection. The dataset keeps pointing at the "
    "asset it always did; re-import it from a live item to move it."
)
# fix(#1266): a DIFFERENT missing — the item still resolves, but the asset
# it was bound to is gone. Saying the item disappeared would misdiagnose it
# and send the reader to re-import from the item they already have.
_ASSET_REMOVED_MESSAGE = (
    "The STAC item this dataset was imported from no longer publishes the "
    "asset it was bound to. The item itself is still on the catalog, and the "
    "dataset keeps pointing at the asset it always did; re-import it from "
    "that item to bind to one of the assets it publishes now."
)
_UNREACHABLE_MESSAGE = (
    "GeoLens could not read the STAC item this dataset was imported from, "
    "and the catalog's answer did not establish whether the item is still "
    "published. Nothing was changed. Try again."
)


class StacRefreshError(Exception):
    """A refresh failure that already knows what it means.

    Carries the run's ``error_code`` and, when the failure described the
    ORIGIN rather than the attempt, the source-health verdict to persist. The
    failure handler reads both off the exception instead of re-classifying,
    so the classification happens once, at the point that has the evidence.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        health: str | None = None,
        detail: str | None = None,
        contacted: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.health = health
        self.detail = detail
        # fix(#1266): whether an outbound attempt reached the publisher,
        # separate from the verdict — a 5xx/401 establishes nothing about
        # where the asset is (health stays None) but is still a contact
        # `last_checked_at` should date. Defaults False so a failure raised
        # before any request cannot date a contact that never happened.
        self.contacted = contacted


def _binding(dataset: Any) -> tuple:
    """The ``(origin_uri, origin_ref, source_format)`` triple, as read.

    One spelling of the triple, used for three things that must agree: the
    guard the write transaction checks before it changes anything, the guard
    the failed-health stamp writes under, and the value the two are compared
    as. Composing it at each site is how they drift.
    """
    return (dataset.origin_uri, dataset.origin_ref, dataset.source_format)


def _stac_pointers(
    origin_ref: dict | None,
) -> tuple[str, str | None, str | None, str | None, str | None]:
    """``(item_href, item_id, collection_id, asset_href, asset_key)``.

    Raises when there is no ``item_href``: only the item document can answer
    where an asset moved TO (the asset href answers a different question). A
    dataset without one has nothing to re-resolve against — the door already
    refuses this with ``origin_unavailable`` before a job is created; this is
    the worker's own copy of that refusal, since the binding could have
    changed since.
    """
    ref = origin_ref or {}
    item_href = ref.get("item_href")
    if not item_href:
        raise StacRefreshError(
            "This dataset's source binding does not record the STAC item its "
            "asset was published in, so there is nothing to re-resolve "
            "against. Re-import it from the catalog to record one.",
            error_code=_ERROR_CODE_GENERIC,
        )
    return (
        item_href,
        ref.get("item_id"),
        ref.get("collection_id"),
        ref.get("asset_href"),
        ref.get("asset_key"),
    )


def _failure_for(resolution: Any) -> StacRefreshError:
    """The refusal a resolution that found nothing turns into.

    ``missing`` is the only verdict that says something about the ORIGIN and
    so the only one that writes health: the item answered 404/410 and the
    re-search didn't produce it elsewhere. Everything else — timeout, 5xx,
    401/403, a non-STAC body — is inconclusive and passes ``health=None``,
    leaving the last conclusive observation as-is. Reporting a live dataset
    as missing on one timeout is worse than reporting nothing.
    """
    if resolution.health == _MISSING:
        # Missing-shaped but not the same thing: the ITEM is gone from the
        # catalog (`item_withdrawn`), or the item is fine and the ASSET is
        # gone from it (`not_found`). `detail` carries which.
        return StacRefreshError(
            _ASSET_REMOVED_MESSAGE
            if resolution.detail == _NOT_FOUND
            else _WITHDRAWN_MESSAGE,
            error_code=_ERROR_CODE_MISSING,
            health=resolution.health,
            detail=resolution.detail,
            contacted=resolution.contacted,
        )
    return StacRefreshError(
        _UNREACHABLE_MESSAGE,
        error_code=_ERROR_CODE_INACCESSIBLE,
        health=None,
        detail=None,
        contacted=resolution.contacted,
    )


def _rebind(dataset: Any, resolution: Any, *, collection_id: str | None) -> None:
    """Point the dataset at where the publisher now says its asset is.

    Through ``set_dataset_origin``, the only door into ``origin_ref``, which
    applies the per-kind key allowlist — a resolution carrying an extra
    field raises here rather than widening a STAC binding (ADR-002
    invariant 4).

    ``collection_id`` is the stored value, or — for a binding that never had
    one — the value the resolution verified against, read from the stored
    item URL, never from the re-fetched item: an item reporting a different
    collection has been re-published as something else, not moved, and
    following that would be a rebinding, not a re-resolution.

    ``origin_uri`` moves with the asset href (one value — the STAC import
    sets the pointer to the asset href, and the duplicate-source guard keys
    on it). ``source_url`` is deliberately left alone: it's in the metadata
    PATCH's field map and belongs to the owner, not this door.
    """
    set_dataset_origin(
        dataset,
        "stac",
        uri=resolution.asset_href,
        asset_href=resolution.asset_href,
        item_href=resolution.item_href,
        # fix(#1266): written back on every rebind, so a dataset imported
        # before the id was recorded gains one on its first refresh.
        item_id=resolution.item_id,
        collection_id=collection_id,
        asset_key=resolution.asset_key,
    )


def _pixel_geometry(described: dict) -> dict:
    """The affine-derived columns, written only when the affine was READ.

    fix(#1375): these three move together or not at all. ``fetch_cog_info``'s
    transform probe is optional (``/cog/info`` can answer while
    ``/cog/stac`` fails); writing a fabricated ``is_rotated=False`` from a
    probe that measured nothing would assert axis-alignment on an object
    nothing looked at, and since ``_check_rotation`` (VAL-07) rejects a VRT
    source only when the flag is true, that lets a rotated replacement
    through a gate built to stop it. Same argument as ``crs_wkt``/``epsg``
    in ``sources/cog_info.py``.

    Absent keys leave the previous values in place — stale for a moved
    object, but the conservative direction (a scene previously measured
    rotated stays flagged rotated).
    """
    if "res_x" not in described:
        return {}
    return {
        "res_x": described["res_x"],
        "res_y": described["res_y"],
        "is_rotated": described["is_rotated"],
    }


async def _repoint_remote_asset(
    session: Any,
    dataset_uuid: uuid.UUID,
    href: str,
    metadata: dict[str, Any] | None,
    epsg: int | None,
) -> None:
    """Move the raster row the tiler actually reads, and re-describe it.

    ``origin_ref`` is provenance; THIS is what serves. The tile router
    resolves an open path from ``RasterAsset.asset_uri``, so a refresh that
    updated only the binding would report a moved asset and go on serving
    tiles from the dead href.

    fix(#1266): structural columns move WITH the URI, in the same statement.
    A moved asset is not the same object — a re-tiled scene can change band
    count, dtype, nodata and the statistics rescale is computed from — and
    ``raster_tile_proxy`` builds ``bidx``/rescale/nodata from exactly these
    fields. Updating the address alone would serve the new raster through
    the old one's description (not cosmetic for a single-band COG requested
    as RGB).

    Scoped to ``storage_backend='remote'`` rows: a raster whose bytes
    GeoLens now owns (a #1290 replace flips the backend to ``local``) isn't
    addressed by the publisher's item, and pointing it at an external href
    would make consumers treat a managed key as a URL.
    """
    from app.processing.raster.cog import is_dem_candidate
    from app.processing.raster.models import RasterAsset

    described = metadata or {}
    nodata = described.get("nodata")
    await session.execute(
        update(RasterAsset)
        .where(
            RasterAsset.dataset_id == dataset_uuid,
            RasterAsset.storage_backend == "remote",
        )
        .values(
            asset_uri=href,
            band_count=described.get("band_count"),
            dtype=described.get("dtype"),
            width=described.get("width"),
            height=described.get("height"),
            nodata=str(nodata) if nodata is not None else None,
            band_info=described.get("band_info"),
            # fix(#1266): DEM flag moves with band_count/dtype — the tile
            # proxy branches on this BEFORE band metadata, so a stale flag
            # would render a new elevation raster as ordinary imagery (or
            # vice versa). Re-derives over an owner's PATCH deliberately,
            # with precedent from `_write_swapped_fields` on raster replace:
            # the classification describes the object, and the object just
            # changed.
            is_dem=is_dem_candidate(
                described.get("band_count"), described.get("dtype")
            ),
            # fix(#1266): restamped so VRTs built before `built_from` existed
            # (judged by comparing this timestamp to their own build time)
            # don't probe healthy while still embedding the old, possibly
            # dead URL. The raster replace path restamps for the same reason.
            ingested_at=datetime.now(timezone.utc),
            # fix(#1266): georeferencing moves too — emitted as STAC
            # `proj:code` and read by VRT compatibility checks, so a
            # reprojected replacement described by the old EPSG is wrong for
            # both. Already reconciled with the probe's own CRS in
            # `stac_resolve.py` (fix(#1334)).
            epsg=epsg,
            # fix(#1334): `crs_wkt` moves for the same reason — `fetch_cog_
            # info` already reads it off the moved object, and the STAC
            # import path writes it too, so leaving it stale here would
            # disagree with a fresh import of the same asset.
            crs_wkt=described.get("crs_wkt"),
            # fix(#1375): resolution pair and rotation flag move for the
            # same reason — a re-tiled or reprojected replacement is exactly
            # where the old pixel size stops describing the new object.
            **_pixel_geometry(described),
        )
    )


async def _upsert_origin_data_asset(
    session: Any,
    dataset_uuid: uuid.UUID,
    *,
    href: str,
    media_type: str | None,
) -> None:
    """Make the served ``dataset_assets`` row describe the resolved asset.

    feat(#1692): the STAC import persists the origin item's primary data
    asset as a ``dataset_assets`` row keyed ``data``, the readable COG href
    on STAC items GeoLens serves. This is the refresh's half of that
    contract, run on EVERY successful resolution, moved or not — a no-op
    against an unchanged answer, and the backfill for a dataset imported
    before the row existed.

    ON CONFLICT against ``uq_dataset_assets_key``, same shape as the
    raster-replace tail's ``_upsert_stac_and_distribution_rows`` — which is
    also why this is safe against a replaced dataset: a #1290 replace flips
    ``source_format`` off ``stac``, so the phase-3 binding guard discards
    this task's answer before it could overwrite the replacement's row.

    Lives inside the success block on purpose (invariant 10): a refresh that
    resolved nothing repairs nothing.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.processing.raster.models import DatasetAsset

    stmt = pg_insert(DatasetAsset).values(
        dataset_id=dataset_uuid,
        key="data",
        href=href,
        media_type=media_type,
        roles=["data"],
    )
    await session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_dataset_assets_key",
            # href, media_type and roles describe the resolved asset and move
            # with it; size_bytes is deliberately absent — this task measures
            # nothing, and listing it would overwrite a stored value with
            # NULL.
            set_={
                "href": stmt.excluded.href,
                "media_type": stmt.excluded.media_type,
                "roles": stmt.excluded.roles,
            },
        )
    )


@task_app.task(queue="ingest", retry=0)
@tenant_task
async def refresh_stac(
    job_id: str,
    dataset_id: str,
    attempt_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Background task: re-resolve this dataset's STAC item and asset pointer.

    No ``user_id`` argument, for the same reason the registered-table refresh
    takes none: this creates no ``DatasetVersion`` and stamps no uploader,
    because no data moved. The actor is already on the run row as
    ``triggered_by``, which is where this operation's audit trail lives.
    """
    _bind_task_log_context(
        task_name="refresh_stac", job_id=job_id, dataset_id=dataset_id
    )
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from sqlalchemy.orm import joinedload

    port = get_processing_port()
    Dataset = port.get_dataset_orm_class()

    resolved_attempt = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="refresh"
    )
    if resolved_attempt is None:
        return
    job_uuid, attempt_uuid = resolved_attempt
    dataset_uuid = uuid.UUID(dataset_id)
    heartbeat_task: asyncio.Task[None] | None = None
    # The binding this attempt resolved against, for the failure handler's
    # guarded write and the write transaction's own guard. Left None until
    # phase 1 has read it — a failure before that established nothing about
    # any origin and must not write a verdict.
    bound: tuple | None = None

    try:
        # Phase 1: claim the attempt and the run, and read the binding.
        async with async_session() as session:
            job = (
                await session.execute(
                    select(IngestJob).where(
                        IngestJob.id == job_uuid,
                        IngestJob.attempt_id == attempt_uuid,
                    )
                )
            ).scalar_one_or_none()
            if job is None:
                logger.warning("Ingest job not found, skipping", job_id=job_id)
                return

            dataset = (
                await session.execute(select(Dataset).where(Dataset.id == dataset_uuid))
            ).scalar_one_or_none()
            if dataset is None:
                logger.warning("Dataset not found, skipping", dataset_id=dataset_id)
                return

            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid
            )
            if heartbeat_task is None:
                return

            bound = _binding(dataset)
            (
                item_href,
                item_id,
                collection_id,
                asset_href,
                asset_key,
            ) = _stac_pointers(dataset.origin_ref)
            await claim_run_for_job(session, job_uuid)
            await session.commit()

        # Phase 2: ASK THE PUBLISHER, holding no database session. Three
        # requests at worst (item, a re-search on 404, a probe of the asset
        # href) against a host that owes GeoLens no latency guarantee — a
        # pooled connection held across that would pin a slot, same reason
        # the #1222 endpoint releases its session before probing.
        resolution = await port.resolve_stac_binding(
            item_href=item_href,
            item_id=item_id,
            collection_id=collection_id,
            asset_href=asset_href,
            asset_key=asset_key,
        )
        if not resolution.resolved:
            raise _failure_for(resolution)

        # Phase 3: WRITE what phase 2 resolved.
        async with async_session() as session:
            # Lock the row, THEN compare the binding — same order as the
            # registered-table strategy's content token. The binding is
            # this task's subject, so the guard is an equality check on it,
            # not a version counter: a re-upload or raster replace that
            # committed while the publisher was being asked has already
            # written where this dataset points, and applying an answer
            # about the OLD origin would undo that. `FOR UPDATE` makes
            # compare-and-write one indivisible step; a single-column select
            # keeps the statement off any joined relationship (PostgreSQL
            # won't lock through an outer join).
            # fix(#1847): job row, then raster child, then datasets row —
            # the order the replace worker and dataset delete hold.
            from app.processing.raster.models import RasterAsset

            await session.execute(
                select(IngestJob.id)
                .where(IngestJob.id == job_uuid)
                .with_for_update(key_share=True)
            )
            await session.execute(
                select(RasterAsset.dataset_id)
                .where(RasterAsset.dataset_id == dataset_uuid)
                .with_for_update()
            )
            locked = (
                await session.execute(
                    select(
                        Dataset.origin_uri,
                        Dataset.origin_ref,
                        Dataset.source_format,
                    )
                    .where(Dataset.id == dataset_uuid)
                    .with_for_update()
                )
            ).one_or_none()
            if locked is None:
                logger.warning("Dataset not found, skipping", dataset_id=dataset_id)
                return
            if tuple(locked) != bound:
                raise StacRefreshError(
                    "This dataset's source changed while its STAC item was "
                    "being re-resolved, so the older answer was discarded "
                    "rather than written over the newer binding. Refresh "
                    "again.",
                    error_code=_ERROR_CODE_SUPERSEDED,
                    # The publisher WAS reached, against a binding the
                    # dataset no longer has — both stamps below are guarded
                    # on the binding this attempt read, and that guard is
                    # what declines the write.
                    contacted=True,
                )

            dataset = (
                await session.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == dataset_uuid)
                )
            ).scalar_one_or_none()
            if dataset is None:
                logger.warning("Dataset not found, skipping", dataset_id=dataset_id)
                return

            moved = resolution.asset_href != asset_href
            # A binding with no collection of its own learns the one the
            # resolution checked it against; one that has a collection keeps
            # it, because only the stored value may name what this dataset is.
            learned_collection = collection_id or resolution.collection_id
            rebound = (
                moved
                or resolution.item_href != item_href
                or resolution.item_id != item_id
                or resolution.asset_key != asset_key
                or learned_collection != collection_id
            )
            if rebound:
                _rebind(dataset, resolution, collection_id=learned_collection)
            if moved:
                await _repoint_remote_asset(
                    session,
                    dataset_uuid,
                    resolution.asset_href,
                    resolution.asset_metadata,
                    resolution.epsg,
                )
                # Dataset-level mirror of the same fact. `resolution.epsg` is
                # already reconciled with the probe's own CRS (fix(#1334)), so
                # this and the raster row `_repoint_remote_asset` just wrote
                # agree by construction.
                dataset.srid = resolution.epsg
                # fix(#1266): and the footprint, from the same document — a
                # re-tiled or cropped scene has a new bbox, and a stale one
                # lies to spatial search and map-bounds reads. Written only
                # when the item states a bbox; a silent item hasn't said the
                # footprint changed.
                if resolution.bbox is not None:
                    west, south, east, north = resolution.bbox
                    dataset.record.spatial_extent = func.ST_GeomFromText(
                        bbox_to_extent_wkt(west, south, east, north), 4326
                    )
                # The `_v=` tile-URL parameter busts browser/CDN caches, and
                # also reaches `tiles.router._raster_meta_cache` — fix(#1329)
                # keyed that per-process LRU on the request's `v`, so this
                # bump is itself the invalidation. `reupload_raster` and
                # `regenerate_vrt` bump the same counter for the same effect.
                # A request still on the OLD version keeps the pre-refresh
                # href until that cache entry expires (60s).
                dataset.bump_tile_cache_version()

            # feat(#1692): unconditional on purpose — not gated on `moved` or
            # `rebound`. For an unchanged answer it rewrites the row with the
            # values it already has; for a dataset imported before the row
            # existed it is the backfill. See _upsert_origin_data_asset.
            await _upsert_origin_data_asset(
                session,
                dataset_uuid,
                href=resolution.asset_href,
                media_type=resolution.asset_media_type,
            )

            # AFTER the rebind, never before: `set_dataset_origin` clears the
            # probe state on every write, since a binding write is the
            # moment a stored verdict stops describing anything real. What
            # goes back is the #1222 probe's own verdict on the asset href
            # this run just resolved, not a second opinion. `last_checked_at`
            # is stamped by the run finalizer below, from contacted_origin.
            #
            # So a run can succeed while the dataset reports `missing` —
            # coherent, not contradictory: the run answers "did the refresh
            # re-resolve the binding", the column answers "is the origin
            # serving what the binding names".
            dataset.source_health = resolution.health
            dataset.source_health_detail = resolution.detail
            # Decision 5a: this is the only refresh operation for a STAC
            # origin, so it dates the column regardless of whether the
            # answer moved anything.
            now = datetime.now(timezone.utc)
            dataset.last_refreshed_at = now

            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={"status": "complete", "completed_at": now},
            )
            # Run's terminal status commits with the job's and the rebind,
            # making "job complete, run still running" unreachable for the
            # stale-run sweep. dataset_version_id/feature_count_after are
            # None: no data moved, a raster has no rows to count. schema_diff
            # is None: no attribute schema to drift. contacted_origin=True:
            # this run reached the publisher and got an answer.
            await record_refresh_success(
                session,
                ingest_job_id=job_uuid,
                dataset=dataset,
                dataset_version_id=None,
                feature_count_after=None,
                schema_diff=None,
                contacted_origin=True,
            )
            await session.commit()

        # GET /datasets/ serves the origin pointer and the health columns from
        # a 60-second cache, so without this the list keeps describing the old
        # href after the refresh reported the new one.
        await invalidate_catalog_cache()

    except Exception as exc:  # broad: any step here is a network or database read
        logger.exception("STAC refresh failed", job_id=job_id, task="refresh_stac")
        error_code = getattr(exc, "error_code", _ERROR_CODE_GENERIC)
        async with async_session() as err_session:
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
            await err_session.commit()
            health = getattr(exc, "health", None)
            await stamp_failed_origin_health(
                err_session,
                Dataset,
                dataset_uuid,
                health=health,
                detail=getattr(exc, "detail", None),
                bound=bound,
            )
            # fix(#1266): exactly one writer dates the contact. The stamp
            # above dates it whenever it writes a verdict; when the attempt
            # reached the origin but established nothing (5xx, 401/403, a
            # non-STAC body), the stamp declines to write at all, and the
            # finalizer below dates it instead, under the identical binding
            # guard — otherwise the contact goes unrecorded even though
            # `last_checked_at` is defined as the last time GeoLens
            # contacted the origin at all.
            dates_contact = (
                getattr(exc, "contacted", False)
                and health is None
                and bound is not None
            )
            await record_refresh_failure(
                err_session,
                ingest_job_id=job_uuid,
                error_code=error_code,
                error_message=str(exc),
                contacted_origin=dates_contact,
                origin_binding=bound if dates_contact else None,
            )
            await err_session.commit()
        raise
    finally:
        async with cleanup_step("refresh_stac heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
