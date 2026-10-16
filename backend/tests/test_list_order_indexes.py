"""The job list and dataset feed orderings are served by an index, not a sort."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql

from app.modules.admin.service import AdminService
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.jobs.models import IngestJob

_JOBS_DEF = (
    "CREATE INDEX ix_ingest_jobs_created_at_id ON catalog.ingest_jobs "
    "USING btree (created_at DESC, id)"
)
_RECORDS_DEF = (
    "CREATE INDEX idx_records_created_at_desc ON catalog.records "
    "USING btree (created_at DESC, id DESC)"
)
_RECORDS_PREVIOUS_DEF = (
    "CREATE INDEX idx_records_created_at_desc ON catalog.records "
    "USING btree (created_at)"
)
_SWAP_DEF = (
    "CREATE INDEX idx_records_created_at_desc_swap ON catalog.records "
    "USING btree (created_at DESC, id DESC)"
)


@pytest.mark.anyio
async def test_migrated_index_definitions(test_db_session) -> None:
    rows = await test_db_session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'catalog' "
            "AND indexname IN ('ix_ingest_jobs_created_at_id', "
            "'idx_records_created_at_desc', 'idx_records_created_at_desc_swap')"
        )
    )
    assert dict(rows.all()) == {
        "ix_ingest_jobs_created_at_id": _JOBS_DEF,
        "idx_records_created_at_desc": _RECORDS_DEF,
    }


def _literal_sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "stmt",
    [
        pytest.param(
            select(IngestJob.id)
            .order_by(*AdminService._job_ordering("created_at", "desc"))
            .offset(100)
            .limit(50),
            id="admin-job-list",
        ),
        pytest.param(
            select(Dataset.id)
            .join(Record, Dataset.record_id == Record.id)
            .order_by(Record.created_at.desc(), Record.id.desc())
            .offset(100)
            .limit(50),
            id="dataset-list-and-dcat",
        ),
    ],
)
async def test_default_order_needs_no_sort(test_db_session, stmt) -> None:
    """With sorts and sequential scans disabled, the plan still has no Sort node.

    The tables in a test database are tiny, so the planner is told to avoid
    both; it then sorts only when no index yields the requested order.
    """
    await test_db_session.execute(text("SET LOCAL enable_seqscan = off"))
    await test_db_session.execute(text("SET LOCAL enable_sort = off"))
    try:
        plan = await test_db_session.execute(
            text(f"EXPLAIN (COSTS OFF) {_literal_sql(stmt)}")
        )
        lines = [line for (line,) in plan.all()]
    finally:
        await test_db_session.rollback()
    assert not any("Sort" in line for line in lines), "\n".join(lines)
    assert any("Index" in line for line in lines), "\n".join(lines)


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0083_list_order_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0083", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeBind:
    def __init__(self, states: dict[str, tuple[str, bool] | None]) -> None:
        self._states = states

    def execute(self, _statement, params):
        state = self._states.get(params["index_name"])
        row = (
            None
            if state is None
            else SimpleNamespace(definition=state[0], usable=state[1])
        )
        return SimpleNamespace(one_or_none=lambda: row)


def _run(monkeypatch, step: str, states: dict) -> list[str]:
    return [
        sql
        for sql in _run_with_markers(monkeypatch, step, states)
        if sql != "<autocommit>"
    ]


def _run_with_markers(monkeypatch, step: str, states: dict) -> list[str]:
    """Executed SQL, with ``<autocommit>`` where an autocommit block opens."""
    migration = _load_migration()
    executed: list[str] = []

    class FakeContext:
        @contextmanager
        def autocommit_block(self):
            executed.append("<autocommit>")
            yield

    monkeypatch.setattr(migration.op, "get_context", lambda: FakeContext())
    monkeypatch.setattr(migration.op, "get_bind", lambda: _FakeBind(states))
    monkeypatch.setattr(migration.op, "execute", executed.append)
    getattr(migration, step)()
    return executed


_BUILD_JOBS = (
    'CREATE INDEX CONCURRENTLY "ix_ingest_jobs_created_at_id" '
    'ON catalog."ingest_jobs" (created_at DESC, id)'
)
_BUILD_SWAP = (
    'CREATE INDEX CONCURRENTLY "idx_records_created_at_desc_swap" '
    'ON catalog."records" (created_at DESC, id DESC)'
)
_DROP_RECORDS = (
    'DROP INDEX CONCURRENTLY IF EXISTS catalog."idx_records_created_at_desc"'
)
_DROP_SWAP = (
    'DROP INDEX CONCURRENTLY IF EXISTS catalog."idx_records_created_at_desc_swap"'
)
_RENAME = (
    'ALTER INDEX catalog."idx_records_created_at_desc_swap" '
    'RENAME TO "idx_records_created_at_desc"'
)


def test_upgrade_from_the_previous_revision(monkeypatch) -> None:
    executed = _run(
        monkeypatch,
        "upgrade",
        {"idx_records_created_at_desc": (_RECORDS_PREVIOUS_DEF, True)},
    )
    # The new records index exists before the old one is dropped.
    assert executed == [_BUILD_JOBS, _BUILD_SWAP, _DROP_RECORDS, _RENAME]


def test_upgrade_resumes_after_the_old_index_was_dropped(monkeypatch) -> None:
    executed = _run(
        monkeypatch,
        "upgrade",
        {
            "ix_ingest_jobs_created_at_id": (_JOBS_DEF, True),
            "idx_records_created_at_desc_swap": (_SWAP_DEF, True),
        },
    )
    assert executed == [_DROP_RECORDS, _RENAME]


def test_upgrade_rebuilds_invalid_indexes(monkeypatch) -> None:
    executed = _run(
        monkeypatch,
        "upgrade",
        {
            "ix_ingest_jobs_created_at_id": (_JOBS_DEF, False),
            "idx_records_created_at_desc": (_RECORDS_PREVIOUS_DEF, True),
            "idx_records_created_at_desc_swap": (_SWAP_DEF, False),
        },
    )
    assert executed == [
        'DROP INDEX CONCURRENTLY IF EXISTS catalog."ix_ingest_jobs_created_at_id"',
        _BUILD_JOBS,
        _DROP_SWAP,
        _BUILD_SWAP,
        _DROP_RECORDS,
        _RENAME,
    ]


def test_upgrade_of_a_finished_schema_only_clears_a_leftover_swap(monkeypatch) -> None:
    done = {
        "ix_ingest_jobs_created_at_id": (_JOBS_DEF, True),
        "idx_records_created_at_desc": (_RECORDS_DEF, True),
    }
    assert _run(monkeypatch, "upgrade", done) == []
    leftover = {**done, "idx_records_created_at_desc_swap": (_SWAP_DEF, False)}
    assert _run(monkeypatch, "upgrade", leftover) == [_DROP_SWAP]


def test_downgrade_runs_in_the_migration_transaction(monkeypatch) -> None:
    """A later revision's refusal must roll this downgrade back with its stamp."""
    executed = _run_with_markers(
        monkeypatch,
        "downgrade",
        {
            "ix_ingest_jobs_created_at_id": (_JOBS_DEF, True),
            "idx_records_created_at_desc": (_RECORDS_DEF, True),
        },
    )
    assert executed == [
        "SET LOCAL lock_timeout = '5s'",
        'DROP INDEX IF EXISTS catalog."ix_ingest_jobs_created_at_id"',
        'DROP INDEX IF EXISTS catalog."idx_records_created_at_desc_swap"',
        'DROP INDEX IF EXISTS catalog."idx_records_created_at_desc"',
        'CREATE INDEX "idx_records_created_at_desc" ON catalog."records" (created_at)',
    ]
