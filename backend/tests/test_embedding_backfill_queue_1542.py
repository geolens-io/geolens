"""The embedding backfill runs on the queue, not inside the request (#1542).

`POST /admin/backfill-embeddings/` used to call `backfill_embeddings` inline.
A full regenerate is ~88% provider round trips and scales linearly, so a
catalog somewhere below 59,000 records outgrew nginx's 600s `proxy_read_timeout`
for `/api/`. The request dying at the proxy never stopped the run, which left
three problems, of which the middle one is destructive:

  1. The operator cannot tell "still running" from "died halfway".
  2. The natural retry starts a SECOND full regenerate alongside the first —
     on the force path, a second DELETE. #1519's pre-flight guards do not see
     this, because each run passes its own pre-flight independently.
  3. Provider spend continues after the caller has given up.

These tests drive the real conditions: that the endpoint answers with a job id
instead of blocking for the run's duration, that the queued task does the work,
and — the safety-critical one — that a second force run started while one is in
flight is refused BEFORE anything is deleted.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin import backfill_jobs, router as admin_router
from app.modules.admin.backfill_jobs import run_embedding_backfill
from app.platform.jobs.models import (
    ACTIVE_BACKFILL_INDEX_NAME,
    EMBEDDING_BACKFILL_METADATA_KEY,
    IngestJob,
    commit_attempted_marker,
)
from app.processing.embeddings import backfill as backfill_module
from app.processing.embeddings.models import RecordEmbedding

from tests.factories import create_dataset, get_user_id

_URL = "/admin/backfill-embeddings/"
_FORCE_URL = "/admin/backfill-embeddings/?force=true"


@pytest.fixture(autouse=True)
async def _clear_backfill_slot(test_db_session: AsyncSession):
    """Keep the one global backfill slot empty around every test in this file.

    The guard under test is instance-wide by design, and the worker database is
    shared across the suite: a row this file leaves behind would make the next
    test refuse for the wrong reason, and a row a sibling left behind would do
    the same to the first one here.
    """
    await _release_slot(test_db_session)
    yield
    await _release_slot(test_db_session)


async def _release_slot(session: AsyncSession) -> None:
    await session.execute(
        update(IngestJob)
        .where(
            IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY),
            IngestJob.status.in_(("pending", "running")),
        )
        .values(status="failed")
    )
    await session.commit()


async def _seed_embedding(session: AsyncSession, name: str) -> RecordEmbedding:
    """One dataset with one embedding row — something a force DELETE can take."""
    user_id = await get_user_id(session, "admin")
    dataset = await create_dataset(session, created_by=user_id, name=name)
    embedding = RecordEmbedding(
        record_id=dataset.record_id,
        embedding=[1.0] + [0.0] * 1535,
        model_name="queue-1542-model",
        content_hash=uuid.uuid4().hex[:64],
    )
    session.add(embedding)
    await session.commit()
    return embedding


async def _embedding_count(session: AsyncSession) -> int:
    session.expire_all()
    return (
        await session.execute(select(func.count()).select_from(RecordEmbedding))
    ).scalar_one()


async def _in_flight_job(session: AsyncSession, *, force: bool = True) -> IngestJob:
    """A backfill job the guard must treat as in flight: running, lease fresh."""
    now = datetime.now(timezone.utc)
    job = IngestJob(
        source_filename="embedding-backfill",
        file_path="",
        created_by=await get_user_id(session, "admin"),
        status="running",
        started_at=now,
        heartbeat_at=now,
        user_metadata={
            EMBEDDING_BACKFILL_METADATA_KEY: {"force": force, "operation_id": "seed"}
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _stale_job(
    session: AsyncSession, *, status: str, backfill: bool
) -> IngestJob:
    """A job the shared sweep settles: abandoned `running`, or old `pending`.

    Both halves of the pass have their own UPDATE, their own message and their
    own audit call site, so a fix applied to one of them says nothing about the
    other.
    """
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    job = IngestJob(
        source_filename="embedding-backfill" if backfill else "ordinary-upload.geojson",
        file_path="",
        created_by=await get_user_id(session, "admin"),
        status=status,
        created_at=old,
        started_at=old if status == "running" else None,
        heartbeat_at=old if status == "running" else None,
        # fix(#1744): both rows describe work that was dispatched and then
        # orphaned, which is the class this sweep settles `failed`. Without
        # the stamp the pending half reads them as uploads nobody committed
        # and cancels them, and the non-vacuity assertions below would be
        # measuring a different pass.
        user_metadata=(
            {
                **commit_attempted_marker(),
                EMBEDDING_BACKFILL_METADATA_KEY: {
                    "force": True,
                    "operation_id": f"sweep-pin-{uuid.uuid4().hex[:8]}",
                },
            }
            if backfill
            else {"file_type": "vector", **commit_attempted_marker()}
        ),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _audit_entries_naming(session: AsyncSession, job_id: str) -> int:
    """How many audit rows of ANY action name this job."""
    from app.modules.audit.models import AuditLog

    session.expire_all()
    return (
        await session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.details["job_id"].astext == job_id)
        )
    ).scalar_one()


async def _load_job(session: AsyncSession, job_id) -> IngestJob:
    session.expire_all()
    job = await session.get(IngestJob, uuid.UUID(str(job_id)))
    assert job is not None
    return job


@pytest.mark.anyio
async def test_enqueue_answers_with_a_job_id_and_does_not_run_the_backfill(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The response is an acknowledgement, and the request does no provider work."""
    ran_inline = False

    async def _should_not_run(session, *, force=False, should_continue=None):
        nonlocal ran_inline
        ran_inline = True
        return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _should_not_run)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert ran_inline is False, "the request must not run the backfill itself"

    job = await _load_job(test_db_session, body["job_id"])
    assert job.status == "pending"
    assert job.current_step == "queued"
    assert (job.user_metadata or {})[EMBEDDING_BACKFILL_METADATA_KEY]["force"] is True

    mock_defer.assert_awaited_once()
    kwargs = mock_defer.await_args.kwargs
    assert kwargs["job_id"] == body["job_id"]
    assert kwargs["attempt_id"] == str(job.attempt_id)
    assert kwargs["force"] is True


@pytest.mark.anyio
async def test_enqueue_returns_promptly_instead_of_waiting_for_the_run(
    client: AsyncClient,
    admin_auth_header: dict,
    monkeypatch,
):
    """The 600s ceiling is only reachable if the request waits. It must not.

    Two seconds stands in for the ten minutes a ~59,000-record regenerate takes:
    the inline route's elapsed time is the backfill's elapsed time, whatever the
    catalog size, and the queued route's is not.
    """

    async def _slow_backfill(session, *, force=False, should_continue=None):
        await anyio.sleep(2.0)
        return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _slow_backfill)

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        started = time.monotonic()
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
        elapsed = time.monotonic() - started

    assert resp.status_code == 200, resp.text
    assert elapsed < 1.0, (
        f"the endpoint blocked for {elapsed:.2f}s — it is still running the "
        "backfill inside the request"
    )


@pytest.mark.anyio
async def test_the_queued_task_runs_the_backfill_and_completes_the_job(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """Enqueueing is not the whole promise — the deferred work has to happen."""
    calls: list[bool] = []

    async def _fake_backfill(session, *, force=False, should_continue=None):
        calls.append(force)
        return {"processed": 7, "created": 6, "skipped": 0, "errors": 1}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _fake_backfill)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # Run exactly what was handed to the queue.
    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    assert calls == [True], "the queued task did not run the backfill"

    job = await _load_job(test_db_session, job_id)
    assert job.status == "complete"
    assert job.error_message is None
    assert job.rows_processed == 7
    result = (job.user_metadata or {})[EMBEDDING_BACKFILL_METADATA_KEY]["result"]
    assert result == {"processed": 7, "created": 6, "skipped": 0, "errors": 1}

    audit = await client.get(
        "/admin/audit-logs/",
        params={"action": "embedding.backfill"},
        headers=admin_auth_header,
    )
    assert audit.status_code == 200
    entries = audit.json()["logs"]
    completed = next(
        e
        for e in entries
        if e["details"]["outcome"] == "completed"
        and e["details"].get("job_id") == job_id
    )
    assert completed["details"]["created"] == 6
    requested = next(
        e
        for e in entries
        if e["details"]["outcome"] == "requested"
        and e["details"].get("job_id") == job_id
    )
    assert requested["details"]["force"] is True
    assert requested["ip_address"] is not None


