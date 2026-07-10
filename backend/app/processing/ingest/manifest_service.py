"""Service entry point for applying manifest v1 payloads."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db.tenant_session import defer_async_with_tenant
from app.core.identity import Identity
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB, get_allowed_extensions_list
from app.platform.extensions import get_catalog_port, get_processing_port
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    make_ingest_job_failed_rollback,
)

from app.platform.jobs.models import IngestJob
from app.processing.ingest.manifest_schemas import (
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestApplyResponse,
    ManifestDataset,
)
from app.processing.ingest.manifest_sources import (
    ManifestPreparedSource,
    ManifestSourceError,
    classify_manifest_source,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
)
from app.processing.ingest.service import queue_ingest_job, validate_file_extension

# fix(#435): batch manifest-download writes so a 64 KiB httpx chunk does not cost
# one `asyncio.to_thread` handoff each. 4 MiB keeps peak buffer memory small
# while amortizing the thread hop across ~64 chunks.
_WRITE_BUFFER_BYTES = 4 * 1024 * 1024


async def _latest_in_flight_manifest_job(
    db: AsyncSession, key: str
) -> IngestJob | None:
    result = await db.execute(
        select(IngestJob)
        .where(
            IngestJob.status.in_(["pending", "running"]),
            IngestJob.user_metadata["manifest_key"].astext == key,
        )
        .order_by(desc(IngestJob.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _latest_completed_manifest_job(
    db: AsyncSession, key: str
) -> tuple[IngestJob, object] | None:
    Dataset = get_processing_port().get_dataset_orm_class()
    result = await db.execute(
        select(IngestJob, Dataset)
        .join(Dataset, IngestJob.dataset_id == Dataset.id)
        .where(
            IngestJob.status == "complete",
            IngestJob.user_metadata["manifest_key"].astext == key,
        )
        .order_by(desc(IngestJob.completed_at), desc(IngestJob.created_at))
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        return None
    return row[0], row[1]


async def _validate_prepared_source(
    db: AsyncSession, prepared: ManifestPreparedSource
) -> None:
    allowed = await get_allowed_extensions_list(db)
    if prepared.source.type == "vrt" and ".vrt" not in allowed:
        allowed = [*allowed, ".vrt"]
    validate_file_extension(prepared.source_filename, allowed)


async def _download_http_source(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
) -> str:
    max_size_bytes = (await UPLOAD_MAX_SIZE_MB.get(db)) * 1024 * 1024
    staging_dir = Path(settings.upload_staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    destination = staging_dir / (
        f"manifest_{uuid.uuid4().hex}_{prepared.source_filename}"
    )

    bytes_seen = 0
    # Phase 1061 SEC-S04 (Rule 2): use make_safe_client so per-hop SSRF
    # revalidation applies to manifest HTTP source downloads. Lazy import
    # to preserve the Phase 225 PROCESS-02/04 layering invariant — `processing/`
    # cannot have a module-level import from `app.modules.catalog.*`.
    from app.modules.catalog.sources.security import make_safe_client

    try:
        async with make_safe_client(timeout=60.0) as client:
            async with client.stream("GET", prepared.source_uri) as response:
                response.raise_for_status()
                # fix(#435): `Path.open()` + `file_obj.write()` ran synchronously
                # inside this async loop, stalling the event loop — and therefore job
                # heartbeats, cancellation, and unrelated requests — for the length of
                # a multi-GB download. Writes now go to a worker thread, batched
                # through a 4 MiB buffer so we are not paying a thread handoff per
                # 64 KiB httpx chunk.
                file_obj = await asyncio.to_thread(destination.open, "wb")
                try:
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        bytes_seen += len(chunk)
                        if bytes_seen > max_size_bytes:
                            raise ManifestSourceError(
                                "Manifest source exceeds configured upload size limit"
                            )
                        buffer.extend(chunk)
                        if len(buffer) >= _WRITE_BUFFER_BYTES:
                            await asyncio.to_thread(file_obj.write, bytes(buffer))
                            buffer.clear()
                    if buffer:
                        await asyncio.to_thread(file_obj.write, bytes(buffer))
                finally:
                    await asyncio.to_thread(file_obj.close)
    except ManifestSourceError:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:  # broad: HTTP client / I/O / decompress can throw varied types; map to ManifestSourceError
        destination.unlink(missing_ok=True)
        raise ManifestSourceError(f"Failed to download manifest source: {exc}") from exc

    return str(destination)


async def _stage_source_if_needed(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
    *,
    dry_run: bool,
) -> str | None:
    if prepared.kind == "http":
        if dry_run:
            return None
        return await _download_http_source(db, prepared)
    return prepared.file_path


async def _caller_owns_job(db: AsyncSession, job: IngestJob, user: Identity) -> bool:
    """Owner-or-admin gate for referencing an existing manifest job's ids.

    fix(#430 codex r15): in-flight jobs may have no Dataset row yet, so the
    dataset-level write gate can't run — key ownership on IngestJob.created_by
    instead (same contract as service.py's reupload ownership check).
    """
    if job.created_by is not None and job.created_by == user.id:
        return True
    # Lazy import: processing/ must not import app.modules.catalog.* at module
    # level (PROCESS-02/04 layering invariant).
    from app.modules.catalog.authorization import get_user_roles

    return "admin" in await get_user_roles(db, user)


def _skip_result_for_in_flight(
    dataset: ManifestDataset, job: IngestJob
) -> ManifestApplyEntryResult:
    return ManifestApplyEntryResult(
        dataset_key=dataset.key,
        action="skip",
        job_id=job.id,
        dataset_id=job.dataset_id,
        message="Manifest dataset apply is already queued or running.",
    )


async def _classify_dataset(
    db: AsyncSession,
    dataset: ManifestDataset,
) -> tuple[str, ManifestPreparedSource | None, IngestJob | None, object | None, str]:
    fingerprint = manifest_dataset_fingerprint(dataset)
    if not dataset.sources:
        raise ManifestSourceError("Manifest dataset has no sources")
    prepared = await classify_manifest_source(dataset.sources[0])
    await _validate_prepared_source(db, prepared)

    in_flight = await _latest_in_flight_manifest_job(db, dataset.key)
    if in_flight is not None:
        in_flight_fingerprint = (in_flight.user_metadata or {}).get(
            "manifest_fingerprint"
        )
        if in_flight_fingerprint == fingerprint:
            return "skip_in_flight", prepared, in_flight, None, fingerprint
        raise ManifestSourceError("Manifest dataset key already has an in-flight apply")

    completed = await _latest_completed_manifest_job(db, dataset.key)
    if completed is not None:
        completed_job, existing_dataset = completed
        completed_fingerprint = (completed_job.user_metadata or {}).get(
            "manifest_fingerprint"
        )
        if completed_fingerprint == fingerprint:
            return (
                "skip_complete",
                prepared,
                completed_job,
                existing_dataset,
                fingerprint,
            )
        return "update", prepared, completed_job, existing_dataset, fingerprint

    return "create", prepared, None, None, fingerprint


async def _queue_reupload_job(
    db: AsyncSession,
    job: IngestJob,
    dataset_id: uuid.UUID,
    user: Identity,
    prepared: ManifestPreparedSource,
) -> None:
    task = get_catalog_port().reupload_file_task()
    file_path = job.file_path
    if not file_path:
        raise ManifestSourceError("Manifest reupload job is missing file_path")

    async def _defer_reupload() -> None:
        await defer_async_with_tenant(
            task,
            job_id=str(job.id),
            dataset_id=str(dataset_id),
            file_path=file_path,
            user_id=str(user.id),
        )

    await defer_with_orphan_guard(
        _defer_reupload,
        rollback=make_ingest_job_failed_rollback(job),
        db=db,
    )


async def _create_job_and_queue(
    db: AsyncSession,
    dataset: ManifestDataset,
    prepared: ManifestPreparedSource,
    fingerprint: str,
    user: Identity,
) -> ManifestApplyEntryResult:
    file_path = await _stage_source_if_needed(db, prepared, dry_run=False)
    job = IngestJob(
        source_filename=prepared.source_filename,
        file_path=file_path,
        source_url=None,
        source_layer=prepared.source_layer,
        created_by=user.id,
        status="pending",
        user_metadata=manifest_job_metadata(
            dataset,
            prepared,
            fingerprint=fingerprint,
        ),
    )
    db.add(job)
    await db.flush()
    await db.commit()

    await queue_ingest_job(job, str(user.id), db=db)
    return ManifestApplyEntryResult(
        dataset_key=dataset.key,
        action="create",
        job_id=job.id,
        message="Manifest dataset ingest queued.",
    )


async def _create_reupload_job_and_queue(
    db: AsyncSession,
    dataset: ManifestDataset,
    prepared: ManifestPreparedSource,
    fingerprint: str,
    existing_dataset: object,
    user: Identity,
) -> ManifestApplyEntryResult:
    dataset_id = existing_dataset.id
    file_path = await _stage_source_if_needed(db, prepared, dry_run=False)
    metadata = {
        **manifest_job_metadata(dataset, prepared, fingerprint=fingerprint),
        "reupload": True,
        "dataset_id": str(dataset_id),
    }
    job = IngestJob(
        dataset_id=dataset_id,
        source_filename=prepared.source_filename,
        file_path=file_path,
        source_url=None,
        source_layer=prepared.source_layer,
        created_by=user.id,
        status="pending",
        user_metadata=metadata,
    )
    db.add(job)
    await db.flush()
    await db.commit()

    await _queue_reupload_job(db, job, dataset_id, user, prepared)
    return ManifestApplyEntryResult(
        dataset_key=dataset.key,
        action="update",
        job_id=job.id,
        dataset_id=dataset_id,
        message="Manifest dataset reupload queued.",
    )


def _error_result(dataset: ManifestDataset, exc: Exception) -> ManifestApplyEntryResult:
    message = str(exc)
    return ManifestApplyEntryResult(
        dataset_key=dataset.key,
        action="error",
        message=message,
        errors=[message],
    )


async def _run_entry(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    dataset: ManifestDataset,
) -> ManifestApplyEntryResult:
    (
        classification,
        prepared,
        job,
        existing_dataset,
        fingerprint,
    ) = await _classify_dataset(db, dataset)
    if prepared is None:
        raise ManifestSourceError("Manifest source could not be prepared")

    if classification == "skip_in_flight" and job is not None:
        # fix(#430 codex r15): the skip paths previously returned job/dataset
        # ids for a manifest key owned by ANOTHER user whenever the caller
        # submitted a matching fingerprint — the same enumeration oracle
        # BA-02 closed on the update path. Non-owners get the identical
        # generic error the fingerprint-mismatch path raises, with no ids.
        if not await _caller_owns_job(db, job, user):
            raise ManifestSourceError(
                "Manifest dataset key already has an in-flight apply"
            )
        return _skip_result_for_in_flight(dataset, job)

    if classification == "skip_complete" and job is not None:
        if existing_dataset is not None:
            # fix(#430 codex r15): same gate as the update branch below —
            # raises 404/403 into the per-entry error wrapper, so the skip
            # response cannot disclose another user's job/dataset UUIDs.
            from app.modules.catalog.authorization import (
                check_dataset_write_access,
            )

            await check_dataset_write_access(
                db, existing_dataset, existing_dataset.id, user
            )
        return ManifestApplyEntryResult(
            dataset_key=dataset.key,
            action="skip",
            job_id=job.id,
            dataset_id=job.dataset_id,
            message="Manifest dataset is already up to date.",
        )

    if classification == "update" and existing_dataset is not None:
        # fix(#430 BA-02): manifest_key is globally namespaced and taken from the request
        # body, so an editor could otherwise overwrite (or, via dry_run, enumerate
        # the UUID of) another user's manifest-managed dataset. Gate before the
        # dry-run response too — it otherwise leaks existing_dataset.id.
        # Lazy import: processing/ must not import app.modules.catalog.* at module
        # level (PROCESS-02/04 layering invariant).
        from app.modules.catalog.authorization import check_dataset_write_access

        await check_dataset_write_access(
            db, existing_dataset, existing_dataset.id, user
        )

    if request.dry_run:
        if classification == "create":
            return ManifestApplyEntryResult(
                dataset_key=dataset.key,
                action="create",
                message="Manifest dataset would be created.",
            )
        if classification == "update" and existing_dataset is not None:
            return ManifestApplyEntryResult(
                dataset_key=dataset.key,
                action="update",
                dataset_id=existing_dataset.id,
                message="Manifest dataset would be updated.",
            )

    if classification == "create":
        return await _create_job_and_queue(db, dataset, prepared, fingerprint, user)

    if classification == "update" and existing_dataset is not None:
        return await _create_reupload_job_and_queue(
            db, dataset, prepared, fingerprint, existing_dataset, user
        )

    raise ManifestSourceError("Manifest dataset could not be classified")


async def apply_manifest(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
) -> ManifestApplyResponse:
    """Apply a manifest payload through existing ingest/reupload queues."""
    results: list[ManifestApplyEntryResult] = []
    for dataset in request.datasets:
        try:
            results.append(await _run_entry(db, request, user, dataset))
        except (ManifestSourceError, ValueError, HTTPException) as exc:
            await db.rollback()
            results.append(_error_result(dataset, exc))
        except Exception as exc:  # broad: per-entry isolation — any unexpected failure is recorded as that entry's error
            await db.rollback()
            results.append(_error_result(dataset, exc))

    return ManifestApplyResponse(
        accepted=any(result.action != "error" for result in results),
        dry_run=request.dry_run,
        results=results,
    )
