"""fix(#1955): admission control for the three VRT regeneration doors.

ADR-002 Decision 5b admits one mutation per dataset through a partial unique
index the VRT path never writes to. Its three doors read the asset status,
check it and flip it as separate statements, so two of them could dispatch at
once. They now share ``admit_vrt_mutation``, which takes the per-dataset lock
BEFORE the status read.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import importlib
import inspect
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, text

from app.platform.catalog_locks import admit_vrt_mutation
from app.platform.dataset_origin import classify_origin
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.raster.models import VrtGeneration
from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _get_admin_id,
    _link_source,
)
from tests.test_vrt_staged_mutation_1327 import _capture_defer

_DOORS = [
    ("app.modules.catalog.datasets.api.router_vrt", "regenerate_vrt_endpoint"),
    ("app.processing.ingest.router", "add_vrt_source"),
    ("app.processing.ingest.router", "remove_vrt_source"),
]


def _door_source(module_name: str, attr: str) -> str:
    return inspect.getsource(getattr(importlib.import_module(module_name), attr))


def _call_names(node: ast.AST) -> set[str]:
    return {
        getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
    }


class TestEveryDoorAdmitsThroughOneLock:
    """Pure AST — no database."""

    @pytest.mark.parametrize(("module_name", "attr"), _DOORS, ids=lambda v: v)
    def test_the_door_calls_the_shared_admission(
        self, module_name: str, attr: str
    ) -> None:
        assert "admit_vrt_mutation" in _call_names(
            ast.parse(_door_source(module_name, attr))
        ), (
            f"{attr} dispatches a regeneration without taking the per-dataset "
            "admission lock, so a concurrent door can dispatch a second one"
        )

    @pytest.mark.parametrize(("module_name", "attr"), _DOORS, ids=lambda v: v)
    def test_the_door_does_not_read_the_status_outside_the_lock(
        self, module_name: str, attr: str
    ) -> None:
        """A read before the lock leaves the loser's snapshot saying 'idle'."""
        compares = [
            node
            for node in ast.walk(ast.parse(_door_source(module_name, attr)))
            if isinstance(node, ast.Compare)
            and any(
                isinstance(operand, ast.Constant) and operand.value == "regenerating"
                for operand in node.comparators
            )
        ]
        assert not compares, (
            f"{attr} compares an asset status to 'regenerating' itself. That "
            "read is not held by the lock, which is the window two concurrent "
            "triggers land in"
        )

    @pytest.mark.parametrize(("module_name", "attr"), _DOORS, ids=lambda v: v)
    def test_the_door_reads_no_asset_status_before_admitting(
        self, module_name: str, attr: str
    ) -> None:
        """A read hoisted into a local still leaves the window open."""
        tree = ast.parse(_door_source(module_name, attr))
        admits = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "admit_vrt_mutation"
        ]
        assert len(admits) == 1, f"expected one admission; found {len(admits)}"
        early = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr == "status"
            and getattr(node.value, "id", "").endswith("asset")
            and node.lineno < admits[0]
        ]
        assert not early, (
            f"{attr} reads the asset status at {early}, before the lock at "
            f"{admits[0]}. That value is from a snapshot the winner has "
            "already invalidated"
        )

    def test_the_shared_admission_locks_before_it_reads(self) -> None:
        tree = ast.parse(inspect.getsource(admit_vrt_mutation))
        locks = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "pg_try_advisory_xact_lock" in node.value
        ]
        reads = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "attr", None) == "refresh"
        ]
        assert len(locks) == 1 and len(reads) == 1, (
            f"expected one lock and one re-read; found {len(locks)} and {len(reads)}"
        )
        assert locks[0] < reads[0], (
            "the status is re-read before the lock is taken, which is the "
            "ordering this helper exists to remove"
        )


@contextlib.asynccontextmanager
async def _admission_held(dataset_id: uuid.UUID):
    """Hold *dataset_id*'s VRT admission lock on another connection."""
    import app.core.db as db_module

    async with db_module.async_session() as holder:
        acquired = await holder.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"),
            {"key": dataset_id.int % (2**63)},
        )
        assert acquired, "the holder could not take the lock, so nothing is held"
        try:
            yield
        finally:
            await holder.rollback()


async def _generation_count(session, vrt_id: uuid.UUID) -> int:
    return len(
        (
            await session.execute(
                select(VrtGeneration).where(VrtGeneration.vrt_dataset_id == vrt_id)
            )
        )
        .scalars()
        .all()
    )


