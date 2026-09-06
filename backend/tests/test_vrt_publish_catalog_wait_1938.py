"""The VRT publish's catalog acquisition carries its own budget (#1938).

Its ``catalog.records`` half is a real wait: the asset SELECT's join covers
``catalog.datasets`` alone. The DB tests need the Docker test database.
"""

import ast
import asyncio
import uuid
from pathlib import Path

import pytest
import structlog
from asyncpg.exceptions import DeadlockDetectedError, LockNotAvailableError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import sqlstate
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.catalog_locks import CatalogLockConflict, lock_catalog_rows
from app.processing.ingest import tasks_vrt
from app.processing.raster.models import RasterAsset

from tests.test_swap_lock_timeout_scope_1917 import make_swap_target

pytestmark = pytest.mark.anyio

# Short enough that a held row outlasts it in under a second.
_TEST_BUDGET = "400ms"
_TEST_BUDGET_MS = 400


def _publish_lock_call() -> ast.Call:
    """The ``lock_catalog_rows`` call the VRT publish transaction makes."""
    source = Path(tasks_vrt.__file__).read_text()
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "lock_catalog_rows"
    ]
    assert len(calls) == 1, f"expected one acquisition; found {len(calls)}"
    return calls[0]


# Modules an argument may read through; anything else is a live instance.
_SAFE_ROOTS = frozenset({"time"})


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def _failure_log_call() -> ast.Call:
    source = Path(tasks_vrt.__file__).read_text()
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_log_publish_wait_failure"
    ]
    assert len(calls) == 1, f"expected one failure report; found {len(calls)}"
    return calls[0]


async def _as_postgres_renders(value: str) -> str:
    """What ``current_setting('lock_timeout')`` reports back for *value*."""
    import app.core.db as db_module

    async with db_module.async_session() as probe:
        rendered = await probe.scalar(
            text("SELECT set_config('lock_timeout', :value, true)"), {"value": value}
        )
        await probe.rollback()
    return rendered


@pytest.fixture
async def vrt_target(client, test_db_session):
    """A committed dataset/record pair with the raster asset the publish joins."""
    async for stub, _staging in make_swap_target(client, test_db_session):
        test_db_session.add(
            RasterAsset(
                dataset_id=stub.id,
                asset_uri=f"rasters/{uuid.uuid4().hex}/source.vrt",
                storage_backend="local",
            )
        )
        await test_db_session.commit()
        yield stub


class TestPublishCallSite:
    """Pure AST and pure mapping — no DB."""

    def test_the_acquisition_names_the_publish_budget(self) -> None:
        passed = {
            kw.arg: kw.value for kw in _publish_lock_call().keywords if kw.arg
        }.get("lock_timeout")
        assert (
            isinstance(passed, ast.Name) and passed.id == "_PUBLISH_CATALOG_TIMEOUT"
        ), (
            "the publish acquires catalog.records with "
            f"{ast.dump(passed) if passed else None}. That row is not in the "
            "asset SELECT's join, so nothing else bounds the wait for it."
        )

    def test_the_failure_report_reads_no_orm_attribute(self) -> None:
        offenders = [
            f"{kw.arg}={_root_name(sub)}.{sub.attr}"
            for kw in _failure_log_call().keywords
            if kw.arg
            for sub in ast.walk(kw.value)
            if isinstance(sub, ast.Attribute) and _root_name(sub) not in _SAFE_ROOTS
        ]
        assert not offenders, (
            f"{offenders} are read off a loaded instance after the acquisition "
            "failed. lock_catalog_rows rolls back before it raises, which "
            "expires every instance, so the read raises MissingGreenlet and "
            "replaces the conflict with a greenlet error."
        )

    @pytest.mark.parametrize(
        ("cause", "log_event", "code", "needle"),
        [
            (
                DBAPIError("stmt", {}, LockNotAvailableError("expired")),
                "vrt_publish_catalog_lock_timeout",
                "55P03",
                "pg_stat_activity",
            ),
            (
                DBAPIError("stmt", {}, DeadlockDetectedError("cycle")),
                "vrt_publish_catalog_deadlock",
                "40P01",
                "deadlock victim",
            ),
            (None, "vrt_publish_catalog_lock_failed", None, "no SQLSTATE"),
        ],
        ids=["expiry", "deadlock", "no_sqlstate"],
    )
    def test_the_cause_picks_the_event(self, cause, log_event, code, needle) -> None:
        conflict = CatalogLockConflict("held")
        conflict.__cause__ = cause
        with structlog.testing.capture_logs() as captured:
            tasks_vrt._log_publish_wait_failure(
                conflict, job_id="job-1", dataset_id="ds-1", waited_ms=7
            )
        assert [r["event"] for r in captured] == [log_event]
        assert captured[0]["log_level"] == "warning"
        assert captured[0]["sqlstate"] == code
        assert needle in captured[0]["hint"]
        assert captured[0]["budget"] == tasks_vrt._PUBLISH_CATALOG_TIMEOUT
        assert captured[0]["waited_ms"] == 7


