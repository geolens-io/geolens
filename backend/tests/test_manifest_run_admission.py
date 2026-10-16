"""A manifest update is admitted through a refresh run, like every other door."""

from __future__ import annotations

import asyncio
import contextvars
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from sqlalchemy import delete, select, text, update

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.extensions import DefaultPermissionExtension
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.platform.refresh.service import (
    claim_run_for_job,
    create_pending_run,
    transition_run,
)
from app.processing.ingest import manifest_service
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from app.processing.ingest.manifest_sources import (
    classify_manifest_source,
    manifest_dataset_fingerprint,
    manifest_job_metadata,
)
from app.processing.ingest.tasks import reupload_file
from tests.factories import create_dataset

pytestmark = pytest.mark.anyio

_FIXTURE = "tests/fixtures/ingest/basic_attrs.geojson"


def _entry(key: str, *, title: str = "Road centerlines") -> dict:
    return {
        "key": key,
        "title": title,
        "sources": [{"type": "vector", "uri": _FIXTURE, "format": "geojson"}],
        "metadata": {"crs": "EPSG:4326"},
        "publication": {"intent": "draft"},
    }


def _request(*entries: dict) -> ManifestApplyRequest:
    return ManifestApplyRequest.model_validate(
        {
            "manifest_version": "1",
            "catalog": {"title": "Manifest catalog"},
            "datasets": list(entries),
        }
    )


def _update(key: str) -> ManifestApplyRequest:
    return _request(_entry(key, title="Updated roads"))


def _http_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ingest/manifest/apply",
            "headers": [],
        }
    )


async def _admin(session) -> User:
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one()


