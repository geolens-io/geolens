"""Staging a VRT membership change for its regeneration."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.permissions import UPLOAD
from app.platform.jobs.models import ADMITTED_CAPABILITY_METADATA_KEY
from app.processing.ingest.service import create_ingest_job


async def stage_vrt_regeneration(
    db: AsyncSession,
    vrt_asset: Any,
    dataset_id: uuid.UUID,
    staged_source_ids: list[str],
    user: Identity,
) -> tuple[Any, Any]:
    """Stage ``staged_source_ids`` on a pending generation, mark the VRT
    regenerating and create the job that rebuilds it, recording that it was
    admitted under ``upload``, which both source doors require. Returns
    ``(job, generation)``.

    Call holding the VRT's catalog rows. Does not commit.
    """
    from app.processing.raster.models import VrtGeneration

    generation = VrtGeneration(
        vrt_dataset_id=dataset_id,
        status="pending",
        started_at=datetime.now(timezone.utc),
        source_count=len(staged_source_ids),
        staged_source_ids=staged_source_ids,
        triggered_by=str(user.id),
    )
    db.add(generation)
    await db.flush()
    vrt_asset.status = "regenerating"
    vrt_asset.current_generation_id = generation.id

    job = await create_ingest_job(db, "vrt_regenerate", "", user.id)
    job.dataset_id = dataset_id
    job.user_metadata = {ADMITTED_CAPABILITY_METADATA_KEY: UPLOAD}
    return job, generation
