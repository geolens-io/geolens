"""Backend audit 2026-09-04 P1-1, tracked in #1847.

The feature-edit metadata refresh took ``catalog.records`` FOR UPDATE and left
``catalog.datasets`` to the flush. ``refresh_postgis`` phase 3 takes the
datasets row FOR UPDATE first and writes the record row inside that same
transaction, so an ordinary feature edit during a refresh was an ABBA cycle:
PostgreSQL aborted one side with 40P01 after ``deadlock_timeout``, and because
the refresh call sat outside the write handlers' ``except DBAPIError`` the abort
surfaced as a generic 503 with the edit lost.

The concurrency tests here assert on LOCK STATE, never on elapsed time. The
barrier is ``pg_stat_activity.wait_event_type``, and whether a lock is held is
settled by a third session's ``FOR UPDATE NOWAIT``, which either raises 55P03
or does not.

The DB-backed tests require the Docker test database.
"""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import is_lock_conflict
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.features import service as features_service
from app.modules.catalog.features.router import _feature_write_db_error

from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

# Seeded rows span (-74.00, 40.70) .. (-73.90, 40.80), so this envelope is
# strictly inside the stored extent and the incremental fast path applies.
INSIDE_BOUNDS = (-73.96, 40.74, -73.96, 40.74)

# The barrier polls until the backend under test is parked on a lock. Bounded
# only so a wait that will never end fails with a readable message instead of
# hanging the suite; the bound is not an assertion about how long anything took.
_BARRIER_POLLS = 600
_BARRIER_INTERVAL_SECONDS = 0.01


async def _seed_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """A point layer with a POLYGON stored extent, seeded the honest way."""
    table_name = f"test_lo_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "gid SERIAL PRIMARY KEY, "
            "geom geometry(Geometry, 4326), "
            "geom_4326 geometry(Geometry, 4326), "
            "name TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))
    for lng, lat in ((-74.00, 40.70), (-73.90, 40.80), (-73.95, 40.75)):
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326, name) VALUES ("
                "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), "
                "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 'seed')"
            ).bindparams(lng=lng, lat=lat)
        )

    record = Record(
        title=f"Lock order {table_name}",
        summary="Fixture layer",
        theme_category=["test"],
        visibility="private",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="POINT",
        feature_count=0,
        column_info=[{"name": "name", "type": "text"}],
        source_format="geojson",
    )
    session.add(dataset)
    await session.flush()
    await features_service.refresh_dataset_metadata(session, dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
async def locked_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _seed_dataset(test_db_session, created_by=admin_id)
    yield dataset
    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
    )
    await test_db_session.commit()


async def _await_lock_wait(probe, pid: int) -> None:
    """Block until backend *pid* is parked waiting on a lock."""
    for _ in range(_BARRIER_POLLS):
        wait_event_type = await probe.scalar(
            text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
            {"pid": pid},
        )
        await probe.rollback()
        if wait_event_type == "Lock":
            return
        await asyncio.sleep(_BARRIER_INTERVAL_SECONDS)
    raise AssertionError(
        f"backend {pid} never parked on a lock; the refresh under test did not "
        "reach its blocking acquisition"
    )


async def _holds_record_lock(probe, record_id: uuid.UUID) -> bool:
    """True when some other transaction holds the records row."""
    try:
        await probe.execute(
            select(Record.id).where(Record.id == record_id).with_for_update(nowait=True)
        )
    except DBAPIError as exc:
        await probe.rollback()
        if is_lock_conflict(exc):
            return True
        raise
    await probe.rollback()
    return False


