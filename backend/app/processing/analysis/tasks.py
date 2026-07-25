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
from types import SimpleNamespace
from typing import Any

import structlog
from prometheus_client import Counter
from sqlalchemy import select, text
from sqlalchemy.exc import DataError, InternalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var, tenant_task
from app.core.tenancy import is_multi_tenant
from app.platform.analysis_sql import render_geometry_expr, render_mask_cte
from app.platform.jobs.heartbeat import (
    claim_ingest_job_attempt,
    maintain_ingest_job_heartbeat,
    resolve_ingest_job_attempt,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SAFE_TABLE = re.compile(r"^[a-z0-9_]+$")

# The preview path is bounded (10s sandbox timeout, 500-row cap); the CTAS
# here is the only unbounded statement a user can queue, so cap it.
# ponytail: hardcoded ceiling; promote to persistent-config if operators hit it.
MATERIALIZE_TIMEOUT = "300s"

# The mid-task commit that makes the output table durable also ends the
# transaction carrying MATERIALIZE_TIMEOUT — registration then runs full-scan
# metadata extraction (COUNT + ST_Extent + the sample-values CTE) in a fresh
# transaction, which would otherwise have no statement budget at all
# (fix(#692)). Larger than the CTAS budget: those scans are cheap relative to
# the build, but must never be unbounded.
REGISTRATION_TIMEOUT = "600s"

# Served by the worker's :8001 /metrics endpoint (default registry).
# ponytail: analysis-only counter; generalize to all ingest job types when
# another type needs it.
ANALYSIS_JOBS = Counter(
    "geolens_analysis_jobs_total",
    "Materialize-analysis job outcomes",
    ["operation", "status"],
)


def _user_error_message(exc: Exception) -> str:
    """Map a failure onto text safe to return from ``GET /jobs/{job_id}``.

    SQLAlchemy stringifies DB errors with the full statement appended
    (``[SQL: CREATE TABLE "data"."…" AS …]``), which would hand internal
    schema and table names to the client (fix(#692)). Mirrors the sandbox's
    ``_handle_execution_error`` categories; raw text stays in server logs.
    """
    if isinstance(exc, SQLAlchemyError):
        exc_text = str(exc).lower()
        if "querycancelederror" in exc_text or "statement timeout" in exc_text:
            return (
                "The analysis exceeded its processing time limit. "
                "Try a smaller dataset or area."
            )
        if isinstance(exc, (DataError, InternalError)):
            return "The analysis failed while processing this data"
        return "The analysis failed due to a database error"
    return str(exc)[:2000]


async def _fail_cancelled_job(
    working_session: AsyncSession,
    *,
    job_id: str,
    attempt_id: uuid.UUID,
    schema: str,
    out_table: str | None,
    operation: str,
) -> None:
    """Bookkeeping for a materialize cancelled mid-run, on a fresh session.

    Fenced on the attempt token FIRST: a successful fence proves the row was
    still 'running', so the final registration commit (which atomically
    persists the dataset and flips the row to 'complete') has not happened,
    and any committed output table is an unregistered orphan — safe to drop.
    If the fence misses, the job already reached a terminal state and the
    table must be left alone.
    """
    from app.core.db import async_session

    # fix(#700 review): the cancel can land while `working_session`'s open
    # transaction still holds the job-row lock (any flush since its last
    # commit, e.g. mid-commit). Release it first — time-bounded so a wedged
    # connection can't eat the whole shield window — or the fenced update
    # below waits on our own lock until the shield timeout and the row
    # strands in 'running' anyway.
    try:
        await asyncio.wait_for(working_session.rollback(), timeout=5)
    except Exception:  # broad: cleanup must reach the fenced update regardless
        logger.warning("analysis.cancel_rollback_failed", job_id=job_id)

    async with async_session() as session:
        if not await update_ingest_job_for_attempt(
            session,
            uuid.UUID(job_id),
            attempt_id,
            values={
                "status": "failed",
                "error_message": (
                    "The worker shut down before this analysis finished. Run it again."
                ),
            },
        ):
            await session.rollback()
            return
        await session.commit()
        if out_table is not None:
            try:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
                )
                await session.commit()
            except Exception:  # broad: best-effort cleanup of the partial table
                await session.rollback()
    ANALYSIS_JOBS.labels(operation=operation, status="failed").inc()


