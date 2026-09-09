"""Operator-facing embedding-backfill progress, history and estimate (#2025).

A backfill has had a durable run row since #1542, but nothing read it back: an
operator could not see how far the current run had got, what earlier runs did,
or how long a run would take before starting one. These tests drive the three
answers off `GET /admin/embedding-stats/`.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin import backfill_jobs
from app.modules.admin.backfill_jobs import (
    RECENT_RUN_LIMIT,
    RECORDS_TOTAL_KEY,
    collect_backfill_observability,
    run_embedding_backfill,
)
from app.modules.admin.service import AdminService
from app.platform.jobs.models import EMBEDDING_BACKFILL_METADATA_KEY, IngestJob
from app.processing.embeddings import backfill as backfill_module

from tests.factories import create_dataset, get_user_id


def _marker(**extra) -> dict:
    return {EMBEDDING_BACKFILL_METADATA_KEY: {"force": False, **extra}}


async def _drop(session: AsyncSession, job_ids: list[uuid.UUID]) -> None:
    await session.execute(delete(IngestJob).where(IngestJob.id.in_(job_ids)))
    await session.commit()


@pytest.mark.anyio
async def test_a_run_in_flight_reports_records_processed_over_total(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The counter the worker writes per batch is what the endpoint reports.

    ``JobStatusResponse.current_step`` is a closed Literal, so the poll the
    admin panel already runs is also the check that the counter writes nothing
    the job contract cannot render.
    """
    from app.core.db import async_session

    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        source_filename="embedding-backfill",
        file_path="",
        created_by=admin_id,
        status="pending",
        user_metadata=_marker(operation_id="progress"),
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id, attempt_id = job.id, job.attempt_id

    seen: list = []
    polled: list = []

    async def _two_batches(
        session, *, force=False, should_continue=None, on_progress=None
    ):
        await on_progress(0, 4)
        await on_progress(2, 4)
        # What an operator polling the admin panel sees while the run is live.
        async with async_session() as watcher:
            seen.append((await AdminService(watcher).get_embedding_stats()).current_run)
        polled.append(await client.get(f"/jobs/{job_id}", headers=admin_auth_header))
        return {"processed": 4, "created": 4, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _two_batches)

    try:
        await run_embedding_backfill(
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            force=False,
            user_id=str(admin_id),
            operation_id="progress",
        )
        assert seen and seen[0] is not None
        current = seen[0]
        assert current.job_id == job_id
        assert current.status == "running"
        assert current.records_processed == 2
        assert current.records_total == 4
        assert current.started_at is not None
        assert polled and polled[0].status_code == 200, polled[0].text
        assert polled[0].json()["rows_processed"] == 2
    finally:
        await _drop(test_db_session, [job_id])


@pytest.mark.anyio
async def test_the_history_is_bounded_and_newest_first(
    test_db_session: AsyncSession,
):
    """The last N finished runs, newest first, with each run's outcome."""
    admin_id = await get_user_id(test_db_session, "admin")
    # Dated ahead of now so sibling suites sharing this database cannot land a
    # row between these and change which of them the bound keeps.
    base = datetime.now(timezone.utc) + timedelta(hours=1)
    seeded: list[uuid.UUID] = []
    for index in range(RECENT_RUN_LIMIT + 2):
        job = IngestJob(
            source_filename="embedding-backfill",
            file_path="",
            created_by=admin_id,
            status="failed" if index == RECENT_RUN_LIMIT + 1 else "complete",
            created_at=base + timedelta(minutes=index),
            started_at=base + timedelta(minutes=index),
            completed_at=base + timedelta(minutes=index, seconds=30),
            rows_processed=index,
            user_metadata=_marker(operation_id=f"history-{index}", error_code="boom")
            if index == RECENT_RUN_LIMIT + 1
            else _marker(operation_id=f"history-{index}"),
        )
        test_db_session.add(job)
        await test_db_session.commit()
        seeded.append(job.id)

    try:
        stats = await AdminService(test_db_session).get_embedding_stats()
        assert [run.job_id for run in stats.recent_runs] == seeded[::-1][
            :RECENT_RUN_LIMIT
        ]
        newest = stats.recent_runs[0]
        assert newest.status == "failed"
        assert newest.error_code == "boom"
        assert newest.records_processed == RECENT_RUN_LIMIT + 1
        assert newest.finished_at is not None
        assert seeded[0] not in {run.job_id for run in stats.recent_runs}
    finally:
        await _drop(test_db_session, seeded)


