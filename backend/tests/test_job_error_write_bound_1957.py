"""fix(#1957): the five worker error-write paths #1950 left unbounded.

Each settles a failed job by UPDATEing ``ingest_jobs`` on a session holding no
lock on that row. They now share ``write_job_failure_for_attempt``, whose
budget ends the write on a held row instead of parking the worker there.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
import uuid
from pathlib import Path

import pytest
import structlog.testing
from sqlalchemy import delete, select

import app.processing.analysis.tasks as analysis_tasks
from app.modules.auth.models import User
from app.platform.jobs.heartbeat import (
    JOB_ERROR_WRITE_TIMEOUT_MS,
    write_job_failure_for_attempt,
)
from app.platform.jobs.models import IngestJob

pytestmark = pytest.mark.anyio

# Short enough to measure a give-up inside a test, long enough that a healthy
# uncontended write never reaches it.
_TEST_BUDGET_MS = 400

# The remaining sites and the routine each reaches its terminal job write
# through. ``regenerate_vrt`` arms directly: its handler writes two more rows
# in the same session and the budget belongs to that whole transaction.
_REMAINING_SITES = {
    ("app.processing.ingest.tasks_postgis_refresh", "refresh_postgis"): (
        "write_job_failure_for_attempt"
    ),
    ("app.processing.ingest.tasks_stac_refresh", "refresh_stac"): (
        "write_job_failure_for_attempt"
    ),
    ("app.processing.analysis.tasks", "_fail_cancelled_job"): (
        "write_job_failure_for_attempt"
    ),
    ("app.processing.analysis.tasks", "_mark_job_failed"): (
        "write_job_failure_for_attempt"
    ),
    ("app.processing.ingest.tasks_vrt", "regenerate_vrt"): (
        "arm_job_error_write_budget"
    ),
}

# Any of these routes the write through an armed transaction.
_SANCTIONED_ROUTES = frozenset(
    {
        "arm_job_error_write_budget",
        "write_job_failure_for_attempt",
        "_cleanup_staging_on_failure",
        "load_job_for_error_write",
    }
)


def _source_of(module_name: str, attr: str) -> str:
    module = importlib.import_module(module_name)
    target = getattr(module, attr)
    return inspect.getsource(getattr(target, "func", target))


def _call_names(node: ast.AST) -> set[str]:
    return {
        getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
    }


def _writes_failed_status(node: ast.AST) -> bool:
    """Whether *node* contains a ``{"status": "failed", ...}`` values map."""
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Dict):
            continue
        for key, value in zip(sub.keys, sub.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "status"
                and isinstance(value, ast.Constant)
                and value.value == "failed"
            ):
                return True
    return False


def _call_lines(node: ast.AST, name: str) -> list[int]:
    return [
        sub.lineno
        for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        and (getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)) == name
    ]


class TestEveryRemainingSiteIsArmed:
    """Pure AST — no database."""

    @pytest.mark.parametrize(
        ("target", "route"),
        sorted(_REMAINING_SITES.items()),
        ids=lambda value: value[1] if isinstance(value, tuple) else value,
    )
    def test_the_site_routes_through_an_armed_transaction(
        self, target: tuple[str, str], route: str
    ) -> None:
        assert route in _call_names(ast.parse(_source_of(*target))), (
            f"{target[1]} writes its terminal ingest_jobs row without {route}, "
            "so a row a later attempt holds parks the worker there while the "
            "heartbeat keeps reporting the job alive"
        )

    def test_no_fresh_session_failure_write_is_left_unarmed(self) -> None:
        """The enumeration, so a sixth site cannot be added silently."""
        unarmed = []
        for path in sorted(Path("app/processing").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                    continue
                names = _call_names(node)
                if "async_session" not in names or not _writes_failed_status(node):
                    continue
                if not names & _SANCTIONED_ROUTES:
                    unarmed.append(f"{path}:{node.lineno} {node.name}")
        assert not unarmed, (
            f"{unarmed} open a fresh session and write status='failed' on the "
            "job row without arming the error-write budget on it"
        )

    def test_the_analysis_write_is_armed_after_its_rollback(self) -> None:
        """``SET LOCAL`` dies with the transaction, so order is the whole fix."""
        tree = ast.parse(
            _source_of("app.processing.analysis.tasks", "_mark_job_failed")
        )
        writes = _call_lines(tree, "write_job_failure_for_attempt")
        assert len(writes) == 1, f"expected one budgeted write; found {len(writes)}"
        rollbacks = _call_lines(tree, "rollback")
        assert rollbacks and min(rollbacks) < writes[0], (
            "the caller's transaction is no longer ended before the budgeted "
            "write, so the write waits on a lock this session holds itself"
        )
        assert not [line for line in _call_lines(tree, "commit") if line < writes[0]], (
            "a commit runs between the rollback and the budgeted write, which "
            "leaves the UPDATE in a transaction carrying no SET LOCAL"
        )

    def test_the_shared_helper_swallows_its_own_failure(self) -> None:
        tree = ast.parse(inspect.getsource(write_job_failure_for_attempt))
        handlers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler)
            and getattr(node.type, "id", None) == "DBAPIError"
        ]
        assert len(handlers) == 1, (
            f"the helper has {len(handlers)} DBAPIError handlers; without "
            "exactly one an expired budget becomes the task's outcome in "
            "place of the failure the caller was already handling"
        )
        assert not [n for n in ast.walk(handlers[0]) if isinstance(n, ast.Raise)], (
            "the helper re-raises, so a timeout is still what the worker reports"
        )
        assert "log_job_error_write_failure" in _call_names(handlers[0]), (
            "the helper swallows the failure without recording it, trading a "
            "visible hang for an invisible one"
        )


class TestOneBudgetConstant:
    def test_exactly_one_module_defines_the_budget(self) -> None:
        defined = []
        for path in sorted(Path("app").rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    name = getattr(target, "id", "")
                    if name.endswith("ERROR_WRITE_TIMEOUT_MS"):
                        defined.append(f"{path}:{name}")
        assert defined == [
            "app/platform/jobs/heartbeat.py:JOB_ERROR_WRITE_TIMEOUT_MS"
        ], (
            f"the error-write budget is defined at {defined}. Two constants for "
            "one budget agree until one of them is retuned"
        )

    def test_the_raster_replace_bracket_reads_the_shared_budget(self) -> None:
        import app.processing.ingest.tasks_raster_replace as tasks_raster_replace

        assert (
            tasks_raster_replace.JOB_ERROR_WRITE_TIMEOUT_MS
            is JOB_ERROR_WRITE_TIMEOUT_MS
        ), "the replace tail no longer reads the shared budget"


async def _admin_id(session) -> uuid.UUID:
    return (
        await session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()


@pytest.fixture
async def running_job(test_db_session):
    """A claimed ``ingest_jobs`` row, deleted when the test ends."""
    job = IngestJob(
        source_filename=f"error_write_1957_{uuid.uuid4().hex[:8]}.geojson",
        created_by=await _admin_id(test_db_session),
        status="running",
    )
    test_db_session.add(job)
    await test_db_session.commit()
    await test_db_session.refresh(job)
    ids = (job.id, job.attempt_id)
    yield ids
    await test_db_session.execute(delete(IngestJob).where(IngestJob.id == ids[0]))
    await test_db_session.commit()


class _HeldJobRow:
    """Holds *job_id* under ``FOR UPDATE`` and times what waits on it."""

    def __init__(self, job_id: uuid.UUID) -> None:
        self._job_id = job_id
        self.waited_ms = 0.0

    async def __aenter__(self) -> "_HeldJobRow":
        import app.core.db as db_module

        self._holder = db_module.async_session()
        self._session = await self._holder.__aenter__()
        await self._session.execute(
            select(IngestJob.id).where(IngestJob.id == self._job_id).with_for_update()
        )
        self._started = asyncio.get_running_loop().time()
        return self

    async def __aexit__(self, *exc_info) -> None:
        self.waited_ms = (asyncio.get_running_loop().time() - self._started) * 1000
        await self._session.rollback()
        await self._holder.__aexit__(*exc_info)

    def assert_gave_up_on_budget(self) -> None:
        assert self.waited_ms >= _TEST_BUDGET_MS * 0.8, (
            f"the write gave up after {round(self.waited_ms)}ms against a "
            f"{_TEST_BUDGET_MS}ms budget, so this run proves nothing about it"
        )
        assert self.waited_ms < _TEST_BUDGET_MS * 5, (
            f"the write waited {round(self.waited_ms)}ms, far past the "
            f"{_TEST_BUDGET_MS}ms this test installs. The patch did not reach "
            "the budget the code read, so this run measures the shipped 10s "
            "constant and would pass with the patch severed entirely"
        )


@pytest.fixture
def short_budget(monkeypatch):
    # `arm_job_error_write_budget` reads this as a global of its OWN module,
    # resolved per call, so no import placement elsewhere severs the patch.
    monkeypatch.setattr(
        "app.platform.jobs.heartbeat.JOB_ERROR_WRITE_TIMEOUT_MS", _TEST_BUDGET_MS
    )


class TestAHeldJobRowEndsTheRemainingWrites:
    """Against PostgreSQL, with the row held by another transaction."""

    async def test_the_shared_helper_gives_up_and_reports_nothing(
        self, running_job, short_budget, test_db_session
    ) -> None:
        job_id, attempt_id = running_job
        import app.core.db as db_module

        async with _HeldJobRow(job_id) as held:
            async with db_module.async_session() as err_session:
                with structlog.testing.capture_logs() as captured:
                    outcome = await asyncio.wait_for(
                        write_job_failure_for_attempt(
                            err_session,
                            job_id,
                            attempt_id,
                            values={"status": "failed", "error_message": "boom"},
                            task_name="refresh_postgis",
                        ),
                        timeout=30,
                    )
        held.assert_gave_up_on_budget()

        assert outcome is None, (
            f"the expired write returned {outcome!r}, which a caller reads as "
            "a fence miss and answers by dropping work this attempt still owns"
        )
        expired = [r for r in captured if r.get("event") == "job_error_write_timeout"]
        assert len(expired) == 1, (
            f"expected one job_error_write_timeout event; got {captured}"
        )
        assert expired[0]["sqlstate"] == "57014", (
            f"the held row ended the write with {expired[0]['sqlstate']!r}. Both "
            "GUCs are armed at the same value and the blocking statement is the "
            "UPDATE, so statement_timeout holds the earlier deadline; 55P03 "
            "would mean only lock_timeout was armed"
        )
        test_db_session.expire_all()
        unchanged = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == job_id)
            )
        ).scalar_one()
        assert unchanged.status == "running", (
            "the write that gave up still recorded a status, so the trade this "
            "bound makes is not the one the helper's docstring states"
        )

    async def test_the_analysis_failure_tail_gives_up(
        self, running_job, short_budget, monkeypatch
    ) -> None:
        job_id, attempt_id = running_job
        import app.core.db as db_module

        probes: list[str | None] = []

        async def _record_probe(session, **kwargs) -> None:
            probes.append(kwargs.get("out_table"))

        monkeypatch.setattr(
            analysis_tasks, "drop_unadopted_analysis_output", _record_probe
        )

        async with _HeldJobRow(job_id) as held:
            async with db_module.async_session() as session:
                await asyncio.wait_for(
                    analysis_tasks._mark_job_failed(
                        session,
                        job_id=str(job_id),
                        attempt_id=attempt_id,
                        exc=RuntimeError("the CTAS ran out of temp space"),
                        schema="data",
                        out_table="analysis_1957",
                        operation="buffer",
                    ),
                    timeout=30,
                )
        held.assert_gave_up_on_budget()

        assert probes == [], (
            "an expired budget was read as a fence miss, so the tail probed "
            "for an adopting dataset and would drop a table its own attempt "
            "still owns"
        )

    async def test_the_cancelled_analysis_tail_gives_up(
        self, running_job, short_budget
    ) -> None:
        job_id, attempt_id = running_job
        import app.core.db as db_module

        async with _HeldJobRow(job_id) as held:
            async with db_module.async_session() as working:
                await asyncio.wait_for(
                    analysis_tasks._fail_cancelled_job(
                        working,
                        job_id=str(job_id),
                        attempt_id=attempt_id,
                        schema="data",
                        out_table=None,
                        operation="buffer",
                    ),
                    timeout=30,
                )
        held.assert_gave_up_on_budget()

    async def test_an_uncontended_fence_miss_still_probes(
        self, running_job, short_budget, monkeypatch
    ) -> None:
        """``False`` and ``None`` must not collapse: only one may drop a table."""
        job_id, _attempt_id = running_job
        import app.core.db as db_module

        probes: list[str | None] = []

        async def _record_probe(session, **kwargs) -> None:
            probes.append(kwargs.get("out_table"))

        monkeypatch.setattr(
            analysis_tasks, "drop_unadopted_analysis_output", _record_probe
        )

        async with db_module.async_session() as session:
            await analysis_tasks._mark_job_failed(
                session,
                job_id=str(job_id),
                attempt_id=uuid.uuid4(),
                exc=RuntimeError("superseded"),
                schema="data",
                out_table="analysis_1957",
                operation="buffer",
            )

        assert probes == ["analysis_1957"], (
            "a fence miss no longer probes for an adopting dataset row, so a "
            "swept job's unregistered output table is leaked forever"
        )
