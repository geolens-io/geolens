"""The no-swap-after-cancel guarantee (#1677), with zero CancelledError involvement.

The guarantee the issue names is NOT delivered by the Procrastinate abort
signal — that is best-effort acceleration. It is the existing job-row fence,
made load-bearing: every finalize site runs, inside ONE transaction, a fenced
job update (``require_ingest_job_update``, matching only
``status='running' AND attempt_id=<mine>``) before and after the staging
swap. A committed ``cancelled`` job row therefore makes the finalize raise
``StaleIngestAttempt`` and roll the whole transaction — swap included — back.

Because the endpoint's CAS and the worker's fenced update contend on the same
``ingest_jobs`` row lock, only two serializations exist:

1. Cancel commits first  -> the fence matches zero rows, raises, swap rolls back.
2. Finalize locked first -> the endpoint's CAS waits, hits its 2s lock_timeout,
   and reports 409 ``job_finishing`` without writing anything.

Both are pinned here, worker-side sequence driven verbatim (fenced heartbeat
-> ``_apply_reupload_swap`` -> fenced complete -> run CAS), no asyncio
cancellation anywhere. If a refactor moves the swap after the commit or drops
the fence, the first test fails.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.jobs.heartbeat import (
    StaleIngestAttempt,
    attempt_scoped_staging_table,
    require_ingest_job_update,
)
from app.platform.jobs.models import IngestJob
from app.platform.refresh.service import (
    USER_CANCELLED_ERROR_CODE,
    claim_run_for_job,
    create_pending_run,
    record_refresh_success,
)
from app.processing.ingest.tasks_common import _apply_reupload_swap
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _table_rows(session, table: str) -> list[str]:
    return list(
        (await session.execute(sa.text(f'SELECT name FROM data."{table}"'))).scalars()
    )


async def _version_count(session, dataset_id: uuid.UUID) -> int:
    return (
        await session.execute(
            sa.text(
                "SELECT count(*) FROM catalog.dataset_versions"
                " WHERE dataset_id = :dataset_id"
            ),
            {"dataset_id": dataset_id},
        )
    ).scalar_one()


async def _seed_running_reupload(session):
    """Dataset with a REAL live table + running job (attempt A) + running run
    + a REAL attempt-scoped staging table with a distinguishable row."""
    admin_id = await get_user_id(session, "admin")
    live = f"cancelfence_{uuid.uuid4().hex[:10]}"
    dataset = await create_dataset(session, created_by=admin_id, table_name=live)

    attempt_id = uuid.uuid4()
    staging = attempt_scoped_staging_table(live, attempt_id)
    for table, row in ((live, "original"), (staging, "new_data")):
        await session.execute(
            sa.text(
                f'CREATE TABLE data."{table}" '
                "(id serial PRIMARY KEY, name text, geom geometry(Point, 4326))"
            )
        )
        await session.execute(
            sa.text(f'INSERT INTO data."{table}" (name) VALUES (:row)'),
            {"row": row},
        )

    job = IngestJob(
        dataset_id=dataset.id,
        status="running",
        attempt_id=attempt_id,
        started_at=datetime.now(timezone.utc),
        heartbeat_at=datetime.now(timezone.utc),
        source_filename="parcels.gpkg",
        created_by=admin_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    run = await create_pending_run(
        session,
        dataset_id=dataset.id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=admin_id,
        ingest_job_id=job.id,
        feature_count_before=1,
    )
    await session.commit()
    assert await claim_run_for_job(session, job.id) == run.id
    await session.commit()
    return dataset, job, run, live, staging


async def _drive_finalize_verbatim(
    session,
    *,
    dataset_id: uuid.UUID,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    staging: str,
) -> None:
    """The worker's finalize sequence, exactly as tasks_reupload runs it:
    fenced heartbeat -> swap -> fenced complete -> run CAS, one transaction.

    No commit here — the caller decides, mirroring the worker where the
    commit is the last statement of the same transaction.
    """
    dataset = (
        await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    ).scalar_one()
    await require_ingest_job_update(
        session,
        job_id,
        attempt_id,
        values={"heartbeat_at": datetime.now(timezone.utc)},
    )
    version = await _apply_reupload_swap(
        session,
        dataset=dataset,
        staging_table=staging,
        metadata={
            "srid": 4326,
            "geometry_type": "Point",
            "feature_count": 1,
            "extent_wkt": None,
            "column_info": [{"name": "name", "type": "character varying"}],
        },
        sample_values={},
        user_id=str(dataset.record.created_by),
        source_filename="parcels.gpkg",
        source_format="gpkg",
        original_srid=4326,
    )
    await require_ingest_job_update(
        session,
        job_id,
        attempt_id,
        values={
            "status": "complete",
            "completed_at": datetime.now(timezone.utc),
        },
    )
    await record_refresh_success(
        session,
        ingest_job_id=job_id,
        dataset=dataset,
        dataset_version_id=version.id,
        feature_count_after=1,
        schema_diff=None,
        contacted_origin=False,
    )


async def test_committed_cancel_fences_out_the_swap(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Serialization 1: cancel commits first, the finalize raises and the
    swap rolls back — live data, versions, and both terminal rows intact."""
    dataset, job, run, live, staging = await _seed_running_reupload(test_db_session)
    # Plain-value snapshots: the doomed transaction's rollback below expires
    # every ORM instance in the session, and re-reading attributes through
    # them would lazy-load mid-assertion.
    dataset_id, job_id, run_id = dataset.id, job.id, run.id
    attempt_id = job.attempt_id
    versions_before = await _version_count(test_db_session, dataset_id)

    resp = await client.post(f"/jobs/{job_id}/cancel", headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    assert resp.json()["run_id"] == str(run_id)

    with pytest.raises(StaleIngestAttempt):
        await _drive_finalize_verbatim(
            test_db_session,
            dataset_id=dataset_id,
            job_id=job_id,
            attempt_id=attempt_id,
            staging=staging,
        )
        await test_db_session.commit()
    await test_db_session.rollback()

    # The swap never became visible: live contents, staging table, and the
    # version ledger are exactly as they were before the doomed finalize.
    assert await _table_rows(test_db_session, live) == ["original"]
    assert await _table_rows(test_db_session, staging) == ["new_data"]
    assert await _version_count(test_db_session, dataset_id) == versions_before

    job_row = (
        await test_db_session.execute(
            select(IngestJob.status).where(IngestJob.id == job_id)
        )
    ).scalar_one()
    assert job_row == "cancelled"
    run_row = (
        await test_db_session.execute(
            sa.text(
                "SELECT status, error_code FROM catalog.dataset_refresh_runs"
                " WHERE id = :run_id"
            ),
            {"run_id": run_id},
        )
    ).one()
    assert run_row.status == "cancelled"
    assert run_row.error_code == USER_CANCELLED_ERROR_CODE


async def test_cancel_blocked_by_finalize_lock_is_409_and_writes_nothing(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Serialization 2: the finalize transaction holds the job-row lock (from
    its first fenced update through commit); the endpoint's CAS hits its 2s
    lock_timeout and reports ``job_finishing`` without writing anything."""
    dataset, job, run, live, staging = await _seed_running_reupload(test_db_session)
    attempt_id = job.attempt_id

    # Take the finalize's first fenced update on this session and HOLD the
    # transaction open across the cancel request, as a mid-swap worker does.
    await require_ingest_job_update(
        test_db_session,
        job.id,
        attempt_id,
        values={"heartbeat_at": datetime.now(timezone.utc)},
    )

    resp = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "job_finishing"

    # The worker's transaction proceeds untouched and commits its finalize.
    await test_db_session.execute(
        sa.text(
            "UPDATE catalog.ingest_jobs SET status = 'complete',"
            " completed_at = now() WHERE id = :job_id"
        ),
        {"job_id": job.id},
    )
    await test_db_session.commit()

    await test_db_session.refresh(job)
    await test_db_session.refresh(run)
    assert job.status == "complete"
    # The run is still active — nothing about the cancel request landed. (The
    # real worker's own record_refresh_success would have finalized it in the
    # same transaction; here only the lock semantics are under test.)
    assert run.status == "running"

    # A retried cancel now reports the honest outcome: too late.
    retry = await client.post(f"/jobs/{job.id}/cancel", headers=admin_auth_header)
    assert retry.status_code == 409
    assert retry.json()["detail"]["code"] == "job_already_finished"
