"""Service entry point for applying manifest payloads."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from fastapi import HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm import joinedload

from app.core.async_io import (
    run_in_thread_draining,
    run_in_thread_draining_capture_cancel,
)
from app.core.config import settings
from app.core.failure_reason import prefixed_failure_reason
from app.core.geo import unknown_srid_refusal
from app.core.db.tenant_session import defer_async_with_tenant
from app.core.identity import Identity, IdentitySnapshot
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB, get_allowed_extensions_list
from app.platform.dataset_origin import classify_origin
from app.platform.extensions import get_catalog_port, get_processing_port
from app.platform.extensions.entitlement import enforce_limit
from app.platform.jobs.defer_guard import (
    defer_with_orphan_guard,
    reset_session_for_settlement,
    settle_ingest_job_failed,
)
from app.platform.jobs.sweep import JOB_TIMEOUT_SECONDS
from app.platform.catalog_locks import CatalogLockConflict
from app.platform.refresh.service import DatasetBusyError, create_pending_run
from app.platform.request_credential import (
    refuse_publish_key,
)

from app.platform.jobs import ledger
from app.platform.jobs.models import (
    ADMITTED_RAW_SOURCE_METADATA_KEY,
    MANIFEST_FINGERPRINT_METADATA_KEY,
    IngestJob,
)
from app.processing.ingest.manifest_dataset_fields import (
    ManifestEntryFields,
    ManifestEntryRefused,
    attach_unchanged_entry,
    raster_not_replaced_message,
    note_more_visible,
    answer_as_the_job_ends,
    refuse_a_share_its_job_refuses,
    resolve_entry_groups,
    report_entry,
    resolve_entry_collection,
)
from app.processing.ingest.manifest_links import describe_results
from app.processing.ingest.manifest_maps import run_manifest_maps
from app.processing.ingest.manifest_publication import (
    decide_publication,
    is_version_2,
    entry_job_metadata,
    judge_update,
    in_flight_job_matches,
    held_job_matches,
)
from app.processing.ingest.manifest_reservation import (
    RESERVATION_LOST_MESSAGE,
    bind_reservation_to_staged_source,
    downloading_stage_marker,
    expire_stale_manifest_reservations,
    held_entry,
    latest_in_flight_manifest_job,
    lock_manifest_key,
    release_manifest_reservation,
    staged_source_is_referenced,
)
from app.processing.ingest.publication import WriteAccessRevoked
from app.processing.ingest.manifest_schemas import (
    ManifestApplyEntryResult,
    ManifestApplyRequest,
    ManifestApplyResponse,
    ManifestDataset,
)
from app.processing.ingest.manifest_sources import (
    ManifestPreparedSource,
    ManifestSourceError,
    claim_upload_source,
    manifest_dataset_fingerprint,
    parse_manifest_crs,
    prepare_manifest_source,
    publication_to_catalog_fields,
    refuse_used_upload,
    skip_complete_message,
    _validate_existing_dataset_update,
    validate_publication_intent,
)
from app.processing.ingest.pointcloud import require_pointcloud_file
from app.processing.ingest.service import queue_ingest_job, validate_file_extension

# Batch download writes so a 64 KiB httpx chunk doesn't cost one
# `asyncio.to_thread` handoff each; 4 MiB amortizes the hop across ~64 chunks.
_WRITE_BUFFER_BYTES = 4 * 1024 * 1024

# Total wall clock for staging one entry. Derived from the lease the
# reservation is judged by, so the budget and its judge cannot drift apart.
MANIFEST_STAGE_MAX_SECONDS = JOB_TIMEOUT_SECONDS // 2

# Total wall clock for admitting an already-staged entry against quota and
# binding its reservation. stage + admit < lease, with margin.
MANIFEST_ADMIT_MAX_SECONDS = JOB_TIMEOUT_SECONDS // 4

log = structlog.get_logger()


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


@dataclass(frozen=True)
class _ReservedEntry:
    """A committed reservation plus everything staging it needs afterwards.

    Plain values beyond the job row itself: the session is free to serve
    another request between the reservation commit and the staging bind.
    """

    job: IngestJob
    prepared: ManifestPreparedSource
    dataset_id: uuid.UUID | None
    max_size_bytes: int
    quota_byte_limit: int | None

    @property
    def creates_dataset(self) -> bool:
        """An entry with no existing dataset to replace is creating one."""
        return self.dataset_id is None


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
    require_pointcloud_file(None, prepared.source_filename)


async def _authorize_prepared_source(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
    user: Identity,
) -> None:
    """Restrict unowned raw seed paths to administrators.

    Local staging paths and same-bucket object keys carry no database
    ownership record; treating knowledge of a path as authorization would
    turn the ingest worker into a cross-user storage reader. They remain an
    admin-only operator-seed workflow, while ordinary users use HTTPS
    sources (shared SSRF validation and redirect hooks) or their own uploads.
    """
    if prepared.kind in ("http", "upload"):
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


async def _upload_max_size_bytes(db: AsyncSession) -> int:
    return (await UPLOAD_MAX_SIZE_MB.get(db)) * 1024 * 1024


def _owned_staging_path(job_id: uuid.UUID, prepared: ManifestPreparedSource) -> Path:
    """The staged copy a reservation writes, named for its committed job row.

    The local staging reconciler attributes a ``{job id}_`` file to that row,
    so a copy left before the reservation bound it is still reclaimable.
    """
    return Path(settings.upload_staging_dir) / f"{job_id}_{prepared.source_filename}"


async def _download_http_source(
    prepared: ManifestPreparedSource,
    *,
    job_id: uuid.UUID,
    max_size_bytes: int,
    quota_byte_limit: int | None = None,
) -> str:
    """Stream one manifest source to staging. Takes no database session.

    A session here would hold a pooled connection for the download's length;
    the caller reads the size ceiling before committing.
    """
    destination = _owned_staging_path(job_id, prepared)
    destination.parent.mkdir(parents=True, exist_ok=True)

    bytes_seen = 0
    # Rule 2 (AGENTS.md): make_safe_client revalidates SSRF on every redirect
    # hop of a manifest HTTP download and pins the address at connect time.
    from app.platform.security import make_safe_client

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
                # Sync `Path.open()`/`write()` would stall the event loop
                # (and job heartbeats, cancellation, other requests) for a
                # multi-GB download, so writes go to a worker thread, batched
                # through the 4 MiB buffer. The completed open() handle is
                # kept even if cancellation arrives mid-open, and closed
                # before propagating; otherwise it's never assigned and the
                # finally block can't reach it.
                (
                    file_obj,
                    open_cancellation,
                ) = await run_in_thread_draining_capture_cancel(destination.open, "wb")
                if open_cancellation is not None:
                    try:
                        await run_in_thread_draining(file_obj.close)
                    finally:
                        destination.unlink(missing_ok=True)
                    raise open_cancellation

                # Each threaded write/close is drained on cancellation, so no
                # thread still owns the staged fd to race the unlink below.
                # `bytes(buffer)` snapshots before the thread reads it, so
                # the following `buffer.clear()` is safe.
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
        # Cancellation or shutdown. The `finally` above already drained the
        # close, so no thread owns the fd; drop the partial staged file.
        destination.unlink(missing_ok=True)
        raise

    return str(destination)


async def _stage_source_if_needed(
    prepared: ManifestPreparedSource,
    *,
    job_id: uuid.UUID,
    dry_run: bool,
    max_size_bytes: int,
    quota_byte_limit: int | None = None,
) -> str | None:
    """Put one manifest source where ingest can read it, under a total deadline.

    httpx's 60s clock is per read, so a trickling source has no bound of its
    own, and staging must finish inside the reservation's lease.
    """
    try:
        async with asyncio.timeout(MANIFEST_STAGE_MAX_SECONDS):
            return await _stage_source(
                prepared,
                job_id=job_id,
                dry_run=dry_run,
                max_size_bytes=max_size_bytes,
                quota_byte_limit=quota_byte_limit,
            )
    except TimeoutError as exc:
        raise ManifestSourceError(
            "Manifest source did not finish staging within "
            f"{MANIFEST_STAGE_MAX_SECONDS} seconds"
        ) from exc


async def _stage_source(
    prepared: ManifestPreparedSource,
    *,
    job_id: uuid.UUID,
    dry_run: bool,
    max_size_bytes: int,
    quota_byte_limit: int | None = None,
) -> str | None:
    if prepared.kind == "http":
        if dry_run:
            return None
        return await _download_http_source(
            prepared,
            job_id=job_id,
            max_size_bytes=max_size_bytes,
            quota_byte_limit=quota_byte_limit,
        )
    if prepared.kind == "local":
        if dry_run or prepared.file_path is None:
            return prepared.file_path
        import shutil

        source_path = Path(prepared.file_path)
        owned_copy = _owned_staging_path(job_id, prepared)
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
        if prepared.upload is not None:
            return prepared.upload.size_bytes
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


async def _preflight_quota(
    db: AsyncSession,
    user: Identity,
    *,
    replaces: uuid.UUID | None,
    quota: _ManifestQuotaReservation,
) -> int | None:
    """Refuse an over-quota caller, and derive the streaming byte budget.

    Runs before the reservation is inserted, so a refused entry leaves no
    row behind and its upload unclaimed, for the same apply to use once the
    account has room. The same snapshot supplies a hard byte budget for
    streaming, so a caller near quota can't force a full download just to
    discover it can't be admitted. A replacement's budget counts the credit
    its admission takes. Returns None when uncapped.
    """
    from app.modules.quota.service import (
        check_dataset_count_quota,
        get_user_quota_usage,
        replacement_credit_bytes,
    )

    if replaces is None:
        await check_dataset_count_quota(
            db, user.id, None, admitted=quota.datasets_admitted
        )
    usage = await get_user_quota_usage(db, user.id)
    if usage.storage_cap <= 0:
        return None
    credited = (
        0
        if replaces is None
        else await replacement_credit_bytes(db, replaces, owned_by=user.id)
    )
    return max(
        usage.storage_cap - usage.bytes_used - quota.bytes_admitted + credited,
        0,
    )


async def _admit_staged_source(
    db: AsyncSession,
    prepared: ManifestPreparedSource,
    user: Identity,
    request: Request,
    *,
    file_path: str,
    replaces: uuid.UUID | None,
    quota: _ManifestQuotaReservation,
) -> _StagedManifestSource:
    """Size a staged manifest source and admit it against live quota.

    A replacement takes the re-upload doors' credit, while the caller still
    owns the dataset: ownership is rechecked under the row lock only after
    this, and a transfer during staging must not lend the caller its bytes.
    """
    # Lazy import preserves the processing -> modules layering boundary.
    from app.modules.quota.service import (
        check_dataset_count_quota,
        check_replacement_quota,
        check_upload_quota,
        get_user_quota_usage,
    )

    incoming_bytes = await _manifest_source_size_bytes(prepared, file_path)
    if replaces is not None:
        credited = await check_replacement_quota(
            db,
            user.id,
            incoming_bytes,
            request,
            dataset_id=replaces,
            admitted=quota.bytes_admitted,
            owned_by=user.id,
        )
        # A smaller file frees nothing until its job publishes, so it lends
        # no room to the manifest's later entries.
        charged = max(0, incoming_bytes - credited)
        quota.reserve(incoming_bytes=charged, creates_dataset=False)
        return _StagedManifestSource(file_path=file_path, incoming_bytes=charged)

    fresh_usage = await get_user_quota_usage(db, user.id)
    projected_bytes = fresh_usage.bytes_used + quota.bytes_admitted + incoming_bytes
    if fresh_usage.storage_cap > 0 and projected_bytes > fresh_usage.storage_cap:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Storage quota exceeded: used "
                f"{fresh_usage.bytes_used + quota.bytes_admitted} of "
                f"{fresh_usage.storage_cap} bytes (adding {incoming_bytes} bytes)"
            ),
        )

    await check_upload_quota(db, user.id, incoming_bytes, request)
    # Asked again: staging can take as long as a download, and the
    # preflight's answer is that old.
    await check_dataset_count_quota(
        db, user.id, request, admitted=quota.datasets_admitted
    )
    await enforce_limit(request, "storage_bytes", projected_bytes)

    quota.reserve(incoming_bytes=incoming_bytes, creates_dataset=True)
    return _StagedManifestSource(file_path=file_path, incoming_bytes=incoming_bytes)


# One wording for every refusal of a key the caller doesn't own, so the answer
# never says whether the key's dataset is visible to the caller.
MANIFEST_KEY_NOT_OWNED = (
    "This manifest key belongs to a dataset or apply you don't own. "
    "Use a different key, or have the dataset transferred to you first."
)


async def _admit_key_dataset(db: AsyncSession, dataset: Any, user: Identity) -> None:
    """Admit the caller to the dataset a manifest key already names.

    Keys are global, so write access alone would let a key someone else
    created steer an admin's source into that person's dataset. Only the
    dataset's owner may update or reference it through its key.
    """
    # Lazy import: processing/ must not import app.modules.catalog.* at module
    # level (layering invariant).
    from app.modules.catalog.authorization import check_dataset_write_access

    # The row may have been loaded before a transfer or a delete committed.
    try:
        await db.refresh(dataset.record, attribute_names=["created_by"])
    except InvalidRequestError as exc:
        raise ManifestSourceError(MANIFEST_KEY_NOT_OWNED) from exc
    if dataset.record.created_by != user.id:
        raise ManifestSourceError(MANIFEST_KEY_NOT_OWNED)
    try:
        await check_dataset_write_access(db, dataset, dataset.id, user)
    except HTTPException as exc:
        raise ManifestSourceError(MANIFEST_KEY_NOT_OWNED) from exc


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
    *,
    dry_run: bool = False,
    fields: ManifestEntryFields | None = None,
) -> tuple[str, ManifestPreparedSource | None, IngestJob | None, object | None, str]:
    fingerprint = manifest_dataset_fingerprint(dataset)
    if not dataset.sources:
        raise ManifestSourceError("Manifest dataset has no sources")
    # Reject an intent the live workflow extension does not define before any
    # staging, download or queue work, and before the dry_run early return,
    # which is the branch operators use to validate a manifest.
    validate_publication_intent(dataset.publication)
    # The manifest's own spelling of srid_override, refused here so a dry run
    # reports it too.
    crs_refusal = await unknown_srid_refusal(
        db,
        parse_manifest_crs(dataset.metadata.crs if dataset.metadata else None),
        field="metadata.crs",
    )
    if crs_refusal:
        raise ManifestSourceError(crs_refusal)
    # A public visibility goes through the same admin gate as every
    # visibility-accepting API mutation, raising 403 for a non-admin when
    # restrict_public_visibility is on. Checked before staging so dry_run
    # reports it too. Version 2 gates the entry's own visibility, and acts on
    # a refusal only for an entry that writes; version 1 gates the one its
    # intent implies. Local import: processing/ must not import
    # app.modules.catalog.* at module level.
    from app.modules.catalog.authorization import check_public_visibility_allowed

    visibility, _ = publication_to_catalog_fields(dataset.publication)
    try:
        await check_public_visibility_allowed(
            db, user, visibility if fields is None else dataset.visibility
        )
    except HTTPException as exc:
        if fields is None or exc.status_code != 403:
            raise
        fields.may_set_public = False
    prepared = await prepare_manifest_source(db, dataset, user)
    await _validate_prepared_source(db, prepared)
    await _authorize_prepared_source(db, prepared, user)

    # From here to the reservation commit is one locked critical section on
    # this key, and nothing inside it may touch the network. The SSRF
    # validation above is deliberately outside it.
    await lock_manifest_key(db, dataset.key)
    if not dry_run:
        # A preview writes nothing, so it does not settle another caller's
        # abandoned reservation. The cost is that a dry run can still report
        # an entry as in flight where an apply would take it.
        await expire_stale_manifest_reservations(db, dataset.key)

    in_flight = await latest_in_flight_manifest_job(db, dataset.key)
    if in_flight is not None:
        # Before the fingerprint comparison, so a non-owner can't learn whether
        # their entry matches someone else's apply.
        if in_flight.created_by != user.id:
            raise ManifestSourceError(MANIFEST_KEY_NOT_OWNED)
        in_flight_fingerprint = (in_flight.user_metadata or {}).get(
            MANIFEST_FINGERPRINT_METADATA_KEY
        )
        if in_flight_fingerprint == fingerprint:
            return "skip_in_flight", prepared, in_flight, None, fingerprint
        raise ManifestSourceError("Manifest dataset key already has an in-flight apply")

    completed = await _latest_completed_manifest_job(db, dataset.key)
    if completed is not None:
        completed_job, existing_dataset = completed
        completed_fingerprint = (completed_job.user_metadata or {}).get(
            MANIFEST_FINGERPRINT_METADATA_KEY
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


async def _admit_refresh_run(
    db: AsyncSession, job: IngestJob, dataset_id: uuid.UUID, user: Identity
) -> None:
    """Take the dataset's one active-run slot for this update, then its
    catalog rows, the order a re-upload commit takes them in.

    Raises ``DatasetBusyError`` while the dataset has another active run or
    another writer holds its catalog rows past the lock budget;
    ``WriteAccessRevoked`` when the caller has lost the dataset, or is no
    longer the admin a raw seed source needs; and ``ManifestSourceError``
    when the dataset has passed to another owner. ``trigger`` is ``api``.
    """
    from app.modules.catalog.authorization import lock_dataset_rows_for_write

    raw_source = bool((job.user_metadata or {}).get(ADMITTED_RAW_SOURCE_METADATA_KEY))
    dataset = await get_processing_port().get_dataset(db, dataset_id)
    if dataset is None:
        raise ManifestSourceError(
            "The dataset this entry updates was deleted while its source was "
            "being staged."
        )
    await create_pending_run(
        db,
        dataset_id=dataset_id,
        origin_kind="upload",
        trigger="api",
        triggered_by=user.id,
        ingest_job_id=job.id,
        feature_count_before=dataset.feature_count,
    )
    try:
        await lock_dataset_rows_for_write(db, dataset)
    except CatalogLockConflict as exc:
        raise DatasetBusyError(str(exc)) from exc
    except HTTPException as exc:
        raise WriteAccessRevoked from exc
    # Rechecked under the lock: the owner and the binding may have changed
    # while the source was being staged, and a key stays its owner's alone.
    await db.refresh(dataset, attribute_names=["source_format"])
    await db.refresh(dataset.record, attribute_names=["created_by"])
    if dataset.record.created_by != user.id:
        raise ManifestSourceError(MANIFEST_KEY_NOT_OWNED)
    try:
        _refuse_publish_key_irreversible_replace(db, dataset)
    except HTTPException as exc:
        raise ManifestSourceError(exc.detail["message"]) from exc
    if raw_source and "admin" not in await get_processing_port().get_user_roles(
        db, user
    ):
        raise WriteAccessRevoked


async def _fail_unqueued_job(job: IngestJob, exc: BaseException) -> None:
    """Fail a staged job the queue never took, and the run admitted with it.

    The job ledger fails the run only when the job write lands: a miss means
    a worker or a cancel owns both rows, and a run the worker claimed must
    stay its own.
    """
    await settle_ingest_job_failed(
        job, exc, message_prefix="Failed to queue manifest job"
    )


async def _queue_reupload_job(
    db: AsyncSession,
    job: IngestJob,
    dataset_id: uuid.UUID,
    user: Identity,
    prepared: ManifestPreparedSource,
) -> None:
    port = get_catalog_port()
    if prepared.file_type == "raster":
        # Under a name earlier workers lack: their raster replacement skips
        # the manifest's record fields.
        from app.processing.ingest.tasks import reupload_manifest_raster

        task = reupload_manifest_raster
    elif is_version_2(job.user_metadata or {}):
        task = port.manifest_v2_reupload_task()
    else:
        task = port.reupload_file_task()
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
        rollback=lambda exc: _fail_unqueued_job(job, exc),
        db=db,
        job=job,
    )


def _refuse_publish_key_irreversible_replace(
    db: AsyncSession, existing_dataset
) -> None:
    # A replaced raster keeps no previous version. A vector update replaces the
    # source binding, and a restore can bring back only an upload's or a drawn
    # layer's.
    if existing_dataset.record.record_type == "raster_dataset":
        refuse_publish_key(db, "A publish key can't replace a raster dataset")
    origin = classify_origin(
        existing_dataset.source_format, existing_dataset.record.record_type
    )
    if origin not in ("upload", "created"):
        refuse_publish_key(
            db, "A publish key can't replace a dataset bound to a remote origin"
        )


def _refuse_unreplaceable_update(
    db: AsyncSession,
    dataset: ManifestDataset,
    existing_dataset,
    prepared: ManifestPreparedSource,
    fields: ManifestEntryFields | None,
) -> None:
    """Refuse an update whose source can't replace the dataset's data, or one
    a publish key may not make. A version 2 raster refusal is error A054."""
    _validate_existing_dataset_update(existing_dataset, prepared)
    try:
        _refuse_publish_key_irreversible_replace(db, existing_dataset)
    except HTTPException as exc:
        if fields is None or prepared.file_type != "raster":
            raise ManifestSourceError(exc.detail["message"]) from exc
        raise ManifestEntryRefused([raster_not_replaced_message(dataset)]) from exc


def _job_metadata(
    db: AsyncSession,
    dataset: ManifestDataset,
    prepared: ManifestPreparedSource,
    fingerprint: str,
    user: Identity,
    fields: ManifestEntryFields | None,
    dataset_id: uuid.UUID | None,
) -> dict[str, object]:
    from app.modules.catalog.authorization import admitted_public_visibility

    # What this entry's restricted-public gate decided, not a later read.
    admitted = admitted_public_visibility(db, user.id)
    return {
        **entry_job_metadata(
            db,
            dataset,
            prepared,
            fingerprint,
            fields,
            dataset_id,
            admitted_public=admitted,
        )
    }


async def _reserve_entry(
    db: AsyncSession,
    dataset: ManifestDataset,
    prepared: ManifestPreparedSource,
    fingerprint: str,
    user: Identity,
    *,
    dataset_id: uuid.UUID | None,
    quota: _ManifestQuotaReservation,
    fields: ManifestEntryFields | None = None,
) -> _ReservedEntry:
    """Commit this key's claim, and everything staging needs, in one transaction.

    The row goes in before the fetch, so a retry during the download
    sees `skip_in_flight`. The commit releases the key lock and the connection.
    """
    quota_byte_limit = await _preflight_quota(
        db,
        user,
        replaces=dataset_id,
        quota=quota,
    )
    max_size_bytes = await _upload_max_size_bytes(db)

    metadata: dict[str, object] = {
        **_job_metadata(db, dataset, prepared, fingerprint, user, fields, dataset_id),
        **downloading_stage_marker(),
    }

    # `running`, not `pending`: a pending row with no file_path and no queue
    # task is reapable by four actors while its source downloads; the lease is
    # not. An upload's own row is the reservation, keeping its file attributed.
    if prepared.kind == "upload":
        job = await claim_upload_source(
            db, prepared, user, metadata, dataset_id=dataset_id
        )
    else:
        job = ledger.create(
            db,
            created_by=user.id,
            status="running",
            dataset_id=dataset_id,
            source_filename=prepared.source_filename,
            source_layer=prepared.source_layer,
            user_metadata=metadata,
        )
    try:
        await db.flush()
        await _commit_reservation(db)
    except BaseException as exc:
        # A cancellation is not a failure to recover from. The durable row is
        # reconciled either way, but staging must not run on through a
        # shutdown, so only an ordinary exception continues.
        adopted = await _adopt_committed_reservation(
            db, job, exc, adopt=isinstance(exc, Exception)
        )
        if adopted is None:
            raise
        job = adopted
    return _ReservedEntry(
        job=job,
        prepared=prepared,
        dataset_id=dataset_id,
        max_size_bytes=max_size_bytes,
        quota_byte_limit=quota_byte_limit,
    )


async def _adopt_committed_reservation(
    db: AsyncSession, job: IngestJob, exc: BaseException, *, adopt: bool = True
) -> IngestJob | None:
    """Reconcile a reservation whose write was durable but unacknowledged.

    Returns the row when this request may go on using it: running, at this
    claim's own attempt. None when the caller must re-raise; either way the key
    is not left held. ``adopt`` is False for a cancellation, which releases the
    landed row instead.
    """
    job_id, attempt_id = job.id, job.attempt_id
    adopted: IngestJob | None = None

    async def _read_back() -> None:
        nonlocal adopted
        row = await db.get(IngestJob, job_id, populate_existing=True)
        ours = row is not None and row.attempt_id == attempt_id
        adopted = row if ours and row.status == "running" else None

    await _settle_under_reset(db, job, _read_back, job_id=job_id, attempt_id=attempt_id)
    if adopted is not None and adopt:
        return adopted
    set_committed_value(job, "attempt_id", attempt_id)  # the read-back may not be ours
    await _fail_reservation(db, job, exc)
    return None


async def _commit_reservation(db: AsyncSession) -> None:
    """The commit that publishes the reservation, as a named seam.

    Named so a test can make it durable-but-raising, a shape a real session
    can't be asked for directly.
    """
    await db.commit()


async def _commit_staged_bind(db: AsyncSession) -> None:
    """The commit that publishes the staging bind, as a named seam.

    Named so a test can make it durable-but-raising. Production is exactly
    ``db.commit()``.
    """
    await db.commit()


async def _settle_under_reset(
    db: AsyncSession,
    job: IngestJob,
    body: Callable[[], Awaitable[None]],
    *,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID | None = None,
) -> bool:
    """Run every statement of one settlement on a session that was just reset.

    Returns whether an attempt committed. The body is fenced so one
    reset-and-retry, needed because any statement can find the transaction
    unusable, lands nothing twice.
    """
    # Pinned once, never re-read. A retry can rotate the token between the two
    # attempts, and a reset reloads the new one, so the retry body would settle
    # a fresh attempt for the previous attempt's error.
    pinned_attempt = attempt_id or getattr(job, "attempt_id", None)
    for attempt in (1, 2):
        await reset_session_for_settlement(job, db=db)
        if sa_inspect(job, raiseerr=False) is not None:
            # The reset reloads the job, but a failed reload must not leave the
            # body reading an expired id.
            set_committed_value(job, "id", job_id)
            set_committed_value(job, "attempt_id", pinned_attempt)
        try:
            await body()
            await db.commit()
            return True
        except Exception:  # broad: any database error is a reset-and-retry
            if attempt == 2:
                log.exception("Could not settle a manifest job", job_id=str(job_id))
                await db.rollback()
    return False


async def _fail_reservation(
    db: AsyncSession, job: IngestJob, exc: BaseException
) -> None:
    """Settle a reservation that never staged its source, freeing its key."""
    # Read before the first reset: a log line must not be what raises.
    job_id = job.id

    async def _release() -> None:
        await release_manifest_reservation(
            db, job, prefixed_failure_reason("Failed to stage manifest source", exc)
        )

    await _settle_under_reset(db, job, _release, job_id=job_id)


async def _settled_failed(db: AsyncSession, job_id: uuid.UUID) -> bool:
    """Does the row for ``job_id`` read ``failed`` on this transaction?"""
    row = (
        await db.execute(select(IngestJob.status).where(IngestJob.id == job_id))
    ).one_or_none()
    return row is not None and row.status == "failed"


async def _settle_staged_entry(
    db: AsyncSession,
    job: IngestJob,
    exc: BaseException,
    ids: tuple[uuid.UUID, uuid.UUID | None],
    *,
    prepared: ManifestPreparedSource,
    file_path: str,
) -> None:
    """Settle an entry that failed after its source was staged, then reap the copy.

    ``ids`` are the job's id and attempt, read before the failure.

    The row decides, not the exception: the two settlements fence on
    disjoint states, and read and settlement share one body.
    """
    job_id, attempt_id = ids
    # The safe default if neither attempt can read: keep the bytes, because
    # orphaned ones are reclaimable and ones a durable row names are not.
    referenced = True
    failed = False

    async def _decide_and_settle() -> None:
        nonlocal referenced, failed
        referenced = await staged_source_is_referenced(db, job_id, file_path=file_path)
        if not await release_manifest_reservation(db, job, reason):
            await _fail_unqueued_job(job, exc)
        failed = await _settled_failed(db, job_id)

    # A refusal under the catalog rows reads as one; anything else is staging.
    reason = (
        str(exc)
        if isinstance(exc, WriteAccessRevoked)
        else prefixed_failure_reason("Failed to stage manifest source", exc)
    )
    committed = await _settle_under_reset(
        db, job, _decide_and_settle, job_id=job_id, attempt_id=attempt_id
    )
    # Outside the retry: the filesystem is not part of the transaction, and an
    # HTTP download is owned by this attempt while a raw operator seed is not.
    # Only a committed settlement may reap; a failed row has no retry.
    if committed and (failed or not referenced):
        try:
            _cleanup_downloaded_source(prepared, file_path)
        except OSError:
            log.warning("Could not reap a staged manifest source", job_id=str(job_id))


async def _finalize_reserved_entry(
    db: AsyncSession,
    reserved: _ReservedEntry,
    dataset: ManifestDataset,
    user: Identity,
    request: Request,
    quota: _ManifestQuotaReservation,
) -> ManifestApplyEntryResult:
    """Stage the reserved entry's source, admit it, and queue the job."""
    job = reserved.job
    # A failed admission rolls back, which expires ``job``.
    ids = (job.id, job.attempt_id)
    prepared = reserved.prepared
    try:
        file_path = await _stage_source_if_needed(
            prepared,
            job_id=job.id,
            dry_run=False,
            max_size_bytes=reserved.max_size_bytes,
            quota_byte_limit=reserved.quota_byte_limit,
        )
        if file_path is None:
            raise ManifestSourceError("Manifest source could not be staged")
    except BaseException as exc:
        await _fail_reservation(db, job, exc)
        raise

    admitted = False
    try:
        try:
            # Stage + admit must stay under the lease with margin, so a
            # heartbeat-less running row can't be reaped mid-admit.
            async with asyncio.timeout(MANIFEST_ADMIT_MAX_SECONDS):
                staged = await _admit_staged_source(
                    db,
                    prepared,
                    user,
                    request,
                    file_path=file_path,
                    replaces=reserved.dataset_id,
                    quota=quota,
                )
                admitted = True
                if not await bind_reservation_to_staged_source(
                    db, job, file_path=file_path
                ):
                    raise ManifestSourceError(RESERVATION_LOST_MESSAGE)
                # After the bind: the job row is locked before the run insert
                # reaches the dataset row, the order a dataset delete takes.
                if reserved.dataset_id is not None:
                    await _admit_refresh_run(db, job, reserved.dataset_id, user)
                await _commit_staged_bind(db)
        except TimeoutError as exc:
            raise ManifestSourceError(
                "Manifest source did not finish admission within "
                f"{MANIFEST_ADMIT_MAX_SECONDS} seconds"
            ) from exc
    except BaseException as exc:
        if admitted:
            quota.release(
                incoming_bytes=staged.incoming_bytes,
                creates_dataset=reserved.creates_dataset,
            )
        await _settle_staged_entry(
            db, job, exc, ids, prepared=prepared, file_path=file_path
        )
        raise

    try:
        if reserved.dataset_id is None:
            await queue_ingest_job(job, str(user.id), db=db)
        else:
            await _queue_reupload_job(db, job, reserved.dataset_id, user, prepared)
    except BaseException as exc:
        quota.release(
            incoming_bytes=staged.incoming_bytes,
            creates_dataset=reserved.creates_dataset,
        )
        await _settle_staged_entry(
            db, job, exc, ids, prepared=prepared, file_path=file_path
        )
        raise

    if reserved.dataset_id is None:
        return ManifestApplyEntryResult(
            dataset_key=dataset.key,
            action="create",
            job_id=job.id,
            message="Manifest dataset ingest queued.",
        )
    return ManifestApplyEntryResult(
        dataset_key=dataset.key,
        action="update",
        job_id=job.id,
        dataset_id=reserved.dataset_id,
        message="Manifest dataset reupload queued.",
    )