def _stage_fixture() -> None:
    destination = Path(settings.upload_staging_dir) / _FIXTURE
    destination.parent.mkdir(parents=True, exist_ok=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", destination)


async def _applied_dataset(session, user: User, key: str) -> uuid.UUID:
    """The id of a dataset an earlier apply of ``key`` created."""
    dataset = await create_dataset(session, created_by=user.id, name=f"Manifest {key}")
    original = _request(_entry(key)).datasets[0]
    prepared = await classify_manifest_source(original.sources[0])
    session.add(
        IngestJob(
            dataset_id=dataset.id,
            source_filename=prepared.source_filename,
            file_path=prepared.file_path,
            created_by=user.id,
            status="complete",
            completed_at=datetime.now(timezone.utc),
            user_metadata=manifest_job_metadata(
                original, prepared, fingerprint=manifest_dataset_fingerprint(original)
            ),
        )
    )
    await session.commit()
    return dataset.id


async def _occupy(session, dataset_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    """Hold the dataset's active-run slot the way a UI re-upload commit does."""
    job = IngestJob(
        dataset_id=dataset_id,
        status="pending",
        source_filename="parcels.gpkg",
        created_by=user_id,
        user_metadata={"reupload": True, "dataset_id": str(dataset_id)},
    )
    session.add(job)
    await session.flush()
    run = await create_pending_run(
        session,
        dataset_id=dataset_id,
        origin_kind="upload",
        trigger="manual",
        triggered_by=user_id,
        ingest_job_id=job.id,
        feature_count_before=None,
    )
    run_id = run.id
    await session.commit()
    return run_id


@contextmanager
def _reupload_task(**defer):
    task = MagicMock()
    task.defer_async = AsyncMock(**defer)
    port = MagicMock()
    port.reupload_file_task.return_value = task
    with patch(
        "app.processing.ingest.manifest_service.get_catalog_port", return_value=port
    ):
        yield task


async def _runs(session, dataset_id: uuid.UUID) -> list[DatasetRefreshRun]:
    result = await session.execute(
        select(DatasetRefreshRun)
        .where(DatasetRefreshRun.dataset_id == dataset_id)
        .order_by(DatasetRefreshRun.started_at)
        .execution_options(populate_existing=True)
    )
    return list(result.scalars())


async def _newest_job(session, key: str) -> IngestJob:
    result = await session.execute(
        select(IngestJob)
        .where(IngestJob.user_metadata["manifest_key"].astext == key)
        .order_by(IngestJob.created_at.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


class TestManifestUpdateRunAdmission:
    async def test_an_update_commits_a_pending_run_before_its_defer(
        self, test_db_session, clean_tables
    ):
        """The run row is committed, bound to the job, by the time the task is deferred."""
        import app.core.db as db_module

        _stage_fixture()
        user = await _admin(test_db_session)
        user_id = user.id
        dataset_id = await _applied_dataset(test_db_session, user, "run-admitted")
        seen_at_defer: list[tuple[str, uuid.UUID | None]] = []

        async def _defer(**kwargs) -> None:
            async with db_module.async_session() as other:
                seen_at_defer.extend(
                    (run.status, run.ingest_job_id)
                    for run in await _runs(other, dataset_id)
                )

        with _reupload_task(side_effect=_defer) as task:
            response = await apply_manifest(
                test_db_session, _update("run-admitted"), user, _http_request()
            )

        result = response.results[0]
        assert result.action == "update"
        task.defer_async.assert_awaited_once()
        assert seen_at_defer == [("pending", result.job_id)]
        [run] = await _runs(test_db_session, dataset_id)
        assert run.status == "pending"
        assert (run.origin_kind, run.trigger, run.triggered_by) == (
            "upload",
            "api",
            user_id,
        )
        assert run.feature_count_before == 42

    async def test_the_reupload_worker_claims_the_run_a_manifest_admitted(
        self, test_db_session, clean_tables
    ):
        """reupload_file claims and settles the run from the deferred arguments alone."""
        _stage_fixture()
        user = await _admin(test_db_session)
        dataset_id = await _applied_dataset(test_db_session, user, "run-claimed")

        with _reupload_task() as task:
            response = await apply_manifest(
                test_db_session, _update("run-claimed"), user, _http_request()
            )
        assert response.results[0].action == "update"

        with (
            patch(
                "app.processing.ingest.service.resolve_file_path",
                new=AsyncMock(side_effect=lambda path, job_id: path),
            ),
            patch(
                "app.processing.ingest.tasks_reupload._validate_upload_file_safety",
                new=AsyncMock(side_effect=ValueError("not a vector file")),
            ),
        ):
            await reupload_file(**task.defer_async.await_args.kwargs)

        [run] = await _runs(test_db_session, dataset_id)
        assert run.claimed_at is not None
        assert (run.status, run.error_code) == ("failed", "validation_failed")

    async def test_an_update_is_refused_while_the_dataset_has_an_active_run(
        self, test_db_session, clean_tables
    ):
        """A busy dataset refuses the entry as dataset_busy and queues nothing."""
        _stage_fixture()
        user = await _admin(test_db_session)
        user_id = user.id
        dataset_id = await _applied_dataset(test_db_session, user, "run-busy")
        active_run_id = await _occupy(test_db_session, dataset_id, user_id)

        with _reupload_task() as task:
            response = await apply_manifest(
                test_db_session, _update("run-busy"), user, _http_request()
            )

        result = response.results[0]
        assert (result.action, result.errors, result.job_id) == (
            "error",
            ["dataset_busy"],
            None,
        )
        assert response.accepted is False
        task.defer_async.assert_not_awaited()
        runs = await _runs(test_db_session, dataset_id)
        assert [(run.id, run.status) for run in runs] == [(active_run_id, "pending")]
        refused = await _newest_job(test_db_session, "run-busy")
        assert refused.status == "failed"

        # The refusal released its key: once the slot frees, a re-apply goes ahead.
        assert await transition_run(
            test_db_session, active_run_id, expected=("pending",), to="failed"
        )
        await test_db_session.commit()
        with _reupload_task() as task:
            retried = await apply_manifest(
                test_db_session,
                _update("run-busy"),
                await _admin(test_db_session),
                _http_request(),
            )
        assert retried.results[0].action == "update"
        task.defer_async.assert_awaited_once()

    async def test_a_failed_defer_settles_the_job_and_its_run(
        self, test_db_session, clean_tables
    ):
        """A defer that never queued leaves both rows failed and the dataset free."""
        _stage_fixture()
        user = await _admin(test_db_session)
        dataset_id = await _applied_dataset(test_db_session, user, "run-defer-failed")

        with _reupload_task(side_effect=RuntimeError("queue down")):
            response = await apply_manifest(
                test_db_session, _update("run-defer-failed"), user, _http_request()
            )

        assert response.results[0].action == "error"
        assert "queue_unavailable" in response.results[0].message
        [run] = await _runs(test_db_session, dataset_id)
        assert (run.status, run.error_code) == ("failed", "dispatch_failed")
        job = await _newest_job(test_db_session, "run-defer-failed")
        assert (job.id, job.status) == (run.ingest_job_id, "failed")

    async def test_a_durable_bind_whose_commit_raises_fails_its_run(
        self, test_db_session, clean_tables
    ):
        """The settlement that fails the committed job fails the run beside it."""
        _stage_fixture()
        user = await _admin(test_db_session)
        dataset_id = await _applied_dataset(test_db_session, user, "run-bind-lost")

        async def _durable_then_raise(db) -> None:
            await db.commit()
            raise RuntimeError("acknowledgement lost")

        with (
            _reupload_task() as task,
            patch(
                "app.processing.ingest.manifest_service._commit_staged_bind",
                new=_durable_then_raise,
            ),
        ):
            response = await apply_manifest(
                test_db_session, _update("run-bind-lost"), user, _http_request()
            )

        assert response.results[0].action == "error"
        task.defer_async.assert_not_awaited()
        [run] = await _runs(test_db_session, dataset_id)
        assert (run.status, run.error_code) == ("failed", "dispatch_failed")
        job = await _newest_job(test_db_session, "run-bind-lost")
        assert (job.id, job.status) == (run.ingest_job_id, "failed")

    async def test_a_run_the_worker_already_claimed_is_left_to_it(
        self, test_db_session, clean_tables
    ):
        """A defer that raises after its task was taken leaves the worker's run alone."""
        import app.core.db as db_module

        _stage_fixture()
        user = await _admin(test_db_session)
        dataset_id = await _applied_dataset(test_db_session, user, "run-taken")

        async def _taken_then_raise(**kwargs) -> None:
            job_id = uuid.UUID(kwargs["job_id"])
            async with db_module.async_session() as worker:
                await worker.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job_id)
                    .values(status="running")
                )
                assert await claim_run_for_job(worker, job_id) is not None
                await worker.commit()
            raise RuntimeError("acknowledgement lost")

        with _reupload_task(side_effect=_taken_then_raise):
            await apply_manifest(
                test_db_session, _update("run-taken"), user, _http_request()
            )

        [run] = await _runs(test_db_session, dataset_id)
        assert run.status == "running"
        job = await _newest_job(test_db_session, "run-taken")
        assert job.status == "running"

    async def test_a_dataset_deleted_while_staging_fails_the_entry(
        self, test_db_session, clean_tables
    ):
        """An update whose dataset is deleted mid-staging is refused before the insert."""
        import app.core.db as db_module

        _stage_fixture()
        user = await _admin(test_db_session)
        dataset_id = await _applied_dataset(test_db_session, user, "run-deleted")
        real_stage = manifest_service._stage_source_if_needed

        async def _stage_after_delete(*args, **kwargs):
            async with db_module.async_session() as other:
                await other.execute(delete(Dataset).where(Dataset.id == dataset_id))
                await other.commit()
            return await real_stage(*args, **kwargs)

        with (
            _reupload_task() as task,
            patch.object(
                manifest_service, "_stage_source_if_needed", new=_stage_after_delete
            ),
        ):
            response = await apply_manifest(
                test_db_session, _update("run-deleted"), user, _http_request()
            )

        result = response.results[0]
        assert result.action == "error"
        assert "was deleted" in result.message
        task.defer_async.assert_not_awaited()
        assert (await _newest_job(test_db_session, "run-deleted")).status == "failed"

    async def test_a_busy_entry_does_not_stop_the_rest_of_the_manifest(
        self, test_db_session, clean_tables
    ):
        """Entries after a dataset_busy refusal still update and create."""
        _stage_fixture()
        user = await _admin(test_db_session)
        user_id = user.id
        busy_id = await _applied_dataset(test_db_session, user, "run-busy-first")
        free_id = await _applied_dataset(test_db_session, user, "run-free")
        await _occupy(test_db_session, busy_id, user_id)
        request = _request(
            _entry("run-busy-first", title="Updated roads"),
            _entry("run-free", title="Updated roads"),
            _entry("run-new"),
        )

        with (
            _reupload_task() as task,
            patch(
                "app.processing.ingest.manifest_service.queue_ingest_job",
                new=AsyncMock(),
            ) as queue,
        ):
            response = await apply_manifest(
                test_db_session, request, user, _http_request()
            )

        assert [(r.dataset_key, r.action) for r in response.results] == [
            ("run-busy-first", "error"),
            ("run-free", "update"),
            ("run-new", "create"),
        ]
        assert response.results[0].errors == ["dataset_busy"]
        task.defer_async.assert_awaited_once()
        queue.assert_awaited_once()
        [free_run] = await _runs(test_db_session, free_id)
        assert free_run.ingest_job_id == response.results[1].job_id


def _stage_then(after) -> tuple[list[str], AsyncMock]:
    """Wrap staging to record the staged path and run ``after`` once staged."""
    staged: list[str] = []
    original = manifest_service._stage_source_if_needed

    async def stage_then(*args, **kwargs):
        path = await original(*args, **kwargs)
        staged.append(path)
        await after()
        return path

    return staged, stage_then


async def _settled(key: str) -> tuple[str, str | None, bool]:
    """The newest job for ``key``: its status and error, and whether the key
    still reads as in flight."""
    import app.core.db as db_module
    from app.processing.ingest.manifest_reservation import (
        latest_in_flight_manifest_job,
    )

    async with db_module.async_session() as session:
        job = await _newest_job(session, key)
        in_flight = await latest_in_flight_manifest_job(session, key)
    return job.status, job.error_message, in_flight is not None


class TestManifestAdmissionUnderTheCatalogRows:
    async def test_a_held_dataset_row_answers_busy_and_settles_the_entry(
        self, test_db_session, clean_tables
    ):
        import app.core.db as db_module

        _stage_fixture()
        user = await _admin(test_db_session)
        dataset_id = await _applied_dataset(test_db_session, user, "row-held")
        holder = db_module.async_session()
        session = await holder.__aenter__()

        async def hold_the_row() -> None:
            await session.execute(
                select(Dataset.id)
                .where(Dataset.id == dataset_id)
                .with_for_update(key_share=True)
            )

        staged, stage_then = _stage_then(hold_the_row)
        try:
            with (
                _reupload_task() as task,
                patch.object(manifest_service, "_stage_source_if_needed", stage_then),
            ):
                response = await apply_manifest(
                    test_db_session, _update("row-held"), user, _http_request()
                )
        finally:
            await session.rollback()
            await holder.__aexit__(None, None, None)

        assert response.results[0].errors == ["dataset_busy"]
        task.defer_async.assert_not_awaited()
        status, _error, in_flight = await _settled("row-held")
        assert status == "failed"
        assert not in_flight
        assert staged and not Path(staged[0]).exists()
        assert await _runs(test_db_session, dataset_id) == []

    async def test_a_caller_deactivated_while_staging_is_refused_as_revoked(
        self, test_db_session, clean_tables, client, admin_auth_header
    ):
        from app.processing.ingest.publication import WriteAccessRevoked
        from tests.factories import create_user
        from tests.write_recheck_races import _commit, _deactivate

        _stage_fixture()
        # Local sources are admin-only, so the caller starts as an admin.
        _, caller_id = await create_user(client, admin_auth_header, "admin")
        caller = await test_db_session.get(User, uuid.UUID(caller_id))
        await _applied_dataset(test_db_session, caller, "row-lost")

        async def deactivate() -> None:
            await _commit(_deactivate(uuid.UUID(caller_id)))

        staged, stage_then = _stage_then(deactivate)
        with (
            _reupload_task() as task,
            patch.object(manifest_service, "_stage_source_if_needed", stage_then),
        ):
            response = await apply_manifest(
                test_db_session, _update("row-lost"), caller, _http_request()
            )

        assert response.results[0].action == "error"
        assert response.results[0].message == str(WriteAccessRevoked())
        task.defer_async.assert_not_awaited()
        status, error, in_flight = await _settled("row-lost")
        assert (status, error, in_flight) == (
            "failed",
            str(WriteAccessRevoked()),
            False,
        )
        assert staged and not Path(staged[0]).exists()


async def _wait_until_it_blocks_a_writer(session) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        # The activity view is snapshotted once per transaction.
        await session.execute(text("SELECT pg_stat_clear_snapshot()"))
        if await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE pg_backend_pid() = ANY(pg_blocking_pids(pid))"
            )
        ):
            return
        await asyncio.sleep(0.1)
    pytest.fail("the re-upload commit never waited on the manifest")


