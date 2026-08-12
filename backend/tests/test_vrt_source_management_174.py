"""Tests for VRT source add/remove endpoints, regenerate_vrt task, and status serialization (Phase 174-01).

Covers:
- TestAddSource: POST /ingest/vrt/{dataset_id}/sources/ endpoint behavior
- TestRemoveSource: DELETE /ingest/vrt/{dataset_id}/sources/{source_dataset_id}/ endpoint behavior
- TestMutationSerialization: 409 when VRT is regenerating (SRC-05)
- TestRegenerateVrtTask: regenerate_vrt task logic (build, swap, metadata update, error handling)
- TestStatusField: GET /datasets/{id} response includes raster.status (SRC-06)
- TestStagedMutationOverHttp: fix(#1327) — the staged member set survives the
  full request path, and vrt_source_links does not move

Pure unit tests -- no DB, no real files, no network -- except the last class,
which is database-backed on purpose: the staged set is a JSONB column written
by a real session, and a mocked db cannot show that a request wrote one column
and left a table alone.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.processing.ingest.schemas import VrtAddSourceRequest, VrtMutationResponse
from app.modules.catalog.datasets.domain.schemas import RasterMetadata


@pytest.fixture(autouse=True)
def _fence_vrt_worker_helpers(monkeypatch):
    """Keep legacy pure-unit session doubles focused on VRT mutations.

    Attempt fencing itself is covered with a real database in
    test_ingest_job_attempt_fencing.py; these tests predate the extra atomic
    UPDATE statements and intentionally model only the VRT domain queries.
    """

    # fix(#836): the claim/commit/heartbeat prologue is now the shared
    # claim_job_attempt_and_start_heartbeat helper. Model a successful claim by
    # returning a live dummy task the finally-block heartbeat teardown can
    # cancel, mirroring the old claim_ingest_job_attempt=True double.
    async def _claim_and_start_heartbeat(session, job_uuid, attempt_uuid, **kwargs):
        del session, job_uuid, attempt_uuid, kwargs
        return asyncio.create_task(asyncio.sleep(3600))

    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.claim_job_attempt_and_start_heartbeat",
        _claim_and_start_heartbeat,
    )
    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.require_ingest_job_update",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.update_ingest_job_for_attempt",
        AsyncMock(return_value=True),
    )


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


def _added_generation(mock_db: AsyncMock):
    """The single VrtGeneration the endpoint under test handed to ``db.add``.

    fix(#1327): the staged member set is the endpoint's whole output now, and
    it lives on that row — these doubles never reach a database, so the object
    passed to ``db.add`` is the only place to read it back from.
    """
    from app.processing.raster.models import VrtGeneration

    added = [
        call.args[0]
        for call in mock_db.add.call_args_list
        if isinstance(call.args[0], VrtGeneration)
    ]
    assert len(added) == 1, f"expected exactly one VrtGeneration, got {len(added)}"
    return added[0]


def _make_mock_source_asset(band_count: int = 1, epsg: int = 4326) -> MagicMock:
    asset = MagicMock()
    asset.band_count = band_count
    asset.epsg = epsg
    asset.dataset_id = uuid.uuid4()
    asset.asset_uri = f"rasters/{uuid.uuid4()}/hash/source.cog.tif"
    return asset


@pytest.fixture(autouse=True)
def _stub_vrt_source_authz():
    """``add_vrt_source`` authorizes the new source and the parent VRT, and both
    add/remove_vrt_source now require owner-or-admin on the VRT via
    ``check_dataset_write_access``. Those helpers issue their own ``db.execute``
    calls, which would shift the call-count-ordered mock ``db`` sequences these
    pure unit tests rely on. Stub them to make ZERO ``db.execute`` calls (and
    always allow) so the existing sequences stay valid and the tests reach the
    real 404/409/422 guards. The authorization behavior itself is covered by the
    DB-backed ``tests/test_vrt_source_authz_1172.py``.
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
            # fix(#1327): a rejected request stages nothing. Validation still
            # runs synchronously and still runs BEFORE the generation exists,
            # so an incompatible source leaves no intent behind for a task to
            # pick up later.
            from app.processing.raster.models import VrtGeneration

            assert not [
                call
                for call in mock_db.add.call_args_list
                if isinstance(call.args[0], VrtGeneration)
            ]
            mock_db.commit.assert_not_awaited()

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
            mock_db, expected_job_id, mock_create_ingest_job, _existing = (
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

    def test_stages_post_add_set_and_leaves_links_untouched(self, monkeypatch):
        """fix(#1327): the addition is STAGED on the generation, not applied.

        The endpoint issues no write against vrt_source_links, and the
        generation it creates carries the full post-add member set with the new
        source last — the position the MAX(position)+1 INSERT used to give it.
        """

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
            mock_db, _job_id, mock_create_ingest_job, existing_ids = (
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
                await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)

            statements = "\n".join(
                str(call.args[0]) for call in mock_db.execute.await_args_list
            )
            assert "INSERT INTO catalog.vrt_source_links" not in statements
            assert "DELETE FROM catalog.vrt_source_links" not in statements

            generation = _added_generation(mock_db)
            assert generation.staged_source_ids == [
                *[str(sid) for sid in existing_ids],
                str(source_id),
            ]
            assert generation.source_count == len(existing_ids) + 1
            assert mock_asset.status == "regenerating"

        asyncio.run(_check())

    def test_rollback_on_defer_failure_leaves_links_untouched(self, monkeypatch):
        """fix(#1327): the orphan-guard rollback no longer deletes a link row.

        There is nothing to compensate — the add was never applied — so the
        rollback restores only the asset state it flipped.
        """

        async def _check():
            from fastapi import HTTPException

            from app.processing.ingest.router import add_vrt_source
            import app.processing.ingest.router as ingest_router

            source_id = uuid.uuid4()
            mock_request = MagicMock()
            mock_request.source_dataset_id = source_id
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()
            dataset_id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            mock_asset.current_generation_id = None
            mock_db, _job_id, mock_create_ingest_job, _existing = (
                _build_mock_db_success_add(mock_asset, dataset_id)
            )
            monkeypatch.setattr(
                ingest_router, "create_ingest_job", mock_create_ingest_job
            )

            with (
                patch("app.processing.ingest.router.validate_sources", return_value=[]),
                patch(
                    "app.processing.ingest.router.defer_async_with_tenant",
                    new=AsyncMock(side_effect=RuntimeError("procrastinate down")),
                ),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await add_vrt_source(dataset_id, mock_request, mock_user, mock_db)

            assert exc_info.value.status_code == 503
            statements = "\n".join(
                str(call.args[0]) for call in mock_db.execute.await_args_list
            )
            assert "DELETE FROM catalog.vrt_source_links" not in statements
            assert "INSERT INTO catalog.vrt_source_links" not in statements
            assert mock_asset.status == "ready"
            assert mock_asset.current_generation_id is None
            generation = _added_generation(mock_db)
            assert generation.status == "failed"
            # The intent survives on the failed row; only a task that owns the
            # asset pointer could ever apply it, and this rollback gave it back.
            assert generation.staged_source_ids is not None

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
            mock_db, expected_job_id, mock_create_ingest_job, _remaining = (
                _build_mock_db_success_remove(
                    mock_asset,
                    dataset_id,
                    source_count=3,
                    source_dataset_id=source_dataset_id,
                )
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

    def test_stages_post_removal_set_and_leaves_links_untouched(self, monkeypatch):
        """fix(#1327): the removal is STAGED on the generation, not applied.

        Two properties in one place, because they are the same property: the
        endpoint issues no write against vrt_source_links, and the generation
        it creates carries the full post-removal member set in position order.
        """

        async def _check():
            from app.processing.ingest.router import remove_vrt_source
            import app.processing.ingest.router as ingest_router

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            mock_db, _job_id, mock_create_ingest_job, remaining_ids = (
                _build_mock_db_success_remove(
                    mock_asset,
                    dataset_id,
                    source_count=3,
                    source_dataset_id=source_dataset_id,
                )
            )
            monkeypatch.setattr(
                ingest_router, "create_ingest_job", mock_create_ingest_job
            )

            with patch("app.processing.ingest.router.regenerate_vrt") as mock_task:
                mock_task.defer_async = AsyncMock()
                await remove_vrt_source(
                    dataset_id, source_dataset_id, mock_user, mock_db
                )

            statements = "\n".join(
                str(call.args[0]) for call in mock_db.execute.await_args_list
            )
            assert "DELETE FROM catalog.vrt_source_links" not in statements
            assert "INSERT INTO catalog.vrt_source_links" not in statements

            generation = _added_generation(mock_db)
            assert generation.staged_source_ids == [str(sid) for sid in remaining_ids]
            assert generation.source_count == len(remaining_ids)

        asyncio.run(_check())

    def test_rollback_on_defer_failure_leaves_links_untouched(self, monkeypatch):
        """fix(#1327): the orphan-guard rollback has no link surgery left to do.

        It used to re-INSERT the row it had just deleted. Nothing was deleted,
        so the compensation is gone — and the asset state it DOES restore is
        still restored.
        """

        async def _check():
            from fastapi import HTTPException

            from app.processing.ingest.router import remove_vrt_source
            import app.processing.ingest.router as ingest_router

            dataset_id = uuid.uuid4()
            source_dataset_id = uuid.uuid4()
            mock_user = MagicMock()
            mock_user.id = uuid.uuid4()

            mock_asset = _make_mock_asset(status="ready")
            mock_asset.current_generation_id = None
            mock_db, _job_id, mock_create_ingest_job, _remaining = (
                _build_mock_db_success_remove(
                    mock_asset,
                    dataset_id,
                    source_count=3,
                    source_dataset_id=source_dataset_id,
                )
            )
            monkeypatch.setattr(
                ingest_router, "create_ingest_job", mock_create_ingest_job
            )

            with patch(
                "app.processing.ingest.router.defer_async_with_tenant",
                new=AsyncMock(side_effect=RuntimeError("procrastinate down")),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await remove_vrt_source(
                        dataset_id, source_dataset_id, mock_user, mock_db
                    )

            assert exc_info.value.status_code == 503
            statements = "\n".join(
                str(call.args[0]) for call in mock_db.execute.await_args_list
            )
            assert "vrt_source_links" not in statements.replace(
                "SELECT source_dataset_id FROM catalog.vrt_source_links", ""
            )
            assert mock_asset.status == "ready"
            assert mock_asset.current_generation_id is None
            generation = _added_generation(mock_db)
            assert generation.status == "failed"

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
            mock_db, _, mock_create_ingest_job, _existing = _build_mock_db_success_add(
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
                    # fix(#909): tasks_vrt late-binds; patch the origin
                    "app.core.db.async_session"
                ) as mock_async_session,
                patch(
                    "app.processing.ingest.tasks_vrt.build_vrt",
                    side_effect=RuntimeError("gdalbuildvrt failed"),
                ),
            ):
                mock_async_session.return_value = mock_session

                try:
                    await regenerate_vrt.func(
                        job_id=job_id,
                        attempt_id=str(uuid.uuid4()),
                        vrt_dataset_id=vrt_dataset_id,
                    )
                except (RuntimeError, Exception):
                    pass

            # Failure recovery is an atomic SQL UPDATE now; mutating the
            # phase-1 snapshot could let an expired attempt dirty newer state.
            statements = "\n".join(
                str(call.args[0]) for call in mock_session.execute.await_args_list
            )
            assert "UPDATE catalog.raster_assets" in statements

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
                    # fix(#909): tasks_vrt late-binds; patch the origin
                    "app.core.db.async_session"
                ) as mock_async_session,
                patch(
                    "app.processing.ingest.tasks_vrt.build_vrt",
                    side_effect=RuntimeError("fail"),
                ),
            ):
                mock_async_session.return_value = mock_session
                try:
                    await regenerate_vrt.func(
                        job_id=job_id,
                        attempt_id=str(uuid.uuid4()),
                        vrt_dataset_id=vrt_dataset_id,
                    )
                except Exception:
                    pass

            statements = "\n".join(
                str(call.args[0]) for call in mock_session.execute.await_args_list
            )
            assert "UPDATE catalog.raster_assets" in statements
            assert "current_generation_id" in statements

        asyncio.run(_check())

    def test_task_sets_status_to_ready_on_success(self):
        """On success, asset.status is set to 'ready' and last_regenerated_at is updated."""
        import inspect

        from app.processing.ingest import tasks_vrt

        source = inspect.getsource(tasks_vrt.regenerate_vrt.func)
        assert 'vrt_asset.status = "ready"' in source
        assert "vrt_asset.last_regenerated_at" in source
        return

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
                    # fix(#909): tasks_vrt late-binds; patch the origin
                    "app.core.db.async_session"
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
                    "app.processing.ingest.tasks_vrt.sha256_file",
                    return_value="newhash",
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
                    "app.processing.ingest.tasks_vrt.rewrite_vrt_sources",
                    return_value=[],
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
                        job_id=job_id,
                        attempt_id=str(uuid.uuid4()),
                        vrt_dataset_id=vrt_dataset_id,
                    )

            assert mock_vrt_asset.status == "ready"
            assert mock_vrt_asset.last_regenerated_at is not None
            assert mock_vrt_asset.current_generation_id is None

        asyncio.run(_check())

    def test_task_publishes_immutable_generation_key(self):
        """Task publishes an immutable key instead of overwriting live bytes."""
        import inspect

        from app.processing.ingest import tasks_vrt

        source = inspect.getsource(tasks_vrt.regenerate_vrt.func)
        assert 'f"rasters/{vrt_id}/generations/{generation_uuid}"' in source
        assert "next_vrt_storage_key" in source
        return

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
                    # fix(#909): tasks_vrt late-binds; patch the origin
                    "app.core.db.async_session"
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
                    "app.processing.ingest.tasks_vrt.sha256_file",
                    return_value="newhash",
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
                    "app.processing.ingest.tasks_vrt.rewrite_vrt_sources",
                    return_value=[],
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
                        job_id=job_id,
                        attempt_id=str(uuid.uuid4()),
                        vrt_dataset_id=vrt_dataset_id,
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
# TestStagedSourceSetReading — fix(#1327)
# ---------------------------------------------------------------------------


class TestStagedSourceSetReading:
    """What the task accepts as a staged member set, and what it refuses."""

    def test_absent_and_json_null_both_mean_no_membership_change(self):
        """The NULL fallback has to survive both shapes the column can hold.

        A column never written reads back None; one written from an explicitly
        assigned Python None holds the JSON scalar `null` and ALSO reads back
        None (measured against Postgres — the #1322 trap). Neither is a member
        set, and both must mean "build from the live links, apply nothing"
        rather than an error.
        """
        from app.processing.ingest.tasks_vrt import staged_source_ids_or_none

        assert staged_source_ids_or_none(MagicMock(staged_source_ids=None)) is None
        # A JSONB scalar that is not an array cannot be a member set either.
        assert staged_source_ids_or_none(MagicMock(staged_source_ids="null")) is None
        assert staged_source_ids_or_none(MagicMock(staged_source_ids={})) is None

    def test_returns_uuids_in_staged_order(self):
        from app.processing.ingest.tasks_vrt import staged_source_ids_or_none

        staged = [uuid.uuid4() for _ in range(3)]
        generation = MagicMock(staged_source_ids=[str(sid) for sid in staged])
        assert staged_source_ids_or_none(generation) == staged

    def test_rejects_an_empty_set(self):
        """A VRT with no members is not a publishable intent."""
        from app.processing.ingest.tasks_vrt import staged_source_ids_or_none

        with pytest.raises(ValueError, match="empty"):
            staged_source_ids_or_none(MagicMock(staged_source_ids=[]))

    def test_rejects_a_repeated_member(self):
        """Caught here, before the build, rather than as an ON CONFLICT error
        from the apply after a GDAL run has already been paid for."""
        from app.processing.ingest.tasks_vrt import staged_source_ids_or_none

        repeated = str(uuid.uuid4())
        with pytest.raises(ValueError, match="repeats"):
            staged_source_ids_or_none(
                MagicMock(staged_source_ids=[repeated, str(uuid.uuid4()), repeated])
            )


# ---------------------------------------------------------------------------
# TestStagedMutationOverHttp — fix(#1327), database-backed
# ---------------------------------------------------------------------------


async def _vrt_link_ids(session, vrt_id) -> list[uuid.UUID]:
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT source_dataset_id FROM catalog.vrt_source_links "
            "WHERE vrt_dataset_id = :id ORDER BY position ASC"
        ),
        {"id": str(vrt_id)},
    )
    return [row.source_dataset_id for row in result.fetchall()]


