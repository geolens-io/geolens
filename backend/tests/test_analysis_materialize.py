"""Tests for async analysis materialization (M4).

Covers the materialize endpoint (job creation, auth, validation) and the
worker's core logic (`_materialize`) run directly against the test DB.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import asyncio
import math
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from geoalchemy2 import WKTElement
from httpx import AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

import app.core.db as core_db
from app.core.geo import extent_to_bbox
from app.modules.catalog.datasets.api import router_analysis
from app.platform.analysis_sql import MAX_BUFFER_METERS
from app.platform.jobs.models import IngestJob
from app.processing.analysis.tasks import (
    materialize_timeout,
    _complete_job_for_attempt,
    _materialize_work_mem,
    _enforce_output_size,
    _fail_cancelled_job,
    _mark_job_failed,
    _materialize,
    _user_error_message,
)

from tests.conftest import _create_test_user
from tests.factories import create_dataset, get_user_id
from tests.test_analysis_preview import (
    _create_empty_dataset,
    _create_mask_dataset,
    _create_point_dataset_at,
    _create_polygon_dataset,
    _create_raster_dataset,
    _create_wkt_dataset,
)
from tests.test_export_hardening import (
    _DEFAULT_PERMISSION_MATRIX,
    _put_permission_matrix,
    _reset_permission_matrix,
)


def _materialize_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/materialize/"


async def _create_job(session: AsyncSession, user_id: uuid.UUID) -> IngestJob:
    job = IngestJob(
        source_filename="analysis-test",
        created_by=user_id,
        status="pending",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def _create_other_user_id(client: AsyncClient, admin_headers: dict) -> uuid.UUID:
    """A second user in the same tenant, for the tenant-cap tests."""
    _headers, user_id = await _create_test_user(client, admin_headers, "viewer")
    return uuid.UUID(user_id)


async def _fill_tenant_analysis_slots(
    session: AsyncSession, user_id: uuid.UUID, target: int
) -> list[IngestJob]:
    """Top the tenant's active-analysis count up to ``target``.

    Counts what is already active rather than assuming zero: the worker
    database is shared across this file's tests, and a sibling that left a job
    behind would otherwise make these pass or fail for the wrong reason.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import and_, func, or_

    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=router_analysis.MATERIALIZE_LEASE_SECONDS
    )
    existing = await session.scalar(
        select(func.count())
        .select_from(IngestJob)
        .where(
            IngestJob.user_metadata.has_key("analysis"),
            or_(
                IngestJob.status == "pending",
                and_(
                    IngestJob.status == "running",
                    func.coalesce(IngestJob.heartbeat_at, IngestJob.started_at)
                    >= cutoff,
                ),
            ),
        )
    )
    created: list[IngestJob] = []
    for _ in range(max(0, target - (existing or 0))):
        job = await _create_job(session, user_id)
        job.user_metadata = {"analysis": {"operation": "buffer"}}
        created.append(job)
    await session.commit()
    return created


async def _release_jobs(session: AsyncSession, jobs: list[IngestJob]) -> None:
    for job in jobs:
        job.status = "failed"
    await session.commit()


# The two statuses the materialize endpoint's per-user cap counts.
_SLOT_HOLDING_STATUSES = ("pending", "running")


