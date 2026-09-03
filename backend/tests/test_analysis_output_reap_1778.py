"""Codebase audit 2026-08-30, orphaned analysis output (tracked in #1778).

A hard worker kill after the materialize commit left ``data.<out_table>`` and
its GIST index behind with no catalog row: the name was generated inside the
worker, nothing durable carried it, and every DROP of it lives in a handler a
SIGKILL never runs.
"""

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