class TestLockOrderAgainstRefreshPhaseThree:
    """The request must reach for the datasets row before the records row."""

    async def test_request_holds_no_record_lock_while_waiting_for_the_dataset(
        self, locked_dataset, monkeypatch
    ):
        """The whole ABBA cycle in one assertion.

        A cycle needs the request to be holding one row and waiting for the
        other. With the datasets row taken first there is nothing to hold: the
        request parks at its very first acquisition, so the third session can
        still take the records row. Before fix(#1847) the request was parked at
        its flush with ``catalog.records`` already locked, and this probe raised
        55P03.
        """
        # This test is about acquisition ORDER, so give the wait a budget the
        # barrier below cannot plausibly exhaust. The 2s production value is
        # exercised by test_lock_timeout_is_set_on_the_acquisition.
        monkeypatch.setattr(features_service, "_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        async with (
            db_module.async_session() as worker,
            db_module.async_session() as api,
            db_module.async_session() as probe,
        ):
            # The worker's phase 3 lock, verbatim: datasets row, single column.
            await worker.execute(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == locked_dataset.id)
                .with_for_update()
            )

            api_pid = await api.scalar(text("SELECT pg_backend_pid()"))
            api_dataset = await api.get(Dataset, locked_dataset.id)
            refresh = asyncio.create_task(
                features_service.refresh_dataset_metadata(
                    api,
                    api_dataset,
                    count_delta=1,
                    touched_bounds=[INSIDE_BOUNDS],
                    added_geometry_type="Point",
                )
            )
            try:
                await _await_lock_wait(probe, api_pid)
                assert not await _holds_record_lock(probe, locked_dataset.record_id), (
                    "the feature-edit path is parked on a lock while holding "
                    "catalog.records. That is one half of an ABBA cycle with "
                    "refresh_postgis phase 3, which holds catalog.datasets and "
                    "goes on to write the record row."
                )
            finally:
                await worker.rollback()
                await refresh
                await api.rollback()

    async def test_concurrent_edit_and_phase_three_write_do_not_deadlock(
        self, locked_dataset, monkeypatch
    ):
        """Drive both sides of the cycle and require neither to be aborted."""
        monkeypatch.setattr(features_service, "_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        async with (
            db_module.async_session() as worker,
            db_module.async_session() as api,
            db_module.async_session() as probe,
        ):
            await worker.execute(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == locked_dataset.id)
                .with_for_update()
            )

            api_pid = await api.scalar(text("SELECT pg_backend_pid()"))
            api_dataset = await api.get(Dataset, locked_dataset.id)
            refresh = asyncio.create_task(
                features_service.refresh_dataset_metadata(
                    api,
                    api_dataset,
                    count_delta=1,
                    touched_bounds=[INSIDE_BOUNDS],
                    added_geometry_type="Point",
                )
            )
            await _await_lock_wait(probe, api_pid)

            # The second half of what phase 3 does under its datasets lock:
            # write the record row. On the inverted order this is where
            # PostgreSQL detected the cycle and aborted one of the two.
            await worker.execute(
                text("UPDATE catalog.records SET updated_at = now() WHERE id = :rid"),
                {"rid": locked_dataset.record_id},
            )
            await worker.commit()

            await refresh
            await api.commit()

        # Both sides ran to completion, so the edit is in the catalog.
        async with db_module.async_session() as check:
            count = await check.scalar(
                select(Dataset.feature_count).where(Dataset.id == locked_dataset.id)
            )
        assert count == 4, (
            "the incremental fast path should have added one to the seeded "
            f"count of 3, got {count}"
        )


def _compiled(statement) -> str:
    """The SQL text a statement emits, as PostgreSQL would receive it."""
    if isinstance(statement, str):
        return statement
    try:
        return str(statement.compile(dialect=postgresql.dialect()))
    except Exception:
        return str(statement)


class _StubResult:
    def first(self):
        return None


class _RecordingSession:
    """Captures the statements the lock helper emits, in order."""

    def __init__(self):
        self.statements: list[str] = []

    @property
    def no_autoflush(self):
        import contextlib

        return contextlib.nullcontext()

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(_compiled(statement))
        return _StubResult()


class _StubDataset:
    id = uuid.UUID("00000000-0000-0000-0000-0000000000d5")
    record_id = uuid.UUID("00000000-0000-0000-0000-0000000000fe")


