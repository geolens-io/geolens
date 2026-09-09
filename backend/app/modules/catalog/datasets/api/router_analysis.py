"""Dataset analysis endpoints: parameterized PostGIS operations (M4)."""

import re
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import current_tenant_var, defer_async_with_tenant
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.core.tenancy import is_multi_tenant
from app.modules.auth.dependencies import get_current_active_user, require_permission
from app.modules.catalog.authorization import check_dataset_access
from app.modules.catalog.datasets.domain.schemas import (
    MASK_OPERATIONS,
    AnalysisMaterializeRequest,
    AnalysisMaterializeResponse,
    AnalysisPreviewRequest,
    AnalysisPreviewResponse,
)
from app.modules.catalog.datasets.domain.service import (
    get_dataset,
    resolve_source_feature_count,
    run_analysis_preview,
)
from app.modules.quota.service import check_upload_quota
from app.platform.analysis_sql import (
    INTERSECT_OUTPUT_COLUMNS,
    MAX_MASK_LAYER_FEATURES,
    MAX_SOURCE_FEATURES,
    INTERNAL_ALIAS_PREFIX,
    MEASURE_OUTPUT_COLUMNS,
    NON_GROUPABLE_COLUMN_TYPES,
    render_mask_expr,
    spatial_join_output_columns,
)
from app.platform.extensions import get_catalog_port
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)

# fix(#691): the lease window lives beside the heartbeat machinery so the
# per-job status read applies the identical rule.
from app.platform.jobs.heartbeat import (
    ANALYSIS_MATERIALIZE_LEASE_SECONDS as MATERIALIZE_LEASE_SECONDS,
)
from app.platform.jobs.models import IngestJob
from app.platform.sandbox.schemas import SandboxError
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Analysis"], responses=ERROR_RESPONSES_WRITE
)

_SAFE_COLUMN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# fix(#1015): ceiling on active materializes for one tenant, above the
# one-per-user cap rather than replacing it -- a tenant with N users
# could otherwise hold N active CTASes, and #1012's raised per-statement
# work_mem times an unbounded count is the same outage in a new place.
# Three: WORKER_CONCURRENCY=1 default means one running plus two queued,
# the count #1012's work_mem division is sized against. Module constant,
# not a Settings field: nobody has asked to tune it yet (#1013).
MAX_ACTIVE_MATERIALIZES_PER_TENANT = 3

# fix(#766): PostgreSQL has no equality operator for these types, so a
# dissolve GROUP BY on such a column fails the CTAS with an opaque 42883
# after the queue wait. GDAL maps nested GeoJSON objects to `json`, so
# real uploads hit this. Rejected at enqueue with the column named.

# fix(#695): Procrastinate ranks by per-job priority (DESC, default 0),
# not queue name, so a 300s analysis CTAS enqueued first would
# head-of-line block every upload on the shared single worker.
# Below-default priority lets interactive ingest win the fetch. Known
# tradeoff: a steady upload stream can starve queued analysis
# indefinitely -- acceptable for background work (#696 for a budget knob).
ANALYSIS_JOB_PRIORITY = -10


# Sandbox error categories -> HTTP status. Everything else is a sanitized
# 500. query_data_error (SQLSTATE class 22 / GEOS internal errors) is a
# 422 since all SQL here is server-built from validated params, so
# failures are data-driven (e.g. degenerate geometries). Generic
# query_failed stays a 500 -- also covers connection loss and role-binding
# failures, server faults rather than bad requests.
_SANDBOX_STATUS = {
    "query_busy": status.HTTP_429_TOO_MANY_REQUESTS,
    # fix(#1014): server-at-capacity is also a 429, but a distinct
    # category so the message isn't relabelled as the per-user one.
    "query_at_capacity": status.HTTP_429_TOO_MANY_REQUESTS,
    "query_timeout": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "query_data_error": status.HTTP_422_UNPROCESSABLE_CONTENT,
}


