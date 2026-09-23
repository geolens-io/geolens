"""A manifest update is admitted through a refresh run, like every other door."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset
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
