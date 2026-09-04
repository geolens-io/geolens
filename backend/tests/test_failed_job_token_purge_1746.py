"""fix(#1746) finding 2: a failed queue row must not keep the service token.

With no credential store configured — the default, since `.env.example` ships
`REDIS_URL` commented out — the import-commit and reupload-commit doors hand
the service tasks a raw `token` in the job kwargs. The worker deletes
SUCCESSFUL rows only, so a terminal failure used to leave
`catalog.procrastinate_jobs.args->>'token'` holding the secret for the whole
retention window, and forever when retention is off.

Two defenses, one test module: the task strips its own row on the way out
(`purge_token_on_failure`), and `purge_terminal_job_tokens` — one statement per
fleet sweep, NOT per tenant (see `test_tenant_job_recovery.py`) — strips every
terminal row that still carries the key. DB-backed on purpose: both are raw SQL
against a JSONB column, and a mocked session would assert nothing about whether
the statements are even valid.

Every token literal here is obviously fake.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.heartbeat import (
    stop_ingest_job_heartbeat as _real_stop_heartbeat,
)
from app.platform.jobs.models import IngestJob
from app.platform.jobs.sweep import purge_terminal_job_tokens
from app.processing.ingest import tasks_reupload, tasks_vector
from app.processing.ingest.tasks_common import (
    purge_queued_job_token,
    purge_token_on_failure,
)
from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

FAKE_TOKEN = "FAKE-TOKEN-1746-NOT-A-SECRET"
FAKE_CREDENTIAL_REF = "cred-ref-1746"


def _args(*, with_token: bool = True) -> dict:
    args = {
        "job_id": str(uuid.uuid4()),
        "source_url": "https://example.invalid/FeatureServer/0",
        "credential_ref": FAKE_CREDENTIAL_REF,
    }
    if with_token:
        args["token"] = FAKE_TOKEN
    return args


async def _queue_row(
    session: AsyncSession, *, status: str, queue_name: str, args: dict
) -> int:
    """Insert one procrastinate row and return its id.

    Procrastinate's insert trigger logs to `procrastinate_events` by
    unqualified name, so the schema has to be on the search_path or a 'todo'
    insert fails where a 'doing' one (no event) would succeed.
    """
    await session.execute(text("SET LOCAL search_path TO catalog, public"))
    row_id = (
        await session.execute(
            text(
                "INSERT INTO catalog.procrastinate_jobs"
                " (queue_name, task_name, args, status)"
                " VALUES (:queue, 'app.processing.ingest.tasks.ingest_service',"
                " CAST(:args AS jsonb),"
                " CAST(:status AS catalog.procrastinate_job_status))"
                " RETURNING id"
            ).bindparams(queue=queue_name, args=json.dumps(args), status=status)
        )
    ).scalar_one()
    await session.commit()
    return int(row_id)


async def _read_args(session: AsyncSession, row_id: int) -> dict:
    raw = (
        await session.execute(
            text(
                "SELECT args FROM catalog.procrastinate_jobs WHERE id = :id"
            ).bindparams(id=row_id)
        )
    ).scalar_one()
    return raw if isinstance(raw, dict) else json.loads(raw)


async def _drop_queue(session: AsyncSession, queue_name: str) -> None:
    # Same unqualified-name reason as the insert: the delete trigger reaches
    # for `procrastinate_periodic_defers`.
    await session.execute(text("SET LOCAL search_path TO catalog, public"))
    await session.execute(
        text("DELETE FROM catalog.procrastinate_jobs WHERE queue_name = :q").bindparams(
            q=queue_name
        )
    )
    await session.commit()


class TestThePurgeStripsTerminalRows:
    async def test_terminal_rows_lose_the_token_and_keep_everything_else(
        self, test_db_session: AsyncSession
    ):
        """failed and succeeded lose `token`; todo is left alone.

        `todo` is still waiting to be worked with exactly these args — the
        purge taking the token from it would break the pending dispatch,
        which is the one way this cleanup could cause harm.
        """
        queue = f"tok-purge-{uuid.uuid4().hex[:12]}"
        failed_args = _args()
        todo_args = _args()
        succeeded_args = _args()
        try:
            failed_id = await _queue_row(
                test_db_session, status="failed", queue_name=queue, args=failed_args
            )
            todo_id = await _queue_row(
                test_db_session, status="todo", queue_name=queue, args=todo_args
            )
            succeeded_id = await _queue_row(
                test_db_session,
                status="succeeded",
                queue_name=queue,
                args=succeeded_args,
            )

            await purge_terminal_job_tokens(test_db_session)

            after_failed = await _read_args(test_db_session, failed_id)
            assert "token" not in after_failed
            assert after_failed == {
                k: v for k, v in failed_args.items() if k != "token"
            }, "the purge must remove the token key and nothing else"

            after_succeeded = await _read_args(test_db_session, succeeded_id)
            assert "token" not in after_succeeded
            assert after_succeeded["credential_ref"] == FAKE_CREDENTIAL_REF

            after_todo = await _read_args(test_db_session, todo_id)
            assert after_todo == todo_args, "a queued dispatch must keep its args"
        finally:
            await _drop_queue(test_db_session, queue)

    async def test_a_row_without_a_token_is_not_rewritten(
        self, test_db_session: AsyncSession
    ):
        """The `args ? 'token'` guard keeps the UPDATE off untouched rows."""
        queue = f"tok-purge-{uuid.uuid4().hex[:12]}"
        clean_args = _args(with_token=False)
        try:
            row_id = await _queue_row(
                test_db_session, status="failed", queue_name=queue, args=clean_args
            )

            await purge_terminal_job_tokens(test_db_session)

            assert await _read_args(test_db_session, row_id) == clean_args
        finally:
            await _drop_queue(test_db_session, queue)


class TestTheTaskStripsItsOwnRow:
    async def test_a_failed_attempt_purges_its_own_queue_row(
        self, test_db_session: AsyncSession
    ):
        """`doing`, so only the task-side purge can be what stripped it."""
        queue = f"tok-purge-{uuid.uuid4().hex[:12]}"
        args = _args()
        try:
            row_id = await _queue_row(
                test_db_session, status="doing", queue_name=queue, args=args
            )

            @purge_token_on_failure
            async def _dies(**kwargs):
                raise RuntimeError("terminal")

            context = SimpleNamespace(job=SimpleNamespace(id=row_id))
            with pytest.raises(RuntimeError, match="terminal"):
                await _dies(context, job_id=args["job_id"], token=FAKE_TOKEN)

            after = await _read_args(test_db_session, row_id)
            assert "token" not in after
            assert after["credential_ref"] == FAKE_CREDENTIAL_REF
        finally:
            await _drop_queue(test_db_session, queue)

    async def test_a_successful_attempt_writes_nothing(
        self, test_db_session: AsyncSession
    ):
        """The worker deletes successful rows; the purge stays off that path."""
        queue = f"tok-purge-{uuid.uuid4().hex[:12]}"
        args = _args()
        try:
            row_id = await _queue_row(
                test_db_session, status="doing", queue_name=queue, args=args
            )
            calls: list[dict] = []

            @purge_token_on_failure
            async def _succeeds(**kwargs):
                calls.append(kwargs)
                return "ok"

            context = SimpleNamespace(job=SimpleNamespace(id=row_id))
            assert await _succeeds(context, job_id=args["job_id"]) == "ok"
            assert calls == [{"job_id": args["job_id"]}], (
                "the wrapper must absorb the context and forward the rest verbatim"
            )
            assert await _read_args(test_db_session, row_id) == args
        finally:
            await _drop_queue(test_db_session, queue)

    async def test_a_direct_call_without_a_context_is_transparent(self):
        """Tests and `.func` callers pass no context; there is no row to purge."""

        @purge_token_on_failure
        async def _dies(**kwargs):
            raise RuntimeError("terminal")

        with pytest.raises(RuntimeError, match="terminal"):
            await _dies(job_id="whatever")

    async def test_the_purge_never_displaces_the_real_failure(self):
        """A broken purge is a warning, not a second exception."""
        with patch("app.core.db.async_session", side_effect=RuntimeError("db is gone")):
            await purge_queued_job_token(SimpleNamespace(job=SimpleNamespace(id=1)))


class TestBothServiceTasksAreWired:
    @pytest.mark.parametrize(
        "task",
        [tasks_vector.ingest_service, tasks_reupload.reupload_service],
        ids=["ingest_service", "reupload_service"],
    )
    def test_the_task_receives_the_context_it_needs(self, task):
        """Without `pass_context` the task cannot learn its own row id."""
        assert task.pass_context is True
        # retry=0 is what makes stripping safe: the first exception is the
        # terminal one, so no later attempt reads these args.
        assert task.retry_strategy is None

    async def test_the_real_task_stack_purges_a_pre_flight_failure(
        self, test_db_session: AsyncSession
    ):
        """Through the whole stack, called the way the worker calls it.

        The SSRF revalidation in `ingest_service` raises BEFORE the task's own
        try/except, which is why the purge is a wrapper around the task rather
        than a line in that handler. Driving the real Task object also proves
        `pass_context` and `tenant_task` still compose: the context arrives
        positionally and the task's own signature is untouched.
        """
        queue = f"tok-purge-{uuid.uuid4().hex[:12]}"
        args = _args()
        try:
            row_id = await _queue_row(
                test_db_session, status="doing", queue_name=queue, args=args
            )
            context = SimpleNamespace(job=SimpleNamespace(id=row_id))

            with pytest.raises(RuntimeError, match="failed safety check"):
                await tasks_vector.ingest_service(
                    context,
                    job_id=args["job_id"],
                    # loopback: blocked by validate_url_for_ssrf, so the task
                    # dies before it reaches a database or a subprocess.
                    source_url="http://127.0.0.1/FeatureServer/0",
                    source_layer="",
                    user_id=str(uuid.uuid4()),
                    token=FAKE_TOKEN,
                )

            assert "token" not in await _read_args(test_db_session, row_id)
        finally:
            await _drop_queue(test_db_session, queue)


class TestCleanupFailuresDoNotMaskTheOriginalException:
    """fix(#1755 item 11): a `finally`-block cleanup failure must not replace
    the ingest exception, and the #1753 token purge must still run.

    Each test fails the task with a distinctive exception from well past
    staging-table setup (so `stop_ingest_job_heartbeat` and
    `_drop_attempt_staging_table` both have real state to act on), then makes
    BOTH cleanup calls in the `finally` block also raise. The mocked cleanup
    still runs the real cleanup underneath (cancels the real heartbeat task,
    drops the real staging table) before raising, so this pins the wrapping
    itself rather than merely skipping the cleanup work. Without the item-11
    fix, the ingest exception raised below is replaced by whichever cleanup
    call runs first — `pytest.raises` would see `ValueError`/`KeyError`
    instead of the ingest exception, which is exactly what these tests
    refuse.
    """

    async def test_ingest_service_cleanup_failure_does_not_mask_the_original(
        self,
        client: AsyncClient,  # ensures app.core.db.async_session points at the test DB
        test_db_session: AsyncSession,
        monkeypatch,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        job = IngestJob(
            source_filename="Cleanup Failure Service",
            source_url="https://services.example.com/svc/FeatureServer",
            source_layer="0",
            created_by=admin_id,
            status="pending",
            user_metadata={
                "title": "Cleanup Failure Service",
                "visibility": "private",
                "service_type": "ArcGIS FeatureServer",
                "layer_id": "0",
                "geometry_type": None,
                "source_columns": [],
            },
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        job_id = job.id
        attempt_id = job.attempt_id
        assert attempt_id is not None

        queue = f"tok-purge-{uuid.uuid4().hex[:12]}"
        args = {
            "job_id": str(job_id),
            "attempt_id": str(attempt_id),
            "source_url": job.source_url,
            "source_layer": "0",
            "user_id": str(admin_id),
            "token": FAKE_TOKEN,
        }
        row_id = await _queue_row(
            test_db_session, status="doing", queue_name=queue, args=args
        )

        async def _validate_url_noop(_url: str) -> None:
            return None

        async def _boom_credential(*_args, **_kwargs) -> str | None:
            raise RuntimeError("simulated ingest failure")

        async def _stop_heartbeat_and_raise(task) -> None:
            # Real cleanup first (cancels the real background task), THEN the
            # simulated failure — proves the wrapping, not merely that
            # cleanup was skipped.
            await _real_stop_heartbeat(task)
            raise ValueError("cleanup boom: heartbeat")

        real_drop_staging = tasks_vector._drop_attempt_staging_table

        async def _drop_staging_and_raise(staging_table: str) -> None:
            await real_drop_staging(staging_table)
            raise KeyError("cleanup boom: staging")

        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _validate_url_noop
        )
        monkeypatch.setattr(
            "app.platform.refresh.credentials.resolve_worker_credential",
            _boom_credential,
        )
        monkeypatch.setattr(
            tasks_vector, "stop_ingest_job_heartbeat", _stop_heartbeat_and_raise
        )
        monkeypatch.setattr(
            tasks_vector, "_drop_attempt_staging_table", _drop_staging_and_raise
        )

        try:
            context = SimpleNamespace(job=SimpleNamespace(id=row_id))
            with pytest.raises(RuntimeError, match="simulated ingest failure"):
                await tasks_vector.ingest_service(
                    context,
                    job_id=str(job_id),
                    attempt_id=str(attempt_id),
                    source_url=job.source_url,
                    source_layer="0",
                    user_id=str(admin_id),
                    token=FAKE_TOKEN,
                )

            after = await _read_args(test_db_session, row_id)
            assert "token" not in after, "the #1753 purge must still run"
        finally:
            await _drop_queue(test_db_session, queue)

    async def test_reupload_service_cleanup_failure_does_not_mask_the_original(
        self,
        client: AsyncClient,  # ensures app.core.db.async_session points at the test DB
        test_db_session: AsyncSession,
        monkeypatch,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_cleanup_{uuid.uuid4().hex[:12]}"
        record = Record(
            title="Cleanup Failure Reupload",
            summary="fix(#1755 item 11) fixture",
            visibility="private",
            record_status="published",
            created_by=admin_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        dataset = Dataset(
            record_id=record.id,
            table_name=table_name,
            feature_count=1,
            source_format="arcgis_featureserver",
            source_filename="quakes",
            source_url="https://services.example.com/svc/FeatureServer/0",
        )
        test_db_session.add(dataset)
        await test_db_session.commit()
        await test_db_session.refresh(dataset)
        dataset_id = dataset.id

        job = IngestJob(
            dataset_id=dataset_id,
            source_filename="quakes",
            source_url="https://services.example.com/svc/FeatureServer/0",
            source_layer="0",
            created_by=admin_id,
            status="pending",
            user_metadata={
                "reupload": True,
                "dataset_id": str(dataset_id),
                "service_type": "ArcGIS FeatureServer",
                "layer_id": 0,
                "source_type": "service_url",
            },
        )
        test_db_session.add(job)
        await test_db_session.commit()
        await test_db_session.refresh(job)
        job_id = job.id
        attempt_id = job.attempt_id
        assert attempt_id is not None

        queue = f"tok-purge-{uuid.uuid4().hex[:12]}"
        args = {
            "job_id": str(job_id),
            "attempt_id": str(attempt_id),
            "dataset_id": str(dataset_id),
            "source_url": job.source_url,
            "source_layer": "0",
            "user_id": str(admin_id),
            "token": FAKE_TOKEN,
        }
        row_id = await _queue_row(
            test_db_session, status="doing", queue_name=queue, args=args
        )

        async def _validate_url_noop(_url: str) -> None:
            return None

        def _boom_service_type(_raw: str):
            raise RuntimeError("simulated reupload failure")

        async def _stop_heartbeat_and_raise(task) -> None:
            await _real_stop_heartbeat(task)
            raise ValueError("cleanup boom: heartbeat")

        real_drop_staging = tasks_reupload._drop_attempt_staging_table

        async def _drop_staging_and_raise(staging_table: str) -> None:
            await real_drop_staging(staging_table)
            raise KeyError("cleanup boom: staging")

        monkeypatch.setattr(
            "app.platform.security.validate_url_for_ssrf", _validate_url_noop
        )
        # fix(#1755 item 11) test: `resolve_service_type` runs AFTER
        # `staging_tn`/`heartbeat_task` are both set, so failing here (rather
        # than at credential resolution, which runs before either) is what
        # gives both cleanup calls real state to act on.
        monkeypatch.setattr(tasks_reupload, "resolve_service_type", _boom_service_type)
        monkeypatch.setattr(
            tasks_reupload, "stop_ingest_job_heartbeat", _stop_heartbeat_and_raise
        )
        monkeypatch.setattr(
            tasks_reupload, "_drop_attempt_staging_table", _drop_staging_and_raise
        )

        try:
            context = SimpleNamespace(job=SimpleNamespace(id=row_id))
            with pytest.raises(RuntimeError, match="simulated reupload failure"):
                await tasks_reupload.reupload_service(
                    context,
                    job_id=str(job_id),
                    attempt_id=str(attempt_id),
                    dataset_id=str(dataset_id),
                    source_url=job.source_url,
                    source_layer="0",
                    user_id=str(admin_id),
                    token=FAKE_TOKEN,
                )

            after = await _read_args(test_db_session, row_id)
            assert "token" not in after, "the #1753 purge must still run"
        finally:
            await _drop_queue(test_db_session, queue)
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE')
            )
            await test_db_session.commit()
