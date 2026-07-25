"""Materialize a PostGIS analysis result into a new dataset (M4).

The worker builds the output table with server-rendered SQL (shared
expression templates in ``app.platform.analysis_sql``), normalizes it to the
geom/geom_4326 convention, and registers it through the standard ingest
registration path (``register_existing_table``) so metadata extraction,
reader grants, and the atomic dataset-slot quota all apply.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import structlog
from prometheus_client import Counter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var, tenant_task
from app.core.tenancy import is_multi_tenant
from app.platform.analysis_sql import render_geometry_expr, render_mask_cte
from app.platform.jobs.heartbeat import maintain_ingest_job_heartbeat
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SAFE_TABLE = re.compile(r"^[a-z0-9_]+$")

# The preview path is bounded (10s sandbox timeout, 500-row cap); the CTAS
# here is the only unbounded statement a user can queue, so cap it.
# ponytail: hardcoded ceiling; promote to persistent-config if operators hit it.
MATERIALIZE_TIMEOUT = "300s"

# Served by the worker's :8001 /metrics endpoint (default registry).
# ponytail: analysis-only counter; generalize to all ingest job types when
# another type needs it.
ANALYSIS_JOBS = Counter(
    "geolens_analysis_jobs_total",
    "Materialize-analysis job outcomes",
    ["operation", "status"],
)


async def _list_carry_columns(
    session: AsyncSession, schema: str, table_name: str
) -> list[str]:
    """Attribute columns to carry into 1:1 op output (skip system/geom cols)."""
    rows = await session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table_name "
            "AND column_name NOT IN ('gid', 'geom', 'geom_4326') "
            "ORDER BY ordinal_position"
        ).bindparams(schema=schema, table_name=table_name)
    )
    return [row[0] for row in rows if _SAFE_IDENT.match(row[0])]


def _build_materialize_select(
    src_ref: str,
    operation: str,
    *,
    distance_meters: float | None,
    mask: dict[str, Any] | None,
    by_field: str | None,
    carry_cols: list[str],
    mask_table_ref: str | None = None,
) -> str:
    """Render the SELECT that produces the output table's rows."""
    if operation == "dissolve":
        # ST_MakeValid: one invalid ring would abort the whole union.
        # ST_CollectionExtract: a union over mixed geometry types returns a
        # GEOMETRYCOLLECTION, which the MVT tile path can't render — keep only
        # the highest-dimension components so the output stays typed.
        union_expr = "ST_Multi(ST_CollectionExtract(ST_Union(ST_MakeValid(geom_4326))))"
        if by_field:
            col = f'"{by_field}"'
            return (
                f"SELECT (row_number() OVER ())::integer AS gid, {col}, "
                f"COUNT(*)::integer AS source_count, "
                f"{union_expr} AS geom "
                f"FROM {src_ref} GROUP BY {col}"
            )
        return (
            f"SELECT 1 AS gid, COUNT(*)::integer AS source_count, "
            f"{union_expr} AS geom FROM {src_ref}"
        )
    expr, where = render_geometry_expr(
        operation,
        distance_meters=distance_meters,
        mask=mask,
        layer_mask=mask_table_ref is not None,
    )
    cte = f"{render_mask_cte(mask_table_ref)} " if mask_table_ref else ""
    cols = "".join(f'"{c}", ' for c in carry_cols)
    return f"{cte}SELECT gid, {cols}{expr} AS geom FROM {src_ref}{where}"