class TestEmittedSqlPinsTheOrder:
    """Pin the order on the SQL text, so a reordering fails without a race."""

    async def test_datasets_for_update_is_emitted_before_the_records_read(self):
        session = _RecordingSession()
        await features_service._lock_dataset_then_read_extent_box(
            session, _StubDataset()
        )

        locking = [
            (i, sql)
            for i, sql in enumerate(session.statements)
            if "FOR UPDATE" in sql.upper()
        ]
        assert len(locking) == 2, (
            f"expected exactly two locking statements, got {session.statements}"
        )
        (first_i, first_sql), (second_i, second_sql) = locking
        assert "datasets" in first_sql and "records" not in first_sql, (
            f"the first FOR UPDATE must be on the datasets row, got {first_sql}"
        )
        assert "records" in second_sql, (
            f"the second FOR UPDATE must be on the records row, got {second_sql}"
        )
        assert first_i < second_i

    async def test_lock_timeout_is_set_on_the_acquisition(self):
        session = _RecordingSession()
        await features_service._lock_dataset_then_read_extent_box(
            session, _StubDataset()
        )
        assert "SET LOCAL lock_timeout" in session.statements[0], (
            "the wait for the datasets row must be bounded, so a request "
            "queued behind a long refresh answers a retryable conflict rather "
            f"than hanging. Got {session.statements[0]}"
        )
        assert features_service._LOCK_TIMEOUT in session.statements[0]


class TestWorkerSitesLeadWithTheDatasetRow:
    """The two background writers of the pair keep the order this one matched."""

    def _lines(self, rel: str) -> list[str]:
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[1] / "app"
        return (app_dir / rel).read_text().splitlines()

    def test_postgis_refresh_locks_the_dataset_before_applying_the_measurement(self):
        lines = self._lines("processing/ingest/tasks_postgis_refresh.py")
        lock = next(
            i
            for i, line in enumerate(lines)
            if "select(Dataset.tile_cache_version)" in line
        )
        apply_call = next(
            i for i, line in enumerate(lines) if line.strip() == "_apply_measurement("
        )
        assert lock < apply_call, (
            "phase 3 must take the datasets row before _apply_measurement "
            "writes dataset.record. Reversing this re-opens #1847 from the "
            "worker side."
        )

    def test_stac_refresh_locks_the_dataset_before_writing_the_record(self):
        lines = self._lines("processing/ingest/tasks_stac_refresh.py")
        lock = next(
            i
            for i, line in enumerate(lines)
            if "select(" in line and "Dataset." in line
        )
        write = next(
            i
            for i, line in enumerate(lines)
            if "dataset.record.spatial_extent" in line and "=" in line
        )
        assert lock < write


class TestFeatureWriteErrorClassification:
    """A lock conflict is a retryable 409, not a 503 telling clients to back off."""

    class _Orig:
        def __init__(self, code):
            self.sqlstate = code

    def _error(self, code: str) -> DBAPIError:
        return DBAPIError("SELECT 1", {}, self._Orig(code))

    @pytest.mark.parametrize(
        "code",
        [
            "40P01",  # deadlock_detected
            "55P03",  # lock_not_available
        ],
    )
    def test_lock_conflict_is_a_conflict(self, code: str):
        result = _feature_write_db_error(self._error(code))
        assert result.status_code == 409
        assert result.detail["code"] == "feature_write_locked"

    def test_a_real_outage_is_still_unavailable(self):
        # 08006 is connection_failure: class 08, still operational.
        assert _feature_write_db_error(self._error("08006")).status_code == 503

    def test_a_bad_value_is_still_the_callers_fault(self):
        assert _feature_write_db_error(self._error("22P02")).status_code == 400


class TestEveryWriteHandlerGoesThroughTheGuard:
    """The refresh is inside the DBAPIError classification at all four sites."""

    def test_no_handler_calls_the_refresh_unguarded(self):
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "app/modules/catalog/features/router.py"
        ).read_text()
        bare = [
            line
            for line in source.splitlines()
            if "await refresh_dataset_metadata(" in line
        ]
        assert len(bare) == 1, (
            "the only call to refresh_dataset_metadata in this router should be "
            "the one inside _refresh_metadata_guarded; a handler calling it "
            "directly puts its row-lock acquisition back outside the "
            f"DBAPIError guard. Found {bare}"
        )
        assert source.count("await _refresh_metadata_guarded(") == 4
