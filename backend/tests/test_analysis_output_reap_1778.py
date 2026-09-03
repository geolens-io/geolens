"""Codebase audit 2026-08-30, orphaned analysis output (tracked in #1778).

A hard worker kill after the materialize commit left ``data.<out_table>`` and
its GIST index behind with no catalog row: the name was generated inside the
worker, nothing durable carried it, and every DROP of it lives in a handler a
SIGKILL never runs.
"""

import ast
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def _source(rel: str) -> str:
    return (APP / rel).read_text()


class TestUnadoptedAnalysisOutput:
    def test_the_generated_name_is_persisted_next_to_the_collision_warning(
        self,
    ) -> None:
        """Written unconditionally, in the transaction that creates the table.

        The two facts become durable together, so a job row that names a table
        is exactly a job row whose table exists.
        """
        source = _source("processing/analysis/tasks.py")
        assert "ANALYSIS_OUTPUT_TABLE_FIELD: out_table," in source
        lines = source.splitlines()
        generated = next(
            i
            for i, line in enumerate(lines)
            if "out_table, collision_warning = await generate_table_name(" in line
        )
        persisted = next(
            i
            for i, line in enumerate(lines)
            if "ANALYSIS_OUTPUT_TABLE_FIELD: out_table," in line
        )
        commit = next(
            i
            for i, line in enumerate(lines)
            if i > persisted and "await session.commit()" in line
        )
        assert generated < persisted < commit

    @pytest.mark.parametrize(
        "metadata,expected",
        [
            (None, None),
            ({}, None),
            ({"analysis_out_table": ""}, None),
            ({"analysis_out_table": 7}, None),
            ({"analysis_out_table": "parcels_buffered"}, "parcels_buffered"),
        ],
    )
    def test_the_name_is_read_back_off_the_job_row(self, metadata, expected) -> None:
        from app.platform.jobs.sweep import unadopted_analysis_table_from_metadata

        assert unadopted_analysis_table_from_metadata(metadata) == expected

    @pytest.mark.asyncio
    async def test_an_unadopted_table_is_dropped(self) -> None:
        from app.processing.analysis.tasks import drop_unadopted_analysis_output

        session = AsyncMock()
        probe = MagicMock()
        probe.first.return_value = None
        session.execute = AsyncMock(return_value=probe)

        await drop_unadopted_analysis_output(
            session, out_table="parcels_buffered", schema="data", job_id="j"
        )

        statements = [str(call.args[0]) for call in session.execute.await_args_list]
        assert any(
            'DROP TABLE IF EXISTS "data"."parcels_buffered"' in stmt
            for stmt in statements
        )

    @pytest.mark.asyncio
    async def test_an_adopted_table_is_left_alone(self) -> None:
        from app.processing.analysis.tasks import drop_unadopted_analysis_output

        session = AsyncMock()
        probe = MagicMock()
        probe.first.return_value = (1,)
        session.execute = AsyncMock(return_value=probe)

        await drop_unadopted_analysis_output(
            session, out_table="parcels_buffered", schema="data", job_id="j"
        )

        statements = [str(call.args[0]) for call in session.execute.await_args_list]
        assert not any("DROP TABLE" in stmt for stmt in statements)

    @pytest.mark.asyncio
    async def test_a_name_that_is_not_an_identifier_never_reaches_ddl(self) -> None:
        """The name arrives through JSONB and is interpolated into DDL."""
        from app.processing.analysis.tasks import drop_unadopted_analysis_output

        session = AsyncMock()
        session.execute = AsyncMock()

        await drop_unadopted_analysis_output(
            session,
            out_table='parcels"; DROP TABLE catalog.datasets; --',
            schema="data",
            job_id="j",
        )

        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fail_stale_jobs_carries_the_table_out_of_a_running_row(self) -> None:
        from app.platform.jobs.sweep import fail_stale_jobs

        mock_db = _mock_db_for_fail_stale(
            running_rows=[
                (uuid.uuid4(), {"analysis_out_table": "parcels_buffered"}, None),
            ]
        )
        reap = AsyncMock()
        with patch("app.platform.jobs.sweep._reap_unadopted_analysis_outputs", reap):
            outcome = await fail_stale_jobs(mock_db, detailed=True)

        assert outcome._unadopted_analysis_tables == ("parcels_buffered",)
        reap.assert_awaited_once_with(("parcels_buffered",))


