"""The links, visibility and group names a version 2 apply response carries.

Built after the dataset entries and maps have run, from what the caller can
read, so the response needs no second request to show where things are.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.core.public_urls import (
    get_browser_reachable_api_url,
    get_browser_reachable_app_url,
    get_public_app_url,
    join_public_url,
)
from app.core.record_types import capabilities
from app.core.tile_scope import vector_tile_template
from app.platform.extensions import get_processing_port
from app.platform.jobs.in_flight import datasets_with_jobs_in_flight
from app.processing.ingest.manifest_maps import planned_publication
from app.processing.ingest.manifest_schemas import (
    ManifestApplyRequest,
    ManifestDataset,
    ManifestApplyEntryResult,
    ManifestDatasetLinks,
    ManifestMapLinks,
    ManifestMapResult,
)

log = structlog.get_logger()


async def _readable_dataset(
    db: AsyncSession, dataset_id: uuid.UUID, user: Identity
) -> Any | None:
    port = get_processing_port()
    dataset = await port.get_dataset(db, dataset_id)
    if dataset is None:
        return None
    try:
        await port.check_dataset_access(db, dataset, dataset_id, user)
    except HTTPException:
        return None
    return dataset


@dataclass(frozen=True)
class _DatasetFacts:
    """What a dataset's links are built from, read while the dataset is loaded."""

    id: uuid.UUID
    stored_visibility: str
    has_items: bool
    tile_table: str | None
    tile_cache_version: int | None
    publication_version: int | None


def _facts(dataset: Any) -> _DatasetFacts:
    kind = capabilities(dataset.record.record_type)
    has_tiles = kind.tile_token == "vector" and dataset.geometry_type is not None
    return _DatasetFacts(
        id=dataset.id,
        stored_visibility=dataset.record.visibility,
        has_items=kind.ogc_item_type not in (None, "coverage"),
        tile_table=dataset.table_name if has_tiles else None,
        tile_cache_version=dataset.tile_cache_version,
        publication_version=dataset.publication_version,
    )


def _dataset_links(facts: _DatasetFacts, app_url: str, api_url: str, *, settled: bool):
    return ManifestDatasetLinks(
        page=join_public_url(app_url, f"/datasets/{facts.id}"),
        items=join_public_url(api_url, f"/collections/{facts.id}/items")
        if facts.has_items
        else None,
        tiles=join_public_url(
            api_url,
            vector_tile_template(
                facts.tile_table,
                facts.tile_cache_version,
                facts.publication_version,
            ),
        )
        if facts.tile_table is not None and settled
        else None,
    )


def _pending_visibility(
    entries: dict[str, ManifestDataset], result: ManifestApplyEntryResult
) -> str | None:
    """The level the entry's job publishes, None when it keeps the stored one.

    An entry matched to a job still queued or running, or to a held
    replacement, answers for that job's publication. Otherwise a create or
    update writes what its entry decided.
    """
    if result.pending:
        return result.pending_visibility
    if result.action in ("create", "update") and result.dataset_key in entries:
        return planned_publication(entries[result.dataset_key], result)[0]
    return None


async def describe_results(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    http_request: Request | None,
    results: Sequence[ManifestApplyEntryResult],
    maps: Sequence[ManifestMapResult] | None,
) -> None:
    """Set visibility and links on version 2 dataset results, and links on
    map results.

    A dataset result's visibility is what its entry publishes, else the
    stored level. It never depends on the URLs: each lookup runs in its own
    savepoint, so one that fails leaves the session usable and costs only that
    result its stored level. Links are built after, in a savepoint of their
    own, and a failure there nulls the links alone. An entry with no dataset
    yet gets no links, nor does one the caller can't read. A map whose apply
    minted its share link keeps the links built for it then, which carry the
    share link and embed code, even when building the others fails.
    """
    entries = {dataset.key: dataset for dataset in request.datasets}
    facts: dict[uuid.UUID, _DatasetFacts] = {}
    for result in results:
        result.visibility = result.links = None
        if result.action == "error":
            continue
        planned = _pending_visibility(entries, result)
        if result.dataset_id is None:
            result.visibility = planned or "private"
            continue
        try:
            async with db.begin_nested():
                dataset = await _readable_dataset(db, result.dataset_id, user)
                found = _facts(dataset) if dataset is not None else None
        except Exception:  # broad: a lookup failure must not fail the apply
            log.exception("manifest_visibility_failed")
            result.visibility = planned
            continue
        if found is None:
            continue
        facts[result.dataset_id] = found
        result.visibility = planned or found.stored_visibility
    try:
        async with db.begin_nested():
            await _link(db, http_request, facts, results, maps)
    except Exception:  # broad: links are a courtesy; the apply already happened
        log.exception("manifest_links_failed")
        for result in results:
            result.links = None
        for map_result in maps or ():
            # A minted share link was built before the apply wrote anything.
            map_result.links = map_result._minted_links
            for removed in map_result.removed_layers:
                removed.link = None


async def _link(
    db: AsyncSession,
    http_request: Request | None,
    facts: dict[uuid.UUID, _DatasetFacts],
    results: Sequence[ManifestApplyEntryResult],
    maps: Sequence[ManifestMapResult] | None,
) -> None:
    app_url = await get_browser_reachable_app_url(
        db, request=http_request
    ) or await get_public_app_url(db, request=http_request)
    api_url = await get_browser_reachable_api_url(db, request=http_request)
    # Another apply may have queued a replacement since this entry settled.
    busy = await datasets_with_jobs_in_flight(db, facts)
    for result in results:
        if result.dataset_id in facts:
            # A job still writing the dataset bumps the tile version when it
            # publishes, so a template read now would name the old tiles.
            settled = (
                result.action == "skip"
                and not result.pending
                and result.dataset_id not in busy
            )
            result.links = _dataset_links(
                facts[result.dataset_id], app_url, api_url, settled=settled
            )
    for map_result in maps or ():
        if map_result._minted_links is not None:
            map_result.links = map_result._minted_links
        elif map_result.map_id is not None and map_result.action != "error":
            map_result.links = ManifestMapLinks(
                viewer=join_public_url(app_url, f"/maps/{map_result.map_id}")
            )
        for removed in map_result.removed_layers:
            removed.link = join_public_url(app_url, f"/datasets/{removed.dataset_id}")
