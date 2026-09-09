"""One-request refresh of a dataset from its stored origin binding.

feat(#1220) / ADR-002 Decisions 5a, 5b, 5c and 6. Re-pulling a service
dataset used to mean walking the re-upload dialog (restating the URL,
layer, etc. the catalog already knows -- a chance to state it
differently and silently re-point the dataset). This door reads the
pointer instead: the request body carries no URL, type, or layer, only
an optional transient credential (see ``platform/refresh/credentials.py``).

Separate module rather than more of ``router_reupload.py`` (already the
largest file in the package, at its size cap); shares almost nothing
with preview/commit beyond two helpers. The admission control, run row,
and worker dispatch machinery IS deliberately the same
(``create_pending_run``, the same ``reupload_service`` task) -- a
second admission path is how the two doors end up with different rules.

feat(#1265) added a second execution strategy behind that same
machinery: one endpoint, one Rule 1 gate, one admission function, one
run ledger, varying only the binding unpacked and the task deferred.
Registered PostGIS differs most (no URL, no SSRF check, no credential)
and still goes through the same
``create_pending_run``/``defer_with_orphan_guard``/
``make_refresh_run_failed_rollback`` -- parts that must not have two
implementations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import defer_async_with_tenant
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import check_dataset_write_access
from app.modules.catalog.datasets.domain.schemas import (
    DatasetRefreshRequest,
    DatasetRefreshResponse,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.platform.security import SSRFError, validate_url_for_ssrf
from app.modules.catalog.sources.schemas import service_credential_from_request
from app.modules.catalog.sources.stac_resolve import states_verifiable_identity
from app.platform.service_auth import wire_credential
from app.modules.catalog.sources.origin_probe import (
    AUTH_CHALLENGE_DETAILS,
    probe_arcgis_origin,
    service_probe_target,
)
from app.platform.dataset_origin import classify_origin, service_auth_required
from app.platform.extensions import get_catalog_port
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import IngestJob
from app.platform.refresh.credentials import (
    CredentialStoreUnavailable,
    credential_store_available,
    discard_service_credential,
    stash_service_credential,
)
from app.platform.refresh.service import (
    DatasetBusyError,
    create_pending_run,
    make_refresh_run_failed_rollback,
)
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets",
    tags=["Datasets - Refresh"],
    responses=ERROR_RESPONSES_WRITE,
)
logger = structlog.get_logger(__name__)

# ``origin_ref["service_type"]`` stores the canonical format, while
# ``build_gdal_source`` and ``resolve_service_type`` both dispatch on a human
# label by prefix ("ArcGIS...", "WFS...", "OGC API..."). One table maps back,
# and ``test_service_refresh_1220`` round-trips every entry through
# ``resolve_service_type`` so a label that stops resolving fails a test rather
# than a refresh.
_SERVICE_TYPE_LABELS: dict[str, str] = {
    "arcgis_featureserver": "ArcGIS FeatureServer",
    "wfs": "WFS",
    "ogcapi_features": "OGC API - Features",
}


@dataclass(frozen=True)
class _ServiceOrigin:
    """The stored binding, re-expressed as the ingest pipeline's arguments.

    ``layer_id``/``layer_name`` are mutually exclusive by service type
    (``build_gdal_source`` wants the numeric id for ArcGIS, the name for
    WFS/OGC API). ``origin_ref`` stores whichever addresses the layer
    under one key; unpacked here once, and the worker's
    ``service_layer_identity`` folds it back to the same value after a
    swap, so a refresh doesn't slowly rewrite the pointer it refreshed from.
    """

    source_format: str
    service_label: str
    base_url: str
    layer_id: int | str | None
    layer_name: str


def _resolve_service_origin(dataset) -> _ServiceOrigin:
    """Unpack a service dataset's binding, or explain why it cannot refresh.

    Two different 409s, because they are two different problems for the
    person reading them: ``refresh_not_applicable`` means this kind of dataset
    has no origin to re-pull from (an upload, a drawn layer, a collection, a
    VRT — a registered table has one, and reaches this function only if it
    was rebound mid-request, since the handler routes that kind to its own
    strategy), and ``origin_unavailable`` means it does but GeoLens never
    recorded enough of it — a service dataset from before the binding existed
    whose backfill could not reconstruct a base URL and layer.
    """
    origin_kind = classify_origin(dataset.source_format, dataset.record.record_type)
    if origin_kind != "service":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "refresh_not_applicable",
                "message": (
                    "This dataset has no remote service origin to refresh "
                    "from. Replace its data through re-upload instead."
                ),
                "origin_kind": origin_kind,
            },
        )

    ref = dataset.origin_ref or {}
    base_url = ref.get("url")
    stored_format = ref.get("service_type")
    layer_identity = ref.get("layer_id")
    service_label = _SERVICE_TYPE_LABELS.get(stored_format or "")
    if not base_url or not service_label:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_unavailable",
                "message": (
                    "This dataset's source binding is incomplete, so GeoLens "
                    "cannot re-pull it without being told where from. "
                    "Re-import the layer through the service import flow."
                ),
                "origin_kind": "service",
            },
        )
    if layer_identity is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_unavailable",
                "message": (
                    "This dataset's source binding records no layer, so "
                    "GeoLens cannot tell which layer of the service to "
                    "re-pull. Re-import the layer through the service import "
                    "flow."
                ),
                "origin_kind": "service",
            },
        )

    if stored_format == "arcgis_featureserver":
        return _ServiceOrigin(
            source_format=stored_format,
            service_label=service_label,
            base_url=base_url,
            layer_id=layer_identity,
            # Ignored by the ArcGIS branch of build_gdal_source, and left
            # empty rather than guessed: a name here would be a second layer
            # identifier that nothing reads and the next reader would trust.
            layer_name="",
        )
    # fix(#1277): layer_id must carry the identity here too -- setting it
    # None was a real bug, not tidiness. `build_gdal_source` ignores
    # layer_id for WFS/OGC API, but the worker ALSO composes the stored
    # pointer as `base/layer_id`, same as the import path (probe.py sets
    # `layer_id = layer["name"]` for these services), so passing None
    # rewrote origin_uri/source_url to the bare base on every refresh --
    # silently respelling a verified-unchanged binding. Visible damage:
    # the duplicate-source guard matches on origin_uri, so a re-import of
    # the same layer stopped looking like a duplicate after one refresh.
    return _ServiceOrigin(
        source_format=stored_format or "",
        service_label=service_label,
        base_url=base_url,
        layer_id=layer_identity,
        layer_name=str(layer_identity),
    )


def _service_token_required() -> HTTPException:
    """The one 422 both refusal paths raise, so the wording cannot fork.

    fix(#1746): the message used to name only the deprecated `token`
    field (a bearer credential), but a WFS/OGC API origin last pulled
    with a username/password or API key is marked by the same flag, so
    following that advice couldn't authenticate it. Code unchanged: a
    client keying on it is answering the same question.
    """
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "service_token_required",
            "message": (
                "This dataset's source needed a credential the last time it "
                "was imported or refreshed, and this request carries none. "
                "Send it again in the request body's `auth` object, using the "
                "same method the source needs; the deprecated `token` field "
                "still works and means a bearer token. Credentials are "
                "request-only and are never stored between runs. If the "
                "source is public now, re-import it through the re-upload "
                "dialog without a credential to clear the requirement."
            ),
        },
    )


async def _recheck_service_token_after_reservation(
    db, dataset, token, *, marked_before: bool
) -> None:
    """Catch a marker that APPEARED while the refresh was being reserved.

    fix(#1746): a race the pre-reservation guard can't close -- an
    authenticated re-upload of the same origin can mark the dataset
    inside the reservation window, after a token-less refresh already
    read it unmarked, sending dispatch token-less into the worker
    failure the guard exists to prevent. The post-reservation
    ``_ServiceOrigin`` equality check can't catch it (auth state
    changed, not the source), and the marker must not be folded into
    that dataclass either -- it would answer ``origin_changed``, whose
    copy tells the caller to check the new source when the fix is a
    token. So the decision is re-applied here instead.

    No probe: a marker that just appeared was written by an
    authenticated pull seconds ago -- the strongest evidence possible.
    A TRANSITION, not a second opinion: ``marked_before`` was already
    adjudicated by the pre-check (probed ArcGIS, or refused WFS
    outright), so re-deciding on the marker alone would overturn a
    healthy probe with no new evidence.
    """
    if token or marked_before or not service_auth_required(dataset.origin_ref):
        return
    # Release the reservation the way every other post-reservation
    # refusal does, so a refused request leaves no run row holding the dataset.
    await db.rollback()
    raise _service_token_required()


async def _require_service_token_if_marked(db, dataset, dataset_id, token):
    """Handle a token-less refresh of an origin whose last pull used a token.

    Returns the dataset to carry forward (re-read if the ArcGIS probe
    path had to release the session).

    CALLER CONTRACT: the ArcGIS probe path may roll back, expiring EVERY
    ORM instance in the session -- anything the caller loaded earlier
    and still needs (including ``user``) must be re-read first.

    fix(#1746): refusing here, naming the field that fixes it, beats
    dispatching a token-less refresh that 202s and fails in the worker.
    The marker alone isn't proof (the worker can't observe a challenge,
    so ``auth_required`` just means the last pull used a token, even if
    the service was public), so where possible the door asks the origin.

    fix(#1755): ArcGIS is asked, at the same ``<layer>/query`` resource
    the worker fetches (499/498 = token required/rejected); a healthy
    answer means a false marker costs one probe, never a refusal. WFS
    and OGC API Features are refused outright, no probe: their
    capabilities/landing-page resource is DIFFERENT from what the
    worker fetches, so a healthy answer there is evidence of nothing.
    Probing the feature endpoint anonymously is not on the table either:
    composing a GetFeature/``/items`` request means reproducing the
    worker's URL-building path, and a wrong one answers 400 and reads
    as "not an auth problem".

    Escape hatch for both: a successful token-less pull rebuilds the ref
    without the key, and the re-upload dialog still allows one. Only an
    auth challenge refuses on the ArcGIS path -- every other outcome
    fails open, since a third party's bad day shouldn't become a refusal.
    """
    if token or not service_auth_required(dataset.origin_ref):
        return dataset
    ref = dataset.origin_ref or {}
    if ref.get("service_type") != "arcgis_featureserver":
        # No probe, and no session released: this path touches no network.
        raise _service_token_required()
    target = service_probe_target(ref, dataset.origin_uri)
    if not target:
        # Nothing safe to contact, so there is nothing to ask. The health
        # endpoint answers 409 here; a refresh has no verdict to persist and
        # simply lets the worker try.
        return dataset

    # fix(#1746): release the pooled connection BEFORE the outbound wait,
    # same as `check_source_health` -- a session held across a slow
    # origin's probe pins a pool connection, and enough concurrent
    # marked refreshes would starve other requests. Nothing is written
    # yet, so this rolls back a read-only transaction at no cost. The
    # ORM instance is dead across the await; hence the re-read below.
    await db.rollback()
    try:
        result = await probe_arcgis_origin(target)
    except Exception:  # broad: this guard must never 500 a refresh bound for 202
        # `probe_arcgis_origin` already swallows every transport failure into
        # a verdict, so this is the belt to those braces. Anything that still
        # escapes is a bug in the probe, and the honest response is to let the
        # refresh proceed the way it did before this guard existed.
        result = None

    # Re-read on BOTH outcomes, so the post-condition is flat: when this
    # returns or raises, the session is live again and no expired instance is
    # left for a later line to touch. Write access was gated on this same
    # dataset id before the probe; this read only re-materializes it.
    reloaded = await get_dataset(db, dataset_id)
    if reloaded is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    if result is not None and result.detail in AUTH_CHALLENGE_DETAILS:
        raise _service_token_required()
    return reloaded


@dataclass(frozen=True)
class _PostgisOrigin:
    """The registered table a postgis-origin dataset is bound to.

    One field, and that is the whole of ADR-002 gate 2: ``origin_ref`` for
    this kind accepts ``table_name`` and nothing else — no host, port, DSN or
    credential — so there is no shape in which this dataclass could address a
    table outside this instance. The stored value is schema-qualified
    (``set_postgis_origin`` composes it), and the worker proves it names this
    dataset's own live table before reading anything.
    """

    table_name: str


def _resolve_postgis_origin(dataset) -> _PostgisOrigin:
    """Unpack a registered table's binding, or explain why it cannot refresh.

    Same two refusals, and the same distinction between them, as
    :func:`_resolve_service_origin`: ``refresh_not_applicable`` for a kind
    with no origin to re-measure, ``origin_unavailable`` for a registered
    dataset whose binding predates #1218 and carries no table name. The
    second is recoverable by re-registering the table; the first is not
    recoverable at all, and telling the two apart is the difference between
    useful advice and a shrug.
    """
    origin_kind = classify_origin(dataset.source_format, dataset.record.record_type)
    if origin_kind != "postgis":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "refresh_not_applicable",
                "message": (
                    "This dataset is not backed by a registered table, so "
                    "there is nothing to re-measure."
                ),
                "origin_kind": origin_kind,
            },
        )
    table_name = (dataset.origin_ref or {}).get("table_name")
    if not table_name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_unavailable",
                "message": (
                    "This dataset's source binding does not record which "
                    "table it was registered from, so GeoLens cannot tell "
                    "what to re-measure. Register the table again."
                ),
                "origin_kind": "postgis",
            },
        )
    return _PostgisOrigin(table_name=table_name)


async def _dispatch_postgis_refresh(
    db: AsyncSession,
    *,
    dataset,
    dataset_id: uuid.UUID,
    user: Identity,
    token: str | None,
) -> DatasetRefreshResponse:
    """Admit and dispatch a re-measurement of a registered table.

    The ordering is the service path's, minus the steps that only a remote
    origin has, and for the same reasons — see the long note in
    :func:`refresh_dataset`. In particular the binding that gets dispatched is
    read AFTER the reservation exists, so a re-upload that commits while this
    request is being admitted cannot have its rebind dispatched from a
    pre-swap snapshot. There is no SSRF step because there is no URL, and no
    credential step because there is nothing to authenticate to: the origin is
    a relation in this database, reached over the connection the request is
    already using.
    """
    # A pre-check, exactly as on the service path: it answers the cheap
    # refusals before the admission index is touched. The value that gets
    # dispatched is the re-read below.
    candidate = _resolve_postgis_origin(dataset)

    if token:
        # Refused rather than ignored. Nothing on this path could use a
        # credential, and accepting one would answer 202 to a request that
        # handed GeoLens a secret it silently dropped — the caller would have
        # no way to learn their token went nowhere.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "credential_not_applicable",
                "message": (
                    "This dataset is backed by a registered table in this "
                    "instance, which needs no service credential. Send the "
                    "request without a token."
                ),
            },
        )

    job = IngestJob(
        dataset_id=dataset_id,
        created_by=user.id,
        status="pending",
        # Deliberately NOT `reupload: True`. That marker means "a task is
        # replacing this dataset's data", and two pieces of shared SQL key off
        # it — the legacy-live admission probe and the abandoned-run sweep's
        # other-live-task clause — both of which reason about swaps this task
        # never performs. `refresh` alone is the honest marker, and it is the
        # one the job list already reads to tell a refresh from an import.
        user_metadata={
            "refresh": True,
            "dataset_id": str(dataset_id),
            "origin_kind": "postgis",
        },
    )
    db.add(job)
    await db.flush()

    try:
        run = await create_pending_run(
            db,
            dataset_id=dataset_id,
            origin_kind="postgis",
            trigger="api",
            triggered_by=user.id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
    except DatasetBusyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": (
                    "A refresh is already running for this dataset. "
                    "Wait for it to finish, then try again."
                ),
            },
        ) from exc

    await db.refresh(
        dataset, ["origin_uri", "origin_ref", "source_format", "feature_count"]
    )
    try:
        origin = _resolve_postgis_origin(dataset)
    except HTTPException:
        # Rebound to something this strategy cannot refresh while we were
        # reserving — a file re-upload of the registered dataset, most
        # likely. Release the reservation before answering, or the leaked run
        # row refuses every later refresh until the sweep cancels it.
        await db.rollback()
        raise
    if origin != candidate:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_changed",
                "message": (
                    "This dataset's source changed while the refresh was "
                    "being queued, so it was not started. Check the new "
                    "source and try again."
                ),
            },
        )

    # The job carries no source pointer of its own — the worker reads the
    # binding, the same way this handler does. The filename slot is what the
    # job list renders, and the table is the only name this operation has.
    job.source_filename = origin.table_name
    # Read after the reservation for the same reason the binding is: a
    # refresh that finished in the window changed the count this one is
    # measured against, and the history row renders it as the "before".
    run.feature_count_before = dataset.feature_count

    job_id = job.id
    attempt_id = job.attempt_id
    run_id = run.id
    await db.commit()

    rollback = make_refresh_run_failed_rollback(
        make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue refresh task"
        ),
        db=db,
        ingest_job_id=job_id,
    )

    async def _defer_refresh() -> None:
        await defer_async_with_tenant(
            get_catalog_port().refresh_postgis_task(),
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            dataset_id=str(dataset_id),
        )

    await defer_with_orphan_guard(_defer_refresh, rollback=rollback, db=db, job=job)

    return DatasetRefreshResponse(
        run_id=run_id,
        job_id=job_id,
        dataset_id=dataset_id,
        origin_kind="postgis",
        trigger="api",
        status="pending",
        message="Refresh queued from the registered table",
    )


@dataclass(frozen=True)
class _StacOrigin:
    """The STAC item a remote-asset dataset was published in.

    ``item_href`` is the only field this strategy cannot work without, and
    the reason is the asymmetry ``origin_ref``'s comment already records: the
    asset href answers "is the COG still there", the item href answers "where
    does the publisher say the COG is now". Only the second can follow a
    move, so only the second is required here.

    The other three are the identity the worker re-resolves WITH — the
    collection scopes the fallback search, and the key and the previous href
    are how the right asset is recognised in the item that comes back.
    """

    item_href: str
    item_id: str | None
    collection_id: str | None
    asset_href: str | None
    asset_key: str | None


def _resolve_stac_origin(dataset) -> _StacOrigin:
    """Unpack a STAC dataset's binding, or explain why it cannot refresh.

    The same two refusals, with the same distinction, as the two resolvers
    above: ``refresh_not_applicable`` for a kind with no origin of this
    shape, ``origin_unavailable`` for a STAC dataset whose binding records no
    item href — imported before #1222 taught search to capture the
    ``rel=self`` link, or from a catalog that publishes none. The second is
    recoverable by re-importing the item; the first is not recoverable at
    all, and telling them apart is the difference between useful advice and a
    shrug.
    """
    origin_kind = classify_origin(dataset.source_format, dataset.record.record_type)
    if origin_kind != "stac":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "refresh_not_applicable",
                "message": (
                    "This dataset was not imported from a STAC item, so there "
                    "is no item to re-resolve."
                ),
                "origin_kind": origin_kind,
            },
        )
    ref = dataset.origin_ref or {}
    item_href = ref.get("item_href")
    item_id = ref.get("item_id")
    collection_id = ref.get("collection_id")
    if not item_href:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_unavailable",
                "message": (
                    "This dataset's source binding does not record the STAC "
                    "item its asset was published in, so GeoLens cannot ask "
                    "the catalog where that asset is now. Re-import it from "
                    "the STAC catalog to record one."
                ),
                "origin_kind": "stac",
            },
        )
    if not states_verifiable_identity(
        item_href=item_href, item_id=item_id, collection_id=collection_id
    ):
        # fix(#1266): refused here rather than discovered by
        # the worker, so the caller learns immediately and no run row is
        # spent. A binding written before the item id was recorded, whose
        # catalog publishes item URLs that state no identity either, gives a
        # refresh nothing to check the publisher's answer against — and an
        # unverified first answer would be adopted AND recorded as durable
        # truth. Re-importing records the identity and the dataset refreshes
        # normally thereafter.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_unavailable",
                "message": (
                    "GeoLens cannot tell this dataset's STAC item from "
                    "another one its stored URL might serve: the binding "
                    "predates item-identity tracking and the catalog's item "
                    "URLs carry no identity of their own. Re-import it from "
                    "the STAC catalog to record one."
                ),
                "origin_kind": "stac",
            },
        )
    return _StacOrigin(
        item_href=item_href,
        item_id=item_id,
        collection_id=collection_id,
        asset_href=ref.get("asset_href"),
        asset_key=ref.get("asset_key"),
    )


async def _dispatch_stac_refresh(
    db: AsyncSession,
    *,
    dataset,
    dataset_id: uuid.UUID,
    user: Identity,
    token: str | None,
) -> DatasetRefreshResponse:
    """Admit and dispatch a re-resolution of a STAC item and its asset.

    The service path's ordering, for the service path's reasons (see the long
    note in :func:`refresh_dataset`): eligibility and SSRF on a pre-check
    binding before the reservation, then every dispatched value re-read once
    the reservation exists. What differs is only what is unpacked and which
    task is deferred.

    feat(#1764): ``token`` is the composed header line for a protected
    catalog, staged through the same single-use store the service path uses.
    """
    candidate = _resolve_stac_origin(dataset)

    # feat(#1764): the same rule the WFS/OGC API branch applies, and for the
    # same reason: the marker means the last successful refresh used a
    # credential, so a token-less one would reach the catalog, collect a 401
    # and report a live dataset as inaccessible. No probe — a STAC item read
    # is the resource the worker fetches, so an anonymous pre-check would
    # cost a request to learn what the marker already says.
    if not token and service_auth_required(dataset.origin_ref):
        raise _service_token_required()

    # Refused before anything is written, for the reason the service path
    # gives: without a shared store the secret cannot reach the worker, and
    # dispatching anyway fails an hour later for a reason that is a missing
    # setting rather than the credential.
    if token and not credential_store_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "credential_store_unavailable",
                "message": (
                    "Refreshing a protected catalog needs a shared credential "
                    "store so the credential can reach the worker without "
                    "being written to disk. Set REDIS_URL and try again."
                ),
            },
        )

    # Rule 2: the item href is ours, but "ours" is not a safety property — it
    # was a catalog's when import stored it, and DNS moves. Before the
    # reservation, so resolving it never happens while an uncommitted run row
    # is held; the worker's fetch revalidates per hop through the safe client.
    try:
        await validate_url_for_ssrf(candidate.item_href)
    except SSRFError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This dataset's stored STAC item URL is not reachable: {exc}",
        ) from exc

    job = IngestJob(
        dataset_id=dataset_id,
        created_by=user.id,
        status="pending",
        # Deliberately NOT `reupload: True`, for the reason the postgis door
        # gives: that marker means "a task is replacing this dataset's data",
        # and two pieces of shared SQL key off it to reason about swaps this
        # task never performs.
        user_metadata={
            "refresh": True,
            "dataset_id": str(dataset_id),
            "origin_kind": "stac",
        },
    )
    db.add(job)
    await db.flush()

    try:
        run = await create_pending_run(
            db,
            dataset_id=dataset_id,
            origin_kind="stac",
            trigger="api",
            triggered_by=user.id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
    except DatasetBusyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": (
                    "A refresh is already running for this dataset. "
                    "Wait for it to finish, then try again."
                ),
            },
        ) from exc

    await db.refresh(
        dataset,
        ["origin_uri", "origin_ref", "source_format", "source_filename"],
    )
    try:
        origin = _resolve_stac_origin(dataset)
    except HTTPException:
        # Rebound to something this strategy cannot refresh while we were
        # reserving — a raster replace of the same dataset, most likely.
        # Release the reservation before answering, or the leaked run row
        # refuses every later refresh until the sweep cancels it.
        await db.rollback()
        raise
    if origin != candidate:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_changed",
                "message": (
                    "This dataset's source changed while the refresh was "
                    "being queued, so it was not started. Check the new "
                    "source and try again."
                ),
            },
        )

    # The job carries no source pointer of its own — the worker reads the
    # binding, the same way this handler does. The filename slot is what the
    # job list renders, and the item id is the only name this operation has.
    job.source_filename = dataset.source_filename
    if token:
        # feat(#1764): a boolean, never the credential — the same marker the
        # service door writes, recording that this attempt's credential was
        # request-scoped and a retry cannot reproduce the authenticated read.
        job.user_metadata = {**(job.user_metadata or {}), "service_auth_required": True}

    # Stashed before the commit, for the reason the service door gives: a
    # store failure rolls the whole request back rather than leaving a
    # dispatch that can never authenticate.
    credential_ref: str | None = None
    if token:
        try:
            credential_ref = await stash_service_credential(token)
        except CredentialStoreUnavailable as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "credential_store_unavailable",
                    "message": (
                        "Could not stage the credential for this refresh. "
                        "Check that the credential store is reachable and "
                        "try again."
                    ),
                },
            ) from exc

    job_id = job.id
    attempt_id = job.attempt_id
    run_id = run.id
    await db.commit()

    inner_rollback = make_refresh_run_failed_rollback(
        make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue refresh task"
        ),
        db=db,
        ingest_job_id=job_id,
    )

    async def _rollback(defer_exc: BaseException) -> None:
        await inner_rollback(defer_exc)
        # The worker will never come for it, and the run is already terminal.
        # Best-effort; the TTL is the real guarantee.
        await discard_service_credential(credential_ref)

    async def _defer_refresh() -> None:
        await defer_async_with_tenant(
            get_catalog_port().refresh_stac_task(),
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            dataset_id=str(dataset_id),
            # The REFERENCE, never the secret. Task arguments are durable
            # rows; this value means nothing once claimed or expired. An
            # old-generation worker takes **kwargs and discards it, so a
            # rolling deploy fails the run promptly instead of hanging it.
            credential_ref=credential_ref,
        )

    await defer_with_orphan_guard(_defer_refresh, rollback=_rollback, db=db, job=job)

    return DatasetRefreshResponse(
        run_id=run_id,
        job_id=job_id,
        dataset_id=dataset_id,
        origin_kind="stac",
        trigger="api",
        status="pending",
        message="Refresh queued from the stored STAC item",
    )


async def _prior_service_ingest_settings(
    db: AsyncSession, dataset_id: uuid.UUID
) -> tuple[str | None, str | None]:
    """``(source_filename, object_id_field)`` from the last successful ingest.

    Neither belongs in ``origin_ref`` — the allowlist there is deliberately
    the pointer and nothing else — but both change what a refresh produces.
    ``object_id_field`` is the ArcGIS paging order key, and a service whose
    key is not ``OBJECTID`` pages incorrectly without it; ``source_filename``
    is what the version row and the dataset's display name carry forward.
    Reading them from the previous job keeps a refresh reproducing the last
    good ingest rather than a default that happened to work for most
    services. Absent for a dataset whose jobs have aged out of retention, in
    which case the caller falls back to the layer identity.
    """
    result = await db.execute(
        select(IngestJob)
        .where(
            IngestJob.dataset_id == dataset_id,
            IngestJob.status == "complete",
            IngestJob.source_url.isnot(None),
        )
        .order_by(desc(IngestJob.completed_at))
        .limit(1)
    )
    prior = result.scalar_one_or_none()
    if prior is None:
        return None, None
    return prior.source_filename, (prior.user_metadata or {}).get("object_id_field")


@router.post(
    "/{dataset_id}/refresh",
    response_model=DatasetRefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_dataset(
    dataset_id: uuid.UUID,
    request: DatasetRefreshRequest | None = None,
    user: Identity = Depends(require_permission("edit_metadata")),
    db: AsyncSession = Depends(get_db),
) -> DatasetRefreshResponse:
    """Re-pull this dataset's data from the origin it was imported from.

    One request, no source pointer, no layer selection. The dataset keeps
    serving its current data throughout: the worker loads into an
    attempt-scoped staging table and swaps only once the new data is
    complete, so a refresh that fails leaves the live table and its freshness
    exactly as they were.

    Two origin kinds take their own execution strategy, and neither moves any
    data. A dataset registered from an existing PostGIS table (#1265) has an
    origin that IS the table it serves from, so its refresh re-measures the
    live relation — recounting features, recomputing the extent, rebuilding
    the column schema snapshot and statistics. A dataset imported from a STAC
    item (#1266) is nothing but a pointer at somebody else's COG, so its
    refresh re-reads the item document and follows the asset if the publisher
    moved it. Admission, the run row and the history they write are identical
    across all three.

    Refuses with 409 ``dataset_busy`` while another refresh or re-upload is
    active for this dataset — v1 rejects rather than queues (Decision 5b), and
    the refusal comes from a partial unique index rather than a check, so two
    simultaneous clicks cannot both be admitted.
    """
    body = request or DatasetRefreshRequest()
    # feat(#1746): the structured credential is what the service layer takes;
    # `body.token` is its deprecated bearer spelling.
    credential = service_credential_from_request(body.auth, body.token)

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    # Rule 1: this endpoint replaces the dataset's data. One gate, before the
    # strategy split below, so neither strategy can be reached without it.
    await check_dataset_write_access(db, dataset, dataset_id, user)

    # Judged and composed as soon as the origin is known: header line for
    # WFS/OGC API, bare token for ArcGIS, 422 for a method the origin
    # can't carry -- before any origin is contacted or row written, so a
    # bad credential never probes, reserves, or stashes.
    #
    # fix(#1746): AFTER the write-access gate, never before it -- this
    # reads `dataset.source_format`, so a refusal running first would
    # answer 422 for a dataset the caller may not touch, leaking its
    # existence and source family ahead of the visibility check.
    service_token = wire_credential(credential, service_format=dataset.source_format)

    # `classify_origin` is the same pure derivation ADR-002 Decision 2
    # keeps for the API's `origin` field, so this dispatch can't disagree
    # with it. Unnamed kinds fall through to the service path, whose
    # resolver answers `refresh_not_applicable` for originless kinds.
    origin_kind = classify_origin(dataset.source_format, dataset.record.record_type)
    if origin_kind == "postgis":
        return await _dispatch_postgis_refresh(
            db,
            dataset=dataset,
            dataset_id=dataset_id,
            user=user,
            token=service_token,
        )
    if origin_kind == "stac":
        return await _dispatch_stac_refresh(
            db,
            dataset=dataset,
            dataset_id=dataset_id,
            user=user,
            token=service_token,
        )

    # Record-type eligibility isn't checked separately: `classify_origin`
    # already returns None for the two originless record types
    # (collection, VRT), and `refresh_not_applicable` is the honest
    # answer for both -- the re-upload door's guard talks about a file
    # swap and would answer a refresh with advice about a different feature.
    #
    # fix(#1277): this read is a PRE-CHECK, not what gets dispatched --
    # it answers cheap refusals before the admission index and supplies
    # a URL to validate outside the reservation window. The binding the
    # worker actually gets is read again below, after the reservation.
    candidate = _resolve_service_origin(dataset)

    # Rule 2: the URL is ours, but "ours" isn't a safety property -- it
    # was a client's when ingest stored it, and DNS moves. Revalidating
    # here matches the preview door; the worker revalidates again at
    # fetch time for the window in between. Kept BEFORE the reservation:
    # this resolves DNS, and holding an uncommitted run row across a
    # network wait would queue every other refresh of this dataset
    # behind a resolver.
    try:
        await validate_url_for_ssrf(candidate.base_url)
    except SSRFError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This dataset's stored source URL is not reachable: {exc}",
        ) from exc

    # fix(#1746): placed after the postgis/stac early returns (never fires
    # for a non-service origin) and after the SSRF block, since its
    # ArcGIS branch FETCHES the stored URL as a token-less probe. Still
    # before `create_pending_run`, so a refusal here burns no run row.
    #
    # Returns the dataset because its probe path releases the session
    # across the outbound wait, so the caller must rebind to the re-read
    # instance (used by `dataset.feature_count`, the post-reservation
    # `db.refresh`). `candidate` is NOT recomputed: it stays the
    # pre-check binding, and a rebind during the probe window is exactly
    # what `origin != candidate` catches with 409 after the reservation.
    #
    # `user.id` is captured now since `user` (an `Identity`-satisfying
    # ORM instance in THIS session) also expires on that rollback, and a
    # sync lazy load inside a coroutine raises MissingGreenlet rather
    # than re-querying.
    user_id = user.id
    # fix(#1746): what the PRE-CHECK saw, so the post-reservation recheck
    # can tell a marker that appeared in the window apart from one this
    # guard already adjudicated. Read before the guard, since its ArcGIS
    # path re-reads the row.
    marked_before = service_auth_required(dataset.origin_ref)
    dataset = await _require_service_token_if_marked(
        db, dataset, dataset_id, service_token
    )

    # Refuse a credentialed refresh we cannot carry out, before writing
    # anything. Without a shared store the secret cannot reach the worker at
    # all, and dispatching anyway would produce a `credential_expired` failure
    # an hour later whose real cause is a missing setting.
    if service_token and not credential_store_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "credential_store_unavailable",
                "message": (
                    "Refreshing a protected service needs a shared credential "
                    "store so the token can reach the worker without being "
                    "written to disk. Set REDIS_URL and try again."
                ),
            },
        )

    # fix(#1277): THE ORDERING. This handler used to snapshot the
    # binding then reserve; an in-flight re-upload finishing in between
    # (commit swap, restamp `origin_ref`) left the admission index
    # seeing no active run, so the worker would re-fetch the OLD origin
    # and quietly undo a re-upload that had already succeeded.
    #
    # Fix: read the dispatched binding only once the reservation exists.
    # `_apply_reupload_swap`/`record_refresh_success` commit in ONE
    # transaction, so a non-active run implies its swap is already
    # committed and visible (READ COMMITTED) -- either the other refresh
    # still holds the reservation (refused below, dataset_busy) or its
    # rebind is committed and the re-read below sees it. No third case.
    #
    # Order: (1) eligibility + SSRF on the pre-check binding BEFORE
    # reserving, so cheap refusals skip the index and DNS never resolves
    # under an uncommitted run row; (2) insert job, reserve run; (3)
    # re-read all dispatched state, refusing if the binding moved; (4)
    # fill the job from that; (5) stash the credential; (6) commit, defer.
    # Every refusal from (3) on rolls back the whole request.
    job = IngestJob(
        dataset_id=dataset_id,
        created_by=user_id,
        status="pending",
        # Enough to be a well-formed re-upload job; the source binding is
        # filled in below, from the read that happens after the reservation.
        user_metadata={"reupload": True, "dataset_id": str(dataset_id)},
    )
    db.add(job)
    await db.flush()

    # Admission control and the history row, through the one implementation
    # `reupload_commit` uses. `trigger="api"` names this door; the CLI issue
    # (#1227) passes "cli" through the same function.
    try:
        run = await create_pending_run(
            db,
            dataset_id=dataset_id,
            origin_kind="service",
            trigger="api",
            triggered_by=user_id,
            ingest_job_id=job.id,
            feature_count_before=dataset.feature_count,
        )
    except DatasetBusyError as exc:
        # The job row rolls back with the refusal, so a busy dataset leaves no
        # orphan pending job for the stale sweep to clean up later.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "dataset_busy",
                "message": (
                    "A refresh is already running for this dataset. "
                    "Wait for it to finish, then try again."
                ),
            },
        ) from exc

    # Step 3. `refresh` rather than a second `get_dataset`: the identity map
    # would hand back the instance already loaded above, with the stale
    # attributes intact, and the whole point of this read is to see writes
    # that landed after it.
    await db.refresh(
        dataset, ["origin_uri", "origin_ref", "source_format", "feature_count"]
    )
    try:
        origin = _resolve_service_origin(dataset)
    except HTTPException:
        # Rebound to something unrefreshable while we were reserving — an
        # upload, most likely. Release the reservation before answering.
        await db.rollback()
        raise
    if origin != candidate:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "origin_changed",
                "message": (
                    "This dataset's source changed while the refresh was "
                    "being queued, so it was not started. Check the new "
                    "source and try again."
                ),
            },
        )

    # fix(#1746): the binding can be identical and the answer still
    # different. An authenticated re-upload that landed inside the reservation
    # window marks the dataset without moving its origin, so the check above
    # passes and only this one notices.
    await _recheck_service_token_after_reservation(
        db, dataset, service_token, marked_before=marked_before
    )

    # fix(#1277): read after the reservation too -- an unchanged binding
    # does NOT mean unchanged dispatch state. A re-upload of the same
    # URL/layer leaves origin_ref identical while writing a new job, and
    # `object_id_field` (ArcGIS's paging order key) carried forward
    # stale can silently duplicate or drop features. The binding check
    # can't see that, so every piece of dispatched state is re-read here.
    prior_filename, object_id_field = await _prior_service_ingest_settings(
        db, dataset_id
    )

    # fix(#1277): the credential is judged by the policy the WORKER will
    # apply, selected by the dispatched binding's service type -- done
    # HERE too, after the re-read, since the request model can't know
    # the service type and the pre-check binding isn't guaranteed to be
    # the dispatched one.
    #
    # Header-auth services (WFS, OGC API) pin a bearer token to the
    # base64url charset, since it becomes an Authorization header line
    # through GDAL/libcurl -- an outside character is a header-smuggling
    # primitive. ArcGIS is exempt: its token is a urlencoded query
    # parameter with a legitimately wider vocabulary.
    #
    # Before the stash, so a rejected credential never burns one -- a
    # 202 followed by a deterministic background failure and a spent
    # single-use secret is the whole failure this closes.
    try:
        service_token = wire_credential(credential, service_format=origin.source_format)
    except HTTPException:
        await db.rollback()
        raise

    # Step 4. Refusing on ANY change rather than dispatching the new binding
    # is the deliberate choice: the caller asked to refresh the source they
    # were looking at, the validated URL above is the pre-check one, and a
    # retry against the settled binding succeeds immediately. Dispatching a
    # source nobody has seen would be the surprising outcome.
    job.source_filename = prior_filename or origin.layer_name or str(origin.layer_id)
    job.source_url = origin.base_url
    job.source_layer = origin.layer_name
    job.user_metadata = {
        "reupload": True,
        "dataset_id": str(dataset_id),
        "service_type": origin.service_label,
        "layer_id": origin.layer_id,
        "source_type": "service_url",
        "object_id_field": object_id_field,
        # Records that this job's credential was request-scoped, so a
        # retry cannot reproduce the authenticated fetch. Same marker the
        # commit door writes; the value is a boolean, never the token.
        **({"service_auth_required": True} if service_token else {}),
        # Distinguishes a server-side refresh from a dialog-driven
        # re-upload in the job list, where both are `reupload: True`.
        "refresh": True,
    }
    # Read after the reservation too, for the same reason the binding is: a
    # refresh that finished in the window changed the count this one is
    # measured against, and the history row renders it as the "before".
    run.feature_count_before = dataset.feature_count

    # Stashed before the commit so a store failure rolls the whole request
    # back — no committed job, no reserved run, nothing for the sweep to
    # unwind — rather than leaving a dispatch that can never authenticate.
    # The reverse order leaves a window the other way: a commit that fails
    # after this point strands the credential, which is why the TTL exists
    # and why nothing depends on the discard below actually running.
    credential_ref: str | None = None
    if service_token:
        try:
            credential_ref = await stash_service_credential(service_token)
        except CredentialStoreUnavailable as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "credential_store_unavailable",
                    "message": (
                        "Could not stage the service credential for this "
                        "refresh. Check that the credential store is "
                        "reachable and try again."
                    ),
                },
            ) from exc

    # Snapshotted before the commit. The session is `expire_on_commit=False`
    # so these survive it, but the defer closure runs after the transaction is
    # gone and reading through the instance there is one config change away
    # from a lazy load with no greenlet to run it on.
    job_id = job.id
    attempt_id = job.attempt_id
    run_id = run.id
    await db.commit()

    inner_rollback = make_refresh_run_failed_rollback(
        make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue refresh task"
        ),
        db=db,
        ingest_job_id=job_id,
    )

    async def _rollback(defer_exc: BaseException) -> None:
        await inner_rollback(defer_exc)
        # The worker will never come for it, and the run is already terminal.
        # Best-effort; the TTL is the real guarantee.
        await discard_service_credential(credential_ref)

    async def _defer_refresh() -> None:
        task = get_catalog_port().reupload_service_task()
        await defer_async_with_tenant(
            task,
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            dataset_id=str(dataset_id),
            source_url=origin.base_url,
            source_layer=origin.layer_name,
            user_id=str(user_id),
            # The REFERENCE, never the secret. Task arguments are durable
            # rows; this value means nothing once claimed or expired.
            #
            # fix(#1277): ROLLING-DEPLOY SKEW, accepted. `reupload_service`
            # takes **kwargs, so an old-generation worker accepts this arg
            # and silently discards it, fetching unauthenticated -- the
            # origin refuses and the run fails. The alternative, a task
            # name old workers don't register, is WORSE: Procrastinate
            # marks it FAILED cleanly, but nothing ever writes the ingest
            # job or run, so both sit pending, holding the dataset against
            # the admission index, until the abandoned-run sweep cancels
            # them -- the user sees a refresh that appears to hang.
            # Accepting the skew instead gives a prompt failure
            # (`_looks_like_auth_error` matches the origin's 401/403,
            # releasing the dataset immediately) and the stranded
            # credential expires by TTL, same precedent #1274 set.
            credential_ref=credential_ref,
        )

    await defer_with_orphan_guard(_defer_refresh, rollback=_rollback, db=db, job=job)

    return DatasetRefreshResponse(
        run_id=run_id,
        job_id=job_id,
        dataset_id=dataset_id,
        origin_kind="service",
        trigger="api",
        status="pending",
        message="Refresh queued from the stored source",
    )
