"""Regression coverage for ingest worker attempt/lease fencing."""

import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text, update

from app.platform.jobs.heartbeat import (
    StaleIngestAttempt,
    attempt_scoped_staging_table,
    claim_ingest_job_attempt,
    renew_ingest_job_heartbeat,
    resolve_ingest_job_attempt,
    update_ingest_job_for_attempt,
)
from app.platform.jobs.models import IngestJob
from app.platform.jobs.router import fail_stale_jobs


async def test_expired_attempt_cannot_renew_or_finalize_retried_job(test_db_session):
    """Expired A, retried B, resumed A: only B may renew or finalize."""
    attempt_a = uuid.uuid4()
    job = IngestJob(
        status="running",
        attempt_id=attempt_a,
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)

    _, running_failed = await fail_stale_jobs(test_db_session)
    assert running_failed == 1
    await test_db_session.refresh(job)
    assert job.status == "failed"

    attempt_b = uuid.uuid4()
    await test_db_session.execute(
        update(IngestJob)
        .where(IngestJob.id == job.id, IngestJob.attempt_id == attempt_a)
        .values(
            status="pending",
            attempt_id=attempt_b,
            started_at=None,
            heartbeat_at=None,
            completed_at=None,
        )
    )
    await test_db_session.commit()
    assert await claim_ingest_job_attempt(test_db_session, job.id, attempt_b)
    await test_db_session.commit()

    # The resumed delivery for A cannot adopt B's token.
    assert not await renew_ingest_job_heartbeat(job.id, attempt_a)
    assert not await update_ingest_job_for_attempt(
        test_db_session,
        job.id,
        attempt_a,
        values={"status": "complete", "completed_at": datetime.now(timezone.utc)},
    )
    assert not await claim_ingest_job_attempt(test_db_session, job.id, attempt_a)
    await test_db_session.rollback()

    await test_db_session.refresh(job)
    assert job.status == "running"
    assert job.attempt_id == attempt_b

    assert await renew_ingest_job_heartbeat(job.id, attempt_b)
    assert await update_ingest_job_for_attempt(
        test_db_session,
        job.id,
        attempt_b,
        values={"status": "complete", "completed_at": datetime.now(timezone.utc)},
    )
    await test_db_session.commit()
    await test_db_session.refresh(job)
    assert job.status == "complete"


async def test_vrt_generation_heartbeat_fences_stale_recovery(test_db_session):
    """A live generation survives; only its expired generation pointer is reset."""
    from app.platform.jobs.router import sweep_stale_vrt_assets
    from app.processing.raster.models import RasterAsset, VrtGeneration
    from tests.factories import create_dataset, get_user_id

    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(test_db_session, created_by=admin_id)
    generation = VrtGeneration(
        vrt_dataset_id=dataset.id,
        status="running",
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        heartbeat_at=datetime.now(timezone.utc),
    )
    test_db_session.add(generation)
    await test_db_session.flush()
    asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri="rasters/test/source.vrt",
        status="regenerating",
        current_generation_id=generation.id,
    )
    test_db_session.add(asset)
    await test_db_session.commit()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    assert await sweep_stale_vrt_assets(test_db_session, cutoff) == (0, 0)
    await test_db_session.commit()

    generation.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await test_db_session.commit()
    assert await sweep_stale_vrt_assets(test_db_session, cutoff) == (1, 1)
    await test_db_session.commit()
    await test_db_session.refresh(generation)
    await test_db_session.refresh(asset)
    assert generation.status == "failed"
    assert asset.status == "failed"
    assert asset.current_generation_id is None


