"""One-request refresh of a dataset from its stored origin binding.

feat(#1220) / ADR-002 Decisions 5a, 5b, 5c and 6. Re-pulling a service dataset
used to mean walking the re-upload dialog: preview with the URL in the request
body, re-pick the layer, then commit. Every one of those steps asks the client
to restate something the catalog already knows, and each restatement is a
chance to state it differently — a dataset could be silently re-pointed at a
new source through a door whose name says "re-upload the same thing".

This door reads the pointer instead. The request body carries no URL, no
service type, and no layer: they come from ``origin_ref``, which ingest wrote
and only ingest writes. The one thing a client may supply is a transient
credential, and it does not reach durable storage either (see
``platform/refresh/credentials.py``).

Separate module rather than more of ``router_reupload.py`` for two reasons
that are really one: that file is already the largest in the api package and
sits at an exact size cap, and this endpoint shares almost nothing with the
preview/commit pair beyond two helpers it imports. The shared machinery that
matters — admission control, the run row, the worker — is deliberately the
SAME (handoff invariant 11): this handler calls ``create_pending_run`` exactly
as ``reupload_commit`` does and dispatches the same ``reupload_service`` task.
A second admission path is how one of them ends up with a rule the other
lacks.
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
from app.modules.catalog.sources.security import SSRFError, validate_url_for_ssrf
from app.platform.dataset_origin import classify_origin
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

    ``layer_id`` and ``layer_name`` are mutually exclusive by service type,
    which is not this module's choice: ``build_gdal_source`` requires the
    numeric id for ArcGIS and ignores the name, and passes the name to GDAL
    for WFS and OGC API while ignoring the id. ``origin_ref`` stores whichever
    one addresses the layer under the single key ``layer_id``, so unpacking it
    into the right slot happens here, once — and the worker's
    ``service_layer_identity`` call folds it back to the same stored value
    when it re-writes the binding after a successful swap. That round trip is
    what keeps a refresh from slowly rewriting the pointer it refreshed from.
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
    has no origin to re-pull from (an upload, a drawn layer, a registered
    table), and ``origin_unavailable`` means it does but GeoLens never
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
    return _ServiceOrigin(
        source_format=stored_format or "",
        service_label=service_label,
        base_url=base_url,
        layer_id=None,
        layer_name=str(layer_identity),
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

    Refuses with 409 ``dataset_busy`` while another refresh or re-upload is
    active for this dataset — v1 rejects rather than queues (Decision 5b), and
    the refusal comes from a partial unique index rather than a check, so two
    simultaneous clicks cannot both be admitted.
    """
    body = request or DatasetRefreshRequest()

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    # Rule 1: this endpoint replaces the dataset's data.
    await check_dataset_write_access(db, dataset, dataset_id, user)

    # Record-type eligibility is not checked separately here, deliberately.
    # `classify_origin` already returns None for the two originless record
    # types (a collection has no dataset row of its own, a VRT is composed
    # from other datasets), and `refresh_not_applicable` is the honest answer
    # for both. The re-upload door's record-type guard exists to explain a
    # cross-record-type file swap, and its wording says "reupload" — reusing
    # it here would answer a refresh with advice about a different feature.
    origin = _resolve_service_origin(dataset)

    # Rule 2: the URL is ours, but "ours" is not a safety property — it was a
    # client's when ingest stored it, and DNS moves. Revalidating at dispatch
    # matches what the preview door does with a fresh URL; the worker
    # revalidates again at fetch time for the window in between.
    try:
        await validate_url_for_ssrf(origin.base_url)
    except SSRFError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This dataset's stored source URL is not reachable: {exc}",
        ) from exc

    # Refuse a credentialed refresh we cannot carry out, before writing
    # anything. Without a shared store the secret cannot reach the worker at
    # all, and dispatching anyway would produce a `credential_expired` failure
    # an hour later whose real cause is a missing setting.
    if body.token and not credential_store_available():
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

    prior_filename, object_id_field = await _prior_service_ingest_settings(
        db, dataset_id
    )

    job = IngestJob(
        dataset_id=dataset_id,
        source_filename=prior_filename or origin.layer_name or str(origin.layer_id),
        source_url=origin.base_url,
        source_layer=origin.layer_name,
        created_by=user.id,
        status="pending",
        user_metadata={
            "reupload": True,
            "dataset_id": str(dataset_id),
            "service_type": origin.service_label,
            "layer_id": origin.layer_id,
            "source_type": "service_url",
            "object_id_field": object_id_field,
            # Records that this job's credential was request-scoped, so a
            # retry cannot reproduce the authenticated fetch. Same marker the
            # commit door writes; the value is a boolean, never the token.
            **({"service_auth_required": True} if body.token else {}),
            # Distinguishes a server-side refresh from a dialog-driven
            # re-upload in the job list, where both are `reupload: True`.
            "refresh": True,
        },
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
            triggered_by=user.id,
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

    # Stashed before the commit so a store failure rolls the whole request
    # back — no committed job, no reserved run, nothing for the sweep to
    # unwind — rather than leaving a dispatch that can never authenticate.
    # The reverse order leaves a window the other way: a commit that fails
    # after this point strands the credential, which is why the TTL exists
    # and why nothing depends on the discard below actually running.
    credential_ref: str | None = None
    if body.token:
        try:
            credential_ref = await stash_service_credential(body.token)
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
        await defer_async_with_tenant(
            get_catalog_port().reupload_service_task(),
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            dataset_id=str(dataset_id),
            source_url=origin.base_url,
            source_layer=origin.layer_name,
            user_id=str(user.id),
            # The REFERENCE, never the secret. Task arguments are durable rows
            # in PostgreSQL and a failed job keeps them until retention runs;
            # this value means nothing once claimed or expired.
            credential_ref=credential_ref,
        )

    await defer_with_orphan_guard(_defer_refresh, rollback=_rollback, db=db)

    return DatasetRefreshResponse(
        run_id=run_id,
        job_id=job_id,
        dataset_id=dataset_id,
        origin_kind="service",
        trigger="api",
        status="pending",
        message="Refresh queued from the stored source",
    )