class TestAHeldAdmissionRefusesTheSecondDoor:
    async def test_regenerate_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        deferred = _capture_defer(monkeypatch)
        admin_id = await _get_admin_id(test_db_session)
        vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
        for position in range(2):
            source_id = await _create_raster_dataset(
                test_db_session, created_by=admin_id
            )
            await _link_source(test_db_session, vrt_id, source_id, position)

        async with _admission_held(vrt_id):
            resp = await client.post(
                f"/datasets/{vrt_id}/vrt/regenerate/", headers=admin_auth_header
            )

        assert resp.status_code == 409, resp.text
        assert deferred == [], "a refused trigger still queued a regeneration"
        assert await _generation_count(test_db_session, vrt_id) == 0

    async def test_add_source_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        deferred = _capture_defer(monkeypatch)
        admin_id = await _get_admin_id(test_db_session)
        vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
        for position in range(2):
            source_id = await _create_raster_dataset(
                test_db_session, created_by=admin_id
            )
            await _link_source(test_db_session, vrt_id, source_id, position)
        incoming = await _create_raster_dataset(test_db_session, created_by=admin_id)

        async with _admission_held(vrt_id):
            resp = await client.post(
                f"/ingest/vrt/{vrt_id}/sources/",
                json={"source_dataset_id": str(incoming)},
                headers=admin_auth_header,
            )

        assert resp.status_code == 409, resp.text
        assert deferred == [], "a refused add still queued a regeneration"
        assert await _generation_count(test_db_session, vrt_id) == 0

    async def test_remove_source_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        deferred = _capture_defer(monkeypatch)
        admin_id = await _get_admin_id(test_db_session)
        vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)
        linked = [
            await _create_raster_dataset(test_db_session, created_by=admin_id)
            for _ in range(3)
        ]
        for position, source_id in enumerate(linked):
            await _link_source(test_db_session, vrt_id, source_id, position)

        async with _admission_held(vrt_id):
            resp = await client.delete(
                f"/ingest/vrt/{vrt_id}/sources/{linked[1]}/", headers=admin_auth_header
            )

        assert resp.status_code == 409, resp.text
        assert deferred == [], "a refused removal still queued a regeneration"
        assert await _generation_count(test_db_session, vrt_id) == 0


async def test_an_asset_deleted_under_the_re_read_is_refused(test_db_session) -> None:
    """fix(#1955 codex r2): `refresh` reports a vanished row, and 409 beats 500."""
    import app.core.db as db_module
    from app.processing.raster.models import RasterAsset

    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)

    async with db_module.async_session() as reader:
        vrt_asset = (
            await reader.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == vrt_id)
            )
        ).scalar_one()
        async with db_module.async_session() as deleter:
            await deleter.execute(
                text("DELETE FROM catalog.raster_assets WHERE dataset_id = :id"),
                {"id": str(vrt_id)},
            )
            await deleter.commit()
        assert await admit_vrt_mutation(reader, vrt_id, vrt_asset) is False


async def _run_count(session, dataset_id: uuid.UUID) -> int:
    return len(
        (
            await session.execute(
                select(DatasetRefreshRun).where(
                    DatasetRefreshRun.dataset_id == dataset_id
                )
            )
        )
        .scalars()
        .all()
    )


class TestNoRunRowMutationCanTargetAVrt:
    """Why one advisory lock is enough, rather than a shared key with Decision 5b.

    Every ``create_pending_run`` door refuses a VRT dataset before it reaches the
    insert, so a VRT regeneration and a run-row mutation cannot interleave.
    """

    def test_a_vrt_record_type_classifies_as_no_origin(self) -> None:
        assert classify_origin("geotiff", "vrt_dataset") is None, (
            "a VRT now classifies as an origin the refresh doors accept, so "
            "one of them can open a run row on a dataset the advisory lock "
            "alone is admitting"
        )

    def test_the_reupload_door_refuses_a_vrt_before_its_run_row(self) -> None:
        from app.modules.catalog.datasets.api.router_reupload import (
            _assert_compatible_record_type,
        )

        dataset = SimpleNamespace(record=SimpleNamespace(record_type="vrt_dataset"))
        with pytest.raises(HTTPException) as refusal:
            _assert_compatible_record_type(dataset, None)
        assert refusal.value.status_code == 400

    async def test_every_run_row_door_refuses_a_vrt_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        admin_id = await _get_admin_id(test_db_session)
        vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)

        refused = {
            "refresh": await client.post(
                f"/datasets/{vrt_id}/refresh", headers=admin_auth_header
            ),
            "reupload": await client.post(
                f"/datasets/{vrt_id}/reupload",
                files={"file": ("replacement.tif", b"not-a-tif", "image/tiff")},
                headers=admin_auth_header,
            ),
        }
        for door, resp in refused.items():
            assert resp.status_code in (400, 409), f"{door} answered {resp.status_code}"
        assert await _run_count(test_db_session, vrt_id) == 0, (
            "a run-row door reached create_pending_run on a VRT dataset, so a "
            "refresh and a regeneration can now interleave and the advisory "
            "lock alone is no longer the whole admission"
        )


