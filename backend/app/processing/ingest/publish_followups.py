"""The follow-ups a job owes once its terminal commit has landed.

A first ingest or a VRT regeneration owes its completion follow-ups, and a
failed job its failure notice. A publish that consumed a staged upload also
owes its archive and then its deletion. A raster replacement owes deleting
the objects it superseded, apart from a COG a VRT may still read, which stays
charged to the dataset for the stale-job sweep to reclaim. A replacement owes
its cache purges, quicklook and embedding. The terminal transaction records
them on the job row, so the record exists exactly when the commit does. A
record that names no run-once item gets the ones its job's status and task
imply at its first claim, in the claim's own write. The task runs the record
after its commit, or the stale-job sweep once its lease runs out. Each item
is confirmed on its own and retried, after a doubling delay capped at a few
hours, until it is: a best-effort item for a few attempts, a storage item for
as long as it takes. The record goes once no item is left. A job that holds
an unarchived original but owes no archive, as one flagged before archives
were owed does, has its archive owed again when its row establishes it, and
is marked for review otherwise.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import (
    DateTime,
    Integer,
    Text,
    and_,
    case,
    cast,
    func,
    literal,
    not_,
    or_,
    select,
    text,
    true,
    type_coerce,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.failure_reason import redact_failure_reason
from app.platform.cache.tiles import invalidate_catalog_cache
from app.platform.jobs.models import (
    ARCHIVE_PENDING_METADATA_KEY,
    ARCHIVE_REVIEW_METADATA_KEY,
    OBLIGATIONS_HOLD_FIELD,
    PUBLISH_FOLLOWUPS_FIELD,
    PUBLISH_OBLIGATIONS_FIELD,
    QUICKLOOK_ITEM,
    SUPERSEDED_COG_ITEM,
    IngestJob,
    holds_unarchived_original,
    obligations_hold,
    owned_presigned_staging_key,
)
from app.processing.ingest.tasks_common import (
    _emit_billing_event,
    _generate_quicklook,
    cleanup_step,
    invalidate_tile_cache_for_table,
)
from app.processing.ingest.tasks_staging import (
    _archive_original_file,
    original_archive_key,
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

# The completion-notice label of each task that owes the completion follow-ups,
# or None when it sends no notice and bills nothing.
_LABELS: dict[str, str | None] = {
    "ingest_raster": "Raster",
    "ingest_tileset": "3D Tiles",
    "ingest_pointcloud": "Point cloud",
    "ingest_vrt": None,
    "regenerate_vrt": None,
}

_SWEEP_BATCH = 50

# A record of these tasks that names no run-once item owes none.
_ITEMS_ONLY = frozenset({"reupload_file", "reupload_raster", "ingest_file"})

# The items a record can owe, each a key in the record that is removed alone
# once it is confirmed. The purges run first, so no reader of a completed job
# meets the replaced data while a slow archive runs, and the notice never
# reads a cache the purge has yet to clear; the storage items come next.
_ARCHIVE_KEY = "archive_key"
_REAPS_STAGED_UPLOAD = "reaps_staged_upload"
_SUPERSEDED_KEYS = "superseded_keys"
_SUPERSEDED_COG = SUPERSEDED_COG_ITEM
_STORAGE_ITEMS = (_ARCHIVE_KEY, _REAPS_STAGED_UPLOAD, _SUPERSEDED_KEYS, _SUPERSEDED_COG)
_CATALOG_CACHE = "catalog_cache"
_TILE_CACHE = "tile_cache"
_EMBEDDING = "embedding"
_NOTICE = "notice"
# The channels a notice still owes once others delivered it; without it, the
# notice owes every channel configured when it is sent.
_NOTICE_CHANNELS = "notice_channels"
_USAGE = "usage"
_PURGES = (_CATALOG_CACHE, _TILE_CACHE)
_AFTER_STORAGE = (QUICKLOOK_ITEM, _EMBEDDING, _NOTICE, _USAGE)
_RUN_ONCE_ITEMS = _PURGES + _AFTER_STORAGE

# Retry state kept in the record. A storage item has no last attempt, since
# nothing else is sure to archive or delete a published upload; the sweep
# keeps trying it at the capped delay.
_ATTEMPTS = "attempts"
_NEXT_ATTEMPT_AT = "next_attempt_at"
_RETRY_BASE = timedelta(minutes=5)
_RETRY_CAP = timedelta(hours=4)
# A run-once item still owed after this many attempts, about nine hours, is dropped.
_GIVE_UP_ATTEMPTS = 8
# Set once the record holds every run-once item it owes.
_CLAIMED = "claimed"
# The attempt whose record a take has leased, so its writer bypasses the lease once.
_TAKEN_FOR = "taken_for"
# How long the sweep leaves a claimed record to its claimer, well past a notice's
# bounded network calls.
_CLAIM_LEASE = timedelta(minutes=10)
# A job that ended more recently may still have its own archive or cleanup in flight.
_UNOWED_ARCHIVE_MIN_AGE = timedelta(days=1)


def _hold():
    return func.jsonb_build_object(OBLIGATIONS_HOLD_FIELD, obligations_hold())


def _holding(metadata):
    """``metadata`` with the obligations hold while it holds an obligations record, and without it otherwise.

    The hold never replaces a value already in its field.
    """
    stored = type_coerce(metadata, JSONB).self_group()
    field = literal(OBLIGATIONS_HOLD_FIELD, Text)
    obligations = stored.op("->")(literal(PUBLISH_OBLIGATIONS_FIELD, Text))
    return case(
        (obligations.is_not(None), _hold().op("||")(metadata)),
        (
            stored.op("->")(field) == obligations_hold(),
            metadata.op("-")(field),
        ),
        else_=metadata,
    )


def owed_followups(
    attempt_uuid: uuid.UUID,
    task: str,
    *,
    reaps_staged_upload: bool = False,
    archive_key: str | None = None,
    superseded_keys: Sequence[str] = (),
    superseded_cog: str | None = None,
    superseded_cog_bytes: int = 0,
    sweep_waits: bool = False,
    catalog_cache: bool = False,
    tile_cache: str | None = None,
    quicklook: str | None = None,
    embedding: bool = False,
    notice: str | None = None,
    usage: str | None = None,
):
    """The job's ``user_metadata`` with this attempt's ``task`` follow-ups owed.

    The storage items go in ``PUBLISH_FOLLOWUPS_FIELD``, claimed, so a runner
    of an earlier release runs them and nothing else. With ``archive_key`` it
    also marks the upload's archive pending, which the follow-ups remove once
    that archive exists. ``sweep_waits`` holds the sweep off those items for
    one retry delay, for a task that archives the upload itself.

    The run-once items go in ``PUBLISH_OBLIGATIONS_FIELD``: the catalog cache
    purge, the tile cache purge and the quicklook of a table, the embedding, a
    notice event and a usage dimension, billed once under the job's id. A
    record naming none gets the ones its job implies at its first claim. One
    naming any is written claimed, so its claim adds none, and leased, so the
    sweep leaves it to the writer's own call until the lease runs out. The
    obligations hold goes beside it, and goes with it.
    """
    owner = ["task", task, "attempt_id", str(attempt_uuid)]
    fields = list(owner)
    run_once = {
        _CATALOG_CACHE: catalog_cache or None,
        _TILE_CACHE: tile_cache,
        QUICKLOOK_ITEM: quicklook,
        _EMBEDDING: embedding or None,
        _NOTICE: notice,
        _USAGE: usage,
    }
    for item, value in run_once.items():
        if value is not None:
            fields += [item, literal(value, JSONB)]
    if any(value is not None for value in run_once.values()):
        fields += [_CLAIMED, true(), _NEXT_ATTEMPT_AT, func.now() + _CLAIM_LEASE]
    records = [PUBLISH_OBLIGATIONS_FIELD, func.jsonb_build_object(*fields)]
    storage = []
    if reaps_staged_upload:
        storage += [_REAPS_STAGED_UPLOAD, true()]
    if archive_key is not None:
        storage += [_ARCHIVE_KEY, archive_key]
        records += [ARCHIVE_PENDING_METADATA_KEY, true()]
    if superseded_keys:
        storage += [_SUPERSEDED_KEYS, literal(list(superseded_keys), JSONB)]
    if superseded_cog is not None:
        cog = {"key": superseded_cog, "bytes": superseded_cog_bytes}
        storage += [_SUPERSEDED_COG, literal(cog, JSONB)]
    if storage:
        storage += [_CLAIMED, true()]
        if sweep_waits:
            storage += [_NEXT_ATTEMPT_AT, func.now() + _RETRY_BASE]
        records += [PUBLISH_FOLLOWUPS_FIELD, func.jsonb_build_object(*owner, *storage)]
    owed = func.jsonb_build_object(*records)
    stored = func.coalesce(IngestJob.user_metadata, text("'{}'::jsonb"))
    return _hold().op("||")(stored.op("||")(owed))


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


async def _note_archive_failure(
    job_uuid: uuid.UUID, attempt_id: str, error: str
) -> None:
    """Flag the job's archive as failed with ``error``; never raises.

    It is the flag ``_archive_original_file`` sets. It lands only while
    ``attempt_id`` owns the job and the archive-pending mark is still there,
    since another run may have made the archive meanwhile. Edits the stored
    metadata in place, since writing back a copy could restore a record a
    concurrent claim has cleared.
    """
    import app.core.db as db_module

    stored = IngestJob.user_metadata
    flag = func.jsonb_build_object(
        "archive_failed", true(), "archive_error", error[:500]
    )
    async with cleanup_step("archive outcome", job_id=str(job_uuid)):
        async with db_module.async_session() as session:
            await session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == job_uuid,
                    IngestJob.attempt_id == uuid.UUID(attempt_id),
                    stored.has_key(ARCHIVE_PENDING_METADATA_KEY),
                )
                .values(
                    user_metadata=func.coalesce(stored, text("'{}'::jsonb")).op("||")(
                        flag
                    )
                )
                .execution_options(synchronize_session=False)
            )
            await session.commit()


async def _stored_size(archive_key: str) -> int | None:
    """The size of the object under ``archive_key``, or None when there is none; raises when the store can't tell."""
    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key

    try:
        return await get_storage().size(resolve_current_storage_key(archive_key))
    except FileNotFoundError:
        return None


