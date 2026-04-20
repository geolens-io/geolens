"""Tests for VRT source add/remove endpoints, regenerate_vrt task, and status serialization (Phase 174-01).

Covers:
- TestAddSource: POST /ingest/vrt/{dataset_id}/sources/ endpoint behavior
- TestRemoveSource: DELETE /ingest/vrt/{dataset_id}/sources/{source_dataset_id}/ endpoint behavior
- TestMutationSerialization: 409 when VRT is regenerating (SRC-05)
- TestRegenerateVrtTask: regenerate_vrt task logic (build, swap, metadata update, error handling)
- TestStatusField: GET /datasets/{id} response includes raster.status (SRC-06)

All tests are pure unit tests -- no DB, no real files, no network.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.processing.ingest.schemas import VrtAddSourceRequest, VrtMutationResponse
from app.modules.catalog.datasets.domain.schemas import RasterMetadata


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_mock_asset(
    status: str = "ready",
    vrt_type: str = "mosaic",
    resolution_strategy: str = "finest",
    asset_uri: str = "rasters/vrt-id/abc123/source.vrt",
    quicklook_256_uri: str = "rasters/vrt-id/abc123/quicklook_256.png",
    quicklook_512_uri: str = "rasters/vrt-id/abc123/quicklook_512.png",
    band_count: int = 1,
    epsg: int = 4326,
) -> MagicMock:
    asset = MagicMock()
    asset.status = status
    asset.vrt_type = vrt_type
    asset.resolution_strategy = resolution_strategy
    asset.asset_uri = asset_uri
    asset.quicklook_256_uri = quicklook_256_uri
    asset.quicklook_512_uri = quicklook_512_uri
    asset.band_count = band_count
    asset.epsg = epsg
    asset.dataset_id = uuid.uuid4()
    return asset


def _make_mock_source_asset(band_count: int = 1, epsg: int = 4326) -> MagicMock:
    asset = MagicMock()
    asset.band_count = band_count
    asset.epsg = epsg
    asset.dataset_id = uuid.uuid4()
    asset.asset_uri = f"rasters/{uuid.uuid4()}/hash/source.cog.tif"
    return asset


# ---------------------------------------------------------------------------
# TestAddSourceSchemas
# ---------------------------------------------------------------------------


class TestAddSourceSchemas:
    """Schema validation for VrtAddSourceRequest and VrtMutationResponse."""

    def test_add_source_request_accepts_valid_uuid(self):
        source_id = uuid.uuid4()
        req = VrtAddSourceRequest(source_dataset_id=source_id)
        assert req.source_dataset_id == source_id

    def test_add_source_request_rejects_non_uuid(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            VrtAddSourceRequest(source_dataset_id="not-a-uuid")

    def test_mutation_response_default_status_is_accepted(self):
        resp = VrtMutationResponse(job_id=uuid.uuid4(), message="done")
        assert resp.status == "accepted"

    def test_mutation_response_accepts_job_id(self):
        job_id = uuid.uuid4()
        resp = VrtMutationResponse(
            job_id=job_id, message="Source added, VRT regeneration started"
        )
        assert resp.job_id == job_id

    def test_mutation_response_has_message(self):
        resp = VrtMutationResponse(
            job_id=uuid.uuid4(), message="Source removed, VRT regeneration started"
        )
        assert "removed" in resp.message


# ---------------------------------------------------------------------------
# TestAddSource
# ---------------------------------------------------------------------------


class TestAddSource:
    """Unit tests for POST /ingest/vrt/{dataset_id}/sources/ endpoint."""

    def test_returns_409_when_vrt_is_regenerating(self):
        """Returns 409 Conflict when VRT status is 'regenerating'."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import add_vrt_source

            mock_request = MagicMock()
            mock_request.source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()

            # Setup DB with a regenerating VRT asset
            dataset_id = uuid.uuid4()
            mock_asset = _make_mock_asset(status="regenerating")
            mock_db = _build_mock_db_for_vrt(mock_asset)

            with pytest.raises(HTTPException) as exc_info:
                await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)

            assert exc_info.value.status_code == 409
            assert "regenerating" in str(exc_info.value.detail).lower()

        asyncio.run(_check())

    def test_returns_404_when_vrt_not_found(self):
        """Returns 404 when the VRT dataset does not exist."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import add_vrt_source

            mock_request = MagicMock()
            mock_request.source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            dataset_id = uuid.uuid4()

            # DB returns no result
            mock_db = _build_mock_db_no_vrt()

            with pytest.raises(HTTPException) as exc_info:
                await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)

            assert exc_info.value.status_code == 404

        asyncio.run(_check())

    def test_returns_422_when_source_not_found(self):
        """Returns 422 when the source dataset is not a raster_dataset."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import add_vrt_source

            mock_request = MagicMock()
            mock_request.source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            dataset_id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            # VRT found, but source not found
            mock_db = _build_mock_db_source_not_found(mock_asset)

            with pytest.raises(HTTPException) as exc_info:
                await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)

            assert exc_info.value.status_code == 422

        asyncio.run(_check())

    def test_returns_409_when_source_already_linked(self):
        """Returns 409 when source is already linked to this VRT."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import add_vrt_source

            source_id = uuid.uuid4()
            mock_request = MagicMock()
            mock_request.source_dataset_id = source_id
            mock_user = MagicMock()
            dataset_id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            mock_db = _build_mock_db_source_already_linked(mock_asset)

            with pytest.raises(HTTPException) as exc_info:
                await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)

            assert exc_info.value.status_code == 409
            assert "already" in str(exc_info.value.detail).lower()

        asyncio.run(_check())

    def test_returns_422_when_validation_fails(self):
        """Returns 422 when new source is incompatible with existing sources."""
        from fastapi import HTTPException
        from app.processing.raster.validation import SourceValidationError

        async def _check():
            from app.processing.ingest.router import add_vrt_source

            mock_request = MagicMock()
            mock_request.source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            dataset_id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            mock_db = _build_mock_db_for_validation_failure(mock_asset)

            # Simulate validate_sources returning an error
            mock_error = MagicMock(spec=SourceValidationError)
            mock_error.model_dump.return_value = {
                "code": "CRS_MISMATCH",
                "message": "CRS mismatch",
            }

            with patch(
                "app.processing.ingest.router.validate_sources",
                return_value=[mock_error],
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)

            assert exc_info.value.status_code == 422

        asyncio.run(_check())

    def test_returns_202_with_job_id_on_success(self, monkeypatch):
        """Returns 202 Accepted with job_id on valid add."""

        async def _check():
            from app.processing.ingest.router import add_vrt_source
            import app.processing.ingest.router as ingest_router

            source_id = uuid.uuid4()
            mock_request = MagicMock()
            mock_request.source_dataset_id = source_id
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()
            dataset_id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            mock_db, expected_job_id, mock_create_ingest_job = (
                _build_mock_db_success_add(mock_asset, dataset_id)
            )
            monkeypatch.setattr(
                ingest_router, "create_ingest_job", mock_create_ingest_job
            )

            with (
                patch("app.processing.ingest.router.validate_sources", return_value=[]),
                patch("app.processing.ingest.router.regenerate_vrt") as mock_task,
            ):
                mock_task.defer_async = AsyncMock()
                result = await add_vrt_source(
                    dataset_id, mock_request, mock_user, mock_db
                )

            assert result.job_id == expected_job_id
            assert result.status == "accepted"

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# TestRemoveSource
# ---------------------------------------------------------------------------


class TestRemoveSource:
    """Unit tests for DELETE /ingest/vrt/{dataset_id}/sources/{source_dataset_id}/ endpoint."""

    def test_returns_409_when_vrt_is_regenerating(self):
        """Returns 409 when VRT status is 'regenerating'."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import remove_vrt_source

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()

            mock_asset = _make_mock_asset(status="regenerating")
            mock_db = _build_mock_db_for_vrt(mock_asset)

            with pytest.raises(HTTPException) as exc_info:
                await remove_vrt_source(
                    dataset_id, source_dataset_id, mock_user, mock_db
                )

            assert exc_info.value.status_code == 409
            assert "regenerating" in str(exc_info.value.detail).lower()

        asyncio.run(_check())

    def test_returns_404_when_vrt_not_found(self):
        """Returns 404 when VRT dataset not found."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import remove_vrt_source

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()

            mock_db = _build_mock_db_no_vrt()

            with pytest.raises(HTTPException) as exc_info:
                await remove_vrt_source(
                    dataset_id, source_dataset_id, mock_user, mock_db
                )

            assert exc_info.value.status_code == 404

        asyncio.run(_check())

    def test_returns_422_when_removing_would_leave_fewer_than_2(self):
        """Returns 422 when removing would leave fewer than 2 sources."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import remove_vrt_source

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()

            mock_asset = _make_mock_asset(status="ready")
            # DB returns count of 2 (so removing one would leave 1)
            mock_db = _build_mock_db_remove_min_guard(mock_asset, source_count=2)

            with pytest.raises(HTTPException) as exc_info:
                await remove_vrt_source(
                    dataset_id, source_dataset_id, mock_user, mock_db
                )

            assert exc_info.value.status_code == 422
            assert "2" in str(exc_info.value.detail)

        asyncio.run(_check())

    def test_returns_404_when_source_link_not_found(self):
        """Returns 404 when source is not linked to VRT."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import remove_vrt_source

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()

            mock_asset = _make_mock_asset(status="ready")
            mock_db = _build_mock_db_remove_source_not_linked(
                mock_asset, source_count=3
            )

            with pytest.raises(HTTPException) as exc_info:
                await remove_vrt_source(
                    dataset_id, source_dataset_id, mock_user, mock_db
                )

            assert exc_info.value.status_code == 404
            assert "not linked" in str(exc_info.value.detail).lower()

        asyncio.run(_check())

    def test_returns_202_with_job_id_on_success(self, monkeypatch):
        """Returns 202 Accepted with job_id on valid remove."""

        async def _check():
            from app.processing.ingest.router import remove_vrt_source
            import app.processing.ingest.router as ingest_router

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            mock_db, expected_job_id, mock_create_ingest_job = (
                _build_mock_db_success_remove(mock_asset, dataset_id, source_count=3)
            )
            monkeypatch.setattr(
                ingest_router, "create_ingest_job", mock_create_ingest_job
            )

            with patch("app.processing.ingest.router.regenerate_vrt") as mock_task:
                mock_task.defer_async = AsyncMock()
                result = await remove_vrt_source(
                    dataset_id, source_dataset_id, mock_user, mock_db
                )

            assert result.job_id == expected_job_id
            assert result.status == "accepted"

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# TestMutationSerialization
# ---------------------------------------------------------------------------


class TestMutationSerialization:
    """Both add and remove return 409 when VRT is regenerating (SRC-05)."""

    def test_add_returns_409_when_regenerating(self):
        """SRC-05: add endpoint refuses mutation when already regenerating."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import add_vrt_source

            mock_request = MagicMock()
            mock_request.source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            dataset_id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="regenerating")
            mock_db = _build_mock_db_for_vrt(mock_asset)

            with pytest.raises(HTTPException) as exc_info:
                await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)
            assert exc_info.value.status_code == 409

        asyncio.run(_check())

    def test_remove_returns_409_when_regenerating(self):
        """SRC-05: remove endpoint refuses mutation when already regenerating."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import remove_vrt_source

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()

            mock_asset = _make_mock_asset(status="regenerating")
            mock_db = _build_mock_db_for_vrt(mock_asset)

            with pytest.raises(HTTPException) as exc_info:
                await remove_vrt_source(
                    dataset_id, source_dataset_id, mock_user, mock_db
                )
            assert exc_info.value.status_code == 409

        asyncio.run(_check())

    def test_add_allows_ready_status(self, monkeypatch):
        """Add endpoint proceeds when status is 'ready'."""

        async def _check():
            from app.processing.ingest.router import add_vrt_source
            import app.processing.ingest.router as ingest_router

            mock_request = MagicMock()
            mock_request.source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()
            dataset_id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            mock_db, _, mock_create_ingest_job = _build_mock_db_success_add(
                mock_asset, dataset_id
            )
            monkeypatch.setattr(
                ingest_router, "create_ingest_job", mock_create_ingest_job
            )

            with (
                patch("app.processing.ingest.router.validate_sources", return_value=[]),
                patch("app.processing.ingest.router.regenerate_vrt") as mock_task,
            ):
                mock_task.defer_async = AsyncMock()
                # Should not raise 409
                result = await add_vrt_source(
                    dataset_id, mock_request, mock_user, mock_db
                )
            assert result.status == "accepted"

        asyncio.run(_check())

    def test_409_message_includes_regenerating(self):
        """409 response body mentions that VRT is regenerating."""
        from fastapi import HTTPException

        async def _check():
            from app.processing.ingest.router import add_vrt_source

            mock_request = MagicMock()
            mock_request.source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            dataset_id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="regenerating")
            mock_db = _build_mock_db_for_vrt(mock_asset)

            with pytest.raises(HTTPException) as exc_info:
                await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)
            assert "regenerating" in str(exc_info.value.detail).lower()
            assert "try again" in str(exc_info.value.detail).lower()

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# TestRegenerateVrtTask
# ---------------------------------------------------------------------------


class TestRegenerateVrtTask:
    """Tests for the regenerate_vrt Procrastinate task."""

    def test_task_exists_and_is_importable(self):
        """regenerate_vrt task can be imported from app.processing.ingest.tasks."""
        from app.processing.ingest.tasks import regenerate_vrt

        assert regenerate_vrt is not None

    def test_task_is_on_raster_queue(self):
        """regenerate_vrt must be on the 'raster' queue."""
        from app.processing.ingest.tasks import regenerate_vrt

        # Procrastinate tasks store queue in task.queue or task.task_kwargs
        assert hasattr(regenerate_vrt, "queue") or hasattr(
            regenerate_vrt, "task_kwargs"
        )
        queue = getattr(
            regenerate_vrt, "queue", None
        ) or regenerate_vrt.task_kwargs.get("queue")
        assert queue == "raster"

    def test_task_sets_status_to_failed_on_exception(self):
        """On exception, task sets asset.status = 'failed' and job.status = 'failed'."""

        async def _check():
            from app.processing.ingest.tasks import regenerate_vrt

            job_id = str(uuid.uuid4())
            vrt_dataset_id = str(uuid.uuid4())

            mock_job = MagicMock()
            mock_job.id = uuid.UUID(job_id)
            mock_job.status = "pending"

            mock_vrt_asset = _make_mock_asset(status="regenerating")

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            call_count = [0]

            def execute_side_effect(query, params=None):
                call_count[0] += 1
                result_mock = MagicMock()
                if call_count[0] == 1:
                    result_mock.scalar_one.return_value = mock_job
                elif call_count[0] == 2:
                    result_mock.scalar_one_or_none.return_value = mock_vrt_asset
                elif call_count[0] == 3:
                    # vrt_source_links -- empty list causes ValueError
                    result_mock.fetchall.return_value = []
                return result_mock

            mock_session.execute = AsyncMock(side_effect=execute_side_effect)

            with (
                patch(
                    "app.processing.ingest.tasks_vrt.async_session"
                ) as mock_async_session,
                patch(
                    "app.processing.ingest.tasks_vrt.build_vrt",
                    side_effect=RuntimeError("gdalbuildvrt failed"),
                ),
            ):
                mock_async_session.return_value = mock_session

                try:
                    await regenerate_vrt.func(
                        job_id=job_id, vrt_dataset_id=vrt_dataset_id
                    )
                except (RuntimeError, Exception):
                    pass

            # The task should have attempted to set status to failed
            # We verify mock_vrt_asset.status was set to 'failed'
            assert mock_vrt_asset.status == "failed"

        asyncio.run(_check())

    def test_task_clears_current_generation_id_on_failure(self):
        """On failure, current_generation_id is cleared (set to None)."""

        async def _check():
            from app.processing.ingest.tasks import regenerate_vrt

            job_id = str(uuid.uuid4())
            vrt_dataset_id = str(uuid.uuid4())

            mock_job = MagicMock()
            mock_job.id = uuid.UUID(job_id)
            mock_job.status = "pending"

            mock_vrt_asset = _make_mock_asset(status="regenerating")
            mock_vrt_asset.current_generation_id = uuid.uuid4()

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)

            call_count = [0]

            def execute_side_effect(query, params=None):
                call_count[0] += 1
                result_mock = MagicMock()
                if call_count[0] == 1:
                    result_mock.scalar_one.return_value = mock_job
                elif call_count[0] == 2:
                    result_mock.scalar_one_or_none.return_value = mock_vrt_asset
                elif call_count[0] == 3:
                    # vrt_source_links -- empty causes ValueError before build
                    result_mock.fetchall.return_value = []
                return result_mock

            mock_session.execute = AsyncMock(side_effect=execute_side_effect)

            with (
                patch(
                    "app.processing.ingest.tasks_vrt.async_session"
                ) as mock_async_session,
                patch(
                    "app.processing.ingest.tasks_vrt.build_vrt",
                    side_effect=RuntimeError("fail"),
                ),
            ):
                mock_async_session.return_value = mock_session
                try:
                    await regenerate_vrt.func(
                        job_id=job_id, vrt_dataset_id=vrt_dataset_id
                    )
                except Exception:
                    pass

            assert mock_vrt_asset.current_generation_id is None

        asyncio.run(_check())

    def test_task_sets_status_to_ready_on_success(self):
        """On success, asset.status is set to 'ready' and last_regenerated_at is updated."""

        async def _check():
            from app.processing.ingest.tasks import regenerate_vrt

            job_id = str(uuid.uuid4())
            vrt_dataset_id = str(uuid.uuid4())
            mock_vrt_asset_id = uuid.uuid4()

            mock_job = MagicMock()
            mock_job.id = uuid.UUID(job_id)
            mock_job.status = "pending"

            mock_vrt_asset = _make_mock_asset(status="regenerating")
            mock_vrt_asset.dataset_id = mock_vrt_asset_id
            mock_vrt_asset.current_generation_id = uuid.uuid4()
            mock_vrt_asset.last_regenerated_at = None

            source_ids = [uuid.uuid4(), uuid.uuid4()]
            mock_rows = [
                MagicMock(source_dataset_id=source_ids[0]),
                MagicMock(source_dataset_id=source_ids[1]),
            ]

            mock_source_asset1 = _make_mock_source_asset()
            mock_source_asset1.dataset_id = source_ids[0]
            mock_source_asset2 = _make_mock_source_asset()
            mock_source_asset2.dataset_id = source_ids[1]

            mock_dataset = MagicMock()
            mock_dataset.record = MagicMock()
            mock_dataset.record.geometry = None

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            # session.add is synchronous in real SQLAlchemy; AsyncMock would
            # make it return an un-awaited coroutine and emit RuntimeWarning.
            mock_session.add = MagicMock()

            call_count = [0]

            def execute_side_effect(query, params=None):
                call_count[0] += 1
                result_mock = MagicMock()
                n = call_count[0]
                if n == 1:
                    result_mock.scalar_one.return_value = mock_job
                elif n == 2:
                    result_mock.scalar_one_or_none.return_value = mock_vrt_asset
                elif n == 3:
                    # vrt_source_links
                    result_mock.fetchall.return_value = mock_rows
                elif n == 4:
                    # source RasterAssets
                    result_mock.scalars.return_value.all.return_value = [
                        mock_source_asset1,
                        mock_source_asset2,
                    ]
                elif n == 5:
                    # dataset record for footprint
                    result_mock.scalar_one_or_none.return_value = mock_dataset
                return result_mock

            mock_session.execute = AsyncMock(side_effect=execute_side_effect)

            mock_meta = {
                "crs_wkt": 'GEOGCS["WGS 84"]',
                "epsg": 4326,
                "res_x": 0.001,
                "res_y": 0.001,
                "band_count": 1,
                "nodata": None,
                "compression": None,
                "width": 100,
                "height": 100,
                "bounds": [0.0, 0.0, 1.0, 1.0],
                "band_info": [],
            }

            with (
                patch(
                    "app.processing.ingest.tasks_vrt.async_session"
                ) as mock_async_session,
                patch(
                    "app.processing.ingest.tasks_vrt.build_vrt",
                    return_value="/tmp/x/source.vrt",
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.resolve_vrt_source_path",
                    return_value="/path/to/source.cog.tif",
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.extract_raster_metadata",
                    return_value=mock_meta,
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.sha256_file", return_value="newhash"
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.generate_quicklook",
                    return_value=b"\x89PNG",
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.invalidate_catalog_cache",
                    new_callable=AsyncMock,
                ),
                patch(
                    "builtins.open",
                    MagicMock(
                        return_value=MagicMock(
                            __enter__=MagicMock(return_value=MagicMock()),
                            __exit__=MagicMock(),
                        )
                    ),
                ),
                patch("os.path.getsize", return_value=1024),
                patch("tempfile.mkdtemp", return_value="/tmp/regen_test"),
                patch("shutil.rmtree"),
                patch("asyncio.to_thread", new=_fake_to_thread),
            ):
                mock_async_session.return_value = mock_session

                mock_storage = AsyncMock()
                mock_storage.put = AsyncMock()
                with (
                    patch(
                        "app.processing.ingest.tasks_vrt.get_storage",
                        return_value=mock_storage,
                    ),
                    patch(
                        "app.processing.ingest.tasks_vrt.defer_embedding",
                        new_callable=AsyncMock,
                    ),
                ):
                    await regenerate_vrt.func(
                        job_id=job_id, vrt_dataset_id=vrt_dataset_id
                    )

            assert mock_vrt_asset.status == "ready"
            assert mock_vrt_asset.last_regenerated_at is not None
            assert mock_vrt_asset.current_generation_id is None

        asyncio.run(_check())

    def test_task_overwrites_same_storage_key(self):
        """Task must overwrite existing asset_uri key, not create a new one."""

        # The asset_uri should remain UNCHANGED after successful regeneration.
        # Atomic swap = overwrite same key, asset_uri stays the same.
        async def _check():
            from app.processing.ingest.tasks import regenerate_vrt

            original_uri = "rasters/vrt-id/oldhash/source.vrt"
            job_id = str(uuid.uuid4())
            vrt_dataset_id = str(uuid.uuid4())
            mock_vrt_asset_id = uuid.uuid4()

            mock_job = MagicMock()
            mock_job.id = uuid.UUID(job_id)

            mock_vrt_asset = _make_mock_asset(
                status="regenerating", asset_uri=original_uri
            )
            mock_vrt_asset.dataset_id = mock_vrt_asset_id

            source_ids = [uuid.uuid4(), uuid.uuid4()]
            mock_rows = [
                MagicMock(source_dataset_id=source_ids[0]),
                MagicMock(source_dataset_id=source_ids[1]),
            ]
            mock_source_assets = [_make_mock_source_asset() for _ in source_ids]
            for i, a in enumerate(mock_source_assets):
                a.dataset_id = source_ids[i]

            mock_dataset = MagicMock()
            mock_dataset.record = MagicMock()
            mock_dataset.record.geometry = None

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            # session.add is synchronous in real SQLAlchemy; AsyncMock would
            # make it return an un-awaited coroutine and emit RuntimeWarning.
            mock_session.add = MagicMock()

            call_count = [0]

            def execute_side_effect(query, params=None):
                call_count[0] += 1
                result_mock = MagicMock()
                n = call_count[0]
                if n == 1:
                    result_mock.scalar_one.return_value = mock_job
                elif n == 2:
                    result_mock.scalar_one_or_none.return_value = mock_vrt_asset
                elif n == 3:
                    result_mock.fetchall.return_value = mock_rows
                elif n == 4:
                    result_mock.scalars.return_value.all.return_value = (
                        mock_source_assets
                    )
                elif n == 5:
                    result_mock.scalar_one_or_none.return_value = mock_dataset
                return result_mock

            mock_session.execute = AsyncMock(side_effect=execute_side_effect)

            mock_meta = {
                "crs_wkt": 'GEOGCS["WGS 84"]',
                "epsg": 4326,
                "res_x": 0.001,
                "res_y": 0.001,
                "band_count": 1,
                "nodata": None,
                "compression": None,
                "width": 100,
                "height": 100,
                "bounds": [0.0, 0.0, 1.0, 1.0],
                "band_info": [],
            }

            put_calls = []

            async def mock_put(key, data):
                put_calls.append(key)

            with (
                patch(
                    "app.processing.ingest.tasks_vrt.async_session"
                ) as mock_async_session,
                patch(
                    "app.processing.ingest.tasks_vrt.build_vrt",
                    return_value="/tmp/x/source.vrt",
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.resolve_vrt_source_path",
                    return_value="/path/to/source.cog.tif",
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.extract_raster_metadata",
                    return_value=mock_meta,
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.sha256_file", return_value="newhash"
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.generate_quicklook",
                    return_value=b"\x89PNG",
                ),
                patch(
                    "app.processing.ingest.tasks_vrt.invalidate_catalog_cache",
                    new_callable=AsyncMock,
                ),
                patch(
                    "builtins.open",
                    MagicMock(
                        return_value=MagicMock(
                            __enter__=MagicMock(return_value=MagicMock()),
                            __exit__=MagicMock(),
                        )
                    ),
                ),
                patch("os.path.getsize", return_value=1024),
                patch("tempfile.mkdtemp", return_value="/tmp/regen_test"),
                patch("shutil.rmtree"),
                patch("asyncio.to_thread", new=_fake_to_thread),
            ):
                mock_async_session.return_value = mock_session

                mock_storage = AsyncMock()
                mock_storage.put = mock_put
                with (
                    patch(
                        "app.processing.ingest.tasks_vrt.get_storage",
                        return_value=mock_storage,
                    ),
                    patch(
                        "app.processing.ingest.tasks_vrt.defer_embedding",
                        new_callable=AsyncMock,
                    ),
                ):
                    await regenerate_vrt.func(
                        job_id=job_id, vrt_dataset_id=vrt_dataset_id
                    )

            # The VRT file should be written to the ORIGINAL key
            assert original_uri in put_calls, (
                f"Expected {original_uri} in put_calls={put_calls}"
            )
            # asset_uri should not have changed
            assert mock_vrt_asset.asset_uri == original_uri

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# TestStatusField
# ---------------------------------------------------------------------------


class TestStatusField:
    """Status field exposed in GET /datasets/{id} response (SRC-06)."""

    def test_raster_metadata_has_status_field(self):
        """RasterMetadata schema must include a status field."""
        meta = RasterMetadata()
        assert hasattr(meta, "status")

    def test_raster_metadata_status_defaults_to_none(self):
        """RasterMetadata.status defaults to None."""
        meta = RasterMetadata()
        assert meta.status is None

    def test_raster_metadata_status_accepts_ready(self):
        """RasterMetadata.status can be set to 'ready'."""
        meta = RasterMetadata(status="ready")
        assert meta.status == "ready"

    def test_raster_metadata_status_accepts_regenerating(self):
        """RasterMetadata.status can be set to 'regenerating'."""
        meta = RasterMetadata(status="regenerating")
        assert meta.status == "regenerating"

    def test_raster_metadata_status_accepts_failed(self):
        """RasterMetadata.status can be set to 'failed'."""
        meta = RasterMetadata(status="failed")
        assert meta.status == "failed"

    def test_build_raster_metadata_includes_status(self):
        """_build_raster_metadata populates status from raster_asset.status."""
        from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

        mock_dataset = MagicMock()
        mock_dataset.id = uuid.uuid4()

        mock_raster_asset = MagicMock()
        mock_raster_asset.epsg = 4326
        mock_raster_asset.res_x = 0.001
        mock_raster_asset.res_y = 0.001
        mock_raster_asset.band_count = 1
        mock_raster_asset.nodata = None
        mock_raster_asset.compression = None
        mock_raster_asset.width = 100
        mock_raster_asset.height = 100
        mock_raster_asset.size_bytes = 1024
        mock_raster_asset.band_info = []
        mock_raster_asset.storage_backend = "local"
        mock_raster_asset.status = "ready"
        mock_raster_asset.vrt_type = None
        mock_raster_asset.resolution_strategy = None

        result = _build_raster_metadata(mock_dataset, mock_raster_asset)

        assert result is not None
        assert result.status == "ready"

    def test_build_raster_metadata_status_regenerating(self):
        """_build_raster_metadata maps status='regenerating' correctly."""
        from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

        mock_dataset = MagicMock()
        mock_dataset.id = uuid.uuid4()

        mock_raster_asset = MagicMock()
        mock_raster_asset.epsg = 4326
        mock_raster_asset.res_x = 0.001
        mock_raster_asset.res_y = 0.001
        mock_raster_asset.band_count = 1
        mock_raster_asset.nodata = None
        mock_raster_asset.compression = None
        mock_raster_asset.width = 100
        mock_raster_asset.height = 100
        mock_raster_asset.size_bytes = 1024
        mock_raster_asset.band_info = []
        mock_raster_asset.storage_backend = "local"
        mock_raster_asset.status = "regenerating"
        mock_raster_asset.vrt_type = None
        mock_raster_asset.resolution_strategy = None

        result = _build_raster_metadata(mock_dataset, mock_raster_asset)

        assert result is not None
        assert result.status == "regenerating"

    def test_build_raster_metadata_returns_none_for_none_asset(self):
        """_build_raster_metadata returns None when raster_asset is None."""
        from app.modules.catalog.datasets.domain.helpers import _build_raster_metadata

        assert _build_raster_metadata(MagicMock(), None) is None


# ---------------------------------------------------------------------------
# Mock DB helpers
# ---------------------------------------------------------------------------
# These build the AsyncMock db objects needed by endpoint tests.


def _build_mock_db_for_vrt(mock_asset: MagicMock) -> AsyncMock:
    """DB that finds VRT asset but it's in 'regenerating' status."""
    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = mock_asset
    mock_db.execute = AsyncMock(return_value=result_mock)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()
    return mock_db