async def _materialize(
    *,
    job_id: str,
    dataset_id: str,
    user_id: str,
    operation: str,
    title: str,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
    mask_dataset_id: str | None = None,
    by_field: str | None = None,
) -> None:
    """Core materialize logic; separated from the task wrapper for tests."""
    from app.core.db import async_session
    from app.platform.extensions import get_processing_port
    from app.platform.jobs.models import IngestJob
    from app.processing.ingest.metadata import add_4326_column
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import (
        generate_table_name,
        register_existing_table,
    )

    async with async_session() as session:
        job = await session.get(IngestJob, uuid.UUID(job_id))
        if job is None:
            logger.warning("analysis.job_not_found", job_id=job_id)
            return
        job.status = "running"
        # Stamp the start time. Without it this row carries NO liveness signal
        # at all, and the platform's stale-job recovery matches on
        # `coalesce(heartbeat_at, started_at) < cutoff` — which is NULL for
        # such a row, so a worker that dies mid-CTAS would strand the job in
        # 'running' forever.
        _now = datetime.now(timezone.utc)
        job.started_at = _now
        # ...and renew a lease from here on, or started_at alone would condemn
        # a job that legitimately outlives JOB_TIMEOUT_SECONDS (fix(#682
        # review)). statement_timeout bounds each STATEMENT, not the task: the
        # CTAS, DELETE, EXISTS probe, two ALTERs, the primary key,
        # add_4326_column and registration each get their own budget, so a
        # large materialize can run long. Without a lease the sweep would mark
        # a live job failed, the watcher would report a false failure, the
        # per-user slot would reopen for a second CTAS, and this worker would
        # later overwrite 'failed' with 'complete'.
        #
        # Reuse the token the row already carries (IngestJob.attempt_id
        # defaults to uuid4 at creation) rather than minting a fresh one —
        # rotating it here would invalidate the token the enqueue side
        # recorded, and this task is retry=0 so there is no second delivery to
        # fence against. The fallback covers rows predating that default.
        attempt_id = job.attempt_id
        if attempt_id is None:
            attempt_id = uuid.uuid4()
            job.attempt_id = attempt_id
        job.heartbeat_at = _now
        # current_step only, no numeric progress: the operation is a single
        # CTAS, so there is no intra-statement telemetry to report and a bar
        # parked at 10% for five minutes reads as "stuck" rather than "busy".
        job.current_step = "analyzing"
        await session.commit()

        # Renews on its own session, so it never contends with the work below,
        # and returns by itself once the row leaves 'running'.
        heartbeat = asyncio.create_task(
            maintain_ingest_job_heartbeat(job.id, attempt_id)
        )

        _schema = tenant_data_schema(
            current_tenant_var.get() if is_multi_tenant() else None
        )
        out_table: str | None = None
        # Only drop the output table on failure if THIS job created it: when
        # CREATE TABLE itself fails because a concurrent job won the same
        # generated name, an unconditional cleanup would destroy the winner's
        # table while its dataset registration stays live.
        out_table_created = False
        try:
            port = get_processing_port()
            Dataset = port.get_dataset_orm_class()
            result = await session.execute(
                select(Dataset).where(Dataset.id == uuid.UUID(dataset_id))
            )
            src = result.scalar_one_or_none()
            if src is None or not src.table_name:
                raise ValueError("Source dataset not found")
            if not _SAFE_TABLE.match(src.table_name):
                raise ValueError("Invalid source table name")
            if by_field is not None and not _SAFE_IDENT.match(by_field):
                raise ValueError("Invalid dissolve column name")
            src_ref = f'"{_schema}"."{src.table_name}"'

            # Layer-sourced clip mask: re-resolve the table name at run time
            # (access was checked at enqueue by the router, same trust model
            # as the source dataset).
            mask_table_ref: str | None = None
            if mask_dataset_id is not None:
                mask_result = await session.execute(
                    select(Dataset).where(Dataset.id == uuid.UUID(mask_dataset_id))
                )
                mask_ds = mask_result.scalar_one_or_none()
                if mask_ds is None or not mask_ds.table_name:
                    raise ValueError("Mask dataset not found")
                if not _SAFE_TABLE.match(mask_ds.table_name):
                    raise ValueError("Invalid mask table name")
                mask_table_ref = f'"{_schema}"."{mask_ds.table_name}"'

            out_table, _warning = await generate_table_name(title, session)
            out_ref = f'"{_schema}"."{out_table}"'

            carry_cols = (
                await _list_carry_columns(session, _schema, src.table_name)
                if operation != "dissolve"
                else []
            )
            select_sql = _build_materialize_select(
                src_ref,
                operation,
                distance_meters=distance_meters,
                mask=mask,
                by_field=by_field,
                carry_cols=carry_cols,
                mask_table_ref=mask_table_ref,
            )
            await session.execute(
                text(f"SET LOCAL statement_timeout = '{MATERIALIZE_TIMEOUT}'")
            )
            await session.execute(text(f"CREATE TABLE {out_ref} AS {select_sql}"))
            out_table_created = True
            if operation == "clip":
                # Boundary-grazing rows survive ST_Intersects but extract to
                # EMPTY (see analysis_sql.render_geometry_expr) — drop them.
                await session.execute(
                    text(f"DELETE FROM {out_ref} WHERE ST_IsEmpty(geom)")
                )
            has_features = await session.scalar(
                text(
                    f"SELECT EXISTS (SELECT 1 FROM {out_ref} "
                    f"WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom))"
                )
            )
            if not has_features:
                # e.g. a clip matching nothing, or dissolving an empty
                # dataset (whose no-GROUP-BY aggregate still yields one
                # NULL-geometry row) — fail loud instead of registering junk.
                raise ValueError("Analysis produced no features to save")
            # CTAS yields an untyped geometry column (typmod srid=0), which
            # metadata extraction reports as SRID 0 — stamp the 4326 typmod.
            await session.execute(
                text(
                    f"ALTER TABLE {out_ref} ALTER COLUMN geom "
                    f"TYPE geometry(Geometry, 4326) USING ST_SetSRID(geom, 4326)"
                )
            )
            await session.execute(text(f"ALTER TABLE {out_ref} ADD PRIMARY KEY (gid)"))
            await add_4326_column(session, out_table, 4326, schema=_schema)
            job.current_step = "registering"
            await session.commit()

            # Identity is a structural Protocol; registration only reads .id.
            requester = SimpleNamespace(id=uuid.UUID(user_id))
            dataset = await register_existing_table(
                session,
                RegisterRequest(
                    table_name=out_table, title=title, visibility="private"
                ),
                requester,
            )
            job.dataset_id = dataset.id
            job.status = "complete"
            await session.commit()
            ANALYSIS_JOBS.labels(operation=operation, status="complete").inc()
        except Exception as exc:  # broad: any failure must mark the job failed, not raise into the queue
            logger.warning("analysis.materialize_failed", job_id=job_id, error=str(exc))
            await session.rollback()
            if out_table and out_table_created:
                try:
                    await session.execute(
                        text(f'DROP TABLE IF EXISTS "{_schema}"."{out_table}"')
                    )
                    await session.commit()
                except Exception:  # broad: best-effort cleanup of the partial table
                    await session.rollback()
            failed_job = await session.get(IngestJob, uuid.UUID(job_id))
            if failed_job is not None:
                failed_job.status = "failed"
                failed_job.error_message = str(exc)[:2000]
                await session.commit()
            ANALYSIS_JOBS.labels(operation=operation, status="failed").inc()
        finally:
            # The row has left 'running' by now, so the loop would exit on its
            # own at the next renewal — cancel so the task does not outlive the
            # work by up to one heartbeat interval.
            heartbeat.cancel()


@task_app.task(
    queue="ingest", retry=0, aliases=["app.analysis.tasks.materialize_analysis"]
)
@tenant_task
async def materialize_analysis(
    job_id: str,
    dataset_id: str,
    user_id: str,
    operation: str,
    title: str,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
    mask_dataset_id: str | None = None,
    by_field: str | None = None,
) -> None:
    """Procrastinate entry point for async analysis materialization."""
    await _materialize(
        job_id=job_id,
        dataset_id=dataset_id,
        user_id=user_id,
        operation=operation,
        title=title,
        distance_meters=distance_meters,
        mask=mask,
        mask_dataset_id=mask_dataset_id,
        by_field=by_field,
    )
