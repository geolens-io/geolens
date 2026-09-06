"""Raster replace's phase 2 runs every statement on a named budget (#1937).

The catalog wait it ends with is covered by that budget, so a held row fails
the job rather than hanging it. The DB tests need the Docker test database.
"""

import ast
import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import is_lock_conflict, sqlstate
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.catalog_locks import lock_catalog_rows
from app.platform.jobs.models import IngestJob
from app.processing.ingest import tasks_raster_replace
from app.processing.ingest.tasks_common import _job_phase_session

from tests.factories import get_user_id
from tests.test_swap_lock_timeout_scope_1917 import make_swap_target

pytestmark = pytest.mark.anyio

# Short enough that a held row outlasts it in under a second.
_TEST_BUDGET_MS = 500


def _phase_two_call() -> ast.Call:
    """The ``_job_phase_session`` call ``reupload_raster`` opens phase 2 with."""
    source = Path(tasks_raster_replace.__file__).read_text()
    calls = [
        node
        for node in ast.walk(ast.parse(source))
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


def _phase_two_keywords() -> dict[str, ast.expr]:
    return {kw.arg: kw.value for kw in _phase_two_call().keywords if kw.arg}


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


class TestPhaseTwoCallSite:
    """Pure AST — no DB."""

    def test_the_phase_bracket_names_the_module_budget(self) -> None:
        budget = _phase_two_keywords().get("lock_and_statement_timeout_ms")
        assert isinstance(budget, ast.Name) and budget.id == "_PHASE2_TIMEOUT_MS", (
            "reupload_raster's phase 2 enters _job_phase_session without "
            f"lock_and_statement_timeout_ms ({ast.dump(budget) if budget else None}), "
            "so the helper issues neither SET LOCAL and every statement in the "
            "phase — the catalog wait included — runs unbounded."
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
            "the acquisition installs its own lock_timeout, which replaces the "
            "phase budget for the rest of the transaction."
        )


class TestPhaseTwoBudgetAgainstPostgres:
    async def test_the_catalog_wait_starts_on_the_phase_budget(
        self, swap_target, running_job
    ) -> None:
        """Both timeouts are in force when the acquisition is entered."""
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

        async with _job_phase_session(
            job_id,
            phase="phase2",
            attempt_id=attempt_id,
            require_status="running",
            lock_and_statement_timeout_ms=tasks_raster_replace._PHASE2_TIMEOUT_MS,
        ) as (session, job):
            assert job is not None
            await _recording_lock(
                session,
                dataset_cls=Dataset,
                record_cls=Record,
                dataset_id=stub.id,
                record_id=stub.record_id,
                lock_timeout=None,
            )
            await session.rollback()

        assert observed["lock_timeout"] == expected, (
            f"the acquisition was entered on lock_timeout "
            f"{observed['lock_timeout']!r}, not the {expected!r} PostgreSQL "
            f"renders {tasks_raster_replace._PHASE2_TIMEOUT_MS} to. A '0' here "
            "is an unbounded wait on a contended catalog row."
        )
        assert observed["statement_timeout"] == expected, (
            f"statement_timeout read {observed['statement_timeout']!r} at the "
            "acquisition, so the phase's other statements are unbounded even "
            "where the lock wait is not."
        )

    async def test_a_holder_past_the_budget_aborts_the_phase(
        self, swap_target, running_job, monkeypatch
    ) -> None:
        """Expiry raises 57014 — statement_timeout wins the tie at equal values."""
        stub, _staging = swap_target
        job_id, attempt_id = running_job
        monkeypatch.setattr(tasks_raster_replace, "_PHASE2_TIMEOUT_MS", _TEST_BUDGET_MS)
        import app.core.db as db_module

        async def _run_phase() -> None:
            async with _job_phase_session(
                job_id,
                phase="phase2",
                attempt_id=attempt_id,
                require_status="running",
                lock_and_statement_timeout_ms=tasks_raster_replace._PHASE2_TIMEOUT_MS,
            ) as (session, job):
                assert job is not None
                await lock_catalog_rows(
                    session,
                    dataset_cls=Dataset,
                    record_cls=Record,
                    dataset_id=stub.id,
                    record_id=stub.record_id,
                    lock_timeout=None,
                )

        async with db_module.async_session() as holder:
            await holder.execute(
                select(Dataset.id).where(Dataset.id == stub.id).with_for_update()
            )
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(DBAPIError) as excinfo:
                await asyncio.wait_for(_run_phase(), timeout=30)
            waited_ms = (loop.time() - started) * 1000
            await holder.rollback()

        assert waited_ms >= _TEST_BUDGET_MS * 0.8, (
            f"the phase gave up after {round(waited_ms)}ms against a "
            f"{_TEST_BUDGET_MS}ms budget, so this run proves nothing about the wait"
        )
        assert sqlstate(excinfo.value) == "57014", (
            f"the held row aborted the phase with {sqlstate(excinfo.value)!r}. "
            "lock_and_statement_timeout_ms arms statement_timeout at statement "
            "start and lock_timeout only once the wait begins, so at equal "
            "values statement_timeout is always the earlier deadline."
        )
        assert not is_lock_conflict(excinfo.value), (
            "57014 is outside LOCK_CONFLICT, so lock_catalog_rows re-raises the "
            "DBAPIError instead of the rolled-back CatalogLockConflict; the "
            "phase bracket's own handler does the rollback."
        )
