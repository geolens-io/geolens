"""fix(#1955): admission control for the three VRT regeneration doors.

ADR-002 Decision 5b admits one mutation per dataset through a partial unique
index the VRT path never writes to. Its three doors read the asset status,
check it and flip it as separate statements, so two of them could dispatch at
once. They now share ``admit_vrt_mutation``, which takes the per-dataset lock
BEFORE the status read.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import inspect
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.platform.catalog_locks import admit_vrt_mutation
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
