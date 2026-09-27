"""The follow-ups a job owes once its terminal commit has landed.

A first ingest owes its completion follow-ups, and a rejected replacement its
failure notice. A publish that consumed a staged upload also owes items: the
upload's archive and then its deletion. The terminal transaction records them
on the job row, so the record exists exactly when the commit does. The task
runs them after its commit, or the stale-job sweep when the task could not.
Each item is confirmed on its own and retried after a doubling delay; the
record is claimed, and the rest runs once, only when no item is left.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import (
    DateTime,
    Integer,
    Text,
    cast,
    func,
    literal,
    or_,
    select,
    text,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.failure_reason import redact_failure_reason
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.models import (
    ARCHIVE_PENDING_METADATA_KEY,
    PUBLISH_FOLLOWUPS_FIELD,
    IngestJob,
    owned_presigned_staging_key,
)
from app.processing.ingest.tasks_common import _emit_billing_event, cleanup_step
from app.processing.ingest.tasks_staging import (
    _archive_original_file,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Each first ingest's completion-notice label, or None when it sends no notice
# and bills nothing.
_LABELS: dict[str, str | None] = {
    "ingest_raster": "Raster",
    "ingest_tileset": "3D Tiles",
    "ingest_pointcloud": "Point cloud",
    "ingest_vrt": None,
}

_SWEEP_BATCH = 50

# A replacement or a vector import runs its own completion steps, so its
# record owes only its items.
_ITEMS_ONLY = frozenset({"reupload_file", "reupload_raster", "ingest_file"})

# The items a record can owe, each a key in the record that is removed alone
# once it is confirmed.
_ARCHIVE_KEY = "archive_key"
_REAPS_STAGED_UPLOAD = "reaps_staged_upload"
_ITEMS = (_ARCHIVE_KEY, _REAPS_STAGED_UPLOAD)

# Retry state kept in the record. The doubling delay rides out a storage
# outage of a few hours; after the last attempt the record is claimed and the
# job keeps its archive flag, which holds the upload for the operator.
_ATTEMPTS = "attempts"
_NEXT_ATTEMPT_AT = "next_attempt_at"
_RETRY_BASE = timedelta(minutes=5)
_RETRY_CAP = timedelta(hours=4)
_MAX_ATTEMPTS = 8


def owed_followups(
    attempt_uuid: uuid.UUID,
    task: str,
    *,
    reaps_staged_upload: bool = False,
    archive_key: str | None = None,
    sweep_waits: bool = False,
):
    """The job's ``user_metadata`` with this attempt's ``task`` follow-ups owed.

    With ``archive_key`` it also marks the upload's archive pending, which the
    follow-ups remove once that archive exists. ``sweep_waits`` holds the
    sweep off for one retry delay, for a task that archives the upload itself.
    """
    fields = ["task", task, "attempt_id", str(attempt_uuid)]
    marks = []
    if reaps_staged_upload:
        fields += [_REAPS_STAGED_UPLOAD, true()]
    if archive_key is not None:
        fields += [_ARCHIVE_KEY, archive_key]
        marks = [ARCHIVE_PENDING_METADATA_KEY, true()]
    if sweep_waits:
        fields += [_NEXT_ATTEMPT_AT, func.now() + _RETRY_BASE]
    owed = func.jsonb_build_object(
        PUBLISH_FOLLOWUPS_FIELD, func.jsonb_build_object(*fields), *marks
    )
    return func.coalesce(IngestJob.user_metadata, text("'{}'::jsonb")).op("||")(owed)


async def note_publish_followups(
    session: AsyncSession,
    job_uuid: uuid.UUID,
    attempt_uuid: uuid.UUID,
    task: str,
    *,
    reaps_staged_upload: bool = False,
) -> None:
    """Record, in the terminal transaction, that this attempt's ``task`` follow-ups are owed.

    ``reaps_staged_upload`` adds deleting the job's staged upload, which the
    publish no longer needs.
    """
    await session.execute(
        update(IngestJob)
        .where(IngestJob.id == job_uuid, IngestJob.attempt_id == attempt_uuid)
        .values(
            user_metadata=owed_followups(
                attempt_uuid, task, reaps_staged_upload=reaps_staged_upload
            )
        )
        .execution_options(synchronize_session=False)
    )


def _in_staging_dir(path: str) -> bool:
    """Whether ``path`` resolves, following links, inside the upload staging directory."""
    return (
        Path(path).resolve().is_relative_to(Path(settings.upload_staging_dir).resolve())
    )


async def _note_archive_outcome(job_uuid: uuid.UUID, error: str | None) -> None:
    """Flag the job's archive as failed with ``error``, or with None as made; never raises.

    It is the flag ``_archive_original_file`` sets. A made archive clears it
    and the archive-pending mark. Edits the stored metadata in place, since
    writing back a copy could restore a record a concurrent claim has cleared.
    """
    import app.core.db as db_module

    stored = IngestJob.user_metadata
    outcome = update(IngestJob).where(IngestJob.id == job_uuid)
    if error is None:
        outcome = outcome.where(
            or_(
                stored.has_key("archive_failed"),
                stored.has_key(ARCHIVE_PENDING_METADATA_KEY),
            )
        )
        metadata = stored.op("-")(literal("archive_failed", Text))
        metadata = metadata.op("-")(literal("archive_error", Text))
        metadata = metadata.op("-")(literal(ARCHIVE_PENDING_METADATA_KEY, Text))
    else:
        flag = func.jsonb_build_object(
            "archive_failed", true(), "archive_error", error[:500]
        )
        metadata = func.coalesce(stored, text("'{}'::jsonb")).op("||")(flag)
    async with cleanup_step("archive outcome", job_id=str(job_uuid)):
        async with db_module.async_session() as session:
            await session.execute(
                outcome.values(user_metadata=metadata).execution_options(
                    synchronize_session=False
                )
            )
            await session.commit()


async def _archive_in_place(archive_key: str) -> bool:
    """Whether storage holds an object under ``archive_key``; False when it can't tell."""
    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key

    try:
        return await get_storage().exists(resolve_current_storage_key(archive_key))
    except Exception:  # broad: an unreadable store leaves the archive unconfirmed
        return False