class TestPublishWaitAgainstPostgres:
    async def test_the_asset_select_covers_the_datasets_row_alone(
        self, vrt_target
    ) -> None:
        """The join takes catalog.datasets incidentally and never catalog.records."""
        import app.core.db as db_module

        async with (
            db_module.async_session() as publisher,
            db_module.async_session() as probe,
        ):
            await publisher.execute(
                select(RasterAsset)
                .join(Dataset, RasterAsset.dataset_id == Dataset.id)
                .where(Dataset.id == vrt_target.id)
                .with_for_update()
            )
            await probe.execute(text("SET LOCAL lock_timeout = '250ms'"))
            with pytest.raises(DBAPIError):
                await probe.execute(
                    select(Dataset.id)
                    .where(Dataset.id == vrt_target.id)
                    .with_for_update()
                )
            await probe.rollback()

            await probe.execute(text("SET LOCAL lock_timeout = '250ms'"))
            free = await probe.scalar(
                select(Record.id)
                .where(Record.id == vrt_target.record_id)
                .with_for_update()
            )
            assert free == vrt_target.record_id, (
                "the asset SELECT takes catalog.records too, so the publish's "
                "second acquisition needs no budget of its own"
            )
            await probe.rollback()
            await publisher.rollback()

    async def test_the_publish_budget_is_in_force_at_the_acquisition(
        self, vrt_target
    ) -> None:
        expected = await _as_postgres_renders(tasks_vrt._PUBLISH_CATALOG_TIMEOUT)
        import app.core.db as db_module

        async with db_module.async_session() as session:
            await lock_catalog_rows(
                session,
                dataset_cls=Dataset,
                record_cls=Record,
                dataset_id=vrt_target.id,
                record_id=vrt_target.record_id,
                lock_timeout=tasks_vrt._PUBLISH_CATALOG_TIMEOUT,
            )
            in_force = await session.scalar(
                text("SELECT current_setting('lock_timeout')")
            )
            await session.rollback()

        assert in_force == expected, (
            f"the acquisition ran on lock_timeout {in_force!r}, not the "
            f"{expected!r} PostgreSQL renders "
            f"{tasks_vrt._PUBLISH_CATALOG_TIMEOUT!r} to."
        )

    def test_the_budget_is_restored_after_the_acquisition(self) -> None:
        """The UPDATEs after the wait run on the value the transaction arrived with."""
        source = Path(tasks_vrt.__file__).read_text()
        restores = [
            node.lineno
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "set_config('lock_timeout'" in node.value
        ]
        assert len(restores) == 1, f"expected one restore; found {restores}"
        assert _publish_lock_call().lineno < restores[0], (
            "the restore runs before the wait it exists for. Those UPDATEs sit "
            "outside lock_catalog_rows, so a 55P03 there is a bare DBAPIError "
            "whose str() carries the statement and its bound parameters."
        )

    async def test_a_held_records_row_expires_the_budget(
        self, vrt_target, monkeypatch
    ) -> None:
        """The wait gives up as lock contention instead of hanging the job."""
        monkeypatch.setattr(tasks_vrt, "_PUBLISH_CATALOG_TIMEOUT", _TEST_BUDGET)
        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as publisher,
        ):
            await holder.execute(
                select(Record.id)
                .where(Record.id == vrt_target.record_id)
                .with_for_update()
            )
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(CatalogLockConflict) as excinfo:
                await asyncio.wait_for(
                    lock_catalog_rows(
                        publisher,
                        dataset_cls=Dataset,
                        record_cls=Record,
                        dataset_id=vrt_target.id,
                        record_id=vrt_target.record_id,
                        lock_timeout=tasks_vrt._PUBLISH_CATALOG_TIMEOUT,
                    ),
                    timeout=30,
                )
            waited_ms = (loop.time() - started) * 1000
            await holder.rollback()

        assert waited_ms >= _TEST_BUDGET_MS * 0.8, (
            f"the wait gave up after {round(waited_ms)}ms against a "
            f"{_TEST_BUDGET} budget, so this run proves nothing about it"
        )
        cause = excinfo.value.__cause__
        assert sqlstate(cause) == "55P03", (
            f"the expiry reported {sqlstate(cause)!r}, so the three-way dispatch "
            "cannot tell it from a deadlock"
        )
