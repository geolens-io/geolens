"""Raster replace's phase 2 bounds two waits and leaves the rest alone (#1937).

The kwarg covers the job SELECT, `lock_timeout` covers the catalog wait, and
both are cleared before the quota reservation, which waits on an advisory lock
a sibling upload holds across a whole COG upload. DB tests need the test database.
"""

import ast
import asyncio
import uuid
from pathlib import Path

import pytest
import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import joinedload

from app.core.db.sqlstate import sqlstate
from app.modules.catalog.datasets.domain.models import Dataset
from app.platform.catalog_locks import (
    CATALOG_LOCK_CONFLICT_CODE,
    CatalogLockConflict,
    lock_catalog_rows,
)
from app.platform.jobs.models import IngestJob
from app.processing.ingest import tasks_raster_replace
from app.processing.ingest.tasks_common import _job_phase_session

from tests.factories import get_user_id
from tests.test_swap_lock_timeout_scope_1917 import make_swap_target

pytestmark = pytest.mark.anyio

# Short enough that a held row outlasts it in under a second.
_TEST_BUDGET_MS = 400

# The lock `reserve_storage_bytes` takes; a sibling first ingest holds it from
# `create_raster_dataset` until its own commit, across three storage puts.
_QUOTA_LOCK = (
    "SELECT pg_advisory_xact_lock("
    "hashtextextended('geolens:dataset_quota:' || :uid, 0))"
)


def _reupload_raster_body() -> ast.FunctionDef:
    source = Path(tasks_raster_replace.__file__).read_text()
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "reupload_raster"
    )


def _phase_two_call() -> ast.Call:
    """The ``_job_phase_session`` call ``reupload_raster`` opens phase 2 with."""
    calls = [
        node
        for node in ast.walk(_reupload_raster_body())
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_job_phase_session"
        and any(
            kw.arg == "phase"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == "phase2"
            for kw in node.keywords
        )
    ]
    assert len(calls) == 1, f"expected one phase-2 session bracket; found {len(calls)}"
    return calls[0]


def _set_local_line(guc: str) -> int:
    """Line of the ``SET LOCAL <guc> = 0`` reset inside ``reupload_raster``."""
    lines = [
        node.lineno
        for node in ast.walk(_reupload_raster_body())
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == f"SET LOCAL {guc} = 0"
    ]
    assert len(lines) == 1, f"expected one 'SET LOCAL {guc} = 0'; found {lines}"
    return lines[0]


def _call_line(name: str) -> int:
    lines = [
        node.lineno
        for node in ast.walk(_reupload_raster_body())
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == name
    ]
    assert len(lines) == 1, f"expected one {name} call; found {lines}"
    return lines[0]


async def _as_postgres_renders(value_ms: int) -> str:
    """What ``current_setting('lock_timeout')`` reports back for *value_ms*."""
    import app.core.db as db_module

    async with db_module.async_session() as probe:
        rendered = await probe.scalar(
            text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": str(value_ms)},
        )
        await probe.rollback()
    return rendered


@pytest.fixture
async def swap_target(client, test_db_session):
    async for target in make_swap_target(client, test_db_session):
        yield target


@pytest.fixture
async def running_job(test_db_session):
    """A claimed ``ingest_jobs`` row the phase bracket can load and fence on."""
    job = IngestJob(
        source_filename=f"phase_budget_{uuid.uuid4().hex[:8]}.tif",
        created_by=await get_user_id(test_db_session, "admin"),
        status="running",
        current_step="finalize",
        progress=0.8,
    )
    test_db_session.add(job)
    await test_db_session.commit()
    ids = (job.id, job.attempt_id)
    yield ids
    await test_db_session.execute(delete(IngestJob).where(IngestJob.id == ids[0]))
    await test_db_session.commit()


async def _take_the_pair(session, dataset, acquire=lock_catalog_rows) -> None:
    """The acquisition as ``reupload_raster`` makes it, reporter included."""
    with tasks_raster_replace._reporting_catalog_wait(
        job_id="job-1", dataset_id=str(dataset.id)
    ):
        await acquire(
            session,
            dataset_cls=Dataset,
            record_cls=type(dataset.record),
            dataset_id=dataset.id,
            record_id=dataset.record_id,
            lock_timeout=None,
        )


def _enter_phase(job_id, attempt_id):
    """The phase-2 bracket with the module's budget, as ``reupload_raster`` opens it."""
    return _job_phase_session(
        job_id,
        phase="phase2",
        attempt_id=attempt_id,
        require_status="running",
        lock_and_statement_timeout_ms=tasks_raster_replace._PHASE2_TIMEOUT_MS,
    )