def _error_result(dataset: ManifestDataset, exc: Exception) -> ManifestApplyEntryResult:
    message = str(exc)
    return ManifestApplyEntryResult(
        dataset_key=dataset.key,
        action="error",
        message=message,
        errors=[message],
        messages=getattr(exc, "messages", None),
    )


def _dataset_busy_result(dataset: ManifestDataset) -> ManifestApplyEntryResult:
    """The other doors' 409 ``dataset_busy``, with the code in ``errors``."""
    return ManifestApplyEntryResult(
        dataset_key=dataset.key,
        action="error",
        message=(
            "A refresh is already running for this dataset. Wait for it to "
            "finish, then apply the manifest again."
        ),
        errors=["dataset_busy"],
    )


async def _answer_in_flight(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    dataset: ManifestDataset,
    fields: ManifestEntryFields | None,
    job: IngestJob,
) -> ManifestApplyEntryResult:
    """Answer an unchanged entry for the job of its key still in flight."""
    # The dataset may have passed to another owner since the job was queued;
    # only its owner is answered for it, before the match judges the owner's
    # shared maps.
    if job.dataset_id is not None:
        named = await get_processing_port().get_dataset(db, job.dataset_id)
        if named is not None:
            await _admit_key_dataset(db, named, user)
    if not await in_flight_job_matches(db, user, fields, dataset, job):
        raise DatasetBusyError(
            "The key's in-flight apply publishes otherwise than this one."
        )
    answer_as_the_job_ends(fields, dry_run=request.dry_run)
    result = _skip_result_for_in_flight(dataset, job)
    # The match above settled the level the queued job publishes.
    result.mark_pending(fields.visibility if fields else None)
    await db.commit()
    return result


