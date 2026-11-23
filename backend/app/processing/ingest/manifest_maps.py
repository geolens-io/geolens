"""The maps section of a version 2 manifest.

Map checks and writes live in the catalog and run through ``ProcessingPort``;
this module resolves the layers' dataset keys and reports one result per map.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

import structlog
from fastapi import Request
from sqlalchemy import desc, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.identity import Identity
from app.platform.extensions import get_processing_port
from app.platform.jobs.in_flight import datasets_with_jobs_in_flight
from app.platform.jobs.models import ACTIVE_STATUSES, IngestJob
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
# The entries that change their dataset: a queued or held job whose dataset
# isn't yet the one the publish describes. A completed skip changes nothing.
_CHANGING_ACTIONS = frozenset({"create", "update", "blocked"})

log = structlog.get_logger()


async def ready_manifest_dataset_ids(
    db: AsyncSession, keys: Iterable[str]
) -> dict[str, uuid.UUID]:
    """The dataset each key names once its jobs have settled, in one query.

    The same pick as the dataset apply's own lookup of a key, the newest
    completed job whose dataset still exists, for a key with no job pending
    or running. A key with a job in flight names a dataset that job may
    still replace, and a key with no completed job names none; both are left
    out. A failed or cancelled replacement leaves the dataset the key named.
    """
    wanted = sorted(set(keys))
    if not wanted:
        return {}
    Dataset = get_processing_port().get_dataset_orm_class()
    key = IngestJob.user_metadata["manifest_key"].astext
    InFlight = aliased(IngestJob)
    in_flight = exists().where(
        InFlight.status.in_(ACTIVE_STATUSES),
        InFlight.user_metadata["manifest_key"].astext == key,
    )
    rows = await db.execute(
        select(key, IngestJob.dataset_id)
        .join(Dataset, IngestJob.dataset_id == Dataset.id)
        .where(IngestJob.status == "complete", key.in_(wanted), ~in_flight)
        .distinct(key)
        .order_by(key, desc(IngestJob.completed_at), desc(IngestJob.created_at))
    )
    return {row[0]: row[1] for row in rows}


def planned_publication(
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

    ``dataset_results`` are this request's dataset outcomes. A dry run
    answers for the whole publish, datasets first and maps once their jobs
    finish: a layer may name, by key or by id, the dataset of an entry that
    changes it, and the map's visibility is judged on what that entry
    publishes. An apply writes a layer only on the dataset the publish
    describes, so a layer on the dataset of an entry this request created,
    replaced, held or failed, or on a dataset with a job still in flight,
    answers A052. A completed skip changes nothing, so both runs judge its
    dataset as it is.

    An apply commits each map on its own; whatever is left open, a dry run
    entirely, is rolled back.
    """
    if request.manifest_version != "2":
        return None
    maps = request.maps or []
    if not maps:
        return []
    try:
        layers = [layer for entry in maps for layer in entry.layers]
        # The entries' own keys too: a skip settles only when its key does,
        # whichever way the layers name its dataset.
        ready = await ready_manifest_dataset_ids(
            db,
            [
                *(layer.dataset_key for layer in layers if layer.dataset_key),
                *(r.dataset_key for r in dataset_results),
            ],
        )
        entries = {dataset.key: dataset for dataset in request.datasets}
        # A skip onto a job still in flight publishes when that job does.
        changing = [
            r
            for r in dataset_results
            if r.dataset_key in entries
            and (
                r.action in _CHANGING_ACTIONS
                or (r.action == "skip" and r.dataset_key not in ready)
            )
        ]
        # An entry that failed in this request supplies no dataset, not even
        # the one an earlier publish left under its key, by key or by id.
        failed = [r for r in dataset_results if r.action == "error"]
        not_ready = {r.dataset_key for r in failed}
        pending: dict[str | uuid.UUID, tuple[str | None, str]] = {}
        unsettled = await datasets_with_jobs_in_flight(
            db,
            [
                *(layer.dataset_id for layer in layers if layer.dataset_id),
                *ready.values(),
            ],
        )
        unsettled |= {ready[r.dataset_key] for r in failed if r.dataset_key in ready}
        bindings: dict[str, uuid.UUID] = {}
        for r in changing:
            if request.dry_run:
                planned = planned_publication(entries[r.dataset_key], r)
                pending[r.dataset_key] = planned
                if r.dataset_id is not None:
                    pending[r.dataset_id] = planned
                    # The dataset a key whose job is in flight already names,
                    # so its columns are checked as they are by id.
                    bindings.setdefault(r.dataset_key, r.dataset_id)
            else:
                not_ready.add(r.dataset_key)
                if r.dataset_id is not None:
                    unsettled.add(r.dataset_id)
        results = await get_processing_port().apply_manifest_maps(
            db,
            maps,
            user,
            dry_run=request.dry_run,
            dataset_ids_by_key={
                **{key: id_ for key, id_ in bindings.items() if key not in not_ready},
                **{
                    key: dataset_id
                    for key, dataset_id in ready.items()
                    if key not in not_ready
                },
            },
            pending_datasets=pending,
            unsettled_dataset_ids=frozenset(unsettled),
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
