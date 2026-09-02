"""fix(#724): the pending reaper must not fail jobs that are genuinely queued.

``fail_stale_jobs`` marked every ``pending`` IngestJob older than
``stale_pending_cutoff_seconds`` as failed with "never queued". That conflated two
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
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import MIN_SIGNABLE_JOB_LIFETIME_SECONDS, settings
from app.platform.jobs.models import IngestJob
from tests.factories import get_user_id
from app.platform.jobs.router import (
    fail_stale_jobs,
    get_job_status,
    post_expiry_sweep_after_seconds,
    stale_pending_cutoff_seconds,
)
from app.processing.ingest.presigned import require_signable_job_lifetime

pytestmark = pytest.mark.anyio


def _request() -> SimpleNamespace:
    """Minimal Request stand-in; only the owner branch is exercised here."""
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


def _user(user_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _dispatched_metadata() -> dict:
    """The `user_metadata` a row carries once a dispatch has been attempted.

    fix(#1744): `defer_with_orphan_guard` stamps `commit_attempted_at` before
    every defer, so a row that reached the queue at all has this key. Its
    absence is now what makes the sweep read a row as an abandoned upload, so
    a fixture describing "the defer never landed" has to carry it or it
    describes something else.
    """
    from app.platform.jobs.models import COMMIT_ATTEMPTED_METADATA_KEY

    return {COMMIT_ATTEMPTED_METADATA_KEY: datetime.now(timezone.utc).isoformat()}


async def _stale_pending_job(
    session: AsyncSession,
    created_by: uuid.UUID | None = None,
    *,
    commit_attempted: bool = True,
) -> IngestJob:
    """A pending job old enough for the reaper to consider it.

    Dispatch-attempted by default: every test in this class is about the
    live-queue predicate, and the row it reasons about is one whose task was
    deferred (or whose defer died), not an upload nobody committed.
    """
    job = IngestJob(
        source_filename="reaper-test",
        status="pending",
        created_by=created_by,
        user_metadata=_dispatched_metadata() if commit_attempted else {},
    )
    session.add(job)
    await session.flush()
    old = datetime.now(timezone.utc) - timedelta(
        seconds=stale_pending_cutoff_seconds(completion_bound=False) + 600
    )
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


async def _make_pending_job(
    session,
    *,
    age_seconds: int,
    file_path: str,
    presigned: bool = True,
    source_url: str | None = None,
    commit_attempted: bool = False,
):
    """A pending job aged past a cutoff, with file_path as given.

    fix(#1556): `presigned` is now a parameter because it discriminates two
    classes that both reach the unbound half. Default True keeps every existing
    caller describing the presigned upload it already described.

    fix(#1744): `commit_attempted` is what discriminates them now. Default
    False, because the rows these fixtures describe are mostly ones nobody
    dispatched; a caller that means "the defer never landed" passes True.
    """
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
        source_url=source_url,
        user_metadata={
            **({"presigned": True} if presigned else {}),
            **(_dispatched_metadata() if commit_attempted else {}),
        },
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
    async def _make_job(
        session,
        *,
        age_seconds: int,
        file_path: str,
        presigned: bool = True,
        commit_attempted: bool = False,
    ):
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
            user_metadata={
                **({"presigned": True} if presigned else {}),
                **(_dispatched_metadata() if commit_attempted else {}),
            },
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

    async def test_an_unbound_job_is_still_settled_at_1h(self, test_db_session) -> None:
        """The policy itself is deliberate and stays.

        fix(#1556): the TERMINAL STATE moved for this row and only this row —
        a presigned upload with nothing bound is an abandonment, not a failed
        ingest. The 1h clause, the class it selects and the sites that apply it
        are all untouched; see TestAbandonedUploadsAreCancelled for the split.
        """
        from app.platform.jobs.router import fail_stale_jobs

        job = await self._make_job(test_db_session, age_seconds=7200, file_path="")

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        assert "Abandoned" in (job.error_message or "")

    async def test_an_unbound_non_presigned_job_still_fails_at_1h(
        self, test_db_session
    ) -> None:
        """The other side of the same fork: an analysis run or an embedding
        backfill also carries `file_path=""`, and a dispatch that never landed
        is a real failure of something the user asked for.

        fix(#1744): the row says so itself now. Both of those doors reach the
        queue through the guard that stamps `commit_attempted_at`, so a defer
        that died still leaves the stamp behind."""
        from app.platform.jobs.router import fail_stale_jobs

        job = await self._make_job(
            test_db_session,
            age_seconds=7200,
            file_path="",
            presigned=False,
            commit_attempted=True,
        )

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
            test_db_session,
            age_seconds=7200,
            file_path="/tmp/fake.geojson",
            commit_attempted=True,
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

    async def test_a_poll_still_settles_an_unbound_pending_job(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """The 1h abandonment policy is deliberate and stays on this path too.

        fix(#1556): terminal state only — this row is a presigned upload with
        nothing bound, so the poll settles it `cancelled` exactly as the
        background sweep does. The non-presigned twin below keeps `failed`.
        """
        job = await _make_pending_job(test_db_session, age_seconds=7200, file_path="")

        resp = await self._poll(client, admin_auth_header, job.id)

        assert resp.status_code == 200, resp.text
        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        assert "Abandoned" in (job.error_message or "")

    async def test_a_poll_still_fails_an_unbound_non_presigned_job(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """The poll keeps its own elapsed-seconds wording for everything that
        is not an abandoned upload."""
        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="",
            presigned=False,
            commit_attempted=True,
        )

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
            test_db_session,
            age_seconds=7200,
            file_path="/tmp/fake.geojson",
            commit_attempted=True,
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


class TestAbandonedUploadsAreCancelled:
    """fix(#1556): a presigned upload nobody ever bound bytes to is not a
    failed ingest.

    On the public demo two rows (uls.csv, 2026-08-18) sat in the admin jobs
    list as `failed` with "Stale: pending too long (never queued)" — a visitor
    asked for a presigned URL and walked away. Nothing was ever attempted, so
    they were indistinguishable from real ingest failures in the failed-jobs
    badge and in operator triage.

    `cancelled` is already in the `ingest_jobs` status CHECK constraint, in the
    admin `JobStatus` literal and in openapi.json, so this is a state change
    and not a schema or contract change.
    """

    async def test_the_sweep_cancels_an_abandoned_upload(self, test_db_session) -> None:
        from app.platform.jobs.router import fail_stale_jobs

        job = await _make_pending_job(test_db_session, age_seconds=7200, file_path="")

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        assert job.error_message == "Abandoned: upload was never completed"
        assert job.completed_at is not None

    async def test_a_service_import_awaiting_retry_still_fails(
        self, test_db_session
    ) -> None:
        """The reason the class is not "falsy file_path".

        A service/URL import that was never queued is unbound too, and it IS
        recoverable — but `/jobs/{id}/retry` and `_retry_capability` both
        require status `failed`, so cancelling it would take its only recovery
        path away.
        """
        from app.platform.jobs.router import fail_stale_jobs, get_retry_capability

        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="",
            presigned=False,
            source_url="https://example.test/roads.geojson",
            commit_attempted=True,
        )

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "never queued" in (job.error_message or "")
        can_retry, reason = await get_retry_capability(job)
        assert can_retry, f"the retry path was lost: {reason}"

    async def test_a_direct_upload_with_a_real_file_still_fails(
        self, test_db_session
    ) -> None:
        """#1235's absolute-path class, unchanged: a real file exists and
        retry matters, so the row must stay `failed`.

        fix(#1744): what keeps it failed is the stamp, not the path. The same
        absolute path with no stamp is an upload nobody committed, which the
        test below covers."""
        from app.platform.jobs.router import fail_stale_jobs

        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="/tmp/fake.geojson",
            commit_attempted=True,
        )

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "never queued" in (job.error_message or "")

    async def test_the_bound_half_is_untouched(self, test_db_session) -> None:
        """The 24h backstop keeps writing `failed` with its own message: a
        completion that bound bytes and then stalled IS a failure."""
        from app.platform.jobs.router import fail_stale_jobs

        job = await _make_pending_job(
            test_db_session,
            age_seconds=90000,
            file_path="staging/x/frozen/roads.geojson",
        )

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "completed but never committed" in (job.error_message or "")

    async def test_the_running_lease_sweep_is_untouched(self, test_db_session) -> None:
        """The stale-RUNNING path shares the function, not the values."""
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import update

        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.router import fail_stale_jobs

        job = await _make_pending_job(test_db_session, age_seconds=7200, file_path="")
        await test_db_session.execute(
            update(IngestJob)
            .where(IngestJob.id == job.id)
            .values(
                status="running",
                started_at=datetime.now(timezone.utc) - timedelta(seconds=7200),
            )
        )
        await test_db_session.commit()

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert "running for over" in (job.error_message or "")

    async def test_the_worker_startup_recovery_cancels_it_too(
        self, test_db_session
    ) -> None:
        """The third site. It settles the same rows with the same clauses, and
        it is the pass that actually reaches a row after a hard restart."""
        from app.platform.jobs.worker import recover_stale_jobs

        abandoned = await _make_pending_job(
            test_db_session, age_seconds=7200, file_path=""
        )
        dispatched = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="",
            presigned=False,
            commit_attempted=True,
        )

        await recover_stale_jobs()

        test_db_session.expire_all()
        await test_db_session.refresh(abandoned)
        await test_db_session.refresh(dispatched)
        assert abandoned.status == "cancelled", (
            "the worker's startup recovery still reports an abandoned upload "
            "as a failed ingest"
        )
        assert abandoned.error_message == "Abandoned: upload was never completed"
        assert dispatched.status == "failed"
        assert "never queued" in (dispatched.error_message or "")

    async def test_the_outcome_counts_cancellations_apart_from_failures(
        self, test_db_session
    ) -> None:
        """fix(#1556 review, codex P2): settling the row was only half of it.

        `pending_failed` is read as a failure count by the admin cleanup
        response, by its `job.cleanup_stale` audit event and by the sweeper's
        log line. Leaving abandoned uploads inside it undoes the split at
        exactly the surfaces the split exists for — the row would say
        `cancelled` while the pass that wrote it still reported a failure.
        """
        from app.platform.jobs.router import fail_stale_jobs

        # The test database is shared across every test on this xdist worker
        # (see conftest's isolation note), so drain whatever is already stale
        # before counting. Without this the assertions below measure other
        # tests' leftovers.
        await fail_stale_jobs(test_db_session)

        await _make_pending_job(test_db_session, age_seconds=7200, file_path="")
        await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="",
            presigned=False,
            commit_attempted=True,
        )

        outcome = await fail_stale_jobs(test_db_session, detailed=True)

        assert outcome.pending_cancelled == 1
        assert outcome.pending_failed == 1, (
            "the abandoned upload is still being counted as a failure"
        )
        assert outcome.total_cleaned == outcome.pending_failed + outcome.running_failed
        # Work done, not failures: a pass that cancelled a row mutated it.
        assert outcome.total_affected >= outcome.total_cleaned + 1
        detail = outcome.as_dict()
        assert detail["pending_cancelled"] == 1
        assert detail["pending_failed"] == 1

    async def test_a_cancelled_job_cannot_be_completed(self) -> None:
        """The completion door reads the sweep's terminal state.

        `require_completable_presigned_job` refuses a settled job precisely
        because the PUT URL outlives the 1h clause, so a client can still
        re-PUT and complete. Reading only `failed` would have reopened that
        hole for the one class that reaches it without any door stamping it.
        """
        from app.processing.ingest.presigned import require_completable_presigned_job

        job = SimpleNamespace(file_path="", status="cancelled")
        with pytest.raises(HTTPException) as exc:
            require_completable_presigned_job(job, restart_hint="Start again.")
        assert exc.value.status_code == 400
        assert "cancelled" in exc.value.detail.lower()

    @pytest.mark.parametrize(
        "user_metadata,abandoned",
        [
            ({"presigned": True}, True),
            ({}, True),
            (None, True),
            ({"analysis": True}, True),
            ({"commit_attempted_at": "2026-09-01T12:00:00+00:00"}, False),
            ({"presigned": True, "commit_attempted_at": "2026-09-01T12:00:00Z"}, False),
            (
                {"embedding_backfill": {}, "commit_attempted_at": "2026-09-01T12:00Z"},
                False,
            ),
            ({"commit_attempted_at": ""}, True),
            ({"commit_attempted_at": None}, True),
        ],
    )
    def test_the_python_twin_agrees_with_the_sql_predicate(
        self, user_metadata, abandoned
    ) -> None:
        """The worker mirrors the UPDATE onto ORM instances, so the two
        expressions of one rule must not drift. Enumerated over every shape a
        pending row can carry, not just the reported one.

        fix(#1744): the shapes that matter are now what the metadata says,
        not what `file_path` looks like, so the empty and absent stamps are
        enumerated alongside the present one. Both expressions coalesce a
        missing or empty value to "no dispatch was attempted", which is the
        conservative reading for a row that never got a real timestamp.
        """
        from app.platform.jobs.router import is_abandoned_upload

        assert is_abandoned_upload(user_metadata) is abandoned


def test_the_published_cleanup_response_drops_the_new_count_without_raising() -> None:
    """fix(#1556 review, codex P2): the boundary, pinned deliberately.

    `pending_cancelled` reaches the audit event's `details` (a JSONB blob with
    no schema) and the multi-tenant fleet totals. It stops at
    `StaleCleanupResponse`, which is published in openapi.json and generated
    into both SDKs and `api.generated.ts` — adding a field there is a contract
    change with a regen attached, and it is a decision to take on its own
    rather than a side effect of this one.

    The endpoint builds that model with `StaleCleanupResponse(**details)`, so
    the half that MUST hold is that the extra key is ignored rather than
    refused: an `extra="forbid"` added later (six sibling models in that file
    have it) would turn every cleanup call into a 500.
    """
    from app.platform.jobs.schemas import StaleCleanupResponse
    from app.platform.jobs.sweep import StaleCleanupOutcome

    outcome = StaleCleanupOutcome(
        pending_failed=1,
        running_failed=0,
        vrt_assets_recovered=0,
        vrt_generations_failed=0,
        terminal_jobs_purged=0,
        staged_paths_considered=0,
        local_files_reaped=0,
        storage_objects_reaped=0,
        staged_paths_skipped=0,
        staged_cleanup_failures=0,
        pending_cancelled=2,
    )
    details = outcome.as_dict()
    assert details["pending_cancelled"] == 2
    assert details["pending_failed"] == 1
    assert details["total_cleaned"] == 1, "cancellations must not inflate the failures"
    assert details["total_affected"] == 3, "cancellations are work the pass did"

    response = StaleCleanupResponse(**details)
    assert response.pending_failed == 1
    assert not hasattr(response, "pending_cancelled")


def test_every_unbound_pending_site_uses_the_shared_action() -> None:
    """fix(#1556): the census again, for the ACTION this time.

    The clause helper stopped a fifth site from reconstructing the predicates.
    The same argument applies to what a site WRITES: three of them settle an
    unbound pending row, and a split applied at one while the others keep
    writing `failed` makes the same abandoned upload report two different
    terminal states depending on which actor reached it first.
    """
    import inspect

    from app.platform.jobs import router as jobs_router
    from app.platform.jobs import sweep as jobs_sweep
    from app.platform.jobs import worker as jobs_worker

    for module in (jobs_router, jobs_sweep, jobs_worker):
        assert "stale_pending_unbound_values" in inspect.getsource(module), (
            f"{module.__name__} settles unbound pending rows without the "
            "shared action helper"
        )


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
    from app.platform.jobs import sweep as jobs_sweep
    from app.platform.jobs import worker as jobs_worker

    for module in (jobs_router, jobs_sweep, jobs_worker):
        source = inspect.getsource(module)
        # The only legitimate definition site is the helper itself — moved
        # from router.py into sweep.py by #1335's recovery/sweep split.
        inline = source.count('IngestJob.status == "pending",')
        allowed = 1 if module is jobs_sweep else 0
        assert inline == allowed, (
            f"{module.__name__} builds the pending-fail predicates inline "
            f"({inline} occurrences, expected {allowed}) — route it through "
            "stale_pending_clauses instead"
        )


class TestUrlExpiryAnchorsToTheJobDeadline:
    """fix(#1235 review r3): URL expiry anchored at SIGNING time while the job
    deadline anchors at created_at, so the two drifted by the in-request time
    between the job INSERT and each signature — and the part loop signs
    sequentially, so a many-part file's last URLs drifted furthest. In that gap
    S3 accepts bytes the sweep is already entitled to fail the job for.

    Unit-level on the helper because the drift is a property of the arithmetic,
    not of any one door; both doors call it and the fakes in the contract
    suites record what they were handed.
    """

    @staticmethod
    def _backdated(minutes: int):
        from datetime import datetime, timedelta, timezone

        return datetime.now(timezone.utc) - timedelta(minutes=minutes)

    def test_a_ten_minute_old_job_gets_the_remaining_lifetime(self) -> None:
        from app.core.config import settings
        from app.processing.ingest.presigned import remaining_job_lifetime_seconds

        with patch.object(settings, "pending_job_timeout_seconds", 3600):
            ttl = remaining_job_lifetime_seconds(self._backdated(10))

        # 3600 - 600 = 3000. (The review's "~2400" example implies a 20-minute
        # backdate; the arithmetic here is deliberate and checked.)
        assert 2995 <= ttl <= 3000, (
            f"expected ~3000s of remaining lifetime, got {ttl} — the URL is "
            "anchored to signing time, not to the job deadline"
        )

    def test_a_fresh_job_gets_very_nearly_the_whole_window(self) -> None:
        """The other direction: anchoring must not shorten a fresh job's URL."""
        from app.core.config import settings
        from app.processing.ingest.presigned import remaining_job_lifetime_seconds

        with patch.object(settings, "pending_job_timeout_seconds", 3600):
            ttl = remaining_job_lifetime_seconds(self._backdated(0))

        assert 3595 <= ttl <= 3600, ttl

    def test_a_job_past_its_deadline_reports_a_negative_remainder(self) -> None:
        """fix(#1235 review r4): the helper must not launder a dead job into a
        live URL. It used to floor at 1, which reads as "expired on arrival" and
        is the opposite: ExpiresIn is relative to SIGNING time, so 1 buys the
        client one more usable second past the deadline."""
        from app.core.config import settings
        from app.processing.ingest.presigned import remaining_job_lifetime_seconds

        with patch.object(settings, "pending_job_timeout_seconds", 3600):
            ttl = remaining_job_lifetime_seconds(self._backdated(120))

        assert ttl < 0, (
            f"expected a negative remainder for a job 2h past a 1h deadline, "
            f"got {ttl} — a floored value becomes a signable, USABLE ExpiresIn"
        )

    def test_the_window_shrinks_with_a_lowered_timeout(self) -> None:
        """The drift scales as an operator lowers the timeout, which is what
        makes this worth fixing rather than tolerating."""
        from app.core.config import settings
        from app.processing.ingest.presigned import remaining_job_lifetime_seconds

        with patch.object(settings, "pending_job_timeout_seconds", 900):
            ttl = remaining_job_lifetime_seconds(self._backdated(10))

        assert 295 <= ttl <= 300, ttl


class TestEveryLifetimeTimerDerivesFromTheOneSetting:
    """fix(#1235 review r4): #1234 made the pending lifetime configurable and
    converted only some of the consumers of the numbers that used to be its
    fixed value. Each survivor broke differently once an operator moved it, so
    what is asserted here is the closure — every lifetime-derived timer moves
    with the setting — rather than three particular call sites being patched.

    ``JOB_TIMEOUT_SECONDS`` is deliberately absent: it is the worker lease on a
    RUNNING job, and it shares a number with the default upload lifetime and
    nothing else.
    """

    def test_the_unbound_cutoff_is_the_setting(self) -> None:
        with patch.object(settings, "pending_job_timeout_seconds", 12345):
            assert stale_pending_cutoff_seconds(completion_bound=False) == 12345

    def test_the_bound_backstop_stays_beyond_the_upload_lifetime(self) -> None:
        """The 24h backstop was a fixed 86400. Configure the timeout past a day
        and a legitimate completion at hour 25 committed the frozen path into a
        row that was instantly eligible for its own backstop."""
        long_timeout = 100_000  # ~27.8h, comfortably past the old fixed 86400
        with patch.object(settings, "pending_job_timeout_seconds", long_timeout):
            cutoff = stale_pending_cutoff_seconds(completion_bound=True)

        assert cutoff > long_timeout, (
            f"the bound backstop ({cutoff}s) is not beyond the upload lifetime "
            f"({long_timeout}s) — a completion arriving inside its own still-"
            "valid window is immediately sweepable"
        )

    def test_the_bound_backstop_default_is_unchanged(self) -> None:
        """Deriving it must not move the shipped 24h behaviour."""
        with patch.object(settings, "pending_job_timeout_seconds", 3600):
            assert stale_pending_cutoff_seconds(completion_bound=True) == 86400

    def test_the_post_expiry_sweep_waits_out_the_configured_url(self) -> None:
        """fix(#1235 review r4): this cutoff derived from a fixed 3600. With a
        longer timeout the sweep ran while the PUT URL was still live, and the
        reaped marker takes the row out of every later pass — so an object
        recreated after it survived forever."""
        with patch.object(settings, "pending_job_timeout_seconds", 100_000):
            assert post_expiry_sweep_after_seconds() > 100_000

    def test_the_post_expiry_sweep_default_is_unchanged(self) -> None:
        with patch.object(settings, "pending_job_timeout_seconds", 3600):
            assert post_expiry_sweep_after_seconds() == 4500


class TestPresignRefusesRatherThanSigningADeadWindow:
    """fix(#1235 review r4): there is no ExpiresIn that means "already dead".

    The helper used to floor the remaining lifetime at 1, described as a URL
    "expired on arrival". ExpiresIn is relative to SIGNING time, so that floor
    minted a URL usable for one more second past the deadline the change exists
    to enforce. The only way not to hand out a live URL is not to sign one.
    """

    @staticmethod
    def _backdated(seconds: int):
        return datetime.now(timezone.utc) - timedelta(seconds=seconds)

    def test_a_healthy_job_gets_its_remaining_lifetime(self) -> None:
        with patch.object(settings, "pending_job_timeout_seconds", 3600):
            ttl = require_signable_job_lifetime(self._backdated(600))

        assert 2995 <= ttl <= 3000, ttl

    def test_a_job_past_its_deadline_is_refused(self) -> None:
        with patch.object(settings, "pending_job_timeout_seconds", 3600):
            with pytest.raises(HTTPException) as excinfo:
                require_signable_job_lifetime(self._backdated(7200))

        assert excinfo.value.status_code == 409, (
            "a job past its deadline was signed for anyway — any positive "
            "ExpiresIn hands the client a URL that still works"
        )

    def test_a_sliver_of_lifetime_is_refused_too(self) -> None:
        """A URL with seconds left is not a shorter upload window, it is a
        failure the client cannot tell apart from a broken server."""
        with patch.object(settings, "pending_job_timeout_seconds", 3600):
            with pytest.raises(HTTPException):
                require_signable_job_lifetime(
                    self._backdated(3600 - MIN_SIGNABLE_JOB_LIFETIME_SECONDS + 5)
                )


class TestThePollPathSkipsUpdatesItCannotMatch:
    """fix(#1235 review r4): the r2 rewrite dropped the outer elapsed check, so
    BOTH pending UPDATEs ran on every 2s poll of every pending job. The DB
    predicates remain the authority; the elapsed check is a fast-path skip.
    """

    @staticmethod
    def _updates(statements: list[str]) -> list[str]:
        return [s for s in statements if s.lstrip().upper().startswith("UPDATE")]

    async def _poll_recording_statements(self, session, job) -> list[str]:
        seen: list[str] = []
        real = session.execute

        async def _recording(statement, *args, **kwargs):
            seen.append(str(statement))
            return await real(statement, *args, **kwargs)

        with patch.object(session, "execute", _recording):
            await get_job_status(job.id, _request(), _user(job.created_by), session)
        return seen

    async def test_a_young_pending_job_costs_no_updates(
        self, test_db_session: AsyncSession
    ) -> None:
        job = await _make_pending_job(test_db_session, age_seconds=30, file_path="")

        statements = await self._poll_recording_statements(test_db_session, job)

        assert self._updates(statements) == [], (
            "a 30-second-old pending job issued stale-pending UPDATEs on a "
            "routine poll, and the frontend polls this route every 2s"
        )

    async def test_a_genuinely_stale_job_is_still_settled(
        self, test_db_session: AsyncSession
    ) -> None:
        """The skip must not become the guard: past the cutoff the UPDATE runs
        and the row goes terminal exactly as before (fix(#1556): `cancelled`
        for this presigned-and-unbound row)."""
        job = await _make_pending_job(test_db_session, age_seconds=7200, file_path="")

        statements = await self._poll_recording_statements(test_db_session, job)

        assert self._updates(statements), "the stale job was never updated"
        await test_db_session.refresh(job)
        assert job.status == "cancelled"


class TestAbandonedDirectUploadsAreCancelled:
    """fix(#1744): the door #1556 did not reach.

    `POST /ingest/upload` says it in its own docstring: it stages the file and
    does NOT auto-queue, so a `pending` row with no Procrastinate job is the
    normal state between upload and commit. When the owner walks away at the
    preview step, the row settles at the pending timeout as `failed` with
    "never queued", pointing at a queue that is working correctly.

    #1556 fixed exactly this reasoning for the presign doors, but keyed the
    carve-out to the `presigned` marker plus an empty `file_path`. A direct
    upload binds an absolute staging path and stamps no such marker, so it
    matched neither half: on the demo, four of six failed jobs were abandoned
    direct uploads by three different users over two weeks, and zero were
    broken commits.

    The split is now the stamp `defer_with_orphan_guard` writes, so the two
    classes are told apart by whether a dispatch was attempted rather than by
    the shape of a path they can both carry.
    """

    async def test_the_sweep_cancels_an_abandoned_direct_upload(
        self, test_db_session
    ) -> None:
        from app.platform.jobs.router import fail_stale_jobs

        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="/app/staging/abc_uls.csv",
            presigned=False,
        )

        await fail_stale_jobs(test_db_session)

        await test_db_session.refresh(job)
        assert job.status == "cancelled", (
            "an upload nobody ever committed is still reported as a failed "
            "ingest, which is what inflates the admin failed-jobs badge"
        )
        assert job.error_message == "Abandoned: upload was never completed"
        assert job.completed_at is not None

    async def test_a_poll_cancels_an_abandoned_direct_upload(
        self, client, admin_auth_header, test_db_session
    ) -> None:
        """The second site, and the one that usually gets there first: the
        frontend polls this route every 2s for any job it is tracking."""
        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="/app/staging/abc_uls.csv",
            presigned=False,
        )

        resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)

        assert resp.status_code == 200, resp.text
        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        assert job.error_message == "Abandoned: upload was never completed"

    async def test_the_worker_startup_recovery_cancels_it_too(
        self, test_db_session
    ) -> None:
        """The third site. After a hard restart it is the pass that reaches the
        row, and once it has made the row terminal no later sweep looks at it
        again."""
        from app.platform.jobs.worker import recover_stale_jobs

        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="/app/staging/abc_uls.csv",
            presigned=False,
        )

        await recover_stale_jobs()

        test_db_session.expire_all()
        await test_db_session.refresh(job)
        assert job.status == "cancelled"
        assert job.error_message == "Abandoned: upload was never completed"

    @pytest.mark.parametrize("site", ["sweep", "poll", "recovery"])
    async def test_a_dispatched_direct_upload_stays_failed_and_retryable(
        self, client, admin_auth_header, test_db_session, tmp_path, site
    ) -> None:
        """The class the split exists to protect, at all three sites.

        A commit whose dispatch died leaves the same absolute path on the same
        `pending` row. It must keep reporting `failed`, because that is the
        only status `/jobs/{id}/retry` accepts, and cancelling it would take a
        recoverable job's only recovery path away (the trap #1235 avoided).

        The staged file is real because `_retry_capability` reads it: a
        `failed` status alone is not the retry affordance, it is half of it.
        """
        from app.platform.jobs.router import fail_stale_jobs, get_retry_capability
        from app.platform.jobs.worker import recover_stale_jobs

        staged = tmp_path / "abc_uls.csv"
        staged.write_text("id,name\n1,a\n", encoding="utf-8")
        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path=str(staged),
            presigned=False,
            commit_attempted=True,
        )

        if site == "sweep":
            await fail_stale_jobs(test_db_session)
        elif site == "poll":
            resp = await client.get(f"/jobs/{job.id}", headers=admin_auth_header)
            assert resp.status_code == 200, resp.text
        else:
            await recover_stale_jobs()
            test_db_session.expire_all()

        await test_db_session.refresh(job)
        assert job.status == "failed", (
            "a commit whose dispatch died was reported as an abandoned upload"
        )
        message = job.error_message or ""
        assert "never queued" in message or "without being processed" in message
        can_retry, reason = await get_retry_capability(job)
        assert can_retry, f"the retry path was lost: {reason}"

    async def test_the_stamp_survives_the_settlement_a_retry_reads(
        self, test_db_session
    ) -> None:
        """`/jobs/{id}/retry` resets the row to `pending` and re-queues it
        through the same guard, and neither it nor the sweep clears metadata.
        If the stamp did not survive being settled, a retry whose dispatch also
        died would come back as a cancellation on the second pass and lose the
        retry affordance the first pass kept.
        """
        from app.platform.jobs.models import COMMIT_ATTEMPTED_METADATA_KEY
        from app.platform.jobs.router import fail_stale_jobs

        job = await _make_pending_job(
            test_db_session,
            age_seconds=7200,
            file_path="/app/staging/abc_uls.csv",
            presigned=False,
            commit_attempted=True,
        )

        await fail_stale_jobs(test_db_session)
        await test_db_session.refresh(job)
        assert job.status == "failed"
        assert (job.user_metadata or {}).get(COMMIT_ATTEMPTED_METADATA_KEY)
