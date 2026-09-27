"""The follow-ups a job owes once its terminal commit has landed.

A first ingest owes its completion follow-ups, and a rejected replacement its
failure notice. A publish that consumed a staged upload also owes items: the
upload's archive and then its deletion. The terminal transaction records them
on the job row, so the record exists exactly when the commit does. The task
runs them after its commit, or the stale-job sweep when the task could not.
The rest runs once, at the first claim, without waiting on the items. Each
item is confirmed on its own and retried, after a doubling delay capped at a
few hours, until it is; the record goes once it is claimed and no item is left.
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

# Retry state kept in the record. An owed item has no last attempt, since
# nothing else is sure to archive or delete a published upload; the sweep
# keeps trying it at the capped delay.
_ATTEMPTS = "attempts"
_NEXT_ATTEMPT_AT = "next_attempt_at"
_RETRY_BASE = timedelta(minutes=5)
_RETRY_CAP = timedelta(hours=4)
# Set once the run-once follow-ups have run, while items are still owed.
_CLAIMED = "claimed"


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


async def _note_archive_outcome(
    job_uuid: uuid.UUID, attempt_id: str, error: str | None
) -> None:
    """Flag the job's archive as failed with ``error``, or with None as made; never raises.

    It is the flag ``_archive_original_file`` sets. A made archive clears it
    and the archive-pending mark. A failure lands only while ``attempt_id``
    owns the job and the mark is still there, since another run may have made
    the archive meanwhile. Edits the stored metadata in place, since writing
    back a copy could restore a record a concurrent claim has cleared.
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
        outcome = outcome.where(
            IngestJob.attempt_id == uuid.UUID(attempt_id),
            stored.has_key(ARCHIVE_PENDING_METADATA_KEY),
        )
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
    attempt_id: str,
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
            await _note_archive_outcome(job_uuid, attempt_id, None)
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
                job_uuid,
                attempt_id,
                "The staged upload is outside the upload staging directory.",
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
            await _note_archive_outcome(job_uuid, attempt_id, None)
            return True
        return False
    except Exception as exc:  # broad: an unreadable upload or store keeps the upload
        if await _archive_in_place(archive_key):
            await _note_archive_outcome(job_uuid, attempt_id, None)
            return True
        structlog.get_logger().warning("staged_upload_archive_failed", job_id=job_id)
        await _note_archive_outcome(job_uuid, attempt_id, str(exc))
        return False
    finally:
        if downloaded:
            Path(local).unlink(missing_ok=True)


async def _delete_staged_upload(job_uuid: uuid.UUID, file_path: str | None) -> bool:
    """Delete the staged upload ``file_path`` names, as its task's cleanup does; never raises.

    ``file_path`` is a local file when ``resolve_file_path`` would read it as
    one, and is unlinked only inside the upload staging directory. A
    ``staging/`` path is also deleted from storage. Returns False only when a
    delete it attempted failed.
    """
    from app.core.tenancy import is_multi_tenant

    if not file_path:
        return True
    job_id = str(job_uuid)
    unlinked = False
    async with cleanup_step("staged upload", job_id=job_id):
        path = Path(file_path)
        if path.exists() and (path.is_absolute() or not is_multi_tenant()):
            if _in_staging_dir(file_path):
                path.resolve().unlink(missing_ok=True)
            else:
                structlog.get_logger().warning(
                    "staged_upload_outside_staging_dir", job_id=job_id
                )
        unlinked = True
    reaped = await reap_downloaded_staging_source(
        job_id,
        original_file_path=file_path,
        final_status="complete",
        failed_source_replayable=True,
    )
    return unlinked and reaped


async def _write_record(job_uuid: uuid.UUID, attempt_id: str, metadata) -> None:
    """Write ``metadata``, built from the stored value, while the record is ``attempt_id``'s."""
    import app.core.db as db_module

    record = IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    async with db_module.async_session() as session:
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_uuid, record["attempt_id"].astext == attempt_id)
            .values(user_metadata=metadata)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def _confirm_owed_item(job_uuid: uuid.UUID, attempt_id: str, item: str) -> None:
    """Take ``item`` alone off the record ``attempt_id`` wrote; every other item stays owed."""
    path = literal([PUBLISH_FOLLOWUPS_FIELD, item], ARRAY(Text))
    await _write_record(job_uuid, attempt_id, IngestJob.user_metadata.op("#-")(path))


