"""Staging helpers behind ``POST /ingest/upload/url``: budget, put, settlement."""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.async_io import run_in_thread_draining
from app.modules.quota.service import get_user_quota_usage
from app.platform.storage import get_storage
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.service import (
    _await_provider_call_draining,
    _cleanup_saved_upload,
)
from app.processing.ingest.url_fetch import (
    MIN_FETCH_BUDGET_SECONDS,
    PREFLIGHT_DNS_MAX_SECONDS,
)

logger = structlog.get_logger(__name__)


class _StagePutAbandoned(HTTPException):
    """The staging put outlived its budget and was abandoned, not cancelled.

    fix(#1708): carries the fact settlement needs — the late-put
    reaper already owns this key's deletion, so the failure path must NOT
    synchronously await an S3 delete of it. On a degraded endpoint that
    delete would spend botocore's read timeout plus retries and push the
    response past the edge proxy's deadline, the exact loss the budget
    exists to prevent.
    """


async def _put_staging_object(s3_key: str, local_dest: Path) -> None:
    """Upload the staged local file to the S3 staging key.

    Owns its file handle: if ``_stage_put_bounded`` abandons the wait at the
    deadline, this task's own finally still closes it once the SDK thread
    finishes — the caller never closes a file a live upload thread is reading.
    """
    # codeql[py/path-injection] fix(#1708): the component is basename-stripped (safe_upload_basename/filename_from_url) and byte-clamped, rooted under upload_staging_dir
    fh = open(local_dest, "rb")
    try:
        await _await_provider_call_draining(
            get_storage().put(resolve_current_storage_key(s3_key), fh)
        )
    finally:
        await run_in_thread_draining(fh.close)


def _abandoned_put_reaper(s3_key: str, job_id: str):
    """Done-callback for a staging put whose wait was abandoned at deadline.

    The request already answered 502 and ``_settle_failed_url_import``
    already attempted an S3 delete — but that may have run BEFORE the
    in-flight upload finished, orphaning the late-landing object. Re-delete
    once the task completes. ``_cleanup_saved_upload`` never raises;
    ``task.exception()`` is retrieved first so a failed upload doesn't log
    "exception was never retrieved".
    """

    def _cb(task: "asyncio.Task") -> None:
        # fix(#1708): cancelled() FIRST — on a cancelled task,
        # exception() RAISES CancelledError, which used to escape before
        # cleanup was scheduled. The provider call drains, so the upload can
        # still land after cancellation propagates; all three outcomes now
        # schedule the same delete.
        if task.cancelled():
            outcome = "cancelled"
        else:
            outcome = "failed" if task.exception() is not None else "landed_late"
        logger.warning(
            "url_import_abandoned_put_finished",
            job_id=job_id,
            s3_key=s3_key,
            outcome=outcome,
        )
        asyncio.ensure_future(_cleanup_saved_upload(s3_key, job_id))

    return _cb