async def _load_vector_dataset(db: AsyncSession, dataset_id: uuid.UUID, user: Identity):
    """Fetch + visibility-check a dataset and require it to be vector."""
    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )
    await check_dataset_access(db, dataset, dataset_id, user)
    if not dataset.geometry_type or not dataset.table_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Analysis requires a vector dataset",
        )
    return dataset


_POLYGONAL_TYPES = {"POLYGON", "MULTIPOLYGON"}

# Size-gate ceilings live in app.platform.analysis_sql (shared with the
# worker's pre-CTAS recheck). Counted via resolve_source_feature_count: the
# cached snapshot when present, a LIMIT-bounded live count when it's NULL
# (fix(#701): NULL-as-zero would admit exactly the unknown-size datasets
# these gates exist for).


async def _load_mask_dataset(
    db: AsyncSession, mask_dataset_id: uuid.UUID, user: Identity
):
    """Fetch + visibility-check a mask dataset (Rule 1 applies to BOTH
    datasets of a two-layer operation) and require it to be polygonal --
    unioning points/lines produces a mask that clips nothing meaningful.

    fix(#955): shared with select_by_location, which takes its selection
    geometry from the same mask pair; both ceilings apply unchanged. The
    over-limit message still says "to clip with" -- reads slightly off for
    a selection, but is wired through error-map.ts and five locales.
    """
    dataset = await _load_vector_dataset(db, mask_dataset_id, user)
    if (dataset.geometry_type or "").upper() not in _POLYGONAL_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="mask_dataset_id must reference a polygon dataset",
        )
    mask_count = await resolve_source_feature_count(
        db, dataset, cap=MAX_MASK_LAYER_FEATURES
    )
    if mask_count > MAX_MASK_LAYER_FEATURES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"The mask layer has too many features to clip with "
                f"(limit {MAX_MASK_LAYER_FEATURES:,}). Choose a smaller mask "
                "layer or draw the mask on the map."
            ),
        )
    return dataset


async def _load_join_dataset(
    db: AsyncSession, join_dataset_id: uuid.UUID, user: Identity
):
    """Fetch + visibility-check a spatial-join layer (fix(#953)).

    Rule 1 applies to BOTH datasets, same treatment ``_load_mask_dataset``
    gives the clip mask. No geometry-type requirement, unlike the mask: a
    join is meaningful in every direction (points in polygons, polygons
    touching lines, ...). No size ceiling either: the join layer is probed
    via GIST once per source row, so the SOURCE row count drives the cost,
    which is what MAX_SOURCE_FEATURES['spatial_join'] bounds.
    """
    return await _load_vector_dataset(db, join_dataset_id, user)


def _reject_generated_column_collision(source, generated: Iterable[str]) -> None:
    """422 when the source already has a column an operation would generate.

    Every 1:1 operation's output is the source's own columns verbatim plus
    generated ones, so a same-named source column reaches the CTAS twice
    and fails with an opaque "column specified more than once" after the
    whole queue wait. Named at enqueue instead. Shared form of the guard
    dissolve applies to ``source_count`` (fix(#954): measure and
    spatial_join both need it too).
    """
    source_columns = {col.get("name") for col in (source.column_info or []) if col}
    clashes = sorted(source_columns & set(generated))
    if clashes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"The source dataset already has a column named {clashes[0]!r}, "
                "which this operation would overwrite. Rename it, or choose a "
                "different operation."
            ),
        )


def _validate_join_fields(source, join_dataset, join_fields: list[str]) -> None:
    """422 on unknown join columns, or ones that would collide on output."""
    known = {col.get("name") for col in (join_dataset.column_info or []) if col}
    for name in join_fields:
        if not _SAFE_COLUMN_RE.match(name) or name not in known:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown join column: {name!r}",
            )
    generated = spatial_join_output_columns(join_fields)
    # fix(#1097): generated names must be unique among THEMSELVES first --
    # a join column named `count` prefixes to `join_count`, already
    # generated for the match count, so a source-only check misses the
    # collision. A duplicate check, not "reject `count`": the collision is
    # a property of the generated names, so it still holds if the prefix
    # changes; a repeated field is already rejected by the request schema.
    duplicates = sorted({name for name in generated if generated.count(name) > 1})
    if duplicates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Two transferred columns would both be named {duplicates[0]!r} "
                "in the result. Choose the field once, and rename it in the join "
                "layer if its name collides with a column this operation "
                "generates."
            ),
        )
    _reject_generated_column_collision(source, generated)


