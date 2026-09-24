"""The dispatch orphan guard settles what a failed defer would strand.

Covers ``defer_with_orphan_guard`` and its application to the six
``defer_async`` call sites that commit DB state *before* dispatching a
Procrastinate task:

- ``datasets/router_reupload.py``: reupload_service, reupload_file
  priority, reupload_file default (3 sites)
- ``ingest/router.py``: add_vrt_source, remove_vrt_source (2 sites)
- ``datasets/router_vrt.py``: regenerate_vrt_endpoint (1 site)

The guard's own contract is tested against doubles. The door tests make the
queue unreachable and read the rows back from the test database: the job
fails, its run or VRT generation fails with it, and the door answers 503.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helper unit tests — defer_with_orphan_guard contract
# ---------------------------------------------------------------------------


def _job():
    """A row shaped enough for the #1744 dispatch stamp.

    `stamp_commit_attempted` reads `user_metadata`, writes an UPDATE keyed on
    `id` and mirrors the result back, so a plain namespace is representative;
    a MagicMock is not, because its `user_metadata` is a Mock rather than a
    mapping.
    """
    return SimpleNamespace(id=uuid.uuid4(), user_metadata=None)


class TestDeferWithOrphanGuard:
    """Unit tests for the generic ``defer_with_orphan_guard`` helper."""

    def test_success_path_does_not_invoke_rollback(self):
        """On a successful defer, rollback must not run.

        fix(#1744): the guard now commits once on this path, stamping
        `commit_attempted_at` on the row before the task exists, so the count
        is one rather than none. Any commit beyond that is the rollback's, and
        the rollback did not run.
        """

        async def _check():
            from app.platform.jobs.defer_guard import defer_with_orphan_guard

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            defer_called = []
            rollback_called = []

            async def _defer() -> None:
                defer_called.append(True)

            async def _rollback(exc: BaseException) -> None:
                rollback_called.append(exc)

            await defer_with_orphan_guard(
                _defer, rollback=_rollback, db=mock_db, job=_job()
            )

            assert defer_called == [True]
            assert rollback_called == []
            mock_db.commit.assert_awaited_once()

        asyncio.run(_check())

    def test_defer_failure_invokes_rollback_and_raises_503(self):
        """Defer raising must: run rollback, commit it, and propagate as HTTP 503."""

        async def _check():
            from app.platform.jobs.defer_guard import defer_with_orphan_guard

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            received_exc: list[BaseException] = []

            async def _defer() -> None:
                raise RuntimeError("procrastinate unreachable")

            async def _rollback(exc: BaseException) -> None:
                received_exc.append(exc)

            with pytest.raises(HTTPException) as exc_info:
                await defer_with_orphan_guard(
                    _defer, rollback=_rollback, db=mock_db, job=_job()
                )

            assert exc_info.value.status_code == 503
            assert "retry" in str(exc_info.value.detail).lower()
            # Rollback received the underlying exception
            assert len(received_exc) == 1
            assert isinstance(received_exc[0], RuntimeError)
            assert "procrastinate unreachable" in str(received_exc[0])
            # Two commits: the #1744 dispatch stamp, then the rollback.
            assert mock_db.commit.await_count == 2

        asyncio.run(_check())

    def test_defer_failed_cause_class_names_the_defer_call_exception(self):
        """fix(#1755 item 10): the 503 body carries the CLASS of whatever made
        the guard raise, coded and redacted -- never the exception's own
        message, which can carry a credential or provider-chosen text.
        """

        async def _check():
            from app.platform.jobs.defer_guard import (
                DeferFailed,
                defer_with_orphan_guard,
            )

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            class _QueueOutage(RuntimeError):
                pass

            async def _defer() -> None:
                raise _QueueOutage("connection refused: 10.0.0.9:5432 secret=abc123")

            async def _rollback(exc: BaseException) -> None:
                return None

            with pytest.raises(DeferFailed) as exc_info:
                await defer_with_orphan_guard(
                    _defer, rollback=_rollback, db=mock_db, job=_job()
                )

            assert exc_info.value.status_code == 503
            assert exc_info.value.cause_class == "_QueueOutage"
            assert exc_info.value.detail["cause_class"] == "_QueueOutage"
            # The raw message -- including the address and the fake
            # credential-shaped substring above -- never reaches the body.
            assert "10.0.0.9" not in str(exc_info.value.detail)
            assert "secret=abc123" not in str(exc_info.value.detail)
            assert (
                exc_info.value.detail["message"]
                == "Task queue unavailable, please retry"
            )

        asyncio.run(_check())

    def test_defer_failed_cause_class_names_the_dispatch_marker_exception(self):
        """fix(#1755 item 10): a failure BEFORE the defer call -- the #1744
        dispatch-attempted marker write -- gets a DIFFERENT `cause_class`
        than a `defer_call` failure, even though both produce the identical
        503 status and fixed message. This is what makes the two shapes
        (a bug in the closure that built the dispatch vs. the queue itself
        being unreachable) distinguishable without ever inspecting the raw
        exception text.
        """

        async def _check():
            from app.platform.jobs.defer_guard import (
                DeferFailed,
                defer_with_orphan_guard,
            )

            class _ClosureBug(ValueError):
                pass

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()
            mock_db.execute = AsyncMock(side_effect=_ClosureBug("bad argument shape"))
            mock_db.rollback = AsyncMock()
            mock_db.refresh = AsyncMock()

            async def _defer() -> None:  # pragma: no cover - never reached
                raise AssertionError(
                    "defer_call must not run: the marker write failed first"
                )

            async def _rollback(exc: BaseException) -> None:
                return None

            with pytest.raises(DeferFailed) as exc_info:
                await defer_with_orphan_guard(
                    _defer, rollback=_rollback, db=mock_db, job=_job()
                )

            assert exc_info.value.status_code == 503
            assert exc_info.value.cause_class == "_ClosureBug"
            assert exc_info.value.detail["cause_class"] == "_ClosureBug"
            assert "bad argument shape" not in str(exc_info.value.detail)
            # Same fixed body shape as a defer_call-stage failure -- only
            # `cause_class` tells the two apart.
            assert (
                exc_info.value.detail["message"]
                == "Task queue unavailable, please retry"
            )
            assert exc_info.value.detail["code"] == "queue_unavailable"

        asyncio.run(_check())

    def test_each_stage_logs_its_cause_with_the_url_redacted(self):
        """fix(#1755 item 10): FastAPI answers a `DeferFailed` without logging
        it, so the guard logs the cause itself, under a `stage` that separates
        the marker write from the defer call, with any URL redacted first.
        """

        async def _check():
            from app.platform.jobs import defer_guard

            async def _rollback(exc: BaseException) -> None:
                return None

            async def _defer() -> None:
                raise RuntimeError(
                    "queue down: https://queue.example.com/d?token=SECRETVALUE1"
                )

            defer_db = AsyncMock()
            defer_db.commit = AsyncMock()
            with patch.object(defer_guard, "logger") as defer_logger:
                with pytest.raises(defer_guard.DeferFailed):
                    await defer_guard.defer_with_orphan_guard(
                        _defer, rollback=_rollback, db=defer_db, job=_job()
                    )

            marker_db = AsyncMock()
            marker_db.commit = AsyncMock()
            marker_db.rollback = AsyncMock()
            marker_db.refresh = AsyncMock()
            marker_db.execute = AsyncMock(side_effect=ValueError("bad shape"))
            with patch.object(defer_guard, "logger") as marker_logger:
                with pytest.raises(defer_guard.DeferFailed):
                    await defer_guard.defer_with_orphan_guard(
                        _defer, rollback=_rollback, db=marker_db, job=_job()
                    )

            defer_call = defer_logger.warning.call_args
            marker_call = marker_logger.warning.call_args
            assert defer_call.args[0] == "ingest_dispatch_failed"
            assert marker_call.args[0] == "ingest_dispatch_failed"
            assert defer_call.kwargs["stage"] == "defer_async"
            assert marker_call.kwargs["stage"] == "commit_attempted_marker"
            assert defer_call.kwargs["cause_class"] == "RuntimeError"
            assert marker_call.kwargs["cause_class"] == "ValueError"
            assert "SECRETVALUE1" not in defer_call.kwargs["error"]
            assert defer_call.kwargs["error"].startswith("queue down: ")

        asyncio.run(_check())

    def test_an_unreadable_job_id_does_not_preempt_the_settlement(self):
        """fix(#1755 item 10): reading `job.id` off an already-expired instance
        raises, and `reset_session_for_settlement` is what recovers it. The log
        runs first, so it has to absorb that read rather than skip the rollback.
        """

        async def _check():
            from app.platform.jobs import defer_guard

            class _Expired:
                """A job whose identifier read raises, as an expired ORM instance does."""

                user_metadata = None

                @property
                def id(self):
                    raise RuntimeError("greenlet_spawn has not been called")

            settled: list[BaseException] = []

            async def _rollback(exc: BaseException) -> None:
                settled.append(exc)

            async def _defer() -> None:  # pragma: no cover - never reached
                raise AssertionError("defer_call must not run")

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()
            mock_db.rollback = AsyncMock()
            mock_db.refresh = AsyncMock()

            with pytest.raises(defer_guard.DeferFailed) as exc_info:
                await defer_guard.defer_with_orphan_guard(
                    _defer, rollback=_rollback, db=mock_db, job=_Expired()
                )

            assert exc_info.value.status_code == 503
            assert exc_info.value.rolled_back is True
            assert len(settled) == 1

        asyncio.run(_check())

    def test_an_unrenderable_exception_does_not_preempt_the_settlement(self):
        """fix(#1755 item 10): the dispatch log renders the exception, so an
        exception whose `__str__` raises must degrade to a placeholder. The
        readable field beside it keeps its real value.
        """

        async def _check():
            from app.platform.jobs import defer_guard

            class _Unrenderable(RuntimeError):
                def __str__(self) -> str:
                    raise ValueError("this exception cannot render itself")

            settled: list[BaseException] = []

            async def _rollback(exc: BaseException) -> None:
                settled.append(exc)

            async def _defer() -> None:
                raise _Unrenderable()

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            with patch.object(defer_guard, "logger") as mock_logger:
                with pytest.raises(defer_guard.DeferFailed) as exc_info:
                    await defer_guard.defer_with_orphan_guard(
                        _defer, rollback=_rollback, db=mock_db, job=_job()
                    )

            assert exc_info.value.cause_class == "_Unrenderable"
            assert exc_info.value.rolled_back is True
            assert len(settled) == 1
            logged = mock_logger.warning.call_args.kwargs
            assert logged["error"] == "unreadable"
            assert logged["job_id"] != "unreadable"

        asyncio.run(_check())

    def test_a_rendered_task_kwarg_is_scrubbed_before_it_reaches_the_record(self):
        """fix(#1755 item 10): `error` is a plain scalar field, and the log
        processor scrubs free text only under `event` and `exception`. A defer
        error quoting Procrastinate's `call_string` must be scrubbed here.
        """

        async def _check():
            from app.platform.jobs import defer_guard

            async def _rollback(exc: BaseException) -> None:
                return None

            async def _defer() -> None:
                raise RuntimeError(
                    "could not enqueue ingest_service[9]"
                    "(token='PLACEHOLDERSECRET1', credential_ref=None)"
                )

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            with patch.object(defer_guard, "logger") as mock_logger:
                with pytest.raises(defer_guard.DeferFailed):
                    await defer_guard.defer_with_orphan_guard(
                        _defer, rollback=_rollback, db=mock_db, job=_job()
                    )

            logged_error = mock_logger.warning.call_args.kwargs["error"]
            assert "PLACEHOLDERSECRET1" not in logged_error
            assert "[REDACTED]" in logged_error
            assert logged_error.startswith("could not enqueue ingest_service[9]")

        asyncio.run(_check())

    def test_the_rollback_failure_log_scrubs_the_same_text(self):
        """fix(#1755 item 10): the rollback-failure log renders the same defer
        exception under its own scalar field, so it needs the same scrub.
        """

        async def _check():
            from app.platform.jobs import defer_guard

            async def _rollback(exc: BaseException) -> None:
                raise ValueError("rollback crashed")

            async def _defer() -> None:
                raise RuntimeError(
                    "could not enqueue ingest_service[9]"
                    "(token='PLACEHOLDERSECRET2', credential_ref=None)"
                )

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            with patch.object(defer_guard, "logger") as mock_logger:
                with pytest.raises(defer_guard.DeferFailed):
                    await defer_guard.defer_with_orphan_guard(
                        _defer, rollback=_rollback, db=mock_db, job=_job()
                    )

            logged = mock_logger.exception.call_args.kwargs["defer_error"]
            assert "PLACEHOLDERSECRET2" not in logged
            assert "[REDACTED]" in logged

        asyncio.run(_check())

    def test_the_wrapped_cause_reaches_the_record_scrubbed(self):
        """fix(#1755 item 10): Procrastinate wraps a connector failure as
        `ConnectorException("Database error.")`, so the top frame alone tells
        two outages apart from neither. The chain lands under `exception`.
        """
        import logging

        from app.platform.jobs.defer_guard import _log_dispatch_failure
        from tests._logging_state import configured_logging

        records: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(self.format(record))

        try:
            raise ValueError(
                "connect failed for https://db.example.com/?token=PLACEHOLDERSECRET3"
            )
        except ValueError as inner:
            wrapped = RuntimeError("Database error.")
            wrapped.__cause__ = inner

        handler = _Capture()
        with configured_logging():
            logging.getLogger().addHandler(handler)
            try:
                _log_dispatch_failure(_job(), wrapped, stage="defer_async")
            finally:
                logging.getLogger().removeHandler(handler)

        emitted = "\n".join(records)
        assert "connect failed for" in emitted
        assert "PLACEHOLDERSECRET3" not in emitted

    def test_a_logger_that_raises_does_not_preempt_the_settlement(self):
        """fix(#1755 item 10): a structlog processor can raise while emitting.
        The whole diagnostic is best-effort, so the rollback still runs and the
        caller still sees the 503.
        """

        async def _check():
            from app.platform.jobs import defer_guard

            settled: list[BaseException] = []

            async def _rollback(exc: BaseException) -> None:
                settled.append(exc)

            async def _defer() -> None:
                raise RuntimeError("queue down")

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            with patch.object(defer_guard, "logger") as mock_logger:
                mock_logger.warning.side_effect = OSError("log sink is gone")
                with pytest.raises(defer_guard.DeferFailed) as exc_info:
                    await defer_guard.defer_with_orphan_guard(
                        _defer, rollback=_rollback, db=mock_db, job=_job()
                    )

            assert exc_info.value.status_code == 503
            assert exc_info.value.rolled_back is True
            assert len(settled) == 1

        asyncio.run(_check())

    def test_rollback_failure_still_raises_503(self):
        """If rollback itself raises, helper still surfaces the 503 to the client."""

        async def _check():
            from app.platform.jobs.defer_guard import defer_with_orphan_guard

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            async def _defer() -> None:
                raise RuntimeError("defer failure")

            async def _rollback(exc: BaseException) -> None:
                raise ValueError("rollback crashed")

            with pytest.raises(HTTPException) as exc_info:
                await defer_with_orphan_guard(
                    _defer, rollback=_rollback, db=mock_db, job=_job()
                )

            # 503 is always raised — rollback failure is logged, not swallowed.
            assert exc_info.value.status_code == 503

        asyncio.run(_check())

    async def test_make_ingest_job_failed_rollback_marks_job_failed(
        self, test_db_session
    ):
        """The builder's rollback fails the job row and names the exception's type only."""
        from app.platform.jobs.defer_guard import make_ingest_job_failed_rollback
        from app.platform.jobs.models import IngestJob

        job = IngestJob(
            source_filename="custom.geojson", status="pending", file_path=""
        )
        test_db_session.add(job)
        await test_db_session.commit()
        job_id = job.id

        rollback = make_ingest_job_failed_rollback(
            job, message_prefix="Failed to queue custom task"
        )
        assert await rollback(RuntimeError("queue dead"))
        await test_db_session.commit()

        row = await test_db_session.get(IngestJob, job_id, populate_existing=True)
        assert row.status == "failed"
        assert row.error_message == "Failed to queue custom task (RuntimeError)"
        assert row.completed_at is not None

    async def test_a_job_outside_any_session_is_not_reported_settled(self):
        """The rollback raises for a job no session holds rather than claim it failed."""
        from app.platform.jobs.defer_guard import make_ingest_job_failed_rollback
        from app.platform.jobs.models import IngestJob

        detached = IngestJob(id=uuid.uuid4(), attempt_id=uuid.uuid4(), status="pending")

        with pytest.raises(RuntimeError, match="not attached to a session"):
            await make_ingest_job_failed_rollback(detached)(RuntimeError("queue dead"))


# ---------------------------------------------------------------------------
# Reupload router — 3 defer sites
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _unreachable_reupload_queue():
    """Every re-upload task's defer raises, as it does while the queue is down."""
    task = MagicMock()
    task.defer_async = AsyncMock(side_effect=RuntimeError("reupload queue down"))
    task.configure = MagicMock(return_value=task)
    port = MagicMock()
    port.reupload_service_task.return_value = task
    port.reupload_file_task.return_value = task
    port.priority_queue_threshold_bytes = 10_000_000
    with patch(
        "app.modules.catalog.datasets.api.router_reupload.get_catalog_port",
        return_value=port,
    ):
        yield task


class TestReuploadOrphanGuard:
    @pytest.mark.parametrize("source", ["service", "priority-file", "default-file"])
    async def test_a_failed_dispatch_fails_the_job_and_its_run(
        self,
        client,
        admin_auth_header,
        test_db_session,
        clean_tables,
        tmp_path,
        source,
    ):
        """Each re-upload queue's failed dispatch fails the job and its run with the re-upload reason."""
        from sqlalchemy import select

        from app.platform.jobs.models import IngestJob
        from app.platform.refresh.models import DatasetRefreshRun
        from tests.factories import create_dataset, get_user_id
        from tests.test_import_token_lease_1676 import _service_reupload_job

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        if source == "service":
            job = await _service_reupload_job(
                test_db_session, dataset_id=dataset.id, created_by=admin_id
            )
        else:
            small = tmp_path / "tiny.geojson"
            small.write_text('{"type":"FeatureCollection","features":[]}')
            job = IngestJob(
                dataset_id=dataset.id,
                status="pending",
                source_filename="tiny.geojson",
                # A local file under the threshold goes to the priority queue;
                # an object-store key is never probed and takes the default.
                file_path=(
                    str(small)
                    if source == "priority-file"
                    else "staging/reupload/tiny.geojson"
                ),
                created_by=admin_id,
                user_metadata={"reupload": True, "dataset_id": str(dataset.id)},
            )
            test_db_session.add(job)
            await test_db_session.commit()
        job_id = job.id

        async with _unreachable_reupload_queue() as task:
            resp = await client.post(
                f"/datasets/{dataset.id}/reupload/{job_id}/commit",
                json={},
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        assert task.configure.called is (source == "priority-file")
        reason = "Failed to queue reupload task (RuntimeError)"
        row = await test_db_session.get(IngestJob, job_id, populate_existing=True)
        assert (row.status, row.error_message) == ("failed", reason)
        assert row.completed_at is not None
        run = (
            await test_db_session.execute(
                select(DatasetRefreshRun)
                .where(DatasetRefreshRun.ingest_job_id == job_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert (run.status, run.error_code, run.error_message) == (
            "failed",
            "dispatch_failed",
            reason,
        )


# ---------------------------------------------------------------------------
# VRT regeneration doors — datasets/router_vrt.py and ingest/router.py
# ---------------------------------------------------------------------------


class TestVrtDoorsOrphanGuard:
    @pytest.mark.parametrize(
        "published", [True, False], ids=["published", "unrecorded"]
    )
    @pytest.mark.parametrize("door", ["regenerate", "add-source", "remove-source"])
    async def test_a_failed_dispatch_releases_the_vrt_by_the_ready_worthy_rule(
        self,
        client,
        admin_auth_header,
        test_db_session,
        clean_tables,
        monkeypatch,
        door,
        published,
    ):
        """A VRT door's failed dispatch fails its job and generation, restores the asset by the ready-worthy rule and leaves the links alone."""
        from sqlalchemy import select, text, update

        from app.platform.jobs.models import IngestJob
        from app.processing.raster.models import RasterAsset, VrtGeneration
        from tests.factories import get_user_id
        from tests.test_vrt_source_authz_1172 import (
            _create_raster_dataset,
            _create_vrt_dataset,
            _link_source,
        )

        admin_id = await get_user_id(test_db_session, "admin")
        vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
        linked = [
            await _create_raster_dataset(test_db_session, created_by=admin_id)
            for _ in range(3)
        ]
        for position, source_id in enumerate(linked):
            await _link_source(test_db_session, vrt_id, source_id, position)
        if published:
            # The member set the served artifact was built from, matching the
            # links. An asset built before `built_from` existed has none.
            await test_db_session.execute(
                update(RasterAsset)
                .where(RasterAsset.dataset_id == vrt_id)
                .values(built_from={str(s): f"rasters/{s}/cog.tif" for s in linked})
            )
            await test_db_session.commit()
        unreachable = AsyncMock(side_effect=RuntimeError("vrt queue dead"))
        monkeypatch.setattr(
            "app.processing.ingest.router.defer_async_with_tenant", unreachable
        )
        monkeypatch.setattr(
            "app.modules.catalog.datasets.api.router_vrt.defer_async_with_tenant",
            unreachable,
        )

        if door == "regenerate":
            resp = await client.post(
                f"/datasets/{vrt_id}/vrt/regenerate/", headers=admin_auth_header
            )
        elif door == "add-source":
            incoming = await _create_raster_dataset(
                test_db_session, created_by=admin_id
            )
            resp = await client.post(
                f"/ingest/vrt/{vrt_id}/sources/",
                json={"source_dataset_id": str(incoming)},
                headers=admin_auth_header,
            )
        else:
            resp = await client.delete(
                f"/ingest/vrt/{vrt_id}/sources/{linked[1]}/",
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        reason = "Failed to queue VRT regeneration (RuntimeError)"
        job_id = uuid.UUID(unreachable.await_args.kwargs["job_id"])
        job = await test_db_session.get(IngestJob, job_id, populate_existing=True)
        assert (job.status, job.error_message) == ("failed", reason)
        assert job.completed_at is not None
        generation = (
            await test_db_session.execute(
                select(VrtGeneration)
                .where(VrtGeneration.vrt_dataset_id == vrt_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert (generation.status, generation.error_message) == ("failed", reason)
        assert generation.completed_at is not None
        asset = (
            await test_db_session.execute(
                select(RasterAsset)
                .where(RasterAsset.dataset_id == vrt_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert (asset.status, asset.current_generation_id) == (
            "ready" if published else "failed",
            None,
        )
        links = (
            await test_db_session.execute(
                text(
                    "SELECT source_dataset_id FROM catalog.vrt_source_links "
                    "WHERE vrt_dataset_id = :vrt ORDER BY position"
                ),
                {"vrt": str(vrt_id)},
            )
        ).scalars()
        assert list(links) == linked


# ---------------------------------------------------------------------------
# VRT creation — ingest/service.py create_vrt_job
# ---------------------------------------------------------------------------


class TestVrtCreateOrphanGuard:
    async def test_a_failed_dispatch_fails_the_creation_job(
        self, client, admin_auth_header, test_db_session, clean_tables
    ):
        """A VRT creation whose queue is unreachable answers 503 and leaves its job failed."""
        from app.platform.jobs.models import IngestJob
        from tests.factories import get_user_id
        from tests.test_vrt_source_authz_1172 import _create_raster_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        sources = [
            str(await _create_raster_dataset(test_db_session, created_by=admin_id))
            for _ in range(2)
        ]
        task = MagicMock()
        task.defer_async = AsyncMock(
            side_effect=RuntimeError("procrastinate unreachable")
        )

        with patch("app.processing.ingest.tasks.ingest_vrt", task):
            resp = await client.post(
                "/ingest/vrt/create",
                json={
                    "source_dataset_ids": sources,
                    "vrt_type": "mosaic",
                    "resolution_strategy": "finest",
                    "title": "Unqueued VRT",
                },
                headers=admin_auth_header,
            )

        assert resp.status_code == 503, resp.text
        job_id = uuid.UUID(task.defer_async.await_args.kwargs["job_id"])
        job = await test_db_session.get(IngestJob, job_id, populate_existing=True)
        assert (job.status, job.error_message) == (
            "failed",
            "Failed to queue VRT task (RuntimeError)",
        )
        assert job.completed_at is not None
