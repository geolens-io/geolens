"""Shared presigned-upload completion checks."""

from __future__ import annotations

import asyncio
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import MIN_SIGNABLE_JOB_LIFETIME_SECONDS, settings
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB
from app.core.async_io import await_draining, run_in_thread_draining
from app.core.upload_errors import UnsafeUploadError, refusal_detail
from app.modules.quota.service import check_replacement_quota, check_upload_quota
from app.platform.storage import StorageProvider
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.pointcloud import inspect_stored_pointcloud
from app.processing.ingest.tileset import (
    TILESET_UNPACKED_BYTES_FIELD,
    inspect_stored_tileset,
)
from app.processing.ingest.validation import HEADER_READ_SIZE, validate_file_content

if TYPE_CHECKING:
    from app.platform.jobs.models import IngestJob

logger = structlog.get_logger(__name__)


async def _cleanup_presigned_object(
    storage: StorageProvider, key: str, job_id: uuid.UUID
) -> None:
    """Best-effort rollback delete of one presigned object.

    Drains, and swallows BaseException. Callers delete both objects in
    sequence on a refusal, and a cancellation escaping the first would leave
    the staging object alive, handing the client back the bytes just
    refused. The delete runs in an SDK thread a client disconnect can't
    stop, hence the drain.
    """
    try:
        await await_draining(storage.delete(key))
    except BaseException:  # broad: rollback must complete through cancellation
        logger.warning(
            "presigned_upload_cleanup_failed",
            s3_key=key,
            job_id=str(job_id),
        )


async def abort_presigned_multipart_upload(
    storage: StorageProvider,
    *,
    key: str,
    upload_id: object,
    job_id: uuid.UUID,
) -> None:
    """Best-effort abort for rejected multipart presigned uploads."""
    if not upload_id:
        return
    try:
        await run_in_thread_draining(
            storage.abort_multipart_upload, key, str(upload_id)
        )
    except Exception:  # broad: cleanup is best-effort after a rejected upload
        logger.warning(
            "presigned_multipart_abort_failed",
            s3_key=key,
            job_id=str(job_id),
        )


def remaining_job_lifetime_seconds(created_at: datetime) -> int:
    """Seconds a presigned URL for this job may still legitimately be honoured.

    URL expiry anchors at signing time and the job deadline at `created_at`.
    They drift by however long the request takes between the job INSERT and
    each signature (a many-part file's signing loop can run seconds late),
    and in that gap S3 would accept bytes the pending sweep may already fail
    the job for. Anchoring to the deadline makes the URL expire exactly when
    the job does, whenever it was signed.

    May be zero or negative; `require_signable_job_lifetime` refuses to sign
    then.
    """
    deadline = created_at + timedelta(seconds=settings.pending_job_timeout_seconds)
    return int((deadline - datetime.now(timezone.utc)).total_seconds())


def require_signable_job_lifetime(created_at: datetime) -> int:
    """Remaining lifetime, refusing outright when too little of it is left.

    No `ExpiresIn` value means "already dead", since it is relative to
    signing time; a `max(1, ...)` floor would mint a URL usable for one more
    second past the deadline. The only way to avoid a live URL is not to
    sign one.

    409 rather than 422: the presign door's 400s mean "this request cannot
    be served as asked" and its 422 means "your file is wrong". A valid
    request that lost to the job's own clock is a state conflict.

    Both doors call this above the multipart branch, so the common refusal
    costs nothing (no upload id initiated yet). Every signature also reaches
    it via `sign_url_with_deadline`, where a refusal lands in the multipart
    try that aborts the upload and re-raises this exception unchanged.

    The margin lives in `core/config` with the setting whose lower bound
    must equal it, so a timeout that can't clear this check doesn't boot;
    reaching this refusal means the request was slow.
    """
    remaining = remaining_job_lifetime_seconds(created_at)
    if remaining < MIN_SIGNABLE_JOB_LIFETIME_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This upload's time window has closed. Start a new upload.",
        )
    return remaining


def sign_url_with_deadline(storage_method, created_at: datetime, *args):
    """Compute the remaining lifetime and sign, as two adjacent instructions.

    A sync callable, handed to `run_in_thread_draining` so both halves run in
    the signing thread. `ExpiresIn` starts counting when boto signs, so
    computing on the event loop would let any gap before the thread is
    picked up (executor saturation, GIL contention) push expiry past the job
    deadline.

    Every storage method here takes `expiration` as its final positional
    argument, so callers pass the leading arguments and this appends it.
    """
    return storage_method(*args, require_signable_job_lifetime(created_at))