class TestOnlyASettledArtifactLosesItsRecord:
    """fix(#1778 codex r6): "it did not raise" is not "it is done".

    `drop_unadopted_analysis_output` catches its own probe and DROP failures,
    so it returned the same `None` whether it dropped the table or failed to.
    The sweep read that as success, `_clear_settled_artifact_records` stripped
    the table's last durable name off the job row, the retention purge then
    deleted the row, and the table was orphaned for good: the exact leak that
    function exists to prevent, reintroduced by the function itself.

    The rule is now stated once per arm and keyed on a NAMED outcome rather
    than on control flow, because the storage arm was correct only by where a
    statement sat inside a try block.
    """

    TABLE = "parcels_buffered"
    KEY = "rasters/ds/attempts/a/abc/source.cog.tif"

    @staticmethod
    def _session_double(*, adopted, drop_raises: bool = False):
        """A session whose probe answers `adopted` and whose DROP may raise."""
        session = AsyncMock()

        async def _execute(stmt, *_a, **_kw):
            sql = str(stmt)
            if "DROP TABLE" in sql:
                if drop_raises:
                    raise RuntimeError("lock timeout")
                return MagicMock()
            if isinstance(adopted, Exception):
                raise adopted
            probe = MagicMock()
            probe.first.return_value = (1,) if adopted else None
            return probe

        session.execute = AsyncMock(side_effect=_execute)
        return session

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "adopted,drop_raises,expected",
        [
            (False, False, "dropped"),
            (True, False, "adopted"),
            (False, True, "failed"),
            (RuntimeError("catalog unreadable"), False, "failed"),
        ],
    )
    async def test_the_helper_reports_what_it_established(
        self, adopted, drop_raises, expected
    ) -> None:
        from app.processing.analysis.tasks import drop_unadopted_analysis_output

        outcome = await drop_unadopted_analysis_output(
            self._session_double(adopted=adopted, drop_raises=drop_raises),
            out_table=self.TABLE,
            schema="data",
            job_id="j",
        )

        assert outcome == expected

    @pytest.mark.asyncio
    async def test_a_name_that_is_not_an_identifier_is_final(self) -> None:
        """No retry can change the string, so keeping the record would pin
        the job row forever."""
        from app.processing.analysis.tasks import (
            ANALYSIS_OUTPUT_FINAL_OUTCOMES,
            drop_unadopted_analysis_output,
        )

        session = AsyncMock()
        outcome = await drop_unadopted_analysis_output(
            session, out_table='x"; DROP TABLE y; --', schema="data", job_id="j"
        )

        assert outcome == "invalid"
        assert outcome in ANALYSIS_OUTPUT_FINAL_OUTCOMES
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "outcome,settles",
        [
            ("dropped", True),
            ("adopted", True),
            ("invalid", True),
            ("skipped", True),
            ("failed", False),
        ],
    )
    async def test_the_analysis_arm_settles_only_on_a_final_outcome(
        self, outcome: str, settles: bool
    ) -> None:
        from app.platform.jobs.sweep import _reap_unadopted_analysis_outputs

        clear = AsyncMock()
        with (
            patch(
                "app.processing.analysis.tasks.drop_unadopted_analysis_output",
                AsyncMock(return_value=outcome),
            ),
            patch("app.platform.jobs.sweep._clear_settled_artifact_records", clear),
        ):
            await _reap_unadopted_analysis_outputs((self.TABLE,))

        clear.assert_awaited_once_with(
            analysis_tables={self.TABLE} if settles else set()
        )

    @pytest.mark.asyncio
    async def test_a_drop_that_raises_outright_also_keeps_the_record(self) -> None:
        """The callee catches its own failures; this covers one it does not."""
        from app.platform.jobs.sweep import _reap_unadopted_analysis_outputs

        clear = AsyncMock()
        with (
            patch(
                "app.processing.analysis.tasks.drop_unadopted_analysis_output",
                AsyncMock(side_effect=RuntimeError("connection reset")),
            ),
            patch("app.platform.jobs.sweep._clear_settled_artifact_records", clear),
        ):
            await _reap_unadopted_analysis_outputs((self.TABLE,))

        clear.assert_awaited_once_with(analysis_tables=set())

    @pytest.mark.anyio
    async def test_a_failed_drop_leaves_the_job_row_naming_the_table(
        self, test_db_session
    ) -> None:
        """The pin, end to end against real Postgres.

        A DROP that raises must leave `analysis_out_table` on the row, because
        that name is the only remaining pointer to the orphan and the retention
        purge exempts rows that still carry one.
        """
        from sqlalchemy import select

        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.sweep import _reap_unadopted_analysis_outputs

        job = IngestJob(
            status="failed",
            file_path="",
            user_metadata={"analysis_out_table": self.TABLE},
        )
        test_db_session.add(job)
        await test_db_session.flush()
        job_id = job.id
        await test_db_session.commit()

        with patch(
            "app.processing.analysis.tasks.drop_unadopted_analysis_output",
            AsyncMock(return_value="failed"),
        ):
            await _reap_unadopted_analysis_outputs((self.TABLE,))

        test_db_session.expire_all()
        row = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == job_id)
            )
        ).scalar_one()
        assert row.user_metadata.get("analysis_out_table") == self.TABLE, (
            "a failed drop must leave the table's last durable name on the row"
        )

    @pytest.mark.asyncio
    async def test_a_delete_that_raises_leaves_the_key_on_the_record(self) -> None:
        """The storage arm's half of the same rule."""
        from app.platform.jobs.sweep import reap_unpublished_storage_keys

        clear = AsyncMock()
        storage = MagicMock()
        storage.delete = AsyncMock(side_effect=RuntimeError("s3 unavailable"))
        with (
            patch("app.platform.storage.get_storage", return_value=storage),
            patch(
                "app.platform.jobs.sweep._live_referenced_storage_keys",
                AsyncMock(return_value=set()),
            ),
            patch("app.platform.jobs.sweep._clear_settled_artifact_records", clear),
        ):
            reaped, skipped, failures = await reap_unpublished_storage_keys((self.KEY,))

        assert (reaped, skipped, failures) == (0, 0, 1)
        clear.assert_awaited_once_with(storage_keys=set())

    def test_every_arm_that_clears_a_record_keys_off_a_named_outcome(self) -> None:
        """Enumerated, so a third arm cannot quietly repeat this.

        Codex charges one round per sibling site, and the two arms here reached
        the same bug from opposite directions: the analysis one by trusting a
        callee that swallowed, the storage one by relying on where a statement
        sat in a try block. Any future caller of the clearing helper has to
        appear in this list and consult a FINAL-outcome set.
        """
        source = (APP / "platform/jobs/sweep.py").read_text()
        tree = ast.parse(source)
        callers: set[str] = set()
        stack: list[str] = []

        def walk(node: ast.AST) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    stack.append(child.name)
                    walk(child)
                    stack.pop()
                    continue
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "_clear_settled_artifact_records"
                    and stack
                ):
                    callers.add(stack[-1])
                walk(child)

        walk(tree)
        assert callers == {
            "reap_unpublished_storage_keys",
            "_reap_unadopted_analysis_outputs",
        }, callers

        for name, vocabulary in (
            ("reap_unpublished_storage_keys", "STORAGE_KEY_FINAL_OUTCOMES"),
            ("_reap_unadopted_analysis_outputs", "ANALYSIS_OUTPUT_FINAL_OUTCOMES"),
        ):
            fn = next(
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name
            )
            assert vocabulary in ast.unparse(fn), (
                f"{name} clears records without consulting {vocabulary}"
            )


