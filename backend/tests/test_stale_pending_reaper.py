"""fix(#724): the pending reaper must not fail jobs that are genuinely queued.

``fail_stale_jobs`` marked every ``pending`` IngestJob older than
``PENDING_TIMEOUT_SECONDS`` as failed with "never queued". That conflated two
different states, and since fix(#695) deferred analysis to priority -10 —
where waiting behind a steady upload stream is by design and unbounded — the
wrong one became reachable in normal operation.

DB-backed on purpose: the fix is a correlated EXISTS against
``catalog.procrastinate_jobs``, so mocking the session would assert nothing
about whether the SQL is even valid.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from unittest.mock import patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.jobs.models import IngestJob
from tests.factories import get_user_id
from app.platform.jobs.router import (
    PENDING_TIMEOUT_SECONDS,
    fail_stale_jobs,
    get_job_status,
)

pytestmark = pytest.mark.anyio


def _request() -> SimpleNamespace:
    """Minimal Request stand-in; only the owner branch is exercised here."""
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


def _user(user_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


async def _stale_pending_job(
    session: AsyncSession, created_by: uuid.UUID | None = None
) -> IngestJob:
    """A pending job old enough for the reaper to consider it."""
    job = IngestJob(
        source_filename="reaper-test", status="pending", created_by=created_by
    )
    session.add(job)
    await session.flush()
    old = datetime.now(timezone.utc) - timedelta(seconds=PENDING_TIMEOUT_SECONDS + 600)
    await session.execute(
        text(
            "UPDATE catalog.ingest_jobs SET created_at = :old WHERE id = :id"
        ).bindparams(old=old, id=job.id)
    )
    await session.commit()
    # The session is expire_on_commit=False, so the instance still holds the
    # created_at from flush. get_job_status() computes elapsed in PYTHON from
    # that attribute (the sweeper compares in SQL), so without this refresh the
    # poll-path tests silently exercise a job that is not stale at all — and
    # pass for the wrong reason.
    await session.refresh(job)
    return job


async def _queue_procrastinate_job(
    session: AsyncSession, job_id: uuid.UUID, status: str
) -> None:
    # Procrastinate's insert trigger logs to procrastinate_events by unqualified
    # name, so the schema has to be on the search_path or a 'todo' insert fails
    # where a 'doing' one (no event) would succeed.
    await session.execute(text("SET LOCAL search_path TO catalog, public"))
    await session.execute(
        text(
            "INSERT INTO catalog.procrastinate_jobs"
            " (queue_name, task_name, args, status)"
            " VALUES ('default', 'app.processing.analysis.tasks.materialize_analysis',"
            " jsonb_build_object('job_id', :job_id), CAST(:status AS"
            " catalog.procrastinate_job_status))"
        ).bindparams(job_id=str(job_id), status=status)
    )
    await session.commit()


class TestStalePendingReaper:
    async def test_reaps_a_job_that_was_never_queued(
        self, test_db_session: AsyncSession
    ):
        """The genuine orphan: committed, then the defer never landed a row."""
        job = await _stale_pending_job(test_db_session)

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "never queued" in (job.error_message or "")

    @pytest.mark.parametrize("queue_status", ["todo", "doing"])
    async def test_spares_a_job_the_queue_still_holds(
        self, test_db_session: AsyncSession, queue_status: str
    ):
        """Starved, not orphaned — the task is right there in the queue.

        Reachable in normal operation: analysis defers at priority -10, so a
        steady upload stream keeps it in 'todo' indefinitely. Failing it here
        both lies to the user and races the worker, which later picks the task
        up against a row already marked failed.
        """
        job = await _stale_pending_job(test_db_session)
        await _queue_procrastinate_job(test_db_session, job.id, queue_status)

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "pending", job.error_message
        assert job.error_message is None

    @pytest.mark.parametrize("queue_status", ["failed", "cancelled", "succeeded"])
    async def test_reaps_a_job_whose_queue_entry_is_already_terminal(
        self, test_db_session: AsyncSession, queue_status: str
    ):
        """A terminal queue row cannot advance the job, so the row IS stale."""
        job = await _stale_pending_job(test_db_session)
        await _queue_procrastinate_job(test_db_session, job.id, queue_status)

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"

    async def test_leaves_a_recent_pending_job_alone(
        self, test_db_session: AsyncSession
    ):
        """The age test still applies — this guards against over-reaping."""
        job = IngestJob(source_filename="fresh", status="pending")
        test_db_session.add(job)
        await test_db_session.commit()

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "pending"


class TestStatusPollDoesNotReapQueuedJobs:
    """fix(#724 review): the poll path is the one that actually fires.

    get_job_status() runs its own age-only pending auto-fail, and the frontend
    polls it every 2s (useJobStatus / AnalysisJobWatcher). Fixing only the
    periodic sweeper left the whole failure reachable: the first poll after the
    one-hour mark still killed a correctly-queued job.
    """

    async def test_poll_spares_a_job_the_queue_still_holds(
        self, test_db_session: AsyncSession
    ):
        owner = await get_user_id(test_db_session, "admin")
        job = await _stale_pending_job(test_db_session, created_by=owner)
        await _queue_procrastinate_job(test_db_session, job.id, "todo")

        await get_job_status(job.id, _request(), _user(owner), test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "pending", job.error_message
        assert job.error_message is None

    async def test_poll_still_reaps_a_true_orphan(self, test_db_session: AsyncSession):
        owner = await get_user_id(test_db_session, "admin")
        job = await _stale_pending_job(test_db_session, created_by=owner)

        await get_job_status(job.id, _request(), _user(owner), test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "without being processed" in (job.error_message or "")


async def _make_pending_job(session, *, age_seconds: int, file_path: str):
    """A pending job aged past a cutoff, with file_path as given."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select, update

    from app.modules.auth.models import User
    from app.platform.jobs.models import IngestJob

    admin = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    job = IngestJob(
        source_filename="roads.geojson",
        created_by=admin.id,
        status="pending",
        file_path=file_path,
        user_metadata={"presigned": True},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await session.execute(
        update(IngestJob)
        .where(IngestJob.id == job.id)
        .values(created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds))
    )
    await session.commit()
    return job


class TestBoundPendingSweep:
    """fix(#1234): the 1h abandonment clause must not race a completion.

    A presigned completion sets `file_path` and then commits. Between those the
    row is `pending` WITH a `file_path`, and the 1h sweep used to fail it out
    from under the request — the loser is a completion that actually worked.
    The policy itself stays; it just applies only to rows that never bound.
    """

    @staticmethod
    async def _make_job(session, *, age_seconds: int, file_path: str):
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select, update

        from app.modules.auth.models import User
        from app.platform.jobs.models import IngestJob

        admin = (
            await session.execute(select(User).where(User.username == "admin"))
        ).scalar_one()
        job = IngestJob(
            source_filename="roads.geojson",
            created_by=admin.id,
            status="pending",
            file_path=file_path,
            user_metadata={"presigned": True},
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        await session.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(
                created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
            )
        )
        await session.commit()
        return job

    async def test_a_completed_uncommitted_job_survives_the_1h_sweep(
        self, test_db_session
    ) -> None:
        from app.platform.jobs.router import fail_stale_jobs

        job = await self._make_job(
            test_db_session,
            age_seconds=7200,
            file_path="staging/x/frozen/roads.geojson",
        )

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "pending", (
            "the 1h abandonment clause failed a job that had already bound its "
            "bytes — the completion that set file_path was still committing"
        )

    async def test_an_unbound_job_still_fails_at_1h(self, test_db_session) -> None:
        """The policy itself is deliberate and stays."""
        from app.platform.jobs.router import fail_stale_jobs

        job = await self._make_job(test_db_session, age_seconds=7200, file_path="")

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "never queued" in (job.error_message or "")

    async def test_the_sweep_still_fails_a_local_path_bound_job_at_1h(
        self, test_db_session
    ) -> None:
        """The sweep-path twin of the poll case above."""
        from app.platform.jobs.router import fail_stale_jobs

        job = await self._make_job(
            test_db_session, age_seconds=7200, file_path="/tmp/fake.geojson"
        )

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "never queued" in (job.error_message or "")

    async def test_a_bound_pending_row_fails_after_24h(self, test_db_session) -> None:
        """The other half: exempting bound rows from the 1h clause would make
        them immortal, because the retention purge only considers terminal
        rows. The message must not claim the upload never queued."""
        from app.platform.jobs.router import fail_stale_jobs

        job = await self._make_job(
            test_db_session,
            age_seconds=90000,
            file_path="staging/x/frozen/roads.geojson",
        )

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "completed but never committed" in (job.error_message or "")


def test_put_url_ttl_cannot_outlive_the_job() -> None:
    """fix(#1234, #1235 r2): the one-shot PUT URL needed the clamp too.

    Its 3600 default happens to equal today's default timeout, which is what
    hid it: configure the timeout lower and the URL silently outlives the job.
    """
    from app.core.config import settings
    from app.platform.storage.s3 import S3StorageProvider

    provider = S3StorageProvider.__new__(S3StorageProvider)
    captured = {}

    class _Client:
        def generate_presigned_url(self, **kwargs):
            captured.update(kwargs)
            return "https://s3.invalid/put"

    provider.client = _Client()
    provider.bucket = "b"

    with patch.object(settings, "pending_job_timeout_seconds", 900):
        provider.generate_presigned_put_url("staging/x/f.tif")

    assert captured["ExpiresIn"] == 900


def test_part_url_ttl_cannot_outlive_the_job() -> None:
    """fix(#1234): the server was selling 7200s part URLs on a 3600s lifetime."""
    from app.core.config import settings
    from app.platform.storage.s3 import S3StorageProvider

    provider = S3StorageProvider.__new__(S3StorageProvider)
    captured = {}

    class _Client:
        def generate_presigned_url(self, **kwargs):
            captured.update(kwargs)
            return "https://s3.invalid/part"

    provider.client = _Client()
    provider.bucket = "b"

    provider.generate_presigned_part_url("staging/x/f.tif", "upload-1", 1)

    assert captured["ExpiresIn"] == settings.pending_job_timeout_seconds
    assert captured["ExpiresIn"] < 7200


class TestPollingPathHonoursTheSameGuard:
    """fix(#1235 review r2): the POLL is the path that actually fires.

    `get_job_status`'s own comment says so — the frontend polls it every 2s for
    any job it is tracking. #1234 guarded the background sweep and left this
    one on the old predicates, so a poll that blocked on a completing job's row
    lock resumed after the commit and failed the row it had just waited for.
    """

    @staticmethod
    async def _poll(client, headers, job_id):
        return await client.get(f"/jobs/{job_id}", headers=headers)

    async def test_a_poll_does_not_fail_a_bound_pending_job(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="staging/x/frozen/roads.geojson",
        )

        resp = await self._poll(client, admin_auth_header, job.id)

        assert resp.status_code == 200, resp.text
        await test_db_session.refresh(job)
        assert job.status == "pending", (
            "the poll failed a job that had already bound its bytes — the "
            "completion that set file_path was still committing"
        )

    async def test_a_poll_still_fails_an_unbound_pending_job(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """The 1h abandonment policy is deliberate and stays on this path too."""
        job = await _make_pending_job(test_db_session, age_seconds=7200, file_path="")

        resp = await self._poll(client, admin_auth_header, job.id)

        assert resp.status_code == 200, resp.text
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "without being processed" in (job.error_message or "")

    async def test_a_poll_still_fails_a_local_path_bound_job_at_1h(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """fix(#1235 review r2 refinement): the protected class is the
        `staging/` PREFIX, not "file_path is set".

        A direct upload whose dispatch failed binds an ABSOLUTE local path and
        has nothing to do with the completion race. Giving it the 24h backstop
        would leave it pending for a day, and /jobs/{id}/retry is unavailable
        until a job is `failed` — turning 1h-to-recoverable into
        24h-to-recoverable on a real path.
        """
        job = await _make_pending_job(
            test_db_session, age_seconds=7200, file_path="/tmp/fake.geojson"
        )

        resp = await self._poll(client, admin_auth_header, job.id)

        assert resp.status_code == 200, resp.text
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "without being processed" in (job.error_message or "")

    async def test_a_poll_fails_a_bound_pending_job_after_24h(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """The backstop reaches this path as well, with the honest message."""
        job = await _make_pending_job(
            test_db_session,
            age_seconds=90000,
            file_path="staging/x/frozen/roads.geojson",
        )

        resp = await self._poll(client, admin_auth_header, job.id)

        assert resp.status_code == 200, resp.text
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "completed but never committed" in (job.error_message or "")


def test_every_pending_fail_site_uses_the_shared_clauses() -> None:
    """fix(#1235 review r2): the census, pinned.

    Four sites flip pending -> failed on a timeout and #1234 guarded two. This
    asserts no site reconstructs the predicates inline, so a fifth cannot be
    added past the guard by being written carefully.

    KNOWN BLIND SPOT: this greps source, so it catches a NEW inline predicate
    set but not a call that is present-yet-unreachable. The behavioural tests
    above are what fail in that case.
    """
    import inspect

    from app.platform.jobs import router as jobs_router
    from app.platform.jobs import worker as jobs_worker

    for module in (jobs_router, jobs_worker):
        source = inspect.getsource(module)
        # The only legitimate definition site is the helper itself.
        inline = source.count('IngestJob.status == "pending",')
        allowed = 1 if module is jobs_router else 0
        assert inline == allowed, (
            f"{module.__name__} builds the pending-fail predicates inline "
            f"({inline} occurrences, expected {allowed}) — route it through "
            "stale_pending_clauses instead"
        )
