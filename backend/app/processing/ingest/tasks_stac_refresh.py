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

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select, update

from app.core.geo import bbox_to_extent_wkt, crs_columns
from app.core.service_tokens import (
    STAC_SERVICE_FORMAT,
    ServiceCredential,
    credential_from_header_line,
)

from app.core.db.tenant_session import tenant_task
from app.platform.dataset_origin import set_dataset_origin
from app.platform.refresh.credentials import (
    CredentialExpiredError,
    CredentialStoreUnavailable,
    resolve_worker_credential,
)
from app.processing.ingest.publication import (
    PUBLISH,
    Failure,
    PublicationCommit,
    Published,
    Verdict,
    settle_replacement,
)
from app.processing.ingest.tasks_common import _bind_task_log_context, task_app

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
# An `inaccessible` detail, mirrored for the same reason as the two above: it
# selects the refusal diagnosis instead of the generic unreachable one.
_BLOCKED_BY_POLICY = "blocked_by_policy"
# The resolver's refusal of an asset whose CRS it can't identify, mirrored
# for the same reason: it selects its own message.
_CRS_UNIDENTIFIED = "crs_unidentified"

_ERROR_CODE_MISSING = "source_missing"
_ERROR_CODE_INACCESSIBLE = "source_inaccessible"
_ERROR_CODE_BLOCKED_BY_POLICY = "source_blocked_by_policy"
_ERROR_CODE_GENERIC = "stac_refresh_failed"
_ERROR_CODE_SUPERSEDED = "superseded"

