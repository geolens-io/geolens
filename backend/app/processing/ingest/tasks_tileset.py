"""Procrastinate task that unpacks an uploaded 3D Tiles tileset and publishes it."""

import asyncio
import uuid
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import func
from sqlalchemy.exc import DBAPIError

from app.core.db.tenant_session import current_tenant_var, tenant_task
from app.core.failure_reason import redact_failure_reason
from app.core.geo import bbox_to_extent_wkt
from app.core.tenancy import is_multi_tenant
from app.core.tiles3d import (
    TILESET_ASSET_KEY,
    TILESET_ENTRY_POINT,
    TILESET_MEDIA_TYPE,
    UNPUBLISHED_TILESET_ATTEMPTS_FIELD,
    tileset_attempt_prefix,
)
from app.platform.dataset_origin import set_dataset_origin
from app.platform.jobs import ledger
from app.platform.jobs.heartbeat import (
    JOB_ERROR_WRITE_TIMEOUT_MS,
    claim_job_attempt_and_start_heartbeat,
    log_job_error_write_failure,
    resolve_ingest_attempt_or_skip,
    stop_ingest_job_heartbeat,
)
from app.platform.jobs.models import owned_presigned_staging_key
from app.platform.storage.reap import delete_prefix
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.metadata_quality import compute_quality_score
from app.processing.ingest.publish_followups import (
    note_publish_followups,
    run_publish_followups,
)
from app.processing.ingest.tasks_common import (
    _bind_task_log_context,
    _job_phase_session,
    _parse_temporal_fields,
    cleanup_step,
    task_app,
)
from app.processing.ingest.tasks_raster_common import (
    absorb_cancellation,
    publish_commit_landed,
    publishing_xid,
    record_unpublished_storage_keys,
)
from app.processing.ingest.tasks_staging import (
    reap_downloaded_staging_source,
    reap_presigned_staging_object,
)
from app.processing.ingest.tileset import Tileset, inspect_tileset
from app.processing.ingest.tileset_content import scan_tileset_archive
from app.processing.ingest.validation import _member_read_errors

_TASK = "ingest_tileset"


class _MemberReader:
    """One archive member as a forward-only stream.

    A damaged member reads as a refusal while a storage error passes through
    unchanged, and offering no seek keeps the S3 client from decompressing a
    member twice just to measure it.
    """

    def __init__(self, member, name: str) -> None:
        self._member = member
        self._name = name

    def read(self, size: int = -1) -> bytes:
        with _member_read_errors(self._name):
            return self._member.read(size)


async def unpack_tileset(path: str, tileset: Tileset, attempt_prefix: str) -> None:
    """Put every file of a checked archive under one attempt's prefix.

    Each key goes through the tenant-aware resolver, so a hosted worker with
    no tenant context fails before its first put.
    """
    from app.platform.storage import get_storage

    storage = get_storage()
    with zipfile.ZipFile(path) as archive:
        for info, relative in tileset.layout.files:
            key = resolve_current_storage_key(f"{attempt_prefix}{relative}")
            with _member_read_errors(relative):
                member = archive.open(info)
            with member:
                await storage.put(key, _MemberReader(member, relative))


