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

    fix(#1271 review): split from the probing itself so the handler can
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

    ``contacted`` is the OR of the two probes' flags (fix #1271 review): a
    403 from the item beside a policy-blocked asset still means the origin
    answered once, and the contact clock must say so even though the asset's
    verdict is the one that stands.
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

    Reachability is nearly all this can claim. ArcGIS FeatureServer answers
    several conditions with HTTP 200 and an error envelope in the body, so a
    status-code probe reads them as healthy. fix(#1746) parses exactly one of
    those envelopes: codes 498 and 499, the auth refusals, which
    :func:`probe_arcgis_origin` reports as ``inaccessible`` /
    ``auth_required``. A DROPPED LAYER is still not detected — parsing the
    rest of the per-service error space is the connector-completeness
    contract, which ADR-002 leaves out of v1, so ``missing`` on a service
    origin still means the HTTP resource itself is gone, not that a layer was
    dropped from a service that still answers.

    The per-service target rule lives in
    :func:`~app.modules.catalog.sources.origin_probe.service_probe_target`,
    which the refresh door reads too (fix #1746). This wrapper is only the
    HTTP vocabulary around it: a row with nothing safe to probe answers 409
    rather than reporting a health state.
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

    # fix(#1271 review): the probe awaits a third-party host, and a reupload
    # can commit a new origin binding in that window. Persisting through the
    # ORM instance would write the OLD origin's verdict onto the new binding —
    # permanently, when a service became an upload, since uploads 409 above
    # and nothing could re-probe. Snapshot the binding now and make the write
    # conditional on it below; set_dataset_origin clearing probe state on
    # rebind covers the other interleaving (rebind commits after our write).
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
        # fix(#1746): read while the session is still live — the ORM instance
        # is dead after the rollback below, and the probe branch needs to know
        # whether this origin speaks ArcGIS error envelopes.
        service_type = (dataset.origin_ref or {}).get("service_type")

    # ...then release the pooled connection BEFORE the outbound wait
    # (fix #1271 review). The probe can take 10s against a slow origin, and
    # a session held across it pins a pool slot for the duration — a dozen
    # concurrent probes would starve every other database-backed request.
    # Everything the rest of the handler needs is in locals; the ORM
    # instance is dead after this line. The conditional UPDATE below opens
    # its own fresh transaction.
    await db.rollback()

    # feat(#1268): timed around the outbound wait only, not the handler. The
    # duration an operator cares about is the origin's, and folding the
    # database work either side of it in would blur the one number that says
    # "this source got slow". Real instruments rather than derived gauges,
    # because a probe is a request and one request is handled by one worker.
    probe_started = time.perf_counter()
    if origin == "stac":
        result = await _probe_stac_targets(asset_uri, item_href)
    else:
        # fix(#1746): ArcGIS answers an auth refusal with HTTP 200 and an
        # error envelope, which a status-code probe reads as healthy, so the
        # probe is chosen by service type. The refresh door chooses the same
        # way, through the same helper.
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

    # last_checked_at is written on BOTH outcomes — that is the whole meaning
    # of the column, and a failed probe is the case an operator most needs
    # dated. The one exception is a probe that never left GeoLens: an SSRF
    # policy refusal happens before any packet goes out (result.contacted is
    # False), and stamping it would overwrite a real earlier contact time
    # with a policy-check time. The verdict is still persisted — "policy now
    # blocks this origin" is true state — but the contact clock keeps its
    # prior value.
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
        # fix(#1271 review): the response reports what the row actually holds
        # after this write, not a pre-probe snapshot — a concurrent probe may
        # have committed a newer contact time that an uncontacted outcome
        # here correctly leaves in place.
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

    # fix(#1271 review): GET /datasets/ serves these three fields from a
    # 60-second cache, so without this the list keeps reporting the
    # pre-probe state after the probe response already showed the update —
    # the same reason every other dataset mutation invalidates here. After
    # the rowcount check: a discarded verdict changed nothing.
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
