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
        assert "job.user_metadata = append_analysis_output_record(" in source
        lines = source.splitlines()
        # fix(#1778 codex r7/r10): the name is resolved (scoped by job AND
        # attempt, collision-checked as scoped) after `generate_table_name`
        # chooses its readable half, so the assignment this ordering hangs
        # off is the resolving call.
        generated = next(
            i
            for i, line in enumerate(lines)
            if "out_table = await resolve_analysis_output_table(" in line
        )
        persisted = next(
            i
            for i, line in enumerate(lines)
            if "job.user_metadata = append_analysis_output_record(" in line
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
            (None, ()),
            ({}, ()),
            ({"analysis_out_table": ""}, ()),
            ({"analysis_out_table": 7}, ()),
            # fix(#1778 codex r10): a plain string is what a row written
            # before this commit still holds, and is read as a one-element
            # list so its pointer survives.
            ({"analysis_out_table": "parcels_buffered"}, ("parcels_buffered",)),
            (
                {"analysis_out_table": ["parcels_buffered", "parcels_buffered_2"]},
                ("parcels_buffered", "parcels_buffered_2"),
            ),
            # A non-string entry in the list is dropped, not raised on --
            # this reads a schemaless JSONB blob.
            ({"analysis_out_table": ["a", 7, "", "b"]}, ("a", "b")),
        ],
    )
    def test_the_names_are_read_back_off_the_job_row(self, metadata, expected) -> None:
        from app.platform.jobs.sweep import unadopted_analysis_tables_from_metadata

        assert unadopted_analysis_tables_from_metadata(metadata) == expected

    @pytest.mark.asyncio
    async def test_an_unadopted_table_is_dropped(self) -> None:
        from app.processing.analysis.tasks import drop_unadopted_analysis_output

        job_uuid = uuid.uuid4()
        owned = analysis_output_table_name_for_test("parcels_buffered", job_uuid)
        session = AsyncMock()
        probe = MagicMock()
        probe.first.return_value = None
        session.execute = AsyncMock(return_value=probe)

        await drop_unadopted_analysis_output(
            session,
            out_table=owned,
            schema="data",
            job_id="j",
            owner_job_uuid=job_uuid,
        )

        statements = [str(call.args[0]) for call in session.execute.await_args_list]
        assert any(
            f'DROP TABLE IF EXISTS "data"."{owned}"' in stmt for stmt in statements
        )

    @pytest.mark.asyncio
    async def test_an_adopted_table_is_left_alone(self) -> None:
        from app.processing.analysis.tasks import drop_unadopted_analysis_output

        job_uuid = uuid.uuid4()
        session = AsyncMock()
        probe = MagicMock()
        probe.first.return_value = (1,)
        session.execute = AsyncMock(return_value=probe)

        await drop_unadopted_analysis_output(
            session,
            out_table=analysis_output_table_name_for_test("parcels_buffered", job_uuid),
            schema="data",
            job_id="j",
            owner_job_uuid=job_uuid,
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
            owner_job_uuid=uuid.uuid4(),
        )

        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fail_stale_jobs_carries_the_table_out_of_a_running_row(self) -> None:
        """fix(#1778 codex r10): the running-row transition no longer collects
        the name directly -- that moved into the unconditional
        artifact-carrying SELECT that runs after the retention block (see
        that query's own docstring in sweep.py). Against real Postgres it
        runs inside the same uncommitted transaction as the UPDATE above it
        and sees the row's new status, so the split changes nothing about
        same-pass reaping; the double routes the fixture through the query
        that answers it now.
        """
        from app.platform.jobs.sweep import fail_stale_jobs

        job_uuid = uuid.uuid4()
        mock_db = _mock_db_for_fail_stale(
            running_rows=[(job_uuid, None, None)],
            artifact_rows=[
                (job_uuid, {"analysis_out_table": "parcels_buffered"}),
            ],
        )
        reap = AsyncMock()
        with patch("app.platform.jobs.sweep._reap_unadopted_analysis_outputs", reap):
            outcome = await fail_stale_jobs(mock_db, detailed=True)

        # fix(#1778 codex r7): (job, table), so the drop can verify ownership.
        assert outcome._unadopted_analysis_tables == ((job_uuid, "parcels_buffered"),)
        reap.assert_awaited_once_with(((job_uuid, "parcels_buffered"),))


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

        job_uuid = uuid.uuid4()
        outcome = await drop_unadopted_analysis_output(
            self._session_double(adopted=adopted, drop_raises=drop_raises),
            out_table=analysis_output_table_name_for_test(self.TABLE, job_uuid),
            schema="data",
            job_id="j",
            owner_job_uuid=job_uuid,
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
            session,
            out_table='x"; DROP TABLE y; --',
            schema="data",
            job_id="j",
            owner_job_uuid=uuid.uuid4(),
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
        job_uuid = uuid.uuid4()
        with (
            patch(
                "app.processing.analysis.tasks.drop_unadopted_analysis_output",
                AsyncMock(return_value=outcome),
            ),
            patch("app.platform.jobs.sweep._clear_settled_artifact_records", clear),
        ):
            await _reap_unadopted_analysis_outputs(((job_uuid, self.TABLE),))

        # fix(#1778 codex r10): settled by VALUE, not by owning job id -- the
        # record accumulates across attempts now, so clearing "the field for
        # this job" would forget a name this pass never answered for.
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
            await _reap_unadopted_analysis_outputs(((uuid.uuid4(), self.TABLE),))

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
            await _reap_unadopted_analysis_outputs(((job_id, self.TABLE),))

        test_db_session.expire_all()
        row = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == job_id)
            )
        ).scalar_one()
        assert row.user_metadata.get("analysis_out_table") == self.TABLE, (
            "a failed drop must leave the table's last durable name on the row"
        )

    @pytest.mark.anyio
    async def test_a_legacy_string_shaped_record_clears_on_settle(
        self, test_db_session
    ) -> None:
        """fix(#1778 codex r10): a pre-PR row still holds a plain JSONB
        string, not a list. `unadopted_analysis_tables_from_metadata` already
        reads it as a one-element list, so the table gets dropped either way
        -- but the clearing SQL originally kept its `jsonb_typeof(...) =
        'array'` guard, which never matched a string, so a legacy row's
        pointer survived a successful reap forever and the retention purge
        could never take the row. The clearing SQL now has a matching arm for
        the string shape."""
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
            AsyncMock(return_value="dropped"),
        ):
            await _reap_unadopted_analysis_outputs(((job_id, self.TABLE),))

        test_db_session.expire_all()
        row = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == job_id)
            )
        ).scalar_one()
        assert "analysis_out_table" not in (row.user_metadata or {}), (
            "a settled legacy string-shaped record must clear so the row can be purged"
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


def analysis_output_table_name_for_test(base: str, job_uuid, attempt_uuid=None) -> str:
    from app.processing.analysis.tasks import analysis_output_table_name

    return analysis_output_table_name(base, job_uuid, attempt_uuid or uuid.uuid4())


def _output_name_for(job_uuid, attempt_uuid=None) -> str:
    from app.processing.analysis.tasks import analysis_output_table_name

    return analysis_output_table_name(
        "parcels_buffered", job_uuid, attempt_uuid or uuid.uuid4()
    )


class TestAnalysisOutputNamesAreJobScoped:
    """fix(#1778 codex r7): two jobs could hold one physical table name.

    An old failed analysis keeps `analysis_out_table` on its row until the reap
    succeeds. Once its table is gone the name is free again -- nothing retires
    it, because an unregistered output never became a dataset -- so a new
    analysis with the same title was handed the same name. Let the new job
    commit its CTAS between the sweep's adoption probe and its DROP and the
    sweep destroyed the NEW job's table, and the name-keyed record clearing
    then erased the new job's recovery pointer along with the old one's.

    fix(#1778 codex r10): job scoping alone left one gap open -- `/jobs/{id}/
    retry` keeps `IngestJob.id` and mints a new attempt token, so every retry
    of one job derived the SAME name. A stale sweep could capture attempt 1's
    name, settle the job `failed`, and then probe and drop while attempt 2
    was creating that same name, and the ownership check passed because the
    name really was this job's. The scope now carries the attempt too.
    """

    def test_two_jobs_never_derive_the_same_name(self) -> None:
        from app.processing.analysis.tasks import analysis_output_table_name

        first = analysis_output_table_name(
            "parcels_buffered", uuid.uuid4(), uuid.uuid4()
        )
        second = analysis_output_table_name(
            "parcels_buffered", uuid.uuid4(), uuid.uuid4()
        )
        assert first != second
        assert first.startswith("parcels_buffered_")
        assert second.startswith("parcels_buffered_")

    def test_two_attempts_of_one_job_never_derive_the_same_name(self) -> None:
        """fix(#1778 codex r10): the gap job scoping alone left open."""
        from app.processing.analysis.tasks import analysis_output_table_name

        job_uuid = uuid.uuid4()
        first = analysis_output_table_name("parcels_buffered", job_uuid, uuid.uuid4())
        second = analysis_output_table_name("parcels_buffered", job_uuid, uuid.uuid4())
        assert first != second

    def test_one_attempt_derives_a_stable_name(self) -> None:
        """The same (job, attempt) pair is idempotent -- what a retry of a
        retry that reuses the same attempt token would need."""
        from app.processing.analysis.tasks import analysis_output_table_name

        job_uuid = uuid.uuid4()
        attempt_uuid = uuid.uuid4()
        assert analysis_output_table_name(
            "x", job_uuid, attempt_uuid
        ) == analysis_output_table_name("x", job_uuid, attempt_uuid)

    def test_the_name_stays_inside_the_identifier_limit(self) -> None:
        from app.processing.analysis.tasks import (
            _ANALYSIS_TABLE_NAME_RE,
            analysis_output_table_name,
        )

        name = analysis_output_table_name("a" * 60, uuid.uuid4(), uuid.uuid4())
        assert len(name) <= 63
        assert _ANALYSIS_TABLE_NAME_RE.match(name)

    def test_the_materialize_path_scopes_the_generated_name(self) -> None:
        """`generate_table_name` still chooses the readable half; the scoped
        collision walk happens separately, in `resolve_analysis_output_table`
        (fix(#1778 codex r10))."""
        source = _source("processing/analysis/tasks.py")
        assert "out_table = await resolve_analysis_output_table(" in source
        assert "out_table, collision_warning = await generate_table_name" not in source

    @pytest.mark.asyncio
    async def test_the_sweep_refuses_a_table_the_job_did_not_create(self) -> None:
        """The ownership gate, stated as its own unit.

        The name says which job created it, so this needs no catalog read, no
        comment and no lock: a table the check passes was created by this job
        or by nothing at all.
        """
        from app.processing.analysis.tasks import drop_unadopted_analysis_output

        session = AsyncMock()
        outcome = await drop_unadopted_analysis_output(
            session,
            out_table=_output_name_for(uuid.uuid4()),
            schema="data",
            job_id="j",
            owner_job_uuid=uuid.uuid4(),
        )

        assert outcome == "invalid"
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_sweep_accepts_the_table_the_job_did_create(self) -> None:
        from app.processing.analysis.tasks import drop_unadopted_analysis_output

        job_uuid = uuid.uuid4()
        session = AsyncMock()
        probe = MagicMock()
        probe.first.return_value = None
        session.execute = AsyncMock(return_value=probe)

        outcome = await drop_unadopted_analysis_output(
            session,
            out_table=_output_name_for(job_uuid),
            schema="data",
            job_id="j",
            owner_job_uuid=job_uuid,
        )

        assert outcome == "dropped"

    @pytest.mark.anyio
    async def test_a_new_jobs_table_and_record_survive_the_old_jobs_reap(
        self, test_db_session
    ) -> None:
        """The interleaving, against real Postgres.

        The old job row names its own table, which is already gone -- that is
        what used to free the name. A new job creates its table and records it.
        The sweep reaps the old row. The new job's table and its recovery
        pointer both survive, and the old row's record clears so its row can
        finally be purged.
        """
        from sqlalchemy import select, text

        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.sweep import _reap_unadopted_analysis_outputs
        from app.processing.analysis.tasks import analysis_output_table_name

        base = f"parcels_{uuid.uuid4().hex[:6]}"
        old_job = IngestJob(status="failed", file_path="")
        new_job = IngestJob(status="failed", file_path="")
        test_db_session.add_all([old_job, new_job])
        await test_db_session.flush()
        old_id, new_id = old_job.id, new_job.id
        old_table = analysis_output_table_name(base, old_id, old_job.attempt_id)
        new_table = analysis_output_table_name(base, new_id, new_job.attempt_id)
        assert old_table != new_table, "the whole point of the scope"
        # List-shaped, the current writer's shape (fix(#1778 codex r10)).
        old_job.user_metadata = {"analysis_out_table": [old_table]}
        new_job.user_metadata = {"analysis_out_table": [new_table]}
        # Only the NEW job's table exists: the old one's was already dropped,
        # which is what freed the name in the first place.
        await test_db_session.execute(
            text(f'CREATE TABLE data."{new_table}" (marker integer)')
        )
        await test_db_session.commit()

        try:
            await _reap_unadopted_analysis_outputs(((old_id, old_table),))

            still_there = (
                await test_db_session.execute(
                    text(
                        "SELECT 1 FROM pg_catalog.pg_class c"
                        " JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace"
                        " WHERE n.nspname = 'data' AND c.relname = :t"
                    ).bindparams(t=new_table)
                )
            ).first()
            assert still_there, "the sweep dropped the new job's table"

            test_db_session.expire_all()
            rows = {
                row.id: row.user_metadata
                for row in (
                    await test_db_session.execute(
                        select(IngestJob).where(IngestJob.id.in_([old_id, new_id]))
                    )
                ).scalars()
            }
            assert rows[new_id].get("analysis_out_table") == [new_table], (
                "the sweep erased the new job's recovery pointer"
            )
            assert "analysis_out_table" not in rows[old_id], (
                "the old job's record must clear so its row can be purged"
            )
        finally:
            await test_db_session.execute(
                text(f'DROP TABLE IF EXISTS data."{new_table}"')
            )
            await test_db_session.commit()


class TestAttemptScopingPins:
    """fix(#1778 codex r10): the three scenarios named in the round-10
    review, each pinned against real Postgres.
    """

    @pytest.mark.anyio
    async def test_a_stale_sweep_drops_only_the_dead_attempts_table(
        self, test_db_session
    ) -> None:
        """(a) attempt 1's table survives a crash and a stale sweep captures
        its name; by the time the sweep's drop runs, attempt 2 (the retry --
        same job row, a NEW attempt token) has already created its own table
        and appended its name to the same field. The sweep must drop only
        attempt 1's table and leave attempt 2's recovery pointer alone."""
        from sqlalchemy import select, text

        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.sweep import _reap_unadopted_analysis_outputs
        from app.processing.analysis.tasks import (
            analysis_output_table_name,
            append_analysis_output_record,
        )

        job = IngestJob(status="failed", file_path="")
        test_db_session.add(job)
        await test_db_session.flush()
        attempt_1 = job.attempt_id
        base = f"parcels_{uuid.uuid4().hex[:6]}"
        table_1 = analysis_output_table_name(base, job.id, attempt_1)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{table_1}" (marker integer)')
        )

        # The retry: same job row, a new attempt, its own table, appended --
        # never overwriting -- onto the same field (fix(#1778 codex r10)).
        attempt_2 = uuid.uuid4()
        job.attempt_id = attempt_2
        table_2 = analysis_output_table_name(base, job.id, attempt_2)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{table_2}" (marker integer)')
        )
        job.user_metadata = append_analysis_output_record(None, table_1)
        job.user_metadata = append_analysis_output_record(job.user_metadata, table_2)
        await test_db_session.commit()
        job_id = job.id

        try:
            # The stale sweep captured attempt 1's name before the retry
            # committed; it reaps only the (job, table) pair it was handed.
            await _reap_unadopted_analysis_outputs(((job_id, table_1),))

            table_1_gone = (
                await test_db_session.execute(
                    text("SELECT to_regclass(:ref)").bindparams(ref=f"data.{table_1}")
                )
            ).scalar_one()
            assert table_1_gone is None, "attempt 1's dead table must be dropped"

            table_2_survives = (
                await test_db_session.execute(
                    text("SELECT to_regclass(:ref)").bindparams(ref=f"data.{table_2}")
                )
            ).scalar_one()
            assert table_2_survives is not None, (
                "the sweep dropped the RETRY's live table"
            )

            test_db_session.expire_all()
            row = (
                await test_db_session.execute(
                    select(IngestJob).where(IngestJob.id == job_id)
                )
            ).scalar_one()
            assert row.user_metadata.get("analysis_out_table") == [table_2], (
                "attempt 2's recovery pointer must survive the reap of attempt 1's"
            )
        finally:
            await test_db_session.execute(
                text(f'DROP TABLE IF EXISTS data."{table_2}"')
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_carried_over_keys_reap_on_the_datasets_latest_complete_job(
        self, test_db_session
    ) -> None:
        """(b) the OLD collection ran only inside the retention purge block,
        gated by the same `purge_clauses` that exempt a dataset's
        latest-complete job -- so a successful retry that carries a dead
        attempt's storage key forward on its OWN row (record_unpublished_
        storage_keys preserves it; nothing settles it just because the retry
        succeeded) was never looked at, because that row is by definition the
        one the exemption protects. The artifact-carrying SELECT now runs
        unconditionally, with no purge_clauses at all, so it sees the row
        regardless of whether it is the dataset's latest complete job."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.platform.jobs.models import IngestJob
        from app.platform.jobs.router import fail_stale_jobs
        from tests.factories import create_dataset, get_user_id

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(test_db_session, created_by=admin_id)

        carried_key = f"rasters/{ds.id}/attempts/dead/abc/source.cog.tif"
        job = IngestJob(
            dataset_id=ds.id,
            status="complete",
            file_path="",
            user_metadata={"unpublished_storage_keys": [carried_key]},
        )
        test_db_session.add(job)
        await test_db_session.commit()

        storage = MagicMock()
        storage.delete = AsyncMock()
        with patch("app.platform.storage.get_storage", return_value=storage):
            outcome = await fail_stale_jobs(test_db_session, detailed=True)

        assert carried_key in outcome._unpublished_storage_keys, (
            "the dataset's own latest-complete job must still be checked "
            "for a carried-over key from a dead attempt"
        )
        storage.delete.assert_awaited_once_with(carried_key)

    @pytest.mark.anyio
    async def test_the_same_attempt_delivered_twice_self_heals_to_a_suffix(
        self, test_db_session
    ) -> None:
        """(c) resolve_analysis_output_table's own docstring: attempt scoping
        makes a retry colliding with itself rare but not unreachable -- the
        SAME attempt can be delivered twice (redelivery after an ack the
        first delivery never got to send). `generate_table_name`'s own `_N`
        walk only ever probes the UNSCOPED base, so both deliveries are
        handed the same base and scope onto the same occupied name.
        `resolve_analysis_output_table` collision-checks the SCOPED candidate
        directly and self-heals to a suffix instead of failing at CREATE
        TABLE."""
        from sqlalchemy import text

        from app.processing.analysis.tasks import (
            analysis_output_table_name,
            resolve_analysis_output_table,
        )

        job_id = uuid.uuid4()
        attempt_id = uuid.uuid4()
        base = f"parcels_{uuid.uuid4().hex[:6]}"

        # The first delivery's table, already committed.
        first_delivery_table = analysis_output_table_name(base, job_id, attempt_id)
        await test_db_session.execute(
            text(f'CREATE TABLE data."{first_delivery_table}" (marker integer)')
        )
        await test_db_session.commit()

        try:
            resolved = await resolve_analysis_output_table(
                test_db_session,
                base=base,
                job_uuid=job_id,
                attempt_uuid=attempt_id,
                schema="data",
            )

            assert resolved != first_delivery_table
            assert resolved == analysis_output_table_name(
                f"{base}_2", job_id, attempt_id
            )
        finally:
            await test_db_session.execute(
                text(f'DROP TABLE IF EXISTS data."{first_delivery_table}"')
            )
            await test_db_session.commit()


def _mock_db_for_fail_stale(
    *, running_rows: list, artifact_rows: list | None = None
) -> AsyncMock:
    """A session double for ``fail_stale_jobs`` with real running-row metadata.

    The peer helper in ``test_vrt_stale_sweep_gap002`` hands every job row a
    ``None`` metadata blob, which is exactly the column these findings read, so
    this states the same execute() ordering with the rows filled in. Ordering,
    top to bottom: unbound pending UPDATE, bound pending UPDATE, running
    UPDATE, childless fan-out UPDATE, VRT generation UPDATE, two RasterAsset
    UPDATEs, two refresh-run UPDATEs, the retention purge DELETE, the
    artifact-carrying SELECT (fix(#1778 codex r10): unconditional, outside the
    retention block -- see that query's own docstring), and the post-expiry
    presigned SELECT.
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

    # fix(#1778 codex r10): the artifact-carrying SELECT, unconditional and
    # run after the retention block. (id, user_metadata) pairs.
    artifact = MagicMock()
    artifact.all.return_value = list(artifact_rows or [])
    results.append(artifact)

    post_expiry = MagicMock()
    post_expiry.all.return_value = []
    results.append(post_expiry)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=results)
    mock_db.commit = AsyncMock()
    return mock_db