async def _reserve_or_settle_entry(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    dataset: ManifestDataset,
    quota: _ManifestQuotaReservation,
    fields: ManifestEntryFields | None = None,
) -> ManifestApplyEntryResult | _ReservedEntry:
    """The locked half of one entry: classify, then either answer or reserve.

    A result answers from what the key holds; a reservation means the caller
    owns it. Every exit commits, so no key lock outlives the entry.
    """
    (
        classification,
        prepared,
        job,
        existing_dataset,
        fingerprint,
    ) = await _classify_dataset(
        db, dataset, user, dry_run=request.dry_run, fields=fields
    )
    if prepared is None:
        raise ManifestSourceError("Manifest source could not be prepared")

    if classification == "skip_in_flight" and job is not None:
        return await _answer_in_flight(db, request, user, dataset, fields, job)

    if classification == "skip_complete" and job is not None:
        if existing_dataset is None:
            raise ManifestSourceError(MANIFEST_KEY_NOT_OWNED)
        await _admit_key_dataset(db, existing_dataset, user)
        await attach_unchanged_entry(
            db, dataset, user, fields, existing_dataset.id, dry_run=request.dry_run
        )
        result = ManifestApplyEntryResult(
            dataset_key=dataset.key,
            action="skip",
            job_id=job.id,
            dataset_id=job.dataset_id,
            message=skip_complete_message(prepared),
        )
        await db.commit()
        return result

    update_dataset_id: uuid.UUID | None = None
    held: ManifestApplyEntryResult | None = None
    if classification == "update" and existing_dataset is not None:
        # Before the blocked and dry-run responses, which name the dataset.
        await _admit_key_dataset(db, existing_dataset, user)
        held = await held_entry(db, dataset, fingerprint, job, existing_dataset)
        if fields is None and await held_job_matches(
            db, held, None, {}, user=user, dataset=dataset, existing=existing_dataset
        ):
            await db.commit()
            return held
        # Run after authorization (to avoid leaking another user's dataset
        # type) but before dry-run reporting, staging, or queue creation.
        _refuse_unreplaceable_update(db, dataset, existing_dataset, prepared, fields)
        update_dataset_id = existing_dataset.id
        await judge_update(
            db,
            user,
            fields,
            dataset,
            job,
            existing_dataset,
            metadata=_job_metadata(
                db, dataset, prepared, fingerprint, user, fields, update_dataset_id
            ),
            dry_run=request.dry_run,
        )

    await decide_publication(db, fields, dataset, existing_dataset)
    await resolve_entry_collection(db, dataset, user, fields, dry_run=request.dry_run)
    await resolve_entry_groups(db, dataset, user, fields, existing_dataset)
    # Matched before the dry run's A057, which then judges the groups an
    # Accept leaves.
    held_matches = fields is not None and await held_job_matches(
        db,
        held,
        fields,
        _job_metadata(
            db, dataset, prepared, fingerprint, user, fields, update_dataset_id
        ),
        user=user,
        dataset=dataset,
        existing=existing_dataset,
    )
    if held_matches:
        if request.dry_run:
            note_more_visible(dataset, fields, existing_dataset)
        answer_as_the_job_ends(fields, dry_run=request.dry_run)
        # The held replacement publishes what this apply just decided.
        held.mark_pending(fields.visibility)
        await db.commit()
        return held
    refuse_used_upload(prepared)
    await refuse_a_share_its_job_refuses(
        db,
        user,
        dataset,
        fields,
        existing_dataset if update_dataset_id is not None else None,
        _job_metadata(
            db, dataset, prepared, fingerprint, user, fields, update_dataset_id
        ),
    )
    if request.dry_run:
        # Judged on what the job leaves, once the check above settled it.
        note_more_visible(dataset, fields, existing_dataset)
        # A preview reserves nothing, so the key is left exactly as this entry
        # found it.
        result = None
        if classification == "create":
            # The apply's own check, so a preview never promises a dataset
            # the apply would refuse. The ledger counts this manifest's
            # earlier creates.
            await _preflight_quota(db, user, replaces=None, quota=quota)
            quota.reserve(incoming_bytes=0, creates_dataset=True)
            result = ManifestApplyEntryResult(
                dataset_key=dataset.key,
                action="create",
                message="Manifest dataset would be created.",
            )
        elif update_dataset_id is not None:
            result = ManifestApplyEntryResult(
                dataset_key=dataset.key,
                action="update",
                dataset_id=update_dataset_id,
                message="Manifest dataset would be updated.",
            )
        if result is not None:
            await db.commit()
            return result

    reserves_update = classification == "update" and update_dataset_id is not None
    if classification != "create" and not reserves_update:
        raise ManifestSourceError("Manifest dataset could not be classified")

    return await _reserve_entry(
        db,
        dataset,
        prepared,
        fingerprint,
        user,
        dataset_id=update_dataset_id,
        quota=quota,
        fields=fields,
    )


