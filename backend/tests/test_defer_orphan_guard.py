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

    def test_make_vrt_regeneration_failed_rollback_reverts_all_eight_fields(self):
        """fix(#1435): the factory the three VRT regeneration endpoints (add-source,
        remove-source, refresh) now share must revert every field their old
        hand-rolled closures did: vrt_asset.status/current_generation_id,
        generation.status/completed_at/error_message, and
        job.status/error_message/completed_at (the last three via
        `make_ingest_job_failed_rollback`, reused rather than duplicated).

        No single one of the three endpoint-level tests below asserts all
        eight together — this is the one place that does.
        """

        async def _check():
            from app.platform.jobs.defer_guard import (
                make_vrt_regeneration_failed_rollback,
            )

            vrt_asset = MagicMock()
            vrt_asset.status = "regenerating"
            vrt_asset.current_generation_id = uuid.uuid4()
            previous_status = "ready"
            previous_generation_id = uuid.uuid4()

            generation = MagicMock()
            generation.status = "pending"
            generation.completed_at = None
            generation.error_message = None

            job = MagicMock()
            job.status = "pending"
            job.error_message = None
            job.completed_at = None

            rollback = make_vrt_regeneration_failed_rollback(
                vrt_asset,
                generation,
                job,
                previous_status=previous_status,
                previous_generation_id=previous_generation_id,
            )
            exc = RuntimeError("procrastinate unreachable")
            await rollback(exc)

            assert vrt_asset.status == previous_status
            assert vrt_asset.current_generation_id == previous_generation_id
            assert generation.status == "failed"
            assert generation.completed_at is not None
            assert "procrastinate unreachable" in generation.error_message
            assert job.status == "failed"
            assert job.completed_at is not None
            assert "procrastinate unreachable" in job.error_message

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
    # feat(#1219): the handler now inserts a refresh run row before deferring.
    # `create_pending_run` reads the parent dataset's stored tenant_id and
    # wraps its INSERT in a SAVEPOINT so a duplicate-active-run violation can
    # be turned into a 409 without poisoning the transaction. An AsyncMock's
    # `begin_nested()` returns a coroutine, which is not an async context
    # manager, so it has to be spelled out here.
    mock_db.scalar = AsyncMock(return_value=None)
    mock_db.begin_nested = MagicMock(return_value=_null_async_cm())
    return mock_db


def _null_async_cm():
    """A do-nothing async context manager for a mocked SAVEPOINT."""

    @asynccontextmanager
    async def _cm():
        yield None

    return _cm()