async def _archive_upload(
    job_uuid: uuid.UUID,
    file_path: str,
    dataset_id: uuid.UUID,
    archive_key: str,
    local_copy: str | None = None,
) -> bool:
    """Whether ``archive_key`` holds the upload's original, archiving it now if not.

    ``archive_key`` names this upload alone, so an object already there is its
    archive. Reads the upload from ``local_copy`` when the caller holds one,
    and otherwise the way its task did, through ``resolve_file_path``, but
    never a local file outside the staging directory. Any other failure flags
    the job's archive as failed, and an archive in place clears the flag, even
    one found only after a failure, as when another run made it meanwhile.
    """
    import app.core.db as db_module
    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key
    from app.processing.ingest.service import resolve_file_path

    job_id = str(job_uuid)
    local: str | None = None
    downloaded = False
    try:
        if await get_storage().exists(resolve_current_storage_key(archive_key)):
            await _note_archive_outcome(job_uuid, None)
            return True
        if local_copy is not None and Path(local_copy).exists():
            local = local_copy
        else:
            local = await resolve_file_path(file_path, job_id)
            downloaded = local != file_path
        if local == file_path and not _in_staging_dir(local):
            structlog.get_logger().warning(
                "staged_upload_outside_staging_dir", job_id=job_id
            )
            await _note_archive_outcome(
                job_uuid, "The staged upload is outside the upload staging directory."
            )
            return False
        async with db_module.async_session() as session:
            job = await session.get(IngestJob, job_uuid)
            archived = job is not None and await _archive_original_file(
                session,
                job=job,
                dataset_id=dataset_id,
                file_path=local,
                log_message="Failed to archive re-uploaded file to storage",
                archive_name=archive_key.rsplit("/", 1)[-1],
            )
        if archived or await _archive_in_place(archive_key):
            await _note_archive_outcome(job_uuid, None)
            return True
        return False
    except Exception as exc:  # broad: an unreadable upload or store keeps the upload
        if await _archive_in_place(archive_key):
            await _note_archive_outcome(job_uuid, None)
            return True
        structlog.get_logger().warning("staged_upload_archive_failed", job_id=job_id)
        await _note_archive_outcome(job_uuid, str(exc))
        return False
    finally:
        if downloaded:
            Path(local).unlink(missing_ok=True)


async def _delete_staged_upload(job_uuid: uuid.UUID, file_path: str | None) -> None:
    """Delete the staged upload ``file_path`` names, as its task's cleanup does; never raises.

    ``file_path`` is a local file when ``resolve_file_path`` would read it as
    one, and is unlinked only inside the upload staging directory. A
    ``staging/`` path is also deleted from storage.
    """
    from app.core.tenancy import is_multi_tenant

    if not file_path:
        return
    job_id = str(job_uuid)
    async with cleanup_step("staged upload", job_id=job_id):
        path = Path(file_path)
        if path.exists() and (path.is_absolute() or not is_multi_tenant()):
            if _in_staging_dir(file_path):
                path.resolve().unlink(missing_ok=True)
            else:
                structlog.get_logger().warning(
                    "staged_upload_outside_staging_dir", job_id=job_id
                )
    await reap_downloaded_staging_source(
        job_id,
        original_file_path=file_path,
        final_status="complete",
        failed_source_replayable=True,
    )


