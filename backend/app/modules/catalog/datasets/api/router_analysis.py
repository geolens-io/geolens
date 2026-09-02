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
# per-job status read applies the identical rule — see the rationale on the
# constant itself.
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
# one-per-user cap rather than replacing it. The two answer different
# questions — "are you already running one?" and "is your organisation using
# more than its share?" — so both stay, with 429 details that say which was
# hit.
#
# Why a tenant needs its own ceiling: the per-user cap lets a tenant with N
# users hold N active CTASes, and #1012 raises the per-statement work_mem that
# each of those would claim. A raised ceiling times an unbounded count is the
# same outage in a new place.
#
# Three: with the default WORKER_CONCURRENCY of 1 that is one running plus two
# queued, so a single tenant cannot monopolise the queue while still being able
# to line work up. On a deployment that raises WORKER_CONCURRENCY it bounds
# genuinely concurrent CTASes to three per tenant, which is the count #1012's
# work_mem division is sized against.
#
# A module constant, not a Settings field, for the same reason as the ingest
# caps: four surfaces for a limit nobody has asked to tune yet. #1013 is the
# issue that establishes the promotion pattern.
MAX_ACTIVE_MATERIALIZES_PER_TENANT = 3

# fix(#766): PostgreSQL has no equality operator for these types, so a
# dissolve GROUP BY on such a column fails the CTAS with an opaque 42883
# after the queue wait. GDAL maps nested GeoJSON objects to `json`, so
# real uploads hit this. Rejected at enqueue with the column named.

# fix(#695): Procrastinate ranks by per-job priority (DESC, default 0), not
# by queue name — so a 300-second analysis CTAS enqueued first would
# head-of-line block every upload on the shared single worker. Below-default
# priority lets interactive ingest win the fetch whenever both are queued.
# Known tradeoff: a steady upload stream can starve queued analysis
# indefinitely — acceptable for background work; a per-op budget knob is
# #696's scope.
ANALYSIS_JOB_PRIORITY = -10