def _column_names(dataset) -> set[str]:
    return {col.get("name") for col in (dataset.column_info or []) if col}


def _validate_intersect_columns(source, overlay) -> None:
    """422 on any column an overlay would emit twice (fix(#956)).

    An overlay is the first operation to carry columns from BOTH inputs
    onto every output row, so a same-named column in the two layers is
    likely, not exotic (``name``, ``id``, ``area``). The CTAS would fail
    with an opaque "column specified more than once" after the whole queue
    wait. Silent prefixing is the alternative, and makes the output
    columns unpredictable for anyone scripting against the result.
    """
    _reject_generated_column_collision(source, INTERSECT_OUTPUT_COLUMNS)
    generated = sorted(_column_names(overlay) & set(INTERSECT_OUTPUT_COLUMNS))
    if generated:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"The overlay layer has a column named {generated[0]!r}, which "
                "this operation generates. Rename it, or choose a different "
                "layer."
            ),
        )
    clashes = sorted(_column_names(source) & _column_names(overlay))
    if clashes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Both layers have a column named {clashes[0]!r}, and an "
                "overlay carries columns from both. Rename one of them, or "
                "choose a different layer."
            ),
        )
    # fix(#1097): a carried column may not sit in the alias namespace. Both
    # layers, since an overlay carries columns from both and shares the
    # statement with _gl_src_type and _gl_mask_gid. Checked against the
    # PREFIX, not the alias names, so a later alias is covered for free.
    reserved = sorted(
        name
        for name in (_column_names(source) | _column_names(overlay))
        if name and name.startswith(INTERNAL_ALIAS_PREFIX)
    )
    if reserved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Column {reserved[0]!r} uses the {INTERNAL_ALIAS_PREFIX!r} "
                "prefix, which this operation reserves for its own internal "
                "columns. Rename it, or choose a different layer."
            ),
        )
    # fix(#1099): no ungroupable-type branch here any more. The overlay's
    # attributes used to ride through `_mask_pieces`, named in the
    # aggregate's GROUP BY, which meant json/xml columns took an overlay
    # layer out of service entirely. render_intersect_pairs now groups by
    # the two gids alone and joins the overlay back where no grouping
    # applies, so the column type stops mattering. Dissolve's by_field
    # guard above stays: that one really does group by a user-chosen column.


@router.post("/{dataset_id}/analysis/preview/", response_model=AnalysisPreviewResponse)
async def analysis_preview_endpoint(
    dataset_id: uuid.UUID,
    body: AnalysisPreviewRequest,
    user: Identity = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisPreviewResponse:
    """Run a parameterized PostGIS operation and return a GeoJSON preview.

    Synchronous, read-only, and capped: results are for on-map preview, not
    persistence — use the materialize endpoint to save output as a dataset.
    """
    dataset = await _load_vector_dataset(db, dataset_id, user)
    mask_dataset = (
        await _load_mask_dataset(db, body.mask_dataset_id, user)
        if body.mask_dataset_id is not None
        else None
    )
    join_dataset = None
    if body.join_dataset_id is not None:
        join_dataset = await _load_join_dataset(db, body.join_dataset_id, user)
        # fix(#1097): unconditionally, matching materialize -- the guard
        # used to be `if body.join_fields`, but _validate_join_fields also
        # checks the ALWAYS-generated join_count against source columns, so
        # a source with a join_count column previewed fine and then failed
        # Create on the identical form.
        _validate_join_fields(dataset, join_dataset, body.join_fields or [])
    try:
        return await run_analysis_preview(
            db,
            dataset,
            body,
            user.id,
            mask_dataset=mask_dataset,
            join_dataset=join_dataset,
            # fix(#716): safe here — `user.id` is evaluated above, and neither
            # this handler nor any middleware reads ORM state afterwards.
            release_session=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SandboxError as exc:
        raise HTTPException(
            status_code=_SANDBOX_STATUS.get(
                exc.category, status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=exc.user_message,
        ) from exc


def _validate_dissolve_by_field(dataset, by_field: str) -> None:
    """422 on an unknown, generated-name-conflicting, or non-groupable column."""
    known_columns = {col.get("name"): col for col in (dataset.column_info or []) if col}
    if not _SAFE_COLUMN_RE.match(by_field) or by_field not in known_columns:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown dissolve column: {by_field!r}",
        )
    if by_field == "source_count":
        # The dissolve output already emits a generated source_count
        # column; carrying a same-named group key would fail the CTAS
        # with an opaque "column specified more than once".
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="by_field conflicts with the generated 'source_count' column",
        )
    by_field_type = str(known_columns[by_field].get("type") or "").lower()
    if by_field_type in NON_GROUPABLE_COLUMN_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Column {by_field!r} has type '{by_field_type}' "
                "and can't be used to group features. Choose a column "
                "with comparable values."
            ),
        )