async def _mark_job_failed(
    session: AsyncSession,
    *,
    job_id: str,
    exc: Exception,
    schema: str,
    out_table: str | None,
    operation: str,
) -> None:
    """Roll back, drop this job's own partial table, and record the failure."""
    from app.platform.jobs.models import IngestJob

    await session.rollback()
    if out_table is not None:
        try:
            await session.execute(
                text(f'DROP TABLE IF EXISTS "{schema}"."{out_table}"')
            )
            await session.commit()
        except Exception:  # broad: best-effort cleanup of the partial table
            await session.rollback()
    failed_job = await session.get(IngestJob, uuid.UUID(job_id))
    if failed_job is not None:
        failed_job.status = "failed"
        # Sanitized (fix(#692)): raw DB errors embed the generated SQL.
        failed_job.error_message = _user_error_message(exc)
        await session.commit()
    ANALYSIS_JOBS.labels(operation=operation, status="failed").inc()


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
        # Fenced claim (fix(#692), the ingest_file pattern): pending → running
        # succeeds at most once per attempt token, and stamps
        # started_at/heartbeat_at — the liveness signals the stale-job sweep
        # and the lease below depend on (fix(#682 review): statement_timeout
        # bounds each STATEMENT, not the task, so a large materialize can
        # legitimately run long and only the lease keeps it out of the sweep).
        # Without the claim this worker would act on rows some other actor
        # already moved to a terminal state — the pending-sweeper failing a
        # backlogged job after an hour, or the defer orphan-guard failing the
        # row after the queue INSERT committed — and resurrect them: the
        # per-user cap admits a second CTAS, and a dataset appears for a job
        # the user was told failed.
        #
        # The row's own attempt_id is the token (column-defaulted at
        # creation; retry=0, so there is no second delivery to fence against).
        # Rows predating that default are adopted atomically.
        attempt_id = job.attempt_id or await resolve_ingest_job_attempt(job.id, None)
        if attempt_id is None or not await claim_ingest_job_attempt(
            session, job.id, attempt_id
        ):
            await session.rollback()
            logger.warning("analysis.attempt_not_claimed", job_id=job_id)
            return
        # current_step only, no numeric progress: the operation is a single
        # CTAS, so there is no intra-statement telemetry to report and a bar
        # parked at 10% for five minutes reads as "stuck" rather than "busy".
        job.current_step = "analyzing"
        await session.commit()

        _schema = tenant_data_schema(
            current_tenant_var.get() if is_multi_tenant() else None
        )
        out_table: str | None = None
        # Only drop the output table on failure if THIS job created it: when
        # CREATE TABLE itself fails because a concurrent job won the same
        # generated name, an unconditional cleanup would destroy the winner's
        # table while its dataset registration stays live.
        out_table_created = False
        # Created inside the try so the finally below always reaps it: a
        # heartbeat left running after an exception here would renew a lease
        # for a job nobody is executing, and the sweep can never fail a row
        # with a fresh lease (fix(#692)).
        heartbeat: asyncio.Task[None] | None = None
        try:
            # Renews on its own session, so it never contends with the work
            # below, and returns by itself once the row leaves 'running'.
            heartbeat = asyncio.create_task(
                maintain_ingest_job_heartbeat(job.id, attempt_id)
            )
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
            # Rows with nothing to show are dropped for EVERY operation, not
            # just clip (fix(#692)): buffer/centroid map NULL source
            # geometries to NULL, dissolve unions an all-NULL group to NULL,
            # and boundary-grazing clips survive ST_Intersects but extract to
            # EMPTY (see analysis_sql.render_geometry_expr). The preview
            # filters the same rows in SQL (fix(#680 review)) — the saved
            # dataset must agree with the preview the user approved.
            await session.execute(
                text(f"DELETE FROM {out_ref} WHERE geom IS NULL OR ST_IsEmpty(geom)")
            )
            has_features = await session.scalar(
                text(f"SELECT EXISTS (SELECT 1 FROM {out_ref})")
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
            # In-transaction ANALYZE (fix(#692)): the table only becomes
            # visible to autovacuum at the commit below, and the first tile
            # queries land before its pass — without statistics the planner
            # has no geometry selectivity for `&&` against the fresh GIST
            # index and can seq-scan a large output.
            await session.execute(text(f"ANALYZE {out_ref}"))
            job.current_step = "registering"
            await session.commit()

            # The commit above ended the transaction and the SET LOCAL with
            # it — give registration its own budget (fix(#692)). Set here
            # rather than inside register_existing_table, which is shared
            # with the upload path.
            await session.execute(
                text(f"SET LOCAL statement_timeout = '{REGISTRATION_TIMEOUT}'")
            )
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
        except asyncio.CancelledError:
            # Graceful worker shutdown cancels this task after the drain
            # window; `except Exception` cannot catch it, and retry=0 means no
            # redelivery — without this branch the row would strand in
            # 'running', holding the user's one analysis slot, until the
            # 60-minute sweep (fix(#692)). Bookkeeping runs on a fresh session
            # (this one may be mid-statement) and is shielded so the
            # cancellation doesn't also cancel it; then re-raise so the queue
            # records the abort.
            try:
                await asyncio.shield(
                    asyncio.wait_for(
                        _fail_cancelled_job(
                            session,
                            job_id=job_id,
                            attempt_id=attempt_id,
                            schema=_schema,
                            out_table=out_table if out_table_created else None,
                            operation=operation,
                        ),
                        timeout=15,
                    )
                )
            except BaseException:  # broad: best-effort cleanup during shutdown; the raise below preserves the abort
                logger.warning("analysis.cancel_cleanup_failed", job_id=job_id)
            raise
        except Exception as exc:  # broad: any failure must mark the job failed, not raise into the queue
            logger.warning(
                "analysis.materialize_failed",
                job_id=job_id,
                error=str(exc),
                exc_info=True,
            )
            await _mark_job_failed(
                session,
                job_id=job_id,
                exc=exc,
                schema=_schema,
                out_table=out_table if out_table_created else None,
                operation=operation,
            )
        finally:
            # The row has left 'running' by now, so the loop would exit on its
            # own at the next renewal — stop (cancel + await, the ingest
            # convention) so the task neither outlives the work by a heartbeat
            # interval nor leaks a pending task through worker shutdown.
            await stop_ingest_job_heartbeat(heartbeat)


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
