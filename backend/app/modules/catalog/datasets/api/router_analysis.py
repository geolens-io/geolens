"""Dataset analysis endpoints: parameterized PostGIS operations (M4)."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
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
    run_analysis_preview,
)
from app.modules.quota.service import check_upload_quota
from app.platform.analysis_sql import render_mask_expr
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
            db, dataset, body, user.id, mask_dataset=mask_dataset
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


@router.post(
    "/{dataset_id}/analysis/materialize/",
    response_model=AnalysisMaterializeResponse,
)
async def analysis_materialize_endpoint(
    dataset_id: uuid.UUID,
    body: AnalysisMaterializeRequest,
    request: Request,
    # fix(#692): materialize creates a dataset, so it carries the same
    # permission as every ingest endpoint that creates one. Preview stays on
    # the plain active-user dependency: it is read-only, persists nothing,
    # and the chat tool's read-only surface depends on it.
    user: Identity = Depends(require_permission("upload")),
    db: AsyncSession = Depends(get_db),
) -> AnalysisMaterializeResponse:
    """Materialize an analysis result as a new private dataset (async job).

    Requires the ``upload`` permission (this endpoint creates a dataset) and
    read visibility on the source dataset; the new dataset is owned by the
    caller and counted against their dataset quota (the atomic slot
    reservation runs at registration inside the worker). Poll
    ``GET /jobs/{job_id}`` for progress.
    """
    dataset = await _load_vector_dataset(db, dataset_id, user)

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
        known_columns = {col.get("name") for col in (dataset.column_info or []) if col}
        if (
            not _SAFE_COLUMN_RE.match(body.by_field)
            or body.by_field not in known_columns
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown dissolve column: {body.by_field!r}",
            )
        if body.by_field == "source_count":
            # The dissolve output already emits a generated source_count
            # column; carrying a same-named group key would fail the CTAS
            # with an opaque "column specified more than once".
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="by_field conflicts with the generated 'source_count' column",
            )

    # Best-effort dataset-count pre-check; the authoritative atomic
    # reservation happens at registration time in the worker.
    await check_upload_quota(db, user.id, 0, request)

    # One materialize at a time per user: each queued job is an unbounded-ish
    # CTAS, so without a cap one user can stack N of them. ponytail: soft cap —
    # a TOCTOU race can briefly admit two; add a DB-side partial unique index if
    # operators need a hard guarantee.
    #
    # Any pending-or-running job blocks, with NO staleness window (fix(#682
    # review)). A window looks appealing — it would stop a worker that died
    # mid-job from holding the slot — but there is no liveness signal here to
    # base one on, and elapsed time is not a substitute: the 300s
    # statement_timeout bounds each STATEMENT, while the task runs a CTAS, a
    # DELETE, an EXISTS probe, two ALTERs, a primary key, add_4326_column and
    # registration in sequence. A legitimate materialize over a large dataset
    # can outlive any window short enough to be useful, and releasing the slot
    # then lets a second expensive CTAS through — defeating the cap outright.
    # The cost of not having one is bounded and visible: a dead worker holds
    # the slot until the platform's job timeout fails the row (started_at is
    # stamped, so that path works), and the client applies this same rule, so
    # the UI never disagrees with the API about whether a job is active.
    # Proper fix is a heartbeat lease (issue #691), as the ingest tasks use.
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
            IngestJob.status.in_(("pending", "running")),
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
            get_catalog_port().materialize_analysis_task(),
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
