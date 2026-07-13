"""Service entry point for applying manifest v1 payloads."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi import HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.async_io import run_in_thread_draining
from app.core.config import settings
from app.core.db.tenant_session import defer_async_with_tenant
from app.core.identity import Identity
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB, get_allowed_extensions_list
from app.platform.extensions import get_catalog_port, get_processing_port
from app.platform.extensions.entitlement import enforce_limit
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


@dataclass(frozen=True)
class _ManifestCaller:
    """Rollback-stable identity subset used by the per-entry apply loop."""

    id: uuid.UUID


@dataclass
class _ManifestQuotaReservation:
    """Request-local admission ledger for jobs not yet visible in catalog usage."""

    bytes_admitted: int = 0
    datasets_admitted: int = 0

    def reserve(self, *, incoming_bytes: int, creates_dataset: bool) -> None:
        self.bytes_admitted += incoming_bytes
        if creates_dataset:
            self.datasets_admitted += 1

    def release(self, *, incoming_bytes: int, creates_dataset: bool) -> None:
        self.bytes_admitted = max(0, self.bytes_admitted - incoming_bytes)
        if creates_dataset:
            self.datasets_admitted = max(0, self.datasets_admitted - 1)


@dataclass(frozen=True)
class _StagedManifestSource:
    file_path: str
    incoming_bytes: int


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
        .options(joinedload(Dataset.record))
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
    validate_file_extension(prepared.source_filename, allowed)


async def _authorize_prepared_source(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
    user: Identity,
) -> None:
    """Restrict unowned raw seed paths to administrators.

    Local staging paths and same-bucket object keys do not carry a database
    ownership record. Treating knowledge of a path as authorization turns the
    ingest worker into a cross-user storage reader. They remain available as an
    explicit operator-seed workflow, while ordinary upload users use HTTPS
    sources (which retain the shared SSRF validation and redirect hooks).
    """
    if prepared.kind == "http":
        return

    from app.core.tenancy import is_multi_tenant

    if is_multi_tenant():
        raise ManifestSourceError(
            "Raw local and same-bucket manifest seed sources are disabled in "
            "multi-tenant mode because they have no tenant ownership metadata. "
            "Use an HTTPS source or the standard tenant-scoped upload workflow."
        )

    # Lazy import preserves the processing -> catalog layering boundary.
    from app.modules.catalog.authorization import get_user_roles

    if "admin" not in await get_user_roles(db, user):
        raise ManifestSourceError(
            "Local staging and same-bucket manifest sources are admin-only "
            "operator seed inputs because they have no ownership metadata. "
            "Use an HTTPS source or upload the file through the standard "
            "upload workflow."
        )


async def _download_http_source(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
    *,
    quota_byte_limit: int | None = None,
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
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared_size = int(content_length)
                    except ValueError:
                        declared_size = None
                    if declared_size is not None and declared_size >= 0:
                        if declared_size > max_size_bytes:
                            raise ManifestSourceError(
                                "Manifest source exceeds configured upload size limit"
                            )
                        if (
                            quota_byte_limit is not None
                            and declared_size > quota_byte_limit
                        ):
                            raise ManifestSourceError(
                                "Manifest source exceeds the remaining storage quota"
                            )
                # fix(#435): `Path.open()` + `file_obj.write()` ran synchronously
                # inside this async loop, stalling the event loop — and therefore job
                # heartbeats, cancellation, and unrelated requests — for the length of
                # a multi-GB download. Writes now go to a worker thread, batched
                # through a 4 MiB buffer so we are not paying a thread handoff per
                # 64 KiB httpx chunk.
                # fix(#435 codex r4): each threaded write/close is drained on
                # cancellation (run_in_thread_draining), so worker shutdown or a client
                # disconnect cannot return while a thread still owns the staged fd and
                # race the unlink below. `bytes(buffer)` snapshots before the thread
                # reads it, so the following `buffer.clear()` is safe.
                file_obj = await run_in_thread_draining(destination.open, "wb")
                try:
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        bytes_seen += len(chunk)
                        if bytes_seen > max_size_bytes:
                            raise ManifestSourceError(
                                "Manifest source exceeds configured upload size limit"
                            )
                        if (
                            quota_byte_limit is not None
                            and bytes_seen > quota_byte_limit
                        ):
                            raise ManifestSourceError(
                                "Manifest source exceeds the remaining storage quota"
                            )
                        buffer.extend(chunk)
                        if len(buffer) >= _WRITE_BUFFER_BYTES:
                            await run_in_thread_draining(file_obj.write, bytes(buffer))
                            buffer.clear()
                    if buffer:
                        await run_in_thread_draining(file_obj.write, bytes(buffer))
                finally:
                    await run_in_thread_draining(file_obj.close)
    except ManifestSourceError:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:  # broad: HTTP client / I/O / decompress can throw varied types; map to ManifestSourceError
        destination.unlink(missing_ok=True)
        from app.core.url_redaction import redact_url_credentials

        raise ManifestSourceError(
            f"Failed to download manifest source: {redact_url_credentials(str(exc))}"
        ) from exc
    except BaseException:
        # fix(#435 codex r4): cancellation/shutdown. The `finally` above already
        # drained the close, so no thread owns the fd — drop the partial staged file.
        destination.unlink(missing_ok=True)
        raise

    return str(destination)


async def _stage_source_if_needed(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
    *,
    dry_run: bool,
    quota_byte_limit: int | None = None,
) -> str | None:
    if prepared.kind == "http":
        if dry_run:
            return None
        return await _download_http_source(
            db,
            prepared,
            quota_byte_limit=quota_byte_limit,
        )
    if prepared.kind == "local":
        if dry_run or prepared.file_path is None:
            return prepared.file_path
        import shutil

        source_path = Path(prepared.file_path)
        owned_copy = Path(settings.upload_staging_dir) / (
            f"manifest_{uuid.uuid4().hex}_{prepared.source_filename}"
        )
        try:
            await run_in_thread_draining(shutil.copyfile, source_path, owned_copy)
        except BaseException:
            owned_copy.unlink(missing_ok=True)
            raise
        return str(owned_copy)
    return prepared.file_path


async def _manifest_source_size_bytes(
    prepared: ManifestPreparedSource,
    file_path: str,
) -> int:
    """Return the authoritative byte size for a prepared manifest source."""
    try:
        if prepared.kind == "storage":
            from app.platform.storage import get_storage

            return await get_storage().size(file_path)

        candidate = Path(file_path)
        if prepared.kind == "local" and not candidate.is_absolute():
            staging_candidate = Path(settings.upload_staging_dir) / candidate
            if staging_candidate.exists() or not candidate.exists():
                candidate = staging_candidate
        stat_result = await run_in_thread_draining(candidate.stat)
        return stat_result.st_size
    except (OSError, RuntimeError) as exc:
        raise ManifestSourceError(
            f"Manifest source is not available for quota admission: {exc}"
        ) from exc


def _cleanup_downloaded_source(
    prepared: ManifestPreparedSource, file_path: str
) -> None:
    if prepared.kind == "http" or (
        prepared.kind == "local" and file_path != prepared.file_path
    ):
        Path(file_path).unlink(missing_ok=True)


async def _stage_source_and_check_quota(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
    user: Identity,
    request: Request,
    *,
    creates_dataset: bool,
    reservation: _ManifestQuotaReservation,
) -> _StagedManifestSource:
    """Preflight quota, then stage, size, and admit a manifest source."""
    # Check the cheap aggregate before opening an untrusted remote response.
    # The same snapshot supplies a hard byte budget for streaming, so a caller
    # at (or near) quota cannot force the server to download a whole object
    # merely to discover that it cannot be admitted.
    from app.modules.quota.service import get_user_quota_usage

    usage = await get_user_quota_usage(db, user.id)
    if (
        creates_dataset
        and usage.count_cap > 0
        and usage.dataset_count + reservation.datasets_admitted >= usage.count_cap
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Dataset quota exceeded: "
                f"{usage.dataset_count + reservation.datasets_admitted} of "
                f"{usage.count_cap} datasets used"
            ),
        )

    quota_byte_limit = (
        max(
            usage.storage_cap - usage.bytes_used - reservation.bytes_admitted,
            0,
        )
        if usage.storage_cap > 0
        else None
    )
    file_path = await _stage_source_if_needed(
        db,
        prepared,
        dry_run=False,
        quota_byte_limit=quota_byte_limit,
    )
    if file_path is None:
        raise ManifestSourceError("Manifest source could not be staged")

    try:
        incoming_bytes = await _manifest_source_size_bytes(prepared, file_path)
        fresh_usage = await get_user_quota_usage(db, user.id)
        projected_bytes = (
            fresh_usage.bytes_used + reservation.bytes_admitted + incoming_bytes
        )
        projected_count = (
            fresh_usage.dataset_count
            + reservation.datasets_admitted
            + (1 if creates_dataset else 0)
        )
        if fresh_usage.storage_cap > 0 and projected_bytes > fresh_usage.storage_cap:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Storage quota exceeded: used "
                    f"{fresh_usage.bytes_used + reservation.bytes_admitted} of "
                    f"{fresh_usage.storage_cap} bytes (adding {incoming_bytes} bytes)"
                ),
            )
        if (
            creates_dataset
            and fresh_usage.count_cap > 0
            and projected_count > fresh_usage.count_cap
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Dataset quota exceeded: "
                    f"{fresh_usage.dataset_count + reservation.datasets_admitted} of "
                    f"{fresh_usage.count_cap} datasets used"
                ),
            )

        # Lazy import preserves the processing -> modules layering boundary.
        if creates_dataset:
            from app.modules.quota.service import check_upload_quota

            await check_upload_quota(db, user.id, incoming_bytes, request)
        await enforce_limit(request, "storage_bytes", projected_bytes)
        if creates_dataset:
            await enforce_limit(request, "dataset_count", projected_count)
    except BaseException:
        # HTTP downloads are owned by this attempt. Raw operator seeds are not,
        # and must never be deleted merely because admission was denied.
        _cleanup_downloaded_source(prepared, file_path)
        raise

    reservation.reserve(
        incoming_bytes=incoming_bytes,
        creates_dataset=creates_dataset,
    )
    return _StagedManifestSource(
        file_path=file_path,
        incoming_bytes=incoming_bytes,
    )


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
    user: Identity,
) -> tuple[str, ManifestPreparedSource | None, IngestJob | None, object | None, str]:
    fingerprint = manifest_dataset_fingerprint(dataset)
    if not dataset.sources:
        raise ManifestSourceError("Manifest dataset has no sources")
    prepared = await classify_manifest_source(dataset.sources[0])
    await _validate_prepared_source(db, prepared)
    await _authorize_prepared_source(db, prepared, user)

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
            attempt_id=str(job.attempt_id),
            dataset_id=str(dataset_id),
            file_path=file_path,
            user_id=str(user.id),
        )

    await defer_with_orphan_guard(
        _defer_reupload,
        rollback=make_ingest_job_failed_rollback(job),
        db=db,
    )


def _validate_existing_dataset_update(
    existing_dataset: object,
    prepared: ManifestPreparedSource,
) -> None:
    """Reject manifest updates the reupload worker cannot implement safely."""
    record = getattr(existing_dataset, "record", None)
    record_type = getattr(record, "record_type", None)

    # Raster replacement has different asset/version semantics and is not
    # implemented by the vector-only reupload task used by manifest updates.
    if prepared.source.type == "raster_cog":
        raise ManifestSourceError(
            "Manifest raster updates are not supported; create a new raster "
            "dataset instead."
        )
    if record_type not in {"vector_dataset", "table"}:
        raise ManifestSourceError(
            f"Manifest vector updates cannot replace an existing {record_type or 'unknown'} dataset."
        )


async def _create_job_and_queue(
    db: AsyncSession,
    dataset: ManifestDataset,
    prepared: ManifestPreparedSource,
    fingerprint: str,
    user: Identity,
    request: Request,
    reservation: _ManifestQuotaReservation,
) -> ManifestApplyEntryResult:
    staged = await _stage_source_and_check_quota(
        db,
        prepared,
        user,
        request,
        creates_dataset=True,
        reservation=reservation,
    )
    file_path = staged.file_path
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
    try:
        await db.flush()
        await db.commit()
    except BaseException:
        # Until the job is durable, no worker/retry owns an HTTP staging file.
        reservation.release(
            incoming_bytes=staged.incoming_bytes,
            creates_dataset=True,
        )
        _cleanup_downloaded_source(prepared, file_path)
        raise

    try:
        await queue_ingest_job(job, str(user.id), db=db)
    except BaseException:
        reservation.release(
            incoming_bytes=staged.incoming_bytes,
            creates_dataset=True,
        )
        _cleanup_downloaded_source(prepared, file_path)
        raise
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
    request: Request,
    reservation: _ManifestQuotaReservation,
) -> ManifestApplyEntryResult:
    _validate_existing_dataset_update(existing_dataset, prepared)
    dataset_id = existing_dataset.id
    staged = await _stage_source_and_check_quota(
        db,
        prepared,
        user,
        request,
        creates_dataset=False,
        reservation=reservation,
    )
    file_path = staged.file_path
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
    try:
        await db.flush()
        await db.commit()
    except BaseException:
        reservation.release(
            incoming_bytes=staged.incoming_bytes,
            creates_dataset=False,
        )
        _cleanup_downloaded_source(prepared, file_path)
        raise

    try:
        await _queue_reupload_job(db, job, dataset_id, user, prepared)
    except BaseException:
        reservation.release(
            incoming_bytes=staged.incoming_bytes,
            creates_dataset=False,
        )
        _cleanup_downloaded_source(prepared, file_path)
        raise
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
    http_request: Request,
    reservation: _ManifestQuotaReservation,
) -> ManifestApplyEntryResult:
    (
        classification,
        prepared,
        job,
        existing_dataset,
        fingerprint,
    ) = await _classify_dataset(db, dataset, user)
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
        # Run after authorization (to avoid leaking another user's dataset
        # type) but before dry-run reporting, staging, or queue creation.
        _validate_existing_dataset_update(existing_dataset, prepared)

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
        return await _create_job_and_queue(
            db,
            dataset,
            prepared,
            fingerprint,
            user,
            http_request,
            reservation,
        )

    if classification == "update" and existing_dataset is not None:
        return await _create_reupload_job_and_queue(
            db,
            dataset,
            prepared,
            fingerprint,
            existing_dataset,
            user,
            http_request,
            reservation,
        )

    raise ManifestSourceError("Manifest dataset could not be classified")


async def apply_manifest(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    http_request: Request,
) -> ManifestApplyResponse:
    """Apply a manifest payload through existing ingest/reupload queues."""
    # AsyncSession.rollback() expires ORM instances. Keep the caller id outside
    # that lifecycle so one rejected entry cannot make the next entry trigger a
    # synchronous lazy load (MissingGreenlet) while checking authorization.
    caller = cast(Identity, _ManifestCaller(id=user.id))
    results: list[ManifestApplyEntryResult] = []
    reservation = _ManifestQuotaReservation()
    for dataset in request.datasets:
        try:
            results.append(
                await _run_entry(
                    db,
                    request,
                    caller,
                    dataset,
                    http_request,
                    reservation,
                )
            )
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
