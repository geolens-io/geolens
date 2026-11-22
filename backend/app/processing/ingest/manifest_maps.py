"""The maps section of a version 2 manifest.

Map checks live in the catalog and run through ``ProcessingPort``; this module
resolves the layers' dataset keys and reports one result per map.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.extensions import get_processing_port
from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import (
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestMapResult,
    ManifestMessage,
)

OTHER_REFUSAL = "A099"

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


def _failed(map_key: str, message: str) -> ManifestMapResult:
    return ManifestMapResult(
        map_key=map_key,
        action="error",
        messages=[
            ManifestMessage(code=OTHER_REFUSAL, severity="error", message=message)
        ],
    )


async def check_manifest_maps(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    dataset_results: Sequence[ManifestApplyEntryResult],
) -> list[ManifestMapResult] | None:
    """One result per map, or None for a version 1 request.

    ``dataset_results`` are this request's dataset outcomes. A layer may name
    the key of an entry that didn't fail before its dataset can be read; an
    entry in error supplies nothing, so a layer naming it answers A052.

    Writes nothing: the check runs in a dry run, which the request schema
    requires for maps, and is rolled back.
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
            pending_dataset_keys=frozenset(
                r.dataset_key for r in dataset_results if r.action != "error"
            ),
        )
        return [ManifestMapResult.model_validate(result) for result in results]
    except Exception:  # broad: the dataset results above must still reach the caller
        log.exception("manifest_maps_check_failed")
        return [_failed(entry.key, MAPS_CHECK_FAILED) for entry in maps]
    finally:
        await db.rollback()
