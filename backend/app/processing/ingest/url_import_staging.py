"""Staging helpers for the URL import: put, quota, settlement.

feat(#1710): the download runs on the worker, so nothing here budgets
against the edge proxy any more. What remains is the part that is about
OWNERSHIP of staged bytes rather than about time.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import run_in_thread_draining
from app.core.failure_reason import redact_failure_reason
from app.modules.quota.service import check_upload_quota, get_user_quota_usage
from app.platform.jobs.heartbeat import write_job_failure_for_attempt
from app.platform.storage import get_storage
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.service import (
    _await_provider_call_draining,
    _cleanup_saved_upload,
)

logger = structlog.get_logger(__name__)

# fix(#1710): stamped by `_settle_failed_url_import` on the exception it has
# already acted on, so the task's outer handler can settle what never reached
# it without settling the same failure twice.
_SETTLED_ATTR = "_geolens_url_import_settled"


class UrlImportRefused(ValueError):
    """A URL-import refusal the submitter is meant to read.

    fix(#1710): the worker has no response to shape, so a refusal it raises
    is a domain failure rather than an ``HTTPException``. Defined under
    ``app.`` so ADR-002's stored-reason door (#1953) admits its text.
    """


async def _put_staging_object(s3_key: str, local_dest: Path) -> None:
    """Upload the staged local file to the S3 staging key.

    Owns its file handle: the drained provider call finishes its SDK thread
    before this returns, so the descriptor outlives every reader of it.
    """
    # codeql[py/path-injection] fix(#1708): the component is basename-stripped (safe_upload_basename/filename_from_url) and byte-clamped, rooted under upload_staging_dir
    fh = open(local_dest, "rb")
    try:
        await _await_provider_call_draining(
            get_storage().put(resolve_current_storage_key(s3_key), fh)
        )
    finally:
        await run_in_thread_draining(fh.close)


async def _url_import_transition_landed(job_id: uuid.UUID, staged_path: str) -> bool:
    """Did the running->pending transition durably land despite the raise?

    fix(#1708): a commit whose acknowledgement is lost (cancellation
    or connection loss while ``COMMIT`` is in flight) may have been durably
    applied by PostgreSQL even though the await raised. Read the row back on
    a FRESH session — the request session is mid-failure and untrustworthy.
    True means the job is live catalog state: 'pending', bound to exactly
    the staged path this request wrote.

    A probe that itself fails returns True — standing down. Deliberately
    asymmetric: a false positive orphans bytes the sweeps can reclaim, while
    a false negative deletes data a durable pending row points at, which
    nothing can reclaim.
    """
    # Late bind so tests' engine patching is honored (fix(#909)-style).
    import app.core.db as db_module

    from app.platform.jobs.models import IngestJob

    try:
        async with db_module.async_session() as probe:
            row = (
                await probe.execute(
                    select(IngestJob.status, IngestJob.file_path).where(
                        IngestJob.id == job_id
                    )
                )
            ).one_or_none()
    except BaseException:
        logger.warning("url_import_commit_probe_failed", job_id=str(job_id))
        return True
    return row is not None and row.status == "pending" and row.file_path == staged_path


# fix(#1708): stamped on the exception raised BY the final commit
# and read back in settlement — carried on the exception, not threaded as a
# handler flag, so the marker stays bound to the one await whose outcome is
# genuinely unknown.
_COMMIT_AMBIGUOUS_ATTR = "_geolens_url_import_commit_ambiguous"


async def _commit_staged_transition(db: AsyncSession) -> None:
    """The final running->pending commit, as a named seam.

    fix(#1708): split out so tests can simulate the
    ambiguous-commit shape — durable on the server, exception on the
    acknowledgement — which a real session can't produce on demand.
    Production behavior is exactly ``db.commit()``; the marking lives in
    ``_commit_staged_transition_guarded`` around it, so it's always applied
    by production code, not by whatever a test substitutes here.
    """
    await db.commit()


async def _commit_staged_transition_guarded(db: AsyncSession) -> None:
    """Commit the staged transition, marking the exception if it raises.

    fix(#1708): an exception out of THIS await, and only this
    one, is ambiguous — PostgreSQL may have applied the transition before
    the acknowledgement was lost. Marking it here lets settlement tell it
    apart from every failure whose outcome is known, without another branch
    in an already complexity-capped handler.
    """
    try:
        await _commit_staged_transition(db)
    except BaseException as exc:
        try:
            setattr(exc, _COMMIT_AMBIGUOUS_ATTR, True)
        except AttributeError:  # pragma: no cover - exotic exception types
            pass
        raise


async def _settle_failed_url_import(
    db: AsyncSession,
    exc: BaseException,
    *,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    s3_key: str | None,
    local_dest: Path | None,
    staged_path: str | None = None,
) -> None:
    """Everything that must happen when the URL-import fetch task raises.

    Until the file_path commit, the task exclusively owns the staged bytes
    (the local file and, if the put ran, the S3 object) — nothing else
    references them, so both go before the exception propagates.

    fix(#1708): the session's transaction is ROLLED BACK FIRST, before
    anything else here. The steps below — the probe's fresh session, the
    remote delete, the CAS — otherwise run while this caller still holds
    its failed transaction's pool connection.

    fix(#1708): the ambiguous-commit probe fires ONLY when the exception
    carries the marker ``_commit_staged_transition_guarded`` stamps on it.
    If it did, and PostgreSQL applied the transition before the
    acknowledgement was lost, the row is already 'pending' and bound to
    ``staged_path`` — live catalog state, so deleting the bytes would leave
    a durable pending job pointing at nothing, and settlement stands down
    entirely. Applied to EVERY failure (r11's mistake), the probe's "assume
    landed when the probe itself fails" default instead turned ordinary
    pre-commit failures into skipped cleanups and stranded 'running' jobs —
    the asymmetry is correct only where the outcome is genuinely unknown.

    fix(#1708): cleanup is best-effort STRUCTURALLY. A cleanup step that
    raises (the NUL-path unlink was one instance) previously escaped the
    caller's failure block before the failure CAS ran, stranding an
    undiscoverable 'running' job for the full lease — a shape, not an
    instance, so this helper makes "cleanup can never preempt the stamp" a
    property of the one function every failure goes through.

    fix(#1710): the failure CAS is fenced on ``attempt_id`` as well as
    'running'. A retry rotates the token, so a worker whose lease expired
    and later resumed must not stamp a newer attempt's row failed; zero rows
    means something external already settled it, and that verdict stands.

    fix(#1710): ``local_dest`` is None for a caller that does not own staged
    bytes. The task's outer handler is one: it settles failures raised
    outside the staging block, which happen either before any byte exists or
    AFTER the transition committed, and on local storage the published
    ``file_path`` IS ``local_dest`` — deleting it there would leave a durable
    pending row pointing at nothing.
    """
    # fix(#1710): stamped BEFORE any await, so a settlement that is itself
    # cancelled still tells the outer handler this failure was claimed.
    try:
        setattr(exc, _SETTLED_ATTR, True)
    except AttributeError:  # pragma: no cover - exotic exception types
        pass

    # Release the pool connection before the probe/remote delete (r14).
    # Best-effort: a session whose connection died mid-commit may refuse
    # this, and the CAS below opens its own transaction regardless.
    try:
        await db.rollback()
    except BaseException:
        logger.warning("url_import_settle_rollback_failed", job_id=str(job_id))

    if (
        getattr(exc, _COMMIT_AMBIGUOUS_ATTR, False)
        and staged_path is not None
        and await _url_import_transition_landed(job_id, staged_path)
    ):
        # fix(#1708): the transition is live, so the artifact the ROW
        # references must survive. Discriminator is the row itself:
        #   staged_path == str(local_dest) -> local storage; local_dest IS
        #     the referenced artifact, so it must not be deleted.
        #   staged_path != str(local_dest) -> S3; the row records only the
        #     staging key, so the local file is a redundant sniff copy that
        #     nothing downstream can discover — left behind, repeated
        #     ambiguous commits fill the staging volume.
        if local_dest is not None and staged_path != str(local_dest):
            try:
                # codeql[py/path-injection] fix(#1708): clamped, staging-rooted path — see fetch_url
                local_dest.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "url_import_landed_local_copy_cleanup_failed",
                    job_id=str(job_id),
                )
        logger.warning(
            "url_import_commit_ack_lost_but_landed",
            job_id=str(job_id),
            staged_path=staged_path,
        )
        return

    try:
        if s3_key is not None:
            # ``_cleanup_saved_upload`` drains and never raises. Unbounded
            # by design now (#1710): a worker has no response to deliver, and
            # the heartbeat renews the lease while a degraded provider
            # spends its own connect/read timeouts and retries.
            await _cleanup_saved_upload(s3_key, str(job_id))
        if local_dest is not None:
            # codeql[py/path-injection] fix(#1708): clamped, staging-rooted path — see fetch_url
            local_dest.unlink(missing_ok=True)
    except BaseException:
        logger.warning("url_import_cleanup_failed", job_id=str(job_id))
    # fix(#1710, rebased onto #1957): the terminal write goes through the
    # shared fenced helper, which arms the error-write budget so a row another
    # writer is holding cannot block this settlement indefinitely, and which
    # never raises. `None` is not a fence miss: the row stays running and the
    # stale sweep settles it.
    #
    # fix(#1953): the reason is the EXCEPTION, not a rendering of it. ADR-002's
    # door applies its own provenance rule, which a caller that flattens to
    # text first has already thrown away.
    fenced = await write_job_failure_for_attempt(
        db,
        job_id,
        attempt_id,
        values={
            "status": "failed",
            "error_message": redact_failure_reason(exc),
            "completed_at": datetime.now(timezone.utc),
        },
        task_name="fetch_url",
    )
    if fenced is False:
        logger.info("url_import_fail_stamp_skipped", job_id=str(job_id))


async def _effective_stream_cap(
    db: AsyncSession, user_id: uuid.UUID, max_size_bytes: int
) -> tuple[int, str | None]:
    """The fetch's byte cap, and the quota-shaped refusal detail if it is
    the quota rather than the instance limit doing the capping.

    fix(#1708): the SMALLER of the instance upload max and the
    caller's remaining CORE byte quota. With the instance-wide cap alone, a
    user at or near their storage cap could spend instance-max bandwidth,
    staging disk, and a worker slot on a download the post-stage check is
    guaranteed to refuse. ``storage_cap == 0`` means unlimited;
    zero remaining refuses here, before any fetch. The post-stage
    byte-charged check stays authoritative for races and the cloud
    entitlement seam, which this preflight doesn't consult.
    """
    usage = await get_user_quota_usage(db, user_id)
    if usage.storage_cap <= 0:
        return max_size_bytes, None
    remaining_quota = usage.storage_cap - usage.bytes_used
    if remaining_quota <= 0:
        raise UrlImportRefused(
            f"Storage quota exceeded: used {usage.bytes_used} of "
            f"{usage.storage_cap} bytes"
        )
    if remaining_quota < max_size_bytes:
        return remaining_quota, (
            "The remote file exceeds your remaining storage quota "
            f"({remaining_quota / (1024 * 1024):.1f} MB left)."
        )
    return max_size_bytes, None


async def _recheck_staged_quota(
    db: AsyncSession, user_id: uuid.UUID, actual_size: int
) -> None:
    """Charge the bytes that actually landed against the caller's quota.

    fix(#1710): a thin seam so the fetch task never imports
    ``app.modules.*`` itself — the PROCESS-02/04 burndown lists in
    ``tests/test_layering.py`` may only shrink, and this module already
    carries the quota edge. ``request`` is None because a worker has none;
    ``enforce_limit`` never reads it.

    The door's refusal is HTTP-shaped; a worker's is not, so the detail is
    re-raised as a domain failure whose text the stored-reason rule admits.
    """
    try:
        await check_upload_quota(db, user_id, actual_size, None)
    except HTTPException as exc:
        raise UrlImportRefused(str(exc.detail)) from exc