def raise_if_over_max_upload_size(actual_size: int, max_size_mb: int) -> None:
    """Raise the canonical oversize 422 for a completed presigned upload.

    The pre-copy fast path and the authoritative post-copy check both raise
    it, so a client that trips either sees the same status and wording.
    """
    if actual_size > max_size_mb * 1024 * 1024:
        size_mb = round(actual_size / (1024 * 1024), 1)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "file_size_exceeded",
                "message": (
                    f"Uploaded file size ({size_mb} MB) exceeds "
                    f"the maximum allowed ({max_size_mb} MB)."
                ),
                "size_mb": size_mb,
                "limit_mb": max_size_mb,
            },
        )


async def verify_completed_presigned_upload(
    *,
    db: AsyncSession,
    storage: StorageProvider,
    key: str,
    expected_size: object,
    user_id: uuid.UUID | None,
    request: Request,
    job_id: uuid.UUID,
    replacing_dataset_id: uuid.UUID | None = None,
) -> int:
    """Verify a completed direct-to-object-storage upload before accepting it.

    Completion is an admission point: a creation-shaped check here would let
    an owner at the dataset-count cap pass the replacement-aware request-time
    door, upload the bytes, and be refused as if creating a new dataset.

    ``replacing_dataset_id`` names the dataset a reupload door replaces;
    None means a creation.

    ``user_id`` is the owner on the replacement path (the reupload door
    passes ``dataset.record.created_by``) and the uploader on the creation
    path. Only the first can be None, for an ownerless dataset.
    """
    actual_size = await storage.size(key)
    max_size_mb = await UPLOAD_MAX_SIZE_MB.get(db)

    try:
        raise_if_over_max_upload_size(actual_size, max_size_mb)
    except HTTPException:
        await _cleanup_presigned_object(storage, key, job_id)
        raise

    if expected_size is not None:
        try:
            declared_size = int(expected_size)
        except (TypeError, ValueError):
            declared_size = -1
        if actual_size != declared_size:
            await _cleanup_presigned_object(storage, key, job_id)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "presigned_size_mismatch",
                    "message": (
                        f"Uploaded file size ({actual_size} bytes) does not match "
                        f"the declared size ({expected_size} bytes)."
                    ),
                    "actual_size": actual_size,
                    "declared_size": declared_size,
                },
            )

    try:
        if replacing_dataset_id is not None:
            await check_replacement_quota(
                db, user_id, actual_size, request, dataset_id=replacing_dataset_id
            )
        else:
            await check_upload_quota(db, user_id, actual_size, request)
    except HTTPException:
        await _cleanup_presigned_object(storage, key, job_id)
        raise

    return actual_size


async def lock_presigned_job(db: AsyncSession, job_id: uuid.UUID) -> "IngestJob":
    """Re-fetch a job under a row lock, with attributes reloaded from the row.

    The one-shot guard reads `file_path`, which needs two things:

    1. The SELECT must lock. Otherwise two overlapping completions both see
       an empty `file_path` and race over the same frozen key: the loser's
       refusal deletes both objects while the winner binds one of them.

    2. The read must be fresh. `with_for_update` alone keeps the attributes
       the identity map loaded in the caller's authz fetch, before the
       competing request committed; without `populate_existing` the guard
       passes on a stale empty `file_path`.

    The lock is held to the caller's commit or rollback, on one row, so
    completions of different jobs never serialize. Callers keep their own
    authz fetch: the two doors have different 404 semantics, and neither
    should serialize ordinary reads behind a completion.
    """
    from app.platform.jobs.models import IngestJob

    job = await db.get(IngestJob, job_id, with_for_update=True, populate_existing=True)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return job


def require_completable_presigned_job(job: "IngestJob", *, restart_hint: str) -> None:
    """Refuse a completion the job can no longer legitimately accept.

    Both doors check both one-shot facts:

    1. `file_path` set: bytes accepted. A second call would re-freeze
       whatever now sits at the staging key, which the client's unexpired
       PUT URL controls.

    2. A terminal status: no task will ever run for the job. Otherwise a
       client could re-PUT after a content refusal and complete again: the
       endpoint returns 200 and binds a frozen object, but preview/commit
       reject the terminal row, and the frozen object is unowned (no task
       tail fires, and the post-expiry sweep only covers the client's key).

    Terminal means `failed` or `cancelled`: the reupload door stamps
    `failed` before a content 422, while the stale-pending reaper settles an
    abandoned presigned upload `cancelled` after an hour, the same hour the
    PUT URL stays valid.

    The job is refused, not resurrected, since reviving it would let
    client-writable state back in.
    """
    if job.file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload already completed for this job",
        )
    if job.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This job has already failed and cannot be completed. {restart_hint}",
        )
    if job.status == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"This upload was abandoned and has been cancelled. {restart_hint}"
            ),
        )