def _mock_db_for_fail_stale(*, running_rows: list) -> AsyncMock:
    """A session double for ``fail_stale_jobs`` with real running-row metadata.

    The peer helper in ``test_vrt_stale_sweep_gap002`` hands every job row a
    ``None`` metadata blob, which is exactly the column these findings read, so
    this states the same execute() ordering with the rows filled in. Ordering,
    top to bottom: unbound pending UPDATE, bound pending UPDATE, running
    UPDATE, childless fan-out UPDATE, VRT generation UPDATE, two RasterAsset
    UPDATEs, two refresh-run UPDATEs, the retention purge DELETE, and the
    post-expiry presigned SELECT.
    """
    results = []

    unbound = MagicMock()
    unbound.all.return_value = []
    results.append(unbound)

    bound = MagicMock()
    bound.all.return_value = []
    results.append(bound)

    running = MagicMock()
    running.all.return_value = list(running_rows)
    results.append(running)

    fanout = MagicMock()
    fanout.scalars.return_value = []
    results.append(fanout)

    generations = MagicMock()
    generations.all.return_value = []
    results.append(generations)

    for _ in range(4):
        result = MagicMock()
        result.scalars.return_value = []
        results.append(result)

    # fix(#1778 codex r5): the purge reads its exempted rows first - terminal
    # rows that still name an unreaped artifact, which it refuses to delete so
    # the record survives for the next sweep to retry. None here.
    retained = MagicMock()
    retained.scalars.return_value = []
    results.append(retained)

    purge = MagicMock()
    purge.all.return_value = []
    results.append(purge)

    post_expiry = MagicMock()
    post_expiry.all.return_value = []
    results.append(post_expiry)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=results)
    mock_db.commit = AsyncMock()
    return mock_db