async def _schedule_retry(job_uuid: uuid.UUID, attempt_id: str, attempts: int) -> None:
    """Count ``attempts`` on the job's record and set when the next one is due."""
    delay = _RETRY_BASE * min(2 ** (attempts - 1), _RETRY_CAP // _RETRY_BASE)
    counted = func.jsonb_set(
        IngestJob.user_metadata,
        literal([PUBLISH_FOLLOWUPS_FIELD, _ATTEMPTS], ARRAY(Text)),
        func.to_jsonb(literal(attempts, Integer)),
    )
    scheduled = func.jsonb_set(
        counted,
        literal([PUBLISH_FOLLOWUPS_FIELD, _NEXT_ATTEMPT_AT], ARRAY(Text)),
        func.to_jsonb(func.now() + delay),
    )
    await _write_record(job_uuid, attempt_id, scheduled)


async def _settle_owed_items(
    job_uuid: uuid.UUID, row, *, local_copy: str | None = None
) -> None:
    """Run the items a published job's record owes, confirming each one that lands.

    The client's presigned key goes whatever the archive does, since the
    archive reads only ``file_path``. With a live dataset the upload's
    original is archived first, and the upload is deleted only once that
    archive is confirmed. The delete is confirmed only once nothing it should
    remove is left. An item left over is tried again after a doubling delay
    capped at ``_RETRY_CAP``, however many attempts it takes.
    """
    job_id = str(job_uuid)
    attempt_id = row.owed_attempt
    record = row.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    left = {item for item in _ITEMS if item in record}
    file_path = row.file_path
    if _ARCHIVE_KEY in left and (
        not file_path
        or row.dataset_id is None
        or await _archive_upload(
            job_uuid,
            attempt_id,
            file_path,
            row.dataset_id,
            record[_ARCHIVE_KEY],
            local_copy,
        )
    ):
        await _confirm_owed_item(job_uuid, attempt_id, _ARCHIVE_KEY)
        left.discard(_ARCHIVE_KEY)
    if _REAPS_STAGED_UPLOAD in left:
        reaped = await reap_presigned_staging_object(
            job_id,
            owned_presigned_staging_key(job_uuid, row.user_metadata, file_path),
            final_status="complete",
        )
        if _ARCHIVE_KEY not in left:
            deleted = await _delete_staged_upload(job_uuid, file_path)
            if reaped and deleted:
                await _confirm_owed_item(job_uuid, attempt_id, _REAPS_STAGED_UPLOAD)
                left.discard(_REAPS_STAGED_UPLOAD)
    if left:
        await _schedule_retry(job_uuid, attempt_id, int(record.get(_ATTEMPTS) or 0) + 1)


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
    """Run a job's owed follow-ups once its terminal commit is visible.

    A complete job's due items run first, before the claim and holding no
    lock; an item that doesn't land stays in the record for a later attempt,
    so a caller stopped short leaves it for the next one. The claim then runs
    the rest exactly once, without waiting on the items: it marks the record
    claimed while items are left, and removes it once none are. The job's
    status chooses what runs: a complete first ingest's follow-ups, or a failed
    job's ``ingest_failed`` notice. A replacement or a vector import owes
    nothing past its items. A job in neither status runs nothing, and a row
    another caller has locked nothing past the items. A record an earlier
    attempt wrote is cleared and runs nothing, and a deleted dataset skips the
    rest. Returns whether this call ran the rest.

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
    )
    async with db_module.async_session() as session:
        pending = (
            await session.execute(owed_row.where(_due_at(owed) <= func.now()))
        ).one_or_none()
    if pending is not None and _owes_items(pending):
        await _settle_owed_items(job_uuid, pending, local_copy=local_copy)

    async with db_module.async_session() as session:
        claim = (
            await session.execute(owed_row.with_for_update(skip_locked=True))
        ).one_or_none()
        if claim is None:
            return False
        first = not claim.user_metadata[PUBLISH_FOLLOWUPS_FIELD].get(_CLAIMED)
        if not _owes_items(claim):
            metadata = IngestJob.user_metadata.op("-")(
                literal(PUBLISH_FOLLOWUPS_FIELD, Text)
            )
        elif first:
            metadata = func.jsonb_set(
                IngestJob.user_metadata,
                literal([PUBLISH_FOLLOWUPS_FIELD, _CLAIMED], ARRAY(Text)),
                text("'true'::jsonb"),
            )
        else:
            return False
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_uuid)
            .values(user_metadata=metadata)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    if not first:
        return False

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