async def _confirm_owed_item(job_uuid: uuid.UUID, item: str) -> None:
    """Take ``item`` alone off the job's follow-up record; every other item stays owed."""
    import app.core.db as db_module

    stored = IngestJob.user_metadata
    path = literal([PUBLISH_FOLLOWUPS_FIELD, item], ARRAY(Text))
    async with db_module.async_session() as session:
        await session.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job_uuid, stored[PUBLISH_FOLLOWUPS_FIELD].is_not(None)
            )
            .values(user_metadata=stored.op("#-")(path))
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def _schedule_retry(job_uuid: uuid.UUID, attempts: int) -> None:
    """Count ``attempts`` on the job's record and set when the next one is due."""
    import app.core.db as db_module

    delay = min(_RETRY_BASE * 2 ** (attempts - 1), _RETRY_CAP)
    stored = IngestJob.user_metadata
    counted = func.jsonb_set(
        stored,
        literal([PUBLISH_FOLLOWUPS_FIELD, _ATTEMPTS], ARRAY(Text)),
        func.to_jsonb(literal(attempts, Integer)),
    )
    scheduled = func.jsonb_set(
        counted,
        literal([PUBLISH_FOLLOWUPS_FIELD, _NEXT_ATTEMPT_AT], ARRAY(Text)),
        func.to_jsonb(func.now() + delay),
    )
    async with db_module.async_session() as session:
        await session.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job_uuid, stored[PUBLISH_FOLLOWUPS_FIELD].is_not(None)
            )
            .values(user_metadata=scheduled)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def _settle_owed_items(
    job_uuid: uuid.UUID, row, *, local_copy: str | None = None
) -> bool:
    """Run the items a published job's record owes; True once none is left to retry.

    The client's presigned key goes whatever the archive does, since the
    archive reads only ``file_path``. With a live dataset the upload's
    original is archived first, and the upload is deleted only once that
    archive is confirmed. An item left over is tried again after a doubling
    delay, until the attempts run out.
    """
    job_id = str(job_uuid)
    record = row.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    left = {item for item in _ITEMS if item in record}
    file_path = row.file_path
    if _ARCHIVE_KEY in left and (
        not file_path
        or row.dataset_id is None
        or await _archive_upload(
            job_uuid, file_path, row.dataset_id, record[_ARCHIVE_KEY], local_copy
        )
    ):
        await _confirm_owed_item(job_uuid, _ARCHIVE_KEY)
        left.discard(_ARCHIVE_KEY)
    if _REAPS_STAGED_UPLOAD in left:
        await reap_presigned_staging_object(
            job_id,
            owned_presigned_staging_key(job_uuid, row.user_metadata, file_path),
            final_status="complete",
        )
        if _ARCHIVE_KEY not in left:
            await _delete_staged_upload(job_uuid, file_path)
            await _confirm_owed_item(job_uuid, _REAPS_STAGED_UPLOAD)
            left.discard(_REAPS_STAGED_UPLOAD)
    if not left:
        return True
    attempts = int(record.get(_ATTEMPTS) or 0) + 1
    if attempts >= _MAX_ATTEMPTS:
        structlog.get_logger().warning(
            "publish_followups_attempts_spent", job_id=job_id, left=sorted(left)
        )
        return True
    await _schedule_retry(job_uuid, attempts)
    return False


def _owes_items(row) -> bool:
    """Whether a job's record owes items, for the attempt that ended the job complete."""
    record = row.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    return (
        row.status == "complete"
        and row.owed_attempt == str(row.attempt_id)
        and any(item in record for item in _ITEMS)
    )


def _due_at(record):
    """When a follow-up record is due: its next attempt, or else when its job ended."""
    return func.coalesce(
        cast(record[_NEXT_ATTEMPT_AT].astext, DateTime(timezone=True)),
        IngestJob.completed_at,
        IngestJob.created_at,
    )