def _build_mock_db_no_vrt() -> AsyncMock:
    """DB that returns None for VRT lookup."""
    mock_db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    mock_db.execute = AsyncMock(return_value=result_mock)
    mock_db.commit = AsyncMock()
    return mock_db


def _build_mock_db_source_not_found(mock_asset: MagicMock) -> AsyncMock:
    """DB: VRT found (ready), but source dataset not found."""
    mock_db = AsyncMock()
    call_count = [0]

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        if call_count[0] == 1:
            # VRT asset lookup
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif call_count[0] == 2:
            # Source asset lookup -- not found
            result_mock.scalar_one_or_none.return_value = None
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()
    return mock_db


def _build_mock_db_source_already_linked(mock_asset: MagicMock) -> AsyncMock:
    """DB: VRT found, source found, but already linked."""
    mock_db = AsyncMock()
    call_count = [0]

    source_asset = _make_mock_source_asset()

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            # Source asset found
            result_mock.scalar_one_or_none.return_value = source_asset
        elif n == 3:
            # Duplicate check -- row found (already linked)
            result_mock.fetchone.return_value = MagicMock()
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()
    return mock_db


def _build_mock_db_for_validation_failure(mock_asset: MagicMock) -> AsyncMock:
    """DB: VRT found, source found, not a duplicate, but validation fails."""
    mock_db = AsyncMock()
    call_count = [0]

    source_asset = _make_mock_source_asset()
    existing_source = _make_mock_source_asset()

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            result_mock.scalar_one_or_none.return_value = source_asset
        elif n == 3:
            # Duplicate check -- not found
            result_mock.fetchone.return_value = None
        elif n == 4:
            # Existing sources fetch
            result_mock.fetchall.return_value = [
                MagicMock(source_dataset_id=uuid.uuid4())
            ]
        elif n == 5:
            # Load existing source assets
            result_mock.scalars.return_value.all.return_value = [existing_source]
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()

    return mock_db