async def _validate_materialize_params(
    db: AsyncSession, dataset, body: AnalysisMaterializeRequest, user: Identity
) -> None:
    """Per-operation enqueue-time validation, so a bad request 422s fast.

    Everything here fails BEFORE a job row exists -- the alternative is a
    job the user watches fail minutes later with an opaque database error.
    Each check has a second, run-time half in the worker, since the queue
    wait sits between the two and the world can move underneath it.
    """
    # fix(#955): select_by_location takes the same mask pair clip does, so
    # it takes the same two checks. Rule 1 applies to BOTH datasets either way.
    if body.operation in MASK_OPERATIONS and body.mask_dataset_id is not None:
        # Access + polygon checks happen here at enqueue time; the worker
        # re-resolves the table name and re-validates it against _SAFE_TABLE.
        await _load_mask_dataset(db, body.mask_dataset_id, user)
    elif body.operation in MASK_OPERATIONS:
        try:
            render_mask_expr(body.mask or {})
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
    if body.operation == "dissolve" and body.by_field is not None:
        _validate_dissolve_by_field(dataset, body.by_field)
    if body.operation == "spatial_join":
        # Access + column checks, same as the clip mask; the worker re-resolves
        # the table name and re-checks the collision against the live columns.
        join_dataset = await _load_join_dataset(db, body.join_dataset_id, user)
        _validate_join_fields(dataset, join_dataset, body.join_fields or [])
    if body.operation == "measure":
        _reject_generated_column_collision(dataset, MEASURE_OUTPUT_COLUMNS)
    if body.operation == "intersect":
        # Access check on the overlay layer, plus the column checks. Rule 1
        # applies to BOTH datasets; the worker re-resolves the table and
        # re-checks the collisions against the live columns after the queue.
        overlay = await _load_mask_dataset(db, body.mask_dataset_id, user)
        _validate_intersect_columns(dataset, overlay)


def _build_analysis_job_metadata(
    body: AnalysisMaterializeRequest, dataset
) -> dict[str, Any]:
    """The params recorded on the job so Admin -> Jobs can diagnose a run.

    "analysis-buffer failed" on its own says nothing. The drawn mask
    geometry is deliberately NOT stored: it can be kilobytes, and a marker
    suffices.

    Extracted from the handler (#1097): this per-operation dispatch block
    grows with every new operation and tripped ruff's C901 threshold at
    the fourth one. Nothing here touches the request, session, or job row,
    so it lifts out whole.
    """
    meta: dict[str, Any] = {
        "operation": body.operation,
        "source_dataset_id": str(dataset.id),
        "title": body.title,
    }
    if body.distance_meters is not None:
        meta["distance_meters"] = body.distance_meters
    if body.by_field is not None:
        meta["by_field"] = body.by_field
    # fix(#1097): the second layer is recorded for EVERY operation that
    # consumes one, not just clip, so a failed run stays diagnosable.
    # mask_source stays scoped to operations that can take a DRAWN mask;
    # intersect rejects one, so "layer" there would be a constant.
    if body.mask_dataset_id is not None:
        meta["mask_dataset_id"] = str(body.mask_dataset_id)
    if body.operation in MASK_OPERATIONS:
        meta["mask_source"] = "layer" if body.mask_dataset_id else "drawn"
    if body.operation == "spatial_join":
        meta["join_dataset_id"] = str(body.join_dataset_id)
        if body.join_fields:
            meta["join_fields"] = list(body.join_fields)
    return meta