# Sandbox error categories → HTTP status. Everything else is a sanitized 500.
# query_data_error (SQLSTATE class 22 / GEOS internal errors) is a 422: all
# SQL on this path is server-built from validated params, so those failures
# are data-driven (e.g. degenerate geometries). Generic query_failed stays a
# 500 — it also covers connection loss, tenant-context and role-binding
# failures, which are server faults, not bad requests.
_SANDBOX_STATUS = {
    "query_busy": status.HTTP_429_TOO_MANY_REQUESTS,
    # fix(#1014): server-at-capacity is also a 429, but a distinct category so
    # the message is not relabelled as the per-user one.
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
# cached snapshot when present, a LIMIT-bounded live count when it is NULL
# (fix(#701 review): NULL-as-zero would admit exactly the unknown-size
# datasets these gates exist for).


async def _load_mask_dataset(
    db: AsyncSession, mask_dataset_id: uuid.UUID, user: Identity
):
    """Fetch + visibility-check a mask dataset (Rule 1 applies to BOTH
    datasets of a two-layer operation) and require it to be polygonal —
    unioning points/lines produces a mask that clips nothing meaningful.

    fix(#955): shared with select_by_location, which takes its selection
    geometry from the same mask pair. Both ceilings apply there unchanged; the
    over-limit message still says "to clip with", which reads slightly off for
    a selection but is wired through error-map.ts and four locales, so it is
    left alone rather than half-changed.
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

    Rule 1 applies to BOTH datasets of a two-layer operation, so this is the
    same treatment ``_load_mask_dataset`` gives the clip mask. No geometry-type
    requirement, unlike the mask: a join is meaningful in every direction —
    points in polygons, polygons touching lines, polygons overlapping polygons
    — and the count means the same thing in all of them. No size ceiling of its
    own either: the join layer is probed through its GIST index once per source
    row, so it is the SOURCE row count that drives the cost, and that is what
    MAX_SOURCE_FEATURES['spatial_join'] bounds.
    """
    return await _load_vector_dataset(db, join_dataset_id, user)


def _reject_generated_column_collision(source, generated: Iterable[str]) -> None:
    """422 when the source already has a column an operation would generate.

    Every 1:1 operation's output is the source's own columns verbatim plus its
    generated ones, so a source column of the same name reaches the CTAS twice
    and fails it with an opaque "column specified more than once" — after the
    whole queue wait. Named at enqueue instead. This is the shared form of the
    guard dissolve applies to ``source_count`` in ``_validate_dissolve_by_field``
    (fix(#954): measure and spatial_join both need it, so it lives in one place
    rather than being re-derived per operation).
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
    # fix(#1097 review): the generated names must be unique among THEMSELVES
    # before they are checked against the source. A join layer with an ordinary
    # column named `count` prefixes to `join_count`, the name this operation
    # already generates for the match count — so the list holds it twice while
    # the guard below, which only compares against the SOURCE, sees nothing
    # wrong. Materialization then failed the CTAS with "column specified more
    # than once" after the whole queue wait, and the preview was worse: it maps
    # both values onto one property, so the transferred field silently
    # overwrote the real match count.
    #
    # Written as a duplicate check rather than as "reject the field named
    # `count`" because the collision is a property of the generated names, not
    # of that one input: a change to the prefix or to the generated set moves
    # which field collides, and this keeps holding. The other way a name can
    # repeat, the same field requested twice, is already rejected by
    # AnalysisMaterializeRequest and never reaches here.
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

    An overlay is the first operation to carry columns from BOTH inputs onto
    every output row, so a same-named column in the two layers is likely
    rather than exotic — ``name``, ``id`` and ``area`` are all common. The CTAS
    would fail it with an opaque "column specified more than once" after the
    whole queue wait. Prefixing silently is the alternative, and it makes the
    output columns unpredictable for anyone scripting against the result.
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
    # fix(#1097 review): a carried column may not sit in the alias namespace.
    # Both layers, because an overlay carries columns from both and they share
    # the statement with _gl_src_type and _gl_mask_gid. Checked against the
    # PREFIX rather than the alias names, so an alias added to that query later
    # is covered without a second place to update.
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
    # attributes used to ride through `_mask_pieces` and get named in the
    # aggregate's GROUP BY, which meant json and xml — the types nested GeoJSON
    # properties routinely land as — took an overlay layer out of service
    # entirely. render_intersect_pairs groups by the two gids alone now and
    # joins the overlay table back afterwards, where no grouping applies, so the
    # column type stops mattering. Dissolve's by_field guard above stays: that
    # one really does group by a user-chosen column.


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
        # fix(#1097 review): unconditionally, matching materialize. The guard
        # used to be `if body.join_fields`, but _validate_join_fields also
        # checks the ALWAYS-generated join_count against the source's columns —
        # so a source that already had a join_count column previewed fine and
        # then failed Create on the identical form. Preview approving an output
        # that Create refuses is worse than either verdict on its own.
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

    Everything here fails BEFORE a job row exists — the alternative is a job
    the user has to watch fail minutes later with an opaque database error.
    Each check has a second, run-time half in the worker, because the queue
    wait sits between the two and the world can move underneath it.
    """
    # fix(#955): select_by_location takes the same mask pair clip does, so it
    # takes the same two checks. Rule 1 applies to BOTH datasets either way.
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

    "analysis-buffer failed" on its own says nothing. The drawn mask geometry
    is deliberately NOT stored: it can be kilobytes, and a marker suffices.

    Extracted from the handler rather than left inline (#1097 review): this is
    the per-operation dispatch, so it is the block that grows every time an
    operation is added, and it took the endpoint past ruff's C901 threshold at
    the fourth one. Inline, the next operation would trip the same rule again
    and the fix would be the same extraction done under more pressure. Nothing
    here touches the request, the session, or the job row, so it lifts out
    whole.
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
    # fix(#1097 review): the second layer is recorded for EVERY operation that
    # consumes one, not just clip. Admin Jobs surfaces this metadata to
    # diagnose a failed run, and select_by_location and intersect are both
    # driven by a layer the operator could not otherwise identify — so a failure
    # caused by that layer (re-uploaded mid-queue, wrong geometry, ungroupable
    # column) showed only the operation, the source and the title.
    #
    # mask_source stays scoped to the operations that can take a DRAWN mask.
    # intersect rejects one, so "layer" there would be a constant dressed up as
    # a discriminator.
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
    # permission as every ingest endpoint that creates one. It also hands the
    # caller a durable, caller-owned copy of the source attributes (a
    # centroid materialize preserves every column), which is the outcome the
    # download endpoints gate on `export` — so it requires that capability
    # too, keeping the two paths consistent under a customized role matrix.
    # Preview stays on the plain active-user dependency: it is read-only,
    # persists nothing, and the chat tool's read-only surface depends on it.
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

    # One materialize at a time per user: each queued job is an unbounded-ish
    # CTAS, so without a cap one user can stack N of them. Soft cap: a TOCTOU
    # race can briefly admit two; add a DB-side partial unique index if
    # operators need a hard guarantee.
    #
    # fix(#691): the slot is held on a heartbeat LEASE, not job status alone.
    # The worker claims the job and renews heartbeat_at every 30s (#682/#700),
    # so a running job whose lease has gone stale means a hard-killed worker
    # (SIGKILL/OOM) — release the slot instead of waiting for the 60-minute
    # JOB_TIMEOUT_SECONDS backstop to fail the row. Elapsed time alone was
    # tried and reverted (#682 review): a legitimate materialize can outlive
    # any useful window, and enqueue-relative age is wrong for queued jobs.
    #
    # The pending branch MUST stay status-only: a pending job has never been
    # claimed, so heartbeat_at and started_at are both NULL and any cutoff
    # comparison would silently drop it from the count — letting a user stack
    # unbounded queued CTASes, defeating the cap while passing every test.
    # coalesce(heartbeat_at, started_at) covers pre-heartbeat rows that only
    # carry started_at.
    #
    # The client deliberately applies no staleness rule of its own
    # (AnalysisJobWatcher.tsx): it mirrors job status from the API, and on a
    # released lease the next create attempt simply succeeds server-side.
    # fix(#1015): serialize admission per tenant before counting anything.
    # Without it the caps are check-then-insert: N users in one tenant can all
    # read a count below the ceiling, then all create a job, and the tenant
    # ends up over by however many callers arrived together — precisely the
    # unbounded-concurrency case the ceiling exists to stop, and the one #1012's
    # raised work_mem makes expensive. A transaction-scoped advisory lock held
    # until this request commits makes the count-then-create sequence atomic.
    #
    # Blocking rather than pg_try_advisory_xact_lock (the sandbox's shape at
    # executor.py): concurrent admissions should queue for the microseconds this
    # takes, not fail. The critical section is a COUNT and an INSERT.
    #
    # In single-tenant mode the key is constant, so this serializes every
    # analysis admission on the deployment. That is the correct reading — there
    # is one tenant — and admissions are rare and short. It also incidentally
    # hardens the per-user cap below, which the comment there describes as soft.
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
    # fix(#1015): the liveness rule is shared by both caps rather than
    # reinvented for the tenant one. All three properties documented above are
    # load-bearing and apply identically at tenant scope.
    active_predicate = (
        # fix(#682 review): the analysis marker in user_metadata, NOT
        # source_filename — uploads copy the user's own filename into that
        # column, so an upload named "analysis-data.geojson" would lock the
        # uploader out of analysis. The metadata below is written in the
        # same transaction as the job row, so this never misses one.
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

    # fix(#1015): the tenant ceiling above the per-user cap. In single-tenant
    # mode there is one tenant by definition, so the unfiltered count IS the
    # tenant's — which also avoids depending on whether the database stamps
    # tenant_id as NULL or as a fixed value there. IngestJob.tenant_id is
    # already indexed (ix_catalog_ingest_jobs_tenant_id), so the multi-tenant
    # filter needs no schema work.
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
    # being indistinguishable from a broken one. This matters more since #703
    # deliberately defers analysis below the default priority — a queued job
    # now waits behind uploads by design, sometimes for minutes. The column is
    # a free-form String(32).
    job.current_step = "queued"
    await db.commit()

    rollback = make_ingest_job_failed_rollback(
        job, message_prefix="Failed to queue analysis task"
    )

    async def _defer() -> None:
        # mask_dataset_id rides along only when set: a worker still running
        # the pre-clip-by-layer code rejects unknown kwargs, and an
        # unconditional None would break EVERY materialize during a rolling
        # deploy instead of only the new feature.
        extra_kwargs: dict[str, object] = {}
        if body.mask_dataset_id is not None:
            extra_kwargs["mask_dataset_id"] = str(body.mask_dataset_id)
        # Same rolling-deploy rule for the join params (fix(#953)): a worker
        # still running pre-spatial-join code rejects unknown kwargs, so they
        # ride along only when the operation actually uses them.
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