async def run_publish_followups(
    job_uuid: uuid.UUID, *, local_copy: str | None = None
) -> bool:
    """Run a job's owed follow-ups once its terminal commit is visible and they are due.

    A complete job's record first has its items run, before the claim and
    holding no lock; while one is left the record stays owed and is retried
    later, so a caller stopped short leaves it for the next one. The claim then
    takes the record at most once, and the job's status chooses what runs: a
    complete first ingest's follow-ups, or a failed job's ``ingest_failed``
    notice. A replacement or a vector import owes nothing past its items. A job
    in neither status runs nothing, and a row another caller has locked nothing
    past the items. A record an earlier attempt wrote is cleared and runs
    nothing, and a deleted dataset skips the rest. Returns whether this call
    claimed.

    ``local_copy`` is a copy of the upload the caller holds and keeps; the
    archive reads it instead of downloading the upload again.
    """
    import app.core.db as db_module
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant
    from app.platform.extensions import get_processing_port
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )
    from app.processing.embeddings.helpers import defer_embedding

    owed = IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    owed_row = select(
        IngestJob.status,
        IngestJob.dataset_id,
        IngestJob.error_message,
        IngestJob.attempt_id,
        owed["task"].astext.label("task"),
        owed["attempt_id"].astext.label("owed_attempt"),
        IngestJob.file_path,
        IngestJob.user_metadata,
    ).where(
        IngestJob.id == job_uuid,
        IngestJob.status.in_(("complete", "failed")),
        owed.is_not(None),
        _due_at(owed) <= func.now(),
    )
    async with db_module.async_session() as session:
        pending = (await session.execute(owed_row)).one_or_none()
    if pending is not None and _owes_items(pending):
        if not await _settle_owed_items(job_uuid, pending, local_copy=local_copy):
            return False

    async with db_module.async_session() as session:
        claim = (
            await session.execute(owed_row.with_for_update(skip_locked=True))
        ).one_or_none()
        if claim is None:
            return False
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_uuid)
            .values(
                user_metadata=IngestJob.user_metadata.op("-")(
                    literal(PUBLISH_FOLLOWUPS_FIELD, Text)
                )
            )
            .execution_options(synchronize_session=False)
        )
        await session.commit()

    task = claim.task
    job_id = str(job_uuid)
    log = structlog.get_logger().bind(job_id=job_id, task=task)
    if claim.owed_attempt != str(claim.attempt_id):
        log.info("publish_followups_from_an_earlier_attempt")
        return True
    if claim.status == "failed":
        async with cleanup_step("failure notice", job_id=job_id):
            await notify_ingest_failed(
                job_uuid, task=task, reason=claim.error_message or ""
            )
        return True
    if task in _ITEMS_ONLY:
        return True
    if task not in _LABELS:
        log.warning("publish_followups_unknown_task")
        return True
    Dataset = get_processing_port().get_dataset_orm_class()
    async with db_module.async_session() as session:
        dataset = await session.scalar(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == claim.dataset_id)
        )
    if dataset is None or dataset.record is None:
        log.info("publish_followups_dataset_gone")
        return True

    label = _LABELS[task]
    title = dataset.record.title
    if label is not None:
        async with cleanup_step("publish completion notice", job_id=job_id):
            await emit_event_safe(
                event_key="ingest_complete",
                build=lambda: build_event_notification(
                    "ingest_complete",
                    subject=f"{label} ingest complete: {title}",
                    body=f"{label} dataset '{title}' has been successfully ingested.",
                    extra={"job_id": job_id, "dataset": title},
                ),
            )
    async with cleanup_step("publish catalog cache", job_id=job_id):
        await invalidate_catalog_cache()
    async with cleanup_step("publish embedding", job_id=job_id):
        await defer_embedding(dataset)
    if label is not None:
        tenant_id = current_tenant_var.get() if is_multi_tenant() else None
        async with cleanup_step("publish usage event", job_id=job_id):
            await _emit_billing_event(
                str(tenant_id) if tenant_id else None, "ingest_jobs", event_id=job_id
            )
    return True


async def notify_ingest_failed(
    job_id: uuid.UUID, *, task: str, reason: str | BaseException
) -> None:
    """Send ``ingest_failed`` for ``job_id``, with ``reason`` redacted."""
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    message = redact_failure_reason(reason)
    await emit_event_safe(
        event_key="ingest_failed",
        build=lambda: build_event_notification(
            "ingest_failed",
            subject=f"Ingest failed: {task}",
            body=f"Ingest job (task={task}) failed.",
            reason=message,
            extra={"job_id": str(job_id), "task": task},
        ),
    )


async def run_owed_publish_followups() -> int:
    """Run the follow-ups landed terminal commits still owe, a bounded batch a call; never raises.

    Takes only records that are due, the longest due first, so records that
    keep failing wait out their delay instead of crowding out fresh ones.
    Returns how many jobs this call claimed. A job whose follow-ups fail is
    logged and skipped.
    """
    import app.core.db as db_module

    log = structlog.get_logger()
    record = IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    try:
        async with db_module.async_session() as session:
            owed = (
                await session.scalars(
                    select(IngestJob.id)
                    .where(
                        IngestJob.status.in_(("complete", "failed")),
                        record.is_not(None),
                        _due_at(record) <= func.now(),
                    )
                    .order_by(_due_at(record))
                    .limit(_SWEEP_BATCH)
                )
            ).all()
    except Exception:  # broad: the follow-ups wait for the next pass
        log.warning("owed_publish_followups_unreadable", exc_info=True)
        return 0
    claimed = 0
    for job_uuid in owed:
        try:
            claimed += await run_publish_followups(job_uuid)
        except Exception:  # broad: one job's follow-ups must not stop the rest
            log.warning("publish_followups_failed", job_id=str(job_uuid), exc_info=True)
    return claimed
