"""Background download for the URL import (feat #1710).

``POST /ingest/upload/url`` validates and answers immediately; this task does
the work that used to run inside that request. Nothing about Rule 2 changes by
moving here — ``validate_url_for_ssrf`` gated the URL at submission,
``make_safe_client`` re-resolves and pins the address at connect time and
re-validates every redirect hop, the size cap is counted per chunk, and GDAL
still only ever meets the staged local file.

The row is committed ``running`` by the door, so this task ADOPTS an existing
lease rather than claiming a pending one, and renews it with the ordinary
ingest heartbeat for the whole transfer. Success is a fenced CAS to
``pending``: the state the rest of the import pipeline calls previewable.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select

from app.core.config import settings
from app.core.db.tenant_session import tenant_task
from app.core.persistent_config import UPLOAD_MAX_SIZE_MB
from app.platform.jobs.heartbeat import (
    maintain_ingest_job_heartbeat,
    stop_ingest_job_heartbeat,
    update_ingest_job_for_attempt,
)
from app.platform.jobs.models import COMMIT_ATTEMPTED_METADATA_KEY, IngestJob
from app.processing.ingest.service import raster_stamped_metadata
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    cleanup_step,
    purge_queued_job_arg,
    task_app,
)
from app.processing.ingest.url_fetch import fetch_url_to_path
from app.processing.ingest.url_import_staging import (
    _SETTLED_ATTR,
    UrlImportRefused,
    _commit_staged_transition_guarded,
    _effective_stream_cap,
    _put_staging_object,
    _recheck_staged_quota,
    _settle_failed_url_import,
)
from app.processing.ingest.validation import validate_file_content

logger = structlog.get_logger(__name__)

# fix(#1710): the CAS lost the row. Raised rather than returned so the one
# settlement path stamps it, and worded for the job owner, who sees it as the
# job's error_message.
_LEASE_LOST_DETAIL = (
    "The import was cancelled or timed out while the file was downloading. "
    "Start a new import."
)


async def _adopt_running_lease(
    session, job_id: uuid.UUID, attempt_id: uuid.UUID, local_dest: Path
) -> bool:
    """Take over the lease the door committed, or report that it is gone.

    fix(#1710): the row is already 'running' under this attempt's token, so
    the ordinary pending->running claim does not apply. The fence is the one
    every other task uses; a miss means a cancel, a retry or the stale sweep
    settled the row first, and this delivery must touch nothing.

    fix(#1710): ``file_path`` names the destination BEFORE the first byte
    lands, so a hard-killed worker leaves a partial the retention purge's
    ``_reap_committed_staged_paths`` can still find. The success CAS
    overwrites it with wherever the file was actually staged.
    """
    adopted = await update_ingest_job_for_attempt(
        session,
        job_id,
        attempt_id,
        values={
            "heartbeat_at": datetime.now(timezone.utc),
            "current_step": "downloading",
            "progress": 0.0,
            "file_path": str(local_dest),
        },
        expected_status="running",
    )
    if not adopted:
        await session.rollback()
        return False
    await session.commit()
    return True


async def _staged_values(
    session, job_id: uuid.UUID, staged_path: str, filename: str
) -> dict[str, object]:
    """The columns the running -> pending transition writes.

    fix(#1708): ``staged_at`` restarts the pending review window.
    ``stale_pending_clauses`` measures pending age from
    ``coalesce(staged_at, created_at)``, so the download no longer eats the
    review window. Always an isoformat timestamptz; the sweep casts it.

    fix(#1710): the dispatch marker is DROPPED here. ``abandoned_upload`` in
    sweep.py reads its absence as "no ingest was ever dispatched for this
    row", which is true again once the file is merely staged — the door
    stamped it for the download task, not for an import. Leaving it would
    report an abandoned URL import as ``failed`` instead of ``cancelled``.
    """
    existing = (
        await session.execute(
            select(IngestJob.user_metadata).where(IngestJob.id == job_id)
        )
    ).scalar_one_or_none() or {}
    carried = {k: v for k, v in existing.items() if k != COMMIT_ATTEMPTED_METADATA_KEY}
    return {
        "file_path": staged_path,
        "status": "pending",
        "current_step": None,
        "progress": None,
        "user_metadata": {
            **(raster_stamped_metadata(carried, filename) or {}),
            "staged_at": datetime.now(timezone.utc).isoformat(),
        },
    }


@task_app.task(queue="ingest", retry=0, pass_context=True)
@tenant_task
async def fetch_url(
    job_context: Any = None,
    /,
    *,
    job_id: str,
    url: str,
    user_id: str,
    filename: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Download a submitted file URL into staging and make the job previewable.

    Sequence: adopt the running lease, download under the size cap, sniff the
    staged bytes, copy to object storage when that is the staging store,
    re-charge the real byte count against quota, then CAS running -> pending.
    Any failure deletes the bytes this task owns and stamps the row failed.
    """
    _bind_task_log_context(task_name="fetch_url", job_id=job_id)

    # Late bind so a test's engine patching is honored (fix(#909)).
    import app.core.db as db_module

    job_uuid = uuid.UUID(job_id)
    if attempt_id is None:
        # feat(#1710): the door always dispatches a token. Adopting a
        # 'running' row without one would let a delivery whose lease had
        # already been reaped overwrite whatever owns the row now.
        logger.warning("url_fetch_delivery_without_attempt_token", job_id=job_id)
        return
    attempt_uuid = uuid.UUID(attempt_id)

    heartbeat_task: asyncio.Task[None] | None = None
    staging_dir = Path(settings.upload_staging_dir)
    local_dest = staging_dir / f"{job_id}_{filename}"

    try:
        async with db_module.async_session() as session:
            if not await _adopt_running_lease(
                session, job_uuid, attempt_uuid, local_dest
            ):
                logger.info("url_fetch_lease_already_settled", job_id=job_id)
                return
        # fix(#1710): the URL is in memory now, and `retry=0` means nothing
        # re-runs from these args, so drop it from the queue row before the
        # transfer. A presigned S3 or SAS link is bearer-equivalent, and the
        # worker deletes only SUCCESSFUL rows.
        await purge_queued_job_arg(job_context, arg_key="url")
        heartbeat_task = asyncio.create_task(
            maintain_ingest_job_heartbeat(job_uuid, attempt_uuid)
        )
        # INVARIANT: every step after the lease is adopted settles the row.
        # The staging block owns the ones that can hold staged bytes; the
        # handler below is the backstop for the rest, including a session
        # this block cannot even open.
        await _stage_downloaded_file(
            db_module,
            url=url,
            job_id=job_id,
            job_uuid=job_uuid,
            attempt_uuid=attempt_uuid,
            user_id=user_id,
            filename=filename,
            local_dest=local_dest,
            staging_dir=staging_dir,
        )
    except Exception as exc:  # broad: network, file I/O, storage and DB all reach here
        # fix(#1710): a failure that never reached the staging block — the
        # lease adoption itself, or the heartbeat's own start — has not been
        # settled by anyone, and logging alone would leave the row 'running'
        # with no reason until the lease reaper. Settle it here on a fresh
        # session; the CAS is fenced, so a row this delivery no longer owns
        # matches zero rows and keeps whatever verdict it has.
        if not getattr(exc, _SETTLED_ATTR, False):
            async with db_module.async_session() as settle_session:
                # local_dest is None on purpose: this handler owns no bytes.
                # It also catches a teardown raised AFTER the transition
                # committed, where on local storage local_dest IS the
                # published file_path. `fetch_url_to_path` already unlinks
                # its own partial, so nothing here needs deleting.
                await _settle_failed_url_import(
                    settle_session,
                    exc,
                    job_id=job_uuid,
                    attempt_id=attempt_uuid,
                    s3_key=None,
                    local_dest=None,
                )
        # Swallowed so an ordinary refusal (size cap, content mismatch, dead
        # origin) is not reported as a crashed worker. The URL never enters
        # the event: it is caller-supplied and can carry userinfo.
        logger.warning(
            "url_import_failed",
            job_id=job_id,
            reason=type(exc).__name__,
            exc_info=not isinstance(exc, UrlImportRefused),
        )
    finally:
        async with cleanup_step("fetch_url heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)


async def _stage_downloaded_file(
    db_module,
    *,
    url: str,
    job_id: str,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    user_id: str,
    filename: str,
    local_dest: Path,
    staging_dir: Path,
) -> None:
    """Download, sniff, stage and publish, settling the row on any failure.

    Split from ``fetch_url`` so one ``except BaseException`` covers every step
    that can own staged bytes: until the transition commits, this task is the
    only referent of the local file and its storage copy, so both go before
    the exception propagates. After it commits nothing here owns them, which
    ``published`` records positively rather than inferring from the exception.
    """
    s3_key: str | None = None
    staged_path: str | None = None
    published = False
    try:
        # fix(#1710 codex): the config and quota reads get their OWN session,
        # ended before the download. Holding one across a transfer that may
        # run for url_import_fetch_max_seconds would pin a pool connection per
        # concurrent import — the starvation #1708 fixed on the request path.
        async with db_module.async_session() as session:
            max_size_bytes = (await UPLOAD_MAX_SIZE_MB.get(session)) * 1024 * 1024
            # The smaller of the instance cap and what the caller's quota has
            # left, so a user at their cap cannot spend a worker slot on a
            # download the post-stage check is guaranteed to refuse.
            effective_cap_bytes, cap_error_detail = await _effective_stream_cap(
                session, uuid.UUID(user_id), max_size_bytes
            )
            await session.rollback()

        staging_dir.mkdir(parents=True, exist_ok=True)
        actual_size = await fetch_url_to_path(
            url,
            local_dest,
            effective_cap_bytes,
            cap_error_detail=cap_error_detail,
        )

        # The same staged-file content sniff a direct upload gets.
        validate_file_content(str(local_dest), filename)

        if settings.storage_provider == "s3":
            s3_key = f"staging/{job_id}/{filename}"
            await _put_staging_object(s3_key, local_dest)
            staged_path = s3_key
        else:
            staged_path = str(local_dest)

        async with db_module.async_session() as session:
            # fix(#1710): the byte quota is charged on what actually landed.
            # The door charged zero: a remote server's Content-Length was
            # never evidence of anything.
            await _recheck_staged_quota(session, uuid.UUID(user_id), actual_size)

            # fix(#1708): guarded CAS, running -> pending. A Core UPDATE, not
            # dirtied ORM attributes (which would flush a second, unguarded
            # UPDATE), so an external flip — a cancel, or a lease reap —
            # matches zero rows and is SURFACED instead of silently
            # part-updating a dead row.
            if not await update_ingest_job_for_attempt(
                session,
                job_uuid,
                attempt_uuid,
                values=await _staged_values(session, job_uuid, staged_path, filename),
                expected_status="running",
            ):
                raise UrlImportRefused(_LEASE_LOST_DETAIL)
            await _commit_staged_transition_guarded(session)
            # fix(#1710): set INSIDE the block, so a session teardown that
            # raises after the commit still finds it True. Publication is a
            # fact about the row, never something inferred from an exception.
            published = True
    except BaseException as exc:
        if published:
            # The row is live catalog state bound to these bytes; nothing here
            # may touch them. The task's outer handler settles nothing either,
            # since its CAS is fenced on 'running'.
            logger.warning(
                "url_import_teardown_after_publish",
                job_id=job_id,
                reason=type(exc).__name__,
            )
            raise
        async with db_module.async_session() as settle_session:
            await _settle_failed_url_import(
                settle_session,
                exc,
                job_id=job_uuid,
                attempt_id=attempt_uuid,
                s3_key=s3_key,
                local_dest=local_dest,
                staged_path=staged_path,
            )
        raise

    if s3_key is not None:
        # Object storage is the staging store; the local copy has no further
        # reader. Best-effort: the job is already previewable, so a failing
        # delete must not rewrite that success as a failure.
        async with cleanup_step("fetch_url local staging copy", job_id=job_id):
            # codeql[py/path-injection] fix(#1710): clamped, staging-rooted path — see fetch_url_to_path
            local_dest.unlink(missing_ok=True)

    logger.info(
        "url_import_staged",
        job_id=job_id,
        filename=filename,
        size_bytes=actual_size,
    )
