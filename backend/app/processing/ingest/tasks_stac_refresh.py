"""Procrastinate task: re-resolve a moved STAC item and its asset.

feat(#1266) / ADR-002 Amendment A10, Decision 5a. A STAC dataset holds no
bytes of its own — ``storage_backend='remote'``, the COG stays in the
publisher's bucket, and Titiler reads it at tile time — so the entire dataset
is a pointer at somebody else's object. Publishers move those objects:
buckets migrate, scenes are re-tiled, collections are restructured. The item
goes on existing at a new address and GeoLens goes on pointing at the old
one.

#1222 shipped the observer for that (404/410 on the stored pointer ->
``missing``) and deliberately stopped there: a probe reports and never
rewrites. This task is the actor. It re-reads the item document, and if the
asset it publishes has moved, moves the dataset's pointer with it.

**What it is not.** No fetch of the data, no staging table, no swap: the
asset is remote before and remote after, and only the pointer changes. What
makes it a worker task rather than a request is what makes the registered-
PostGIS refresh one — the admission gate, the run ledger and the history a
user reads are the shared machinery (handoff invariant 11), and that
machinery is dispatch-then-finalize.

**Where the network lives.** Nowhere in this file. Every outbound byte goes
through ``catalog/sources/stac_resolve.py``, reached across ``ProcessingPort``
— which keeps Rule 2's safe client, the #1222 health classifier and the
storable-href gate in the one place that already owns them, and leaves this
module as what it should be: a transaction, a guard, and a ledger entry.

**Invariant 10 on every failure path.** Nothing here writes
``last_refreshed_at``, ``origin_ref``, ``origin_uri`` or the asset row except
the success block, so a refresh that could not resolve leaves the dataset
pointing exactly where it pointed before — last-known-good, which for a
dataset that is nothing but a pointer is the whole of its data.
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

# ADR-002's stored source_health values, mirrored the way
# ``tasks_postgis_refresh`` mirrors them: processing/ may not import
# app.modules.catalog (test_no_processing_imports_catalog), so the words are
# retyped rather than imported, and ``test_stac_refresh_1266`` asserts them
# against the probe's own vocabulary so a divergence fails a test instead of
# persisting a value the API cannot describe.
_MISSING = "missing"
# The two `missing` details this strategy can receive, mirrored for the same
# reason the health words are: they select which diagnosis the run reports,
# and reporting the wrong one sends the reader to fix the wrong thing.
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
# fix(#1266 review round 13): says what is established on every path that
# reaches it, and no more. This verdict is reached both from a search that
# answered and did not have the item and from a catalog that offered no way
# to look, so it may not claim a search result it might not have.
_WITHDRAWN_MESSAGE = (
    "The STAC item this dataset was imported from is no longer at the "
    "address its catalog published, and GeoLens could not locate it "
    "anywhere else in its collection. The dataset keeps pointing at the "
    "asset it always did; re-import it from a live item to move it."
)
# fix(#1266 review round 17): a DIFFERENT missing. The item is still on the
# catalog and still resolves; what is gone is the asset this dataset was
# bound to. Telling that reader the item disappeared and to re-import from a
# live one is both a wrong diagnosis and advice that will not help, since the
# item they would re-import from is the one they already have.
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
        # fix(#1266 review round 3): whether an outbound attempt actually
        # reached the publisher, carried separately from the verdict because
        # they are separate facts. A 5xx or a 401 establishes NOTHING about
        # where the asset is (health stays None) while still being a contact
        # that `last_checked_at` is defined to date. Defaults to False so a
        # failure raised before any request — a binding with no item href —
        # cannot date a contact that never happened.
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

    Raises when there is no ``item_href``. The item document is the only
    thing that can answer where an asset moved TO: the asset href answers a
    different question, and a 200 on it says nothing about the item. So a
    dataset without one — imported before #1222 taught search to capture the
    ``rel=self`` link, or from a catalog that publishes none — has nothing to
    re-resolve against, and the door refuses it with ``origin_unavailable``
    before a job is ever created. This is the worker's own copy of that
    refusal, because the binding is re-read here and could have changed.
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
    is therefore the only one that writes health: the item answered 404/410
    and the re-search did not produce it anywhere else. Everything else was
    inconclusive — a timeout, a 5xx, a 401/403, a body that is not a STAC
    item — and passes ``health=None``, which leaves whatever the last
    conclusive observation wrote exactly where it was. Reporting a live
    dataset as missing because one request timed out is worse than reporting
    nothing.
    """
    if resolution.health == _MISSING:
        # Two things are missing-shaped and they are not the same thing to
        # the person reading the history: the ITEM is gone from the catalog
        # (`item_withdrawn`), or the item is fine and the ASSET is gone from
        # it (`not_found`). The detail already carries which, so the message
        # follows it rather than assuming the first.
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

    Through ``set_dataset_origin``, which is the only door into
    ``origin_ref`` and applies the per-kind key allowlist — so a resolution
    that somehow carried an extra field raises here rather than widening what
    a STAC binding can hold (ADR-002 invariant 4).

    ``collection_id`` is the stored value, or — for a binding that never had
    one, which ``StacImportItem`` permits — the one the resolution verified
    the answer against, read out of the stored item URL. It is never taken
    from the re-fetched item: an item that reports a different collection has
    not moved, it has been re-published as something else, and following that
    would be a rebinding rather than a re-resolution. Learning the value the
    URL already stated is a different act, and it is what lets the NEXT
    refresh check against a stored collection rather than re-deriving one.

    ``origin_uri`` moves with the asset href because they are one value: the
    STAC import sets the pointer to the asset href, and the duplicate-source
    guard keys on it. ``source_url`` is deliberately left alone — it is in
    the metadata PATCH's field map, so it belongs to the owner, and a refresh
    overwriting an edited provenance URL would be this door reaching outside
    the system-managed columns it is allowed to write.
    """
    set_dataset_origin(
        dataset,
        "stac",
        uri=resolution.asset_href,
        asset_href=resolution.asset_href,
        item_href=resolution.item_href,
        # fix(#1266 review round 9): written back on every rebind, so a
        # dataset imported before the id was recorded gains one the first
        # time it refreshes and is checked against it thereafter.
        item_id=resolution.item_id,
        collection_id=collection_id,
        asset_key=resolution.asset_key,
    )


def _pixel_geometry(described: dict) -> dict:
    """The affine-derived columns, written only when the affine was READ.

    fix(#1375 review): these three are one fact, so they move together or not
    at all. ``fetch_cog_info``'s transform probe is optional — ``/cog/info``
    can answer while ``/cog/stac`` fails — and an earlier version of this
    turned that partial result into ``is_rotated=False``, which is not a
    missing value but a WRONG measurement: the column is NOT NULL and cannot
    say "unknown", so writing it from a probe that measured nothing asserts
    axis-alignment on an object nothing looked at. ``_check_rotation``
    (VAL-07) rejects a VRT source only when the flag is true, so that
    fabricated ``False`` would have let a rotated replacement through a gate
    built to stop it — and a remote asset IS an eligible VRT source
    (``router_vrt.py`` handles ``storage_backend='remote'`` members).

    Same argument as ``crs_wkt``/``epsg`` in ``sources/cog_info.py``, which
    come off one parsed CRS object for the same reason: half a fact, written
    from a source that produced none of it, leaves a row that is neither the
    old truth nor the new one.

    Absent keys leave the previous values in place. That is stale for a moved
    object, and it is the lesser wrong: a scene previously measured as
    rotated stays flagged rotated, which is the conservative direction for
    every consumer of these columns.
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

    fix(#1266 review round 5): the structural columns move WITH the URI, in
    the same statement. A moved asset is not the same object — a re-tiled
    scene can change its band count, dtype, nodata and the statistics every
    rescale is computed from — and ``raster_tile_proxy`` builds ``bidx``,
    rescale and nodata parameters out of exactly these fields. Updating the
    address alone would serve the new raster through the old one's
    description, which for a single-band COG requested as RGB is not a
    cosmetic error. The resolver reads them off the new object before
    anything is adopted, so a row can never carry one object's URI beside
    another's shape.

    Scoped to ``storage_backend='remote'`` rows: a raster whose bytes GeoLens
    now owns (a #1290 replace writes a managed key and flips the backend to
    ``local``) is not addressed by the publisher's item at all, and pointing
    it at an external href would tell every consumer to treat a managed key
    as a URL.
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
            # fix(#1266 review round 6): the DEM flag is derived from the same
            # two fields, by the same rule every other raster path uses, and
            # it has to move with them: `raster_tile_proxy` branches on this
            # BEFORE it looks at band metadata, so an RGB replacement left
            # flagged as elevation is requested with algorithm=terrainrgb and
            # a new elevation raster is rendered as ordinary imagery.
            #
            # It re-derives over an owner's PATCH of the flag, deliberately
            # and with precedent: `_write_swapped_fields` does the same on a
            # raster replace, because the classification describes the object
            # and the object is what just changed. An annotation made about
            # bytes that are gone is not a setting worth preserving.
            is_dem=is_dem_candidate(
                described.get("band_count"), described.get("dtype")
            ),
            # fix(#1266 review round 6): a moved member has to make the VRTs
            # built on it look stale, and for one class of parent this stamp
            # is the only signal that can. A VRT with `built_from` recorded is
            # judged by state — what the member IS against what the published
            # mosaic was built FROM — and the URI change above is enough. A
            # VRT built before that column existed falls back to comparing
            # this timestamp against its own build time, so leaving it alone
            # would let the member probe healthy while the published VRT still
            # embeds the old, possibly dead URL. The raster replace path
            # restamps it when it swaps a pointer for the same reason; this
            # swaps a pointer too.
            ingested_at=datetime.now(timezone.utc),
            # fix(#1266 review round 7): the georeferencing moves too. This
            # field is emitted as STAC `proj:code` and read by the VRT
            # compatibility checks, so a reprojected replacement described by
            # the previous object's EPSG is a wrong answer served to both.
            # The caller's `epsg` is already reconciled with the probe's own
            # CRS (fix #1334 review, in `stac_resolve.py` — the one place
            # both facts are in hand, and the reason `processing/` never has
            # to import anything from `catalog/` to get this preference).
            epsg=epsg,
            # fix(#1334): `crs_wkt` joins the fields above for the same
            # reason band_count/dtype/nodata do — the moved object is not the
            # same object, and `fetch_cog_info` already reads it off. The
            # STAC import path now writes it too, so leaving it stale here
            # would let a refreshed dataset disagree with what a fresh
            # import of the same asset would record.
            crs_wkt=described.get("crs_wkt"),
            # fix(#1375): the resolution pair and the rotation flag join the
            # fields above for that same reason, and they are the ones a
            # move is MOST likely to change — a re-tiled or reprojected
            # replacement is exactly where the old pixel size stops
            # describing the new object.
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

    feat(#1692). The STAC import persists the origin item's primary data
    asset as a ``dataset_assets`` row keyed ``data``, which is what puts a
    readable COG href on the STAC items GeoLens serves (the ``raster_tiles``
    template renders only in GeoLens's own frontend). This is the refresh's
    half of that contract, and it runs on EVERY successful resolution, moved
    or not — an upsert against an unchanged answer is a no-op, and against a
    dataset imported before the row existed it IS the backfill: one refresh
    and the dataset serves the asset every generic client needs.

    ON CONFLICT against ``uq_dataset_assets_key``, the same statement shape
    the raster-replace tail uses (``_upsert_stac_and_distribution_rows``) —
    and that tail is also why this write is safe against a replaced dataset:
    a #1290 replace flips ``source_format`` off ``stac``, so the binding
    guard in phase 3 discards this task's answer before it could overwrite
    the replacement's managed row.

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
        # ----------------------------------------------------------------- #
        # Phase 1: claim the attempt and the run, and read the binding.
        # ----------------------------------------------------------------- #
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

        # ----------------------------------------------------------------- #
        # Phase 2: ASK THE PUBLISHER, holding no database session.
        #
        # Three requests at worst — the item, a re-search when it 404s, and a
        # probe of whatever asset href comes back — against a host that owes
        # GeoLens nothing in the way of latency. A pooled connection held
        # across that would pin a slot for the duration, which is the same
        # reason the #1222 endpoint releases its session before probing.
        # ----------------------------------------------------------------- #
        resolution = await port.resolve_stac_binding(
            item_href=item_href,
            item_id=item_id,
            collection_id=collection_id,
            asset_href=asset_href,
            asset_key=asset_key,
        )
        if not resolution.resolved:
            raise _failure_for(resolution)

        # ----------------------------------------------------------------- #
        # Phase 3: WRITE what phase 2 resolved.
        # ----------------------------------------------------------------- #
        async with async_session() as session:
            # Lock the row, THEN compare the binding — the same order, and
            # for the same reason, as the registered-table strategy's content
            # token. The binding IS this task's subject, so the guard is an
            # equality check on it rather than on a version counter: a
            # re-upload or a raster replace that commits while the publisher
            # is being asked has already written where this dataset points,
            # and applying an answer about the OLD origin over the top would
            # undo a rebind that had already succeeded. `FOR UPDATE` makes
            # the compare and the write one indivisible step; a single-column
            # select keeps the statement off any joined relationship, which
            # PostgreSQL will not lock through an outer join.
            # fix(#1847): the raster child before the datasets row, the order
            # the is_dem PATCH and the raster replace hold; the moved-asset
            # write below touches that row after this guard.
            from app.processing.raster.models import RasterAsset

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
                    # The publisher WAS reached, so this is a contact — but
                    # one made against a binding the dataset no longer has.
                    # No special case is needed for that: both stamps below
                    # are guarded on the binding this attempt read, and the
                    # guard is what declines the write.
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
                # The dataset-level mirror of the same fact. `resolution.epsg`
                # is already reconciled with the probe's own CRS when one ran
                # (fix #1334 review, in `stac_resolve.py`), so this and the
                # raster row `_repoint_remote_asset` just wrote agree by
                # construction — one value, two writes, same as the STAC
                # import path.
                dataset.srid = resolution.epsg
                # fix(#1266 review round 25): and the footprint, from the same
                # document. A re-tiled or cropped scene comes with a new bbox,
                # and a dataset still advertising the old one lies to every
                # spatial search and every map-bounds read — the registered-
                # table strategy corrects exactly this staleness when it
                # rewrites an extent. Written only when the item states a
                # bbox: an item that states none has not said the footprint
                # changed, and clearing it would remove the dataset from
                # spatial search on no evidence at all.
                if resolution.bbox is not None:
                    west, south, east, north = resolution.bbox
                    dataset.record.spatial_extent = func.ST_GeomFromText(
                        bbox_to_extent_wkt(west, south, east, north), 4326
                    )
                # The other half of the tile story, and the half a server-side
                # purge cannot do: the `_v=` parameter in the tile URL is what
                # busts browser and CDN caches. In the write transaction,
                # beside the content change it describes, which is the
                # contract on the method.
                #
                # It reaches `tiles.router._raster_meta_cache` too, which it
                # once did not (#1266 review, when that per-process LRU was
                # keyed on tenant and dataset alone and kept the pre-refresh
                # href for a TTL even for requests carrying the new version).
                # fix(#1329) keyed it on the request's `v` as well, so this
                # bump is itself the invalidation: the first request carrying
                # the new value misses in every API process and re-reads the
                # href. `reupload_raster` and `regenerate_vrt` bump the same
                # counter in their own write transactions and get the same
                # effect (see the note in
                # tasks_raster_swap._run_post_swap_followups) — the fix that
                # belonged to the tile router, once, for all three. A request
                # still carrying the OLD version keeps the pre-refresh href
                # until that entry expires (60s), bounded and self-healing.
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
            # probe state on every write, because a binding write is the
            # moment a stored verdict stops describing anything real. What
            # goes back is not a second classifier's opinion — it is the
            # #1222 probe's own verdict on the asset href this run resolved,
            # taken moments ago by the resolver. `last_checked_at` is stamped
            # by the run finalizer below, from contacted_origin.
            #
            # So a run can succeed while the dataset reports `missing`, and
            # that pair is coherent rather than contradictory: the run answers
            # "did the refresh re-resolve the binding", the column answers "is
            # the origin serving what the binding names". A publisher whose
            # item points at an href that 404s has told GeoLens both things at
            # once, and flattening them would lose whichever one was recorded
            # second.
            dataset.source_health = resolution.health
            dataset.source_health_detail = resolution.detail
            # Decision 5a's refresh is this operation for a STAC origin —
            # there is no other — so this operation is what dates it, whether
            # or not the answer moved anything. "We asked the publisher and
            # this is current" is exactly the fact the column carries.
            now = datetime.now(timezone.utc)
            dataset.last_refreshed_at = now

            await require_ingest_job_update(
                session,
                job_uuid,
                attempt_uuid,
                values={"status": "complete", "completed_at": now},
            )
            # The run's terminal status commits with the job's and with the
            # rebind, which is what makes "job complete, run still running"
            # unreachable for the stale-run sweep. dataset_version_id is None
            # and feature_count_after too: no data moved and a raster has no
            # rows to count. schema_diff is None for the same reason — there
            # is no attribute schema to drift. contacted_origin=True: this run
            # reached the publisher and got an answer, which is precisely what
            # last_checked_at records.
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
            # fix(#1266 review round 3): exactly one writer dates the contact,
            # and which one depends on whether there was a verdict to write.
            #
            # The stamp above dates it whenever it writes a verdict, so the
            # run finalizer must not repeat that a second, weaker way. But
            # when the attempt established nothing about the origin and still
            # REACHED it — a 5xx, a 401/403, a body that is not a STAC item —
            # the stamp declines to write at all, and the contact would go
            # unrecorded even though `last_checked_at` is defined as the last
            # time GeoLens contacted the origin at all. That is the case the
            # finalizer takes, under the identical binding guard.
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