async def _archived_as(archive_key: str, size: int | None = None) -> bool:
    """Whether storage holds ``size`` bytes under ``archive_key``, or any object without ``size``; False when it can't tell."""
    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key

    try:
        if size is None:
            return await get_storage().exists(resolve_current_storage_key(archive_key))
        return await _stored_size(archive_key) == size
    except Exception:  # broad: an unreadable archive stays unconfirmed
        return False


async def _lock_owed_archive(
    session: AsyncSession,
    job_uuid: uuid.UUID,
    attempt_id: str,
    dataset_id: uuid.UUID,
    archive_key: str,
) -> IngestJob | None:
    """The job's row, locked, while ``attempt_id`` still owes ``archive_key`` for ``dataset_id``.

    None when another holder has the row, the dataset is gone or another run
    has confirmed the archive. A dataset delete locks its jobs' rows before it
    reaps originals/ after its commit, so a write made holding this row is
    reaped with the dataset.
    """
    record = IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    return await session.scalar(
        select(IngestJob)
        .where(
            IngestJob.id == job_uuid,
            IngestJob.dataset_id == dataset_id,
            record["attempt_id"].astext == attempt_id,
            record[_ARCHIVE_KEY].astext == archive_key,
        )
        .with_for_update(skip_locked=True)
    )