class TestTwoConcurrentDoorsAdmitExactlyOne:
    """Both requests in flight at once, each on its own session and connection."""

    async def _vrt_with_sources(self, session, count: int = 3):
        admin_id = await _get_admin_id(session)
        vrt_id = await _create_vrt_dataset(session, created_by=admin_id)
        linked = [
            await _create_raster_dataset(session, created_by=admin_id)
            for _ in range(count)
        ]
        for position, source_id in enumerate(linked):
            await _link_source(session, vrt_id, source_id, position)
        return admin_id, vrt_id, linked

    def _assert_exactly_one_won(self, responses, deferred, label: str) -> None:
        codes = sorted(r.status_code for r in responses)
        assert codes == [202, 409], (
            f"two concurrent {label} calls answered {codes}. Both admitted "
            "means two generations and two queued rebuilds for one dataset"
        )
        assert len(deferred) == 1, (
            f"{len(deferred)} regenerations were queued for one dataset"
        )
        loser = next(r for r in responses if r.status_code == 409)
        assert loser.json()["detail"]["code"] == "dataset_busy", loser.text

    async def test_regenerate(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        deferred = _capture_defer(monkeypatch)
        _, vrt_id, _ = await self._vrt_with_sources(test_db_session, count=2)

        responses = await asyncio.gather(
            *(
                client.post(
                    f"/datasets/{vrt_id}/vrt/regenerate/", headers=admin_auth_header
                )
                for _ in range(2)
            )
        )

        self._assert_exactly_one_won(responses, deferred, "regenerate")
        assert await _generation_count(test_db_session, vrt_id) == 1

    async def test_add_source(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        deferred = _capture_defer(monkeypatch)
        admin_id, vrt_id, _ = await self._vrt_with_sources(test_db_session, count=2)
        incoming = await _create_raster_dataset(test_db_session, created_by=admin_id)

        responses = await asyncio.gather(
            *(
                client.post(
                    f"/ingest/vrt/{vrt_id}/sources/",
                    json={"source_dataset_id": str(incoming)},
                    headers=admin_auth_header,
                )
                for _ in range(2)
            )
        )

        self._assert_exactly_one_won(responses, deferred, "add source")
        assert await _generation_count(test_db_session, vrt_id) == 1

    async def test_remove_source(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ) -> None:
        deferred = _capture_defer(monkeypatch)
        _, vrt_id, linked = await self._vrt_with_sources(test_db_session, count=3)

        responses = await asyncio.gather(
            *(
                client.delete(
                    f"/ingest/vrt/{vrt_id}/sources/{linked[1]}/",
                    headers=admin_auth_header,
                )
                for _ in range(2)
            )
        )

        self._assert_exactly_one_won(responses, deferred, "remove source")
        assert await _generation_count(test_db_session, vrt_id) == 1


async def test_a_stale_snapshot_does_not_admit_a_second_regeneration(
    test_db_session,
) -> None:
    """The ordering, isolated: both doors read `ready` before either wrote.

    Under READ COMMITTED the loser's own re-read would see the winner, so the
    read has to happen under the lock for that to be worth anything.
    """
    import app.core.db as db_module
    from app.processing.raster.models import RasterAsset

    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _create_vrt_dataset(test_db_session, created_by=admin_id)

    async with db_module.async_session() as winner, db_module.async_session() as loser:
        seen = []
        for session in (winner, loser):
            asset = (
                await session.execute(
                    select(RasterAsset).where(RasterAsset.dataset_id == vrt_id)
                )
            ).scalar_one()
            seen.append(asset)
        assert [a.status for a in seen] == ["ready", "ready"], (
            "the fixture did not produce the two identical snapshots this test is about"
        )

        assert await admit_vrt_mutation(winner, vrt_id, seen[0]) is True
        seen[0].status = "regenerating"
        await winner.commit()

        assert await admit_vrt_mutation(loser, vrt_id, seen[1]) is False, (
            "the loser was admitted on the snapshot it took before the winner "
            "wrote, which is what lets two regenerations dispatch at once"
        )
        await loser.rollback()