async def should_assemble_multipart(
    storage: StorageProvider, um: dict, physical_key: str
) -> bool:
    """Whether CompleteMultipartUpload still needs to run for this job.

    For an S3 multipart upload the staging object exists if and only if
    CompleteMultipartUpload succeeded (parts are invisible as an object until
    then), so its presence records that assembly is done.

    A completion that got past assembly and then failed (at the freeze, say)
    leaves the job unbound and the upload id spent, so a retry must not call
    complete again. Callers skip the parts-required 400 along with the
    assembly, since a retrying client has nothing left to resend.
    """
    if not um.get("multipart"):
        return False
    return not await storage.exists(physical_key)


# Trailing PAR1 magic that validate_parquet_file seeks to from the end.
_PARQUET_MAGIC_BYTES = 4

# Path segment separating the frozen snapshot from the client-writable
# staging key. The presign endpoints only ever mint URLs for
# `staging/{job_id}/{filename}`, so nothing under here is client-writable.
_FROZEN_SEGMENT = "frozen"


def frozen_staging_key(s3_key: str) -> str:
    """Derive the immutable snapshot key for a staging upload key.

    Inserts a segment before the filename rather than appending a suffix:
    the extension is load-bearing all the way down (content sniffing, the
    raster/vector branch, ogr2ogr driver selection), so the filename has to
    survive as the last segment. The result still starts with `staging/`,
    which is what every existing staging reaper keys off.
    """
    parent, separator, name = s3_key.rpartition("/")
    if not separator:
        return f"{_FROZEN_SEGMENT}/{s3_key}"
    return f"{parent}/{_FROZEN_SEGMENT}/{name}"


async def validate_presigned_content(
    storage: StorageProvider,
    *,
    key: str,
    filename: str,
    size: int,
) -> None:
    """Run the direct path's content check against an object in storage.

    Without it a presigned upload would reach preview, which hands the file
    to GDAL, with no content check behind it.

    ``validate_file_content`` wants a path, and presigned uploads exist for
    the multi-GB case, so instead of downloading the object this builds a
    probe file out of the only bytes the checks read:

    - the first ``HEADER_READ_SIZE`` bytes, exactly what the magic-byte
      branch reads;
    - for ``.parquet``, the trailing ``PAR1`` magic that
      ``validate_parquet_file`` seeks to from the end. Only appended when
      the object is larger than the header window.

    The ``.vrt`` branch reads the whole body and is never reached from
    either presigned door: both refuse a ``.vrt`` filename at presign-request
    time (``_reject_standalone_vrt`` / ``_assert_compatible_record_type``).

    Raises HTTPException 422 carrying the refusal's code, message and
    values, the same status and body the direct doors raise at their
    ``validate_file_content`` call.
    """
    head = await storage.get_range(key, 0, HEADER_READ_SIZE)

    tail = b""
    if Path(filename).suffix.lower() == ".parquet" and size > len(head):
        tail = await storage.get_range(
            key, size - _PARQUET_MAGIC_BYTES, _PARQUET_MAGIC_BYTES
        )

    with tempfile.NamedTemporaryFile(suffix=".probe") as probe:
        probe.write(head + tail)
        probe.flush()
        try:
            validate_file_content(probe.name, filename)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=refusal_detail(exc),
            ) from exc