async def _stage_put_bounded(
    s3_key: str, local_dest: Path, stage_deadline: float, job_id: str
) -> None:
    """Run the staging put inside what remains of the stage budget.

    fix(#1708): the put is a blocking boto3 upload in a DRAINED
    thread, so cancelling it wouldn't bound wall time (the drain blocks
    until the SDK thread finishes; see storage/s3.py). So the deadline is a
    bounded WAIT: at the remainder it's abandoned, never cancelled — the
    request answers a clean 502, and the still-running task stays bounded by
    botocore's connect/read timeouts and 3 retries, handing any late-landing
    object to ``_abandoned_put_reaper``.
    """
    remaining = stage_deadline - time.monotonic()
    detail = (
        "Staging the downloaded file did not finish within the time "
        "budget. Try again, or upload the file directly."
    )
    if remaining <= 0:
        raise _StagePutAbandoned(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    put_task = asyncio.create_task(_put_staging_object(s3_key, local_dest))
    # fix(#1708): the reaper must exist before the put task can
    # outlive this coroutine. asyncio.wait doesn't cancel the task when IT
    # is cancelled, so a mid-wait cancellation (forced shutdown) used to
    # escape before the timeout branch installed the callback, letting the
    # settle path delete the key while the upload was still in flight with
    # no deleter for its late-landing object. No await sits between
    # create_task and this try, so every exit installs the reaper first.
    try:
        _done, pending = await asyncio.wait({put_task}, timeout=remaining)
    except BaseException:
        if put_task.done():
            # Retrieve so a failed upload does not log "never retrieved";
            # the settle path deletes the key either way.
            put_task.exception()
        else:
            put_task.add_done_callback(_abandoned_put_reaper(s3_key, job_id))
            logger.warning(
                "url_import_stage_put_abandoned", job_id=job_id, s3_key=s3_key
            )
        raise
    if pending:
        put_task.add_done_callback(_abandoned_put_reaper(s3_key, job_id))
        logger.warning("url_import_stage_put_abandoned", job_id=job_id, s3_key=s3_key)
        raise _StagePutAbandoned(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    # Completed inside the budget: surface provider failures as themselves
    # (the settle path stamps the job failed and the outer handler maps them).
    put_task.result()


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
    s3_key: str | None,
    local_dest: Path,
    staged_path: str | None = None,
    stage_deadline: float | None = None,
) -> None:
    """Everything that must happen when the URL-import fetch path raises.

    Until the file_path commit, the request exclusively owns the staged
    bytes (the local file and, if the put ran, the S3 object) — nothing
    else references them, so both go before the exception propagates.

    fix(#1708): the session's transaction is ROLLED BACK FIRST,
    before anything else here. The steps below — the probe's fresh session,
    the remote delete, the CAS — used to run while this request still held
    its failed transaction's pool connection, so a burst of ordinary
    post-stage rejections (a quota race, say) could hold
    pool_size + max_overflow connections through a remote round-trip and
    stall unrelated traffic until DB_POOL_TIMEOUT.

    fix(#1708): the ambiguous-commit probe fires
    ONLY when the exception carries the marker
    ``_commit_staged_transition`` stamps on it. If it did, and PostgreSQL
    applied the transition before the acknowledgement was lost, the row is
    already 'pending' and bound to ``staged_path`` — live catalog state, so
    deleting the bytes would leave a durable pending job pointing at
    nothing, and settlement stands down entirely. Applied to EVERY failure
    (r11's mistake), the probe's "assume landed when the probe itself
    fails" default instead turned ordinary pre-commit failures into skipped
    cleanups and stranded 'running' jobs — the asymmetry is correct only
    where the outcome is genuinely unknown.

    fix(#1708): cleanup is best-effort STRUCTURALLY. A cleanup step
    that raises (the NUL-path unlink was one instance) previously escaped
    the handler's failure block before the failure CAS ran, stranding an
    undiscoverable 'running' job for the full one-hour lease — a shape, not
    an instance, so this helper makes "cleanup can never preempt the stamp"
    a property of the one function every failure goes through.

    fix(#1708): the job row was committed before the fetch, so a
    rollback no longer removes it. The stamp is a guarded CAS from
    'running' only — zero rows means something external already settled the
    row, and that verdict is never overwritten. Best-effort throughout:
    never mask the original error; a cancelled request may refuse the
    awaits, leaving the running sweep's hour as the fallback.
    """
    from sqlalchemy import update as sa_update

    from app.platform.jobs.models import IngestJob

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
        # fix(#1708): the transition is live, so the artifact the
        # ROW references must survive. Discriminator is the row itself:
        #   staged_path == str(local_dest) -> local storage; local_dest IS
        #     the referenced artifact, so it must not be deleted.
        #   staged_path != str(local_dest) -> S3; the row records only the
        #     staging key, so the local file is a redundant sniff copy that
        #     nothing downstream can discover — left behind, repeated
        #     ambiguous commits fill the staging volume.
        # The success path makes the same distinction later; this branch
        # returns early, which is how it was missed before.
        if staged_path != str(local_dest):
            try:
                # codeql[py/path-injection] fix(#1708): clamped, staging-rooted path — see upload_from_url
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
        # fix(#1708): the remote delete is the last unbounded op
        # on the failure path that fires when S3 is degraded.
        # Abandoned put: skip it entirely — `_abandoned_put_reaper` is
        # already attached to the live put task and deletes this key when
        # the upload ends, the only ordering that can win (a delete issued
        # now would race the in-flight upload).
        # Every other failure: bound by what's left of the request's own
        # budget. `_cleanup_saved_upload` drains and never raises, so the
        # wait is abandoned rather than cancelled, with the stale-staging
        # sweep as backstop.
        if s3_key is not None and not isinstance(exc, _StagePutAbandoned):
            cleanup_budget = (
                None if stage_deadline is None else stage_deadline - time.monotonic()
            )
            if cleanup_budget is not None and cleanup_budget <= 0:
                logger.warning(
                    "url_import_cleanup_deferred_no_budget",
                    job_id=str(job_id),
                    s3_key=s3_key,
                )
            else:
                cleanup_task = asyncio.create_task(
                    _cleanup_saved_upload(s3_key, str(job_id))
                )
                _done, still_running = await asyncio.wait(
                    {cleanup_task}, timeout=cleanup_budget
                )
                if still_running:
                    logger.warning(
                        "url_import_cleanup_abandoned",
                        job_id=str(job_id),
                        s3_key=s3_key,
                    )
        # Local disk, not the network. Safe while the abandoned put may
        # still be reading it: POSIX keeps the inode alive for that open
        # handle until the task's own finally closes it.
        # codeql[py/path-injection] fix(#1708): clamped, staging-rooted path — see upload_from_url
        local_dest.unlink(missing_ok=True)
    except BaseException:
        logger.warning("url_import_cleanup_failed", job_id=str(job_id))
    try:
        # No rollback here: the transaction was already ended above, and
        # this CAS opens a fresh one of its own.
        await db.execute(
            sa_update(IngestJob)
            .where(IngestJob.id == job_id, IngestJob.status == "running")
            .values(
                status="failed",
                error_message=(
                    str(exc.detail)
                    if isinstance(exc, HTTPException)
                    else "URL import failed"
                ),
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    except BaseException:
        logger.warning("url_import_fail_stamp_skipped", job_id=str(job_id))


_BUDGET_EXHAUSTED_DETAIL = (
    "Not enough time remained in the request budget to download this file. Try again."
)


def _preflight_dns_budget(stage_deadline: float) -> float:
    """The preflight resolution's bound: min(its ceiling, what remains).

    fix(#1708): previously bounded by a bare
    ``PREFLIGHT_DNS_MAX_SECONDS``, which is harmless while the budget is
    healthy but wrong in the floored regime — a 1s budget could still spend
    up to 30s resolving before anything refused.

    With nothing left, refuse with the BUDGET's message rather than a
    zero-second DNS timeout, which would blame the resolver for an
    exhausted clock.
    """
    remaining = stage_deadline - time.monotonic()
    if remaining <= 0.0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_BUDGET_EXHAUSTED_DETAIL,
        )
    return min(float(PREFLIGHT_DNS_MAX_SECONDS), remaining)


def _remaining_fetch_budget(stage_deadline: float) -> float:
    """What the joint budget has left for the download, or a prompt refusal.

    fix(#1708): the fetch used to get a fresh ``FETCH_MAX_SECONDS``
    regardless of how much of the request's own clock auth, preflight DNS
    and the config/quota transaction had already spent — so a slow start
    could carry the response past the edge proxy even though each phase
    respected its own ceiling. ``fetch_url_to_path`` applies
    ``min(FETCH_MAX_SECONDS, this)``; below ``MIN_FETCH_BUDGET_SECONDS`` the
    request is refused now rather than opening a doomed connection.

    fix(#1708): called TWICE per request — once right after the
    deadline is derived, for that refusal, and again here for the
    download's bound. One shared function so an early check's own threshold
    can't drift from this one.
    """
    remaining = stage_deadline - time.monotonic()
    if remaining < MIN_FETCH_BUDGET_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_BUDGET_EXHAUSTED_DETAIL,
        )
    return remaining


async def _effective_stream_cap(
    db: AsyncSession, user_id: uuid.UUID, max_size_bytes: int
) -> tuple[int, str | None]:
    """The fetch's byte cap, and the quota-shaped refusal detail if it is
    the quota rather than the instance limit doing the capping.

    fix(#1708): the SMALLER of the instance upload max and the
    caller's remaining CORE byte quota. With the instance-wide cap alone, a
    user at or near their storage cap could spend instance-max bandwidth,
    staging disk, and a 480s request slot on a download the post-stage
    check is guaranteed to refuse. ``storage_cap == 0`` means unlimited;
    zero remaining raises 413 here, before any fetch. The post-stage
    byte-charged check stays authoritative for races and the cloud
    entitlement seam, which this preflight doesn't consult.
    """
    usage = await get_user_quota_usage(db, user_id)
    if usage.storage_cap <= 0:
        return max_size_bytes, None
    remaining_quota = usage.storage_cap - usage.bytes_used
    if remaining_quota <= 0:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"Storage quota exceeded: used {usage.bytes_used} of "
                f"{usage.storage_cap} bytes"
            ),
        )
    if remaining_quota < max_size_bytes:
        return remaining_quota, (
            "The remote file exceeds your remaining storage quota "
            f"({remaining_quota / (1024 * 1024):.1f} MB left)."
        )
    return max_size_bytes, None
