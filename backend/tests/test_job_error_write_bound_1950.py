"""fix(#1950): the bound on a worker's terminal failure write.

Six ingest tails settle a failed job by UPDATEing its ``ingest_jobs`` row on a
fresh session. That UPDATE runs under a 10-second budget, so a held row ends it
instead of parking the worker while the heartbeat reports the job alive.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError

import app.processing.ingest.tasks_raster as tasks_raster
from app.core.db.sqlstate import sqlstate
from app.modules.auth.models import User
from app.platform.jobs.heartbeat import JOB_ERROR_WRITE_TIMEOUT_MS
from app.platform.jobs.models import IngestJob
from app.processing.ingest.tasks_common import (
    _cleanup_staging_on_failure,
    _job_phase_session,
)

pytestmark = pytest.mark.anyio

# Short enough to measure a give-up inside a test, long enough that a healthy
# uncontended write never reaches it.
_TEST_BUDGET_MS = 400


def _arm_call_lines(tree: ast.AST) -> list[int]:
    """Line numbers of every ``arm_job_error_write_budget`` call in *tree*."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "arm_job_error_write_budget"
    ]


def _method_call_lines(tree: ast.AST, attr: str) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == attr
    ]


def _failed_status_lines(tree: ast.AST) -> list[int]:
    """Line numbers of every ``status="failed"`` keyword or dict entry."""
    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg == "status"
        and isinstance(node.value, ast.Constant)
        and node.value.value == "failed"
    ]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "status"
                and isinstance(value, ast.Constant)
                and value.value == "failed"
            ):
                lines.append(key.lineno)
    return lines


def _is_error_write_bracket(node: ast.AST) -> bool:
    """Whether *node* is a ``_job_phase_session(phase="error_write")`` call."""
    return (
        isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "_job_phase_session"
        and any(
            kw.arg == "phase"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == "error_write"
            for kw in node.keywords
        )
    )


def _bracket_budget(module) -> str | None:
    """The name *module*'s error-write bracket passes as its budget."""
    tree = ast.parse(Path(module.__file__).read_text())
    for node in ast.walk(tree):
        if _is_error_write_bracket(node):
            for kw in node.keywords:
                if kw.arg == "lock_and_statement_timeout_ms":
                    return getattr(kw.value, "id", None)
            return None
    raise AssertionError(f"{module.__name__} opens no error_write bracket")