async def _run_entry(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    dataset: ManifestDataset,
    http_request: Request,
    quota: _ManifestQuotaReservation,
) -> ManifestApplyEntryResult:
    fields = ManifestEntryFields.of(request, dataset)
    outcome = await _reserve_or_settle_entry(db, request, user, dataset, quota, fields)
    if not isinstance(outcome, ManifestApplyEntryResult):
        outcome = await _finalize_reserved_entry(
            db, outcome, dataset, user, http_request, quota
        )
    return report_entry(fields, outcome)


async def apply_manifest(
    db: AsyncSession,
    request: ManifestApplyRequest,
    user: Identity,
    http_request: Request,
) -> ManifestApplyResponse:
    """Apply a manifest payload through existing ingest/reupload queues."""
    # AsyncSession.rollback() expires ORM instances; a snapshot outside that
    # lifecycle keeps a rejected entry from triggering a synchronous lazy load
    # (MissingGreenlet) in the next entry's auth check.
    caller = IdentitySnapshot.of(user)
    results: list[ManifestApplyEntryResult] = []
    quota = _ManifestQuotaReservation()
    for dataset in request.datasets:
        try:
            results.append(
                await _run_entry(
                    db,
                    request,
                    caller,
                    dataset,
                    http_request,
                    quota,
                )
            )
        except (ManifestSourceError, ValueError, HTTPException) as exc:
            # Also the release of this key's advisory lock, for an entry that
            # raised while still holding it.
            await db.rollback()
            results.append(_error_result(dataset, exc))
        except DatasetBusyError:
            await db.rollback()
            results.append(_dataset_busy_result(dataset))
        except Exception as exc:  # broad: per-entry isolation — any unexpected failure is recorded as that entry's error
            await db.rollback()
            results.append(_error_result(dataset, exc))

    for result in results if request.manifest_version == "2" else ():
        result.messages = result.messages or []
    maps = await run_manifest_maps(db, request, caller, results, http_request)
    if request.manifest_version == "2":
        await describe_results(db, request, caller, http_request, results, maps)
    return ManifestApplyResponse(
        accepted=any(r.action != "error" for r in [*results, *(maps or ())]),
        dry_run=request.dry_run,
        results=results,
        maps=maps,
    )
