"""On-demand source-health probe for live-referenced dataset origins (#1222).

ADR-002 gives ``datasets.source_health`` a three-value vocabulary and
``datasets.last_checked_at`` the meaning "the last time GeoLens contacted the
origin at all, success or failure". #1261 shipped both columns with nothing
writing them. This endpoint is one of their two designated writers (the other
is the refresh executor, #1220).

Only two origin kinds are live-referenced and therefore probeable:

- ``stac`` — the COG lives in someone else's bucket and is read at tile time
  (``storage_backend="remote"``). A deleted upstream is otherwise discovered
  only when a tile request fails, which is both late and invisible in the
  catalog.
- ``service`` — the rows were copied locally at import, so the data still
  renders, but a dead origin means the dataset can never be refreshed.

Everything else is 409 rather than a silent "unknown": an upload has no
remote origin to contact, a registered PostGIS table is local, and a VRT has
its own per-member health at ``/datasets/{id}/vrt/status/``. Returning 200
with ``unknown`` for those would make "nothing to probe" and "probe could not
tell" the same answer, which is the distinction the vocabulary exists to
keep.

### Why this is owner-or-admin and not a read

Probing is an ACTION, not a read: it makes GeoLens issue an outbound request
to a third-party host and then write two columns. Gating it on visibility
would let anyone who can see a public dataset drive traffic at somebody
else's origin service, with GeoLens as the amplifier, and write to a row
they do not own. So the guard is ``check_dataset_write_access``, matching
every other dataset mutation.

Readers are not shut out of the information. ``source_health``,
``source_health_detail`` and ``last_checked_at`` have been on
``DatasetResponse`` since #1218, so ``GET /datasets/{id}`` already serves the
stored state to anyone who can read the dataset. What a reader cannot do is
make GeoLens go and re-check.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user
from app.modules.catalog.authorization import check_dataset_write_access
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.schemas import SourceHealthResponse
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.catalog.sources.adapters.wfs import build_capabilities_url
from app.modules.catalog.sources.origin_probe import (
    ITEM_WITHDRAWN,
    MISSING,
    OriginProbeResult,
    probe_remote_uri,
)
from app.platform.dataset_origin import classify_origin
from app.platform.extensions import get_catalog_port
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets - Source health"],
    responses=ERROR_RESPONSES_WRITE,
)

# The origin kinds that point at something outside this GeoLens instance.
PROBEABLE_ORIGINS = frozenset({"service", "stac"})


def _origin_pointer_missing(origin: str) -> HTTPException:
    """409 for a probeable origin whose pointer never got recorded.

    Not an ``inaccessible`` health state: nothing was contacted, so writing
    ``last_checked_at`` would make the column mean something it does not.
    Datasets imported before ADR-002's backfill, or whose ``source_url`` had
    been edited to prose by the time the backfill ran, land here.
    """
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "origin_pointer_missing",
            "message": (
                "This dataset has no recorded origin pointer, so there is "
                "nothing to contact. Re-import it to record one."
            ),
            "origin": origin,
        },
    )


async def _remote_stac_asset_uri(db: AsyncSession, dataset_id: uuid.UUID) -> str | None:
    """The remote COG a STAC dataset's tiles actually read, if there is one."""
    RasterAsset = get_catalog_port().raster_asset_orm_class()
    result = await db.execute(
        select(RasterAsset.asset_uri)
        .where(
            RasterAsset.dataset_id == dataset_id,
            RasterAsset.storage_backend == "remote",
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _probe_stac_origin(db: AsyncSession, dataset: Dataset) -> OriginProbeResult:
    """Probe a STAC dataset's item document and its data asset.

    Both, because they answer different questions and either can fail alone.
    An item withdrawn from the catalog while its bucket keeps serving the COG
    is exactly the state a catalog should flag, and it is invisible to an
    asset-only probe. The reverse — item still published, asset deleted — is
    the common one and invisible to an item-only probe.

    Precedence: an item that is authoritatively gone wins, because "the
    publisher withdrew this" is the more actionable fact and the asset's
    continued availability does not change it. An item that is merely
    unreachable does NOT win: that is the 401/403-versus-404 distinction one
    level up, and treating "cannot tell about the item" as an item
    withdrawal would be the same mistake in a different place. Otherwise the
    asset's verdict stands, since the asset is what every tile request
    depends on.

    ``item_href`` is absent for catalogs that publish no rel=self link and for
    datasets imported before #1222 taught the import path to record it, so
    this degrades to the asset probe alone rather than requiring it.
    """
    asset_uri = await _remote_stac_asset_uri(db, dataset.id) or dataset.origin_uri
    item_href = (dataset.origin_ref or {}).get("item_href")
    if not asset_uri and not item_href:
        raise _origin_pointer_missing("stac")

    item_result: OriginProbeResult | None = None
    asset_result: OriginProbeResult | None = None
    if item_href and asset_uri:
        item_result, asset_result = await asyncio.gather(
            probe_remote_uri(item_href), probe_remote_uri(asset_uri)
        )
    elif item_href:
        item_result = await probe_remote_uri(item_href)
    else:
        asset_result = await probe_remote_uri(asset_uri)

    if item_result is not None and item_result.health == MISSING:
        return OriginProbeResult(MISSING, ITEM_WITHDRAWN)
    # One of the two is set: the guard above rejected the neither case.
    return asset_result if asset_result is not None else item_result


async def _probe_service_origin(dataset: Dataset) -> OriginProbeResult:
    """Probe a service origin for reachability only.

    Reachability is genuinely all this can claim. ArcGIS FeatureServer in
    particular answers a request for a layer that no longer exists with HTTP
    200 and an error envelope in the body, so a status-code probe reads that
    as healthy. Parsing per-service error bodies to do better is the
    connector-completeness contract, which ADR-002 leaves out of v1; until
    then ``missing`` on a service origin means the HTTP resource itself is
    gone, not that a layer was dropped from a service that still answers.

    fix(#1271 review): the probe target depends on the service type. Ingest
    stores ``origin_uri`` as ``<base>/<layer identity>`` for provenance, and
    only ArcGIS's flavor of that (``<base>/<numeric id>``) is a real HTTP
    resource — WFS and OGC API address layers through a typename or collection
    parameter, so their enriched URI is a non-endpoint and probing it records
    whatever the server's 404 fallback happens to say about a URL nobody
    serves. For those two the canonical service base in ``origin_ref.url`` is
    the thing whose reachability the answer claims to describe — and for WFS
    the base alone is not enough either: many servers 4xx a request without
    ``service=WFS&request=GetCapabilities``, so the probe asks the same
    question the import adapter asks, via the same URL builder. An OGC API
    base is a plain JSON landing page and needs no parameters.
    """
    ref = dataset.origin_ref or {}
    service_type = ref.get("service_type")
    if service_type in ("wfs", "ogcapi_features"):
        target = ref.get("url") or dataset.origin_uri
        if target and service_type == "wfs":
            target = build_capabilities_url(target)
    else:
        target = dataset.origin_uri or ref.get("url")
    if not target:
        raise _origin_pointer_missing("service")
    return await probe_remote_uri(target)


@router.post("/{dataset_id}/source-health/", response_model=SourceHealthResponse)
async def check_source_health(
    dataset_id: uuid.UUID,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SourceHealthResponse:
    """Contact this dataset's origin and record what came back.

    Owner-or-admin: this makes GeoLens issue an outbound request on the
    caller's behalf and writes to the dataset row. Readers get the stored
    result from ``GET /datasets/{id}`` instead.
    """
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    await check_dataset_write_access(db, dataset, dataset_id, user)

    origin = classify_origin(
        dataset.source_format, getattr(dataset.record, "record_type", None)
    )
    if origin not in PROBEABLE_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "health_check_not_applicable",
                "message": (
                    "Only service and STAC origins reference data outside this "
                    "instance. VRT datasets report per-member health at "
                    "/datasets/{id}/vrt/status/."
                ),
                "origin": origin,
            },
        )

    if origin == "stac":
        result = await _probe_stac_origin(db, dataset)
    else:
        result = await _probe_service_origin(dataset)

    # last_checked_at is written on BOTH outcomes — that is the whole meaning
    # of the column, and a failed probe is the case an operator most needs
    # dated. The probe helpers never raise for a network condition, so no path
    # from here reaches the response without this write.
    now = datetime.now(timezone.utc)
    dataset.last_checked_at = now
    dataset.source_health = result.health
    dataset.source_health_detail = result.detail
    await db.commit()

    # Built from locals rather than re-read from the instance: commit expires
    # the attributes, and touching them here would either issue a second round
    # trip or raise MissingGreenlet depending on the session's state.
    return SourceHealthResponse(
        dataset_id=dataset_id,
        origin=origin,
        source_health=result.health,
        source_health_detail=result.detail,
        last_checked_at=now,
    )
