"""Refresh runs as the job status surfaces report them."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.refresh.models import DatasetRefreshRun


def stored_review_reasons(verification: dict[str, Any] | None) -> list[str]:
    """Why a held run needs review, from its stored verification."""
    return [str(r) for r in (verification or {}).get("review_reasons") or ()]


async def latest_runs_for_jobs(
    session: AsyncSession, job_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Row[Any]]:
    """The newest refresh run (id, status, verification) bound to each job."""
    rows = await session.execute(
        select(
            DatasetRefreshRun.ingest_job_id,
            DatasetRefreshRun.id,
            DatasetRefreshRun.status,
            DatasetRefreshRun.verification,
        )
        .where(DatasetRefreshRun.ingest_job_id.in_(job_ids))
        .distinct(DatasetRefreshRun.ingest_job_id)
        .order_by(DatasetRefreshRun.ingest_job_id, DatasetRefreshRun.created_at.desc())
    )
    return {row.ingest_job_id: row for row in rows}