def _bind_reupload_job(
    job: MagicMock, *, dataset_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Give router-unit-test jobs the same immutable bindings as real uploads."""
    job.dataset_id = dataset_id
    job.created_by = user_id
    job.user_metadata = {
        "reupload": True,
        "dataset_id": str(dataset_id),
    }


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
            _bind_reupload_job(job, dataset_id=dataset_id, user_id=mock_user.id)

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
                    "app.modules.catalog.datasets.api.router_reupload.check_dataset_write_access",
                    new=AsyncMock(),
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
            _bind_reupload_job(job, dataset_id=dataset_id, user_id=mock_user.id)

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
                    "app.modules.catalog.datasets.api.router_reupload.check_dataset_write_access",
                    new=AsyncMock(),
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
            _bind_reupload_job(job, dataset_id=dataset_id, user_id=mock_user.id)

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
                    "app.modules.catalog.datasets.api.router_reupload.check_dataset_write_access",
                    new=AsyncMock(),
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

    @pytest.fixture(autouse=True)
    def _stub_vrt_source_authz(self):
        """SEC-C (Phase 1172): add_vrt_source authorizes the new source and the
        parent VRT, and both add/remove_vrt_source now require owner-or-admin on
        the VRT via ``check_dataset_write_access`` — each helper issues its own
        ``db.execute`` calls that would shift the call-count-ordered mock ``db``
        sequence. Stub them to make ZERO db.execute calls (and always allow) so
        the sequence stays valid; the authorization behavior is covered by
        ``tests/test_vrt_source_authz_1172.py``.
        """
        with (
            patch(
                "app.modules.catalog.authorization.get_user_roles",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "app.modules.catalog.authorization.check_dataset_access",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "app.modules.catalog.authorization.check_dataset_write_access",
                new=AsyncMock(return_value=set()),
            ),
            patch(
                "app.modules.catalog.datasets.domain.service.get_dataset",
                new=AsyncMock(return_value=MagicMock()),
            ),
        ):
            yield

    def test_add_vrt_source_defer_failure_reverts_state_and_raises_503(self):
        """VRT add_source defer crash must revert ``vrt_asset.status``, mark the
        IngestJob failed, and raise 503.

        fix(#1327): it must also NOT delete a source link, because it never
        inserted one — the member set is staged on the VrtGeneration row and
        applied only when the regeneration publishes. What used to be the
        rollback's compensating DELETE is now nothing to compensate, and this
        test pins that direction: no statement against vrt_source_links other
        than the ordered read the endpoint does up front."""

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
                # fix(#1327): there is no 6th query. The MAX(position) lookup,
                # the link INSERT and the rollback's compensating DELETE are
                # all gone with the staged member set.
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
                patch(
                    "app.processing.ingest.router.regenerate_vrt_staged"
                ) as mock_task,
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
            # fix(#1327): the link table was only READ. No INSERT to undo, so
            # no DELETE to issue — the compensation the rollback used to owe.
            statements = "\n".join(
                str(call.args[0]) for call in mock_db.execute.await_args_list
            )
            assert "INSERT INTO catalog.vrt_source_links" not in statements
            assert "DELETE FROM catalog.vrt_source_links" not in statements

        asyncio.run(_check())

    def test_remove_vrt_source_defer_failure_reverts_state_and_raises_503(self):
        """VRT remove_source defer crash must revert state, mark the job
        failed, and raise 503.

        fix(#1327): the rollback used to re-INSERT the link it had deleted, at
        the position it had captured. Nothing is deleted now — the post-removal
        set is staged on the generation — so the compensation is gone and the
        member set is untouched throughout."""

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
            other_member_ids = [uuid.uuid4(), uuid.uuid4()]

            def execute_side_effect(query, params=None):
                call_count[0] += 1
                n = call_count[0]
                result_mock = MagicMock()
                if n == 1:
                    # 1. Load VRT RasterAsset
                    result_mock.scalar_one_or_none.return_value = vrt_asset
                elif n == 2:
                    # fix(#1327): 3. ONE ordered read of the member set — it
                    # answers the count guard, the "is it linked" guard and the
                    # staged post-removal set. The separate COUNT(*), the
                    # position lookup, the DELETE and the rollback's re-INSERT
                    # are all gone.
                    result_mock.fetchall.return_value = [
                        MagicMock(source_dataset_id=other_member_ids[0]),
                        MagicMock(source_dataset_id=source_dataset_id),
                        MagicMock(source_dataset_id=other_member_ids[1]),
                    ]
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
                patch(
                    "app.processing.ingest.router.regenerate_vrt_staged"
                ) as mock_task,
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
            # fix(#1327): the member set was only READ — the removal lived on
            # the generation and died with it.
            statements = "\n".join(
                str(call.args[0]) for call in mock_db.execute.await_args_list
            )
            assert "DELETE FROM catalog.vrt_source_links" not in statements
            assert "INSERT INTO catalog.vrt_source_links" not in statements
            from app.processing.raster.models import VrtGeneration

            staged = [
                call.args[0]
                for call in mock_db.add.call_args_list
                if isinstance(call.args[0], VrtGeneration)
            ]
            assert len(staged) == 1
            assert staged[0].staged_source_ids == [str(sid) for sid in other_member_ids]

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
                    "app.modules.catalog.datasets.api.router_vrt.check_dataset_write_access",
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
