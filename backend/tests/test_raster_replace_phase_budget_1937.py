"""Raster replace's failure write bounds its wait on the job row, and contention keeps its own code.

DB tests need the test database.
"""

import ast
import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import sqlstate
from app.platform.catalog_locks import (
    CATALOG_LOCK_CONFLICT_CODE,
    CatalogLockConflict,
)
from app.platform.jobs.heartbeat import update_ingest_job_for_attempt
from app.platform.jobs.models import IngestJob
from app.processing.ingest import tasks_raster_replace
from app.processing.ingest.tasks_common import _job_phase_session

from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

# Short enough that a held row outlasts it in under a second.
_TEST_BUDGET_MS = 400


def _reupload_raster_body() -> ast.FunctionDef:
    source = Path(tasks_raster_replace.__file__).read_text()
    return next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "reupload_raster"
    )


def _phase_call(phase: str) -> ast.Call:
    """The ``_job_phase_session`` call ``reupload_raster`` opens *phase* with."""
    calls = [
        node
        for node in ast.walk(_reupload_raster_body())
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_job_phase_session"
        and any(
            kw.arg == "phase"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == phase
            for kw in node.keywords
        )
    ]
    assert len(calls) == 1, f"expected one {phase} bracket; found {len(calls)}"
    return calls[0]


def _budget_name(phase: str) -> str | None:
    """The constant the *phase* bracket names as its budget, if any."""
    budget = {kw.arg: kw.value for kw in _phase_call(phase).keywords if kw.arg}.get(
        "lock_and_statement_timeout_ms"
    )
    return budget.id if isinstance(budget, ast.Name) else None


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


class TestErrorWriteCallSite:
    """Pure AST — no DB."""

    def test_the_error_write_names_its_own_budget(self) -> None:
        assert _budget_name("error_write") == "JOB_ERROR_WRITE_TIMEOUT_MS", (
            "the failure write is unbounded. It UPDATEs the same ingest_jobs "
            "row phase 2 contends for, so bounding phase 2 alone moves the "
            "contention onto a wait nothing ends, with the heartbeat still "
            "reporting the job alive."
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


class TestErrorWriteBudgetAgainstPostgres:
    async def test_the_error_write_gives_up_on_a_held_job_row(
        self, running_job, monkeypatch
    ) -> None:
        """The failure write bounds its own UPDATE against the same job row."""
        job_id, attempt_id = running_job
        monkeypatch.setattr(
            tasks_raster_replace, "JOB_ERROR_WRITE_TIMEOUT_MS", _TEST_BUDGET_MS
        )
        import app.core.db as db_module

        async def _write_the_failure() -> None:
            async with _job_phase_session(
                job_id,
                phase="error_write",
                attempt_id=attempt_id,
                lock_and_statement_timeout_ms=(
                    tasks_raster_replace.JOB_ERROR_WRITE_TIMEOUT_MS
                ),
            ) as (err_session, _job):
                await update_ingest_job_for_attempt(
                    err_session,
                    job_id,
                    attempt_id,
                    values={"status": "failed", "error_message": "replace failed"},
                )
                await err_session.commit()

        async with db_module.async_session() as holder:
            await holder.execute(
                select(IngestJob.id).where(IngestJob.id == job_id).with_for_update()
            )
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(DBAPIError) as excinfo:
                await asyncio.wait_for(_write_the_failure(), timeout=30)
            waited_ms = (loop.time() - started) * 1000
            await holder.rollback()

        assert waited_ms >= _TEST_BUDGET_MS * 0.8, (
            f"the error write gave up after {round(waited_ms)}ms against a "
            f"{_TEST_BUDGET_MS}ms budget, so this run proves nothing"
        )
        assert sqlstate(excinfo.value) == "57014", (
            f"the held job row ended the error write with "
            f"{sqlstate(excinfo.value)!r}. Both GUCs are armed here and the "
            "blocking statement is the UPDATE, so statement_timeout holds the "
            "earlier deadline; nothing on this path stores str(exc)."
        )