@pytest.mark.anyio
async def test_second_force_run_while_one_is_in_flight_is_refused_before_any_delete(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The whole point: the retry after a lost response must not delete again.

    A force run's first committed act is `DELETE FROM record_embeddings`, and it
    happens in the worker. So the queue hop here is an EAGER one — the deferred
    task runs the moment it is enqueued, which is what a real worker with an
    empty queue does. Without that, "the vectors survived" would hold in a build
    with no guard at all, purely because nothing ran the job, and the ordering
    this test exists to pin would go unasserted.
    """
    await _seed_embedding(test_db_session, f"Queue Guard {uuid.uuid4().hex[:6]}")
    before = await _embedding_count(test_db_session)
    # Non-vacuity: with no rows seeded, "the rows survived" asserts nothing.
    assert before > 0

    deleted_anything = False

    async def _destructive_backfill(session, *, force=False, should_continue=None):
        nonlocal deleted_anything
        deleted_anything = True
        await session.execute(delete(RecordEmbedding))
        await session.commit()
        return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _destructive_backfill)

    async def _run_immediately(_task, /, **kwargs):
        await run_embedding_backfill(**kwargs)

    # Read the id out before anything expires the instance: the assertions
    # below call `session.expire_all()`, and a lazy refresh from inside an
    # assert raises MissingGreenlet instead of failing the claim.
    in_flight_id = str((await _in_flight_job(test_db_session)).id)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock(side_effect=_run_immediately)
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)

    # Asserted first, deliberately: this is the ordering claim. A build whose
    # guard is missing fails HERE, on the destroyed vectors, not on the status
    # code — the status code is how the operator learns, the surviving rows are
    # what the guard is for.
    assert deleted_anything is False, "the refused run reached the DELETE"
    assert await _embedding_count(test_db_session) == before
    mock_defer.assert_not_awaited()
    assert resp.status_code == 409, resp.text
    assert in_flight_id in resp.json()["detail"]

    # And no second job row was created to hold the slot.
    active = await test_db_session.execute(
        select(func.count())
        .select_from(IngestJob)
        .where(
            IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY),
            IngestJob.status.in_(("pending", "running")),
        )
    )
    assert active.scalar_one() == 1


@pytest.mark.anyio
async def test_a_queued_run_also_blocks_a_second_one(
    client: AsyncClient,
    admin_auth_header: dict,
    monkeypatch,
):
    """A run that has not been picked up yet holds the slot too.

    The dangerous window is widest here: the first run has committed nothing,
    so nothing about the catalog shows that a regenerate is already coming.
    """
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        first = await client.post(_FORCE_URL, headers=admin_auth_header)
        assert first.status_code == 200, first.text
        second = await client.post(_FORCE_URL, headers=admin_auth_header)
        assert second.status_code == 409, second.text
        # The non-force run is refused by the same guard: it would duplicate
        # the provider spend and race the in-flight run's inserts.
        third = await client.post(_URL, headers=admin_auth_header)
        assert third.status_code == 409, third.text


@pytest.mark.anyio
async def test_a_finished_run_releases_the_slot(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The guard refuses concurrency, not the operation."""
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())
    in_flight = await _in_flight_job(test_db_session)

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        refused = await client.post(_FORCE_URL, headers=admin_auth_header)
        assert refused.status_code == 409, refused.text

        in_flight.status = "complete"
        await test_db_session.commit()

        allowed = await client.post(_FORCE_URL, headers=admin_auth_header)
        assert allowed.status_code == 200, allowed.text


@pytest.mark.anyio
async def test_a_dead_workers_run_holds_the_slot_until_the_sweeper_settles_it(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """A stale heartbeat is not proof the old worker is gone.

    fix(#1542 review P1): an earlier revision admitted a new run as soon as the
    lease lapsed. That cannot be expressed as a partial unique index — the
    predicate has to be immutable, so it cannot consult `now()` — and for a
    force run, "we have not heard from the worker" is the wrong evidence on
    which to start a second DELETE of every embedding. The slot is released by
    the row reaching a terminal status, which for an abandoned run is the
    stale-job sweeper's job, on the same backstop every other ingest job uses.
    """
    from app.platform.jobs.sweep import fail_stale_jobs

    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())
    stale = await _in_flight_job(test_db_session)
    expired = datetime.now(timezone.utc) - timedelta(hours=3)
    stale.started_at = expired
    stale.heartbeat_at = expired
    await test_db_session.commit()

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        refused = await client.post(_FORCE_URL, headers=admin_auth_header)
        assert refused.status_code == 409, refused.text

        # The real release path, not a hand-written UPDATE.
        await fail_stale_jobs(test_db_session)
        settled = await _load_job(test_db_session, stale.id)
        assert settled.status == "failed", "the sweeper did not settle the row"

        allowed = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert allowed.status_code == 200, allowed.text


@pytest.mark.anyio
async def test_a_failed_run_marks_the_job_failed_without_leaking_the_error(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """RES-2 survives the move: the provider's error text stays in the log."""
    secret = "provider-secret-token=do-not-expose"

    async def _explode(session, *, force=False, should_continue=None):
        raise RuntimeError(secret)

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _explode)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    job = await _load_job(test_db_session, job_id)
    assert job.status == "failed"
    assert job.error_message == backfill_jobs.BACKFILL_FAILED_MESSAGE
    assert secret not in (job.error_message or "")

    status_resp = await client.get(f"/jobs/{job_id}", headers=admin_auth_header)
    assert status_resp.status_code == 200, status_resp.text
    payload = status_resp.json()
    assert payload["status"] == "failed"
    assert secret not in status_resp.text
    # A backfill is not an import, so the ingest retry path must not offer to
    # replay it — that would skip the pre-flight and concurrency guards.
    assert payload["can_retry"] is False
    assert "backfill" in (payload["retry_reason"] or "").lower()

    audit = await client.get(
        "/admin/audit-logs/",
        params={"action": "embedding.backfill"},
        headers=admin_auth_header,
    )
    failed = next(
        e
        for e in audit.json()["logs"]
        if e["details"]["outcome"] == "failed" and e["details"].get("job_id") == job_id
    )
    assert failed["details"]["error_code"] == "backfill_failed"
    assert secret not in str(failed["details"])


