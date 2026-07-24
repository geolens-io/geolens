"""Materialize a PostGIS analysis result into a new dataset (M4).

The worker builds the output table with server-rendered SQL (shared
expression templates in ``app.platform.analysis_sql``), normalizes it to the
geom/geom_4326 convention, and registers it through the standard ingest
registration path (``register_existing_table``) so metadata extraction,
reader grants, and the atomic dataset-slot quota all apply.
"""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema
from app.core.db.tenant_session import current_tenant_var, tenant_task
from app.core.tenancy import is_multi_tenant
from app.platform.analysis_sql import render_geometry_expr
from app.processing.ingest.tasks import task_app

logger = structlog.stdlib.get_logger(__name__)

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_SAFE_TABLE = re.compile(r"^[a-z0-9_]+$")


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
) -> str:
    """Render the SELECT that produces the output table's rows."""
    if operation == "dissolve":
        if by_field:
            col = f'"{by_field}"'
            return (
                f"SELECT (row_number() OVER ())::integer AS gid, {col}, "
                f"COUNT(*)::integer AS source_count, "
                f"ST_Multi(ST_Union(geom_4326)) AS geom "
                f"FROM {src_ref} GROUP BY {col}"
            )
        return (
            f"SELECT 1 AS gid, COUNT(*)::integer AS source_count, "
            f"ST_Multi(ST_Union(geom_4326)) AS geom FROM {src_ref}"
        )
    expr, where = render_geometry_expr(
        operation, distance_meters=distance_meters, mask=mask
    )
    cols = "".join(f'"{c}", ' for c in carry_cols)
    return f"SELECT gid, {cols}{expr} AS geom FROM {src_ref}{where}"


async def _materialize(
    *,
    job_id: str,
    dataset_id: str,
    user_id: str,
    operation: str,
    title: str,
    distance_meters: float | None = None,
    mask: dict[str, Any] | None = None,
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
        await session.commit()

        _schema = tenant_data_schema(
            current_tenant_var.get() if is_multi_tenant() else None
        )
        out_table: str | None = None
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
            )
            await session.execute(text(f"CREATE TABLE {out_ref} AS {select_sql}"))
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
        except Exception as exc:  # broad: any failure must mark the job failed, not raise into the queue
            logger.warning("analysis.materialize_failed", job_id=job_id, error=str(exc))
            await session.rollback()
            if out_table:
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
        by_field=by_field,
    )
