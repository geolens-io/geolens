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

    async def _should_not_run(session, *, force=False):
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

    async def _slow_backfill(session, *, force=False):
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

    async def _fake_backfill(session, *, force=False):
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

    async def _destructive_backfill(session, *, force=False):
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

    async def _explode(session, *, force=False):
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

    async def _backfill_then_lose_the_lease(session, *, force=False):
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

    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    details = terminal[0]["details"]
    assert details["outcome"] != "completed", (
        "the audit claims a completion the job row does not support"
    )
    assert details["outcome"] == backfill_jobs.UNRESOLVED_OUTCOME
    assert details["error_code"] == "finalize_lost_attempt"
    # The work did finish, and the record says so without claiming the row.
    assert details["intended_outcome"] == "completed"


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

    async def _should_not_run(session, *, force=False):
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
    terminal = await _terminal_audit_entries(client, admin_auth_header, job_id)
    assert len(terminal) == 1, terminal
    assert terminal[0]["details"]["outcome"] == backfill_jobs.UNRESOLVED_OUTCOME
    assert terminal[0]["details"]["error_code"] == "attempt_not_owned"


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

    async def _ok(session, *, force=False):
        return {"processed": 2, "created": 2, "skipped": 0, "errors": 0}

    async def _boom(session, *, force=False):
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

    async def _destructive_backfill(session, *, force=False):
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

    async def _cancelled_mid_run(session, *, force=False):
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

    async def _every_record_failed(session, *, force=False):
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

    async def _mostly_worked(session, *, force=False):
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