@pytest.mark.anyio
async def test_backfill_still_requires_admin(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """The queue move does not widen who may start a run."""
    resp = await client.post(_FORCE_URL, headers=viewer_auth_header)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Job row and audit trail are two records of one state (#1550 review P2)
# ---------------------------------------------------------------------------
#
# A run's state is written by independent paths, so any path that updates the
# job row without the audit trail — or the audit trail without the row — opens
# a window where the two disagree. The enumeration of every terminating path is
# in the PR body; these cover the ones this code owns. The two directions are
# not equally bad: a missing terminal entry leaves an administrative operation
# looking perpetually in flight, while a terminal entry the row does not support
# actively lies about what happened.


async def _terminal_audit_entries(
    client: AsyncClient, headers: dict, job_id: str
) -> list[dict]:
    """Every non-`requested` audit entry for one backfill run."""
    resp = await client.get(
        "/admin/audit-logs/",
        params={"action": "embedding.backfill"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return [
        entry
        for entry in resp.json()["logs"]
        if entry["details"].get("job_id") == job_id
        and entry["details"]["outcome"] != "requested"
    ]


@pytest.mark.anyio
async def test_a_dispatch_failure_closes_the_audit_trail(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """A run that never reached the queue still has to reach a terminal record.

    The queue lives inside PostgreSQL, so "the queue is unreachable" is a real
    operational state, not a hypothetical. The orphan guard marks the job failed
    and answers 503 — and no worker will ever pick this run up, so if the route
    does not close the trail here, nothing ever does and the already-committed
    `requested` entry stands as the last word forever.
    """
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    async def _queue_is_down(_task, /, **kwargs):
        raise RuntimeError("procrastinate connector: connection refused")

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock(side_effect=_queue_is_down)
    ):
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)

    assert resp.status_code == 503, resp.text

    # The job row's half of the pair — the orphan guard's existing behaviour.
    job = (
        (
            await test_db_session.execute(
                select(IngestJob)
                .where(IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY))
                .order_by(IngestJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    assert job is not None
    assert job.status == "failed"
    job_id = str(job.id)

    # The audit trail's half. Without it the operation reads as still running.
    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["outcome"] == "failed"
    assert terminal[0]["details"]["error_code"] == "dispatch_failed"
    assert terminal[0]["details"]["force"] is True


@pytest.mark.anyio
async def test_losing_the_fence_never_audits_a_completion_that_did_not_land(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The lie case: failed job row, "completed" audit entry.

    Driven through the real mechanism rather than a stubbed return — the stale
    job sweeper expires the worker's lease mid-run, exactly as it does when a
    long backfill's heartbeat lapses, and `_finalize`'s fenced UPDATE then
    matches nothing. The audit must not claim the run completed, because the row
    says it failed and the row is what an operator reads.
    """
    from app.core.db import async_session
    from app.platform.jobs.sweep import fail_stale_jobs

    async def _backfill_then_lose_the_lease(
        session, *, force=False, should_continue=None
    ):
        # A different actor, on its own connection, as the sweeper really is.
        async with async_session() as other:
            expired = datetime.now(timezone.utc) - timedelta(hours=3)
            await other.execute(
                update(IngestJob)
                .where(
                    IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY),
                    IngestJob.status == "running",
                )
                .values(started_at=expired, heartbeat_at=expired)
            )
            await other.commit()
            await fail_stale_jobs(other)
        return {"processed": 3, "created": 3, "skipped": 0, "errors": 0}

    monkeypatch.setattr(
        backfill_module, "backfill_embeddings", _backfill_then_lose_the_lease
    )

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    job = await _load_job(test_db_session, job_id)
    # Non-vacuity: if the sweeper did not actually take the row, the fence was
    # never lost and this test proves nothing about the branch it targets.
    assert job.status == "failed", "the lease was never expired — test is vacuous"

    # Two actors could each close this run — the sweeper that failed a row
    # which looked dead, and the worker that finished and lost its fence. One
    # operation gets ONE terminal entry, whoever writes it first, so the
    # sweeper's stands and the worker's is suppressed. What must never appear
    # is an entry claiming the run completed: the row says failed.
    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    details = terminal[0]["details"]
    assert details["outcome"] != "completed", (
        f"the audit claims a completion the job row does not support: {terminal}"
    )
    assert details["error_code"] == "worker_lost", (
        f"the actor that settled the row did not close the trail: {terminal}"
    )


@pytest.mark.anyio
async def test_a_run_the_worker_never_claims_still_reaches_a_terminal_record(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The reaper failed the row before the worker got to it.

    Same class as the dispatch failure, at the other end of the queue hop: the
    run ends without this worker ever owning it, and nothing downstream will
    emit its outcome.
    """
    from app.platform.jobs.sweep import fail_stale_jobs

    ran = False

    async def _should_not_run(session, *, force=False, should_continue=None):
        nonlocal ran
        ran = True
        return {"processed": 0, "created": 0, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _should_not_run)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # Age the queued row past the pending-abandonment policy and let the real
    # reaper take it, before the worker ever picks the delivery up.
    await test_db_session.execute(
        update(IngestJob)
        .where(IngestJob.id == uuid.UUID(job_id))
        .values(created_at=datetime.now(timezone.utc) - timedelta(hours=3))
    )
    await test_db_session.commit()
    await fail_stale_jobs(test_db_session)
    reaped = await _load_job(test_db_session, job_id)
    assert reaped.status == "failed", (
        "the reaper did not take the row — test is vacuous"
    )

    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    assert ran is False, "the worker ran a job it did not own"
    # Same rule: the reaper settled the row and closed the trail first, so the
    # worker's own "I never owned this" entry is suppressed rather than added.
    # The run still reaches exactly one terminal record, which is the point.
    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["error_code"] == "never_started", (
        f"the actor that settled the row did not close the trail: {terminal}"
    )
    assert terminal[0]["details"]["outcome"] != "completed"


@pytest.mark.anyio
async def test_every_terminating_path_writes_exactly_one_terminal_audit_entry(
    client: AsyncClient,
    admin_auth_header: dict,
    monkeypatch,
):
    """The invariant behind the four tests above, asserted as one property.

    Worker success and worker failure are the two paths where the row and the
    trail agree the easy way; they are here so the property is stated over the
    whole set rather than only over the broken paths, and so a future path added
    without an audit write fails a test that is about the rule, not about it.
    """

    async def _ok(session, *, force=False, should_continue=None):
        return {"processed": 2, "created": 2, "skipped": 0, "errors": 0}

    async def _boom(session, *, force=False, should_continue=None):
        raise RuntimeError("provider down")

    for backfill_impl, expected_outcome in ((_ok, "completed"), (_boom, "failed")):
        monkeypatch.setattr(backfill_module, "backfill_embeddings", backfill_impl)
        with patch.object(
            admin_router, "defer_async_with_tenant", AsyncMock()
        ) as mock_defer:
            resp = await client.post(_FORCE_URL, headers=admin_auth_header)
        assert resp.status_code == 200, resp.text
        job_id = resp.json()["job_id"]

        await run_embedding_backfill(**mock_defer.await_args.kwargs)

        terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
        assert len(terminal) == 1, terminal
        assert terminal[0]["details"]["outcome"] == expected_outcome


# ---------------------------------------------------------------------------
# The guard is the index, not the check (#1550 review P1)
# ---------------------------------------------------------------------------
#
# A SELECT followed by an INSERT is a TOCTOU on exactly the invariant that
# stops two concurrent force runs from each committing a DELETE of every
# embedding. Two requests arriving together can both pass the check. The
# pre-flight query is kept because it produces a readable 409 for the ordinary
# retry; the thing that actually holds is the partial unique index from
# migration 0050.


@pytest.mark.anyio
async def test_the_index_refuses_a_second_active_run_when_the_check_is_blind(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The race, made deterministic: the check passes and the insert must not.

    Blinding the pre-flight query is a faithful stand-in for two transactions
    interleaving — in the real race both requests SELECT before either commits,
    so both see an empty slot, which is precisely what a query returning None
    reproduces. What is left is the database, and the database is the guard.
    """
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())
    in_flight_id = str((await _in_flight_job(test_db_session)).id)

    async def _sees_nothing(_session):
        return None

    with (
        # The route imports it per call, so the definition site is what to patch.
        patch.object(backfill_jobs, "find_active_embedding_backfill", _sees_nothing),
        patch.object(
            admin_router, "defer_async_with_tenant", AsyncMock()
        ) as mock_defer,
    ):
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)

    assert resp.status_code == 409, resp.text
    mock_defer.assert_not_awaited()

    # And exactly one active run survives — the one that was already there.
    active = (
        (
            await test_db_session.execute(
                select(IngestJob).where(
                    IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY),
                    IngestJob.status.in_(("pending", "running")),
                )
            )
        )
        .scalars()
        .all()
    )
    assert [str(job.id) for job in active] == [in_flight_id]


@pytest.mark.anyio
async def test_two_concurrent_transactions_cannot_both_create_an_active_run(
    test_db_session: AsyncSession,
):
    """The invariant itself, under genuine contention.

    An earlier version of this test committed the first transaction before the
    second even flushed, which is a sequence, not a race — it would have passed
    against a plain non-unique index. Here the second insert is issued while the
    first is still uncommitted, so PostgreSQL makes it WAIT on the unresolved
    index key, and the assertion that it is still blocked is the proof that the
    two transactions genuinely contended rather than took turns.
    """
    from sqlalchemy.exc import IntegrityError

    from app.core.db import async_session

    admin_id = await get_user_id(test_db_session, "admin")

    def _row() -> IngestJob:
        return IngestJob(
            source_filename="embedding-backfill",
            file_path="",
            created_by=admin_id,
            status="pending",
            user_metadata={
                EMBEDDING_BACKFILL_METADATA_KEY: {"force": True, "operation_id": "race"}
            },
        )

    async with async_session() as first, async_session() as second:
        first.add(_row())
        await first.flush()  # holds the index key, uncommitted

        second.add(_row())
        contender = asyncio.create_task(second.flush())
        # Give it room to either block or fail. Blocking is the correct
        # behaviour: PostgreSQL cannot decide uniqueness until the first
        # transaction resolves.
        await asyncio.sleep(0.5)
        assert not contender.done(), (
            "the second insert did not contend for the key — the two "
            "transactions took turns, so this proves nothing about a race"
        )

        await first.commit()  # the winner resolves; the contender can now fail

        with pytest.raises(IntegrityError) as caught:
            await contender
        assert ACTIVE_BACKFILL_INDEX_NAME in str(caught.value)
        await second.rollback()

    await _release_slot(test_db_session)


@pytest.mark.anyio
async def test_two_concurrent_force_requests_produce_exactly_one_delete(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The safety case, measured end to end under real concurrency.

    Two force runs fired together, both racing the same guard, with the queue
    hop EAGER so whichever request wins actually executes its task and reaches
    the DELETE. The measurement is the delete count: two concurrent force runs
    must produce exactly one, whatever order the two requests interleave in.
    """
    await _seed_embedding(test_db_session, f"Race Delete {uuid.uuid4().hex[:6]}")
    before = await _embedding_count(test_db_session)
    assert before > 0  # non-vacuity: there is something a DELETE could take

    deletes = 0

    async def _destructive_backfill(session, *, force=False, should_continue=None):
        nonlocal deletes
        deletes += 1
        await session.execute(delete(RecordEmbedding))
        await session.commit()
        return {"processed": 1, "created": 1, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _destructive_backfill)

    async def _run_immediately(_task, /, **kwargs):
        await run_embedding_backfill(**kwargs)

    # Scope the row count to this episode: the file's other tests leave backfill
    # rows behind, so any time-window filter would count theirs too.
    existing = set(
        (
            await test_db_session.execute(
                select(IngestJob.id).where(
                    IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY)
                )
            )
        ).scalars()
    )

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock(side_effect=_run_immediately)
    ):
        first, second = await asyncio.gather(
            client.post(_FORCE_URL, headers=admin_auth_header),
            client.post(_FORCE_URL, headers=admin_auth_header),
        )

    # The safety claim first: the status codes are how the operator learns, the
    # delete count is what the guard exists to hold.
    assert deletes == 1, (
        f"two concurrent force runs reached the DELETE {deletes} times — the "
        "guard did not hold under contention"
    )
    assert await _embedding_count(test_db_session) == 0, (
        "the winner's DELETE never ran, so the count above is vacuous"
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409], (
        f"expected exactly one winner, got {first.status_code} and {second.status_code}"
    )

    # And exactly one job row was created for the whole episode — the loser's
    # transaction rolled back, so it leaves no trace of a run that never ran.
    created_now = (
        set(
            (
                await test_db_session.execute(
                    select(IngestJob.id).where(
                        IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY)
                    )
                )
            ).scalars()
        )
        - existing
    )
    assert len(created_now) == 1, created_now


@pytest.mark.anyio
async def test_a_cancelled_worker_releases_the_slot_and_closes_the_trail(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The exit that is not an `Exception` (#1550 review).

    A deploy cancels this multi-minute task after it has claimed the job.
    `asyncio.CancelledError` inherits from `BaseException`, so it walks past
    `except Exception`: the row stayed `running` and — since the guard is now a
    unique index over exactly that status — held the single active-run slot
    until the 60-minute sweep. An ordinary deploy turned the concurrency guard
    into a denial of service on itself, with the trail still reading
    `requested` even if a force run had already deleted every vector.
    """

    async def _cancelled_mid_run(session, *, force=False, should_continue=None):
        raise asyncio.CancelledError()

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _cancelled_mid_run)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    # Cooperative shutdown depends on the cancellation propagating, so the task
    # must re-raise rather than swallow it.
    with pytest.raises(asyncio.CancelledError):
        await run_embedding_backfill(**mock_defer.await_args.kwargs)

    job = await _load_job(test_db_session, job_id)
    assert job.status == "failed", (
        "the cancelled run is still holding the single active-backfill slot"
    )
    assert "cancelled" in (job.error_message or "").lower()

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["error_code"] == "worker_cancelled"

    # The slot is genuinely free: a new run is admitted.
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())
    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        again = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert again.status_code == 200, again.text


@pytest.mark.anyio
async def test_a_run_that_created_nothing_is_not_reported_as_complete(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """Zero coverage must not read as a finished regenerate (#1550 review P1).

    `backfill_embeddings` catches per-record provider errors and RETURNS counts
    rather than raising, so a run where every embedding was rejected came back
    normally. On the force path that is a catalog whose vectors were deleted and
    never rebuilt, stamped `complete` — and the job-status response does not
    expose the nested counts, so polling saw a clean success.
    """

    async def _every_record_failed(session, *, force=False, should_continue=None):
        return {"processed": 9, "created": 0, "skipped": 0, "errors": 9}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _every_record_failed)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]

    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    job = await _load_job(test_db_session, job_id)
    assert job.status == "failed", (
        "a run that created zero embeddings after deleting every vector is "
        "reported as a completed regenerate"
    )
    assert job.current_step != "complete"
    # The counts survive anyway — they are the evidence for the diagnosis.
    result = (job.user_metadata or {})[EMBEDDING_BACKFILL_METADATA_KEY]["result"]
    assert result["errors"] == 9

    status_resp = await client.get(f"/jobs/{job_id}", headers=admin_auth_header)
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "failed"

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["outcome"] == "failed"
    assert terminal[0]["details"]["error_code"] == "all_embeddings_failed"


@pytest.mark.anyio
async def test_a_partly_failed_run_still_completes(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The counterpart, so the rule above is a rule and not a blanket.

    One rejected record out of many is not a failed run — it is a run with a
    known gap, and failing it would push an operator to repeat a ten-minute
    regenerate over a catalog that is mostly covered.
    """

    async def _mostly_worked(session, *, force=False, should_continue=None):
        return {"processed": 10, "created": 9, "skipped": 0, "errors": 1}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _mostly_worked)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]
    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    job = await _load_job(test_db_session, job_id)
    assert job.status == "complete"
    assert job.rows_processed == 10


# ---------------------------------------------------------------------------
# One guarded terminal exit (#1550 review round 3)
# ---------------------------------------------------------------------------
#
# This class of defect was fixed four times — the dispatch failure, the lost
# fence, the cancellation — and each fix revealed one more exit that did not go
# through it. These two cover the exits that a handler-per-exception-type shape
# structurally cannot: a failure of the terminal write ITSELF, and a
# cancellation arriving after the terminal write already committed.


@pytest.mark.anyio
async def test_a_failing_terminal_write_does_not_wedge_the_slot(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """A connection blip during the terminal UPDATE, after the work finished.

    The old shape caught only `CancelledError` around the terminal write, so an
    ordinary `Exception` raised inside it escaped: the row stayed `running`,
    holding the single active-backfill slot until the 60-minute sweep, with the
    completed provider work recorded nowhere. Recovery retries on a fresh
    session — which is the point of using a fresh one, since the session that
    just raised may be unusable.
    """
    real_update = backfill_jobs.update_ingest_job_for_attempt
    calls = {"n": 0}

    async def _first_write_blows_up(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset during terminal update")
        return await real_update(*args, **kwargs)

    monkeypatch.setattr(
        backfill_jobs, "update_ingest_job_for_attempt", _first_write_blows_up
    )

    async def _worked_fine(session, *, force=False, should_continue=None):
        return {"processed": 4, "created": 4, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _worked_fine)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]

    # The task re-raises rather than pretending it recorded itself.
    with pytest.raises(RuntimeError):
        await run_embedding_backfill(**mock_defer.await_args.kwargs)

    # The harm first — the `pytest.raises` above already proves the terminal
    # write genuinely blew up, so this is not vacuous.
    job = await _load_job(test_db_session, job_id)
    assert job.status != "running", (
        "the run is still holding the single active-backfill slot after a "
        "failed terminal write"
    )
    assert job.status == "complete"
    # And it was the recovery that settled it, not an undisturbed happy path.
    assert calls["n"] >= 2, "the terminal write did not fail and retry"

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["outcome"] == "completed"

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        again = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert again.status_code == 200, again.text


@pytest.mark.anyio
async def test_a_late_cancellation_does_not_contradict_a_committed_success(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The shutdown lands after `complete` committed, before the audit finishes.

    The previous revision sent every cancellation through a "mark it failed"
    cleanup. Its fenced update could not apply to an already-complete row, so it
    recorded `unresolved` with `intended_outcome="failed"` over a job that had
    durably succeeded — worse than the divergence it replaced, because the trail
    then actively contradicts a committed outcome rather than merely lagging it.
    """
    real_terminal_audit = backfill_jobs._emit_terminal_audit
    calls = {"n": 0}

    async def _cancelled_on_the_first_audit(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.CancelledError()
        await real_terminal_audit(**kwargs)

    monkeypatch.setattr(
        backfill_jobs, "_emit_terminal_audit", _cancelled_on_the_first_audit
    )

    async def _worked_fine(session, *, force=False, should_continue=None):
        return {"processed": 5, "created": 5, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _worked_fine)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]

    with pytest.raises(asyncio.CancelledError):
        await run_embedding_backfill(**mock_defer.await_args.kwargs)

    job = await _load_job(test_db_session, job_id)
    # Non-vacuity: the row must genuinely have committed `complete` BEFORE the
    # cancellation, or there is no committed outcome to contradict.
    assert job.status == "complete", (
        "the terminal write never landed, so this proves nothing about "
        "overwriting a committed success"
    )

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    details = terminal[0]["details"]
    assert details["outcome"] == "completed", (
        f"the trail says {details['outcome']!r} over a job the database "
        "records as complete"
    )
    assert "intended_outcome" not in details
    assert details.get("error_code") != "worker_cancelled"


# ---------------------------------------------------------------------------
# Recovery observes the row, it does not infer from the fence (#1550 round 4)
# ---------------------------------------------------------------------------
#
# In-process state cannot describe what the database did. "My fenced update
# matched nothing" has two causes that demand opposite audit entries — someone
# else settled the row, or I settled it and never heard back — and no flag set
# after `_finalize` returns can tell them apart.


@pytest.mark.anyio
async def test_a_lost_commit_acknowledgement_is_not_read_as_failure(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The terminal write commits; the caller never hears that it did.

    A cancellation or a dropped connection during `commit()` leaves the row
    durably `complete` and the worker believing it wrote nothing. Deciding from
    the in-process flag then retried the fenced update, matched nothing —
    because the row is complete, not running — and recorded `unresolved` over a
    committed success.
    """
    real_finalize = backfill_jobs._finalize
    calls = {"n": 0}

    async def _commits_then_loses_the_answer(*args, **kwargs):
        # Only the first call loses its answer. A recovery that retries the
        # write must be free to do so — whether it retries at all, and what it
        # concludes, is the thing under test.
        calls["n"] += 1
        result = await real_finalize(*args, **kwargs)  # the row really commits
        if calls["n"] == 1:
            raise asyncio.CancelledError()  # ...the caller never learns it
        return result

    monkeypatch.setattr(backfill_jobs, "_finalize", _commits_then_loses_the_answer)

    async def _worked_fine(session, *, force=False, should_continue=None):
        return {"processed": 6, "created": 6, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _worked_fine)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]

    with pytest.raises(asyncio.CancelledError):
        await run_embedding_backfill(**mock_defer.await_args.kwargs)

    job = await _load_job(test_db_session, job_id)
    # Non-vacuity: the commit genuinely landed, so there is a durable success
    # for the trail to get wrong.
    assert job.status == "complete", "the terminal write never committed"

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    details = terminal[0]["details"]
    assert details["outcome"] == "completed", (
        f"the trail says {details['outcome']!r} about a row the database "
        "records as complete"
    )
    assert "intended_outcome" not in details
    # Reading the row also means not re-issuing a write that already landed.
    assert calls["n"] == 1, "the recovery re-ran a terminal write it did not owe"


@pytest.mark.anyio
async def test_recovery_does_not_block_on_the_transaction_it_is_recovering_from(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The caller's transaction still holds the row lock when recovery starts.

    A cancellation during `commit()` leaves the fenced UPDATE applied and the
    transaction open, so the row is locked. Opening a fresh session and issuing
    another UPDATE against that row deadlocks the recovery against its own
    caller until the timeout — after which nothing is written and the run keeps
    the unique slot until the stale sweep. Measured, not asserted: the recovery
    has a 15s budget, so blocking is visible as elapsed time.
    """
    real_update = backfill_jobs.update_ingest_job_for_attempt
    calls = {"n": 0}

    async def _locks_the_row_then_dies(*args, **kwargs):
        # The real UPDATE runs and takes the row lock; the transaction is then
        # abandoned without committing, exactly as a cancelled commit leaves it.
        # Only the FIRST call: the recovery's own write must be allowed to
        # proceed, because whether it can is the thing being measured.
        calls["n"] += 1
        result = await real_update(*args, **kwargs)
        if calls["n"] == 1:
            raise RuntimeError("connection lost while committing")
        return result

    monkeypatch.setattr(
        backfill_jobs, "update_ingest_job_for_attempt", _locks_the_row_then_dies
    )

    async def _worked_fine(session, *, force=False, should_continue=None):
        return {"processed": 3, "created": 3, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _worked_fine)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]

    started = time.monotonic()
    with pytest.raises(RuntimeError):
        await run_embedding_backfill(**mock_defer.await_args.kwargs)
    elapsed = time.monotonic() - started

    assert elapsed < 10.0, (
        f"recovery took {elapsed:.1f}s — it blocked on the row lock its own "
        "caller was still holding, and only gave up at the timeout"
    )
    job = await _load_job(test_db_session, job_id)
    assert job.status != "running", (
        "the run is still holding the single active-backfill slot after the "
        "recovery timed out against its own caller"
    )
    # Non-vacuity: the recovery really did have to take the lock for itself,
    # rather than finding the work already done.
    assert calls["n"] >= 2, "the recovery never issued its own terminal write"

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal


# ---------------------------------------------------------------------------
# The last actor: after a hard kill, the sweeper closes the trail (#1550)
# ---------------------------------------------------------------------------
#
# Every other exit is closed inside the worker. A SIGKILL has no in-process
# path to close, because there is no process. Whoever settles the row is the
# only one left that can record the outcome.


@pytest.mark.anyio
async def test_the_sweeper_closes_the_trail_of_a_hard_killed_run(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The worker is killed after claiming the job. Nothing in it ever runs.

    No `except` clause and no `finally` can help here — the process is gone.
    The stale sweeper later flips the row to `failed`, and unless it also
    records the outcome the trail sits at `requested` forever while the job is
    terminal. On the force path that can be a catalog whose vectors are gone.
    """
    from app.platform.jobs.sweep import fail_stale_jobs

    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]
    kwargs = mock_defer.await_args.kwargs

    # The worker claims the job and is then killed: no exception, no unwind,
    # no cleanup — just a row left `running` and a process that is gone.
    claimed = await _load_job(test_db_session, job_id)
    claimed.status = "running"
    hard_killed = datetime.now(timezone.utc) - timedelta(hours=3)
    claimed.started_at = hard_killed
    claimed.heartbeat_at = hard_killed
    await test_db_session.commit()

    assert await _terminal_audit_entries(client, admin_auth_header, job_id) == [], (
        "the run already had a terminal entry before the sweep — vacuous"
    )

    await fail_stale_jobs(test_db_session)

    job = await _load_job(test_db_session, job_id)
    assert job.status == "failed", "the sweeper did not settle the row"

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    details = terminal[0]["details"]
    assert details["outcome"] == "failed"
    assert details["error_code"] == "worker_lost"
    # Correlated: the `requested` entry the route committed must be closable by
    # this one, or the operation still reads as unresolved.
    requested = next(
        e
        for e in (
            await client.get(
                "/admin/audit-logs/",
                params={"action": "embedding.backfill"},
                headers=admin_auth_header,
            )
        ).json()["logs"]
        if e["details"].get("job_id") == job_id
        and e["details"]["outcome"] == "requested"
    )
    assert details["operation_id"] == requested["details"]["operation_id"]
    assert details["force"] is True
    # Unused kwargs: the worker never ran, which is the whole point.
    assert kwargs["job_id"] == job_id


@pytest.mark.anyio
async def test_a_status_poll_that_settles_a_dead_run_also_closes_the_trail(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """`/jobs/{id}` auto-fails an expired lease, so it settles rows too.

    It is the path that actually fires when anything is polling, so leaving it
    out would mean the trail closes only when the background sweep happens to
    get there first.
    """
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]

    claimed = await _load_job(test_db_session, job_id)
    claimed.status = "running"
    expired = datetime.now(timezone.utc) - timedelta(hours=3)
    claimed.started_at = expired
    claimed.heartbeat_at = expired
    await test_db_session.commit()

    status_resp = await client.get(f"/jobs/{job_id}", headers=admin_auth_header)
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "failed", (
        "the poll did not settle the row — nothing to close the trail for"
    )

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["error_code"] == "worker_lost"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "job_status,error_code",
    [("running", "worker_lost"), ("pending", "never_started")],
)
async def test_the_shared_sweep_settles_an_ingest_job_without_auditing_it(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    job_status: str,
    error_code: str,
):
    """The sweep is shared; only the backfill semantics were taught to it.

    A blanket "audit whatever the sweep touched" would put embedding-backfill
    entries over uploads, which is a different fabricated record. An ordinary
    ingest job's own semantics on this path are "no audit entry at all" — a
    background sweep is not an operator action, and `embedding.backfill` is the
    only action this pass can write — so the assertion is that nothing in the
    log names the upload.

    A real backfill is swept in the SAME pass as the counterfactual. Without it
    "no entries appeared for the upload" would hold just as well in a build
    where the audit hook never fires at all, which is the opposite bug and the
    one #1550 fixed; with it, the pass has to pick one row and not the other.
    Both halves of the sweep are exercised because each has its own UPDATE,
    its own message and its own call site.
    """
    from app.platform.jobs.sweep import fail_stale_jobs

    upload = await _stale_job(test_db_session, status=job_status, backfill=False)
    backfill = await _stale_job(test_db_session, status=job_status, backfill=True)
    upload_id, backfill_id = str(upload.id), str(backfill.id)

    assert await _audit_entries_naming(test_db_session, upload_id) == 0

    await fail_stale_jobs(test_db_session)

    # Non-vacuity: the pass really settled BOTH rows, so both had an outcome to
    # record and exactly one of them should have one recorded.
    assert (await _load_job(test_db_session, upload_id)).status == "failed", (
        "the sweep no longer closes an ordinary ingest job it used to close"
    )
    assert (await _load_job(test_db_session, backfill_id)).status == "failed"

    assert await _audit_entries_naming(test_db_session, upload_id) == 0, (
        "the shared sweep wrote an audit entry for an ordinary upload"
    )
    terminal = await _terminal_audit_entries(client, admin_auth_header, backfill_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["error_code"] == error_code


@pytest.mark.anyio
async def test_a_status_poll_whose_update_loses_the_race_audits_nothing(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The poll's auto-fail is conditional, so its audit must be too.

    The handler reads a job that looks stale, then issues an UPDATE fenced on
    the attempt token, the status and the heartbeat. A heartbeat renewal or the
    worker's own finalization committing in between makes that write match zero
    rows — and the audit ran anyway, putting `worker_lost` over a job that had
    just completed. Same rule `_finalize` follows: a state change reports
    whether it landed, and the caller conditions on that.

    The race window is driven, not waited for. A SECOND admin polling someone
    else's job takes the cross-user permission check, which is the one awaited
    step between the handler's read and its write — so settling the row from
    there lands the competing commit exactly where a real renewal would.
    """
    from app.core.db import async_session
    from app.platform.jobs import router as jobs_router

    from tests.conftest import _create_test_user

    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]

    claimed = await _load_job(test_db_session, job_id)
    claimed.status = "running"
    expired = datetime.now(timezone.utc) - timedelta(hours=3)
    claimed.started_at = expired
    claimed.heartbeat_at = expired
    await test_db_session.commit()

    other_admin_headers, _ = await _create_test_user(client, admin_auth_header, "admin")

    raced = {"n": 0}
    real_check = jobs_router._can_access_another_users_job

    async def _settle_it_mid_request(*args, **kwargs):
        raced["n"] += 1
        async with async_session() as other:
            await other.execute(
                update(IngestJob)
                .where(IngestJob.id == uuid.UUID(job_id))
                .values(status="complete", completed_at=datetime.now(timezone.utc))
            )
            await other.commit()
        return await real_check(*args, **kwargs)

    monkeypatch.setattr(
        jobs_router, "_can_access_another_users_job", _settle_it_mid_request
    )

    status_resp = await client.get(f"/jobs/{job_id}", headers=other_admin_headers)
    assert status_resp.status_code == 200, status_resp.text

    # Non-vacuity: the competing commit really did land inside the request, so
    # the poll's fenced UPDATE really did match zero rows.
    assert raced["n"] == 1, "the race was never driven"
    job = await _load_job(test_db_session, job_id)
    assert job.status == "complete", "the poll's UPDATE overwrote the winner"

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert not any(e["details"].get("error_code") == "worker_lost" for e in terminal), (
        f"the poll recorded a loss for a job that had completed: {terminal}"
    )


@pytest.mark.anyio
async def test_a_partly_failed_run_reports_its_rejected_records(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """`complete` is not the whole story when records were rejected.

    The synchronous endpoint returned counts the panel warned from. The queued
    one has to carry the same fact on the job status, or a force regenerate
    that left coverage gaps — gaps whose old vectors it already deleted —
    reports to the operator as done.
    """

    async def _mostly_worked(session, *, force=False, should_continue=None):
        return {"processed": 10, "created": 9, "skipped": 0, "errors": 1}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _mostly_worked)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]
    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    status_resp = await client.get(f"/jobs/{job_id}", headers=admin_auth_header)
    assert status_resp.status_code == 200, status_resp.text
    payload = status_resp.json()
    assert payload["status"] == "complete"
    assert payload["rows_processed"] == 10
    assert payload["rows_failed"] == 1, (
        "the run's rejected records are invisible to whoever is watching it"
    )


@pytest.mark.anyio
async def test_a_clean_run_reports_no_rejected_records(
    client: AsyncClient,
    admin_auth_header: dict,
    monkeypatch,
):
    """The counterpart, so `rows_failed` distinguishes rather than always warns."""

    async def _clean(session, *, force=False, should_continue=None):
        return {"processed": 4, "created": 4, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _clean)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]
    await run_embedding_backfill(**mock_defer.await_args.kwargs)

    payload = (await client.get(f"/jobs/{job_id}", headers=admin_auth_header)).json()
    assert payload["status"] == "complete"
    assert payload["rows_failed"] == 0


@pytest.mark.anyio
async def test_one_run_gets_one_terminal_entry_whoever_writes_it_first(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """Three actors can close a run's trail; only the first one does.

    A poll that expires a still-live worker's lease records `worker_lost`. The
    worker then returns, loses its fenced finalize, and would record
    `unresolved` — two terminal entries for one operation, with conflicting
    outcomes. Idempotency rather than each actor checking the other two.
    """

    async def _settled_from_under_it(session, *, force=False, should_continue=None):
        # The poll expires the lease while the provider call is still going.
        from app.core.db import async_session

        async with async_session() as other:
            expired = datetime.now(timezone.utc) - timedelta(hours=3)
            await other.execute(
                update(IngestJob)
                .where(IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY))
                .where(IngestJob.status == "running")
                .values(started_at=expired, heartbeat_at=expired)
            )
            await other.commit()
        return {"processed": 2, "created": 2, "skipped": 0, "errors": 0}

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _settled_from_under_it)

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]
    kwargs = mock_defer.await_args.kwargs

    # The worker starts, backdates its own lease mid-run, and a poll settles it
    # before the worker gets to its terminal write.
    import asyncio as _asyncio

    worker = _asyncio.create_task(run_embedding_backfill(**kwargs))
    await _asyncio.sleep(0.2)
    poll = await client.get(f"/jobs/{job_id}", headers=admin_auth_header)
    assert poll.status_code == 200
    await worker

    job = await _load_job(test_db_session, job_id)
    # Non-vacuity: both actors genuinely had something to say about this run.
    assert job.status in ("failed", "complete"), job.status

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, (
        f"one operation ended up with {len(terminal)} terminal entries: {terminal}"
    )


# ---------------------------------------------------------------------------
# `pending` has a terminal path from every actor (#1550 review, final)
# ---------------------------------------------------------------------------
#
# Every recovery path here was built around `running`: the fence matches
# running, the heartbeat covers running, the sweeper expires running. A job
# that never got there was invisible to all of it — and the unique index counts
# pending and running alike, so a stuck pending row blocks every future
# backfill just as effectively.


@pytest.mark.anyio
async def test_a_lost_claim_commit_does_not_strand_the_run_in_pending(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The claim's commit is cancelled before it applies; the row stays pending.

    Recovery observes a live row and owes it a terminal state — but `_finalize`
    is fenced on `running`, so it matched nothing and left the row holding the
    slot while recording `unresolved`. It now terminalizes from whatever state
    it observes.
    """
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    async def _claim_is_cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        backfill_jobs, "claim_job_attempt_and_start_heartbeat", _claim_is_cancelled
    )

    with patch.object(
        admin_router, "defer_async_with_tenant", AsyncMock()
    ) as mock_defer:
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    job_id = resp.json()["job_id"]

    before = await _load_job(test_db_session, job_id)
    # Non-vacuity: the run really is in the state the old fence could not see.
    assert before.status == "pending"

    with pytest.raises(asyncio.CancelledError):
        await run_embedding_backfill(**mock_defer.await_args.kwargs)

    job = await _load_job(test_db_session, job_id)
    assert job.status == "failed", (
        "the run is stranded in `pending`, holding the unique backfill slot"
    )

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal

    # And the slot is genuinely free.
    monkeypatch.setattr(
        backfill_jobs,
        "claim_job_attempt_and_start_heartbeat",
        backfill_jobs.claim_job_attempt_and_start_heartbeat,
    )
    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        again = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert again.status_code == 200, again.text


@pytest.mark.anyio
async def test_a_cancelled_dispatch_does_not_leave_the_slot_held(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """Cancelled while dispatching: committed row, no worker coming for it.

    `defer_with_orphan_guard` catches `Exception`, so the cancellation walks
    past it and past the route's `DeferFailed` handler. The row stays
    `pending` — and the unique index counts pending, so every later backfill is
    refused against a run that will never happen.
    """
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    async def _cancelled_mid_dispatch(_task, /, **kwargs):
        raise asyncio.CancelledError()

    with patch.object(
        admin_router,
        "defer_async_with_tenant",
        AsyncMock(side_effect=_cancelled_mid_dispatch),
    ):
        # httpx's ASGI transport re-wraps a cancellation as
        # RuntimeError("No response returned."), so the type here belongs to
        # the transport rather than to the handler. What matters is that the
        # request did not return a response — the cancellation propagated.
        raised: BaseException | None = None
        try:
            await client.post(_FORCE_URL, headers=admin_auth_header)
        except BaseException as exc:  # noqa: BLE001 - see comment above
            raised = exc
        assert raised is not None, "the cancellation did not propagate"

    stranded = (
        (
            await test_db_session.execute(
                select(IngestJob)
                .where(IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY))
                .order_by(IngestJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    assert stranded is not None
    assert stranded.status == "failed", (
        "the undispatched run is holding the unique backfill slot"
    )

    terminal = await _terminal_audit_entries(
        client, admin_auth_header, str(stranded.id)
    )
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["error_code"] == "dispatch_cancelled"

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        again = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert again.status_code == 200, again.text


async def _latest_backfill_row(session: AsyncSession) -> IngestJob:
    session.expire_all()
    job = (
        (
            await session.execute(
                select(IngestJob)
                .where(IngestJob.user_metadata.has_key(EMBEDDING_BACKFILL_METADATA_KEY))
                .order_by(IngestJob.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    assert job is not None
    return job


@pytest.mark.anyio
async def test_a_lost_ack_on_the_dispatch_settle_still_closes_the_trail(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The write lands; the caller never hears that it did — at the OTHER end.

    `_recover_unsettled` covers this class at the end of a run. The dispatch end
    had the same shape and no recovery: `settle_undispatched_run` failed the
    pending row, committed, and decided from the statement's own rowcount
    whether it owed a terminal entry. Losing that acknowledgement is the
    ORDINARY case here rather than the exotic one, because this code only runs
    under the cancellation that triggered it — and the row it leaves behind is
    `failed`, which every sweeper skips because it is terminal. So nothing
    emitted the entry and nothing ever would: the trail keeps `requested` as its
    last word over a job the database records as failed.
    """
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    real_fail = backfill_jobs._fail_undispatched_pending_row
    calls = {"n": 0}

    async def _commits_then_loses_the_answer(job_uuid):
        calls["n"] += 1
        await real_fail(job_uuid)  # the row really does become `failed`...
        raise asyncio.CancelledError()  # ...and the caller never learns it

    monkeypatch.setattr(
        backfill_jobs, "_fail_undispatched_pending_row", _commits_then_loses_the_answer
    )

    async def _cancelled_mid_dispatch(_task, /, **kwargs):
        raise asyncio.CancelledError()

    with patch.object(
        admin_router,
        "defer_async_with_tenant",
        AsyncMock(side_effect=_cancelled_mid_dispatch),
    ):
        # Same transport note as the test above: httpx re-wraps a cancellation,
        # so what matters is that no response came back.
        raised: BaseException | None = None
        try:
            await client.post(_FORCE_URL, headers=admin_auth_header)
        except BaseException as exc:  # noqa: BLE001 - see comment above
            raised = exc
        assert raised is not None, "the cancellation did not propagate"

    # Non-vacuity: the settle ran and its answer was genuinely lost.
    assert calls["n"] == 1, "the dispatch settle never ran — nothing lost an answer"

    stranded = await _latest_backfill_row(test_db_session)
    assert stranded.status == "failed", (
        "the undispatched run never reached a terminal row"
    )
    assert stranded.error_message == backfill_jobs.UNDISPATCHED_RUN_MESSAGE

    terminal = await _terminal_audit_entries(
        client, admin_auth_header, str(stranded.id)
    )
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["error_code"] == "dispatch_cancelled"


@pytest.mark.anyio
async def test_a_dispatch_settle_that_lost_its_answer_and_its_write_audits_nothing(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """The counterfactual: the same lost answer over a write that never landed.

    Reading the row is only right if it discriminates. A settle whose write was
    fenced out — a worker picked the delivery up after all, so the row is no
    longer `pending` — must record nothing, exactly as it does when the answer
    comes back as zero rows. Otherwise the recovery above would just be an
    unconditional "audit it anyway" wearing a read.
    """
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())

    calls = {"n": 0}

    async def _the_worker_took_it_first(job_uuid):
        # The fenced UPDATE matches nothing because the row is already running,
        # and then the answer is lost as well.
        calls["n"] += 1
        from app.core.db import async_session

        async with async_session() as other:
            await other.execute(
                update(IngestJob)
                .where(IngestJob.id == job_uuid)
                .values(status="running", heartbeat_at=datetime.now(timezone.utc))
            )
            await other.commit()
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        backfill_jobs, "_fail_undispatched_pending_row", _the_worker_took_it_first
    )

    async def _cancelled_mid_dispatch(_task, /, **kwargs):
        raise asyncio.CancelledError()

    with patch.object(
        admin_router,
        "defer_async_with_tenant",
        AsyncMock(side_effect=_cancelled_mid_dispatch),
    ):
        raised: BaseException | None = None
        try:
            await client.post(_FORCE_URL, headers=admin_auth_header)
        except BaseException as exc:  # noqa: BLE001 - transport re-wrap
            raised = exc
        assert raised is not None, "the cancellation did not propagate"

    assert calls["n"] == 1, "the dispatch settle never ran"
    live = await _latest_backfill_row(test_db_session)
    # Non-vacuity: the row really is owned by somebody else now.
    assert live.status == "running"

    terminal = await _terminal_audit_entries(client, admin_auth_header, str(live.id))
    assert terminal == [], f"the settle claimed a run it did not settle: {terminal}"


@pytest.mark.anyio
async def test_a_lost_ack_does_not_claim_a_failure_another_actor_wrote(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """Read the row for evidence of YOUR write, not for the state you'd produce.

    The dispatch DID land. A worker claimed the job, the backfill failed, and
    `_finalize` committed `failed` — and only then was the request cancelled.
    The settle's fenced update matches nothing, because the row is no longer
    `pending`, and its acknowledgement is lost as well. A status-only read then
    calls the worker's failure this cleanup's write and records
    `dispatch_cancelled`, which says the run never started and nothing was
    deleted, over a force regenerate that ran and failed after deleting every
    vector.

    Terminal entries are unique per job id, so that entry does not merely sit
    alongside the truth. It evicts it: the worker's real `backfill_failed` is
    refused by the index and swallowed. The last two assertions are that
    eviction, driven rather than reasoned about — the worker's own entry is
    held until after the cleanup has had its chance, which is exactly the
    window between `_finalize`'s commit and `_emit_terminal_audit`.
    """

    async def _provider_is_down(session, *, force=False, should_continue=None):
        raise RuntimeError("provider down")

    monkeypatch.setattr(backfill_module, "backfill_embeddings", _provider_is_down)

    real_terminal_audit = backfill_jobs._emit_terminal_audit
    held: dict = {}

    async def _hold_the_workers_terminal_audit(**kwargs):
        # First call is the worker's. Its row write has committed; its own
        # entry has not landed yet, which is the live window.
        if not held:
            held.update(kwargs)
            return
        await real_terminal_audit(**kwargs)

    monkeypatch.setattr(
        backfill_jobs, "_emit_terminal_audit", _hold_the_workers_terminal_audit
    )

    settles = {"n": 0}
    real_fail = backfill_jobs._fail_undispatched_pending_row

    async def _matches_nothing_then_loses_the_answer(job_uuid):
        settles["n"] += 1
        applied = await real_fail(job_uuid)
        assert applied is False, "the row was still pending — wrong arrangement"
        raise asyncio.CancelledError()

    monkeypatch.setattr(
        backfill_jobs,
        "_fail_undispatched_pending_row",
        _matches_nothing_then_loses_the_answer,
    )

    async def _worker_finalizes_it_then_the_request_is_cancelled(_task, /, **kwargs):
        # The delivery genuinely reached a worker, which claimed the job and
        # committed `failed`. Only then does the request die.
        await run_embedding_backfill(**kwargs)
        raise asyncio.CancelledError()

    with patch.object(
        admin_router,
        "defer_async_with_tenant",
        AsyncMock(side_effect=_worker_finalizes_it_then_the_request_is_cancelled),
    ):
        raised: BaseException | None = None
        try:
            await client.post(_FORCE_URL, headers=admin_auth_header)
        except BaseException as exc:  # noqa: BLE001 - transport re-wrap
            raised = exc
        assert raised is not None, "the cancellation did not propagate"

    settled = await _latest_backfill_row(test_db_session)
    job_id = str(settled.id)
    # Non-vacuity: the row is terminal, and it is the WORKER's terminal write —
    # the same status this cleanup's write would have produced, under a
    # different message.
    assert settled.status == "failed"
    assert settled.error_message == backfill_jobs.BACKFILL_FAILED_MESSAGE
    assert settles["n"] == 1, "the dispatch settle never ran"
    assert held, "the worker never reached its terminal audit"

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert not any(
        e["details"].get("error_code") == "dispatch_cancelled" for e in terminal
    ), f"the cleanup claimed a failure the worker wrote: {terminal}"

    # The worker's held entry now lands, which it cannot do if the cleanup took
    # the one terminal slot for this run.
    await real_terminal_audit(**held)
    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["error_code"] == "backfill_failed", (
        f"the run's real outcome was evicted by the dispatch cleanup: {terminal}"
    )


# ---------------------------------------------------------------------------
# The fourth actor: the worker's own startup recovery (#1556)
# ---------------------------------------------------------------------------
#
# `fail_stale_jobs`, the status poll and the worker's exits were taught to close
# the trail. `recover_stale_jobs` — the pass a restarting worker runs before it
# accepts a single delivery — settles the same rows with the same predicates and
# was not. It is also the pass that actually reaches a hard-killed run: a worker
# that dies is usually back in seconds, and once its startup pass has made the
# row terminal no later sweep will look at that row again.


@pytest.mark.anyio
@pytest.mark.parametrize(
    "job_status,error_code",
    [("running", "worker_lost"), ("pending", "never_started")],
)
async def test_the_worker_startup_recovery_closes_the_trail_it_settles(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    job_status: str,
    error_code: str,
):
    """A hard kill's recovery is the restarted worker's, not the 5-minute sweep.

    Both settle the row; only one of them was closing the trail. Whichever gets
    there first is the last actor the run will ever have, because a terminal row
    drops out of every other sweep's predicate — so the trail sits at
    `requested` forever, over a force run that may have deleted every vector.
    """
    from app.platform.jobs.worker import recover_stale_jobs

    upload = await _stale_job(test_db_session, status=job_status, backfill=False)
    backfill = await _stale_job(test_db_session, status=job_status, backfill=True)
    upload_id, backfill_id = str(upload.id), str(backfill.id)

    assert (
        await _terminal_audit_entries(client, admin_auth_header, backfill_id) == []
    ), "the run already had a terminal entry before the recovery — vacuous"

    await recover_stale_jobs()

    # Non-vacuity: the recovery genuinely settled both rows. If the advisory
    # lock was held elsewhere it skips the pass entirely, and this says so.
    assert (await _load_job(test_db_session, backfill_id)).status == "failed", (
        "the startup recovery did not settle the row — nothing to close a trail for"
    )
    assert (await _load_job(test_db_session, upload_id)).status == "failed"

    terminal = await _terminal_audit_entries(client, admin_auth_header, backfill_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["outcome"] == "failed"
    assert terminal[0]["details"]["error_code"] == error_code
    # The same discrimination the shared sweep owes: the ordinary upload
    # settled in the same pass gets no entry of any kind.
    assert await _audit_entries_naming(test_db_session, upload_id) == 0, (
        "the startup recovery wrote an audit entry for an ordinary upload"
    )