@pytest.fixture(scope="module")
def _slot_cleanup_engine():
    """A synchronous engine for the teardown below — see its docstring for why.

    Module-scoped so construction is paid once; NullPool because it wants one
    statement at a time and idle connections are the scarce resource in this
    suite. The URL is read lazily, after conftest has stamped the per-xdist
    worker database name onto settings.
    """
    from sqlalchemy import create_engine

    from app.core.config import settings

    engine = create_engine(settings.test_database_url_sync, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _release_analysis_job_slots(request, _slot_cleanup_engine):
    """fix(#789): fail whatever analysis jobs a test leaves behind.

    The materialize endpoint admits one non-terminal analysis job per user, and
    the tests here share a database, so a test that enqueues a job and leaves it
    pending 429s whatever runs next — under `pytest -n 4`, some unrelated
    victim in another file. Releasing the slot by hand at the end of each test
    worked right up until someone forgot, which is why this is autouse rather
    than opt-in: forgetting is the whole failure mode.

    Analysis jobs only, keyed on the same ``user_metadata`` marker the endpoint
    counts, so an upload job a test is still asserting on is left alone. Not
    scoped to one user: the cap is per user but the tests here run as admin,
    editor and viewer, and no test wants another user's leftovers to survive.

    SYNCHRONOUS, and deliberately not routed through ``test_db_session``. An
    autouse ASYNC fixture applies to every test in the module and pytest
    refuses to hand one to a sync test, so the moment any session adds a plain
    ``def`` test here it errors at setup — and takes the rest of the file with
    it, because a failed fixture corrupts pytest's finalizer state. That is not
    hypothetical: it is what this did in an integration batch beside two sync
    tests from another PR. A per-class override patches one occurrence and
    loses to the next, so the fixture must not care what shape the tests are.
    Owning its connection also makes teardown ordering irrelevant, which the
    async version got wrong in the other direction.
    """
    yield
    # A test that never took a client cannot have enqueued anything, so there
    # is nothing to release and no reason to spend a connection.
    if not {"client", "test_db_session"} & set(request.fixturenames):
        return
    with _slot_cleanup_engine.begin() as conn:
        conn.execute(
            update(IngestJob)
            .where(
                IngestJob.user_metadata.has_key("analysis"),
                IngestJob.status.in_(_SLOT_HOLDING_STATUSES),
            )
            .values(status="failed")
        )


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestMaterializeEndpoint:
    async def test_materialize_returns_job(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # Patch only the queue hop — job creation, auth, and quota stay real.
        with patch.object(
            router_analysis, "defer_async_with_tenant", AsyncMock()
        ) as mock_defer:
            resp = await client.post(
                _materialize_url(ds.id),
                json={
                    "operation": "buffer",
                    "distance_meters": 100,
                    "title": f"Buffered {uuid.uuid4().hex[:6]}",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending"
        mock_defer.assert_awaited_once()
        kwargs = mock_defer.await_args.kwargs
        assert kwargs["operation"] == "buffer"
        assert kwargs["dataset_id"] == str(ds.id)
        # fix(#695): queue names don't rank in Procrastinate — the analysis
        # defer must carry a below-default per-job priority (still on the
        # shared "ingest" queue) so queued uploads always fetch first.
        deferrer = mock_defer.await_args.args[0]
        assert deferrer.job.priority == router_analysis.ANALYSIS_JOB_PRIORITY
        assert deferrer.job.priority < 0
        assert deferrer.job.queue == "ingest"
        job = await test_db_session.get(IngestJob, uuid.UUID(data["job_id"]))
        assert job is not None
        assert job.status == "pending"
        # fix(#789): the enqueue stamps a step (ux(#698)) so a pending job reads
        # as "queued" rather than as a broken one. Load-bearing since #703 put
        # analysis below the default priority: a queued job now waits behind
        # uploads by design, sometimes for minutes, and this stamp is the only
        # honest "waiting" signal the UI has to distinguish that from a stall.
        assert job.current_step == "queued"
        # Request params ride the job row so Admin → Jobs can diagnose runs.
        meta = (job.user_metadata or {}).get("analysis", {})
        assert meta["operation"] == "buffer"
        assert meta["distance_meters"] == 100
        assert meta["source_dataset_id"] == str(ds.id)
        assert "mask" not in meta

    async def test_second_materialize_while_active_is_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """One materialize per user at a time: a second request while a job is
        still pending/running 429s instead of stacking CTAS work; a finished
        job releases the slot."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            first = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "First"},
                headers=admin_auth_header,
            )
            assert first.status_code == 200, first.text
            second = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Second"},
                headers=admin_auth_header,
            )
            assert second.status_code == 429
            job = await test_db_session.get(
                IngestJob, uuid.UUID(first.json()["job_id"])
            )
            job.status = "failed"
            await test_db_session.commit()
            third = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Third"},
                headers=admin_auth_header,
            )
            assert third.status_code == 200, third.text

    async def test_upload_named_like_an_analysis_job_does_not_block(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#682 review): the active-job check keys on the analysis marker
        in user_metadata, not source_filename — that column holds the user's
        own upload filename, so uploading "analysis-data.geojson" must not
        lock them out of analysis."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        upload = await _create_job(test_db_session, admin_id)
        upload.source_filename = "analysis-data.geojson"
        upload.status = "running"
        upload.user_metadata = None
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Not blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        upload.status = "failed"
        await test_db_session.commit()

    async def test_tenant_cap_refuses_a_second_user_and_names_itself(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1015): the per-user cap let a tenant with N users hold N active
        CTASes. A tenant ceiling sits above it, and its 429 has to say which
        cap was hit — the per-user message would be a lie here, since this
        user has nothing running.

        The filler jobs are left `pending`, which also covers the status-only
        branch of the shared predicate: a pending job has never been claimed,
        so heartbeat_at and started_at are both NULL and any cutoff comparison
        would silently drop it from the count.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        other_id = await _create_other_user_id(client, admin_auth_header)
        filler = await _fill_tenant_analysis_slots(
            test_db_session,
            other_id,
            router_analysis.MAX_ACTIVE_MATERIALIZES_PER_TENANT,
        )

        try:
            with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
                resp = await client.post(
                    _materialize_url(ds.id),
                    json={"operation": "centroid", "title": "Over tenant cap"},
                    headers=admin_auth_header,
                )
            # If the cap ever regresses this request succeeds, and the job it
            # creates would hold THIS user's slot for every sibling test in the
            # shared worker database — the #933 failure mode. Release it before
            # asserting.
            if resp.status_code == 200:
                leaked = await test_db_session.get(
                    IngestJob, uuid.UUID(resp.json()["job_id"])
                )
                leaked.status = "failed"
                await test_db_session.commit()
            assert resp.status_code == 429, resp.text
            detail = resp.json()["detail"]
            assert "organization" in detail, detail
            # Distinguishable from the per-user cap, which this user has not hit.
            assert "already running; wait for it to finish" not in detail, detail
        finally:
            await _release_jobs(test_db_session, filler)

    async def test_tenant_admission_takes_a_serializing_lock(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1015): admission is a reservation, not a check-then-insert.

        Without serialization, simultaneous callers in one tenant all read the
        same count below the ceiling and all create a job, so the tenant ends
        up over by however many arrived together — the unbounded concurrency
        the ceiling exists to stop, and what #1012's raised work_mem makes
        expensive.

        This asserts the MECHANISM rather than racing real requests. Under
        ASGITransport the interleaving is not controllable: a four-way race
        against the unfixed code reproduced the overshoot once in three runs,
        so an outcome assertion would pass while the bug was present, which is
        worse than no test. What is deterministic, and what the fix actually
        is, is that a transaction-scoped advisory lock is taken BEFORE either
        count runs.
        """
        executed: list[str] = []
        from sqlalchemy.ext.asyncio import AsyncSession as _AS

        real_execute = _AS.execute
        real_scalar = _AS.scalar

        async def spying_execute(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return await real_execute(self, statement, *args, **kwargs)

        # Both counts go through .scalar(), not .execute() — spying only the
        # latter would record the lock and none of what it is protecting.
        async def spying_scalar(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return await real_scalar(self, statement, *args, **kwargs)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            with (
                patch.object(_AS, "execute", spying_execute),
                patch.object(_AS, "scalar", spying_scalar),
            ):
                resp = await client.post(
                    _materialize_url(ds.id),
                    json={"operation": "centroid", "title": "Lock order"},
                    headers=admin_auth_header,
                )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        await test_db_session.commit()

        locks = [s for s in executed if "pg_advisory_xact_lock" in s]
        assert len(locks) == 1, f"expected one admission lock, got {locks}"
        # xact-scoped, so it is held until this request commits and therefore
        # spans the count AND the insert. A session-level lock would be
        # released too early and a `try` variant would fail instead of queueing.
        assert "pg_try_advisory_xact_lock" not in locks[0], locks[0]

        counts = [
            i
            for i, stmt in enumerate(executed)
            if "count" in stmt.lower() and "ingest_jobs" in stmt
        ]
        assert counts, "neither admission count ran"
        assert executed.index(locks[0]) < counts[0], (
            "the admission lock is taken after the count — the count is still a "
            "snapshot another caller can have invalidated"
        )

    async def test_tenant_cap_stale_lease_releases_a_slot(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1015): the tenant cap shares the heartbeat lease rather than
        inventing a liveness rule, so a hard-killed worker (SIGKILL/OOM) gives
        its slot back here too instead of holding the whole tenant out until
        the 60-minute JOB_TIMEOUT_SECONDS backstop."""
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        other_id = await _create_other_user_id(client, admin_auth_header)
        filler = await _fill_tenant_analysis_slots(
            test_db_session,
            other_id,
            router_analysis.MAX_ACTIVE_MATERIALIZES_PER_TENANT,
        )
        dead = filler[-1]
        dead.status = "running"
        dead.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        dead.started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        dead.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await test_db_session.commit()

        admitted_id = None
        try:
            with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
                resp = await client.post(
                    _materialize_url(ds.id),
                    json={"operation": "centroid", "title": "Past dead worker"},
                    headers=admin_auth_header,
                )
            assert resp.status_code == 200, resp.text
            admitted_id = uuid.UUID(resp.json()["job_id"])
        finally:
            await _release_jobs(test_db_session, filler)
            if admitted_id is not None:
                admitted = await test_db_session.get(IngestJob, admitted_id)
                admitted.status = "failed"
                await test_db_session.commit()

    async def test_old_pending_job_still_blocks(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A pending job is queued work that will still run, so a backlogged
        ingest queue must not let a second CTAS through however old it is."""
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        backlogged = await _create_job(test_db_session, admin_id)
        backlogged.user_metadata = {"analysis": {"operation": "buffer"}}
        backlogged.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Should be blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 429, resp.text
        backlogged.status = "failed"
        await test_db_session.commit()

    async def test_backlogged_job_that_just_started_still_blocks(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A job that waited out a queue backlog and only just began is fully
        active, so enqueue age must not exclude it from the cap."""
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        backlogged = await _create_job(test_db_session, admin_id)
        backlogged.user_metadata = {"analysis": {"operation": "buffer"}}
        backlogged.status = "running"
        backlogged.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        backlogged.started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Should be blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 429, resp.text
        backlogged.status = "failed"
        await test_db_session.commit()

    async def test_long_running_job_with_fresh_heartbeat_still_blocks(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#691): elapsed time is NOT a liveness signal — a 45-minute job
        whose worker is still renewing its heartbeat keeps the slot.

        The 300s statement_timeout bounds each statement, not the job — a
        materialize runs a CTAS, a DELETE, an EXISTS probe, two ALTERs, a
        primary key, add_4326_column and registration in sequence, so a
        legitimate run over a large dataset can outlive any elapsed-time
        window (fix(#682 review)). The lease keys on heartbeat freshness
        instead.
        """
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        long_running = await _create_job(test_db_session, admin_id)
        long_running.status = "running"
        long_running.user_metadata = {"analysis": {"operation": "buffer"}}
        long_running.started_at = datetime.now(timezone.utc) - timedelta(minutes=45)
        long_running.created_at = datetime.now(timezone.utc) - timedelta(minutes=45)
        long_running.heartbeat_at = datetime.now(timezone.utc)
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Should be blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 429, resp.text
        long_running.status = "failed"
        await test_db_session.commit()

    async def test_stale_heartbeat_releases_the_slot(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#691): a running job whose lease went stale is a hard-killed
        worker (SIGKILL/OOM between heartbeat renewal and the sweep). The
        next materialize must be admitted immediately rather than waiting
        the 60-minute JOB_TIMEOUT_SECONDS backstop."""
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        dead = await _create_job(test_db_session, admin_id)
        dead.status = "running"
        dead.user_metadata = {"analysis": {"operation": "buffer"}}
        dead.created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        dead.started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        dead.heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Admitted past dead worker"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        new_job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        new_job.status = "failed"
        dead.status = "failed"
        await test_db_session.commit()

    async def test_null_heartbeat_with_fresh_started_at_still_blocks(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#691): the coalesce(heartbeat_at, started_at) leg — a running
        row with no heartbeat yet but a fresh started_at (the pre-migration
        row shape, or the instant between claim stamping the pair) must keep
        blocking rather than being dropped by a NULL comparison."""
        from datetime import datetime, timedelta, timezone

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        fresh = await _create_job(test_db_session, admin_id)
        fresh.status = "running"
        fresh.user_metadata = {"analysis": {"operation": "buffer"}}
        fresh.started_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        fresh.heartbeat_at = None
        await test_db_session.commit()

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Should be blocked"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 429, resp.text
        fresh.status = "failed"
        await test_db_session.commit()

    async def test_materialize_private_source_hidden(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Rule 1 on the source dataset. Editor (who HAS the upload
        permission) so the check exercised here is visibility, not the
        permission gate covered below."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "centroid", "title": "Nope"},
            headers=editor_auth_header,
        )
        assert resp.status_code == 404

    async def test_materialize_private_mask_hidden(
        self,
        client: AsyncClient,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """test(#761): Rule 1 applies to the MASK dataset on the write path
        too. The preview suite pins this; the materialize branch sits between
        two size gates that were each rewritten twice in two weeks (#693,
        #701) and had no test of its own."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        private_mask = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-1 -1, -1 1, 1 1, 1 -1, -1 -1))",
            visibility="private",
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={
                "operation": "clip",
                "mask_dataset_id": str(private_mask.id),
                "title": "Nope",
            },
            headers=editor_auth_header,
        )
        assert resp.status_code == 404

    async def test_materialize_requires_upload_permission(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#692): materialize creates a dataset, so it carries the same
        `upload` permission as every ingest endpoint that creates one — a
        viewer gets 403 even on a dataset they can read. Preview must stay
        open to viewers: read-only, nothing persisted, and the chat tool's
        read-only surface depends on it."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "centroid", "title": "Not allowed"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 403
        preview = await client.post(
            f"/datasets/{ds.id}/analysis/preview/",
            json={"operation": "centroid"},
            headers=viewer_auth_header,
        )
        assert preview.status_code == 200, preview.text

    async def test_materialize_requires_export_permission(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Materialize hands the caller an owned dataset carrying the
        source's attributes — the outcome the download endpoints gate on
        `export` — so the two paths must agree under a customized role
        matrix: an editor whose export was revoked gets 403, not a job."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        revoked = {
            **_DEFAULT_PERMISSION_MATRIX,
            "editor": {**_DEFAULT_PERMISSION_MATRIX["editor"], "export": False},
        }
        try:
            await _put_permission_matrix(client, admin_auth_header, revoked)
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Not allowed"},
                headers=editor_auth_header,
            )
            assert resp.status_code == 403, resp.text
            assert "export" in resp.json()["detail"].lower()
        finally:
            await _reset_permission_matrix(client, admin_auth_header)

    async def test_dissolve_unknown_column_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _materialize_url(ds.id),
            json={
                "operation": "dissolve",
                "by_field": "no_such_col",
                "title": "Dissolved",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_dissolve_json_column_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#766): PG has no equality operator for `json` (GDAL maps
        nested GeoJSON objects to it), so the CTAS GROUP BY would burn the
        queue wait and the per-user job slot on an opaque 42883. Reject at
        enqueue, naming the column."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="POLYGON",
            feature_count=2,
            column_info=[
                {"name": "props", "type": "json"},
                {"name": "name", "type": "text"},
            ],
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "dissolve", "by_field": "props", "title": "Grouped"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "props" in detail
        assert "group" in detail.lower()

    async def test_materialize_requires_title(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_by_field_source_count_conflict_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A real source column named source_count would collide with the
        generated output column and fail the CTAS with an opaque error."""
        admin_id = await get_user_id(test_db_session, "admin")
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="POLYGON",
            column_info=[{"name": "source_count", "type": "integer"}],
        )
        resp = await client.post(
            _materialize_url(ds.id),
            json={
                "operation": "dissolve",
                "by_field": "source_count",
                "title": "Conflict",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "source_count" in resp.json()["detail"]

    async def test_centroid_ignores_stray_distance(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Materialize mirrors the preview schema: distance is buffer-only."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={
                    "operation": "centroid",
                    "distance_meters": 999_999,
                    "title": "Centroids",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text

    async def test_source_size_gates_dissolve_and_buffer(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#694): dissolve/buffer are size-gated at enqueue on the cached
        feature_count — dissolve's ST_Union can OOM the shared db container,
        and buffer amplifies storage with no byte quota. Centroid is 1:1 and
        stays ungated."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)

        ds.feature_count = 250_001
        await test_db_session.commit()
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "dissolve", "title": "Too big"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "too large for dissolve" in resp.json()["detail"]

        # The boundary itself is allowed.
        ds.feature_count = 250_000
        await test_db_session.commit()
        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "dissolve", "title": "At the cap"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        await test_db_session.commit()

        # buffer's ceiling is higher but real; centroid has none.
        ds.feature_count = 500_001
        await test_db_session.commit()
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "buffer", "distance_meters": 10, "title": "Too big"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "too large for buffer" in resp.json()["detail"]

        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "Centroid ok"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        await test_db_session.commit()

    async def test_oversized_mask_layer_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#693): the shared mask loader caps the mask layer's cached
        feature_count — the whole layer is unioned before any row limit can
        bite — so materialize rejects it before creating a job."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
        )
        mask_ds.feature_count = 1_001
        await test_db_session.commit()

        resp = await client.post(
            _materialize_url(ds.id),
            json={
                "operation": "clip",
                "mask_dataset_id": str(mask_ds.id),
                "title": "Too many mask features",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "mask layer has too many features" in resp.json()["detail"].lower()

        # fix(#701 review): a NULL snapshot must not read as zero — the mask
        # table (1 row) is counted live against the patched cap.
        mask_ds.feature_count = None
        await test_db_session.commit()
        with patch.object(router_analysis, "MAX_MASK_LAYER_FEATURES", 0):
            resp = await client.post(
                _materialize_url(ds.id),
                json={
                    "operation": "clip",
                    "mask_dataset_id": str(mask_ds.id),
                    "title": "Unknown mask size",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 422
        assert "mask layer has too many features" in resp.json()["detail"].lower()

    async def test_null_feature_count_probes_live_table(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#701 review): a NULL feature_count (legacy imports,
        register_existing_table paths) must not read as zero — that admits
        exactly the unknown-size datasets the OOM gate exists for. The gate
        falls back to a LIMIT-bounded live count of the physical table."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        ds.feature_count = None
        await test_db_session.commit()

        # The fixture table holds 2 rows; a cap of 1 must reject via the
        # live probe...
        with patch.dict(
            "app.platform.analysis_sql.MAX_SOURCE_FEATURES", {"dissolve": 1}
        ):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "dissolve", "title": "Unknown size"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 422
        assert "too large for dissolve" in resp.json()["detail"]

        # ...and a cap above the true count enqueues.
        with (
            patch.dict(
                "app.platform.analysis_sql.MAX_SOURCE_FEATURES", {"dissolve": 5}
            ),
            patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()),
        ):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "dissolve", "title": "Small enough"},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        job = await test_db_session.get(IngestJob, uuid.UUID(resp.json()["job_id"]))
        job.status = "failed"
        await test_db_session.commit()


# ---------------------------------------------------------------------------
# Worker tests (core logic run inline, no queue)
# ---------------------------------------------------------------------------


class TestMaterializeWorker:
    async def test_buffer_materialize_creates_dataset(
        self,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Buffered {uuid.uuid4().hex[:6]}"

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="buffer",
            title=title,
            distance_meters=100,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        assert job.dataset_id is not None
        # fix(v1.6.0 audit B12): the terminal write must stamp completed_at —
        # without it the jobs UI renders '-' and retention ages on queue time.
        assert job.completed_at is not None
        # fix(#682 review): without started_at the row carries no liveness
        # signal, so the platform's stale-job sweep (which matches on
        # coalesce(heartbeat_at, started_at)) could never recover a crashed
        # analysis job.
        assert job.started_at is not None
        # ...and started_at ALONE would condemn a job that legitimately outlives
        # JOB_TIMEOUT_SECONDS, since the same coalesce would then read as stale
        # while the work is still running. The lease the worker takes is what
        # keeps a live job out of the sweep, so pin that it exists.
        assert job.attempt_id is not None
        assert job.heartbeat_at is not None

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        assert new_ds.feature_count == 2
        # Output table follows the geom/geom_4326 convention with rows intact.
        count = (
            await test_db_session.execute(
                text(
                    f"SELECT COUNT(*) FROM data.{new_ds.table_name} "  # noqa: S608
                    f"WHERE geom_4326 IS NOT NULL"
                )
            )
        ).scalar_one()
        assert count == 2
        # Attribute columns are carried through 1:1 ops.
        name_count = (
            await test_db_session.execute(
                text(
                    f"SELECT COUNT(*) FROM data.{new_ds.table_name} "  # noqa: S608
                    f"WHERE name IS NOT NULL"
                )
            )
        ).scalar_one()
        assert name_count == 2

    async def test_centroid_materialize_creates_dataset(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#789): centroid is this suite's cheap lifecycle op — every other
        occurrence of it is job-slot or permission scaffolding that never looks
        at what got written. Preview does assert the output geometry, which is
        what makes the write path easy to misread as covered. Mirrors the
        buffer test above.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Centroids {uuid.uuid4().hex[:6]}"

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title=title,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        assert job.dataset_id is not None

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        # Centroid is 1:1 — two source polygons in, two points out.
        assert new_ds.feature_count == 2
        assert (new_ds.geometry_type or "").upper() == "POINT"
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT name, ST_GeometryType(geom_4326) AS gtype, "  # noqa: S608
                    f"ST_X(geom_4326) AS x, ST_Y(geom_4326) AS y "
                    f"FROM data.{new_ds.table_name} ORDER BY name"
                )
            )
        ).all()
        # The source's attribute column rides along on a 1:1 op, one row each.
        assert [row.name for row in rows] == ["a", "b"]
        assert {row.gtype for row in rows} == {"ST_Point"}
        # Centroids of the unit square at the origin and of the 1x1 square at
        # (10, 10) — the values test_centroid_preview pins on the read path,
        # so preview and the saved dataset agree.
        assert (rows[0].x, rows[0].y) == pytest.approx((0.5, 0.5))
        assert (rows[1].x, rows[1].y) == pytest.approx((10.5, 10.5))

    async def test_non_identifier_columns_survive_materialize(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#763): GDAL launders only case/`-`/`#`, so ingested tables
        legitimately carry columns like `Área` or `2020_pop`; the old
        identifier-shaped filter silently dropped them from every analysis
        output."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # ":id" doubles as the codex-review case: text() parses `:name` as a
        # bind parameter even inside quoted identifiers, so an unescaped
        # Socrata-style column would fail the whole CTAS, not just drop out.
        await test_db_session.execute(
            text(
                f"ALTER TABLE data.{ds.table_name} "
                f'ADD COLUMN "Área" TEXT, ADD COLUMN "2020_pop" INTEGER, '
                f'ADD COLUMN "\\:id" TEXT'
            )
        )
        await test_db_session.execute(
            text(
                f"UPDATE data.{ds.table_name} "  # noqa: S608
                f'SET "Área" = \'norte\', "2020_pop" = 7, "\\:id" = \'r1\''
            )
        )
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="buffer",
            title=f"Buffered unicode {uuid.uuid4().hex[:6]}",
            distance_meters=100,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        rows = (
            await test_db_session.execute(
                text(
                    f'SELECT "Área", "2020_pop", "\\:id" '  # noqa: S608
                    f"FROM data.{new_ds.table_name}"
                )
            )
        ).all()
        assert len(rows) == 2
        assert all(tuple(row) == ("norte", 7, "r1") for row in rows)

    async def test_null_geometry_rows_are_dropped_from_output(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): the preview filters NULL/EMPTY results in SQL, so the
        saved dataset must agree — buffer of a NULL geometry is NULL and must
        not survive into the registered output."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            text(f"INSERT INTO data.{ds.table_name} (name) VALUES ('null-geom')")  # noqa: S608
        )
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="buffer",
            title=f"Buffered nulls {uuid.uuid4().hex[:6]}",
            distance_meters=100,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        total, nulls = (
            await test_db_session.execute(
                text(
                    f"SELECT COUNT(*), COUNT(*) FILTER (WHERE geom_4326 IS NULL) "  # noqa: S608
                    f"FROM data.{new_ds.table_name}"
                )
            )
        ).one()
        assert (total, nulls) == (2, 0)

    async def test_terminal_job_is_not_resurrected(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): the worker claims pending→running fenced on the attempt
        token. A job that already reached a terminal state — the pending
        sweeper failing a backlogged job, or the defer orphan-guard failing
        the row after the queue INSERT committed — must stay there; before
        the claim, a late delivery would flip it back to running and later
        'complete', defeating the per-user cap and creating a dataset for a
        job the user was told failed."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        job.status = "failed"
        job.error_message = "Stale: pending for over 1 hour (never queued)"
        await test_db_session.commit()

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title="Resurrected?",
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.dataset_id is None

    async def test_sweeper_failed_job_is_not_resurrected_at_completion(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#786): the terminal 'complete' write is fenced on the attempt
        token like the claim — if a stalled heartbeat lets the lease expire
        and the stale-job sweep fails the row mid-run, the worker must not
        overwrite failed → complete and hand the user a dataset for a job
        they were told failed. The fence shares the registration
        transaction, so the Dataset row rolls back with the miss, and the
        already-committed output table is dropped as a provable orphan."""
        import app.processing.ingest.service as ingest_service

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        real_register = ingest_service.register_existing_table
        out_tables: list[str] = []

        async def sweeping_register(session, request, user, **kwargs):
            # The sweep lands between the build commit and the terminal
            # write: fail the row out from under the worker on its own
            # session, exactly as the platform's stale-job sweep does.
            out_tables.append(request.table_name)
            async with core_db.async_session() as sweeper:
                await sweeper.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job.id)
                    .values(
                        status="failed",
                        error_message="Stale: heartbeat lease expired",
                    )
                )
                await sweeper.commit()
            return await real_register(session, request, user, **kwargs)

        with patch.object(ingest_service, "register_existing_table", sweeping_register):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=f"Superseded {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "Stale: heartbeat lease expired"
        assert job.dataset_id is None
        assert out_tables, "materialize never reached registration"

        from app.modules.catalog.datasets.domain.models import Dataset

        registered = (
            await test_db_session.execute(
                select(Dataset).where(Dataset.table_name == out_tables[0])
            )
        ).scalar_one_or_none()
        assert registered is None
        # ...and the committed output table was dropped, not leaked.
        leaked = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(
                    ref=f'data."{out_tables[0]}"'
                )
            )
        ).scalar_one()
        assert leaked is None

    async def test_sweeper_failed_job_error_is_not_overwritten(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#786): _mark_job_failed is fenced like _fail_cancelled_job —
        when another actor already moved the row to a terminal state, this
        worker's later failure must not clobber the message the user saw.
        fix(v1.6.0 audit B13): the failure path CAN now tell a swept row
        from a completed one — no dataset row adopted the table here, so it
        is a provable orphan and gets dropped instead of leaking forever."""
        import app.processing.ingest.service as ingest_service

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        out_tables: list[str] = []

        async def sweeping_register(session, request, user, **kwargs):
            out_tables.append(request.table_name)
            async with core_db.async_session() as sweeper:
                await sweeper.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job.id)
                    .values(
                        status="failed",
                        error_message="Stale: heartbeat lease expired",
                    )
                )
                await sweeper.commit()
            raise RuntimeError("boom after supersession")

        with patch.object(ingest_service, "register_existing_table", sweeping_register):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=f"Superseded fail {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "Stale: heartbeat lease expired"
        assert job.dataset_id is None
        assert out_tables, "materialize never reached registration"
        # fix(v1.6.0 audit B13): the sweep never registered a dataset for the
        # table, so the fence-missed failure path drops it as an orphan.
        left = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(
                    ref=f'data."{out_tables[0]}"'
                )
            )
        ).scalar_one()
        assert left is None

    async def test_fence_missed_failure_keeps_adopted_table(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(v1.6.0 audit B13): the other side of the adoption probe — a
        final commit that reached the server before the connection dropped
        leaves the row 'complete' with a registered dataset. The late
        _mark_job_failed fence-misses AND finds the adopting dataset row, so
        it must leave the table (a live dataset's storage) alone."""
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(f"CREATE TABLE data.{table_name} (gid SERIAL PRIMARY KEY)")
        )
        await test_db_session.commit()
        await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
        )
        job = await _create_job(test_db_session, admin_id)
        job.status = "complete"
        await test_db_session.commit()
        assert job.attempt_id is not None

        async with core_db.async_session() as session:
            await _mark_job_failed(
                session,
                job_id=str(job.id),
                attempt_id=job.attempt_id,
                exc=RuntimeError("late failure after commit"),
                schema="data",
                out_table=table_name,
                operation="centroid",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete"
        left = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(ref=f"data.{table_name}")
            )
        ).scalar_one()
        assert left is not None

    async def test_fence_missed_cancel_drops_unadopted_table(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(v1.6.0 audit B13): the cancel path's fence-miss branch used to
        skip cleanup entirely — a sweep that failed the row before the
        cancel bookkeeping ran left the committed output table leaking
        forever. It now runs the same adoption probe as _mark_job_failed and
        drops the table when no dataset row adopted it.

        fix(#1778 codex r10): the table has to carry THIS job and attempt's
        scope, or `drop_unadopted_analysis_output`'s ownership check refuses
        it on purpose — a name that is not this job's can never become this
        job's. An unscoped name tested a case production code never produces;
        the realistic one is a cancelled attempt's own committed table."""
        from app.processing.analysis.tasks import analysis_output_table_name

        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, admin_id)
        assert job.attempt_id is not None
        base = f"orphan_{uuid.uuid4().hex[:6]}"
        table_name = analysis_output_table_name(base, job.id, job.attempt_id)
        await test_db_session.execute(
            text(f"CREATE TABLE data.{table_name} (gid SERIAL PRIMARY KEY)")
        )
        await test_db_session.commit()
        job.status = "failed"
        job.error_message = "Stale: heartbeat lease expired"
        await test_db_session.commit()

        async with core_db.async_session() as working_session:
            await _fail_cancelled_job(
                working_session,
                job_id=str(job.id),
                attempt_id=job.attempt_id,
                schema="data",
                out_table=table_name,
                operation="centroid",
            )

        await test_db_session.refresh(job)
        # The sweep's terminal state and message survive the fence miss...
        assert job.status == "failed"
        assert job.error_message == "Stale: heartbeat lease expired"
        # ...and the unadopted table was dropped, not leaked.
        left = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(ref=f"data.{table_name}")
            )
        ).scalar_one()
        assert left is None

    async def test_fence_missed_cancel_keeps_adopted_table(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(v1.6.0 audit B13): the leak-over-loss side of the cancel
        path's new probe — when the row went terminal via a real completion
        (dataset row adopted the table), the fence-missed cancel must leave
        the live dataset's storage alone."""
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(f"CREATE TABLE data.{table_name} (gid SERIAL PRIMARY KEY)")
        )
        await test_db_session.commit()
        await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
        )
        job = await _create_job(test_db_session, admin_id)
        job.status = "complete"
        await test_db_session.commit()
        assert job.attempt_id is not None

        async with core_db.async_session() as working_session:
            await _fail_cancelled_job(
                working_session,
                job_id=str(job.id),
                attempt_id=job.attempt_id,
                schema="data",
                out_table=table_name,
                operation="centroid",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete"
        left = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(ref=f"data.{table_name}")
            )
        ).scalar_one()
        assert left is not None

    async def test_fence_missed_completion_keeps_adopted_table(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(v1.6.0 audit B13): the complete path's fence-miss branch used
        to drop the output table unconditionally. It is now gated on the
        same adoption probe — a dataset row committed by another actor for
        this table name keeps its storage."""
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(f"CREATE TABLE data.{table_name} (gid SERIAL PRIMARY KEY)")
        )
        await test_db_session.commit()
        adopting = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
        )
        job = await _create_job(test_db_session, admin_id)
        job.status = "failed"
        job.error_message = "Stale: heartbeat lease expired"
        await test_db_session.commit()
        assert job.attempt_id is not None

        async with core_db.async_session() as session:
            await _complete_job_for_attempt(
                session,
                job_id=str(job.id),
                attempt_id=job.attempt_id,
                dataset_id=adopting.id,
                schema="data",
                out_table=table_name,
                operation="centroid",
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message == "Stale: heartbeat lease expired"
        left = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(ref=f"data.{table_name}")
            )
        ).scalar_one()
        assert left is not None

    async def test_name_collision_warning_is_surfaced(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#786): the rename generate_table_name reports on a collision
        was discarded — the upload path persists it to
        user_metadata['collision_warning'], which the job-status endpoint
        surfaces as warning_message, so an analysis output landing in e.g.
        parcels_buffered_3 said nothing to the user."""
        from app.processing.ingest.service import generate_table_name

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Warned {uuid.uuid4().hex[:6]}"
        taken, _ = await generate_table_name(title, test_db_session)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{taken}" (marker integer)')
        )
        await test_db_session.commit()

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title=title,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        warning = (job.user_metadata or {}).get("collision_warning")
        assert warning is not None
        assert f"{taken}_2" in warning

    async def test_cleanup_rows_do_not_count_toward_size_cap(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#786): NULL/EMPTY-geometry rows are excluded in the CTAS
        itself — a DELETE cannot shrink pg_total_relation_size (dead tuples
        keep their pages until a rewrite), so the early ceiling probe used
        to measure rows the cleanup removes and could fail a small analysis
        as oversized. Same shape as the clip-by-layer case from the #719
        review, extended to the render_geometry_expr operations."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # 2,025 NULL-geometry decoys: centroid maps them to NULL and the
        # cleanup removes them, but before the in-CTAS filter they inflated
        # the measured relation well past the 64 KB ceiling below, while
        # the 2 real centroids fit comfortably.
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{ds.table_name} (name) "  # noqa: S608
                f"SELECT 'decoy' FROM generate_series(1, 2025)"
            )
        )
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 65536):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=f"Centroids {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        kept = await test_db_session.scalar(
            text(f"SELECT COUNT(*) FROM data.{new_ds.table_name}")  # noqa: S608
        )
        assert kept == 2

    async def test_worker_cancellation_fails_job_and_reraises(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): graceful worker shutdown cancels the task mid-CTAS. The
        job must fail immediately with a comprehensible message — not strand
        in 'running' holding the slot until the 60-minute sweep — and the
        CancelledError must propagate so the queue records the abort."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        slow_sql = (
            "SELECT 1 AS gid, "
            "(SELECT ST_GeomFromText('POINT(0 0)', 4326) FROM pg_sleep(30)) AS geom"
        )
        with patch(
            "app.processing.analysis.tasks._build_materialize_select",
            return_value=slow_sql,
        ):
            run = asyncio.create_task(
                _materialize(
                    job_id=str(job.id),
                    dataset_id=str(ds.id),
                    user_id=str(admin_id),
                    operation="centroid",
                    title="Cancelled",
                )
            )
            # Cancel only once the worker owns the row (claim committed), so
            # the cancellation lands inside the guarded body, then give the
            # CTAS a beat to start.
            for _ in range(100):
                await asyncio.sleep(0.1)
                await test_db_session.refresh(job)
                if job.status == "running":
                    break
            assert job.status == "running"
            await asyncio.sleep(0.3)
            run.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "worker shut down" in (job.error_message or "")

    async def test_cancel_cleanup_releases_working_sessions_row_lock(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#700 review): a cancel can land while the working session's
        open transaction still holds the job-row lock (e.g. mid-commit,
        after flush). The cleanup must roll that session back before its
        fenced update, or it blocks on its own lock until the shield
        timeout and the row strands in 'running' after all."""
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, admin_id)
        job.status = "running"
        await test_db_session.commit()

        # Late-bound attribute access: conftest repoints app.core.db's
        # session maker at the per-run test DB after import time.
        async with core_db.async_session() as working_session:
            # Uncommitted UPDATE → this transaction holds the row lock,
            # exactly as a cancel landing mid-commit would leave it.
            await working_session.execute(
                update(IngestJob)
                .where(IngestJob.id == job.id)
                .values(current_step="registering")
            )
            await asyncio.wait_for(
                _fail_cancelled_job(
                    working_session,
                    job_id=str(job.id),
                    attempt_id=job.attempt_id,
                    schema="data",
                    out_table=None,
                    operation="centroid",
                ),
                timeout=10,
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "worker shut down" in (job.error_message or "")

    async def test_dissolve_materialize_single_feature(
        self,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Dissolved {uuid.uuid4().hex[:6]}"

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=title,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        assert new_ds.feature_count == 1

    async def test_dissolve_by_a_json_array_field_fails_with_a_clear_message(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#1097 review): the by_field guard has the overlay guard's array
        blind spot. The router's snapshot says 'ARRAY' for a json[] column, so
        enqueue admits it, and without the worker's live recheck the dissolve
        CTAS dies on SQLSTATE 42883 after the queue wait with an error naming
        nothing the user chose. Through _materialize rather than the helper,
        so the test proves the recheck is actually wired into the job path.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            text(f"ALTER TABLE data.{ds.table_name} ADD COLUMN props json[]")  # noqa: S608
        )
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            by_field="props",
            title=f"Dissolved {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "props" in (job.error_message or "")
        assert "json[]" in (job.error_message or "")
        assert "42883" not in (job.error_message or "")

    async def test_missing_source_marks_job_failed(
        self,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(uuid.uuid4()),
            user_id=str(admin_id),
            operation="centroid",
            title="Ghost",
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert job.error_message
        # fix(v1.6.0 audit B12): the failure path stamps completed_at too.
        assert job.completed_at is not None

    async def test_result_dataset_is_private_and_owned_by_requester(
        self,
        test_db_session: AsyncSession,
    ):
        """The single highest-risk invariant: analysis outputs must register
        as private datasets owned by the requesting user — a regression here
        silently exposes derived copies of source data."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title=f"Owned {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset, Record

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        # Visibility and ownership both live on the catalog Record.
        record = await test_db_session.get(Record, new_ds.record_id)
        assert record is not None
        assert record.visibility == "private"
        assert record.created_by == admin_id

    async def test_clip_materialize_creates_dataset(
        self,
        test_db_session: AsyncSession,
    ):
        """End-to-end clip: mask renders into the CTAS, only intersecting rows
        survive, attributes carry, and the output geometry stays polygonal."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        mask = {
            "type": "Polygon",
            "coordinates": [
                [[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5], [-0.5, -0.5]]
            ],
        }

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Clipped {uuid.uuid4().hex[:6]}",
            mask=mask,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        assert new_ds.feature_count == 1
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT name, GeometryType(geom_4326) FROM data.{new_ds.table_name}"  # noqa: S608
                )
            )
        ).all()
        assert rows == [("a", "POLYGON")]

    async def test_dissolve_by_field_groups(
        self,
        test_db_session: AsyncSession,
    ):
        """Grouped dissolve: one row per group key, source_count populated,
        gid numbered — the only branch that interpolates a user column."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=f"Dissolved by name {uuid.uuid4().hex[:6]}",
            by_field="name",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT gid, name, source_count, GeometryType(geom_4326) "  # noqa: S608
                    f"FROM data.{new_ds.table_name} ORDER BY name"
                )
            )
        ).all()
        assert rows == [
            (1, "a", 1, "MULTIPOLYGON"),
            (2, "b", 1, "MULTIPOLYGON"),
        ] or rows == [
            (2, "a", 1, "MULTIPOLYGON"),
            (1, "b", 1, "MULTIPOLYGON"),
        ]

    async def test_empty_result_fails_job(
        self,
        test_db_session: AsyncSession,
    ):
        """A clip matching nothing must fail loud, not register a junk dataset."""
        from app.processing.analysis.tasks import ANALYSIS_JOBS

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        far_mask = {
            "type": "Polygon",
            "coordinates": [[[50, 50], [51, 50], [51, 51], [50, 51], [50, 50]]],
        }
        failed_before = ANALYSIS_JOBS.labels(
            operation="clip", status="failed"
        )._value.get()

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title="Empty Clip",
            mask=far_mask,
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "no features" in (job.error_message or "")
        assert job.dataset_id is None
        assert (
            ANALYSIS_JOBS.labels(operation="clip", status="failed")._value.get()
            == failed_before + 1
        )

    async def test_name_collision_preserves_existing_table(
        self,
        test_db_session: AsyncSession,
    ):
        """When CREATE TABLE loses a name race, cleanup must not drop the
        winner's table — only a table this job actually created.

        fix(#692): generate_table_name now sidesteps live relations, so the
        lost race is simulated by pinning the generated name to the occupied
        one — exactly what happens when two jobs draw the same name in the
        window between generation and CREATE.

        fix(#1778 codex r7): the occupied table is created at the name this
        JOB will derive, because the output name is scoped by the job now. The
        race is the same one; only where the name comes from has changed.

        fix(#1778 codex r10): the collision-check now runs against the SCOPED
        candidate (`resolve_analysis_output_table`), which reads pg_class
        before CREATE and would self-heal to a `_2` suffix if it saw the
        occupied name sitting there when it probed. So pinning only
        `generate_table_name` is no longer enough to reproduce a lost race --
        the probe would just avoid the collision this test means to force.
        `resolve_analysis_output_table` is pinned too, to the occupied name,
        which is what a probe that ran a moment before the other job's CREATE
        would have returned: "free", followed immediately by a CREATE that
        loses."""
        from app.processing.analysis.tasks import analysis_output_table_name

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Collide {uuid.uuid4().hex[:6]}"
        base = f"collide_{uuid.uuid4().hex[:6]}"
        expected = analysis_output_table_name(base, job.id, job.attempt_id)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{expected}" (marker integer)')
        )
        await test_db_session.commit()

        with (
            patch(
                "app.processing.ingest.service.generate_table_name",
                AsyncMock(return_value=(base, None)),
            ),
            patch(
                "app.processing.analysis.tasks.resolve_analysis_output_table",
                AsyncMock(return_value=expected),
            ),
        ):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=title,
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        survived = (
            await test_db_session.execute(
                text("SELECT to_regclass(:ref)").bindparams(ref=f'data."{expected}"')
            )
        ).scalar_one()
        assert survived is not None
        # And it is still the pre-existing table, not a half-built output.
        cols = (
            (
                await test_db_session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'data' AND table_name = :t"
                    ).bindparams(t=expected)
                )
            )
            .scalars()
            .all()
        )
        assert cols == ["marker"]

    async def test_orphan_physical_table_self_heals_to_suffix(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): a table committed without a catalog row (worker killed
        during registration) used to poison its title forever — the name
        generator collided only against the catalog, so every retry died on
        CREATE TABLE. It now probes information_schema too: the retry lands
        on a _2 suffix and the orphan is left untouched for an operator.

        fix(#1778 codex r7): the output name carries a job scope now, so the
        suffix walk is no longer what keeps the retry off the orphan. The walk
        still runs and still lands on _2, and this keeps asserting it, but the
        guarantee underneath is stronger: a name embedding a job id could not
        have collided with the orphan even without it."""
        from app.processing.analysis.tasks import analysis_output_table_name
        from app.processing.ingest.service import generate_table_name

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)
        title = f"Orphaned {uuid.uuid4().hex[:6]}"
        orphan, _ = await generate_table_name(title, test_db_session)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{orphan}" (marker integer)')
        )
        await test_db_session.commit()

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="centroid",
            title=title,
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds.table_name == analysis_output_table_name(
            f"{orphan}_2", job.id, job.attempt_id
        )
        cols = (
            (
                await test_db_session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'data' AND table_name = :t"
                    ).bindparams(t=orphan)
                )
            )
            .scalars()
            .all()
        )
        assert cols == ["marker"]

    async def test_clip_by_layer_materialize(
        self,
        test_db_session: AsyncSession,
    ):
        """Worker resolves the mask dataset's table and clips against its
        unioned geometries — same output as an equivalent drawn mask."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Layer clipped {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT name, GeometryType(geom_4326) FROM data.{new_ds.table_name}"  # noqa: S608
                )
            )
        ).all()
        assert rows == [("a", "POLYGON")]

    async def test_clip_by_layer_multirow_mask_equals_union_clip(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719): the subdivided join must equal clipping against the
        whole-layer union it replaced.

        The old materialize shape unioned the mask layer into one geometry and
        intersected every source row against it. This one subdivides the mask
        and unions the per-piece intersections instead — 33.2s -> 3.4s on a
        972-polygon mask over 22k source rows. Intersection distributes over
        union so the two are equal in theory; this pins it in practice, on a
        MULTI-row overlapping mask where the distinction actually bites (a
        single-row mask subdivides to pieces that trivially reassemble).
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        mask_wkts = (
            "POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
            "POLYGON((0.25 0.25, 0.25 1.5, 1.5 1.5, 1.5 0.25, 0.25 0.25))",
            "POLYGON((0.4 -0.2, 0.4 0.3, 0.9 0.3, 0.9 -0.2, 0.4 -0.2))",
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt=mask_wkts[0],
            extra_wkts=mask_wkts[1:],
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Multirow clip {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None

        # Ground truth: clip against the unioned mask, the pre-#719 semantics.
        union_wkt = ", ".join(f"ST_GeomFromText('{w}', 4326)" for w in mask_wkts)
        n_got, n_want, symdiff = (
            await test_db_session.execute(
                text(
                    f"WITH truth AS ("  # noqa: S608
                    f"  SELECT ST_CollectionExtract("
                    f"    ST_Intersection(ST_MakeValid(s.geom_4326),"
                    f"      ST_Union(ARRAY[{union_wkt}])),"
                    f"    ST_Dimension(s.geom_4326) + 1) AS geom"
                    f"  FROM data.{ds.table_name} AS s"
                    f"), want AS ("
                    f"  SELECT geom FROM truth"
                    f"  WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)"
                    f"), got AS (SELECT geom_4326 AS geom FROM data.{new_ds.table_name})"
                    f" SELECT (SELECT count(*) FROM got),"
                    f"        (SELECT count(*) FROM want),"
                    f"        ST_Area(ST_SymDifference("
                    f"          (SELECT ST_Union(geom) FROM got),"
                    f"          (SELECT ST_Union(geom) FROM want)))"
                )
            )
        ).one()
        # Guard against a vacuous pass: 0 == 0 with a NULL symdiff would
        # otherwise satisfy both assertions below.
        assert n_got > 0, "clip produced nothing — the fixture no longer overlaps"
        assert n_got == n_want, (
            f"subdivided clip produced {n_got} rows, union clip {n_want}"
        )
        assert symdiff < 1e-12, (
            f"subdivided clip diverged from the whole-layer union it replaced "
            f"(symmetric-difference area {symdiff})"
        )

    async def test_clip_by_layer_does_not_fragment_a_line_at_mask_seams(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719 review): ST_Union does not sew line segments.

        The subdivided join intersects per mask piece and unions the results.
        For polygons that reassembles exactly, but a LineString crossing a
        seam between two touching mask polygons came back as an artificially
        fragmented MultiLineString where the old whole-mask intersection
        returned one continuous LineString — which changes the geometry type
        the new dataset is registered with. ST_LineMerge on single-part
        LineString sources restores it; a line with a REAL gap must stay
        multi-part.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(LineString, 4326),"
                f"  geom_4326 geometry(LineString, 4326))"
            )
        )
        # gid 1 crosses the seam between the two touching mask polygons;
        # gid 2 spans the real gap before the third, detached mask polygon.
        for wkt in ("LINESTRING(1 5, 9 5)", "LINESTRING(1 6, 24 6)"):
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "  # noqa: S608
                    f"(ST_GeomFromText('{wkt}', 4326),"
                    f" ST_GeomFromText('{wkt}', 4326))"
                )
            )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="LINESTRING",
            feature_count=2,
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 0 10, 5 10, 5 0, 0 0))",
            extra_wkts=(
                "POLYGON((5 0, 5 10, 10 10, 10 0, 5 0))",
                "POLYGON((20 0, 20 10, 25 10, 25 0, 20 0))",
            ),
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Clipped lines {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom_4326), ST_NumGeometries(geom_4326) "  # noqa: S608
                    f"FROM data.{new_ds.table_name} ORDER BY gid"
                )
            )
        ).all()
        assert rows == [("LINESTRING", 1), ("MULTILINESTRING", 2)], rows

    async def test_clip_by_layer_keeps_touching_multiline_parts_separate(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719 review): seam repair must not merge REAL components.

        The seam fix above keys on ``GeometryType(...) = 'LINESTRING'``, not
        ``ST_Dimension(...) = 1``. A MultiLineString whose components merely
        touch at an endpoint is dimension 1 too, so a dimension test sews
        those genuine components into one LineString — a change the mask never
        asked for, and one the whole-mask intersection does not make. Measured
        against the old shape: MULTILINESTRING/2 parts, both before and after.

        Both components sit well inside a single mask polygon, so the mask
        introduces no seam here at all; anything but a passthrough is wrong.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(MultiLineString, 4326),"
                f"  geom_4326 geometry(MultiLineString, 4326))"
            )
        )
        wkt = "MULTILINESTRING((1 2, 4 2), (4 2, 4 8))"
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "  # noqa: S608
                f"(ST_GeomFromText('{wkt}', 4326),"
                f" ST_GeomFromText('{wkt}', 4326))"
            )
        )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="MULTILINESTRING",
            feature_count=1,
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 0 10, 5 10, 5 0, 0 0))",
            extra_wkts=("POLYGON((5 0, 5 10, 10 10, 10 0, 5 0))",),
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Clipped multilines {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom_4326), ST_NumGeometries(geom_4326) "  # noqa: S608
                    f"FROM data.{new_ds.table_name} ORDER BY gid"
                )
            )
        ).all()
        assert rows == [("MULTILINESTRING", 2)], rows

    async def test_clip_by_layer_bbox_only_rows_do_not_count_toward_size_cap(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719 review): NULL rows must not be measured as output.

        The row filter admits a source row on a bounding-box overlap, so a
        concave mask lets through rows that never actually intersect it; their
        lateral aggregates over zero pieces and yields geom_out = NULL.
        ``_enforce_output_size`` runs against the CTAS BEFORE the NULL/EMPTY
        cleanup, so those rows used to count toward the ceiling — and clip has
        no source-feature cap bounding how many of them there are.

        The mask is the lower-right triangle of a 0..40 box (hypotenuse along
        y = x), so its bbox covers the whole box while its interior is only
        y < x. Every decoy sits just above the hypotenuse: inside the bbox,
        outside the polygon. Measured sizes for this shape — 1 row = 16 KB,
        2025 rows = 270 KB — so the ceiling below passes the real feature and
        fails the decoys by 4x.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(Point, 4326),"
                f"  geom_4326 geometry(Point, 4326))"
            )
        )
        # 2025 decoys clustered just above the hypotenuse near (1, 39):
        # inside the mask's bbox, outside the triangle.
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) "  # noqa: S608
                f"SELECT ST_SetSRID(ST_MakePoint(1 + x * 0.001, 39 - y * 0.001), 4326),"
                f"       ST_SetSRID(ST_MakePoint(1 + x * 0.001, 39 - y * 0.001), 4326)"
                f"  FROM generate_series(1, 45) AS x,"
                f"       generate_series(1, 45) AS y"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "  # noqa: S608
                f"(ST_SetSRID(ST_MakePoint(30, 5), 4326),"
                f" ST_SetSRID(ST_MakePoint(30, 5), 4326))"
            )
        )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="POINT",
            feature_count=2026,
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 40 0, 40 40, 0 0))",
        )
        job = await _create_job(test_db_session, admin_id)

        # 64 KB of headroom: the single real feature (16 KB) fits, the 2025
        # bbox-only rows (270 KB) do not.
        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 65536):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="clip",
                title=f"Clipped points {uuid.uuid4().hex[:6]}",
                mask_dataset_id=str(mask_ds.id),
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        kept = await test_db_session.scalar(
            text(f"SELECT COUNT(*) FROM data.{new_ds.table_name}")  # noqa: S608
        )
        assert kept == 1, kept

    async def test_clip_by_layer_survives_a_geom_out_attribute_column(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#719 review): "geom_out" is a legal attribute name.

        The CTAS selects the carry columns from _src alongside the lateral's
        own geom_out, so an unqualified predicate is rejected outright:
        `column reference "geom_out" is ambiguous`. The whole-mask shape this
        PR replaced had no lateral and so no collision, making this a
        regression on datasets that happen to use the name.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f'  "geom_out" TEXT,'
                f"  geom geometry(Polygon, 4326),"
                f"  geom_4326 geometry(Polygon, 4326))"
            )
        )
        wkt = "POLYGON((1 1, 4 1, 4 4, 1 4, 1 1))"
        await test_db_session.execute(
            text(
                f'INSERT INTO data.{table_name} ("geom_out", geom, geom_4326)'  # noqa: S608
                f" VALUES ('an ordinary attribute',"
                f" ST_GeomFromText('{wkt}', 4326),"
                f" ST_GeomFromText('{wkt}', 4326))"
            )
        )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="POLYGON",
            feature_count=1,
        )
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 0 10, 5 10, 5 0, 0 0))",
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title=f"Clipped with attr {uuid.uuid4().hex[:6]}",
            mask_dataset_id=str(mask_ds.id),
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

    async def test_clip_by_layer_missing_mask_fails_job(
        self,
        test_db_session: AsyncSession,
    ):
        """A mask dataset deleted between enqueue and run fails cleanly."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="clip",
            title="Ghost mask",
            mask_dataset_id=str(uuid.uuid4()),
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "Mask dataset not found" in (job.error_message or "")

    async def test_analyze_and_registration_timeout_between_phases(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#692): the output table is ANALYZEd before the mid-task commit
        (tile queries land before autovacuum's pass), and registration gets a
        fresh statement_timeout (SET LOCAL died with that commit). Pin both
        by inspecting the statements the worker actually ran."""
        executed: list[str] = []
        from sqlalchemy.ext.asyncio import AsyncSession as _AS

        real_execute = _AS.execute

        async def spying_execute(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return await real_execute(self, statement, *args, **kwargs)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        with patch.object(_AS, "execute", spying_execute):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="centroid",
                title=f"Spied {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        analyzes = [s for s in executed if s.startswith("ANALYZE ")]
        assert len(analyzes) == 1
        timeouts = [s for s in executed if "SET LOCAL statement_timeout" in s]
        # One budget for the build transaction, one re-armed for registration.
        assert len(timeouts) == 2
        # The registration budget is set after the ANALYZE (i.e. in the new
        # transaction), not before.
        assert executed.index(timeouts[1]) > executed.index(analyzes[0])
        # Only dissolve flips the aggregation strategy (fix(#694)).
        assert not [s for s in executed if "enable_hashagg" in s]
        # fix(#701 review): the size ceiling is probed twice — a cheap early
        # exit after the CTAS, and the authoritative check on the finished
        # relation (post-4326-rewrite, so heap + TOAST + GIST all count),
        # which must land before the ANALYZE that precedes the commit.
        # Positions, not values: both probes stringify identically, so
        # list.index() would find the first one twice.
        size_pos = [i for i, s in enumerate(executed) if "pg_total_relation_size" in s]
        assert len(size_pos) == 2
        # fix(#1113): registration now runs the linearize-enforcement UPDATE
        # (uniquely marked by ST_HasArc) AFTER the probes; the position under
        # test is the BUILD's last geom_4326 write, so exclude the enforcer.
        rewrite_pos = max(
            i
            for i, s in enumerate(executed)
            if "geom_4326" in s and "UPDATE" in s and "ST_HasArc" not in s
        )
        assert size_pos[1] > rewrite_pos
        assert size_pos[1] < executed.index(analyzes[0])

    async def test_dissolve_ctas_disables_hashagg(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#694): hash aggregation holds every group's union state in
        memory simultaneously; the dissolve CTAS transaction must switch to
        sorted aggregation, which bounds memory to one group at a time."""
        executed: list[str] = []
        from sqlalchemy.ext.asyncio import AsyncSession as _AS

        real_execute = _AS.execute

        async def spying_execute(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return await real_execute(self, statement, *args, **kwargs)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        with patch.object(_AS, "execute", spying_execute):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="dissolve",
                title=f"Hashagg {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        hashaggs = [s for s in executed if "enable_hashagg" in s]
        assert len(hashaggs) == 1
        ctas = [s for s in executed if s.startswith("CREATE TABLE")]
        # Same transaction, ahead of the CTAS it protects.
        assert executed.index(hashaggs[0]) < executed.index(ctas[0])

    async def test_ctas_scopes_work_mem_to_its_transaction(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#1012): the CTAS gets a raised work_mem, SET LOCAL so it reverts
        with the transaction and the other connections keep the 8MB default.

        Paired with the dissolve case below, which is the shape that most needs
        it: #694's `enable_hashagg = off` forces sorted aggregation, and sorting
        is exactly what work_mem governs.
        """
        executed: list[str] = []
        from sqlalchemy.ext.asyncio import AsyncSession as _AS

        real_execute = _AS.execute

        async def spying_execute(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return await real_execute(self, statement, *args, **kwargs)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        with patch.object(_AS, "execute", spying_execute):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="dissolve",
                title=f"WorkMem {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        work_mems = [s for s in executed if "work_mem" in s]
        assert len(work_mems) == 1, f"expected one work_mem statement, got {work_mems}"
        # Nothing is issued when the operator opts out — asserted separately in
        # test_work_mem_override_can_be_disabled below.
        # SET LOCAL, never a plain SET: a session-level bump would outlive the
        # transaction and follow the pooled connection to unrelated queries.
        assert work_mems[0].startswith("SET LOCAL work_mem"), work_mems[0]
        assert _materialize_work_mem() in work_mems[0]

        ctas = [s for s in executed if s.startswith("CREATE TABLE")]
        hashaggs = [s for s in executed if "enable_hashagg" in s]
        # Ahead of the CTAS it is meant to serve, and in the same transaction as
        # the hashagg flip whose sort it pays for.
        assert executed.index(work_mems[0]) < executed.index(ctas[0])
        assert executed.index(hashaggs[0]) < executed.index(ctas[0])
        # fix(#1012 review): parallelism is pinned alongside it, so the "x2
        # backends" the budget is sized for is guaranteed rather than assumed
        # from db/postgresql.conf — which says nothing about an external server.
        par = [s for s in executed if "max_parallel_workers_per_gather" in s]
        assert len(par) == 1, par
        # LEAST, never a plain assignment: an operator who set 0 has disabled
        # parallel query, and raising them to 1 would hand this statement a
        # worker they said no to. set_config(..., true) is transaction-scoped.
        assert "LEAST" in par[0], par[0]
        assert "set_config" in par[0] and ", true)" in par[0], par[0]
        assert executed.index(par[0]) < executed.index(ctas[0])

    async def test_work_mem_override_can_be_disabled(
        self,
        test_db_session: AsyncSession,
        monkeypatch,
    ):
        """fix(#1012 review): 0 must issue NO statement, not a small one.

        An operator who has tuned their own cluster needs a way to say "leave
        work_mem alone"; a clamped small value would still raise the session
        above a cluster configured below the bundled default.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "analysis_materialize_work_mem_mb", 0)

        executed: list[str] = []
        from sqlalchemy.ext.asyncio import AsyncSession as _AS

        real_execute = _AS.execute

        async def spying_execute(self, statement, *args, **kwargs):
            executed.append(str(statement))
            return await real_execute(self, statement, *args, **kwargs)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        with patch.object(_AS, "execute", spying_execute):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="dissolve",
                title=f"NoWorkMem {uuid.uuid4().hex[:6]}",
            )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message
        assert not [s for s in executed if "work_mem" in s], (
            "work_mem was set despite the override being disabled"
        )
        # The parallelism pin exists to protect the work_mem ceiling, so it
        # must not fire when there is no ceiling to protect.
        assert not [s for s in executed if "max_parallel_workers_per_gather" in s]

    async def test_worker_rechecks_size_caps_before_ctas(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#701 review): the enqueue gate's count can go stale while the
        job waits in the queue (a source or mask can be re-uploaded past its
        cap), and the post-CTAS size check is too late to protect the
        dissolve/mask union itself from OOM — the worker re-counts the live
        tables immediately before building the SQL."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)

        # Source recheck: the fixture table holds 2 rows; cap 1 must fail
        # the job before any output table exists.
        job = await _create_job(test_db_session, admin_id)
        with patch.dict(
            "app.platform.analysis_sql.MAX_SOURCE_FEATURES", {"dissolve": 1}
        ):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="dissolve",
                title="Grew past the cap",
            )
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "too large for dissolve" in (job.error_message or "")
        assert job.dataset_id is None

        # Mask recheck: the 1-row mask table against a cap of 0.
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
        )
        job2 = await _create_job(test_db_session, admin_id)
        with patch("app.processing.analysis.tasks.MAX_MASK_LAYER_FEATURES", 0):
            await _materialize(
                job_id=str(job2.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="clip",
                title="Mask grew past the cap",
                mask_dataset_id=str(mask_ds.id),
            )
        await test_db_session.refresh(job2)
        assert job2.status == "failed"
        assert "mask layer has too many features" in (job2.error_message or "")
        assert job2.dataset_id is None

    async def test_oversized_output_fails_before_registration(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#694): the enqueue gates read a cached feature_count snapshot;
        the post-CTAS pg_total_relation_size backstop is the enforcement that
        can't go stale. The job fails with an actionable message, no dataset
        is registered, and the cleanup path drops the built table."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 1):
            await _materialize(
                job_id=str(job.id),
                dataset_id=str(ds.id),
                user_id=str(admin_id),
                operation="buffer",
                title=f"Oversized {uuid.uuid4().hex[:6]}",
                distance_meters=10.0,
            )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "size limit" in (job.error_message or "")
        assert job.dataset_id is None

    async def test_oversized_message_advice_matches_operation(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(v1.6.0 audit D11): only buffer has a distance to reduce —
        clip/centroid/dissolve users must not be told to shrink a buffer
        they never set."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)

        with patch("app.processing.analysis.tasks.MAX_OUTPUT_BYTES", 1):
            with pytest.raises(ValueError) as clip_exc:
                await _enforce_output_size(
                    test_db_session, "data", ds.table_name, operation="clip"
                )
            with pytest.raises(ValueError) as buffer_exc:
                await _enforce_output_size(
                    test_db_session, "data", ds.table_name, operation="buffer"
                )
        assert "buffer" not in str(clip_exc.value)
        assert "smaller dataset" in str(clip_exc.value)
        assert "buffer distance" in str(buffer_exc.value)

    async def test_mixed_geometry_dissolve_stays_typed(
        self,
        test_db_session: AsyncSession,
    ):
        """A union over mixed types must not register a GEOMETRYCOLLECTION —
        only the highest-dimension components survive."""
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(Geometry, 4326),"
                f"  geom_4326 geometry(Geometry, 4326)"
                f")"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "
                f"(ST_GeomFromText('POINT(5 5)', 4326),"
                f" ST_GeomFromText('POINT(5 5)', 4326)),"
                f"(ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326),"
                f" ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))', 4326))"
            )
        )
        await test_db_session.commit()
        from tests.factories import create_dataset

        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="GEOMETRY",
            feature_count=2,
        )
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=f"Mixed dissolve {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        geom_type = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom_4326) FROM data.{new_ds.table_name}"  # noqa: S608
                )
            )
        ).scalar_one()
        assert geom_type == "MULTIPOLYGON"


# ---------------------------------------------------------------------------
# Antimeridian and high-latitude edge fixtures (fix(#697))
# ---------------------------------------------------------------------------


async def _materialize_buffer(
    session: AsyncSession,
    *,
    distance: float,
    lon: float | None = None,
    lat: float | None = None,
    wkt: str | None = None,
    column_type: str = "Point",
    geometry_type: str = "POINT",
):
    """Run a real buffer materialize over a one-row source geometry.

    Pass either ``lon``/``lat`` for a single point, or ``wkt`` plus its PostGIS
    ``column_type`` for a multipart source.
    """
    admin_id = await get_user_id(session, "admin")
    if wkt is not None:
        src = await _create_wkt_dataset(
            session,
            created_by=admin_id,
            wkt=wkt,
            column_type=column_type,
            geometry_type=geometry_type,
        )
    else:
        assert lon is not None and lat is not None
        src = await _create_point_dataset_at(
            session, created_by=admin_id, lon=lon, lat=lat
        )
    job = await _create_job(session, admin_id)
    await _materialize(
        job_id=str(job.id),
        dataset_id=str(src.id),
        user_id=str(admin_id),
        operation="buffer",
        title=f"Buffer {uuid.uuid4().hex[:8]}",
        distance_meters=distance,
    )
    await session.refresh(job)
    assert job.status == "complete", job.error_message

    from app.modules.catalog.datasets.domain.models import Dataset

    out = await session.get(Dataset, job.dataset_id)
    assert out is not None
    return out


class TestBufferAtDateline:
    """Every other fixture in this suite is low-latitude and low-longitude,
    which is precisely why #697 went unnoticed. These pin the seam.
    """

    async def test_buffer_across_dateline_is_split_not_wrapped(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#697): a 10 km buffer of a point at lon 179.95 used to register
        as ONE self-intersecting polygon with vertices on both sides of ±180.
        Probed before the fix: ST_IsValid false, planar envelope 359.99° wide
        for a footprint 0.25° across, and the stored geometry ST_Intersects a
        bbox over central France — a feature-level false positive ~15 000 km
        out, reaching OGC /items, tile queries, and bbox-filtered exports.
        """
        out = await _materialize_buffer(
            test_db_session, lon=179.95, lat=45.0, distance=10_000
        )

        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(geom_4326) AS gtype,"
                    " ST_NumGeometries(geom_4326) AS parts,"
                    " ST_IsValid(geom_4326) AS valid,"
                    " ST_XMin(geom_4326) AS xmin,"
                    " ST_XMax(geom_4326) AS xmax,"
                    " ST_Intersects("
                    "   geom_4326, ST_MakeEnvelope(2, 44.9, 3, 45.1, 4326)"
                    " ) AS hits_france"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()

        # Split at the seam into one part per hemisphere, each planar-valid.
        assert row.gtype == "MULTIPOLYGON"
        assert row.parts == 2
        assert row.valid is True
        # Every vertex stays inside the WGS84 domain — a shift-only fix would
        # have left coordinates past 180 that no GeoJSON/tile consumer accepts.
        assert row.xmin >= -180.0
        assert row.xmax <= 180.0
        # The defect that actually reached users: the geometry no longer
        # matches a bbox on the far side of the world.
        assert row.hits_france is False

        # fix(#934): this block used to pin the PRE-fold extent — a single
        # POLYGON spanning the whole -180..180 band, 360° wide to describe a
        # footprint 0.25° across — and its comment named the follow-up that
        # would change it ("teaching the analysis extent rollup to emit one is
        # the separate follow-up"). #934 is that follow-up: analysis registers
        # through `register_existing_table`, so it shares the ingest extent
        # producer, which now emits the honest two-ring seam form #892 widened
        # the column to hold. Nothing above this point changed — the #697
        # guarantees about the buffer RESULT geometry are asserted separately
        # and still hold.
        extent = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(spatial_extent) AS gtype,"
                    " ST_NumGeometries(spatial_extent) AS parts,"
                    " ST_IsValid(spatial_extent) AS valid,"
                    " ST_AsText(spatial_extent) AS wkt"
                    " FROM catalog.records WHERE id = :rid"
                ).bindparams(rid=out.record_id)
            )
        ).one()
        assert extent.gtype == "MULTIPOLYGON"
        assert extent.parts == 2
        assert extent.valid is True

        # One lobe per hemisphere, meeting AT the seam: some ring ends on +180
        # and some ring starts on -180 (order is the producer's business, so
        # assert the set). Neither lobe is wide — the old single-ring fold's
        # failure mode was exactly one enormous ring.
        rings = (
            await test_db_session.execute(
                text(
                    "SELECT bool_or(ST_XMax(g) = 180) AS touches_east_seam,"
                    " bool_or(ST_XMin(g) = -180) AS touches_west_seam,"
                    " max(ST_XMax(g) - ST_XMin(g)) AS widest FROM ("
                    " SELECT ST_GeometryN(spatial_extent, n) AS g"
                    " FROM catalog.records,"
                    " generate_series(1, ST_NumGeometries(spatial_extent)) n"
                    " WHERE id = :rid) q"
                ).bindparams(rid=out.record_id)
            )
        ).one()
        assert rings.touches_east_seam is True
        assert rings.touches_west_seam is True
        assert rings.widest < 1.0

        # Read back as an RFC 7946 § 5.2 bbox it is the crossing (west > east)
        # pair, and its span is the real footprint rather than the whole world.
        # This is the point of the change: the pinned single ring reported 360°.
        bbox = extent_to_bbox(WKTElement(extent.wkt, srid=4326))
        assert bbox is not None
        assert bbox[0] > bbox[2], "a seam-crossing extent must read west > east"
        assert (bbox[2] - bbox[0]) % 360 == pytest.approx(0.25, abs=0.15)
        # The latitude band is untouched by any of this.
        assert bbox[1] == pytest.approx(44.91, abs=0.01)
        assert bbox[3] == pytest.approx(45.09, abs=0.01)

    async def test_buffer_away_from_dateline_is_untouched(
        self,
        test_db_session: AsyncSession,
    ):
        """The other half of fix(#697): the split must not fire on ordinary
        input. ST_ShiftLongitude maps negative longitudes to 180..360, so an
        unguarded normalization would cut geometry at the PRIME meridian — a
        10 km buffer at lon 0 measured 2 parts covering 49x the correct area.
        Straddling Greenwich is the case that catches it.
        """
        out = await _materialize_buffer(
            test_db_session, lon=0.0, lat=45.0, distance=10_000
        )

        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(geom_4326) AS gtype,"
                    " ST_IsValid(geom_4326) AS valid,"
                    " ST_XMax(geom_4326) - ST_XMin(geom_4326) AS span"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.gtype == "POLYGON"
        assert row.valid is True
        # ~0.25° across at lat 45 — a prime-meridian split would report ~360.
        assert row.span == pytest.approx(0.2534, abs=0.01)

        extent_span = (
            await test_db_session.execute(
                text(
                    "SELECT ST_XMax(spatial_extent) - ST_XMin(spatial_extent)"
                    " FROM catalog.records WHERE id = :rid"
                ).bindparams(rid=out.record_id)
            )
        ).scalar_one()
        assert extent_span == pytest.approx(0.2534, abs=0.01)

    async def test_buffer_at_highest_reachable_latitude_does_not_wrap(
        self,
        test_db_session: AsyncSession,
    ):
        """Pinning test for the polar half of #697, which does NOT reproduce.

        Two independent limits keep a pole-encircling buffer out of reach.
        Vector ingest clips every geometry to the Web Mercator envelope
        (``clip_to_mercator_bounds``, ±85.06° lat), so a genuinely polar source
        cannot exist — probed via the API, a point at lat -89.95 ingests as
        MULTIPOINT EMPTY and its buffer fails with "produced no features to
        save". And at lat 85.06 the parallel is ~3 480 km around, so encircling
        the pole needs a ~554 km radius, well past MAX_BUFFER_METERS (100 km).

        So the maximum-radius buffer at the seam-free maximum latitude must come
        back as a single unsplit polygon. If either limit ever moves — a larger
        buffer cap, or ingest keeping polar geometry — this fails and the
        pole-encircling case needs its own decision.
        """
        out = await _materialize_buffer(
            test_db_session, lon=0.0, lat=85.06, distance=MAX_BUFFER_METERS
        )

        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(geom_4326) AS gtype,"
                    " ST_IsValid(geom_4326) AS valid,"
                    " ST_XMax(geom_4326) - ST_XMin(geom_4326) AS span,"
                    " ST_YMax(geom_4326) AS ymax"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.gtype == "POLYGON"
        assert row.valid is True
        # ~20.8° of longitude at this latitude, nowhere near a wrap.
        assert row.span == pytest.approx(20.8, abs=1.0)
        assert row.ymax < 90.0

    async def test_pole_encircling_buffer_is_left_alone(
        self,
        test_db_session: AsyncSession,
    ):
        """The split's second guard condition, exercised directly.

        A geometry that encircles a pole genuinely occupies every longitude, so
        its planar span is wide for an honest reason and shifting it does not
        narrow it. A span-only guard would have split such a buffer at the seam
        and thrown away ~7% of its area. Unreachable through ingest today (see
        the test above), so this drives the source table straight past ingest —
        the guard has to hold on its own, not on an upstream clip.
        """
        out = await _materialize_buffer(
            test_db_session, lon=0.0, lat=89.9, distance=MAX_BUFFER_METERS
        )

        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(geom_4326) AS gtype,"
                    " ST_IsValid(geom_4326) AS valid,"
                    " ST_XMax(geom_4326) - ST_XMin(geom_4326) AS span"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        # Not promoted to MULTIPOLYGON: the guard declined to split, and
        # ST_CollectionHomogenize collapses the untouched single component back
        # to POLYGON rather than leaving a one-part MULTIPOLYGON.
        assert row.gtype == "POLYGON"
        assert row.valid is True
        assert row.span > 180.0

    async def test_one_feature_with_components_at_both_seams(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#883 review): the split decision has to be per component.

        A MULTIPOINT holding (179.95, 45) and (0, 45) buffers to one
        antimeridian-wrapping polygon plus one Greenwich-straddling polygon, and
        those two want opposite treatment. Deciding once on the envelope of the
        pair gets it wrong either way, and rounding picks which way: measured
        over a sweep of the second point's longitude, the envelope test declined
        at lon ±0.05 (leaving the antimeridian component self-intersecting and
        still hitting a bbox over France) and split at lon 0.0 (blowing the
        Greenwich component up to 6 parts covering 11.6x the correct area, newly
        intersecting lon -100, where neither input sits).

        Both seam positions are asserted here so a future envelope-level
        shortcut cannot pass by getting only one of them right.
        """
        out = await _materialize_buffer(
            test_db_session,
            wkt="MULTIPOINT((179.95 45),(0 45))",
            column_type="MultiPoint",
            geometry_type="MULTIPOINT",
            distance=10_000,
        )

        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(geom_4326) AS gtype,"
                    " ST_NumGeometries(geom_4326) AS parts,"
                    " ST_IsValid(geom_4326) AS valid,"
                    " ST_XMin(geom_4326) AS xmin,"
                    " ST_XMax(geom_4326) AS xmax,"
                    " ST_Area(geom_4326::geography) AS area,"
                    " ST_Intersects("
                    "   geom_4326, ST_MakeEnvelope(2, 44.9, 3, 45.1, 4326)"
                    " ) AS hits_france,"
                    " ST_Intersects("
                    "   geom_4326, ST_MakeEnvelope(-100, 44.9, -99, 45.1, 4326)"
                    " ) AS hits_dakota,"
                    # The Greenwich component must survive INTACT — a
                    # prime-meridian split would leave nothing covering lon 0.
                    " ST_Contains("
                    "   geom_4326, ST_SetSRID(ST_MakePoint(0, 45), 4326)"
                    " ) AS covers_greenwich,"
                    " ST_Contains("
                    "   geom_4326, ST_SetSRID(ST_MakePoint(179.95, 45), 4326)"
                    " ) AS covers_seam"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()

        # Antimeridian component cut in two, Greenwich component untouched.
        assert row.gtype == "MULTIPOLYGON"
        assert row.parts == 3
        assert row.valid is True
        assert row.xmin >= -180.0
        assert row.xmax <= 180.0
        # Neither source point is near lon 2-3 or lon -100.
        assert row.hits_france is False
        assert row.hits_dakota is False
        # Both original centres still covered: nothing was shifted away.
        assert row.covers_greenwich is True
        assert row.covers_seam is True
        # Two 10 km buffers at lat 45. The split adds a seam edge but removes no
        # area, and a mangled Greenwich component measured 11.6x this.
        assert row.area == pytest.approx(2 * math.pi * 10_000**2, rel=0.02)


async def _component_radius_range(
    session: AsyncSession, table_name: str, source_wkt: str
) -> list[tuple[int, float, float]]:
    """Geodesic distance from each source component to the vertices of the
    output part covering it — the metric the projection bugs actually distort.

    Area alone hides part of it: an equal-area fallback projection keeps the
    total while deforming each component (measured 9 240 - 10 824 m for a
    requested 10 000 m at a 150° span).
    """
    rows = (
        await session.execute(
            text(
                "WITH src AS (SELECT (ST_Dump("
                "  ST_SetSRID(ST_GeomFromText(:wkt), 4326))).path[1] AS ix,"
                " (ST_Dump(ST_SetSRID(ST_GeomFromText(:wkt), 4326))).geom AS p),"
                " out AS (SELECT (ST_Dump(geom_4326)).geom AS part"
                f"         FROM data.{table_name}),"  # noqa: S608
                " paired AS (SELECT src.ix, src.p, out.part FROM src, out"
                "            WHERE ST_Intersects(out.part, src.p))"
                " SELECT paired.ix AS ix,"
                "        min(ST_Distance(paired.p::geography,"
                "                        v.geom::geography)) AS min_r,"
                "        max(ST_Distance(paired.p::geography,"
                "                        v.geom::geography)) AS max_r"
                " FROM paired, LATERAL ST_DumpPoints(paired.part) AS v"
                " GROUP BY paired.ix ORDER BY paired.ix"
            ).bindparams(wkt=source_wkt)
        )
    ).all()
    return [(r.ix, r.min_r, r.max_r) for r in rows]


class TestBufferMultipartProjection:
    """fix(#891): ``ST_Buffer(...::geography, d)`` picks ONE planar working SRID
    for the whole input, so a multipart feature whose components sit far apart in
    longitude is buffered in a projection local to at most one of them.
    """

    async def _radius_range(
        self, session: AsyncSession, table_name: str, source_wkt: str
    ) -> list[tuple[int, float, float]]:
        return await _component_radius_range(session, table_name, source_wkt)

    async def test_components_90_degrees_apart_keep_their_radius(
        self,
        test_db_session: AsyncSession,
    ):
        """The headline case. A two-point MULTIPOINT 90° apart at lat 45 spans
        past the 45° mark where PostGIS falls back to world Mercator, whose
        scale error is 1/cos(latitude). Measured before this fix: both
        components came back with a 7 079 - 7 087 m radius for a requested
        10 000 m, and the feature held 49.9% of the ideal circle area.
        """
        wkt = "MULTIPOINT((0 45),(90 45))"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="MultiPoint",
            geometry_type="MULTIPOINT",
            distance=10_000,
        )

        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(geom_4326) AS gtype,"
                    " ST_NumGeometries(geom_4326) AS parts,"
                    " ST_IsValid(geom_4326) AS valid,"
                    " ST_Area(geom_4326::geography) AS area"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.gtype == "MULTIPOLYGON"
        assert row.parts == 2
        assert row.valid is True
        # vs the ideal circle area, not vs the unfixed output: #891 is precisely
        # the pre-existing error that made fixed-vs-raw the only honest
        # comparison in fix(#883).
        assert row.area == pytest.approx(2 * math.pi * 10_000**2, rel=0.01)

        radii = await self._radius_range(test_db_session, out.table_name, wkt)
        assert len(radii) == 2
        for _ix, min_r, max_r in radii:
            assert min_r == pytest.approx(10_000, rel=0.005)
            assert max_r == pytest.approx(10_000, rel=0.005)

    async def test_component_at_high_latitude_is_not_shrunk(
        self,
        test_db_session: AsyncSession,
    ):
        """The worst measured case, and the one area ratios understate.

        World Mercator's error is cos(latitude), so the further a component sits
        from the equator the more it loses. Measured before the fix on
        ``MULTIPOINT((0 0),(90 60))``: the equatorial component came back at
        exactly 10 000 m while the lat-60 component measured 5 009 - 5 016 m —
        a quarter of its intended area — and the pair together held 62.2% of
        two ideal circles, which reads as a mild deficit rather than one
        component being half size.
        """
        wkt = "MULTIPOINT((0 0),(90 60))"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="MultiPoint",
            geometry_type="MULTIPOINT",
            distance=10_000,
        )

        radii = await self._radius_range(test_db_session, out.table_name, wkt)
        assert len(radii) == 2
        for _ix, min_r, max_r in radii:
            assert min_r == pytest.approx(10_000, rel=0.005)
            assert max_r == pytest.approx(10_000, rel=0.005)

    async def test_single_part_output_is_byte_identical_to_the_plain_buffer(
        self,
        test_db_session: AsyncSession,
    ):
        """A single component has nothing to dump into, so the per-component
        pass must not run at all: the saved geometry has to match the bare
        whole-input buffer byte for byte, not merely be spatially equal.

        This is what keeps the fix(#883) exact assertions — and the polar
        POLYGON fixture above — meaningful rather than accidentally satisfied.
        """
        for lon, lat in ((0.0, 45.0), (0.0, 85.06), (0.0, 89.9)):
            out = await _materialize_buffer(
                test_db_session, lon=lon, lat=lat, distance=10_000
            )
            same = (
                await test_db_session.execute(
                    text(
                        "SELECT ST_AsEWKB(geom_4326) = ST_AsEWKB(ST_Buffer("
                        "  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,"
                        "  10000)::geometry) AS identical,"
                        " GeometryType(geom_4326) AS gtype"
                        f" FROM data.{out.table_name}"  # noqa: S608
                    ).bindparams(lon=lon, lat=lat)
                )
            ).one()
            assert same.identical is True, (lon, lat)
            assert same.gtype == "POLYGON", (lon, lat)

    async def test_narrow_multipart_stays_on_the_whole_input_path(
        self,
        test_db_session: AsyncSession,
    ):
        """Below ``BUFFER_LOCAL_SRID_SPAN_DEG`` the whole input already fits one
        UTM zone, so the guard has to decline and leave the cheap path alone —
        measured ±0.04% radius error there, against a dump plus a dissolve per
        row for up to ``MAX_SOURCE_FEATURES['buffer']`` rows.
        """
        wkt = "MULTIPOINT((0 45),(2 45))"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="MultiPoint",
            geometry_type="MULTIPOINT",
            distance=10_000,
        )
        same = (
            await test_db_session.execute(
                text(
                    "SELECT ST_AsEWKB(geom_4326) = ST_AsEWKB(ST_Buffer("
                    "  ST_GeomFromText(:wkt, 4326)::geography, 10000)::geometry)"
                    "   AS identical"
                    f" FROM data.{out.table_name}"  # noqa: S608
                ).bindparams(wkt=wkt)
            )
        ).one()
        assert same.identical is True

    async def test_overlapping_components_are_dissolved_not_stacked(
        self,
        test_db_session: AsyncSession,
    ):
        """The regression the per-component pass would introduce without the
        ``ST_UnaryUnion``.

        Buffering the whole input merges components whose buffers overlap;
        buffering per component and collecting does not. Measured on this
        fixture with the dissolve removed: 3 parts, ``ST_IsValid`` false, and
        935 908 947 m² of area against a true 701 993 608 m² because the
        overlap counted twice. ``ST_MakeValid`` is not a substitute — it cut the
        overlap out of one part instead of merging, landing on 468 078 270 m².
        """
        out = await _materialize_buffer(
            test_db_session,
            wkt="MULTIPOINT((0 45),(0.05 45),(90 45))",
            column_type="MultiPoint",
            geometry_type="MULTIPOINT",
            distance=10_000,
        )
        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(geom_4326) AS gtype,"
                    " ST_NumGeometries(geom_4326) AS parts,"
                    " ST_IsValid(geom_4326) AS valid,"
                    " ST_Area(geom_4326::geography) AS area"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.gtype == "MULTIPOLYGON"
        # The two 0.05°-apart buffers merged; the distant one stayed separate.
        assert row.parts == 2
        assert row.valid is True
        assert row.area == pytest.approx(701_993_608, rel=0.01)

    async def test_seam_component_of_a_wide_multipart_is_still_split(
        self,
        test_db_session: AsyncSession,
    ):
        """Both passes on one feature, in the order that works.

        A MULTIPOINT holding a seam-crossing component and one 100° away trips
        the projection guard AND the fix(#883) seam guard. The seam split has to
        run before the dissolve: unioning a component that still wraps ±180
        raises ``TopologyException: side location conflict`` and aborts the
        statement instead of saving anything.
        """
        wkt = "MULTIPOINT((179.95 45),(80 45))"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="MultiPoint",
            geometry_type="MULTIPOINT",
            distance=10_000,
        )
        row = (
            await test_db_session.execute(
                text(
                    "SELECT GeometryType(geom_4326) AS gtype,"
                    " ST_NumGeometries(geom_4326) AS parts,"
                    " ST_IsValid(geom_4326) AS valid,"
                    " ST_XMin(geom_4326) AS xmin,"
                    " ST_XMax(geom_4326) AS xmax,"
                    " ST_Area(geom_4326::geography) AS area,"
                    " ST_Intersects("
                    "   geom_4326, ST_MakeEnvelope(2, 44.9, 3, 45.1, 4326)"
                    " ) AS hits_france"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        # Seam component cut in two, distant component intact: 3 parts.
        assert row.gtype == "MULTIPOLYGON"
        assert row.parts == 3
        assert row.valid is True
        assert row.xmin >= -180.0
        assert row.xmax <= 180.0
        assert row.hits_france is False
        assert row.area == pytest.approx(2 * math.pi * 10_000**2, rel=0.01)

        radii = await self._radius_range(test_db_session, out.table_name, wkt)
        # The seam component's own part is one half of the split, so only the
        # distant component has a whole circle to measure. Both must be local.
        assert radii
        for _ix, _min_r, max_r in radii:
            assert max_r == pytest.approx(10_000, rel=0.005)


class TestWideSingleComponentBuffer:
    """fix(#902): a SINGLE component wider than one UTM zone was still buffered
    in one non-local projection — per-component dumping (#891/#900) cannot touch
    it because there is nothing to dump into. The wide branch now slices the
    geography-segmentized input into sub-zone longitude bands and dissolves.

    Two metrics, per the issue's warning that pooled area hides the failure:

    - per SOURCE VERTEX: nearest geodesic distance to the buffer boundary,
      asserted within ±1% of the requested distance (the acceptance bar);
    - over the WHOLE boundary: every vertex's distance to the source line,
      bounded to [-2%, +1%]. The floor is looser than the bar deliberately:
      ``ST_UnaryUnion`` nodes adjacent slice buffers and exposes vertices on
      the INTERIOR of circle-approximation chords (sagitta 0.48% at the
      default quad_segs=8, plus the neighbor slice's own ±0.25% projection
      error), which even an exact whole-input buffer exhibits as chord dip —
      its vertices just happen to sit on the circle. Both unfixed failure
      modes sit far outside the bracket: world Mercator produced 7 079 -
      7 087 m (-29%) and the wide Lambert 9 240 - 10 824 m (±8%).
    """

    async def _radius_stats(
        self, session: AsyncSession, table_name: str, source_wkt: str
    ) -> tuple[list[float], float, float]:
        """(per-source-vertex nearest distances, boundary min, boundary max)."""
        per_vertex = [
            float(r[0])
            for r in (
                await session.execute(
                    text(
                        "WITH s AS (SELECT (ST_DumpPoints("
                        "  ST_SetSRID(ST_GeomFromText(:wkt), 4326))).geom AS sv)"
                        " SELECT ST_Distance(s.sv::geography,"
                        "   ST_Boundary(geom_4326)::geography)"
                        f" FROM s, data.{table_name}"  # noqa: S608
                    ).bindparams(wkt=source_wkt)
                )
            ).all()
        ]
        row = (
            await session.execute(
                text(
                    "WITH v AS (SELECT (ST_DumpPoints(geom_4326)).geom AS bv"
                    f"           FROM data.{table_name})"  # noqa: S608
                    " SELECT min(ST_Distance("
                    "   ST_SetSRID(ST_GeomFromText(:wkt), 4326)::geography,"
                    "   v.bv::geography)) AS min_d,"
                    " max(ST_Distance("
                    "   ST_SetSRID(ST_GeomFromText(:wkt), 4326)::geography,"
                    "   v.bv::geography)) AS max_d"
                    " FROM v"
                ).bindparams(wkt=source_wkt)
            )
        ).one()
        return per_vertex, float(row.min_d), float(row.max_d)

    def _assert_radius(self, stats: tuple[list[float], float, float]) -> None:
        per_vertex, min_d, max_d = stats
        assert per_vertex
        for d in per_vertex:
            assert d == pytest.approx(10_000, rel=0.01)
        assert min_d >= 10_000 * 0.98
        assert max_d <= 10_000 * 1.01

    async def test_90_degree_linestring_matches_piecewise_truth(
        self,
        test_db_session: AsyncSession,
    ):
        """The regression fixture from the issue. Measured before the fix:
        85 485 981 084 m² — 63.7% of the 134 146 143 319 m² piecewise truth —
        because a 90° span lands in world Mercator (radius 7 079 - 7 087 m for
        a requested 10 000 m at lat 45)."""
        wkt = "LINESTRING(0 45, 90 45)"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="LineString",
            geometry_type="LINESTRING",
            distance=10_000,
        )
        row = (
            await test_db_session.execute(
                text(
                    "SELECT ST_IsValid(geom_4326) AS valid,"
                    " ST_Area(geom_4326::geography) AS area"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.valid is True
        assert row.area == pytest.approx(134_146_143_319, rel=0.01)
        self._assert_radius(
            await self._radius_stats(test_db_session, out.table_name, wkt)
        )

    async def test_span_past_135_degrees_holds_shape_not_just_area(
        self,
        test_db_session: AsyncSession,
    ):
        """Past ~135° PostGIS climbs into a wide Lambert (999061), which is
        equal-area: total AREA recovers while the shape stays deformed by about
        ±8% (measured 9 240 - 10 824 m radius). So this fixture asserts the
        radius, which an area-only assertion cannot see."""
        wkt = "LINESTRING(-80 45, 80 45)"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="LineString",
            geometry_type="LINESTRING",
            distance=10_000,
        )
        row = (
            await test_db_session.execute(
                text(
                    f"SELECT ST_IsValid(geom_4326) AS valid FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.valid is True
        self._assert_radius(
            await self._radius_stats(test_db_session, out.table_name, wkt)
        )

    async def test_high_latitude_wide_linestring_keeps_its_radius(
        self,
        test_db_session: AsyncSession,
    ):
        """World Mercator's error is 1/cos(latitude), so lat 60 is where the
        unfixed path lost the most (a quarter of the intended area). The bar
        must hold out to high latitudes, per the acceptance criteria."""
        wkt = "LINESTRING(0 60, 150 60)"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="LineString",
            geometry_type="LINESTRING",
            distance=10_000,
        )
        self._assert_radius(
            await self._radius_stats(test_db_session, out.table_name, wkt)
        )

    async def test_seam_crossing_single_linestring_has_no_false_chord(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#902 codex r1): a single geometry that itself crosses the
        antimeridian segmentizes to a vertex jump from ~+180 to ~-180, and a
        planar band cut read that jump as a near-global chord — the buffer
        touched every longitude band. The slice pass unwraps into the shifted
        domain first, so the output is two seam parts and nothing anywhere
        else."""
        wkt = "LINESTRING(170 0, -170 0)"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="LineString",
            geometry_type="LINESTRING",
            distance=10_000,
        )
        row = (
            await test_db_session.execute(
                text(
                    "SELECT ST_IsValid(geom_4326) AS valid,"
                    " GeometryType(geom_4326) AS gtype,"
                    " ST_NumGeometries(geom_4326) AS parts,"
                    " ST_XMin(geom_4326) AS xmin, ST_XMax(geom_4326) AS xmax,"
                    " ST_Area(geom_4326::geography) AS area,"
                    " ST_Intersects(geom_4326,"
                    "   ST_MakeEnvelope(-100, -30, 100, 30, 4326)) AS false_chord"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.valid is True
        assert row.gtype == "MULTIPOLYGON"
        assert row.parts == 2
        assert row.xmin >= -180.0
        assert row.xmax <= 180.0
        # A 20-degree equatorial line: ~2 226 km x 20 km plus the end caps.
        assert row.area == pytest.approx(44_822_856_266, rel=0.01)
        # The old planar cut buffered a chord across the middle of the world.
        assert row.false_chord is False

    async def test_seam_and_greenwich_components_unwrap_independently(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#902 codex r2): a feature holding a seam-crossing component AND
        a Greenwich-crossing one fails a feature-wide unwrap test in both
        domains, which left the seam component's planar chord in place. The
        unwrap decides per component, so the seam component shifts and the
        Greenwich one stays."""
        wkt = "MULTILINESTRING((170 0, -170 0),(-5 0, 5 0))"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="MultiLineString",
            geometry_type="MULTILINESTRING",
            distance=10_000,
        )
        row = (
            await test_db_session.execute(
                text(
                    "SELECT ST_IsValid(geom_4326) AS valid,"
                    " ST_NumGeometries(geom_4326) AS parts,"
                    " ST_Area(geom_4326::geography) AS area,"
                    " ST_Intersects(geom_4326,"
                    "   ST_MakeEnvelope(45, -30, 135, 30, 4326)) AS chord_east,"
                    " ST_Intersects(geom_4326,"
                    "   ST_MakeEnvelope(-135, -30, -45, 30, 4326)) AS chord_west"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.valid is True
        # Two seam parts plus the intact Greenwich part.
        assert row.parts == 3
        # 20-degree + 10-degree equatorial lines, 20 km wide, plus caps.
        assert row.area == pytest.approx(67_447_048_946, rel=0.01)
        assert row.chord_east is False
        assert row.chord_west is False

    async def test_component_crossing_both_meridians_buffers_per_segment(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#902 codex r3): a single component crossing BOTH the
        antimeridian and the prime meridian is wide in either longitude
        domain, so no whole-component unwrap exists — its planar form always
        carries a seam jump. Such a component falls back to per-segment
        buffering (every segmentized segment unwraps on its own evidence), so
        the output is the true corridor: through the WESTERN hemisphere,
        which the path actually traverses, and never the eastern one, where
        the old planar chord landed."""
        wkt = "LINESTRING(170 0, -170 0, -5 0, 5 0)"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="LineString",
            geometry_type="LINESTRING",
            distance=10_000,
        )
        row = (
            await test_db_session.execute(
                text(
                    "SELECT ST_IsValid(geom_4326) AS valid,"
                    " ST_NumGeometries(geom_4326) AS parts,"
                    " ST_Area(geom_4326::geography) AS area,"
                    " ST_Intersects(geom_4326,"
                    "   ST_MakeEnvelope(-135, -30, -45, 30, 4326)) AS through_west,"
                    " ST_Intersects(geom_4326,"
                    "   ST_MakeEnvelope(45, -30, 135, 30, 4326)) AS chord_east"
                    f" FROM data.{out.table_name}"  # noqa: S608
                )
            )
        ).one()
        assert row.valid is True
        assert row.parts == 2
        # 195 degrees of equatorial path, 20 km wide, plus caps.
        assert row.area == pytest.approx(434_433_852_432, rel=0.01)
        assert row.through_west is True
        assert row.chord_east is False

    async def test_wide_polygon_keeps_its_interior_and_planar_shape(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#902 codex r4): polygonal components are densified PLANAR-ly —
        geography-segmentizing a ring reinterprets long planar edges as great
        arcs and moved the region itself (this fixture's lat-45 center fell
        outside its own area). The buffer of a wide polygon must cover the
        polygon, planar edges included."""
        wkt = "POLYGON((0 40, 90 40, 90 50, 0 50, 0 40))"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="Polygon",
            geometry_type="POLYGON",
            distance=10_000,
        )
        row = (
            await test_db_session.execute(
                text(
                    "SELECT ST_IsValid(geom_4326) AS valid,"
                    " ST_Area(geom_4326::geography) AS area,"
                    " ST_Covers(geom_4326,"
                    "   ST_SetSRID(ST_MakePoint(45, 45), 4326)) AS covers_center,"
                    " ST_Covers(geom_4326,"
                    "   ST_GeomFromText(:src, 4326)) AS covers_source"
                    f" FROM data.{out.table_name}"  # noqa: S608
                ).bindparams(src=wkt)
            )
        ).one()
        assert row.valid is True
        assert row.covers_center is True
        # A buffer must contain what it buffers.
        assert row.covers_source is True
        # Planar polygon area (~7.9e12 m²) plus the 10 km rim.
        assert row.area == pytest.approx(8_039_566_379_240, rel=0.01)

    async def test_narrow_single_part_is_still_byte_identical(
        self,
        test_db_session: AsyncSession,
    ):
        """The gate must not fire below the span threshold: a 2°-wide
        LINESTRING keeps the bare whole-input buffer byte for byte. If this
        moves, the gate is wrong — the blast radius accepted for fix(#902) is
        wide inputs only."""
        wkt = "LINESTRING(0 45, 2 45)"
        out = await _materialize_buffer(
            test_db_session,
            wkt=wkt,
            column_type="LineString",
            geometry_type="LINESTRING",
            distance=10_000,
        )
        same = (
            await test_db_session.execute(
                text(
                    "SELECT ST_AsEWKB(geom_4326) = ST_AsEWKB(ST_Buffer("
                    "  ST_GeomFromText(:wkt, 4326)::geography, 10000)::geometry)"
                    "   AS identical"
                    f" FROM data.{out.table_name}"  # noqa: S608
                ).bindparams(wkt=wkt)
            )
        ).one()
        assert same.identical is True


# ---------------------------------------------------------------------------
# Adversarial dissolve by_field and source-shape edges (fix(#699))
# ---------------------------------------------------------------------------


async def _count_analysis_jobs(session: AsyncSession, user_id: uuid.UUID) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(IngestJob)
        .where(
            IngestJob.created_by == user_id,
            IngestJob.user_metadata.has_key("analysis"),
        )
    )


class TestDissolveByFieldAdversarial:
    """`_validate_dissolve_by_field` is the only thing between a caller-chosen
    identifier and a GROUP BY, so the cases that matter are the ones designed
    to slip past it."""

    async def test_injection_payload_is_refused_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The payload is planted in `column_info` so the membership half of
        the check passes: what has to reject it is the identifier regex. The
        refusal happens at enqueue, so no job is created and the CTAS is never
        reached — a later failure would already have cost the queue wait and
        the caller's one analysis slot.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        payload = 'name"; DROP TABLE data.victim; --'
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="POLYGON",
            feature_count=2,
            column_info=[{"name": payload, "type": "text"}],
        )
        jobs_before = await _count_analysis_jobs(test_db_session, admin_id)

        with patch.object(
            router_analysis, "defer_async_with_tenant", AsyncMock()
        ) as mock_defer:
            resp = await client.post(
                _materialize_url(ds.id),
                json={
                    "operation": "dissolve",
                    "by_field": payload,
                    "title": "Injected",
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 422, resp.text
        assert "dissolve column" in resp.json()["detail"]
        mock_defer.assert_not_awaited()
        assert await _count_analysis_jobs(test_db_session, admin_id) == jobs_before

    async def test_reserved_word_column_survives_the_whole_path(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A column named `order` is a legal PostgreSQL identifier, just one
        that has to be quoted everywhere. It must NOT be rejected as a
        precaution, and the quoting has to hold from the enqueue validator
        through the CTAS's SELECT list and GROUP BY.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        await test_db_session.execute(
            text(f'ALTER TABLE data.{ds.table_name} ADD COLUMN "order" TEXT')
        )
        await test_db_session.execute(
            text(f"UPDATE data.{ds.table_name} SET \"order\" = 'first'")  # noqa: S608
        )
        ds.column_info = [{"name": "order", "type": "text"}]
        await test_db_session.commit()

        with patch.object(
            router_analysis, "defer_async_with_tenant", AsyncMock()
        ) as mock_defer:
            resp = await client.post(
                _materialize_url(ds.id),
                json={
                    "operation": "dissolve",
                    "by_field": "order",
                    "title": f"By order {uuid.uuid4().hex[:6]}",
                },
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text
        kwargs = mock_defer.await_args.kwargs
        assert kwargs["by_field"] == "order"

        # Run the worker the enqueue would have queued, so the job reaches a
        # terminal state and the assertion covers the rendered SQL.
        await _materialize(
            job_id=kwargs["job_id"],
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=f"By order {uuid.uuid4().hex[:6]}",
            by_field="order",
        )
        job = await test_db_session.get(IngestJob, uuid.UUID(kwargs["job_id"]))
        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        rows = (
            await test_db_session.execute(
                text(
                    f'SELECT "order", source_count '  # noqa: S608
                    f"FROM data.{new_ds.table_name}"
                )
            )
        ).all()
        assert [(row[0], row[1]) for row in rows] == [("first", 2)]

    async def test_null_group_values_become_their_own_group(
        self,
        test_db_session: AsyncSession,
    ):
        """PostgreSQL groups NULLs together rather than dropping them, so a
        partially populated column yields a NULL-keyed output row. Worth
        pinning because the alternative (silently losing those features) looks
        identical from the job status.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # 'a' keeps its name; 'b' loses it.
        await test_db_session.execute(
            text(
                f"UPDATE data.{ds.table_name} "  # noqa: S608
                f"SET name = NULL WHERE name = 'b'"
            )
        )
        ds.column_info = [{"name": "name", "type": "text"}]
        await test_db_session.commit()
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=f"Grouped {uuid.uuid4().hex[:6]}",
            by_field="name",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT name, source_count FROM data.{new_ds.table_name} "  # noqa: S608
                    f"ORDER BY name NULLS LAST"
                )
            )
        ).all()
        assert [(row[0], row[1]) for row in rows] == [("a", 1), (None, 1)]


class TestMaterializeSourceShapeEdges:
    async def test_empty_source_fails_the_job(
        self,
        test_db_session: AsyncSession,
    ):
        """A 0-row source is legal input with nothing to save. Buffer maps no
        rows to no rows, so the EXISTS probe fails the job with the same
        message an empty result gets — never a registered empty dataset.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_empty_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="buffer",
            title=f"Empty source {uuid.uuid4().hex[:6]}",
            distance_meters=100,
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "no features" in (job.error_message or "")
        assert job.dataset_id is None

    async def test_empty_source_dissolve_fails_rather_than_saving_a_null_row(
        self,
        test_db_session: AsyncSession,
    ):
        """Dissolve without a GROUP BY is an aggregate, so an empty source
        still yields exactly one row — with a NULL geometry. The in-CTAS
        filter plus the post-CTAS DELETE are what keep that row from being
        registered as a dataset.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_empty_dataset(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="dissolve",
            title=f"Empty dissolve {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "no features" in (job.error_message or "")
        assert job.dataset_id is None

    async def test_real_raster_record_is_rejected_at_enqueue(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The write path's non-vector gate, exercised against the row shape
        raster ingest actually writes rather than a synthetic
        `geometry_type=None` dataset."""
        admin_id = await get_user_id(test_db_session, "admin")
        raster = await _create_raster_dataset(test_db_session, created_by=admin_id)
        jobs_before = await _count_analysis_jobs(test_db_session, admin_id)
        resp = await client.post(
            _materialize_url(raster.id),
            json={"operation": "centroid", "title": "From a DEM"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text
        assert "vector" in resp.json()["detail"].lower()
        assert await _count_analysis_jobs(test_db_session, admin_id) == jobs_before

    @pytest.mark.parametrize(
        ("title", "why"),
        [("", "empty"), ("x" * 501, "over the 500-character cap")],
    )
    async def test_title_length_bound_is_enforced_over_http(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        title: str,
        why: str,
    ):
        """AnalysisMaterializeRequest.title carries min_length=1/max_length=500.
        There is a second 500 downstream on the worker's RegisterRequest.title;
        the two agree only by convention, and this bound is the one a client
        can actually reach, so it is the one worth pinning.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        jobs_before = await _count_analysis_jobs(test_db_session, admin_id)
        resp = await client.post(
            _materialize_url(ds.id),
            json={"operation": "centroid", "title": title},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, f"a {why} title was accepted: {resp.text}"
        assert "title" in resp.json()["detail"]
        assert await _count_analysis_jobs(test_db_session, admin_id) == jobs_before

    async def test_title_at_the_cap_is_accepted(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The boundary itself is valid — 500 is the cap, not the first
        rejected length."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        with patch.object(router_analysis, "defer_async_with_tenant", AsyncMock()):
            resp = await client.post(
                _materialize_url(ds.id),
                json={"operation": "centroid", "title": "x" * 500},
                headers=admin_auth_header,
            )
        assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Error-message sanitization (pure, no DB)
# ---------------------------------------------------------------------------


class TestUserErrorMessage:
    def test_db_error_hides_generated_sql(self):
        """fix(#692): SQLAlchemy appends `[SQL: …]` to DB errors — schema and
        table names must never reach GET /jobs/{id}."""
        from sqlalchemy.exc import ProgrammingError

        exc = ProgrammingError(
            'CREATE TABLE "data"."secret_output" AS SELECT 1', {}, Exception("boom")
        )
        msg = _user_error_message(exc)
        assert "secret_output" not in msg
        assert "CREATE TABLE" not in msg

    def test_sqlstate_42_is_named_a_column_problem(self):
        """fix(#766): SQLSTATE class 42 (e.g. no equality operator for
        `json` in a dissolve GROUP BY) is a parameter problem, not a
        generic database error — say so, without leaking the SQL."""
        from sqlalchemy.exc import ProgrammingError

        orig = Exception("could not identify an equality operator for type json")
        orig.sqlstate = "42883"
        exc = ProgrammingError(
            'CREATE TABLE "data"."secret_output" AS SELECT 1', {}, orig
        )
        msg = _user_error_message(exc)
        assert "column" in msg.lower()
        assert "secret_output" not in msg
        assert "CREATE TABLE" not in msg

    def test_other_class_42_states_stay_generic(self):
        """codex(#791): 42501 (privilege), 42P01 (missing table) and the
        like are server/configuration faults — mapping them onto "choose a
        different column" would bury the actionable failure."""
        from sqlalchemy.exc import ProgrammingError

        for sqlstate in ("42501", "42P01", "42601"):
            orig = Exception("boom")
            orig.sqlstate = sqlstate
            exc = ProgrammingError("CREATE TABLE x AS SELECT 1", {}, orig)
            assert _user_error_message(exc) == (
                "The analysis failed due to a database error"
            ), sqlstate

    def test_statement_timeout_is_actionable(self):
        from sqlalchemy.exc import OperationalError

        exc = OperationalError(
            'CREATE TABLE "data"."big_output" AS SELECT 1',
            {},
            Exception("canceling statement due to statement timeout"),
        )
        msg = _user_error_message(exc)
        assert "time limit" in msg
        # fix(v1.6.0 audit D11): the message names the configured limit.
        assert materialize_timeout() in msg
        assert "big_output" not in msg

    def test_domain_errors_pass_through(self):
        msg = _user_error_message(ValueError("Analysis produced no features to save"))
        assert "no features" in msg

    def test_timeout_message_names_the_budget_that_fired(self, monkeypatch):
        """fix(#1013 review): the two budgets are independently configurable
        now, so a registration timeout quoting the materialize budget would
        send an operator to tune the setting that did not fire."""
        from sqlalchemy.exc import OperationalError

        from app.core.config import settings
        from app.processing.analysis.tasks import _user_error_message

        monkeypatch.setattr(settings, "analysis_materialize_timeout_seconds", 300)
        monkeypatch.setattr(settings, "analysis_registration_timeout_seconds", 900)
        exc = OperationalError(
            "SELECT 1", {}, Exception("canceling statement due to statement timeout")
        )

        assert "300s" in _user_error_message(exc)
        assert "900s" not in _user_error_message(exc)
        assert "900s" in _user_error_message(exc, registered=True)
        assert "300s" not in _user_error_message(exc, registered=True)

    def test_analysis_timeouts_track_their_settings(self, monkeypatch):
        """fix(#1013): the budgets are operator settings now, and they are read
        at call time — a module-level snapshot would freeze whatever the
        settings object held when this module was first imported."""
        from app.core.config import settings

        from app.processing.analysis.tasks import registration_timeout

        # Set the baseline rather than asserting the shipped defaults: settings
        # is a module-level singleton, so an ANALYSIS_*_TIMEOUT_SECONDS in the
        # environment or the root .env would already have overridden them and
        # the "before" assertions would fail for a reason unrelated to the
        # behaviour under test.
        monkeypatch.setattr(settings, "analysis_materialize_timeout_seconds", 300)
        monkeypatch.setattr(settings, "analysis_registration_timeout_seconds", 600)
        assert materialize_timeout() == "300s"
        assert registration_timeout() == "600s"
        monkeypatch.setattr(settings, "analysis_materialize_timeout_seconds", 1200)
        monkeypatch.setattr(settings, "analysis_registration_timeout_seconds", 1800)
        assert materialize_timeout() == "1200s"
        assert registration_timeout() == "1800s"


# ---------------------------------------------------------------------------
# work_mem budgeting (pure, no DB)
# ---------------------------------------------------------------------------


class TestMaterializeWorkMem:
    """fix(#1085): the sync half of the #1012 work_mem tests. Their async
    siblings stay in TestMaterializeWorker, which runs _materialize against a
    real table; these only read settings, so they belong beside the other
    pure ones rather than in a class of DB-backed tests."""

    def test_work_mem_is_divided_across_worker_slots(self, monkeypatch):
        """fix(#1012): the budget is per worker PROCESS, so parallel job slots
        share it — otherwise raising WORKER_CONCURRENCY silently multiplies the
        db container's exposure."""
        from app.core.config import settings

        # Set the baseline rather than asserting the shipped default: settings
        # is a module-level singleton, so ANALYSIS_MATERIALIZE_WORK_MEM_MB in
        # the environment would otherwise decide this test's outcome.
        monkeypatch.setattr(settings, "analysis_materialize_work_mem_mb", 64)
        monkeypatch.setattr(settings, "worker_concurrency", 1)
        assert _materialize_work_mem() == "64MB"
        monkeypatch.setattr(settings, "worker_concurrency", 4)
        assert _materialize_work_mem() == "16MB"
        # Divided in kB so the budget is never exceeded by rounding: 64MB
        # across 128 slots is 512kB each, not 1MB each (which would be 128MB
        # against a 64MB budget). No clamp to the bundled 8MB default either —
        # this process cannot read the connected cluster's work_mem, so it
        # cannot know whether such a floor preserves that value or raises it.
        monkeypatch.setattr(settings, "worker_concurrency", 128)
        assert _materialize_work_mem() == "512kB"
        # Sub-megabyte shares are expressed in kB rather than rounded.
        monkeypatch.setattr(settings, "analysis_materialize_work_mem_mb", 1)
        monkeypatch.setattr(settings, "worker_concurrency", 8)
        assert _materialize_work_mem() == "128kB"
        # A share below PostgreSQL's 64kB minimum cannot reach here: it is
        # refused at boot (test_config.py), because neither the minimum nor
        # falling back to the cluster's value honours the budget.

    def test_work_mem_ceiling_is_operator_configurable(self, monkeypatch):
        """fix(#1012 review): the safe value depends on DB_MEM_LIMIT and on how
        many worker services consume the ingest queue, neither of which this
        process can see — DB_MEM_LIMIT is a compose mem_limit and is never in
        this container's environment. A hardcoded ceiling was therefore only
        valid for the default 2 GB single-worker deployment, and could OOM a
        smaller database or a scaled-out one."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "worker_concurrency", 1)
        monkeypatch.setattr(settings, "analysis_materialize_work_mem_mb", 16)
        assert _materialize_work_mem() == "16MB"
        monkeypatch.setattr(settings, "analysis_materialize_work_mem_mb", 256)
        assert _materialize_work_mem() == "256MB"
        # A deliberately small value is honoured, not clamped up: an external
        # cluster may be tuned below the bundled 8MB, and a floor advertised as
        # "leaves the cluster value alone" would silently raise it.
        monkeypatch.setattr(settings, "analysis_materialize_work_mem_mb", 4)
        assert _materialize_work_mem() == "4MB"
        # 0 is the opt-out: no override at all.
        monkeypatch.setattr(settings, "analysis_materialize_work_mem_mb", 0)
        assert _materialize_work_mem() is None
