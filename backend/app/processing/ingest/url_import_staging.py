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

    fix(#1708 codex r12): carries one fact settlement needs — the late-put
    reaper already owns this key's deletion, so the failure path must NOT
    synchronously await an S3 delete of it. A degraded endpoint is the very
    condition that produced the timeout, and that delete would spend
    botocore's read timeout plus retries on the way to the 502, pushing the
    response past the edge proxy's deadline: the exact loss the budget
    exists to prevent.
    """


async def _put_staging_object(s3_key: str, local_dest: Path) -> None:
    """Upload the staged local file to the S3 staging key.

    Owns its file handle so the task is self-contained: if the bounded wait
    in ``_stage_put_bounded`` abandons it at the deadline, the handle is
    still closed by THIS task's finally when the SDK thread finishes — the
    caller never closes a file a live upload thread is reading.
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

    The request has already answered 502 and ``_settle_failed_url_import``
    already attempted an S3 delete — but that delete may have run BEFORE the
    in-flight upload finished, in which case the late-landing object is an
    orphan nothing references. Re-delete once the task actually completes.
    ``_cleanup_saved_upload`` never raises; ``task.exception()`` is retrieved
    first so a failed upload does not log "exception was never retrieved".
    """

    def _cb(task: "asyncio.Task") -> None:
        # fix(#1708 codex r14): cancelled() FIRST. On a cancelled task
        # `exception()` RAISES CancelledError, which escaped this callback
        # before the cleanup below was ever scheduled — and because the
        # provider call drains, the upload can still land its object after
        # that cancellation propagates, leaving it unreferenced. All three
        # outcomes now schedule the same delete.
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

    fix(#1708 codex r7): the put is a blocking boto3 upload in a DRAINED
    thread — cancelling it does not bound wall time, because the drain
    deliberately blocks until the SDK thread finishes (storage/s3.py records
    why that trade is right for cancellation). So the deadline here is a
    bounded WAIT: at the budget's remainder the wait is abandoned — never
    cancelled — the request answers a clean 502 inside the proxy deadline,
    and the still-running task keeps its own file handle, stays bounded by
    botocore's connect/read timeouts and 3 adaptive retries, and hands its
    late-landing object (if any) to ``_abandoned_put_reaper`` for deletion.
    """
    remaining = stage_deadline - time.monotonic()
    detail = (
        "Staging the downloaded file did not finish within the time "
        "budget. Try again, or upload the file directly."
    )
    if remaining <= 0:
        raise _StagePutAbandoned(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)
    put_task = asyncio.create_task(_put_staging_object(s3_key, local_dest))
    # fix(#1708 codex r8): the reaper must exist from the moment the put
    # task can outlive this coroutine. asyncio.wait does not cancel the
    # task when IT is cancelled, so a request cancelled mid-wait (forced
    # worker shutdown) previously escaped before the timeout branch ever
    # installed the callback — the settle path then deleted the key while
    # the upload was still in flight, and its late-landing object had no
    # deleter. No await sits between create_task and this try, so every
    # exit that leaves the task running installs the reaper first.
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

    fix(#1708 codex r11): a commit whose acknowledgement is lost
    (cancellation or connection loss while ``COMMIT`` is in flight) may have
    been durably applied by PostgreSQL even though the await raised. Read
    the row back on a FRESH session — the request session is mid-failure
    and cannot be trusted to see anything. True means the job is live
    catalog state: 'pending' and bound to exactly the staged path this
    request wrote.

    A probe that itself fails returns True — standing down. The asymmetry
    is deliberate: standing down on a false positive orphans bytes that the
    sweeps can reclaim, while proceeding on a false negative deletes data a
    durable pending row points at, which nothing can reclaim.
    """
    # fix(#909)-style late bind so tests' engine patching is honored.
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


# fix(#1708 codex r14): stamped on the exception raised BY the final commit,
# and read back in settlement. Carrying the fact on the exception rather than
# threading a flag through the handler keeps the marker inseparable from the
# one await whose outcome is genuinely unknown — nothing else can acquire it
# by being re-raised through the same code path.
_COMMIT_AMBIGUOUS_ATTR = "_geolens_url_import_commit_ambiguous"


async def _commit_staged_transition(db: AsyncSession) -> None:
    """The final running->pending commit, as a named seam.

    fix(#1708 codex r11): split out so tests can simulate the
    ambiguous-commit shape — durable on the server, exception on the
    acknowledgement — which cannot be produced through a real session on
    demand. Production behavior is exactly ``db.commit()``.

    Kept as the bare commit so a test can replace it with an ack-lost
    stub; the marking lives in ``_commit_staged_transition_guarded`` around
    it, so the marker is always applied by production code rather than by
    whatever a test substitutes here.
    """
    await db.commit()


async def _commit_staged_transition_guarded(db: AsyncSession) -> None:
    """Commit the staged transition, marking the exception if it raises.

    fix(#1708 codex r14): an exception out of THIS await, and only this
    one, is ambiguous — PostgreSQL may have applied the transition before
    the acknowledgement was lost. Marking it here lets settlement tell it
    apart from every failure whose outcome is known, without threading a
    flag through the handler (which would also mean another branch in an
    already complexity-capped function).
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

    fix(#1708 codex r14): the session's transaction is ROLLED BACK FIRST,
    before anything else here. Everything below — the probe's fresh
    session, the remote delete, the CAS — used to run while this request
    still held its failed transaction's pool connection, so a burst of
    ordinary post-stage rejections (a quota race, say) could hold
    pool_size + max_overflow connections through a remote round-trip and
    stall unrelated traffic until DB_POOL_TIMEOUT. That is the connection
    family closed in r2/r7, reopened by a settlement path that grew.

    fix(#1708 codex r11, narrowed by r14): the ambiguous-commit probe fires
    ONLY when the exception itself carries the marker
    ``_commit_staged_transition`` stamps on it. If it did, and PostgreSQL applied
    the transition before the acknowledgement was lost, the row is already
    'pending' and bound to ``staged_path``: the bytes are live catalog
    state, deleting them would leave a durable pending job pointing at
    nothing, and the failure CAS would match zero rows anyway — so
    settlement stands down entirely and the request loses only its
    response. Scoping matters as much as the check: applied to EVERY
    failure (r11's mistake), the probe's deliberate "assume landed when the
    probe itself fails" default turned ordinary pre-commit failures into
    skipped cleanups and stranded 'running' jobs. The asymmetry is correct
    only where the outcome is genuinely unknown.

    fix(#1708 codex r5): cleanup is best-effort STRUCTURALLY. A cleanup step
    that raises (the NUL-path unlink was one instance) previously escaped
    the handler's failure block before the failure CAS ran, stranding an
    undiscoverable 'running' job for the full one-hour lease. That is a
    shape, not an instance — any raising cleanup reintroduces it — so this
    helper exists to make "cleanup can never preempt the stamp" a property
    of the one function every failure goes through.

    fix(#1708 codex P1/r2): the job row was committed before the fetch, so
    a rollback no longer removes it. The stamp is a guarded CAS from
    'running' only — zero rows means something external already settled the
    row, and that verdict is never overwritten. Best-effort throughout:
    never mask the original error, and a cancelled request may refuse the
    awaits — then the running sweep's hour is the fallback.
    """
    from sqlalchemy import update as sa_update

    from app.platform.jobs.models import IngestJob

    # Release the pool connection before the probe, the remote delete, or
    # anything else that can take time (r14). Best-effort: a session whose
    # connection died mid-commit may refuse this, and the CAS below opens
    # its own transaction regardless.
    try:
        await db.rollback()
    except BaseException:
        logger.warning("url_import_settle_rollback_failed", job_id=str(job_id))

    if (
        getattr(exc, _COMMIT_AMBIGUOUS_ATTR, False)
        and staged_path is not None
        and await _url_import_transition_landed(job_id, staged_path)
    ):
        # fix(#1708 codex r15): the transition is live, so the artifact the
        # ROW references must survive — but the local file is only that
        # artifact under local storage. The discriminator is the row itself:
        #
        #   staged_path == str(local_dest)  -> local storage. local_dest IS
        #       the referenced artifact. Deleting it would leave a pending
        #       job pointing at nothing, which is the whole failure this
        #       stand-down exists to avoid.
        #   staged_path != str(local_dest)  -> S3. The row records only the
        #       staging key, so the local file is a redundant copy that
        #       served the content sniff, and NOTHING downstream can ever
        #       discover it — no reaper sees a path no row references. Left
        #       behind, repeated ambiguous commits accumulate files up to
        #       the upload limit on the staging volume.
        #
        # The success path makes exactly the same distinction a few lines
        # later; this branch returns early, which is how it was missed.
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
        # fix(#1708 codex r12): the remote delete is the last unbounded
        # operation on the request path, and it sits on the failure path
        # that fires when S3 is degraded.
        #
        # Abandoned put: skip it entirely. `_abandoned_put_reaper` is
        # already attached to the live put task and deletes this key when
        # the upload actually ends — which is also the only ordering that
        # can win, since a delete issued now would race the in-flight
        # upload. Handing over costs nothing and saves the verdict.
        #
        # Every other failure: bound it by what is left of the request's
        # own budget. `_cleanup_saved_upload` drains and never raises, so
        # cancellation cannot stop it; the wait is abandoned instead and
        # the deletion continues in the background, with the stale-staging
        # sweep as the backstop if it ultimately fails.
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

    fix(#1708 codex r19): the preflight was bounded by a bare
    ``PREFLIGHT_DNS_MAX_SECONDS`` while the INVARIANT above states that
    every phase uses ``min(own ceiling, remaining)``. Harmless while the
    budget is healthy — the clock starts immediately before this phase, so
    the min is always the ceiling — but wrong in the floored regime, where
    a 1s budget would still have spent up to 30s resolving before anything
    refused. A comment stating a rule the code does not follow is the
    failure mode this PR has hit twice, so the code follows the rule.

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

    fix(#1708 codex r13): the fetch used to receive a fresh
    ``FETCH_MAX_SECONDS`` regardless of how much of the request's own clock
    auth, preflight DNS and the config/quota transaction had already spent —
    so a slow start could carry the response past the edge proxy even though
    each individual phase respected its own ceiling.
    ``fetch_url_to_path`` applies ``min(FETCH_MAX_SECONDS, this)``. Below
    ``MIN_FETCH_BUDGET_SECONDS`` no download can plausibly finish, so the
    request is refused now rather than opening a doomed connection.

    fix(#1708 codex r25): called TWICE per request — once immediately after
    the deadline is derived, purely for that refusal, and again here for the
    download's bound. Sharing one function is the point: an early check with
    its own threshold could drift from this one, and then the floor would
    promise a refusal at a size this call still accepts.
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

    fix(#1708 codex r10): the effective stream cap is the SMALLER of the
    instance upload max and the caller's remaining CORE byte quota. With
    the instance-wide cap alone, a user at or near their storage cap could
    spend instance-max bandwidth, staging disk, and a 480s request slot on
    downloads the post-stage check is guaranteed to refuse — and an honest
    at-cap user waited through the whole transfer for a 413 that was
    knowable at submission. ``storage_cap == 0`` means unlimited (the
    instance cap applies alone); zero remaining raises 413 here, before any
    fetch. The post-stage byte-charged check remains authoritative for
    races and the cloud entitlement seam, which this preflight does not
    consult.
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
