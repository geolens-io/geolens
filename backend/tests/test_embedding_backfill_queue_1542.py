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
from app.platform.jobs.models import EMBEDDING_BACKFILL_METADATA_KEY, IngestJob
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
async def test_a_dead_workers_run_stops_holding_the_slot_after_its_lease(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    monkeypatch,
):
    """A worker that died mid-run must not lock the operator out forever."""
    monkeypatch.setattr(backfill_module, "backfill_embeddings", AsyncMock())
    stale = await _in_flight_job(test_db_session)
    expired = datetime.now(timezone.utc) - timedelta(
        seconds=backfill_jobs._lease_seconds() + 60
    )
    stale.started_at = expired
    stale.heartbeat_at = expired
    await test_db_session.commit()

    with patch.object(admin_router, "defer_async_with_tenant", AsyncMock()):
        resp = await client.post(_FORCE_URL, headers=admin_auth_header)
    assert resp.status_code == 200, resp.text


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
