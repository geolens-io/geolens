"""The maps section of a version 2 manifest.

Map checks and writes live in the catalog and run through ``ProcessingPort``;
this module resolves the layers' dataset keys and reports one result per map.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

import structlog
from fastapi import Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.extensions import get_processing_port
from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import (
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestDataset,
    ManifestMapResult,
    ManifestMessage,
)
from app.processing.ingest.manifest_sources import publication_to_catalog_fields

OTHER_REFUSAL = "A099"
PUBLIC_RESTRICTED = "A020"

MAPS_CHECK_FAILED = "The maps could not be checked. Try again."

log = structlog.get_logger()


async def latest_completed_manifest_dataset_ids(
    db: AsyncSession, keys: Iterable[str]
) -> dict[str, uuid.UUID]:
    """The dataset of each key's newest completed manifest job, in one query.

    The same pick as the dataset apply's own lookup of a key: the newest
    completed job whose dataset still exists. A key with none is left out.
    """
    wanted = sorted(set(keys))
    if not wanted:
        return {}
    Dataset = get_processing_port().get_dataset_orm_class()
    key = IngestJob.user_metadata["manifest_key"].astext
    rows = await db.execute(
        select(key, IngestJob.dataset_id)
        .join(Dataset, IngestJob.dataset_id == Dataset.id)
        .where(IngestJob.status == "complete", key.in_(wanted))
        .distinct(key)
        .order_by(key, desc(IngestJob.completed_at), desc(IngestJob.created_at))
    )
    return {row[0]: row[1] for row in rows}


def _planned_publication(
    dataset: ManifestDataset, result: ManifestApplyEntryResult
) -> tuple[str | None, str]:
    """The visibility (None keeps the dataset's) and status an entry that
    didn't fail publishes: internal when its public fell back."""
    _, record_status = publication_to_catalog_fields(dataset.publication)
    fell_back = any(
        message.code == PUBLIC_RESTRICTED for message in result.messages or ()
    )
    return ("internal" if fell_back else dataset.visibility), record_status


def _failed(map_key: str, message: str) -> ManifestMapResult:
    return ManifestMapResult(
        map_key=map_key,
        action="error",
        messages=[
            ManifestMessage(code=OTHER_REFUSAL, severity="error", message=message)
        ],
    )


async def run_manifest_maps(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    dataset_results: Sequence[ManifestApplyEntryResult],
    http_request: Request | None = None,
) -> list[ManifestMapResult] | None:
    """One result per map, or None for a version 1 request.

    ``dataset_results`` are this request's dataset outcomes. In a dry run a
    layer may name the key of an entry that didn't fail before its dataset
    can be read, and the map's visibility is judged on what that entry
    publishes. An apply writes a layer only on a dataset that is complete, so
    a layer naming an entry this request only queued answers A052, as one
    naming an entry in error does.

    An apply commits each map on its own; whatever is left open, a dry run
    entirely, is rolled back.
    """
    if request.manifest_version != "2":
        return None
    maps = request.maps or []
    if not maps:
        return []
    try:
        dataset_ids = await latest_completed_manifest_dataset_ids(
            db,
            (
                layer.dataset_key
                for entry in maps
                for layer in entry.layers
                if layer.dataset_key is not None
            ),
        )
        # An entry that failed in this request supplies no dataset, not even
        # the one an earlier publish left under its key.
        failed = {r.dataset_key for r in dataset_results if r.action == "error"}
        entries = {dataset.key: dataset for dataset in request.datasets}
        results = await get_processing_port().apply_manifest_maps(
            db,
            maps,
            user,
            dry_run=request.dry_run,
            dataset_ids_by_key={
                key: dataset_id
                for key, dataset_id in dataset_ids.items()
                if key not in failed
            },
            pending_datasets={
                r.dataset_key: _planned_publication(entries[r.dataset_key], r)
                for r in dataset_results
                if request.dry_run and r.action != "error" and r.dataset_key in entries
            },
            public_fallback=request.public_fallback,
            client=request.client,
            ip_address=(
                http_request.client.host
                if http_request is not None and http_request.client
                else None
            ),
        )
        return [ManifestMapResult.model_validate(result) for result in results]
    except Exception:  # broad: the dataset results above must still reach the caller
        log.exception("manifest_maps_check_failed")
        return [_failed(entry.key, MAPS_CHECK_FAILED) for entry in maps]
    finally:
        await db.rollback()