class TestTheBoundIsWhereTheBlockingStatementIs:
    """Pure AST — no database."""

    def test_the_shared_helper_arms_between_its_rollback_and_its_update(self) -> None:
        tree = ast.parse(inspect.getsource(_cleanup_staging_on_failure))
        rollbacks = _method_call_lines(tree, "rollback")
        commits = _method_call_lines(tree, "commit")
        arms = _arm_call_lines(tree)
        failure_update = _failed_status_lines(tree)
        assert len(arms) == 1, (
            f"expected one arm_job_error_write_budget call; found {len(arms)}"
        )
        assert min(rollbacks) < min(arms), (
            "the budget is installed before the helper's rollback, which ends "
            "the transaction and discards every SET LOCAL on it"
        )
        assert max(arms) < min(failure_update), (
            "the failure UPDATE runs before the budget is armed, so the "
            "statement that blocks on a contended job row is still unbounded"
        )
        stranded = [
            line
            for line in rollbacks + commits
            if min(arms) < line < min(failure_update)
        ]
        assert not stranded, (
            f"a rollback or commit at {stranded} ends the transaction between "
            "the arm and the failure UPDATE, so the UPDATE runs on a "
            "transaction that carries no SET LOCAL"
        )

    @pytest.mark.parametrize(
        "module_name", ["tasks_raster", "tasks_vector"], ids=["raster", "vector"]
    )
    def test_the_bracketed_tails_name_the_shared_budget(self, module_name: str) -> None:
        import importlib

        module = importlib.import_module(f"app.processing.ingest.{module_name}")
        assert _bracket_budget(module) == "JOB_ERROR_WRITE_TIMEOUT_MS", (
            f"{module_name}'s error-write bracket passes no "
            "lock_and_statement_timeout_ms, so _job_phase_session issues "
            "neither SET LOCAL and the SELECT it runs before the caller gets "
            "control can stall behind a table lock"
        )

    def test_the_raster_failure_update_is_inside_the_bounded_bracket(self) -> None:
        """The budget belongs to a transaction, so the UPDATE's position is the gate."""
        tree = ast.parse(Path(tasks_raster.__file__).read_text())
        brackets = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncWith)
            and any(_is_error_write_bracket(item.context_expr) for item in node.items)
        ]
        assert len(brackets) == 1, f"expected one bracket; found {len(brackets)}"
        bracket = brackets[0]
        inside = [
            line
            for line in _failed_status_lines(tree)
            if bracket.lineno < line <= bracket.end_lineno
        ]
        assert inside, (
            "ingest_raster's status=failed UPDATE is no longer inside the "
            "bracket that installs the budget, so it runs on a transaction "
            "carrying no SET LOCAL while the kwarg gate stays green"
        )

    def test_the_vrt_regeneration_tail_arms_before_its_writes(self) -> None:
        """`regenerate_vrt` reaches this handler from its own bounded publish wait."""
        import app.processing.ingest.tasks_vrt as tasks_vrt

        tree = ast.parse(inspect.getsource(tasks_vrt.regenerate_vrt.func))
        arms = _arm_call_lines(tree)
        assert len(arms) == 1, (
            "regenerate_vrt's failure handler opens a bare async_session() with "
            "no budget, so a contended job row parks the worker there — and the "
            "publish wait above it gives up after 15s and lands exactly here"
        )
        assert min(arms) < min(_failed_status_lines(tree)), (
            "the budget is armed after the writes it exists to bound"
        )

    @pytest.mark.parametrize(
        ("module_name", "task_name"),
        [
            ("tasks_vector", "ingest_file"),
            ("tasks_raster", "ingest_raster"),
            ("tasks_reupload", "reupload_file"),
        ],
    )
    def test_the_terminal_status_survives_a_raised_error_write(
        self, module_name: str, task_name: str
    ) -> None:
        """The reapers in each `finally` gate on it, and the error write can raise."""
        import importlib

        module = importlib.import_module(f"app.processing.ingest.{module_name}")
        target = getattr(module, task_name)
        tree = ast.parse(inspect.getsource(getattr(target, "func", target)))
        protected = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Try)
            and any(
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "final_status"
                    for t in stmt.targets
                )
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value == "failed"
                for stmt in node.finalbody
            )
        ]
        assert protected, (
            f"{task_name} sets final_status='failed' positionally after its "
            "error write. That write is bounded now and can raise, leaving the "
            "status 'pending' so the finally-block reapers return early"
        )

    @pytest.mark.parametrize(
        ("module_name", "task_name"),
        [
            ("tasks_vector", "ingest_file"),
            ("tasks_vector", "ingest_service"),
            ("tasks_reupload", "reupload_file"),
            ("tasks_reupload", "reupload_service"),
        ],
    )
    def test_the_four_helper_routed_tails_still_route_there(
        self, module_name: str, task_name: str
    ) -> None:
        """Each tail's bound is the shared helper's, so it must still call it."""
        import importlib

        module = importlib.import_module(f"app.processing.ingest.{module_name}")
        target = getattr(module, task_name)
        source = inspect.getsource(getattr(target, "func", target))
        assert "_cleanup_staging_on_failure" in source, (
            f"{module_name}.{task_name} writes its own terminal failure row "
            "again, so the budget in the shared helper no longer covers it"
        )