class TestManifestAdmissionAgainstAReuploadCommit:
    async def test_a_commit_racing_the_admission_is_refused_busy(
        self, test_db_session, clean_tables, client, admin_auth_header
    ):
        """A re-upload commit that reaches the dataset while the manifest holds
        its catalog rows queues behind the manifest and answers dataset_busy."""
        from app.modules.catalog import authorization

        _stage_fixture()
        user = await _admin(test_db_session)
        dataset_id = await _applied_dataset(test_db_session, user, "commit-race")
        reupload = IngestJob(
            dataset_id=dataset_id,
            status="pending",
            attempt_id=uuid.uuid4(),
            source_filename="parcels.gpkg",
            file_path="/tmp/commit-race-reupload.gpkg",
            created_by=user.id,
            user_metadata={"reupload": True, "dataset_id": str(dataset_id)},
        )
        test_db_session.add(reupload)
        await test_db_session.commit()
        reupload_id = reupload.id
        original_lock = authorization.lock_dataset_rows_for_write
        commits: list[asyncio.Task] = []

        async def lock_then_race(db, dataset, **kwargs):
            await original_lock(db, dataset, **kwargs)
            if db is test_db_session and not commits:
                # A context of its own, as a separate request has: the
                # manifest's lock-timeout marker must not leak into it.
                commits.append(
                    asyncio.create_task(
                        client.post(
                            f"/datasets/{dataset_id}/reupload/{reupload_id}/commit",
                            json={},
                            headers=admin_auth_header,
                        ),
                        context=contextvars.Context(),
                    )
                )
                await _wait_until_it_blocks_a_writer(db)

        with (
            _reupload_task() as task,
            patch.object(authorization, "lock_dataset_rows_for_write", lock_then_race),
            patch(
                "app.modules.catalog.datasets.api.router_reupload.defer_with_orphan_guard",
                new=AsyncMock(),
            ),
        ):
            response = await apply_manifest(
                test_db_session, _update("commit-race"), user, _http_request()
            )
            refused = await commits[0]

        result = response.results[0]
        assert result.action == "update", result
        task.defer_async.assert_awaited_once()
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["code"] == "dataset_busy"
        [run] = await _runs(test_db_session, dataset_id)
        assert run.ingest_job_id == result.job_id
        await test_db_session.refresh(reupload)
        assert reupload.status == "pending"


