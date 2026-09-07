"""On-demand source-health probe for live-referenced dataset origins (#1222).

One of two writers of ``datasets.source_health``/``last_checked_at``
(the other is the refresh executor, #1220). Only ``stac``/``service``
origins are probeable; everything else 409s rather than returning
``unknown``, keeping "nothing to probe" distinct from "couldn't tell".

Owner-or-admin, not read-gated: probing is an ACTION (outbound request
plus a write), so visibility alone would let anyone amplify traffic at
somebody else's origin. Readers still see the stored state via
``DatasetResponse`` (#1218); they just can't trigger a re-check.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user
from app.modules.catalog.authorization import check_dataset_write_access
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.datasets.domain.schemas import SourceHealthResponse
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.catalog.sources.origin_probe import (
    ITEM_WITHDRAWN,
    MISSING,
    OriginProbeResult,
    probe_remote_uri,
    probe_service_origin,
    service_probe_target,
)
from app.observability.metrics.refresh import (
    origin_probe_duration_seconds,
    origin_probe_total,
)
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.dataset_origin import classify_origin
from app.platform.extensions import get_catalog_port
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets - Source Health"],
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


async def _stac_probe_targets(
    db: AsyncSession, dataset: Dataset
) -> tuple[str | None, str | None]:
    """Resolve what a STAC probe would contact, on the request's DB session.

    fix(#1271): split from the probing itself so the handler can
    release its pooled connection before the outbound wait — target
    resolution is the only part that needs the database.
    """
    asset_uri = await _remote_stac_asset_uri(db, dataset.id) or dataset.origin_uri
    item_href = (dataset.origin_ref or {}).get("item_href")
    if not asset_uri and not item_href:
        raise _origin_pointer_missing("stac")
    return asset_uri, item_href


async def _probe_stac_targets(
    asset_uri: str | None, item_href: str | None
) -> OriginProbeResult:
    """Probe a STAC dataset's item document and its data asset. Pure network.

    Both, since either can fail alone (item withdrawn but bucket still
    serving, or item published but asset deleted -- the common case).
    Precedence: an item authoritatively gone wins over the asset's verdict;
    an item merely unreachable does NOT win, and the asset (what tiles
    depend on) decides instead. ``item_href`` absent degrades to the asset
    probe alone. ``contacted`` ORs both probes' flags.
    """
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

    contacted_any = any(
        r.contacted for r in (item_result, asset_result) if r is not None
    )
    if item_result is not None and item_result.health == MISSING:
        return OriginProbeResult(MISSING, ITEM_WITHDRAWN, contacted=contacted_any)
    # One of the two is set: the guard above rejected the neither case.
    chosen = asset_result if asset_result is not None else item_result
    if chosen.contacted != contacted_any:
        chosen = replace(chosen, contacted=contacted_any)
    return chosen


def _service_probe_target(dataset: Dataset) -> str:
    """The URL a service probe contacts. Reachability is all it can claim.

    fix(#1746): ArcGIS answers several conditions with HTTP 200 and an
    error envelope, so :func:`probe_arcgis_origin` parses codes 498/499
    (auth refusals) from the ``/query`` operation the worker actually
    reads, not the layer document. A DROPPED LAYER still reads as
    ``missing``, not detected as such -- out of scope for v1 (ADR-002).

    Target rule lives in
    :func:`~app.modules.catalog.sources.origin_probe.service_probe_target`
    (shared with the refresh door); this wrapper just answers 409 when
    nothing is safe to probe.
    """
    target = service_probe_target(dataset.origin_ref, dataset.origin_uri)
    if not target:
        # "Nothing safe to probe" stays distinguishable from a health state,
        # the same way every other pointerless row is answered.
        raise _origin_pointer_missing("service")
    return target


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

    # fix(#1271): the probe awaits a third-party host, and a reupload can
    # commit a new origin binding in that window. Persisting through the
    # ORM instance would write the OLD origin's verdict onto the new
    # binding, permanently if a service became an upload (uploads 409
    # above, so nothing could re-probe). Snapshot the binding now and make
    # the write conditional on it below; set_dataset_origin clearing probe
    # state on rebind covers the other interleaving.
    bound_uri = dataset.origin_uri
    bound_ref = dataset.origin_ref
    bound_format = dataset.source_format

    # Resolve what to contact while the session is still live...
    if origin == "stac":
        asset_uri, item_href = await _stac_probe_targets(db, dataset)
        service_target = None
        service_type = None
    else:
        asset_uri = item_href = None
        service_target = _service_probe_target(dataset)
        # fix(#1746): read while the session is still live -- the ORM
        # instance is dead after the rollback below, and the probe branch
        # needs to know whether this origin speaks ArcGIS error envelopes.
        service_type = (dataset.origin_ref or {}).get("service_type")

    # fix(#1271): release the pooled connection BEFORE the outbound wait.
    # The probe can take 10s against a slow origin, and a session held
    # across it pins a pool slot -- a dozen concurrent probes would starve
    # every other database-backed request. The conditional UPDATE below
    # opens its own fresh transaction.
    await db.rollback()

    # feat(#1268): timed around the outbound wait only, not the handler --
    # the duration an operator cares about is the origin's, and folding
    # database work in would blur the one number that says "this source
    # got slow".
    probe_started = time.perf_counter()
    if origin == "stac":
        result = await _probe_stac_targets(asset_uri, item_href)
    else:
        # fix(#1746): ArcGIS answers an auth refusal with HTTP 200 and an
        # error envelope, which a status-code probe reads as healthy, so
        # the probe is chosen by service type, same as the refresh door.
        result = await probe_service_origin(service_target, service_type)
    origin_probe_duration_seconds.labels(
        origin_kind=origin, health=result.health
    ).observe(time.perf_counter() - probe_started)
    origin_probe_total.labels(
        origin_kind=origin,
        health=result.health,
        # "none" rather than an empty label: a healthy probe has no detail
        # code, and an empty string reads as a missing label in PromQL.
        detail=result.detail or "none",
    ).inc()

    # last_checked_at is written on BOTH outcomes -- a failed probe is the
    # case an operator most needs dated. Exception: an SSRF policy refusal
    # happens before any packet goes out (result.contacted is False), so
    # stamping it would overwrite a real earlier contact time with a
    # policy-check time. The verdict is still persisted; the clock isn't.
    now = datetime.now(timezone.utc)
    values: dict[str, object] = {
        "source_health": result.health,
        "source_health_detail": result.detail,
    }
    if result.contacted:
        values["last_checked_at"] = now
    outcome = await db.execute(
        update(Dataset)
        .where(
            Dataset.id == dataset_id,
            Dataset.origin_uri.is_not_distinct_from(bound_uri),
            Dataset.origin_ref.is_not_distinct_from(bound_ref),
            Dataset.source_format.is_not_distinct_from(bound_format),
        )
        .values(**values)
        # fix(#1271): the response reports what the row actually holds
        # after this write, not a pre-probe snapshot -- a concurrent probe
        # may have committed a newer contact time that this outcome leaves
        # in place.
        .returning(Dataset.last_checked_at)
    )
    # Row-level, not rowcount: an ORM-enabled UPDATE..RETURNING yields a
    # ChunkedIteratorResult, which has no rowcount — and rows also separate
    # "no match" (empty) from "matched, NULL timestamp" (one row of None).
    returned_rows = outcome.all()
    await db.commit()
    if not returned_rows:
        # The row was rebound (or deleted) while the probe was in flight; the
        # verdict describes an origin this dataset no longer has. Discard it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_changed",
                "message": (
                    "The dataset's origin changed while the probe was in "
                    "flight; the result was discarded. Re-run the check."
                ),
            },
        )

    # fix(#1271): GET /datasets/ serves these fields from a 60s cache, so
    # without this the list keeps reporting pre-probe state. After the
    # rowcount check: a discarded verdict changed nothing.
    await invalidate_catalog_cache()

    # Built from locals rather than re-read from the instance: commit expires
    # the attributes, and touching them here would either issue a second round
    # trip or raise MissingGreenlet depending on the session's state.
    return SourceHealthResponse(
        dataset_id=dataset_id,
        origin=origin,
        source_health=result.health,
        source_health_detail=result.detail,
        last_checked_at=returned_rows[0][0],
    )