def _build_mock_db_success_add(mock_asset: MagicMock, dataset_id: uuid.UUID):
    """DB: Full success path for add_vrt_source.

    Returns (mock_db, expected_job_id, mock_create_ingest_job).
    """
    mock_db = AsyncMock()
    call_count = [0]

    source_asset = _make_mock_source_asset()
    existing_source = _make_mock_source_asset()
    job_id = uuid.uuid4()

    mock_job = MagicMock()
    mock_job.id = job_id
    mock_job.dataset_id = None

    # We patch create_ingest_job separately in the test

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            result_mock.scalar_one_or_none.return_value = source_asset
        elif n == 3:
            # Duplicate check -- not found
            result_mock.fetchone.return_value = None
        elif n == 4:
            # Existing source links
            result_mock.fetchall.return_value = [
                MagicMock(source_dataset_id=uuid.uuid4())
            ]
        elif n == 5:
            # Load existing source assets
            result_mock.scalars.return_value.all.return_value = [existing_source]
        elif n == 6:
            # Max position query
            result_mock.scalar.return_value = 0
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()

    async def mock_create_ingest_job(db, *args, **kwargs):
        return mock_job

    return mock_db, job_id, mock_create_ingest_job


def _build_mock_db_remove_min_guard(
    mock_asset: MagicMock, source_count: int
) -> AsyncMock:
    """DB: VRT found (ready), source count check returns <= 2."""
    mock_db = AsyncMock()
    call_count = [0]

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            # Source count
            result_mock.scalar.return_value = source_count
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()
    return mock_db