class _ContractReadingExtension(DefaultPermissionExtension):
    """Reads the whole identity contract on every check, as an overlay may."""

    def __init__(self) -> None:
        self.denied = False

    @staticmethod
    def _read(user) -> None:
        _ = (user.id, user.username, user.email, user.is_active, user.created_at)
        _ = [role.name for role in user.roles]

    async def can_access_dataset(self, db, dataset, dataset_id, user, *, user_roles):
        if user is not None:
            self._read(user)
        if self.denied:
            return False
        return await super().can_access_dataset(
            db, dataset, dataset_id, user, user_roles=user_roles
        )

    async def check_permission(self, db, user, capability, **kwargs):
        self._read(user)
        return await super().check_permission(db, user, capability, **kwargs)


class TestManifestAdmissionWithAnOverlayPermissionExtension:
    @pytest.mark.parametrize("denied", [False, True])
    async def test_the_admission_hands_the_extension_a_full_identity(
        self, test_db_session, clean_tables, monkeypatch, denied
    ):
        from app.platform import extensions
        from app.processing.ingest.publication import WriteAccessRevoked

        _stage_fixture()
        user = await _admin(test_db_session)
        await _applied_dataset(test_db_session, user, "overlay-identity")
        extension = _ContractReadingExtension()
        monkeypatch.setitem(extensions._extensions, "permission", extension)

        async def deny() -> None:
            extension.denied = denied

        _staged, stage_then = _stage_then(deny)
        with (
            _reupload_task() as task,
            patch.object(manifest_service, "_stage_source_if_needed", stage_then),
        ):
            response = await apply_manifest(
                test_db_session, _update("overlay-identity"), user, _http_request()
            )

        result = response.results[0]
        if denied:
            assert result.action == "error"
            assert result.message == str(WriteAccessRevoked())
            task.defer_async.assert_not_awaited()
        else:
            assert result.action == "update", result
            task.defer_async.assert_awaited_once()


