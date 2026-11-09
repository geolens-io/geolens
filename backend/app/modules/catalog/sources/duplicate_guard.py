"""Duplicate-source guards shared by the import doors.

The published-dataset check lives beside each door; the queued-job check
lives here so the service preview door stays within its size cap.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.sources.adapters.arcgis import normalize_arcgis_url
from app.platform.dataset_origin import service_layer_identity
from app.platform.extensions import get_catalog_port
from app.platform.jobs.models import IngestJob

IngestionError = get_catalog_port().ingestion_error_class()


async def _active_service_import_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    source_format: str,
    base_url: str,
    canonical_layer_id: str | None,
) -> IngestJob | None:
    """A pending or running import of the same service layer by this user.

    The published-dataset check beside the door only sees finished imports,
    so a second submission while the first job is still queued would slip
    through and publish a second copy. A failed or cancelled first job is
    not active, so it never blocks a retry.

    Identity is spelled the same way on both sides: the stored job keeps the
    raw service type and the base URL it was previewed with, so each
    candidate is re-resolved and re-normalized before it is compared rather
    than trusted as written.
    """
    candidates = (
        (
            await db.execute(
                select(IngestJob).where(
                    IngestJob.created_by == user_id,
                    IngestJob.status.in_(("pending", "running")),
                )
            )
        )
        .scalars()
        .all()
    )
    for job in candidates:
        metadata = job.user_metadata or {}
        raw_type = metadata.get("service_type")
        if not isinstance(raw_type, str):
            continue
        try:
            _, job_format = get_catalog_port().resolve_service_type(raw_type)
        except (ValueError, KeyError, IngestionError):
            continue
        if job_format != source_format:
            continue
        try:
            job_base_url, _ = normalize_arcgis_url(job.source_url or "")
        except Exception:  # broad: malformed stored URL; degrade to raw
            job_base_url = job.source_url
        if job_base_url != base_url:
            continue
        if (
            service_layer_identity(
                job_format,
                layer_id=metadata.get("layer_id"),
                layer_name=job.source_layer,
            )
            != canonical_layer_id
        ):
            continue
        return job
    return None


async def refuse_queued_service_import(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    source_format: str,
    base_url: str,
    canonical_layer_id: str | None,
) -> None:
    """Raise 409 when an import of the same service layer is already queued."""
    queued = await _active_service_import_job(
        db,
        user_id,
        source_format=source_format,
        base_url=base_url,
        canonical_layer_id=canonical_layer_id,
    )
    if queued is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_source",
                "message": (
                    "An import of this source is already in progress. "
                    "Wait for it to finish, or refresh the dataset once "
                    "it is published, instead of importing it again."
                ),
                "existing_job_id": str(queued.id),
            },
        )