async def create_tileset_dataset(
    session,
    *,
    dataset_id: uuid.UUID,
    tileset: Tileset,
    attempt_prefix: str,
    source_filename: str | None,
    created_by: uuid.UUID,
    user_metadata: dict,
):
    """Create the Record, the Dataset and the tileset pointer row in one transaction.

    The dataset slot and the unpacked bytes are reserved under the per-user
    lock first, as the raster tails reserve theirs. Returns (record, dataset).
    """
    from app.modules.quota.service import reserve_dataset_slot, reserve_storage_bytes
    from app.platform.extensions import get_catalog_port, get_processing_port

    port = get_processing_port()
    Record = port.get_record_orm_class()
    Dataset = port.get_dataset_orm_class()
    DatasetAsset = get_catalog_port().dataset_asset_orm_class()
    layout, facts, contents = tileset.layout, tileset.facts, tileset.contents

    await reserve_dataset_slot(session, created_by)
    await reserve_storage_bytes(session, created_by, layout.unpacked_bytes)

    record = Record(
        title=user_metadata.get("title") or source_filename or "3D Tiles tileset",
        summary=user_metadata.get("summary"),
        record_type="tiles3d_dataset",
        visibility=user_metadata.get("visibility", "private"),
        record_status=user_metadata.get("record_status", "published"),
        created_by=created_by,
        updated_by=created_by,
    )
    if facts.extent_bbox is not None:
        record.spatial_extent = func.ST_GeomFromText(
            bbox_to_extent_wkt(*facts.extent_bbox), 4326
        )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        id=dataset_id,
        record_id=record.id,
        table_name=f"tiles3d_{record.id.hex[:16]}",
        source_format="3dtiles",
        source_filename=source_filename,
        last_refreshed_at=datetime.now(timezone.utc),
        tileset_version=facts.version,
        tileset_geometric_error=facts.geometric_error,
        tileset_bounding_volume=facts.bounding_volume,
        tileset_content_types=list(contents.content_types) if contents else None,
        tileset_extensions_required=(
            list(contents.extensions_required) if contents else None
        ),
    )
    set_dataset_origin(dataset, "upload", filename=source_filename)
    session.add(dataset)
    await session.flush()
    session.add(
        DatasetAsset(
            dataset_id=dataset.id,
            key=TILESET_ASSET_KEY,
            href=f"{attempt_prefix}{TILESET_ENTRY_POINT}",
            media_type=TILESET_MEDIA_TYPE,
            size_bytes=layout.unpacked_bytes,
        )
    )
    await session.flush()
    await session.refresh(dataset, ["record"])
    return record, dataset


async def _notify(
    event_key: str,
    *,
    subject: str,
    body: str,
    extra: dict,
    exc: Exception | None = None,
) -> None:
    from app.platform.notifications.events import (
        build_event_notification,
        emit_event_safe,
    )

    await emit_event_safe(
        event_key=event_key,
        build=lambda: build_event_notification(
            event_key,
            subject=subject,
            body=body,
            reason=redact_failure_reason(exc) if exc is not None else None,
            extra={**extra, "task": _TASK},
        ),
    )


async def _record_failure(
    job_uuid: uuid.UUID, attempt_uuid: uuid.UUID, exc: Exception, *, job_id: str
) -> None:
    try:
        async with _job_phase_session(
            job_uuid,
            phase="error_write",
            attempt_id=attempt_uuid,
            lock_and_statement_timeout_ms=JOB_ERROR_WRITE_TIMEOUT_MS,
        ) as (session, _job):
            await ledger.fail(session, job_uuid, attempt_uuid, reason=exc)
            await session.commit()
    except DBAPIError as write_failure:
        # Swallowed so the caller re-raises the ingest failure, not a timeout.
        log_job_error_write_failure(write_failure, job_id=job_id, task=_TASK)