@router.post(
    "/{dataset_id}/analysis/materialize/",
    response_model=AnalysisMaterializeResponse,
)
async def analysis_materialize_endpoint(
    dataset_id: uuid.UUID,
    body: AnalysisMaterializeRequest,
    request: Request,
    # fix(#692): materialize creates a dataset, so it carries the same
    # permission as every ingest endpoint. It also hands the caller a
    # durable, caller-owned copy of the source attributes (a centroid
    # preserves every column), the outcome download endpoints gate on
    # `export`, so it requires that too. Preview stays on the plain
    # active-user dependency: read-only, and the chat tool depends on it.
    user: Identity = Depends(require_permission("upload", "export")),
    db: AsyncSession = Depends(get_db),
) -> AnalysisMaterializeResponse:
    """Materialize an analysis result as a new private dataset (async job).

    Requires the ``upload`` and ``export`` permissions (this endpoint
    creates a dataset that carries the source's attributes) and read
    visibility on the source dataset; the new dataset is owned by the
    caller and counted against their dataset quota (the atomic slot
    reservation runs at registration inside the worker). Poll
    ``GET /jobs/{job_id}`` for progress.
    """
    dataset = await _load_vector_dataset(db, dataset_id, user)

    max_features = MAX_SOURCE_FEATURES.get(body.operation)
    if max_features is not None:
        source_count = await resolve_source_feature_count(db, dataset, cap=max_features)
        if source_count > max_features:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"This dataset is too large for {body.operation} "
                    f"(the limit is {max_features:,} features). Filter it "
                    "to a smaller dataset first."
                ),
            )

    await _validate_materialize_params(db, dataset, body, user)

    # Best-effort dataset-count pre-check; the authoritative atomic
    # reservation happens at registration time in the worker.
    await check_upload_quota(db, user.id, 0, request)

    # One materialize at a time per user: each queued job is an
    # unbounded-ish CTAS. Soft cap: a TOCTOU race can briefly admit two;
    # add a DB-side partial unique index for a hard guarantee.
    #
    # fix(#691): the slot is held on a heartbeat LEASE, not job status --
    # the worker renews heartbeat_at every 30s, so a stale lease on a
    # "running" job means a hard-killed worker, and the slot releases
    # rather than waiting for the 60-min JOB_TIMEOUT_SECONDS backstop.
    # Elapsed time alone was tried and reverted (#682): a legitimate
    # materialize can outlive any window.
    #
    # The pending branch MUST stay status-only: a pending job is never
    # claimed, so heartbeat_at/started_at are both NULL, and a cutoff
    # comparison would drop it from the count, defeating the cap.
    # coalesce(heartbeat_at, started_at) covers pre-heartbeat rows. The
    # client applies no staleness rule of its own (AnalysisJobWatcher.tsx)
    # -- a released lease just lets the next create succeed server-side.
    #
    # fix(#1015): serialize admission per tenant before counting, or the
    # caps are check-then-insert -- N users could all read a count below
    # the ceiling and all create a job, ending up over it. A
    # transaction-scoped advisory lock held until commit makes
    # count-then-create atomic. Blocking, not pg_try_advisory_xact_lock:
    # admissions should queue for the microseconds this takes, not fail.
    # In single-tenant mode the key is constant, correctly serializing
    # every admission on the deployment (and incidentally hardening the
    # soft per-user cap above).
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:admission_key, 0))"),
        {
            "admission_key": (
                f"geolens:analysis-admission:{current_tenant_var.get()}"
                if is_multi_tenant()
                else "geolens:analysis-admission"
            )
        },
    )

    lease_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=MATERIALIZE_LEASE_SECONDS
    )
    # fix(#1015): the liveness rule is shared by both caps, applying
    # identically at tenant scope.
    active_predicate = (
        # fix(#682): the analysis marker in user_metadata, NOT
        # source_filename -- an upload named "analysis-data.geojson" would
        # otherwise lock the uploader out of analysis. Written in the same
        # transaction as the job row, so this never misses one.
        IngestJob.user_metadata.has_key("analysis"),
        or_(
            IngestJob.status == "pending",
            and_(
                IngestJob.status == "running",
                func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                >= lease_cutoff,
            ),
        ),
    )
    active = await db.scalar(
        select(func.count())
        .select_from(IngestJob)
        .where(IngestJob.created_by == user.id, *active_predicate)
    )
    if active:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="An analysis job is already running; wait for it to finish",
        )

    # fix(#1015): tenant ceiling above the per-user cap. In single-tenant
    # mode there's one tenant by definition, so the unfiltered count IS the
    # tenant's. IngestJob.tenant_id is already indexed
    # (ix_catalog_ingest_jobs_tenant_id), so the multi-tenant filter needs
    # no schema work.
    tenant_stmt = select(func.count()).select_from(IngestJob).where(*active_predicate)
    if is_multi_tenant():
        tenant_stmt = tenant_stmt.where(IngestJob.tenant_id == current_tenant_var.get())
    tenant_active = await db.scalar(tenant_stmt)
    if tenant_active and tenant_active >= MAX_ACTIVE_MATERIALIZES_PER_TENANT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Your organization already has "
                f"{MAX_ACTIVE_MATERIALIZES_PER_TENANT} analysis jobs running or "
                "queued; wait for one to finish"
            ),
        )

    job = await get_catalog_port().create_ingest_job(
        db, f"analysis-{body.operation}", "", user.id
    )
    job.user_metadata = {"analysis": _build_analysis_job_metadata(body, dataset)}
    # ux(#698): stamp a step so a pending job reads as "queued" rather than
    # indistinguishable from a broken one -- matters more since analysis
    # deliberately defers below default priority (#703) and can wait
    # behind uploads for minutes. Free-form String(32).
    job.current_step = "queued"
    await db.commit()

    rollback = make_ingest_job_failed_rollback(
        job, message_prefix="Failed to queue analysis task"
    )

    async def _defer() -> None:
        # mask_dataset_id rides along only when set: a worker still running
        # pre-clip-by-layer code rejects unknown kwargs, and an
        # unconditional None would break EVERY materialize during a
        # rolling deploy instead of only the new feature.
        extra_kwargs: dict[str, object] = {}
        if body.mask_dataset_id is not None:
            extra_kwargs["mask_dataset_id"] = str(body.mask_dataset_id)
        # Same rolling-deploy rule for the join params (fix(#953)).
        if body.join_dataset_id is not None:
            extra_kwargs["join_dataset_id"] = str(body.join_dataset_id)
            if body.join_fields:
                extra_kwargs["join_fields"] = list(body.join_fields)
        await defer_async_with_tenant(
            get_catalog_port()
            .materialize_analysis_task()
            .configure(priority=ANALYSIS_JOB_PRIORITY),
            job_id=str(job.id),
            dataset_id=str(dataset.id),
            user_id=str(user.id),
            operation=body.operation,
            title=body.title,
            distance_meters=body.distance_meters,
            mask=body.mask,
            by_field=body.by_field,
            **extra_kwargs,
        )

    await defer_with_orphan_guard(_defer, rollback=rollback, db=db, job=job)

    return AnalysisMaterializeResponse(job_id=job.id, status="pending")