async def _admin_id(session) -> uuid.UUID:
    return (
        await session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()


@pytest.fixture
async def running_job(test_db_session):
    """A claimed ``ingest_jobs`` row, deleted when the test ends."""
    job = IngestJob(
        source_filename=f"error_write_{uuid.uuid4().hex[:8]}.geojson",
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


class TestAHeldJobRowEndsTheFailureWrite:
    """Against PostgreSQL, with the row held by another transaction."""

    async def test_the_shared_helper_gives_up(
        self, running_job, monkeypatch, test_db_session
    ) -> None:
        job_id, _attempt_id = running_job
        # `arm_job_error_write_budget` reads this as a global of its OWN module,
        # resolved per call, so no import placement elsewhere can sever the
        # patch. The upper bound below is what proves the patch was read.
        monkeypatch.setattr(
            "app.platform.jobs.heartbeat.JOB_ERROR_WRITE_TIMEOUT_MS", _TEST_BUDGET_MS
        )
        import app.core.db as db_module

        async with db_module.async_session() as holder:
            await holder.execute(
                select(IngestJob.id).where(IngestJob.id == job_id).with_for_update()
            )
            loop = asyncio.get_running_loop()
            started = loop.time()
            async with db_module.async_session() as err_session:
                err_job = (
                    await err_session.execute(
                        select(IngestJob).where(IngestJob.id == job_id)
                    )
                ).scalar_one()
                with pytest.raises(DBAPIError) as excinfo:
                    await asyncio.wait_for(
                        _cleanup_staging_on_failure(
                            err_session,
                            staging_table="",
                            job=err_job,
                            exc=RuntimeError("ogr2ogr could not read the layer"),
                            task_name="ingest_file",
                            attempt_id=None,
                        ),
                        timeout=30,
                    )
                waited_ms = (loop.time() - started) * 1000
                await err_session.rollback()
            await holder.rollback()

        assert waited_ms >= _TEST_BUDGET_MS * 0.8, (
            f"the failure write gave up after {round(waited_ms)}ms against a "
            f"{_TEST_BUDGET_MS}ms budget, so this run proves nothing about it"
        )
        assert waited_ms < _TEST_BUDGET_MS * 5, (
            f"the failure write waited {round(waited_ms)}ms, far past the "
            f"{_TEST_BUDGET_MS}ms this test installs. The monkeypatch did not "
            "reach the budget the code read, so this run measures the shipped "
            "10s constant and would pass with the patch severed entirely"
        )
        assert sqlstate(excinfo.value) == "57014", (
            f"the held row ended the failure write with {sqlstate(excinfo.value)!r}. "
            "Both GUCs are armed at the same value and the blocking statement is "
            "the UPDATE, so statement_timeout holds the earlier deadline; 55P03 "
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
            "bound makes is not the one the docstring states"
        )

    async def test_the_raster_tail_gives_up(self, running_job, monkeypatch) -> None:
        """``ingest_raster`` writes its own UPDATE inside the bracket's budget."""
        from sqlalchemy import update as sa_update

        job_id, attempt_id = running_job
        # The budget comes from the real call site, so a bracket that stops
        # passing one fails here as well as in the structural gate.
        budget_name = _bracket_budget(tasks_raster)
        assert budget_name is not None, "the error-write bracket passes no budget"
        monkeypatch.setattr(tasks_raster, budget_name, _TEST_BUDGET_MS)
        import app.core.db as db_module

        async def _write_the_failure() -> None:
            async with _job_phase_session(
                job_id,
                phase="error_write",
                attempt_id=attempt_id,
                lock_and_statement_timeout_ms=getattr(tasks_raster, budget_name),
            ) as (err_session, _err_job):
                await err_session.execute(
                    sa_update(IngestJob)
                    .where(
                        IngestJob.id == job_id,
                        IngestJob.attempt_id == attempt_id,
                        IngestJob.status == "running",
                    )
                    .values(status="failed", error_message="cog build failed")
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
            f"the failure write gave up after {round(waited_ms)}ms against a "
            f"{_TEST_BUDGET_MS}ms budget, so this run proves nothing about it"
        )
        assert waited_ms < _TEST_BUDGET_MS * 5, (
            f"the failure write waited {round(waited_ms)}ms, far past the "
            f"{_TEST_BUDGET_MS}ms this test installs, so it is measuring some "
            "budget other than the one it set"
        )
        assert sqlstate(excinfo.value) == "57014", (
            f"the held row ended the failure write with {sqlstate(excinfo.value)!r}; "
            "see the sibling assertion for why 55P03 is the wrong-arming signal"
        )


class TestWhyTheBoundIsNotOnTheBracket:
    """A budget on the phase bracket does not reach the statement that blocks."""

    async def test_the_helpers_rollback_discards_an_upstream_budget(
        self, running_job
    ) -> None:
        job_id, attempt_id = running_job
        async with _job_phase_session(
            job_id,
            phase="error_write",
            attempt_id=attempt_id,
            lock_and_statement_timeout_ms=_TEST_BUDGET_MS,
        ) as (session, job):
            assert job is not None
            armed = (
                await session.execute(text("SELECT current_setting('lock_timeout')"))
            ).scalar()
            await session.rollback()
            after = (
                await session.execute(text("SELECT current_setting('lock_timeout')"))
            ).scalar()
        assert armed != "0", "the bracket kwarg no longer arms lock_timeout at all"
        assert after == "0", (
            "a budget installed by the bracket survives the rollback the shared "
            "failure helper opens with, which would make arming it there the fix"
        )

    async def test_an_unbounded_update_never_ends_on_a_held_row(
        self, running_job
    ) -> None:
        """The behaviour an unset ``lock_timeout`` gives, measured not assumed."""
        from sqlalchemy import update as sa_update

        job_id, _attempt_id = running_job
        import app.core.db as db_module

        async def _unbounded_failure_update(session) -> None:
            await session.execute(
                sa_update(IngestJob)
                .where(IngestJob.id == job_id)
                .values(status="failed")
            )

        async with db_module.async_session() as holder:
            await holder.execute(
                select(IngestJob.id).where(IngestJob.id == job_id).with_for_update()
            )
            async with db_module.async_session() as waiter:
                await waiter.execute(
                    text(f"SET LOCAL lock_timeout = {_TEST_BUDGET_MS}")
                )
                await waiter.rollback()
                blocked = asyncio.create_task(_unbounded_failure_update(waiter))
                done, _pending = await asyncio.wait(
                    {blocked}, timeout=(_TEST_BUDGET_MS / 1000) * 5
                )
                assert not done, (
                    "the UPDATE ended on its own, so the budget the rollback "
                    "discarded was still in force and this measures nothing"
                )
                await holder.rollback()
                await asyncio.wait_for(blocked, timeout=30)
                await waiter.rollback()


def test_the_shared_budget_is_ten_seconds() -> None:
    """Every holder of the job row self-caps below this, so a longer wait is stuck."""
    assert JOB_ERROR_WRITE_TIMEOUT_MS == 10_000