async def _archive_upload(
    job_uuid: uuid.UUID,
    attempt_id: str,
    file_path: str,
    dataset_id: uuid.UUID,
    archive_key: str,
    local_copy: str | None = None,
    *,
    failed_before: bool = False,
) -> bool:
    """Whether ``archive_key`` holds the upload's original, archiving it now if not.

    ``archive_key`` names this upload alone. While ``failed_before`` is False
    only a whole write can have put an object there, so any object is its
    archive, found without reading the upload, even one found only after a
    failure, as when another run made it meanwhile. Once an attempt has
    failed, the object may be truncated: it counts only when it holds as many
    bytes as the upload, and is written again otherwise. Reads the upload from
    ``local_copy`` when the caller holds one, and otherwise the way its task
    did, through ``resolve_file_path``, but never a local file outside the
    staging directory. Writes only through ``_lock_owed_archive``, and
    otherwise leaves the job as it is. Any other failure flags the job's
    archive as failed; the caller clears the flags when it confirms the
    archive.
    """
    import app.core.db as db_module
    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key
    from app.processing.ingest.service import resolve_file_path

    job_id = str(job_uuid)
    local: str | None = None
    downloaded = False
    size: int | None = None
    try:
        if not failed_before and await get_storage().exists(
            resolve_current_storage_key(archive_key)
        ):
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
            await _note_archive_failure(
                job_uuid,
                attempt_id,
                "The staged upload is outside the upload staging directory.",
            )
            return False
        size = Path(local).stat().st_size
        if await _stored_size(archive_key) == size:
            return True
        async with db_module.async_session() as session:
            job = await _lock_owed_archive(
                session, job_uuid, attempt_id, dataset_id, archive_key
            )
            archived = job is not None and await _archive_original_file(
                session,
                job=job,
                dataset_id=dataset_id,
                file_path=local,
                log_message="Failed to archive re-uploaded file to storage",
                archive_name=archive_key.rsplit("/", 1)[-1],
            )
        return archived or await _archived_as(archive_key, size)
    except Exception as exc:  # broad: an unreadable upload or store keeps the upload
        measured = size is not None
        if (measured or not failed_before) and await _archived_as(archive_key, size):
            return True
        structlog.get_logger().warning("staged_upload_archive_failed", job_id=job_id)
        await _note_archive_failure(job_uuid, attempt_id, str(exc))
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


async def _write_record(
    job_uuid: uuid.UUID, attempt_id: str, metadata, field: str = PUBLISH_FOLLOWUPS_FIELD
) -> None:
    """Write ``metadata``, built from the stored value, while the record in ``field`` is ``attempt_id``'s."""
    import app.core.db as db_module

    record = IngestJob.user_metadata[field]
    async with db_module.async_session() as session:
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job_uuid, record["attempt_id"].astext == attempt_id)
            .values(user_metadata=_holding(metadata))
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def _confirm_owed_item(
    job_uuid: uuid.UUID,
    attempt_id: str,
    *items: str,
    field: str = PUBLISH_FOLLOWUPS_FIELD,
) -> None:
    """Take ``items`` alone off the record in ``field`` ``attempt_id`` wrote; every other item stays owed."""
    metadata = IngestJob.user_metadata
    for item in items:
        metadata = metadata.op("#-")(literal([field, item], ARRAY(Text)))
    await _write_record(job_uuid, attempt_id, metadata, field)


async def _delete_orphaned_archive(job_uuid: uuid.UUID, archive_key: str) -> bool:
    """Delete the archive a deleted dataset left under ``archive_key``; False when the delete failed.

    A write that outlived the connection holding its job row can land after the
    dataset's prefix was reaped. A missing object counts as deleted.
    """
    from app.platform.storage.titiler_url import resolve_current_storage_key
    from app.processing.ingest.tasks_raster_common import (
        _cleanup_orphaned_storage_keys,
    )

    try:
        key = resolve_current_storage_key(archive_key)
    except ValueError:
        return True
    return not await _cleanup_orphaned_storage_keys([key], job_id=str(job_uuid))


async def _confirm_archive(job_uuid: uuid.UUID, attempt_id: str) -> bool:
    """Take the archive item and the job's archive flags off in one write.

    Returns False when the write fails, which leaves the item owed, and the
    upload with it, for a later attempt.
    """
    metadata = IngestJob.user_metadata
    for flag in ("archive_failed", "archive_error", ARCHIVE_PENDING_METADATA_KEY):
        metadata = metadata.op("-")(literal(flag, Text))
    path = literal([PUBLISH_FOLLOWUPS_FIELD, _ARCHIVE_KEY], ARRAY(Text))
    try:
        await _write_record(job_uuid, attempt_id, metadata.op("#-")(path))
    except Exception:  # broad: the archive stays owed and a later attempt confirms it
        structlog.get_logger().warning(
            "archive_not_confirmed", job_id=str(job_uuid), exc_info=True
        )
        return False
    return True


async def _reap_presigned_object(
    job_uuid: uuid.UUID, user_metadata, file_path: str | None
) -> bool:
    """Delete the job's own presigned object; returns False while it stays.

    With no ``file_path`` the object may hold the job's original alone, so it
    stays while the job's row holds an unarchived original, or can't be read.
    """
    import app.core.db as db_module

    key = owned_presigned_staging_key(job_uuid, user_metadata, file_path)
    if key and not file_path:
        try:
            async with db_module.async_session() as session:
                held = await session.scalar(
                    select(IngestJob.id).where(
                        IngestJob.id == job_uuid, holds_unarchived_original()
                    )
                )
        except Exception:  # broad: an unreadable row keeps what may be the only copy
            return False
        if held is not None:
            return False
    return await reap_presigned_staging_object(
        str(job_uuid), key, final_status="complete"
    )