def _build_mock_db_remove_source_not_linked(
    mock_asset: MagicMock, source_count: int
) -> AsyncMock:
    """DB: VRT found, source count > 2, but source link not found."""
    mock_db = AsyncMock()
    call_count = [0]

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            # Source count: > 2
            result_mock.scalar.return_value = source_count
        elif n == 3:
            # Link existence check -- not found
            result_mock.fetchone.return_value = None
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()
    return mock_db


def _build_mock_db_success_remove(
    mock_asset: MagicMock, dataset_id: uuid.UUID, source_count: int
):
    """DB: Full success path for remove_vrt_source.

    Returns (mock_db, expected_job_id, mock_create_ingest_job).
    """
    mock_db = AsyncMock()
    call_count = [0]

    job_id = uuid.uuid4()
    mock_job = MagicMock()
    mock_job.id = job_id
    mock_job.dataset_id = None

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            # Source count: > 2
            result_mock.scalar.return_value = source_count
        elif n == 3:
            # Link existence check -- found
            result_mock.fetchone.return_value = MagicMock()
        # n == 4: DELETE (no return needed)
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()

    async def mock_create_ingest_job(db, *args, **kwargs):
        return mock_job

    return mock_db, job_id, mock_create_ingest_job


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


async def _fake_to_thread(func, *args, **kwargs):
    """Replace asyncio.to_thread with direct synchronous call in tests."""
    return func(*args, **kwargs)