class TestPhaseTwoCallSite:
    """Pure AST — no DB."""

    def test_the_phase_bracket_names_the_module_budget(self) -> None:
        budget = {kw.arg: kw.value for kw in _phase_two_call().keywords if kw.arg}.get(
            "lock_and_statement_timeout_ms"
        )
        assert isinstance(budget, ast.Name) and budget.id == "_PHASE2_TIMEOUT_MS", (
            "reupload_raster's phase 2 enters _job_phase_session without "
            f"lock_and_statement_timeout_ms ({ast.dump(budget) if budget else None}), "
            "so the helper issues neither SET LOCAL and the job SELECT it runs "
            "before the caller gets control is unbounded."
        )

    def test_the_acquisition_leaves_the_phase_budget_in_force(self) -> None:
        source = Path(tasks_raster_replace.__file__).read_text()
        passed = [
            kw.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "lock_catalog_rows"
            for kw in node.keywords
            if kw.arg == "lock_timeout"
        ]
        assert len(passed) == 1, f"expected one acquisition; found {len(passed)}"
        assert isinstance(passed[0], ast.Constant) and passed[0].value is None, (
            "the acquisition installs its own lock_timeout, which would persist "
            "onto the quota reservation below it."
        )

    def test_statement_timeout_is_cleared_before_the_phase_does_its_work(self) -> None:
        assert _set_local_line("statement_timeout") < _call_line("lock_catalog_rows"), (
            "statement_timeout is still armed at the catalog wait, so expiry is "
            "57014, which is outside LOCK_CONFLICT: lock_catalog_rows re-raises "
            "a bare DBAPIError whose str() is a SQL statement, and two "
            "user-visible error_message columns store it verbatim."
        )

    def test_lock_timeout_is_cleared_before_the_quota_reservation(self) -> None:
        reset = _set_local_line("lock_timeout")
        assert _call_line("lock_catalog_rows") < reset, (
            "lock_timeout is cleared before the catalog wait it exists for, "
            "leaving that wait unbounded"
        )
        assert reset < _call_line("reserve_replacement_bytes"), (
            "the quota reservation runs under a lock_timeout. It waits on a "
            "per-user advisory lock a sibling first ingest holds across a whole "
            "COG upload, and both GUCs clamp an advisory wait, so a replace that "
            "waited and succeeded before now fails after its own upload is done."
        )


class TestRasterRefreshErrorCode:
    """Pure mapping — no DB."""

    def test_a_contended_catalog_row_maps_to_its_own_code(self) -> None:
        code = tasks_raster_replace._raster_refresh_error_code(
            CatalogLockConflict("held")
        )
        assert code == CATALOG_LOCK_CONFLICT_CODE, (
            "a lock-contention failure reports as a bad raster, sending the "
            "reader to inspect a file that was never the problem"
        )

    def test_everything_else_keeps_its_path_code(self) -> None:
        assert (
            tasks_raster_replace._raster_refresh_error_code(RuntimeError("gdal"))
            == "raster_refresh_failed"
        )