async def _review_archive_of_no_upload(
    job_uuid: uuid.UUID,
    attempt_id: str,
    dataset_id: uuid.UUID,
    archive_key: str,
    *,
    failed_before: bool,
) -> bool:
    """Settle the owed archive of a job that names no upload; returns whether it is settled.

    A missing path is no proof of an archive, and no retry can make one, so
    only an archive storage holds confirms it, and only while no attempt has
    failed, since a failed write may have left it truncated. Otherwise the
    item goes and the job keeps its archive flags, and so its hold, flagged as
    failed and marked for review, which is logged once. A store that can't
    answer leaves the item owed.
    """
    import app.core.db as db_module
    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key

    try:
        in_place = await get_storage().exists(resolve_current_storage_key(archive_key))
    except Exception:  # broad: an unreadable store leaves the archive owed
        return False
    if in_place and not failed_before:
        return await _confirm_archive(job_uuid, attempt_id)
    reason = "archive_unverified" if in_place else "original_missing"
    record = IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    path = literal([PUBLISH_FOLLOWUPS_FIELD, _ARCHIVE_KEY], ARRAY(Text))
    review = func.jsonb_build_object(
        "archive_failed",
        true(),
        "archive_error",
        "The job names no staged upload.",
        ARCHIVE_REVIEW_METADATA_KEY,
        reason,
    )
    async with db_module.async_session() as session:
        written = await session.execute(
            update(IngestJob)
            .where(
                IngestJob.id == job_uuid,
                record["attempt_id"].astext == attempt_id,
                record.has_key(_ARCHIVE_KEY),
            )
            .values(
                user_metadata=IngestJob.user_metadata.op("#-")(path).op("||")(review)
            )
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    if written.rowcount:
        structlog.get_logger().warning(
            "archive_needs_review",
            job_id=str(job_uuid),
            dataset_id=str(dataset_id),
            reason=reason,
        )
    return True


async def _reap_superseded(
    job_uuid: uuid.UUID, dataset_id: uuid.UUID | None, keys: list[str]
) -> list[str]:
    """Delete what a landed raster replacement superseded; returns the keys still owed.

    Keeps any key a live catalog row names now. A key whose delete fails stays
    owed, and so does every key when anything else fails. A key already gone
    counts as deleted.
    """
    from app.platform.jobs.sweep import _live_referenced_storage_keys
    from app.platform.storage.titiler_url import resolve_current_storage_key
    from app.processing.ingest.tasks_raster_common import (
        _cleanup_orphaned_storage_keys,
    )

    job_id = str(job_uuid)
    try:
        live_keys = await _live_referenced_storage_keys(tuple(keys))
        doomed = {
            resolve_current_storage_key(key): key
            for key in keys
            if key not in live_keys
        }
        failed = await _cleanup_orphaned_storage_keys(list(doomed), job_id=job_id)
    except Exception:  # broad: an undecided key stays owed for the next attempt
        structlog.get_logger().warning(
            "superseded_objects_undecided",
            job_id=job_id,
            dataset_id=str(dataset_id),
            exc_info=True,
        )
        return list(keys)
    return [doomed[key] for key in failed]


async def _reap_superseded_cog(
    job_uuid: uuid.UUID,
    dataset_id: uuid.UUID | None,
    attempt_id: str,
    cog: str,
    cog_bytes: int,
) -> bool:
    """Delete a superseded COG unless it must stay; returns whether it is settled.

    A COG a VRT may still read stays, charged ``cog_bytes`` to the dataset,
    which the publish already did unless a VRT creation noted the dataset only
    after the publish looked. So does one a live catalog row names, such as its
    charge, which the stale-job sweep reclaims object first. When anything
    fails the COG stays owed.
    """
    import app.core.db as db_module
    from app.platform.jobs.sweep import _live_referenced_storage_keys
    from app.platform.storage.titiler_url import resolve_current_storage_key
    from app.processing.ingest.tasks_raster_common import (
        _cleanup_orphaned_storage_keys,
    )
    from app.processing.raster.vrt_members import cog_readers, retain_cog

    if dataset_id is None:
        return True
    job_id = str(job_uuid)
    log = structlog.get_logger()
    try:
        async with db_module.async_session() as session:
            vrt_ids, job_ids = await cog_readers(session, dataset_id, cog)
            if vrt_ids or job_ids:
                await retain_cog(
                    session,
                    dataset_id=dataset_id,
                    attempt_id=attempt_id,
                    asset_uri=cog,
                    size_bytes=cog_bytes,
                )
                await session.commit()
        if vrt_ids or job_ids:
            log.info(
                "superseded_cog_kept_for_vrt",
                job_id=job_id,
                dataset_id=str(dataset_id),
                storage_key=resolve_current_storage_key(cog),
                vrt_dataset_ids=vrt_ids,
                vrt_job_ids=job_ids,
            )
            return True
        if await _live_referenced_storage_keys((cog,)):
            return True
        key = resolve_current_storage_key(cog)
        return not await _cleanup_orphaned_storage_keys([key], job_id=job_id)
    except Exception:  # broad: an undecided COG stays owed for the next attempt
        log.warning("superseded_cog_undecided", job_id=job_id, exc_info=True)
        return False


async def _owe_superseded_keys(
    job_uuid: uuid.UUID, attempt_id: str, keys: list[str]
) -> None:
    """Leave the superseded-keys item of the record ``attempt_id`` wrote owing only ``keys``."""
    path = literal([PUBLISH_FOLLOWUPS_FIELD, _SUPERSEDED_KEYS], ARRAY(Text))
    # Without create_missing, an item already confirmed stays confirmed.
    owed = func.jsonb_set(IngestJob.user_metadata, path, literal(keys, JSONB), False)
    await _write_record(job_uuid, attempt_id, owed)


async def _schedule_retry(
    job_uuid: uuid.UUID,
    attempt_id: str,
    attempts: int,
    field: str = PUBLISH_FOLLOWUPS_FIELD,
) -> None:
    """Count ``attempts`` on the job's record in ``field`` and set when the next one is due."""
    delay = _RETRY_BASE * min(2 ** (attempts - 1), _RETRY_CAP // _RETRY_BASE)
    counted = func.jsonb_set(
        IngestJob.user_metadata,
        literal([field, _ATTEMPTS], ARRAY(Text)),
        func.to_jsonb(literal(attempts, Integer)),
    )
    scheduled = func.jsonb_set(
        counted,
        literal([field, _NEXT_ATTEMPT_AT], ARRAY(Text)),
        func.to_jsonb(func.now() + delay),
    )
    await _write_record(job_uuid, attempt_id, scheduled, field)


async def _settle_storage_items(
    job_uuid: uuid.UUID, row, record, *, local_copy: str | None = None
) -> set[str]:
    """Run the storage items a published job's ``record`` owes; returns those still owed.

    The client's presigned key goes whatever the archive does, since the
    archive reads only ``file_path``. A job naming no ``file_path`` may hold
    its original only under that key, so the key stays, and its delete owed,
    until the job holds no unarchived original. With a live dataset the
    upload's original is archived first, and the upload is deleted only once
    that archive is confirmed. A deleted dataset owes no archive: one left under
    its key is deleted, then the item and the job's archive flags go together.
    A job naming no upload keeps its flags and is marked for review, unless
    storage already holds its archive.
    The delete is confirmed only once nothing it should remove is left. What a
    raster replacement superseded is deleted unless a live catalog row names
    it, or, for its COG, a VRT may read it.
    """
    attempt_id = row.owed_attempt
    left = {item for item in _STORAGE_ITEMS if item in record}
    file_path = row.file_path
    failed_before = row.user_metadata.get("archive_failed") is not None
    if _ARCHIVE_KEY in left and row.dataset_id is None:
        if await _delete_orphaned_archive(
            job_uuid, record[_ARCHIVE_KEY]
        ) and await _confirm_archive(job_uuid, attempt_id):
            left.discard(_ARCHIVE_KEY)
    elif _ARCHIVE_KEY in left and not file_path:
        if await _review_archive_of_no_upload(
            job_uuid,
            attempt_id,
            row.dataset_id,
            record[_ARCHIVE_KEY],
            failed_before=failed_before,
        ):
            left.discard(_ARCHIVE_KEY)
    elif _ARCHIVE_KEY in left and (
        await _archive_upload(
            job_uuid,
            attempt_id,
            file_path,
            row.dataset_id,
            record[_ARCHIVE_KEY],
            local_copy,
            failed_before=failed_before,
        )
        and await _confirm_archive(job_uuid, attempt_id)
    ):
        left.discard(_ARCHIVE_KEY)
    if _REAPS_STAGED_UPLOAD in left:
        reaped = await _reap_presigned_object(job_uuid, row.user_metadata, file_path)
        if _ARCHIVE_KEY not in left:
            deleted = await _delete_staged_upload(job_uuid, file_path)
            if reaped and deleted:
                await _confirm_owed_item(job_uuid, attempt_id, _REAPS_STAGED_UPLOAD)
                left.discard(_REAPS_STAGED_UPLOAD)
    if _SUPERSEDED_KEYS in left:
        keys = record[_SUPERSEDED_KEYS]
        still_owed = await _reap_superseded(job_uuid, row.dataset_id, keys)
        if not still_owed:
            await _confirm_owed_item(job_uuid, attempt_id, _SUPERSEDED_KEYS)
            left.discard(_SUPERSEDED_KEYS)
        elif still_owed != keys:
            await _owe_superseded_keys(job_uuid, attempt_id, still_owed)
    if _SUPERSEDED_COG in left:
        cog = record[_SUPERSEDED_COG]
        if await _reap_superseded_cog(
            job_uuid, row.dataset_id, attempt_id, cog["key"], cog["bytes"]
        ):
            await _confirm_owed_item(job_uuid, attempt_id, _SUPERSEDED_COG)
            left.discard(_SUPERSEDED_COG)
    return left


def _next_attempt_at(record):
    """The record's next attempt, or NULL when it names none or one not shaped like a time.

    Only ``_schedule_retry`` writes it, so its ISO shape is enough to make the
    cast safe.
    """
    value = record[_NEXT_ATTEMPT_AT].astext
    return case(
        (
            value.regexp_match("^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}"),
            cast(value, DateTime(timezone=True)),
        )
    )


def _is_due(record):
    """Whether a record's items may run: it has no retry time, or that time has come.

    The job's end time comes from the worker's clock, so only a retry time the
    database set holds a record back.
    """
    return or_(
        _next_attempt_at(record).is_(None), _next_attempt_at(record) <= func.now()
    )


def _due_at(*records):
    """When a job's records fell due, for ordering: their earliest next attempt, or else when the job ended."""
    return func.coalesce(
        func.least(*(_next_attempt_at(record) for record in records)),
        IngestJob.completed_at,
        IngestJob.created_at,
    )


def _run_once_items(status: str, task: str) -> dict[str, object]:
    """The run-once items a record naming none owes, for its job's ``status`` and ``task``."""
    if status == "failed":
        return {_NOTICE: "ingest_failed"}
    if task not in _LABELS:
        return {}
    items: dict[str, object] = {_CATALOG_CACHE: True, _EMBEDDING: True}
    if _LABELS[task] is not None:
        items |= {_NOTICE: "ingest_complete", _USAGE: "ingest_jobs"}
    return items


def _taken(stored: dict, row, *, leases: bool):
    """The take's write to the job's ``user_metadata``, and whether it claimed a record first.

    A record of an earlier attempt goes. A storage record not yet claimed,
    which an earlier release wrote, is claimed: the run-once items its task
    implies move to the obligations record, and it goes when it owes no
    storage item or its job did not complete. An obligations record naming no
    item gets the ones its task implies. When ``leases``, the obligations
    record is claimed and leased, and marked with the attempt it was leased
    for.
    """
    attempt = str(row.attempt_id)
    obligations = stored.get(PUBLISH_OBLIGATIONS_FIELD)
    storage = stored.get(PUBLISH_FOLLOWUPS_FIELD)
    metadata = IngestJob.user_metadata
    first = False
    for field, record in (
        (PUBLISH_OBLIGATIONS_FIELD, obligations),
        (PUBLISH_FOLLOWUPS_FIELD, storage),
    ):
        if record is not None and record.get("attempt_id") != attempt:
            metadata = metadata.op("-")(literal(field, Text))
            first = True
    if obligations is not None and obligations.get("attempt_id") != attempt:
        obligations = None
    if storage is not None and storage.get("attempt_id") != attempt:
        storage = None
    items: dict[str, object] = {}
    if storage is not None and not storage.get(_CLAIMED):
        items |= _run_once_items(row.status, storage["task"])
        if obligations is None:
            obligations = {"task": storage["task"], "attempt_id": attempt}
            leases = True
        first = True
        if row.status != "complete" or not any(i in storage for i in _STORAGE_ITEMS):
            metadata = metadata.op("-")(literal(PUBLISH_FOLLOWUPS_FIELD, Text))
        else:
            metadata = func.jsonb_set(
                metadata,
                literal([PUBLISH_FOLLOWUPS_FIELD, _CLAIMED], ARRAY(Text)),
                text("'true'::jsonb"),
            )
    if obligations is not None and leases and not obligations.get(_CLAIMED):
        items |= _run_once_items(row.status, obligations["task"])
        first = True
    if obligations is not None and (items or leases):
        fields: list = []
        for item, value in items.items():
            fields += [item, literal(value, JSONB)]
        if leases:
            fields += [_CLAIMED, true(), _NEXT_ATTEMPT_AT, func.now() + _CLAIM_LEASE]
            fields += [_TAKEN_FOR, attempt]
        record = literal(obligations, JSONB).op("||")(func.jsonb_build_object(*fields))
        path = literal([PUBLISH_OBLIGATIONS_FIELD], ARRAY(Text))
        metadata = func.jsonb_set(metadata, path, record)
    return metadata, first, leases and obligations is not None


async def _published_dataset(dataset_id: uuid.UUID | None):
    """The job's dataset with its record loaded, or None once either is gone."""
    import app.core.db as db_module
    from app.platform.extensions import get_processing_port

    if dataset_id is None:
        return None
    Dataset = get_processing_port().get_dataset_orm_class()
    async with db_module.async_session() as session:
        dataset = await session.scalar(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    return None if dataset is None or dataset.record is None else dataset


async def _redraw_quicklook(dataset_id: uuid.UUID, table_name: str) -> bool:
    """Draw the published table's quicklook again, on a session of its own; returns whether it landed."""
    import app.core.db as db_module

    async with db_module.async_session() as session:
        return await _generate_quicklook(session, dataset_id, table_name)


def _completion_text(task: str, dataset) -> tuple[str, str, str]:
    """The completion notice's (subject, body, title); a vector import keeps its own wording."""
    label = _LABELS.get(task)
    if label:
        title = dataset.record.title
        return (
            f"{label} ingest complete: {title}",
            f"{label} dataset '{title}' has been successfully ingested.",
            title,
        )
    title = getattr(dataset, "title", None) or dataset.table_name
    return (
        f"Ingest complete: {title}",
        f"Vector dataset '{title}' has been successfully ingested.",
        title,
    )


async def _send_notice(
    event: str,
    job_uuid: uuid.UUID,
    row,
    dataset,
    channels: frozenset[str] | None = None,
):
    """Send the job's ``event`` notice to ``channels``, or every channel, identified so a receiver can drop a repeat.

    Returns what ``emit_event_safe`` does: which channels failed.
    """
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    notification_id = f"{job_uuid}:{row.owed_attempt}:{event}"
    restrict = {} if channels is None else {"channels": channels}
    if event == "ingest_failed":
        return await notify_ingest_failed(
            job_uuid,
            task=row.task,
            reason=row.error_message or "",
            notification_id=notification_id,
            **restrict,
        )
    subject, body, title = _completion_text(row.task, dataset)
    extra = {"job_id": str(job_uuid), "dataset": title}
    return await emit_event_safe(
        event_key=event,
        build=lambda: build_event_notification(
            event,
            subject=subject,
            body=body,
            extra={**extra, "notification_id": notification_id},
        ),
        **restrict,
    )


async def _settle_notice(job_uuid: uuid.UUID, row, record, dataset) -> bool:
    """Send ``record``'s notice to the channels it still owes; returns whether none is left.

    The channels that failed stay owed alone, so a retry never sends the
    notice again to a channel that delivered it. A channel no longer
    configured owes nothing, and one configured since was never owed.
    """
    from app.platform.notifications.events import EventDelivery

    owed = record.get(_NOTICE_CHANNELS)
    channels = None if owed is None else frozenset(owed)
    sent = await _send_notice(record[_NOTICE], job_uuid, row, dataset, channels)
    if isinstance(sent, EventDelivery):
        left = sent.owed
    else:
        left = frozenset() if sent is not False else None
    if left == frozenset():
        return True
    if left is not None and left != channels:
        path = literal([PUBLISH_OBLIGATIONS_FIELD, _NOTICE_CHANNELS], ARRAY(Text))
        narrowed = func.jsonb_set(
            IngestJob.user_metadata, path, literal(sorted(left), JSONB)
        )
        await _write_record(
            job_uuid, row.owed_attempt, narrowed, PUBLISH_OBLIGATIONS_FIELD
        )
        record[_NOTICE_CHANNELS] = sorted(left)
    return False


async def _run_item(item: str, value, job_uuid: uuid.UUID, row, dataset) -> bool:
    """Run one run-once item; returns False when it did not land.

    Each runner reports its own transient failure, which it also logs, and
    counts a deliberate no-op, such as a disabled event, as landed.
    """
    from app.processing.embeddings.helpers import defer_embedding

    if item == _CATALOG_CACHE:
        settled = await invalidate_catalog_cache()
    elif item == _TILE_CACHE:
        settled = await invalidate_tile_cache_for_table(value)
    elif item == QUICKLOOK_ITEM:
        settled = await _redraw_quicklook(dataset.id, value)
    elif item == _EMBEDDING:
        settled = await defer_embedding(dataset)
    else:
        settled = await _emit_billing_event(
            _usage_tenant(), value, event_id=str(job_uuid)
        )
    return settled is not False


def _usage_tenant() -> str | None:
    """The tenant a usage event is billed to, or None outside a hosted install."""
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    tenant_id = current_tenant_var.get() if is_multi_tenant() else None
    return str(tenant_id) if tenant_id else None


async def _settle_run_once_items(
    job_uuid: uuid.UUID, row, record, items: tuple[str, ...]
) -> set[str]:
    """Run those of ``items`` that ``record`` owes, in order; returns those still owed.

    With the dataset gone, its dataset-bound items settle as no-ops. A failure
    notice and the usage event need only the job, so they still run.
    """
    owed = [item for item in items if item in record]
    bound = [
        item
        for item in owed
        if item != _USAGE and not (item == _NOTICE and record[item] == "ingest_failed")
    ]
    # A notice's owed channels go with it.
    extra = {_NOTICE: (_NOTICE_CHANNELS,)}
    dataset = await _published_dataset(row.dataset_id) if bound else None
    if bound and dataset is None:
        structlog.get_logger().info(
            "publish_followups_dataset_gone", job_id=str(job_uuid), task=row.task
        )
    left: set[str] = set()
    for item in owed:
        if dataset is not None or item not in bound:
            try:
                if item == _NOTICE:
                    settled = await _settle_notice(job_uuid, row, record, dataset)
                else:
                    settled = await _run_item(
                        item, record[item], job_uuid, row, dataset
                    )
            except Exception:  # broad: a run-once item that raised stays owed
                structlog.get_logger().warning(
                    "publish_followup_failed",
                    job_id=str(job_uuid),
                    item=item,
                    exc_info=True,
                )
                settled = False
            if not settled:
                left.add(item)
                continue
        await _confirm_owed_item(
            job_uuid,
            row.owed_attempt,
            item,
            *extra.get(item, ()),
            field=PUBLISH_OBLIGATIONS_FIELD,
        )
    return left


async def _settle_record(
    job_uuid: uuid.UUID, attempt_id: str, record, left: set[str], field: str
) -> None:
    """Retry what the record in ``field`` still owes, ``left``, later, or remove it when nothing is.

    A run-once item still owed once the record's attempts reach
    ``_GIVE_UP_ATTEMPTS`` is dropped and logged, a notice with the channels
    it still owed; a storage item never is.
    """
    attempts = int(record.get(_ATTEMPTS) or 0) + 1
    abandoned = sorted(left.intersection(_RUN_ONCE_ITEMS))
    if abandoned and attempts >= _GIVE_UP_ATTEMPTS:
        channels = record.get(_NOTICE_CHANNELS, "all") if _NOTICE in left else None
        structlog.get_logger().warning(
            "publish_followup_abandoned",
            job_id=str(job_uuid),
            items=abandoned,
            channels=channels,
            attempts=attempts,
        )
        dropped = [*abandoned, _NOTICE_CHANNELS] if _NOTICE in left else abandoned
        await _confirm_owed_item(job_uuid, attempt_id, *dropped, field=field)
        left = left.difference(abandoned)
    if left:
        await _schedule_retry(job_uuid, attempt_id, attempts, field)
        return
    cleared = IngestJob.user_metadata.op("-")(literal(field, Text))
    await _write_record(job_uuid, attempt_id, cleared, field)


async def run_publish_followups(
    job_uuid: uuid.UUID,
    *,
    attempt_id: uuid.UUID | str | None = None,
    local_copy: str | None = None,
) -> bool:
    """Run a job's owed follow-ups once its terminal commit is visible.

    The obligations record, holding the run-once items, is taken only when
    it is due, unless ``attempt_id`` is the attempt that wrote it and no take
    has leased it yet, so the writer runs it at once while the sweep, and a
    repeat call from the writer, wait out the lease. The take leases it in one
    write that, at its first claim, adds the run-once items its job implies.
    The storage record runs whenever it is due, as an earlier release runs it,
    since its items are safe to repeat. The purges run first, then the
    storage items, then the rest of the run-once items, each removed once it
    lands, and each record once it owes nothing; an item that does not land is
    retried later. A row another caller has locked, or a job neither complete
    nor failed, runs nothing. Only a complete job runs its storage items. A
    record an earlier attempt wrote is cleared and runs nothing. Returns
    whether this call claimed a record.

    ``local_copy`` is a copy of the upload the caller holds and keeps; the
    archive reads it instead of downloading the upload again.
    """
    import app.core.db as db_module

    obligations = IngestJob.user_metadata[PUBLISH_OBLIGATIONS_FIELD]
    storage = IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD]
    leases = _is_due(obligations)
    if attempt_id is not None:
        writes = obligations["attempt_id"].astext == str(attempt_id)
        taken = obligations[_TAKEN_FOR].astext == str(attempt_id)
        leases = or_(leases, and_(writes, not_(func.coalesce(taken, False))))
    leases = and_(obligations.is_not(None), leases)
    stores = and_(storage.is_not(None), _is_due(storage))
    async with db_module.async_session() as session:
        row = (
            await session.execute(
                select(
                    IngestJob.status,
                    IngestJob.dataset_id,
                    IngestJob.error_message,
                    IngestJob.attempt_id,
                    IngestJob.file_path,
                    IngestJob.user_metadata,
                    leases.label("leases"),
                    stores.label("stores"),
                )
                .where(
                    IngestJob.id == job_uuid,
                    IngestJob.status.in_(("complete", "failed")),
                    or_(leases, stores),
                )
                .with_for_update(skip_locked=True)
            )
        ).one_or_none()
        if row is None:
            return False
        metadata, first, leased = _taken(row.user_metadata, row, leases=row.leases)
        stored = (
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id == job_uuid)
                .values(user_metadata=_holding(metadata))
                .returning(IngestJob.user_metadata)
                .execution_options(synchronize_session=False)
            )
        ).scalar_one()
        await session.commit()

    attempt = str(row.attempt_id)
    held = stored.get(PUBLISH_OBLIGATIONS_FIELD) if leased else None
    storage_record = stored.get(PUBLISH_FOLLOWUPS_FIELD)
    if not (row.stores and row.status == "complete"):
        storage_record = None
    owed = held or storage_record
    if owed is None:
        return first
    context = SimpleNamespace(**row._mapping, owed_attempt=attempt, task=owed["task"])
    log = structlog.get_logger().bind(job_id=str(job_uuid), task=context.task)
    known = context.task in _LABELS or context.task in _ITEMS_ONLY
    if first and held is not None and row.status == "complete" and not known:
        log.warning("publish_followups_unknown_task")
    left: set[str] = set()
    if held is not None:
        left = await _settle_run_once_items(job_uuid, context, held, _PURGES)
    if storage_record is not None:
        stays = await _settle_storage_items(
            job_uuid, context, storage_record, local_copy=local_copy
        )
        await _settle_record(
            job_uuid, attempt, storage_record, stays, PUBLISH_FOLLOWUPS_FIELD
        )
    if held is not None:
        left |= await _settle_run_once_items(job_uuid, context, held, _AFTER_STORAGE)
        await _settle_record(job_uuid, attempt, held, left, PUBLISH_OBLIGATIONS_FIELD)
    return first