async def test_tokenless_delivery_adopts_only_pending_legacy_job(test_db_session):
    legacy_job = IngestJob(status="pending")
    test_db_session.add(legacy_job)
    await test_db_session.commit()
    await test_db_session.refresh(legacy_job)
    await test_db_session.execute(
        update(IngestJob).where(IngestJob.id == legacy_job.id).values(attempt_id=None)
    )
    await test_db_session.commit()

    adopted = await resolve_ingest_job_attempt(legacy_job.id, None)
    assert adopted is not None
    await test_db_session.refresh(legacy_job)
    assert legacy_job.attempt_id == adopted

    # A duplicate tokenless delivery cannot adopt the now-tokenized row.
    assert await resolve_ingest_job_attempt(legacy_job.id, None) is None

    new_job = IngestJob(status="pending")
    test_db_session.add(new_job)
    await test_db_session.commit()
    await test_db_session.refresh(new_job)
    assert new_job.attempt_id is not None
    assert await resolve_ingest_job_attempt(new_job.id, None) is None


async def test_attempt_owned_publish_rejects_stale_external_writer(test_db_session):
    from app.processing.ingest.tasks_vector import (
        _drop_attempt_staging_table,
        _publish_attempt_staging_table,
    )

    attempt_a = uuid.uuid4()
    attempt_b = uuid.uuid4()
    marker = uuid.uuid4().hex[:8]
    live_table = f"fence_live_{marker}"
    staging_a = attempt_scoped_staging_table(live_table, attempt_a)
    staging_b = attempt_scoped_staging_table(live_table, attempt_b)
    job = IngestJob(status="running", attempt_id=attempt_b)
    test_db_session.add(job)
    await test_db_session.flush()
    job_id = job.id
    await test_db_session.execute(text(f'CREATE TABLE data."{staging_a}" (id int)'))
    await test_db_session.execute(text(f'INSERT INTO data."{staging_a}" VALUES (1)'))
    await test_db_session.execute(text(f'CREATE TABLE data."{staging_b}" (id int)'))
    await test_db_session.execute(text(f'INSERT INTO data."{staging_b}" VALUES (2)'))
    await test_db_session.commit()

    # Retry B publishes its physical table under the current lease.
    await _publish_attempt_staging_table(
        test_db_session,
        job_id=job_id,
        attempt_id=attempt_b,
        staging_table=staging_b,
        live_table=live_table,
    )
    await test_db_session.commit()

    # Expired A resumes afterward but cannot rename over B's live table.
    with pytest.raises(StaleIngestAttempt):
        await _publish_attempt_staging_table(
            test_db_session,
            job_id=job_id,
            attempt_id=attempt_a,
            staging_table=staging_a,
            live_table=live_table,
        )
    await test_db_session.rollback()
    stale_exists = await test_db_session.scalar(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": f"data.{staging_a}"},
    )
    assert stale_exists == f"data.{staging_a}"
    published_value = await test_db_session.scalar(
        text(f'SELECT id FROM data."{live_table}"')
    )
    assert published_value == 2

    await _drop_attempt_staging_table(staging_a)
    await test_db_session.execute(text(f'DROP TABLE data."{live_table}"'))
    await test_db_session.commit()


def test_attempt_scoped_staging_tables_include_full_token():
    base = "x" * 63
    attempt_a = uuid.uuid4()
    attempt_b = uuid.uuid4()

    table_a = attempt_scoped_staging_table(base, attempt_a)
    table_b = attempt_scoped_staging_table(base, attempt_b)

    assert len(table_a) <= 63
    assert attempt_a.hex in table_a
    assert attempt_b.hex in table_b
    assert table_a != table_b


def test_worker_entrypoints_support_legacy_tokenless_deliveries():
    """Every pre-deployment tokenless delivery has a safe adoption path."""
    from app.processing.ingest.tasks_raster import ingest_raster
    from app.processing.ingest.tasks_reupload import reupload_file, reupload_service
    from app.processing.ingest.tasks_vector import ingest_file, ingest_service
    from app.processing.ingest.tasks_vrt import ingest_vrt, regenerate_vrt

    compatible_tasks = (
        ingest_file,
        ingest_service,
        ingest_raster,
        reupload_file,
        reupload_service,
        ingest_vrt,
        regenerate_vrt,
    )
    for task in compatible_tasks:
        parameter = inspect.signature(task.func).parameters["attempt_id"]
        assert parameter.default is None