_S3_BUCKET = "manifest-seed-bucket"


def _raw_source_entry(key: str, uri: str) -> dict:
    entry = _entry(key, title="Updated roads")
    entry["sources"] = [{"type": "vector", "uri": uri, "format": "geojson"}]
    return entry


class TestRawSeedSourceNeedsAnAdmin:
    """Local staging paths and same-bucket keys are admin-only seed sources, so
    an update that reads one is held to its caller still being an admin."""

    @pytest.mark.parametrize("demoted", [True, False])
    @pytest.mark.parametrize(
        "uri",
        [
            _FIXTURE,
            f"./{_FIXTURE}",
            f"{Path(settings.upload_staging_dir).name}/{_FIXTURE}",
            f"s3://{_S3_BUCKET}/seed/roads.geojson",
        ],
    )
    async def test_a_raw_source_update_rechecks_its_admin(
        self,
        test_db_session,
        clean_tables,
        client,
        admin_auth_header,
        monkeypatch,
        uri,
        demoted,
    ):
        from app.processing.ingest.publication import WriteAccessRevoked
        from tests.factories import create_user
        from tests.write_recheck_races import _commit, _move_to_role

        _stage_fixture()
        _, caller_id = await create_user(client, admin_auth_header, "admin")
        caller = await test_db_session.get(User, uuid.UUID(caller_id))
        dataset_id = await _applied_dataset(test_db_session, caller, "raw-seed")
        # Reloaded after the commits above expired it.
        caller = await test_db_session.get(User, uuid.UUID(caller_id))

        async def demote() -> None:
            if demoted:
                await _commit(_move_to_role(uuid.UUID(caller_id), "editor"))

        staged, stage_then = _stage_then(demote)
        if uri.startswith("s3://"):
            monkeypatch.setattr(settings, "storage_provider", "s3")
            monkeypatch.setattr(settings, "s3_bucket", _S3_BUCKET)
            # The test storage serves keys from the staging directory.
            key = Path(settings.upload_staging_dir) / "seed/roads.geojson"
            key.parent.mkdir(parents=True, exist_ok=True)
            copyfile(Path(settings.upload_staging_dir) / _FIXTURE, key)
        with (
            _reupload_task() as task,
            patch.object(manifest_service, "_stage_source_if_needed", stage_then),
        ):
            response = await apply_manifest(
                test_db_session,
                _request(_raw_source_entry("raw-seed", uri)),
                caller,
                _http_request(),
            )

        result = response.results[0]
        if demoted:
            assert result.action == "error", result
            assert result.message == str(WriteAccessRevoked())
            task.defer_async.assert_not_awaited()
            assert await _runs(test_db_session, dataset_id) == []
        else:
            assert result.action == "update", result
            task.defer_async.assert_awaited_once()
            job = await _newest_job(test_db_session, "raw-seed")
            assert job.user_metadata["admitted_raw_source"] is True
