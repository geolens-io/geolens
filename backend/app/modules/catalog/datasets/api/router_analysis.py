"""Dataset analysis endpoints: parameterized PostGIS operations (M4)."""

import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_session import defer_async_with_tenant
from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import get_current_active_user, require_permission
from app.modules.catalog.authorization import check_dataset_access
from app.modules.catalog.datasets.domain.schemas import (
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
    MAX_MASK_LAYER_FEATURES,
    MAX_SOURCE_FEATURES,
    render_mask_expr,
)
from app.platform.extensions import get_catalog_port
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)
from app.platform.jobs.models import IngestJob
from app.platform.sandbox.schemas import SandboxError
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/datasets", tags=["Datasets - Analysis"], responses=ERROR_RESPONSES_WRITE
)

_SAFE_COLUMN_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# fix(#766): PostgreSQL has no equality operator for these types, so a
# dissolve GROUP BY on such a column fails the CTAS with an opaque 42883
# after the queue wait. GDAL maps nested GeoJSON objects to `json`, so
# real uploads hit this. Rejected at enqueue with the column named.
_NON_GROUPABLE_TYPES = {"json", "xml"}

# fix(#695): Procrastinate ranks by per-job priority (DESC, default 0), not
# by queue name — so a 300-second analysis CTAS enqueued first would
# head-of-line block every upload on the shared single worker. Below-default
# priority lets interactive ingest win the fetch whenever both are queued.
# Known tradeoff: a steady upload stream can starve queued analysis
# indefinitely — acceptable for background work; a per-op budget knob is
# #696's scope.
ANALYSIS_JOB_PRIORITY = -10

# fix(#691): lease window for the per-user materialize cap. The worker renews
# heartbeat_at every HEARTBEAT_INTERVAL_SECONDS (30s, platform/jobs/
# heartbeat.py); 3x tolerates two missed renewals before declaring the worker
# dead — generous against transient DB slowness while still releasing the slot
# in under two minutes instead of the 60-minute JOB_TIMEOUT_SECONDS backstop.
# Module-level constant on purpose: promoting it to Settings is #696's scope.
MATERIALIZE_LEASE_SECONDS = 90

# Sandbox error categories → HTTP status. Everything else is a sanitized 500.
# query_data_error (SQLSTATE class 22 / GEOS internal errors) is a 422: all
# SQL on this path is server-built from validated params, so those failures
# are data-driven (e.g. degenerate geometries). Generic query_failed stays a
# 500 — it also covers connection loss, tenant-context and role-binding
# failures, which are server faults, not bad requests.
_SANDBOX_STATUS = {
    "query_busy": status.HTTP_429_TOO_MANY_REQUESTS,
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
    """Fetch + visibility-check a clip-mask dataset (Rule 1 applies to BOTH
    datasets of a two-layer operation) and require it to be polygonal —
    unioning points/lines produces a mask that clips nothing meaningful."""
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
    try:
        return await run_analysis_preview(
            db,
            dataset,
            body,
            user.id,
            mask_dataset=mask_dataset,
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
    if by_field_type in _NON_GROUPABLE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Column {by_field!r} has type '{by_field_type}' "
                "and can't be used to group features. Choose a column "
                "with comparable values."
            ),
        )


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

    # Fail fast on invalid params before creating a job.
    if body.operation == "clip" and body.mask_dataset_id is not None:
        # Access + polygon checks happen here at enqueue time; the worker
        # re-resolves the table name and re-validates it against _SAFE_TABLE.
        await _load_mask_dataset(db, body.mask_dataset_id, user)
    elif body.operation == "clip":
        try:
            render_mask_expr(body.mask or {})
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
            ) from exc
    if body.operation == "dissolve" and body.by_field is not None:
        _validate_dissolve_by_field(dataset, body.by_field)

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
    lease_cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=MATERIALIZE_LEASE_SECONDS
    )
    active = await db.scalar(
        select(func.count())
        .select_from(IngestJob)
        .where(
            IngestJob.created_by == user.id,
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
    )
    if active:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="An analysis job is already running; wait for it to finish",
        )

    job = await get_catalog_port().create_ingest_job(
        db, f"analysis-{body.operation}", "", user.id
    )
    # Record the request params so Admin → Jobs can diagnose a failed run
    # ("analysis-buffer failed" alone says nothing). The drawn mask geometry
    # is deliberately NOT stored — it can be kilobytes; a marker suffices.
    analysis_meta = {
        "operation": body.operation,
        "source_dataset_id": str(dataset.id),
        "title": body.title,
    }
    if body.distance_meters is not None:
        analysis_meta["distance_meters"] = body.distance_meters
    if body.by_field is not None:
        analysis_meta["by_field"] = body.by_field
    if body.operation == "clip":
        analysis_meta["mask_source"] = "layer" if body.mask_dataset_id else "drawn"
        if body.mask_dataset_id is not None:
            analysis_meta["mask_dataset_id"] = str(body.mask_dataset_id)
    job.user_metadata = {"analysis": analysis_meta}
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
        extra_kwargs = (
            {"mask_dataset_id": str(body.mask_dataset_id)}
            if body.mask_dataset_id is not None
            else {}
        )
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

    await defer_with_orphan_guard(_defer, rollback=rollback, db=db)

    return AnalysisMaterializeResponse(job_id=job.id, status="pending")