@pytest.mark.anyio
async def test_the_estimate_uses_the_last_completed_runs_throughput(
    test_db_session: AsyncSession,
):
    """Seconds per record, measured here, applied to both backfill actions."""
    admin_id = await get_user_id(test_db_session, "admin")
    await create_dataset(
        test_db_session, created_by=admin_id, name=f"Estimate {uuid.uuid4().hex[:6]}"
    )
    finished = datetime.now(timezone.utc) + timedelta(hours=1)
    job = IngestJob(
        source_filename="embedding-backfill",
        file_path="",
        created_by=admin_id,
        status="complete",
        created_at=finished,
        started_at=finished - timedelta(seconds=10),
        completed_at=finished,
        rows_processed=100,
        user_metadata=_marker(operation_id="estimate"),
    )
    test_db_session.add(job)
    await test_db_session.commit()

    try:
        stats = await AdminService(test_db_session).get_embedding_stats()
        # Without records to project onto, both sides of the equalities below
        # are zero whatever rate the estimate used.
        assert stats.missing_records > 0 and stats.total_records > 0
        assert stats.estimate is not None
        # 10 seconds for 100 records.
        assert stats.estimate.missing_seconds == round(stats.missing_records * 0.1, 1)
        assert stats.estimate.all_seconds == round(stats.total_records * 0.1, 1)
    finally:
        await _drop(test_db_session, [job.id])


@pytest.mark.anyio
async def test_another_tenants_runs_are_neither_read_nor_estimated_from(monkeypatch):
    """Every run read is tenant-scoped, and no completed run means no estimate."""
    from app.core.db.tenant_session import current_tenant_var

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    token = current_tenant_var.set(uuid.uuid4())
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result

    try:
        observability = await collect_backfill_observability(
            session, missing_records=10, total_records=20
        )
    finally:
        current_tenant_var.reset(token)

    assert observability == {"current_run": None, "recent_runs": [], "estimate": None}
    # The WHERE clause, not the rendered statement: every column of the row is
    # in the SELECT list, so a naive substring check passes with no filter at all.
    predicates = [
        str(call.args[0].whereclause) for call in session.execute.await_args_list
    ]
    assert len(predicates) == 3
    for predicate in predicates:
        assert "ingest_jobs.tenant_id = " in predicate


@pytest.mark.anyio
async def test_a_finished_run_records_the_total_it_set_out_to_embed(
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The terminal write keeps the counter's metadata rather than replacing it."""
    admin_id = await get_user_id(test_db_session, "admin")
    job = IngestJob(
        source_filename="embedding-backfill",
        file_path="",
        created_by=admin_id,
        status="pending",
        user_metadata=_marker(operation_id="total"),
    )
    test_db_session.add(job)
    await test_db_session.commit()
    job_id, attempt_id = job.id, job.attempt_id

    async def _one_batch(
        session, *, force=False, should_continue=None, on_progress=None
    ):
        await on_progress(3, 3)
        return {"processed": 3, "created": 3, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _one_batch)

    try:
        await run_embedding_backfill(
            job_id=str(job_id),
            attempt_id=str(attempt_id),
            force=False,
            user_id=str(admin_id),
            operation_id="total",
        )
        test_db_session.expire_all()
        settled = await test_db_session.get(IngestJob, job_id)
        assert settled is not None
        assert settled.status == "complete"
        assert settled.rows_processed == 3
        meta = (settled.user_metadata or {})[EMBEDDING_BACKFILL_METADATA_KEY]
        assert meta[RECORDS_TOTAL_KEY] == 3
    finally:
        await _drop(test_db_session, [job_id])


@pytest.mark.anyio
async def test_a_progress_write_failure_does_not_end_the_run():
    """Progress is an operator convenience; a run outlives losing it."""
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("connection reset")
    write = backfill_jobs._progress_writer(
        session, uuid.uuid4(), uuid.uuid4(), _marker()
    )

    await write(5, 10)

    session.rollback.assert_awaited()