async def _only_generation(session, vrt_id):
    from sqlalchemy import select as sa_select

    from app.processing.raster.models import VrtGeneration

    result = await session.execute(
        sa_select(VrtGeneration).where(VrtGeneration.vrt_dataset_id == vrt_id)
    )
    return result.scalar_one()


class TestStagedMutationOverHttp:
    """The full request path: what the endpoint writes, and what it leaves."""

    async def test_add_source_stages_the_set_and_leaves_links_alone(
        self, client, admin_auth_header, test_db_session
    ):
        from tests.test_vrt_source_authz_1172 import (
            _create_raster_dataset,
            _create_vrt_dataset,
            _get_admin_id,
            _link_source,
            _patch_defer,
        )

        admin_id = await _get_admin_id(test_db_session)
        vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
        first = await _create_raster_dataset(test_db_session, created_by=admin_id)
        second = await _create_raster_dataset(test_db_session, created_by=admin_id)
        incoming = await _create_raster_dataset(test_db_session, created_by=admin_id)
        await _link_source(test_db_session, vrt_id, first, 0)
        await _link_source(test_db_session, vrt_id, second, 1)

        p_create, p_regen = _patch_defer()
        with p_create, p_regen:
            resp = await client.post(
                f"/ingest/vrt/{vrt_id}/sources/",
                json={"source_dataset_id": str(incoming)},
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        assert await _vrt_link_ids(test_db_session, vrt_id) == [first, second]
        generation = await _only_generation(test_db_session, vrt_id)
        assert generation.staged_source_ids == [
            str(first),
            str(second),
            str(incoming),
        ]
        assert generation.status == "pending"

    async def test_remove_source_stages_the_set_and_leaves_links_alone(
        self, client, admin_auth_header, test_db_session
    ):
        from tests.test_vrt_source_authz_1172 import (
            _create_raster_dataset,
            _create_vrt_dataset,
            _get_admin_id,
            _link_source,
            _patch_defer,
        )

        admin_id = await _get_admin_id(test_db_session)
        vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
        linked = [
            await _create_raster_dataset(test_db_session, created_by=admin_id)
            for _ in range(3)
        ]
        for position, source_id in enumerate(linked):
            await _link_source(test_db_session, vrt_id, source_id, position)

        p_create, p_regen = _patch_defer()
        with p_create, p_regen:
            resp = await client.delete(
                f"/ingest/vrt/{vrt_id}/sources/{linked[1]}/",
                headers=admin_auth_header,
            )

        assert resp.status_code == 202, resp.text
        assert await _vrt_link_ids(test_db_session, vrt_id) == linked
        generation = await _only_generation(test_db_session, vrt_id)
        assert generation.staged_source_ids == [str(linked[0]), str(linked[2])]

    async def test_remove_source_404s_without_staging_anything(
        self, client, admin_auth_header, test_db_session
    ):
        """A rejected request leaves no intent behind — the 404 path included."""
        from sqlalchemy import func, select as sa_select

        from app.processing.raster.models import VrtGeneration
        from tests.test_vrt_source_authz_1172 import (
            _create_raster_dataset,
            _create_vrt_dataset,
            _get_admin_id,
            _link_source,
            _patch_defer,
        )

        admin_id = await _get_admin_id(test_db_session)
        vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
        linked = [
            await _create_raster_dataset(test_db_session, created_by=admin_id)
            for _ in range(3)
        ]
        for position, source_id in enumerate(linked):
            await _link_source(test_db_session, vrt_id, source_id, position)
        stranger = await _create_raster_dataset(test_db_session, created_by=admin_id)

        p_create, p_regen = _patch_defer()
        with p_create, p_regen:
            resp = await client.delete(
                f"/ingest/vrt/{vrt_id}/sources/{stranger}/",
                headers=admin_auth_header,
            )

        assert resp.status_code == 404, resp.text
        assert await _vrt_link_ids(test_db_session, vrt_id) == linked
        generations = await test_db_session.execute(
            sa_select(func.count())
            .select_from(VrtGeneration)
            .where(VrtGeneration.vrt_dataset_id == vrt_id)
        )
        assert generations.scalar() == 0


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


def _build_mock_db_success_add(
    mock_asset: MagicMock, dataset_id: uuid.UUID, existing_count: int = 2
):
    """DB: Full success path for add_vrt_source.

    Returns (mock_db, expected_job_id, mock_create_ingest_job, existing_ids) —
    ``existing_ids`` in position order, so a caller can assert the staged set
    is exactly those plus the new source (fix(#1327)).
    """
    mock_db = AsyncMock()
    call_count = [0]

    source_asset = _make_mock_source_asset()
    existing_assets = [_make_mock_source_asset() for _ in range(existing_count)]
    existing_ids = [asset.dataset_id for asset in existing_assets]
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
            # Existing source links, in position order
            result_mock.fetchall.return_value = [
                MagicMock(source_dataset_id=source_id) for source_id in existing_ids
            ]
        elif n == 5:
            # Load existing source assets
            result_mock.scalars.return_value.all.return_value = existing_assets
        # fix(#1327): there is no 6th query. The MAX(position) lookup and the
        # link INSERT that followed it are gone — order in the staged set is
        # the position.
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()

    async def mock_create_ingest_job(db, *args, **kwargs):
        return mock_job

    return mock_db, job_id, mock_create_ingest_job, existing_ids


def _link_rows(source_ids: list[uuid.UUID]) -> list[MagicMock]:
    """Rows as the ordered vrt_source_links SELECT returns them.

    fix(#1327): remove_vrt_source reads the member set ONCE, in position order,
    and answers the count guard, the "is it linked" guard and the staged
    post-removal set from that single read — so these doubles supply link rows
    where they used to supply a COUNT(*) scalar and a separate position row.
    """
    return [MagicMock(source_dataset_id=sid) for sid in source_ids]


def _build_mock_db_remove_min_guard(
    mock_asset: MagicMock, source_count: int
) -> AsyncMock:
    """DB: VRT found (ready), member set has <= 2 sources."""
    mock_db = AsyncMock()
    call_count = [0]
    rows = _link_rows([uuid.uuid4() for _ in range(source_count)])

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            result_mock.fetchall.return_value = rows
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()
    return mock_db


def _build_mock_db_remove_source_not_linked(
    mock_asset: MagicMock, source_count: int
) -> AsyncMock:
    """DB: VRT found with > 2 sources, none of them the requested one."""
    mock_db = AsyncMock()
    call_count = [0]
    rows = _link_rows([uuid.uuid4() for _ in range(source_count)])

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            result_mock.fetchall.return_value = rows
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()
    return mock_db


def _build_mock_db_success_remove(
    mock_asset: MagicMock,
    dataset_id: uuid.UUID,
    source_count: int,
    source_dataset_id: uuid.UUID,
):
    """DB: Full success path for remove_vrt_source.

    ``source_dataset_id`` is the member being removed and IS present in the
    link rows the ordered read returns — otherwise the endpoint 404s.

    Returns (mock_db, expected_job_id, mock_create_ingest_job, remaining_ids).
    """
    mock_db = AsyncMock()
    call_count = [0]

    job_id = uuid.uuid4()
    mock_job = MagicMock()
    mock_job.id = job_id
    mock_job.dataset_id = None

    remaining_ids = [uuid.uuid4() for _ in range(source_count - 1)]
    # Removed member sits in the middle so the staged set proves order is kept.
    linked_ids = [remaining_ids[0], source_dataset_id, *remaining_ids[1:]]
    rows = _link_rows(linked_ids)

    def execute_side_effect(query, params=None):
        call_count[0] += 1
        result_mock = MagicMock()
        n = call_count[0]
        if n == 1:
            result_mock.scalar_one_or_none.return_value = mock_asset
        elif n == 2:
            result_mock.fetchall.return_value = rows
        return result_mock

    mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    mock_db.commit = AsyncMock()

    async def mock_create_ingest_job(db, *args, **kwargs):
        return mock_job

    return mock_db, job_id, mock_create_ingest_job, remaining_ids


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


async def _fake_to_thread(func, *args, **kwargs):
    """Replace asyncio.to_thread with direct synchronous call in tests."""
    return func(*args, **kwargs)