@task_app.task(
    queue="raster", retry=0, name="app.processing.ingest.tasks_tileset.ingest_tileset"
)
@tenant_task
async def ingest_tileset(
    job_id: str,
    file_path: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: check a staged tileset archive, unpack it and publish it.

    1. Claim the attempt and start the heartbeat.
    2. Check the archive again: every entry, the unpacked total, tileset.json
       and the external tilesets it names.
    3. Name the attempt's prefix on the job row, then unpack under it.
    4. In one transaction, reserve the quota and create the Record, the
       Dataset with its extent and facts, and the pointer row, and complete
       the job.

    Nothing reaches GDAL, and a refusal lands before the first put.
    """
    _bind_task_log_context(task_name=_TASK, job_id=job_id)
    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="tileset"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    original_file_path = file_path
    owned_staging_key: str | None = None
    attempt_prefix: str | None = None
    # Set by the publishing commit and nothing else: it decides whether the
    # attempt's objects are reaped, whatever happens after it.
    published = False
    final_status = "pending"
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        async with _job_phase_session(
            job_uuid, phase="phase1", attempt_id=attempt_uuid
        ) as (session, job):
            if job is None:
                return
            owned_staging_key = owned_presigned_staging_key(
                job.id, job.user_metadata, job.file_path
            )
            heartbeat_task = await claim_job_attempt_and_start_heartbeat(
                session, job_uuid, attempt_uuid, job=job, current_step="validating"
            )
            if heartbeat_task is None:
                return
            user_metadata: dict = dict(job.user_metadata or {})
            source_filename: str | None = job.source_filename

        from app.processing.ingest.service import resolve_file_path

        file_path = await resolve_file_path(file_path, job_id)
        tileset = await asyncio.to_thread(inspect_tileset, file_path)
        contents = await asyncio.to_thread(
            scan_tileset_archive, file_path, tileset.layout
        )
        tileset = replace(tileset, contents=contents)

        dataset_id = uuid.uuid4()
        attempt_prefix = tileset_attempt_prefix(dataset_id, attempt_uuid)
        if not await record_unpublished_storage_keys(
            job_uuid,
            attempt_uuid,
            keys=[attempt_prefix],
            already_published=(),
            attempt_scope=str(attempt_uuid),
            job_id=job_id,
            task=_TASK,
            field=UNPUBLISHED_TILESET_ATTEMPTS_FIELD,
        ):
            return
        await unpack_tileset(file_path, tileset, attempt_prefix)

        async with _job_phase_session(
            job_uuid,
            phase="phase2",
            attempt_id=attempt_uuid,
            require_status="running",
        ) as (session, job):
            if job is None:
                return
            job.current_step = "finalize"
            job.progress = 0.8
            record, dataset = await create_tileset_dataset(
                session,
                dataset_id=dataset_id,
                tileset=tileset,
                attempt_prefix=attempt_prefix,
                source_filename=source_filename,
                created_by=uuid.UUID(user_id),
                user_metadata=user_metadata,
            )
            parsed_start, parsed_end, temporal_errors = _parse_temporal_fields(
                temporal_start=user_metadata.get("temporal_start"),
                temporal_end=user_metadata.get("temporal_end"),
            )
            if parsed_start is not None:
                record.temporal_start = parsed_start
            if parsed_end is not None:
                record.temporal_end = parsed_end
            if temporal_errors:
                job.user_metadata = {
                    **(job.user_metadata or {}),
                    "temporal_parse_errors": temporal_errors,
                }
            dataset.quality_detail = await compute_quality_score(
                session, dataset.table_name, [], dataset
            )
            await note_publish_followups(
                session, job_uuid, attempt_uuid, _TASK, reaps_staged_upload=True
            )
            await ledger.complete(
                session,
                job_uuid,
                attempt_uuid,
                values={
                    "dataset_id": dataset.id,
                    "current_step": "complete",
                    "progress": 1.0,
                },
            )
            xid = publishing_xid(session)
            try:
                await session.commit()
            except BaseException as exc:
                # A lost acknowledgement may still have committed, so only an
                # aborted transaction lets the tileset be reaped.
                if not await publish_commit_landed(
                    job_uuid,
                    attempt_uuid,
                    xid=xid,
                    error=exc,
                    job_id=job_id,
                    task=_TASK,
                ):
                    raise
                published = True
                absorb_cancellation(exc)
                await run_publish_followups(job_uuid)
                return
            published = True
            final_status = "complete"

        await run_publish_followups(job_uuid)
    except Exception as exc:  # broad: any step may fail; the job row records it
        if published:
            # Only the best-effort follow-ups after the commit can land here.
            structlog.get_logger().warning(
                "tileset_post_publish_followup_failed",
                job_id=job_id,
                task=_TASK,
                exc_info=True,
            )
            return
        structlog.get_logger().exception(
            "Ingest task failed", job_id=job_id, task=_TASK
        )
        try:
            await _record_failure(job_uuid, attempt_uuid, exc, job_id=job_id)
        finally:
            final_status = "failed"
        await _notify(
            "ingest_failed",
            subject="3D Tiles ingest failed",
            body="3D Tiles ingest job failed.",
            extra={"job_id": job_id},
            exc=exc,
        )
        raise
    finally:
        async with cleanup_step("ingest_tileset heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("ingest_tileset unpublished attempt", job_id=job_id):
            if not published and attempt_prefix is not None:
                await delete_prefix(
                    attempt_prefix,
                    tenant_id=current_tenant_var.get() if is_multi_tenant() else None,
                )
        async with cleanup_step("ingest_tileset local file", job_id=job_id):
            # A copy downloaded from storage always goes; the staged original
            # only once the tileset is published, since a retry needs it.
            if file_path != original_file_path or (
                final_status == "complete" and Path(original_file_path).is_absolute()
            ):
                Path(file_path).unlink(missing_ok=True)
        async with cleanup_step(
            "ingest_tileset presigned staging object", job_id=job_id
        ):
            await reap_presigned_staging_object(
                job_id, owned_staging_key, final_status=final_status
            )
        async with cleanup_step("ingest_tileset downloaded source", job_id=job_id):
            await reap_downloaded_staging_source(
                job_id,
                original_file_path=original_file_path,
                final_status=final_status,
                failed_source_replayable=True,
            )