class TestPhaseTwoBudgetAgainstPostgres:
    async def test_the_catalog_wait_runs_on_lock_timeout_alone(
        self, swap_target, running_job
    ) -> None:
        """On entry to the acquisition: budget on lock_timeout, statement_timeout off."""
        stub, _staging = swap_target
        job_id, attempt_id = running_job
        expected = await _as_postgres_renders(tasks_raster_replace._PHASE2_TIMEOUT_MS)
        observed: dict[str, object] = {}

        async def _recording_lock(session, **kwargs):
            observed["lock_timeout"] = await session.scalar(
                text("SELECT current_setting('lock_timeout')")
            )
            observed["statement_timeout"] = await session.scalar(
                text("SELECT current_setting('statement_timeout')")
            )
            await lock_catalog_rows(session, **kwargs)

        async with _enter_phase(job_id, attempt_id) as (session, job):
            assert job is not None
            await session.execute(text("SET LOCAL statement_timeout = 0"))
            loaded = (
                await session.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == stub.id)
                )
            ).scalar_one()
            await _take_the_pair(session, loaded, _recording_lock)
            await session.rollback()

        assert observed["lock_timeout"] == expected, (
            f"the acquisition was entered on lock_timeout "
            f"{observed['lock_timeout']!r}, not the {expected!r} PostgreSQL "
            f"renders {tasks_raster_replace._PHASE2_TIMEOUT_MS} to. A '0' here "
            "is an unbounded wait on a contended catalog row."
        )
        assert observed["statement_timeout"] == "0", (
            f"statement_timeout read {observed['statement_timeout']!r} at the "
            "acquisition, so expiry is 57014 rather than the 55P03 that becomes "
            "a rolled-back CatalogLockConflict."
        )

    async def test_a_holder_past_the_budget_reports_contention(
        self, swap_target, running_job, monkeypatch
    ) -> None:
        """Expiry is a CatalogLockConflict, logged with the wait and the budget."""
        stub, _staging = swap_target
        job_id, attempt_id = running_job
        monkeypatch.setattr(tasks_raster_replace, "_PHASE2_TIMEOUT_MS", _TEST_BUDGET_MS)
        import app.core.db as db_module

        async def _run_phase(clear_statement_timeout: bool = True) -> None:
            async with _enter_phase(job_id, attempt_id) as (session, job):
                assert job is not None
                if clear_statement_timeout:
                    await session.execute(text("SET LOCAL statement_timeout = 0"))
                loaded = (
                    await session.execute(
                        select(Dataset)
                        .options(joinedload(Dataset.record))
                        .where(Dataset.id == stub.id)
                    )
                ).scalar_one()
                await _take_the_pair(session, loaded)

        async with db_module.async_session() as holder:
            await holder.execute(
                select(Dataset.id).where(Dataset.id == stub.id).with_for_update()
            )
            loop = asyncio.get_running_loop()
            started = loop.time()
            with structlog.testing.capture_logs() as captured:
                with pytest.raises(CatalogLockConflict) as excinfo:
                    await asyncio.wait_for(_run_phase(), timeout=30)
            waited_ms = (loop.time() - started) * 1000
            await holder.rollback()

        assert waited_ms >= _TEST_BUDGET_MS * 0.8, (
            f"the phase gave up after {round(waited_ms)}ms against a "
            f"{_TEST_BUDGET_MS}ms budget, so this run proves nothing about the wait"
        )
        assert sqlstate(excinfo.value.__cause__) == "55P03"
        expired = [
            r
            for r in captured
            if r.get("event") == "raster_replace_catalog_lock_timeout"
        ]
        assert len(expired) == 1, (
            f"expected one raster_replace_catalog_lock_timeout event; got {captured}"
        )
        assert expired[0]["log_level"] == "warning"
        assert expired[0]["dataset_id"] == str(stub.id)
        assert expired[0]["budget"] == _TEST_BUDGET_MS
        assert expired[0]["sqlstate"] == "55P03"
        assert expired[0]["waited_ms"] >= _TEST_BUDGET_MS * 0.8

        # Leaving statement_timeout armed is what makes the same wait raise a
        # bare DBAPIError, whose str() two error_message columns store verbatim.
        async with db_module.async_session() as holder:
            await holder.execute(
                select(Dataset.id).where(Dataset.id == stub.id).with_for_update()
            )
            with pytest.raises(DBAPIError) as raw:
                await asyncio.wait_for(_run_phase(False), timeout=30)
            await holder.rollback()

        assert not isinstance(raw.value, CatalogLockConflict)
        assert sqlstate(raw.value) == "57014"
        assert "SELECT" in str(raw.value), (
            "the 57014 path no longer carries SQL in str(exc); if that holds, "
            "the statement_timeout reset is no longer load-bearing for the "
            "error surface and this assertion should be revisited"
        )

    @pytest.mark.parametrize(
        "clear_the_budget", [True, False], ids=["reset", "no_reset"]
    )
    async def test_the_quota_reservation_outlasts_the_budget(
        self, swap_target, running_job, monkeypatch, test_db_session, clear_the_budget
    ) -> None:
        """The reservation waits out a sibling upload only because the reset runs."""
        stub, _staging = swap_target
        job_id, attempt_id = running_job
        monkeypatch.setattr(tasks_raster_replace, "_PHASE2_TIMEOUT_MS", _TEST_BUDGET_MS)
        owner = await get_user_id(test_db_session, "admin")
        import app.core.db as db_module

        held = asyncio.Event()
        hold_for = (_TEST_BUDGET_MS / 1000) * 3

        async def _sibling_upload() -> None:
            async with db_module.async_session() as sibling:
                await sibling.execute(text(_QUOTA_LOCK), {"uid": str(owner)})
                held.set()
                await asyncio.sleep(hold_for)
                await sibling.rollback()

        sibling_task = asyncio.create_task(_sibling_upload())
        await held.wait()

        loop = asyncio.get_running_loop()
        started = loop.time()
        async with _enter_phase(job_id, attempt_id) as (session, job):
            assert job is not None
            await session.execute(text("SET LOCAL statement_timeout = 0"))
            loaded = (
                await session.execute(
                    select(Dataset)
                    .options(joinedload(Dataset.record))
                    .where(Dataset.id == stub.id)
                )
            ).scalar_one()
            await _take_the_pair(session, loaded)
            if clear_the_budget:
                await session.execute(text("SET LOCAL lock_timeout = 0"))
            aborted = None
            try:
                await session.execute(text(_QUOTA_LOCK), {"uid": str(owner)})
            except DBAPIError as exc:
                aborted = sqlstate(exc)
            waited_ms = (loop.time() - started) * 1000
            await session.rollback()
        await sibling_task

        if clear_the_budget:
            assert aborted is None, (
                f"the reservation aborted with {aborted!r} despite the reset. "
                "A replace that waited and succeeded now fails after its own "
                "COG and quicklooks are already uploaded."
            )
            assert waited_ms >= _TEST_BUDGET_MS, (
                f"the reservation acquired in {round(waited_ms)}ms, under the "
                f"{_TEST_BUDGET_MS}ms budget, so the sibling was not holding "
                "and this run proves nothing"
            )
        else:
            assert aborted == "55P03", (
                "the budget did not clamp the advisory wait, so the reset above "
                f"it guards nothing (got {aborted!r}). Both GUCs clamp an "
                "advisory-lock wait; that is why the reset has to exist."
            )
