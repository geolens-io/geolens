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
from app.modules.quota.service import check_replacement_quota, check_upload_quota
from app.platform.storage import StorageProvider
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.validation import HEADER_READ_SIZE, validate_file_content

if TYPE_CHECKING:
    from app.platform.jobs.models import IngestJob

logger = structlog.get_logger(__name__)


async def _cleanup_presigned_object(
    storage: StorageProvider, key: str, job_id: uuid.UUID
) -> None:
    """Best-effort rollback delete of one presigned object.

    fix(#1213 review r5): drains, and swallows BaseException. Swallowing a
    CancelledError is normally an anti-pattern; here it is deliberate rollback
    semantics, carried over from `_cleanup_saved_upload` in v1.8.0's router
    (KISS-N9), which this helper replaced when the completion sequence was
    extracted. Two callers below delete BOTH objects in sequence on a
    deliberate refusal, and a cancellation escaping the first would leave the
    staging object alive — handing the client back the very bytes just
    refused, which is the hole the rejection block exists to close.

    Draining matters for the same reason it does at the freeze: the delete
    runs in an SDK thread a client disconnect cannot stop, so returning early
    would abandon it mid-call.
    """
    try:
        await await_draining(storage.delete(key))
    except (
        BaseException
    ):  # broad: rollback must complete through cancellation (KISS-N9)
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

    fix(#1235 review r3): URL expiry anchors at SIGNING time, the job deadline
    anchors at `created_at`, and the two drift by however long the request
    takes between the job INSERT and each signature. The part-URL loop signs
    sequentially through a worker thread, so on a many-part file the last
    signatures can be seconds late — and the window scales as an operator
    lowers `pending_job_timeout_seconds`. In that gap S3 accepts bytes the
    pending sweep is already entitled to fail the job for.

    Anchoring to the deadline removes the class rather than narrowing it: the
    URL expires exactly when the job does, whenever it was signed. Callers
    that sign several URLs may compute this ONCE before the loop — later
    signatures then carry a slightly earlier deadline, which is conservative
    in the right direction.

    May be zero or negative. Signing that is the caller's decision and the
    answer is always no — see `require_signable_job_lifetime`, which is what
    every handler should call.
    """
    deadline = created_at + timedelta(seconds=settings.pending_job_timeout_seconds)
    return int((deadline - datetime.now(timezone.utc)).total_seconds())


def require_signable_job_lifetime(created_at: datetime) -> int:
    """Remaining lifetime, refusing outright when too little of it is left.

    fix(#1235 review r4): the previous `max(1, ...)` floor was described as
    producing a URL "expired on arrival". It does the opposite. `ExpiresIn` is
    relative to SIGNING time, so flooring at 1 mints a URL that is USABLE for
    one more second — past the deadline this whole change exists to enforce.
    There is no `ExpiresIn` value that means "already dead": the only way to
    avoid handing out a live URL is to not sign one.

    409 rather than 422: the presign door's 400s mean "this request cannot be
    served as asked" (wrong storage mode, rejected extension) and its 422 means
    "your file is wrong" (too large). Neither fits a request that was valid and
    lost to the job's own clock — that is a state conflict, which is what the
    ingest router already answers 409 for elsewhere.

    Both doors call this above the multipart branch as a gate, so the common
    refusal costs nothing — there is no initiated upload id yet. Every actual
    signature also reaches it via `sign_url_with_deadline`, from inside the
    signing thread, where a refusal DOES land in the multipart try; that
    handler aborts the upload and re-raises this exception unchanged.

    fix(#1235 review r6): the margin lives in `core/config` with the setting
    whose lower bound must equal it, so a timeout that could not clear this
    check no longer boots at all. Reaching this refusal therefore means the
    request itself was slow enough to eat the window between the job INSERT
    and this signature — not that the deployment is misconfigured.
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

    fix(#1235 review r8): a SYNC callable, handed to `run_in_thread_draining`
    so both halves happen inside the signing thread. Recomputing per signature
    (r5) fixed the loop's own delay but left one more layer of the same drift:
    the computation ran on the event loop, and `ExpiresIn` starts counting when
    boto signs. Any gap between the two — executor saturation, a busy loop, GIL
    contention before the thread is picked up — pushed expiry that far past the
    job deadline. Each round of this bug has been a smaller copy of the last.

    This one terminates the recursion rather than shrinking it again: there is
    no scheduler boundary left between reading the clock and signing, because
    the two are adjacent statements in one thread. The residual is the time
    between two adjacent instructions, which no arrangement of code can remove.

    Every storage method here takes `expiration` as its final positional
    argument, so callers pass the leading arguments and this appends the one
    that must be computed late.
    """
    return storage_method(*args, require_signable_job_lifetime(created_at))


def raise_if_over_max_upload_size(actual_size: int, max_size_mb: int) -> None:
    """Raise the canonical oversize 422 for a completed presigned upload.

    Extracted so the pre-copy fast path in the ingest router and the
    authoritative post-copy check below cannot drift apart: a client that
    trips either one has to see the same status and the same wording.
    """
    if actual_size > max_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Uploaded file size ({actual_size / (1024 * 1024):.1f} MB) exceeds "
                f"the maximum allowed ({max_size_mb} MB)."
            ),
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

    fix(#1290 review): completion is an ADMISSION POINT, and it was running the
    creation-shaped check. An owner at the dataset-count cap therefore passed
    the request-time door — which learned about replacements — uploaded the
    bytes, and was refused here because the finalizer still treated a
    replacement as a new dataset. Replacement-aware admission has to hold at
    every admission point or the class just moves to the next one.

    ``replacing_dataset_id`` is the reupload doors' way of saying which it is.
    None means a genuine creation and keeps the original check.

    ``user_id`` is the OWNER on the replacement path (the reupload door passes
    ``dataset.record.created_by``) and the uploader on the creation path. Only
    the first can be None, for an ownerless dataset — see the ownerless-dataset
    policy in ``app.modules.quota.service``'s module docstring (#1293).
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
                detail=(
                    f"Uploaded file size ({actual_size} bytes) does not match "
                    f"the declared size ({expected_size} bytes)."
                ),
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

    fix(#1202 review r5, r9): the one-shot guard reads `file_path`, and the
    property it needs is TWO-PART. Both halves are load-bearing and each was
    got wrong once:

    1. The SELECT must LOCK. Without `with_for_update` two overlapping
       completions both saw an empty `file_path` and proceeded, racing over
       the same deterministically-derived frozen key: the loser's refusal
       deletes both objects while the winner commits a binding to one of them.

    2. The read must be FRESH. `with_for_update` alone serializes without
       informing — SQLAlchemy keeps the already-loaded attributes on the
       identity-map instance, and the caller's authz fetch loaded this row
       BEFORE the competing request committed. Measured, not inferred: without
       `populate_existing` the re-fetch returns the stale empty `file_path`
       and the guard passes on a job that was already completed. The r5 test
       pinned only half of this (that a FOR UPDATE statement reached the
       driver), which is why the second half survived four review rounds.

    The lock is held to the caller's commit or rollback, and it is one row, so
    completions of different jobs never serialize against each other. Callers
    keep their own authz fetch — the two doors have different 404 semantics
    and neither should serialize ordinary reads behind a completion.
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

    fix(#1213 review r3): completion is one-shot, and "one-shot" has TWO
    resolved-state facts, not one. Both doors checked only the first.

    1. `file_path` set — the bytes were accepted. A second call would re-freeze
       whatever now sits at the staging key, which the client's unexpired PUT
       URL controls.

    2. a TERMINAL status — the job is settled and no task will ever run for
       it. Without this a client could re-PUT after a content refusal and
       complete again: the endpoint 200s and binds a frozen object, but the
       row stays terminal, so preview and commit then reject it with "Job
       already processed". The 200 is a lie, the client's recovery path is
       dead, and the frozen object is unowned — no task tail fires for a job
       nothing was deferred for, and the post-expiry sweep only covers the
       client's key.

    The two doors reach state 2 by different routes, which is why this guard
    belongs to both: the reupload door stamps `failed` itself before a content
    422 (its direct sibling does, and a provenance test asserts that trail),
    while an abandoned presigned upload is settled by the stale-pending reaper
    after an hour — the same hour the PUT URL stays valid, so the windows
    overlap.

    fix(#1556): that reaper now settles the abandoned-upload class `cancelled`
    rather than `failed`, so "terminal" here is BOTH statuses. Reading only
    `failed` would have reopened this hole for the exact rows the sentence
    above is about — the class that reaches state 2 without any door stamping
    it — while every test covering the door-stamped route kept passing.

    REJECT rather than resurrect. Reviving a failed job would re-open the
    client-writable-state-re-entering class this endpoint spent ten rounds
    closing, and the product already has the answer: start again.
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

    fix(#1202 review r3): for an S3 multipart upload the staging object exists
    IF AND ONLY IF CompleteMultipartUpload succeeded — uploaded parts are
    invisible as an object until then — so the object's presence is a sound
    record that assembly is done, with no metadata to keep in sync.

    Without this, a completion that got past assembly and then failed (at the
    freeze, say) left the job unbound and the upload id SPENT: the retry the
    502 advertises re-entered assembly, called complete with a consumed id,
    and could never succeed. Callers must skip the parts-required 400 along
    with the assembly — a retrying client has nothing left to resend.
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

    fix(#1202): the direct upload doors call ``validate_file_content`` on the
    staged bytes, and the presigned completion paths did not — so doors on the
    same surface accepted different files, and a presigned upload reached
    preview (which hands the file to GDAL) with no content check behind it.

    ``validate_file_content`` wants a path, and presigned uploads exist for the
    multi-GB case, so instead of downloading the object this builds a probe
    file out of the only bytes the checks read:

    - the first ``HEADER_READ_SIZE`` bytes, which is exactly what the
      magic-byte branch reads;
    - for ``.parquet``, the trailing ``PAR1`` magic, which
      ``validate_parquet_file`` seeks to from the end. Only appended when the
      object is larger than the header window — below that the header IS the
      whole object, so the probe is byte-identical to it.

    The ``.vrt`` branch reads the whole body and is never reached from either
    presigned door: the upload door refuses a ``.vrt`` filename at
    presign-request time via ``_reject_standalone_vrt`` (422), and the reupload
    door via ``_assert_compatible_record_type`` (400). Different mechanisms and
    different statuses, same unreachability, both checked at request time.

    Raises HTTPException 422 carrying ``str(exc)``, the same class, status and
    body the direct doors raise at their ``validate_file_content`` call.
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
                detail=str(exc),
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

    Owns every step between "the client says it finished" and "the caller may
    bind a job to bytes nobody can change". Returns the frozen LOGICAL key.
    The caller binds, commits, and sweeps — those differ per door.

    THE ORDER IS THE FIX, not the copy. The client still holds a presigned PUT
    URL for the staging key; those stay valid until expiry and a PUT to an
    existing key replaces the object, so anything checked at the staging key
    can be swapped afterwards: upload clean bytes, complete, re-PUT garbage,
    and preview hands GDAL a file nothing ever validated. Snapshotting to a key
    no presign endpoint ever minted a URL for is what makes the checks mean
    something, and verifying or validating BEFORE the copy re-opens the same
    race one step earlier. Size and quota have to judge the immutable bytes
    too, or a client declares 1 KB, completes, and swells the staging object
    past its quota before the snapshot is taken.

    FAILURE CONTRACT, as postconditions on the two objects. The invariant
    underneath them: this function never deletes the staging object except on
    a deliberate refusal, because the staging bytes are what a retry needs and
    re-uploading them can cost gigabytes.

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

    # fix(#1202 review): resource-waste fast path, NOT the security boundary.
    # Presigned PUT URLs do not bind Content-Length, so the object can be any
    # size regardless of what the client declared — without this, an oversize
    # upload gets fully copied just to be rejected a moment later. Advisory
    # ONLY: the client can swell the object between this measurement and the
    # copy, which is exactly why the post-copy check below stays authoritative.
    # Do not remove that one on the strength of this one.
    frozen_key = frozen_staging_key(logical_key)
    physical_frozen_key = resolve_current_storage_key(frozen_key)

    staging_size = await storage.size(physical_key)
    try:
        raise_if_over_max_upload_size(staging_size, await UPLOAD_MAX_SIZE_MB.get(db))
    except HTTPException:
        # fix(#1213 review r5): drop any frozen copy a PRIOR attempt left, not
        # just the staging object. The caller's commit failing after a
        # successful freeze deliberately keeps both objects so the retry can
        # re-copy — and if that retry then trips this gate (the client re-PUT
        # something oversized, or the limit was lowered), the earlier frozen
        # copy is unbound, unreferenced and, on the reupload door, attached to
        # a job the 422 marks failed: terminal, no task, no reaper. The key is
        # derived, not remembered, so this needs no state; deleting one that
        # was never created is already this helper's tolerated case.
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        await _cleanup_presigned_object(storage, physical_key, job_id)
        raise

    # Drained, because the copy runs in an SDK thread a client disconnect
    # cannot stop: returning early would leave it writing a frozen object no
    # job row references. `await_draining` waits the thread out and then
    # re-raises the cancellation, so by the time we clean up there is a whole
    # object to delete rather than one still being written.
    try:
        await await_draining(storage.copy(physical_key, physical_frozen_key))
    except BaseException as exc:
        # ONE cleanup path for every way the freeze can fail — an SDK error or
        # a drained cancellation, which `except Exception` cannot see at all.
        # The staging object is never touched here, so a retry costs one more
        # completion call rather than a multi-GB re-upload.
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
        # A deliberate rejection drops BOTH objects, matching the direct
        # doors' rollback — leaving the staging object would hand the client
        # back bytes we just refused, still addressable by its PUT URL.
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        await _cleanup_presigned_object(storage, physical_key, job_id)
        raise
    except BaseException:
        # N4: this clause must stay AFTER the HTTPException one. A transient
        # storage failure drops only the copy we just made; the staging object
        # survives so a retry costs one more completion call.
        await _cleanup_presigned_object(storage, physical_frozen_key, job_id)
        raise

    return frozen_key
