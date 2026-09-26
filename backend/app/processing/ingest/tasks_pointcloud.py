"""Procrastinate task that checks an uploaded COPC point cloud and publishes it."""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import func
from sqlalchemy.exc import DBAPIError

from app.core.async_io import await_draining
from app.core.db.tenant_session import tenant_task
from app.core.geo import bbox_to_extent_wkt
from app.core.pointcloud import (
    POINTCLOUD_ASSET_KEY,
    POINTCLOUD_MEDIA_TYPE,
    pointcloud_attempt_key,
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
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.metadata_quality import compute_quality_score
from app.processing.ingest.pointcloud import (
    PointCloud,
    inspect_every_node,
    staged_source,
)
from app.processing.ingest.publish_followups import (
    note_publish_followups,
    notify_ingest_failed,
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

_TASK = "ingest_pointcloud"


async def store_pointcloud(file_path: str, attempt_key: str) -> None:
    """Copy a staged file to its attempt's key, within storage when it is there."""
    from app.platform.storage import get_storage

    storage = get_storage()
    target = resolve_current_storage_key(attempt_key)
    is_local, source = staged_source(file_path)
    if not is_local:
        # Cleanup deletes the key, so a cancelled copy must land before it runs.
        await await_draining(storage.copy(source, target))
        return
    # Every adapter's put already drains its thread when cancelled.
    with open(source, "rb") as data:
        await storage.put(target, data)


async def refuse_before_the_copy(user_id: uuid.UUID, cloud: PointCloud) -> None:
    """Refuse, before any copy, a publish its own transaction would refuse.

    The quota reservation that counts stays in the publish transaction; this
    check only saves copying a file that could never be published.
    """
    from app.core.db import async_session
    from app.core.geo import unknown_srid_refusal
    from app.modules.quota.service import reserve_dataset_slot, reserve_storage_bytes

    async with async_session() as session:
        await reserve_dataset_slot(session, user_id)
        await reserve_storage_bytes(session, user_id, cloud.size_bytes)
        refusal = await unknown_srid_refusal(session, cloud.srid, field="srid")
        await session.rollback()
    if refusal:
        raise ValueError(refusal)


async def create_pointcloud_dataset(
    session,
    *,
    dataset_id: uuid.UUID,
    cloud: PointCloud,
    attempt_key: str,
    source_filename: str | None,
    created_by: uuid.UUID,
    user_metadata: dict,
):
    """Create the Record, the Dataset and the point cloud pointer row in one transaction.

    The dataset slot and the file's bytes are reserved under the per-user
    lock first, as the tileset and raster tails reserve theirs. Returns
    (record, dataset).
    """
    from app.modules.quota.service import reserve_dataset_slot, reserve_storage_bytes
    from app.platform.extensions import get_catalog_port, get_processing_port

    port = get_processing_port()
    Record = port.get_record_orm_class()
    Dataset = port.get_dataset_orm_class()
    DatasetAsset = get_catalog_port().dataset_asset_orm_class()

    await reserve_dataset_slot(session, created_by)
    await reserve_storage_bytes(session, created_by, cloud.size_bytes)

    record = Record(
        title=user_metadata.get("title") or source_filename or "Point cloud",
        summary=user_metadata.get("summary"),
        record_type="pointcloud_dataset",
        visibility=user_metadata.get("visibility", "private"),
        record_status=user_metadata.get("record_status", "published"),
        created_by=created_by,
        updated_by=created_by,
        spatial_extent=func.ST_GeomFromText(
            bbox_to_extent_wkt(*cloud.extent_bbox), 4326
        ),
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        id=dataset_id,
        record_id=record.id,
        table_name=f"pointcloud_{record.id.hex[:16]}",
        source_format="copc",
        source_filename=source_filename,
        last_refreshed_at=datetime.now(timezone.utc),
        srid=cloud.srid,
        z_min=cloud.z_min,
        z_max=cloud.z_max,
        pointcloud_point_count=cloud.point_count,
        pointcloud_point_format=cloud.point_format,
        pointcloud_vertical_crs=cloud.vertical_crs,
    )
    set_dataset_origin(dataset, "upload", filename=source_filename)
    session.add(dataset)
    await session.flush()
    session.add(
        DatasetAsset(
            dataset_id=dataset.id,
            key=POINTCLOUD_ASSET_KEY,
            href=attempt_key,
            media_type=POINTCLOUD_MEDIA_TYPE,
            size_bytes=cloud.size_bytes,
        )
    )
    await session.flush()
    await session.refresh(dataset, ["record"])
    return record, dataset


async def _record_failure(
    job_uuid: uuid.UUID, attempt_uuid: uuid.UUID, exc: Exception, *, job_id: str
) -> None:
    """Fail the attempt's job, and send ``ingest_failed`` once that lands."""
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
        return
    await notify_ingest_failed(job_uuid, task=_TASK, reason=exc)


@task_app.task(
    queue="raster",
    retry=0,
    name="app.processing.ingest.tasks_pointcloud.ingest_pointcloud",
)
@tenant_task
async def ingest_pointcloud(
    job_id: str,
    file_path: str,
    user_id: str,
    attempt_id: str | None = None,
    **kwargs,
) -> None:
    """Background task: check a staged COPC file again and publish it.

    1. Claim the attempt and start the heartbeat.
    2. Check the file again, from a local copy when it sits in storage: its
       header, hierarchy and CRS, and every node's points.
    3. Name the attempt's key on the job row, then copy the file to it.
    4. In one transaction, reserve the quota and create the Record, the
       Dataset with its extent and facts, and the pointer row, and complete
       the job.

    GDAL never opens the file, and a refusal lands before the copy.
    """
    _bind_task_log_context(task_name=_TASK, job_id=job_id)
    resolved = await resolve_ingest_attempt_or_skip(
        job_id, attempt_id, task_label="pointcloud"
    )
    if resolved is None:
        return
    job_uuid, attempt_uuid = resolved
    original_file_path = file_path
    owned_staging_key: str | None = None
    attempt_key: str | None = None
    # Set by the publishing commit and nothing else: it decides whether the
    # attempt's object is reaped, whatever happens after it.
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
        cloud = await inspect_every_node(file_path)
        await refuse_before_the_copy(uuid.UUID(user_id), cloud)
        dataset_id = uuid.uuid4()
        attempt_key = pointcloud_attempt_key(dataset_id, attempt_uuid)
        if not await record_unpublished_storage_keys(
            job_uuid,
            attempt_uuid,
            keys=[attempt_key],
            already_published=(),
            attempt_scope=str(attempt_uuid),
            job_id=job_id,
            task=_TASK,
        ):
            return
        await store_pointcloud(original_file_path, attempt_key)

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
            record, dataset = await create_pointcloud_dataset(
                session,
                dataset_id=dataset_id,
                cloud=cloud,
                attempt_key=attempt_key,
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
            await note_publish_followups(session, job_uuid, attempt_uuid, _TASK)
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
                # aborted transaction lets the copy be reaped.
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
                "pointcloud_post_publish_followup_failed",
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
        raise
    finally:
        async with cleanup_step("ingest_pointcloud heartbeat", job_id=job_id):
            await stop_ingest_job_heartbeat(heartbeat_task)
        async with cleanup_step("ingest_pointcloud unpublished copy", job_id=job_id):
            if not published and attempt_key is not None:
                from app.platform.storage import get_storage

                await get_storage().delete(resolve_current_storage_key(attempt_key))
        async with cleanup_step("ingest_pointcloud local file", job_id=job_id):
            # A copy downloaded from storage always goes; the staged original
            # only once published, since a retry needs it.
            if file_path != original_file_path or (
                final_status == "complete" and Path(original_file_path).is_absolute()
            ):
                Path(file_path).unlink(missing_ok=True)
        async with cleanup_step(
            "ingest_pointcloud presigned staging object", job_id=job_id
        ):
            await reap_presigned_staging_object(
                job_id, owned_staging_key, final_status=final_status
            )
        async with cleanup_step("ingest_pointcloud downloaded source", job_id=job_id):
            await reap_downloaded_staging_source(
                job_id,
                original_file_path=original_file_path,
                final_status=final_status,
                failed_source_replayable=True,
            )