async def finalize_presigned_object(
    *,
    db: AsyncSession,
    storage: StorageProvider,
    job_id: uuid.UUID,
    logical_key: str,
    expected_size: object,
    filename: str,
    user_id: uuid.UUID | None,
    request: Request,
    replacing_dataset_id: uuid.UUID | None = None,
) -> str:
    """Freeze, verify and validate a completed presigned upload.

    Owns every step between "the client says it finished" and "the caller
    may bind a job to bytes nobody can change". Returns the frozen logical
    key. The caller binds, commits and sweeps, which differ per door.

    The order matters. The client still holds a presigned PUT URL for the
    staging key until expiry, and a PUT replaces the object, so anything
    checked at the staging key can be swapped afterwards. Checks run on a
    snapshot at a key no presign endpoint ever minted a URL for; checking
    before the copy reopens the race. Size and quota judge the immutable
    bytes too, or a client could declare 1 KB and swell the staging object
    past its quota before the snapshot.

    Failure contract, as postconditions on the two objects. The staging
    object is deleted only on a deliberate refusal, since it is what a retry
    needs and re-uploading it can cost gigabytes.

    - 400, no object at the key: nothing deleted.
    - 422, oversize pre-copy: staging deleted, frozen never created.
    - 502, freeze failed: staging KEPT, frozen deleted.
    - CancelledError, drained: staging KEPT, frozen deleted, cancel re-raised.
    - 422, verify or content rejection: BOTH deleted.
    - any other exception: staging KEPT, frozen deleted.
    - returns: staging KEPT (the caller sweeps it after its commit), frozen
      present and validated.
    """
    physical_key = resolve_current_storage_key(logical_key)

    if not await storage.exists(physical_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File not found in S3 after upload",
        )

    # Resource-waste fast path, not the security boundary: presigned PUT URLs
    # don't bind Content-Length, so an oversize upload would otherwise be
    # copied just to be rejected. The client can swell the object between
    # this measurement and the copy, so the post-copy check stays
    # authoritative.
    frozen_key = frozen_staging_key(logical_key)
    physical_frozen_key = resolve_current_storage_key(frozen_key)

    staging_size = await storage.size(physical_key)
    try:
        raise_if_over_max_upload_size(staging_size, await UPLOAD_MAX_SIZE_MB.get(db))
    except HTTPException:
        # Also drop any frozen copy a prior attempt left: a commit that failed
        # after a successful freeze keeps both objects for retry, and if that
        # retry trips this gate the earlier frozen copy is unreferenced. The
        # key is derived, and deleting one never created is tolerated.
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        await _cleanup_presigned_object(storage, physical_key, job_id)
        raise

    # Drained: the copy runs in an SDK thread a client disconnect can't stop,
    # so by cleanup time there's a whole object to delete rather than one
    # still being written.
    try:
        await await_draining(storage.copy(physical_key, physical_frozen_key))
    except BaseException as exc:
        # One cleanup path for an SDK error or a drained cancellation, which
        # `except Exception` can't see. The staging object is kept, so a
        # retry costs one more completion call rather than a re-upload.
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        if isinstance(exc, asyncio.CancelledError):
            raise
        logger.exception(
            "presigned_upload_freeze_failed",
            job_id=str(job_id),
            s3_key=logical_key,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upload completion failed — the upload session may have expired. Please try again.",
        ) from exc

    try:
        actual_size = await verify_completed_presigned_upload(
            db=db,
            storage=storage,
            key=physical_frozen_key,
            expected_size=expected_size,
            user_id=user_id,
            request=request,
            job_id=job_id,
            replacing_dataset_id=replacing_dataset_id,
        )
        await validate_presigned_content(
            storage,
            key=physical_frozen_key,
            filename=filename,
            size=actual_size,
        )
    except HTTPException:
        # A deliberate rejection drops both objects: the staging object would
        # hand the client back refused bytes, still addressable by its PUT URL.
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        await _cleanup_presigned_object(storage, physical_key, job_id)
        raise
    except BaseException:
        # A transient storage failure drops only the frozen copy; the staging
        # object survives so a retry costs one more completion call.
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        raise

    return frozen_key


async def admit_presigned_tileset(
    db: AsyncSession,
    storage: StorageProvider,
    job: "IngestJob",
    *,
    frozen_key: str,
    user_id: uuid.UUID,
    request: Request,
) -> None:
    """Check a frozen tileset archive and its unpacked total, or drop both objects.

    Runs after ``finalize_presigned_object``, on the frozen copy, and reads only
    the archive's directory and tileset.json. Follows that function's failure
    contract: a refusal deletes both objects, any other failure only the frozen
    copy. Records the unpacked total on the job for the commit door.
    """
    job_id = job.id
    metadata = job.user_metadata or {}
    physical_frozen_key = resolve_current_storage_key(frozen_key)
    try:
        try:
            tileset = await inspect_stored_tileset(storage, physical_frozen_key)
        except UnsafeUploadError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=refusal_detail(exc),
            ) from exc
        await check_upload_quota(db, user_id, tileset.layout.unpacked_bytes, request)
    except HTTPException:
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        await _cleanup_presigned_object(
            storage, resolve_current_storage_key(metadata["s3_key"]), job_id
        )
        raise
    except BaseException:
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        raise
    job.user_metadata = {
        **metadata,
        TILESET_UNPACKED_BYTES_FIELD: tileset.layout.unpacked_bytes,
    }


async def admit_presigned_pointcloud(
    storage: StorageProvider, job: "IngestJob", *, frozen_key: str
) -> None:
    """Check a frozen point cloud's header, hierarchy and top node, or drop both objects.

    Runs after ``finalize_presigned_object``, on the frozen copy, and reads
    only the ranges those checks need. Follows that function's failure
    contract: a refusal deletes both objects, any other failure only the
    frozen copy.
    """
    physical_frozen_key = resolve_current_storage_key(frozen_key)
    try:
        await inspect_stored_pointcloud(storage, physical_frozen_key)
    except UnsafeUploadError as exc:
        await _cleanup_presigned_object(storage, physical_frozen_key, job.id)
        await _cleanup_presigned_object(
            storage, resolve_current_storage_key(job.user_metadata["s3_key"]), job.id
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=refusal_detail(exc),
        ) from exc
    except BaseException:
        await _cleanup_presigned_object(storage, physical_frozen_key, job.id)
        raise