async def notify_ingest_failed(
    job_id: uuid.UUID,
    *,
    task: str,
    reason: str | BaseException,
    notification_id: str | None = None,
    channels: frozenset[str] | None = None,
):
    """Send ``ingest_failed`` for ``job_id``, with ``reason`` redacted, to ``channels`` or every channel.

    Returns what ``emit_event_safe`` does: which channels failed.
    """
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    message = redact_failure_reason(reason)
    extra = {"job_id": str(job_id), "task": task}
    if notification_id is not None:
        extra["notification_id"] = notification_id
    restrict = {} if channels is None else {"channels": channels}
    return await emit_event_safe(
        event_key="ingest_failed",
        build=lambda: build_event_notification(
            "ingest_failed",
            subject=f"Ingest failed: {task}",
            body=f"Ingest job (task={task}) failed.",
            reason=message,
            extra=extra,
        ),
        **restrict,
    )


def _unowed_archive():
    """Predicate: a job that ended a day ago or more holds an unarchived original, owing no archive and with no review."""
    metadata = IngestJob.user_metadata
    ended = func.coalesce(IngestJob.completed_at, IngestJob.created_at)
    return and_(
        holds_unarchived_original(),
        metadata[PUBLISH_FOLLOWUPS_FIELD].is_(None),
        not_(metadata.has_key(ARCHIVE_REVIEW_METADATA_KEY)),
        ended < func.now() - _UNOWED_ARCHIVE_MIN_AGE,
    )


