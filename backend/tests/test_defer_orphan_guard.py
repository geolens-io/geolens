"""Theme H — Procrastinate defer-async orphan-guard regression tests.

Covers ``app.jobs.defer_guard.defer_with_orphan_guard`` and its
application to the six ``defer_async`` call sites that commit DB state
*before* dispatching a Procrastinate task:

- ``datasets/router_reupload.py``: reupload_service, reupload_file
  priority, reupload_file default (3 sites)
- ``ingest/router.py``: add_vrt_source, remove_vrt_source (2 sites)
- ``datasets/router_vrt.py``: regenerate_vrt_endpoint (1 site)

Each test simulates Procrastinate being unreachable by patching the
task's ``defer_async`` to raise, then asserts the handler:
  1. Invokes the caller-supplied rollback to revert committed state.
  2. Marks the relevant ``IngestJob`` row ``failed`` (or, for VRT,
     reverts ``vrt_asset.status`` + ``current_generation_id`` too).
  3. Raises ``HTTPException 503``.

Pure-unit style: no DB, no real files, no network. Mirrors the pattern
in ``test_ingest.py::test_queue_ingest_job_*_defer_failure_marks_job_failed``
and ``test_vrt_creation_173.py::test_defer_failure_marks_job_failed_and_raises_503``.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helper unit tests — defer_with_orphan_guard contract
# ---------------------------------------------------------------------------


class TestDeferWithOrphanGuard:
    """Unit tests for the generic ``defer_with_orphan_guard`` helper."""

    def test_success_path_does_not_invoke_rollback(self):
        """On a successful defer, rollback must not run and db.commit stays untouched."""

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

            await defer_with_orphan_guard(_defer, rollback=_rollback, db=mock_db)

            assert defer_called == [True]
            assert rollback_called == []
            mock_db.commit.assert_not_called()

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
                await defer_with_orphan_guard(_defer, rollback=_rollback, db=mock_db)

            assert exc_info.value.status_code == 503
            assert "retry" in str(exc_info.value.detail).lower()
            # Rollback received the underlying exception
            assert len(received_exc) == 1
            assert isinstance(received_exc[0], RuntimeError)
            assert "procrastinate unreachable" in str(received_exc[0])
            # Helper committed the rollback before raising
            mock_db.commit.assert_awaited_once()

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
                await defer_with_orphan_guard(_defer, rollback=_rollback, db=mock_db)

            # 503 is always raised — rollback failure is logged, not swallowed.
            assert exc_info.value.status_code == 503

        asyncio.run(_check())

    def test_make_ingest_job_failed_rollback_marks_job_failed(self):
        """Convenience rollback helper mutates the IngestJob in-place."""

        async def _check():
            from app.platform.jobs.defer_guard import make_ingest_job_failed_rollback

            job = MagicMock()
            job.status = "pending"
            job.error_message = None
            job.completed_at = None

            rollback = make_ingest_job_failed_rollback(
                job, message_prefix="Failed to queue custom task"
            )
            exc = RuntimeError("queue dead")
            await rollback(exc)

            assert job.status == "failed"
            assert "Failed to queue custom task" in job.error_message
            assert "queue dead" in job.error_message
            assert job.completed_at is not None

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# Reupload router — 3 defer sites
# ---------------------------------------------------------------------------


def _make_reupload_job(
    *,
    source_url: str | None = None,
    file_path: str | None = None,
) -> MagicMock:
    job = MagicMock()
    job.id = uuid.uuid4()
    job.status = "pending"
    job.error_message = None
    job.completed_at = None
    job.source_url = source_url
    job.file_path = file_path
    job.source_layer = "layer1" if source_url else None
    job.user_metadata = {}
    job.dataset_id = None
    return job


def _make_reupload_db(job: MagicMock) -> AsyncMock:
    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    # First execute returns the dataset (not-None), second returns the job.
    # The reupload_commit handler does: get_dataset + select(IngestJob).
    # get_dataset is patched separately; the job select returns the job.
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = job
    mock_db.execute = AsyncMock(return_value=result_mock)
    return mock_db


class TestReuploadOrphanGuard:
    """Verify reupload defer sites flip the job to ``failed`` on defer failure."""

    def test_reupload_service_defer_failure_marks_job_failed(self):
        """RESILIENCE-2 extension: service reupload defer crash → 503 + failed job."""

        async def _check():
            from app.modules.catalog.datasets.api.router_reupload import reupload_commit
            from app.modules.catalog.datasets.domain.schemas import (
                ReuploadCommitRequest,
            )

            dataset_id = uuid.uuid4()
            job = _make_reupload_job(source_url="https://example.com/arcgis/0")
            mock_db = _make_reupload_db(job)
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            mock_dataset = MagicMock()

            request = ReuploadCommitRequest(token=None)

            failing_defer = AsyncMock(
                side_effect=RuntimeError("reupload_service queue down")
            )
            mock_port = MagicMock()
            mock_task = MagicMock()
            mock_task.defer_async = failing_defer
            mock_port.reupload_service_task.return_value = mock_task

            with (
                patch(
                    "app.modules.catalog.datasets.api.router_reupload.get_dataset",
                    new=AsyncMock(return_value=mock_dataset),
                ),
                patch(
                    "app.modules.catalog.datasets.api.router_reupload.get_catalog_port",
                    return_value=mock_port,
                ),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await reupload_commit(
                        dataset_id, job.id, request, mock_user, mock_db
                    )

            assert exc_info.value.status_code == 503
            assert job.status == "failed"
            assert "reupload_service queue down" in job.error_message
            assert job.completed_at is not None

        asyncio.run(_check())

    def test_reupload_file_priority_defer_failure_marks_job_failed(self, tmp_path):
        """Priority-queue reupload defer crash → 503 + failed job."""

        async def _check():
            from app.modules.catalog.datasets.api.router_reupload import reupload_commit
            from app.modules.catalog.datasets.domain.schemas import (
                ReuploadCommitRequest,
            )

            upload_file = tmp_path / "tiny.geojson"
            upload_file.write_text('{"type":"FeatureCollection","features":[]}')

            dataset_id = uuid.uuid4()
            job = _make_reupload_job(file_path=str(upload_file))
            mock_db = _make_reupload_db(job)
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            mock_dataset = MagicMock()
            request = ReuploadCommitRequest(token=None)

            failing_defer = AsyncMock(side_effect=RuntimeError("priority queue dead"))
            mock_port = MagicMock()
            mock_task = MagicMock()
            priority_task = MagicMock()
            priority_task.defer_async = failing_defer
            mock_task.configure.return_value = priority_task
            mock_task.defer_async = failing_defer
            mock_port.reupload_file_task.return_value = mock_task
            mock_port.priority_queue_threshold_bytes = 10_000_000

            with (
                patch(
                    "app.modules.catalog.datasets.api.router_reupload.get_dataset",
                    new=AsyncMock(return_value=mock_dataset),
                ),
                patch(
                    "app.modules.catalog.datasets.api.router_reupload.get_catalog_port",
                    return_value=mock_port,
                ),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await reupload_commit(
                        dataset_id, job.id, request, mock_user, mock_db
                    )

            assert exc_info.value.status_code == 503
            assert job.status == "failed"
            assert "priority queue dead" in job.error_message

        asyncio.run(_check())

    def test_reupload_file_default_defer_failure_marks_job_failed(self):
        """Default-queue reupload (no local file) defer crash → 503 + failed job."""

        async def _check():
            from app.modules.catalog.datasets.api.router_reupload import reupload_commit
            from app.modules.catalog.datasets.domain.schemas import (
                ReuploadCommitRequest,
            )

            # Non-local path (S3-ish) — triggers the default-queue branch.
            dataset_id = uuid.uuid4()
            job = _make_reupload_job(file_path="s3://bucket/path/file.geojson")
            mock_db = _make_reupload_db(job)
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            mock_dataset = MagicMock()
            request = ReuploadCommitRequest(token=None)

            failing_defer = AsyncMock(side_effect=RuntimeError("default queue dead"))
            mock_port = MagicMock()
            mock_task = MagicMock()
            mock_task.defer_async = failing_defer
            mock_port.reupload_file_task.return_value = mock_task
            mock_port.priority_queue_threshold_bytes = 10_000_000

            with (
                patch(
                    "app.modules.catalog.datasets.api.router_reupload.get_dataset",
                    new=AsyncMock(return_value=mock_dataset),
                ),
                patch(
                    "app.modules.catalog.datasets.api.router_reupload.get_catalog_port",
                    return_value=mock_port,
                ),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await reupload_commit(
                        dataset_id, job.id, request, mock_user, mock_db
                    )

            assert exc_info.value.status_code == 503
            assert job.status == "failed"
            assert "default queue dead" in job.error_message

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# VRT source add/remove — ingest/router.py
# ---------------------------------------------------------------------------


def _make_vrt_asset(status: str = "ready") -> MagicMock:
    asset = MagicMock()
    asset.status = status
    asset.vrt_type = "mosaic"
    asset.current_generation_id = uuid.uuid4()
    asset.dataset_id = uuid.uuid4()
    return asset


class TestVrtSourceOrphanGuard:
    """Verify VRT add/remove defer failures revert asset state + mark job failed."""

    def test_add_vrt_source_defer_failure_reverts_state_and_raises_503(self):
        """VRT add_source defer crash must revert ``vrt_asset.status``, delete
        the inserted source link, mark the IngestJob failed, and raise 503."""

        async def _check():
            from app.processing.ingest.router import add_vrt_source
            from app.processing.ingest.schemas import VrtAddSourceRequest

            dataset_id = uuid.uuid4()
            source_id = uuid.uuid4()
            request = VrtAddSourceRequest(source_dataset_id=source_id)
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            vrt_asset = _make_vrt_asset(status="ready")
            original_status = vrt_asset.status
            original_generation_id = vrt_asset.current_generation_id

            source_asset = MagicMock()
            existing_source_asset = MagicMock()

            job_id = uuid.uuid4()
            mock_job = MagicMock()
            mock_job.id = job_id
            mock_job.status = "pending"
            mock_job.error_message = None
            mock_job.completed_at = None

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            call_count = [0]

            def execute_side_effect(query, params=None):
                call_count[0] += 1
                n = call_count[0]
                result_mock = MagicMock()
                if n == 1:
                    # 1. Load VRT RasterAsset
                    result_mock.scalar_one_or_none.return_value = vrt_asset
                elif n == 2:
                    # 3. Validate source exists
                    result_mock.scalar_one_or_none.return_value = source_asset
                elif n == 3:
                    # 4. Duplicate check — not found
                    result_mock.fetchone.return_value = None
                elif n == 4:
                    # 5. Existing source links
                    result_mock.fetchall.return_value = [
                        MagicMock(source_dataset_id=uuid.uuid4())
                    ]
                elif n == 5:
                    # 5. Existing assets
                    result_mock.scalars.return_value.all.return_value = [
                        existing_source_asset
                    ]
                elif n == 6:
                    # 6. Max position
                    result_mock.scalar.return_value = 0
                # n == 7: INSERT (no return needed)
                # n == 8: DELETE (rollback re-deletes)
                return result_mock

            mock_db.execute = AsyncMock(side_effect=execute_side_effect)

            async def mock_create_ingest_job(db, *args, **kwargs):
                return mock_job

            failing_defer = AsyncMock(
                side_effect=RuntimeError("vrt add_source queue dead")
            )

            with (
                patch(
                    "app.processing.ingest.router.create_ingest_job",
                    new=mock_create_ingest_job,
                ),
                patch("app.processing.ingest.router.validate_sources", return_value=[]),
                patch("app.processing.ingest.router.regenerate_vrt") as mock_task,
            ):
                mock_task.defer_async = failing_defer
                with pytest.raises(HTTPException) as exc_info:
                    await add_vrt_source(dataset_id, request, mock_user, mock_db)

            assert exc_info.value.status_code == 503
            # VRT asset state reverted
            assert vrt_asset.status == original_status
            assert vrt_asset.current_generation_id == original_generation_id
            # IngestJob marked failed
            assert mock_job.status == "failed"
            assert "vrt add_source queue dead" in mock_job.error_message
            # At least one DELETE must have been issued for the inserted link
            # (call index 8 onwards corresponds to the rollback DELETE).
            assert call_count[0] >= 8

        asyncio.run(_check())

    def test_remove_vrt_source_defer_failure_reverts_state_and_raises_503(self):
        """VRT remove_source defer crash must revert state, re-insert the
        deleted source link with its original position, mark the job failed,
        and raise 503."""

        async def _check():
            from app.processing.ingest.router import remove_vrt_source

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            vrt_asset = _make_vrt_asset(status="ready")
            original_status = vrt_asset.status
            original_generation_id = vrt_asset.current_generation_id

            job_id = uuid.uuid4()
            mock_job = MagicMock()
            mock_job.id = job_id
            mock_job.status = "pending"
            mock_job.error_message = None
            mock_job.completed_at = None

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()

            call_count = [0]
            rollback_insert_params: dict = {}

            def execute_side_effect(query, params=None):
                call_count[0] += 1
                n = call_count[0]
                result_mock = MagicMock()
                if n == 1:
                    # 1. Load VRT RasterAsset
                    result_mock.scalar_one_or_none.return_value = vrt_asset
                elif n == 2:
                    # 3. Source count
                    result_mock.scalar.return_value = 3
                elif n == 3:
                    # 4. Link existence check — found with position=5
                    link_row = MagicMock()
                    link_row.position = 5
                    result_mock.fetchone.return_value = link_row
                elif n == 4:
                    # 5. DELETE link
                    pass
                elif n == 5:
                    # Rollback: INSERT link
                    rollback_insert_params.update(params or {})
                return result_mock

            mock_db.execute = AsyncMock(side_effect=execute_side_effect)

            async def mock_create_ingest_job(db, *args, **kwargs):
                return mock_job

            failing_defer = AsyncMock(
                side_effect=RuntimeError("vrt remove_source queue dead")
            )

            with (
                patch(
                    "app.processing.ingest.router.create_ingest_job",
                    new=mock_create_ingest_job,
                ),
                patch("app.processing.ingest.router.regenerate_vrt") as mock_task,
            ):
                mock_task.defer_async = failing_defer
                with pytest.raises(HTTPException) as exc_info:
                    await remove_vrt_source(
                        dataset_id, source_dataset_id, mock_user, mock_db
                    )

            assert exc_info.value.status_code == 503
            # VRT asset state reverted
            assert vrt_asset.status == original_status
            assert vrt_asset.current_generation_id == original_generation_id
            # IngestJob marked failed
            assert mock_job.status == "failed"
            assert "vrt remove_source queue dead" in mock_job.error_message
            # Rollback re-inserted the link with the captured position=5
            assert rollback_insert_params.get("pos") == 5
            assert rollback_insert_params.get("src_id") == source_dataset_id

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# VRT datasets router — regenerate_vrt_endpoint
# ---------------------------------------------------------------------------


class TestDatasetsVrtOrphanGuard:
    """Verify datasets/router_vrt.py::regenerate_vrt_endpoint defer-failure path."""

    def test_regenerate_vrt_defer_failure_reverts_state_and_marks_generation_failed(
        self,
    ):
        """Defer crash during manual VRT regen must: revert ``vrt_asset``
        state, mark ``VrtGeneration`` + ``IngestJob`` failed, raise 503."""

        async def _check():
            from app.modules.catalog.datasets.api.router_vrt import (
                regenerate_vrt_endpoint,
            )

            dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            vrt_asset = _make_vrt_asset(status="ready")
            original_status = vrt_asset.status
            original_generation_id = vrt_asset.current_generation_id

            generation = MagicMock()
            generation.id = uuid.uuid4()
            generation.status = "pending"
            generation.completed_at = None
            generation.error_message = None

            job_id = uuid.uuid4()
            mock_job = MagicMock()
            mock_job.id = job_id
            mock_job.status = "pending"
            mock_job.error_message = None
            mock_job.completed_at = None

            # Mock dataset with vrt_dataset record_type
            mock_record = MagicMock()
            mock_record.record_type = "vrt_dataset"
            mock_dataset = MagicMock()
            mock_dataset.record = mock_record

            mock_db = AsyncMock()
            mock_db.commit = AsyncMock()
            mock_db.flush = AsyncMock()
            mock_db.add = MagicMock()

            call_count = [0]

            def execute_side_effect(query, params=None):
                call_count[0] += 1
                n = call_count[0]
                result_mock = MagicMock()
                if n == 1:
                    # Load VRT RasterAsset
                    result_mock.scalar_one_or_none.return_value = vrt_asset
                elif n == 2:
                    # Advisory lock acquired
                    result_mock.scalar.return_value = True
                elif n == 3:
                    # Source count
                    result_mock.scalar.return_value = 3
                return result_mock

            mock_db.execute = AsyncMock(side_effect=execute_side_effect)

            async def mock_create_ingest_job(db, *args, **kwargs):
                return mock_job

            # Patch VrtGeneration constructor to return our tracked mock
            # so we can assert its fields were updated in rollback.
            def mock_vrt_generation_ctor(**kwargs):
                generation.vrt_dataset_id = kwargs.get("vrt_dataset_id")
                generation.source_count = kwargs.get("source_count")
                generation.triggered_by = kwargs.get("triggered_by")
                return generation

            failing_defer = AsyncMock(
                side_effect=RuntimeError("regenerate_vrt queue dead")
            )

            with (
                patch(
                    "app.modules.catalog.datasets.api.router_vrt.get_dataset",
                    new=AsyncMock(return_value=mock_dataset),
                ),
                patch(
                    "app.modules.catalog.datasets.api.router_vrt.check_dataset_access",
                    new=AsyncMock(),
                ),
                patch(
                    "app.processing.ingest.service.create_ingest_job",
                    new=mock_create_ingest_job,
                ),
                patch(
                    "app.processing.raster.models.VrtGeneration",
                    side_effect=mock_vrt_generation_ctor,
                ),
                patch("app.processing.ingest.tasks.regenerate_vrt") as mock_task,
            ):
                mock_task.defer_async = failing_defer
                with pytest.raises(HTTPException) as exc_info:
                    await regenerate_vrt_endpoint(dataset_id, mock_user, mock_db)

            assert exc_info.value.status_code == 503
            # VRT asset state reverted
            assert vrt_asset.status == original_status
            assert vrt_asset.current_generation_id == original_generation_id
            # VrtGeneration marked failed
            assert generation.status == "failed"
            assert "regenerate_vrt queue dead" in (generation.error_message or "")
            assert generation.completed_at is not None
            # IngestJob marked failed
            assert mock_job.status == "failed"
            assert "regenerate_vrt queue dead" in mock_job.error_message

        asyncio.run(_check())