# fix(#1764): the credential message a caller sees, composed here so it never
# carries the store's own error text, which can echo the key it was asked for.
_CREDENTIAL_UNUSABLE_MESSAGE = (
    "The credential for this refresh could not be read, so the catalog was "
    "not contacted and nothing was changed. Start the refresh again with a "
    "fresh credential."
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


def _refresh_error_code(exc: BaseException) -> str:
    """Map a STAC refresh failure onto its run ``error_code``.

    fix(#1764): three codes send the reader to three places — a fresh
    credential, an operator for an unreachable store, or the origin. Mirrors
    ``tasks_reupload._service_refresh_error_code``; ``error_code`` is a
    closed vocabulary the history UI reads, so the mapping lives in one
    function per strategy.
    """
    if isinstance(exc, CredentialExpiredError):
        return "credential_expired"
    if isinstance(exc, CredentialStoreUnavailable):
        return "credential_store_unavailable"
    return getattr(exc, "error_code", _ERROR_CODE_GENERIC)


def _claimed_credential(credential_line: str | None) -> ServiceCredential | None:
    """The credential a claimed wire line describes.

    fix(#1764): a non-empty line that yields nothing raises rather than
    degrading to an anonymous fetch, which would reach a protected catalog,
    collect a 401, and report a live dataset as inaccessible.
    """
    if not credential_line:
        return None
    credential = credential_from_header_line(
        credential_line, service_format=STAC_SERVICE_FORMAT
    )
    if credential is None:
        raise StacRefreshError(
            _CREDENTIAL_UNUSABLE_MESSAGE, error_code="credential_expired"
        )
    return credential


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
_BLOCKED_BY_POLICY_MESSAGE = (
    "GeoLens will not fetch the address this dataset's catalog gave for its "
    "STAC item or its asset, because this instance's outbound-address "
    "policy refuses it. Nothing was changed."
)
_CRS_UNIDENTIFIED_MESSAGE = (
    "The STAC item now names an asset whose CRS has no EPSG code and isn't "
    "OGC CRS84, which GeoLens doesn't support for remote COGs. The dataset "
    "keeps its previous asset until the source is reprojected to an EPSG CRS "
    "(gdalwarp's -t_srs option does this) and refreshed again."
)


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
) -> tuple[str, str | None, str | None, str | None, str | None, str | None]:
    """``(item_href, item_id, collection_id, asset_href, asset_key, url)``.

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
        ref.get("url"),
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
    if resolution.detail == _BLOCKED_BY_POLICY:
        # The policy refuses the same address every time, so retrying can't help.
        return StacRefreshError(
            _BLOCKED_BY_POLICY_MESSAGE,
            error_code=_ERROR_CODE_BLOCKED_BY_POLICY,
            health=None,
            detail=resolution.detail,
            contacted=resolution.contacted,
        )
    if getattr(resolution, "refusal", None) == _CRS_UNIDENTIFIED:
        # A fact about this asset, not the origin, so no health is written.
        return StacRefreshError(
            _CRS_UNIDENTIFIED_MESSAGE,
            error_code=_ERROR_CODE_GENERIC,
            health=None,
            detail=None,
            contacted=resolution.contacted,
        )
    return StacRefreshError(
        _UNREACHABLE_MESSAGE,
        error_code=_ERROR_CODE_INACCESSIBLE,
        health=None,
        detail=None,
        contacted=resolution.contacted,
    )


def _rebind(
    dataset: Any,
    resolution: Any,
    *,
    collection_id: str | None,
    auth_required: bool | None,
    catalog_url: str | None,
) -> None:
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

    feat(#1764): ``auth_required`` is True when THIS attempt used a
    credential and None when it did not, so a token-less success clears the
    marker the same way the service path's does. Never the credential.
    """
    set_dataset_origin(
        dataset,
        "stac",
        uri=resolution.asset_href,
        # Carried forward unchanged: a refresh re-resolves a binding, it does
        # not re-point it at a catalog the caller never submitted.
        url=catalog_url,
        asset_href=resolution.asset_href,
        item_href=resolution.item_href,
        # fix(#1266): written back on every rebind, so a dataset imported
        # before the id was recorded gains one on its first refresh.
        item_id=resolution.item_id,
        collection_id=collection_id,
        asset_key=resolution.asset_key,
        auth_required=auth_required,
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
            **crs_columns(described),
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

    The STAC import persists the item's primary data asset as a
    ``dataset_assets`` row keyed ``data``. This is the refresh's half of that
    contract, run on every successful resolution, moved or not: a no-op for
    an unchanged answer, and the backfill for a dataset imported before the
    row existed.

    ON CONFLICT against ``uq_dataset_assets_key``, the shape the raster
    replace uses. That is also why it is safe against a replaced dataset: a
    replace flips ``source_format`` off ``stac``, so the write step's binding
    fence discards this answer before it could overwrite the replacement's row.

    Runs only in the write step (invariant 10): a refresh that resolved
    nothing repairs nothing.
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


class _StacRefresh:
    """A STAC dataset's item re-read from its catalog, and its pointer moved with the asset."""

    task = "refresh_stac"
    staging = False
    raster_row = True
    catalog_event = "stac_refresh_catalog"

    def __init__(self, *, credential_ref: str | None):
        self.credential_ref = credential_ref
        self.credential: ServiceCredential | None = None
        # The binding this attempt resolves against, for the write's fence and
        # the failure's stamp. None until the claim reads it.
        self.bound: tuple | None = None

    def prepare(self, job, dataset, staging_table: str) -> None:
        self.bound = _binding(dataset)
        self.origin_ref = dataset.origin_ref

    async def fetch(self) -> None:
        from app.platform.extensions import get_processing_port

        (
            self.item_href,
            self.item_id,
            self.collection_id,
            self.asset_href,
            self.asset_key,
            self.catalog_url,
        ) = _stac_pointers(self.origin_ref)
        # Redeemed after the claim, so a delivery that loses it spends nothing.
        self.credential = _claimed_credential(
            await resolve_worker_credential(None, self.credential_ref)
        )
        self.resolution = await get_processing_port().resolve_stac_binding(
            item_href=self.item_href,
            item_id=self.item_id,
            collection_id=self.collection_id,
            asset_href=self.asset_href,
            asset_key=self.asset_key,
            credential=self.credential,
            # The address the caller submitted at import, the one value the
            # catalog never chose: the credential is only sent under it.
            catalog_origin=self.catalog_url,
        )
        if not self.resolution.resolved:
            raise _failure_for(self.resolution)

    async def stage(self, session, job, dataset) -> Verdict:
        return PUBLISH

    async def install(self, session, dataset) -> None:
        return None

    async def write(self, session, dataset) -> Published:
        from sqlalchemy.orm import joinedload

        from app.platform.extensions import get_processing_port

        Dataset = get_processing_port().get_dataset_orm_class()
        # The binding is this task's subject, so a re-upload or replace that
        # committed while the catalog was asked has already moved it, and an
        # answer about the old origin must not undo that.
        dataset = (
            await session.execute(
                select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if _binding(dataset) != self.bound:
            raise StacRefreshError(
                "This dataset's source changed while its STAC item was "
                "being re-resolved, so the older answer was discarded "
                "rather than written over the newer binding. Refresh "
                "again.",
                error_code=_ERROR_CODE_SUPERSEDED,
                # The publisher was reached, against a binding the dataset no
                # longer has; the failure's stamp is guarded on it and declines.
                contacted=True,
            )

        resolution = self.resolution
        moved = resolution.asset_href != self.asset_href
        # A binding with no collection learns the one the resolution checked
        # it against; one with a collection keeps it.
        learned_collection = self.collection_id or resolution.collection_id
        # True or None, never False: the origin_ref allowlist drops a None
        # key, which is how "no credential was used" is spelled.
        auth_required = True if self.credential is not None else None
        marked_before = (dataset.origin_ref or {}).get("auth_required") is True
        if (
            moved
            or resolution.item_href != self.item_href
            or resolution.item_id != self.item_id
            or resolution.asset_key != self.asset_key
            or learned_collection != self.collection_id
            or marked_before != (auth_required is True)
        ):
            _rebind(
                dataset,
                resolution,
                collection_id=learned_collection,
                auth_required=auth_required,
                catalog_url=self.catalog_url,
            )
        if moved:
            await _repoint_remote_asset(
                session,
                dataset.id,
                resolution.asset_href,
                resolution.asset_metadata,
                resolution.epsg,
            )
            # Reconciled with the probe's CRS already, so it agrees with the
            # raster row just written.
            dataset.srid = resolution.epsg
            # Written only when the item states a bbox; a silent item has not
            # said the footprint changed.
            if resolution.bbox is not None:
                west, south, east, north = resolution.bbox
                dataset.record.spatial_extent = func.ST_GeomFromText(
                    bbox_to_extent_wkt(west, south, east, north), 4326
                )
        # Unconditional: an unchanged answer rewrites the same values, and a
        # dataset imported before the row existed gets it.
        await _upsert_origin_data_asset(
            session,
            dataset.id,
            href=resolution.asset_href,
            media_type=resolution.asset_media_type,
        )
        # After the rebind, which clears the probe state: this is the probe's
        # own verdict on the href just resolved. The run may succeed while
        # the dataset reports `missing`; the two answer different questions.
        dataset.source_health = resolution.health
        dataset.source_health_detail = resolution.detail
        # The only refresh for a STAC origin, so it dates the column whether
        # or not anything moved.
        dataset.last_refreshed_at = datetime.now(timezone.utc)
        # No data moved and a raster has no rows or schema. Only a moved
        # asset changes the tiles and the raster facts the embedding reads.
        return Published(
            dataset_version_id=None,
            feature_count=None,
            schema_diff=None,
            contacted_origin=True,
            tiles_changed=moved,
            reembed=moved,
        )

    def classify(self, exc: BaseException) -> Failure:
        health = getattr(exc, "health", None)
        # A verdict or a bare contact both date `last_checked_at`, under the
        # binding this attempt read; a failure before any request dates nothing.
        stamps = health is not None or getattr(exc, "contacted", False)
        code = _refresh_error_code(exc)
        return Failure(
            code,
            contacted=self.bound if stamps else None,
            health=(health, getattr(exc, "detail", None))
            if health is not None
            else None,
            # A rebind overtook the answer, and the message says to refresh again.
            notify=code != _ERROR_CODE_SUPERSEDED,
        )

    async def release(
        self, *, publication: PublicationCommit | None, failed: bool
    ) -> None:
        return None


@task_app.task(queue="ingest", retry=0)
@tenant_task
async def refresh_stac(
    job_id: str,
    dataset_id: str,
    attempt_id: str | None = None,
    credential_ref: str | None = None,
    **kwargs: Any,
) -> None:
    """Background task: re-resolve this dataset's STAC item and asset pointer.

    No ``user_id`` argument, for the same reason the registered-table refresh
    takes none: this creates no ``DatasetVersion`` and stamps no uploader,
    because no data moved. The actor is already on the run row as
    ``triggered_by``, which is where this operation's audit trail lives.

    ``credential_ref`` names a single-use credential the door staged; the
    secret itself never becomes a task argument.
    """
    _bind_task_log_context(
        task_name="refresh_stac", job_id=job_id, dataset_id=dataset_id
    )
    await settle_replacement(
        _StacRefresh(credential_ref=credential_ref),
        job_id=job_id,
        dataset_id=dataset_id,
        attempt_id=attempt_id,
    )