def _established_archive_key(row) -> str | None:
    """The archive key a job's row establishes for its upload, or None.

    Its task archived a local upload under the upload's name, which begins
    with the id of the job that wrote it or, for a fan-out layer, its
    parent's, so no other upload to the dataset is archived under it. A
    ``staging/`` upload's archive was mostly named after a temporary download,
    which no row records. A key storage would refuse establishes nothing.
    """
    from app.platform.storage.titiler_url import resolve_current_storage_key

    path = row.file_path
    if not path or not Path(path).is_absolute() or not _in_staging_dir(path):
        return None
    owners = (str(row.id), (row.user_metadata or {}).get("fan_out_parent_id"))
    if not any(owner and Path(path).name.startswith(f"{owner}_") for owner in owners):
        return None
    key = original_archive_key(row.dataset_id, path)
    try:
        resolve_current_storage_key(key)
    except ValueError:
        return None
    return key


async def _review_reason(row, key: str | None) -> str | None:
    """Why the job's archive can't be owed again, or None when it can; raises when the store can't tell.

    It can when ``key`` is established and the upload is still there to
    archive, or the archive already is, which the follow-ups then confirm.
    With the upload gone, an object there doesn't vouch for an archive that
    failed, since the failed write may have left it truncated.
    """
    from app.platform.storage import get_storage
    from app.platform.storage.titiler_url import resolve_current_storage_key

    if key is None:
        return "archive_unknown"
    if Path(row.file_path).is_file():
        return None
    if not await get_storage().exists(resolve_current_storage_key(key)):
        return "original_missing"
    if (row.user_metadata or {}).get("archive_failed") is not None:
        return "archive_unverified"
    return None


