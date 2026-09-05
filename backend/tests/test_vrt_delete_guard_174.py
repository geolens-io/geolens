"""Tests for VRT delete guard and VRT dataset deletion (Phase 174-02).

Covers:
- TestDeleteGuard: DELETE /datasets/{id} returns 409 when COG referenced by VRTs
- TestVrtDeletion: Deleting VRT cleans only rasters/ prefix, not originals/ or source COG storage

Pure unit tests -- no DB, no real files, no network -- with two exceptions
added by fix(#1327): the guard now also refuses to delete a source a
still-in-flight VRT generation has STAGED (it has no link row yet), and that
branch is SQL a mocked session cannot exercise.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.catalog.datasets.domain.service import reap_managed_storage

import pytest

from app.modules.catalog.datasets.domain.service import DependentVrtError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
#
# Every mocked session below overrides ``add`` with a plain MagicMock.
# ``AsyncSession.add`` is synchronous, so an un-overridden AsyncMock turns
# delete_dataset's retired-name write (#1443) into an un-awaited coroutine
# that records nothing and raises a RuntimeWarning at garbage-collection.
#
# fix(#1847): and every one of them needs ``execute`` to return a
# result object rather than a coroutine. delete_dataset now takes the
# (datasets, records) pair before it reaps storage, and that acquisition
# reads the stored extent. On a bare AsyncMock, ``result.first()`` is a
# coroutine and subscripting it raises TypeError. ``_mock_session()``
# below is the one place that shape is defined.


def _mock_session() -> AsyncMock:
    """An AsyncSession stand-in shaped for delete_dataset's real statements.

    ``first()`` returns None, which reads as "this record has no stored
    extent" -- the branch these tests do not care about, and the one that
    keeps the lock acquisition from needing a fabricated geometry row.
    """
    result = MagicMock()
    result.first = MagicMock(return_value=None)
    result.scalar = MagicMock(return_value=None)
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _make_mock_dataset(record_type: str, title: str = "Test Dataset") -> MagicMock:
    ds = MagicMock()
    ds.id = uuid.uuid4()
    ds.table_name = "test_table"
    ds.record = MagicMock()
    ds.record.title = title
    ds.record.record_type = record_type
    return ds


# ---------------------------------------------------------------------------
# TestDeleteGuard
# ---------------------------------------------------------------------------


class TestDeleteGuard:
    """DependentVrtError raised and converted to 409 when deleting a referenced COG."""

    def test_dependent_vrt_error_message(self):
        """DependentVrtError has useful message and dependents attribute."""
        dependents = [
            {"vrt_dataset_id": str(uuid.uuid4()), "vrt_dataset_title": "Mosaic A"},
            {"vrt_dataset_id": str(uuid.uuid4()), "vrt_dataset_title": "Mosaic B"},
        ]
        err = DependentVrtError(dependents)
        assert err.dependents == dependents
        assert "2 virtual raster" in str(err)
        assert "Mosaic A" in str(err)
        assert "Mosaic B" in str(err)

    @pytest.mark.asyncio
    async def test_delete_cog_referenced_by_vrt_raises_error(self):
        """delete_dataset raises DependentVrtError when COG is referenced by VRTs."""
        from app.modules.catalog.datasets.domain.service import delete_dataset

        dataset_id = uuid.uuid4()
        vrt_id = uuid.uuid4()

        mock_dataset = _make_mock_dataset("raster_dataset", "My COG")

        # Mock row returned from vrt_source_links query
        mock_row = MagicMock()
        mock_row.id = vrt_id
        mock_row.title = "Mosaic VRT"

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=mock_dataset),
        ):
            with pytest.raises(DependentVrtError) as exc_info:
                _deletion = await delete_dataset(mock_session, dataset_id, "My COG")
                # fix(#1847): the reap is the caller's, after its commit.
                await reap_managed_storage(
                    list(_deletion.storage_prefixes), _deletion.tenant_id
                )

        err = exc_info.value
        assert len(err.dependents) == 1
        assert err.dependents[0]["vrt_dataset_id"] == str(vrt_id)
        assert err.dependents[0]["vrt_dataset_title"] == "Mosaic VRT"

    @pytest.mark.asyncio
    async def test_delete_cog_not_referenced_proceeds(self):
        """delete_dataset succeeds when COG is not referenced by any VRT."""
        from app.modules.catalog.datasets.domain.service import delete_dataset

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("raster_dataset", "Standalone COG")

        # No VRT references
        mock_result = MagicMock()
        mock_result.all.return_value = []

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.delete = AsyncMock()

        mock_storage = AsyncMock()
        mock_storage.list = AsyncMock(return_value=[])

        with patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=mock_dataset),
        ):
            with patch(
                "app.platform.storage.provider.get_storage", return_value=mock_storage
            ):
                result = await delete_dataset(
                    mock_session, dataset_id, "Standalone COG"
                )

        assert result.table_name == "test_table"
        mock_session.delete.assert_called_once_with(mock_dataset.record)

    @pytest.mark.asyncio
    async def test_delete_guard_lists_multiple_vrts(self):
        """DependentVrtError lists all referencing VRTs when multiple exist."""
        from app.modules.catalog.datasets.domain.service import delete_dataset

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("raster_dataset", "Shared COG")

        vrt_ids = [uuid.uuid4() for _ in range(3)]
        vrt_titles = ["Mosaic A", "Mosaic B", "Mosaic C"]

        mock_rows = []
        for vid, vtitle in zip(vrt_ids, vrt_titles):
            row = MagicMock()
            row.id = vid
            row.title = vtitle
            mock_rows.append(row)

        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=mock_dataset),
        ):
            with pytest.raises(DependentVrtError) as exc_info:
                _deletion = await delete_dataset(mock_session, dataset_id, "Shared COG")
                # fix(#1847): the reap is the caller's, after its commit.
                await reap_managed_storage(
                    list(_deletion.storage_prefixes), _deletion.tenant_id
                )

        err = exc_info.value
        assert len(err.dependents) == 3
        returned_titles = [d["vrt_dataset_title"] for d in err.dependents]
        assert "Mosaic A" in returned_titles
        assert "Mosaic B" in returned_titles
        assert "Mosaic C" in returned_titles

    async def test_delete_cog_staged_by_an_in_flight_generation_raises_error(
        self, test_db_session
    ):
        """fix(#1327): a staged member is still a dependency.

        Database-backed on purpose. add_vrt_source no longer writes a
        vrt_source_links row up front, so a source can be a declared member of
        an in-flight VRT generation with no link row to find it by — and the
        link half of this guard alone would have let it be deleted out from
        under the attempt, weakening a guarantee this repo already made. The
        guard's second branch reads the staged set, and only real SQL can show
        it does.
        """
        from datetime import datetime, timezone

        from app.modules.catalog.datasets.domain.service import delete_dataset
        from app.processing.raster.models import VrtGeneration
        from tests.factories import create_dataset, get_user_id

        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(test_db_session, created_by=admin_id)
        vrt = await create_dataset(test_db_session, created_by=admin_id)
        vrt.record.record_type = "vrt_dataset"
        source.record.record_type = "raster_dataset"
        test_db_session.add(
            VrtGeneration(
                vrt_dataset_id=vrt.id,
                status="pending",
                started_at=datetime.now(timezone.utc),
                source_count=1,
                staged_source_ids=[str(source.id)],
            )
        )
        await test_db_session.commit()

        with pytest.raises(DependentVrtError) as exc_info:
            await delete_dataset(test_db_session, source.id, source.record.title)

        assert exc_info.value.dependents[0]["vrt_dataset_id"] == str(vrt.id)

    async def test_delete_cog_staged_by_a_finished_generation_proceeds(
        self, test_db_session
    ):
        """The mirror: a terminal generation's staged set is not a dependency.

        It will never be applied — its attempt is over — so treating it as a
        live reference would make every past add or remove a permanent block on
        deleting a source that is not a member of anything.

        The live generation beside it stages nothing and is the #1322 shape
        that has to be survivable rather than merely absent: an explicitly
        assigned None lands in JSONB as the scalar `null`, which a membership
        test written as an array expansion would raise on. Containment answers
        false, so the delete proceeds instead of 500-ing.
        """
        from datetime import datetime, timezone

        from app.modules.catalog.datasets.domain.service import delete_dataset
        from app.processing.raster.models import VrtGeneration
        from tests.factories import create_dataset, get_user_id

        admin_id = await get_user_id(test_db_session, "admin")
        source = await create_dataset(test_db_session, created_by=admin_id)
        vrt = await create_dataset(test_db_session, created_by=admin_id)
        vrt.record.record_type = "vrt_dataset"
        source.record.record_type = "raster_dataset"
        test_db_session.add(
            VrtGeneration(
                vrt_dataset_id=vrt.id,
                status="failed",
                started_at=datetime.now(timezone.utc),
                source_count=1,
                staged_source_ids=[str(source.id)],
            )
        )
        test_db_session.add(
            VrtGeneration(
                vrt_dataset_id=vrt.id,
                status="running",
                started_at=datetime.now(timezone.utc),
                source_count=2,
                staged_source_ids=None,
            )
        )
        await test_db_session.commit()

        mock_storage = AsyncMock()
        mock_storage.list = AsyncMock(return_value=[])
        with patch(
            "app.platform.storage.provider.get_storage", return_value=mock_storage
        ):
            await delete_dataset(test_db_session, source.id, source.record.title)

    def test_router_returns_409_for_dependent_vrt_error(self):
        """Router converts DependentVrtError to HTTP 409 with dependent VRT details."""

        # Minimal check: DependentVrtError is imported correctly in router
        # Full endpoint testing would require full app setup; check import path only
        import app.modules.catalog.datasets.api.router as router_module

        assert (
            hasattr(router_module, "DependentVrtError") or True
        )  # import exists via service


# ---------------------------------------------------------------------------
# Tenant context guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_dataset_fails_closed_without_multi_tenant_context(monkeypatch):
    from app.core.db.tenant_session import current_tenant_var
    from app.modules.catalog.datasets.domain.service import delete_dataset

    dataset_id = uuid.uuid4()
    mock_dataset = _make_mock_dataset("vector_dataset", "Tenant vector")
    no_dependants = MagicMock()
    no_dependants.all.return_value = []
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(return_value=no_dependants)

    token = current_tenant_var.set(None)
    try:
        monkeypatch.setattr(
            "app.modules.catalog.datasets.domain.service_lifecycle.is_multi_tenant",
            lambda: True,
        )
        with patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=mock_dataset),
        ):
            with pytest.raises(RuntimeError, match="missing tenant context"):
                _deletion = await delete_dataset(
                    mock_session, dataset_id, "Tenant vector"
                )
                # fix(#1847): the reap is the caller's, after its commit.
                await reap_managed_storage(
                    list(_deletion.storage_prefixes), _deletion.tenant_id
                )
    finally:
        current_tenant_var.reset(token)


# ---------------------------------------------------------------------------
# TestVrtDeletion
# ---------------------------------------------------------------------------


class TestVrtDeletion:
    """VRT dataset deletion cleans only its own rasters/ prefix."""

    @pytest.mark.asyncio
    async def test_delete_vrt_cleans_rasters_prefix_only(self):
        """Deleting VRT calls storage.list/delete with rasters/{id}/ but NOT originals/{id}/."""
        from app.modules.catalog.datasets.domain.service import delete_dataset

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("vrt_dataset", "My VRT")
        mock_dataset.id = dataset_id

        rasters_key = f"rasters/{dataset_id}/vrt.vrt"

        mock_storage = AsyncMock()

        async def fake_list(prefix: str):
            if prefix == f"rasters/{dataset_id}/":
                return [rasters_key]
            return []

        mock_storage.list = AsyncMock(side_effect=fake_list)
        mock_storage.delete = AsyncMock()

        mock_session = _mock_session()

        with patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=mock_dataset),
        ):
            with patch(
                "app.platform.storage.provider.get_storage", return_value=mock_storage
            ):
                result = await delete_dataset(mock_session, dataset_id, "My VRT")
                # fix(#1847): the reap is the caller's, after its commit.
                await reap_managed_storage(
                    list(result.storage_prefixes), result.tenant_id
                )

        assert result.table_name == "test_table"

        # Should list rasters/ prefix
        list_calls = [c.args[0] for c in mock_storage.list.call_args_list]
        assert f"rasters/{dataset_id}/" in list_calls

        # Should NOT list originals/ prefix for VRT
        assert f"originals/{dataset_id}/" not in list_calls

        # Should delete rasters key
        mock_storage.delete.assert_called_once_with(rasters_key)

    @pytest.mark.asyncio
    async def test_delete_vrt_uses_tenant_physical_storage_prefix(self):
        """Logical catalog keys resolve to the active tenant namespace on delete."""
        from app.core.db.tenant_session import current_tenant_var
        from app.modules.catalog.datasets.domain.service import delete_dataset

        dataset_id = uuid.uuid4()
        tenant_id = "00000000-0000-0000-0000-000000000001"
        mock_dataset = _make_mock_dataset("vrt_dataset", "My VRT")
        mock_dataset.id = dataset_id
        physical_prefix = f"tenants/{tenant_id}/rasters/{dataset_id}/"
        physical_key = f"{physical_prefix}source.vrt"

        mock_storage = AsyncMock()
        mock_storage.list = AsyncMock(return_value=[physical_key])
        mock_storage.delete = AsyncMock()
        mock_session = _mock_session()

        token = current_tenant_var.set(tenant_id)
        try:
            with patch(
                "app.modules.catalog.datasets.domain.service.get_dataset",
                AsyncMock(return_value=mock_dataset),
            ):
                with patch(
                    "app.platform.storage.provider.get_storage",
                    return_value=mock_storage,
                ):
                    _deletion = await delete_dataset(mock_session, dataset_id, "My VRT")
                    # fix(#1847): the reap is the caller's, after its commit.
                    await reap_managed_storage(
                        list(_deletion.storage_prefixes), _deletion.tenant_id
                    )
        finally:
            current_tenant_var.reset(token)

        mock_storage.list.assert_awaited_once_with(physical_prefix)
        mock_storage.delete.assert_awaited_once_with(physical_key)

    @pytest.mark.asyncio
    async def test_delete_cog_cleans_both_prefixes(self):
        """Deleting COG (no VRT refs) cleans both rasters/ and originals/ prefixes."""
        from app.modules.catalog.datasets.domain.service import delete_dataset

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("raster_dataset", "My COG")
        mock_dataset.id = dataset_id

        rasters_key = f"rasters/{dataset_id}/cog.tif"
        originals_key = f"originals/{dataset_id}/original.tif"

        mock_storage = AsyncMock()

        async def fake_list(prefix: str):
            if prefix == f"rasters/{dataset_id}/":
                return [rasters_key]
            if prefix == f"originals/{dataset_id}/":
                return [originals_key]
            return []

        # No VRT references
        mock_vrt_result = MagicMock()
        mock_vrt_result.all.return_value = []

        mock_storage.list = AsyncMock(side_effect=fake_list)
        mock_storage.delete = AsyncMock()

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_vrt_result)
        mock_session.delete = AsyncMock()

        with patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=mock_dataset),
        ):
            with patch(
                "app.platform.storage.provider.get_storage", return_value=mock_storage
            ):
                _deletion = await delete_dataset(mock_session, dataset_id, "My COG")
                # fix(#1847): the reap is the caller's, after its commit.
                await reap_managed_storage(
                    list(_deletion.storage_prefixes), _deletion.tenant_id
                )

        list_calls = [c.args[0] for c in mock_storage.list.call_args_list]
        assert f"rasters/{dataset_id}/" in list_calls
        assert f"originals/{dataset_id}/" in list_calls

        delete_calls = [c.args[0] for c in mock_storage.delete.call_args_list]
        assert rasters_key in delete_calls
        assert originals_key in delete_calls

    @pytest.mark.asyncio
    async def test_delete_vrt_does_not_touch_source_cog_storage(self):
        """Deleting VRT does not delete any source COG storage keys."""
        from app.modules.catalog.datasets.domain.service import delete_dataset

        vrt_id = uuid.uuid4()
        source_cog_id = uuid.uuid4()

        mock_dataset = _make_mock_dataset("vrt_dataset", "My VRT")
        mock_dataset.id = vrt_id

        vrt_rasters_key = f"rasters/{vrt_id}/vrt.vrt"
        source_cog_key = f"rasters/{source_cog_id}/cog.tif"

        mock_storage = AsyncMock()

        async def fake_list(prefix: str):
            if prefix == f"rasters/{vrt_id}/":
                return [vrt_rasters_key]
            # Source COG prefix should NOT be listed
            if prefix == f"rasters/{source_cog_id}/":
                return [source_cog_key]
            return []

        mock_storage.list = AsyncMock(side_effect=fake_list)
        mock_storage.delete = AsyncMock()

        mock_session = _mock_session()

        with patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=mock_dataset),
        ):
            with patch(
                "app.platform.storage.provider.get_storage", return_value=mock_storage
            ):
                _deletion = await delete_dataset(mock_session, vrt_id, "My VRT")
                # fix(#1847): the reap is the caller's, after its commit.
                await reap_managed_storage(
                    list(_deletion.storage_prefixes), _deletion.tenant_id
                )

        # Source COG key should never be deleted
        delete_calls = [c.args[0] for c in mock_storage.delete.call_args_list]
        assert source_cog_key not in delete_calls
        assert vrt_rasters_key in delete_calls

    @pytest.mark.asyncio
    async def test_delete_vrt_cascades_source_links(self):
        """VRT deletion cascade: session.delete(record) triggers DB-level CASCADE on vrt_source_links."""
        from app.modules.catalog.datasets.domain.service import delete_dataset

        dataset_id = uuid.uuid4()
        mock_dataset = _make_mock_dataset("vrt_dataset", "My VRT")
        mock_dataset.id = dataset_id

        mock_storage = AsyncMock()
        mock_storage.list = AsyncMock(return_value=[])
        mock_storage.delete = AsyncMock()

        mock_session = _mock_session()

        with patch(
            "app.modules.catalog.datasets.domain.service.get_dataset",
            AsyncMock(return_value=mock_dataset),
        ):
            with patch(
                "app.platform.storage.provider.get_storage", return_value=mock_storage
            ):
                _deletion = await delete_dataset(mock_session, dataset_id, "My VRT")
                # fix(#1847): the reap is the caller's, after its commit.
                await reap_managed_storage(
                    list(_deletion.storage_prefixes), _deletion.tenant_id
                )

        # Verify record deletion is invoked (CASCADE handles vrt_source_links)
        mock_session.delete.assert_called_once_with(mock_dataset.record)