async def _owe_unowed_archives(limit: int) -> None:
    """Owe the archive again for up to ``limit`` jobs holding an original that nothing will archive.

    A job flagged before archives were owed has no record, so no retry ever
    confirms its archive and retention keeps its upload for good. When its row
    establishes the archive, the archive is owed again in the job's attempt,
    as its task would have owed it. Otherwise the job keeps its flags, and so
    its upload, and gets a review reason, logged once. A job with no attempt
    id can't be owed an item. A job that can't be decided now, as when its
    store can't answer, is left for a later pass.
    """
    import app.core.db as db_module

    log = structlog.get_logger()
    async with db_module.async_session() as session:
        rows = (
            await session.execute(
                select(
                    IngestJob.id,
                    IngestJob.attempt_id,
                    IngestJob.dataset_id,
                    IngestJob.file_path,
                    IngestJob.user_metadata,
                )
                .where(_unowed_archive())
                # Jobs a store can't decide stay eligible and must not fill every batch.
                .order_by(func.random())
                .limit(limit)
            )
        ).all()
    for row in rows:
        try:
            key = _established_archive_key(row) if row.attempt_id else None
            reason = await _review_reason(row, key)
        except Exception:  # broad: an undecided job waits for a later pass
            log.warning("unowed_archive_undecided", job_id=str(row.id), exc_info=True)
            continue
        if reason is None:
            reupload = (row.user_metadata or {}).get("reupload") is True
            task = "reupload_file" if reupload else "ingest_file"
            metadata = owed_followups(row.attempt_id, task, archive_key=key)
        else:
            review = func.jsonb_build_object(ARCHIVE_REVIEW_METADATA_KEY, reason)
            metadata = IngestJob.user_metadata.op("||")(review)
        async with db_module.async_session() as session:
            written = await session.execute(
                update(IngestJob)
                .where(
                    IngestJob.id == row.id,
                    IngestJob.attempt_id == row.attempt_id,
                    _unowed_archive(),
                )
                .values(user_metadata=metadata)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
        if reason is not None and written.rowcount:
            log.warning(
                "archive_needs_review",
                job_id=str(row.id),
                dataset_id=str(row.dataset_id),
                reason=reason,
            )


async def run_owed_publish_followups() -> int:
    """Run the follow-ups landed terminal commits still owe, a bounded batch a call; never raises.

    Takes only records that are due: those never attempted first, then the
    longest due, so records that keep failing wait out their delay and can't
    hold up fresh ones such as failure notices. Only the room the batch left
    then goes to owing the archive again for jobs holding an original that
    nothing will archive, which the next call runs, so a backlog of those
    never crowds out the follow-ups already owed. Returns how many jobs this
    call claimed. A job whose follow-ups fail is logged and skipped.
    """
    import app.core.db as db_module

    log = structlog.get_logger()
    records = (
        IngestJob.user_metadata[PUBLISH_OBLIGATIONS_FIELD],
        IngestJob.user_metadata[PUBLISH_FOLLOWUPS_FIELD],
    )
    due = or_(*(and_(record.is_not(None), _is_due(record)) for record in records))
    retried = or_(*(record[_ATTEMPTS].is_not(None) for record in records))
    # A record written before holds were, and not yet due, gets its hold now.
    unheld = (
        select(IngestJob.id)
        .where(
            records[0].is_not(None),
            IngestJob.user_metadata[OBLIGATIONS_HOLD_FIELD].is_(None),
        )
        .with_for_update(skip_locked=True)
    )
    try:
        async with db_module.async_session() as session:
            await session.execute(
                update(IngestJob)
                .where(IngestJob.id.in_(unheld))
                .values(user_metadata=_hold().op("||")(IngestJob.user_metadata))
                .execution_options(synchronize_session=False)
            )
            await session.commit()
    except Exception:  # broad: the holds are set on the next pass
        log.warning("publish_obligation_holds_not_set", exc_info=True)
    try:
        async with db_module.async_session() as session:
            owed = (
                await session.scalars(
                    select(IngestJob.id)
                    .where(IngestJob.status.in_(("complete", "failed")), due)
                    .order_by(retried, _due_at(*records))
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
    if len(owed) < _SWEEP_BATCH:
        try:
            await _owe_unowed_archives(_SWEEP_BATCH - len(owed))
        except Exception:  # broad: those archives wait for the next pass
            log.warning("unowed_archives_not_settled", exc_info=True)
    return claimed
