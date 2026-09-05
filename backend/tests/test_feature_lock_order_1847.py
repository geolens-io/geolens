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
import functools
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from app.core.db.sqlstate import is_lock_conflict
from app.platform import catalog_locks
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


async def _await_waiter_on(probe, holder_xid: str) -> None:
    """Block until somebody is queued behind transaction *holder_xid*.

    The HTTP path runs on a connection the test never sees, so its pid cannot
    be read up front the way the service-level tests read theirs. Waiting on
    the HOLDER instead identifies the right event without knowing the waiter:
    a transaction blocked on a row lock queues an ungranted ``transactionid``
    lock naming the transaction that holds the row. Scoping to that xid also
    keeps a sibling suite's unrelated lock wait on this shared server from
    releasing this barrier early.
    """
    for _ in range(_BARRIER_POLLS):
        waiters = await probe.scalar(
            text(
                "SELECT count(*) FROM pg_locks WHERE NOT granted "
                "AND locktype = 'transactionid' AND transactionid::text = :xid"
            ),
            {"xid": holder_xid},
        )
        await probe.rollback()
        if waiters:
            return
        await asyncio.sleep(_BARRIER_INTERVAL_SECONDS)
    raise AssertionError(
        f"nothing ever queued behind transaction {holder_xid}; the request "
        "under test did not reach a blocking acquisition"
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
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

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
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

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


class TestPropertyOnlyPatchTakesThePairToo:
    """The one write path that does not recompute anything still locks."""

    async def test_a_property_only_patch_does_not_deadlock_with_phase_three(
        self,
        locked_dataset,
        client: AsyncClient,
        admin_auth_header,
        test_db_session,
        monkeypatch,
    ):
        """End to end, over HTTP, with the worker holding the datasets row.

        The request never recomputes an extent, so before fix(#1847)
        it took no catalog lock at all and its first touch of either row was
        the flush at ``commit()`` -- records, then datasets. That is the
        original inversion, on the one handler whose refresh is conditional.
        """
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        create = await client.post(
            f"/datasets/{locked_dataset.id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [-73.96, 40.74]},
                "properties": {"name": "before"},
            },
            headers=admin_auth_header,
        )
        assert create.status_code == 201, create.text
        gid = create.json()["id"]

        # The handler assigns `record.updated_by = user.id`, and the ORM emits
        # an UPDATE only when that is a real change. The insert above already
        # stamped this admin, so without this the PATCH would dirty the
        # datasets row alone and the records half of the pair would go
        # untested. Clearing it restores the ordinary case: the last editor is
        # somebody other than the current one.
        await test_db_session.execute(
            text("UPDATE catalog.records SET updated_by = NULL WHERE id = :rid"),
            {"rid": locked_dataset.record_id},
        )
        await test_db_session.commit()

        async with (
            db_module.async_session() as worker,
            db_module.async_session() as probe,
        ):
            await worker.execute(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == locked_dataset.id)
                .with_for_update()
            )
            worker_xid = await worker.scalar(text("SELECT pg_current_xact_id()::text"))

            # Properties only: no geometry key at all, so the handler's
            # refresh branch is not taken.
            patch = asyncio.create_task(
                client.patch(
                    f"/datasets/{locked_dataset.id}/features/{gid}",
                    json={"properties": {"name": "after"}},
                    headers=admin_auth_header,
                )
            )
            try:
                await _await_waiter_on(probe, worker_xid)
                assert not await _holds_record_lock(probe, locked_dataset.record_id), (
                    "the property-only PATCH is parked on a lock while holding "
                    "catalog.records. It dirties both rows and must take them "
                    "datasets-first like every other write."
                )
                # The other half of what phase 3 does under its datasets lock.
                # On the inverted order this is where PostgreSQL aborted one.
                await worker.execute(
                    text(
                        "UPDATE catalog.records SET updated_at = now() WHERE id = :rid"
                    ),
                    {"rid": locked_dataset.record_id},
                )
                await worker.commit()
            except BaseException:
                await worker.rollback()
                raise
            response = await patch

        assert response.status_code == 200, response.text
        assert response.json()["properties"]["name"] == "after"

    async def test_a_property_only_patch_and_phase_three_both_complete(
        self,
        locked_dataset,
        client: AsyncClient,
        admin_auth_header,
        test_db_session,
        monkeypatch,
    ):
        """The same interleaving with the diagnostic assertion removed.

        Drives both sides to completion instead of characterising the state in
        the middle, so on the inverted order PostgreSQL reports the cycle
        itself rather than a message this test composed.
        """
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        create = await client.post(
            f"/datasets/{locked_dataset.id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [-73.97, 40.75]},
                "properties": {"name": "before"},
            },
            headers=admin_auth_header,
        )
        assert create.status_code == 201, create.text
        gid = create.json()["id"]
        # See the sibling test: the assignment has to be a real change for the
        # records half of the pair to be written at all.
        await test_db_session.execute(
            text("UPDATE catalog.records SET updated_by = NULL WHERE id = :rid"),
            {"rid": locked_dataset.record_id},
        )
        await test_db_session.commit()

        async with (
            db_module.async_session() as worker,
            db_module.async_session() as probe,
        ):
            await worker.execute(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == locked_dataset.id)
                .with_for_update()
            )
            worker_xid = await worker.scalar(text("SELECT pg_current_xact_id()::text"))

            patch = asyncio.create_task(
                client.patch(
                    f"/datasets/{locked_dataset.id}/features/{gid}",
                    json={"properties": {"name": "after"}},
                    headers=admin_auth_header,
                )
            )
            try:
                await _await_waiter_on(probe, worker_xid)
                await worker.execute(
                    text(
                        "UPDATE catalog.records SET updated_at = now() WHERE id = :rid"
                    ),
                    {"rid": locked_dataset.record_id},
                )
                await worker.commit()
            except BaseException:
                await worker.rollback()
                raise
            response = await patch

        assert response.status_code == 200, response.text


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
        await features_service.lock_catalog_rows_for_write(session, _StubDataset())

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
        await features_service.lock_catalog_rows_for_write(session, _StubDataset())
        assert "SET LOCAL lock_timeout" in session.statements[0], (
            "the wait for the datasets row must be bounded, so a request "
            "queued behind a long refresh answers a retryable conflict rather "
            f"than hanging. Got {session.statements[0]}"
        )
        assert catalog_locks.REQUEST_LOCK_TIMEOUT in session.statements[0]


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

    HANDLERS = {
        "create_feature",
        "replace_single_feature",
        "patch_single_feature",
        "delete_single_feature",
    }
    # Reaching either of these from a handler bypasses the classification, so
    # a lock conflict escapes as a 503 rather than the retryable 409.
    UNGUARDED = {"refresh_dataset_metadata", "lock_catalog_rows_for_write"}

    def _router_tree(self):
        import ast
        from pathlib import Path

        return ast.parse(
            (
                Path(__file__).resolve().parents[1]
                / "app/modules/catalog/features/router.py"
            ).read_text()
        )

    def test_no_handler_reaches_past_the_guard(self):
        import ast

        seen = set()
        for node in ast.walk(self._router_tree()):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if node.name not in self.HANDLERS:
                continue
            seen.add(node.name)
            direct = {
                n.func.id
                for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id in self.UNGUARDED
            }
            assert not direct, (
                f"{node.name} calls {sorted(direct)} directly. That puts the "
                "row-lock acquisition back outside the DBAPIError "
                "classification, where a conflict answers 503 instead of 409."
            )
        assert seen == self.HANDLERS, (
            f"handlers not found: {sorted(self.HANDLERS - seen)}"
        )

    def test_every_write_handler_acquires_on_every_path(self):
        """fix(#1847): unconditionally, or in BOTH arms of the if.

        Three handlers refresh unconditionally, so they hold the pair before
        they stamp `record.updated_by` and roll `tile_cache_version`. The PATCH
        handler refreshes only when the body carries geometry, and a
        property-only PATCH still dirties both rows -- so its else arm has to
        take the pair on its own or the flush at commit takes them in the ORM's
        records-then-datasets order and the deadlock is back.
        """
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "app/modules/catalog/features/router.py"
        ).read_text()
        tree = ast.parse(source)

        acquisitions = {"_refresh_metadata_guarded", "_lock_catalog_rows_guarded"}

        def acquires(nodes) -> bool:
            return any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id in acquisitions
                for node in nodes
                for n in ast.walk(node)
            )

        def acquires_on_every_path(body) -> bool:
            for stmt in body:
                if isinstance(stmt, ast.If):
                    if acquires(stmt.body) and acquires(stmt.orelse):
                        return True
                    continue
                if acquires([stmt]):
                    return True
            return False

        handlers = {
            "create_feature",
            "replace_single_feature",
            "patch_single_feature",
            "delete_single_feature",
        }
        seen = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef) or node.name not in handlers:
                continue
            seen.add(node.name)
            assert acquires_on_every_path(node.body), (
                f"{node.name} has a path that reaches db.commit() without "
                "taking the (datasets, records) pair. Every handler here "
                "dirties both rows, so a path that acquires nothing lets the "
                "flush order them records-first and re-opens #1847."
            )
        assert seen == handlers, f"handlers not found: {sorted(handlers - seen)}"


class TestMetadataPatchTakesThePairToo:
    """fix(#1847): the class from the other side.

    `update_user_metadata` writes record fields and dataset fields and then
    flushes them together. Before this round it acquired nothing, so the flush
    took catalog.records ahead of catalog.datasets and inverted against every
    writer that now leads with the dataset row -- including an ordinary feature
    edit, which is the pairing this issue exists to remove.
    """

    async def test_metadata_patch_holds_no_record_lock_while_waiting(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            # Stand in for a feature edit, which now holds the dataset row for
            # the rest of its transaction.
            await holder.execute(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == locked_dataset.id)
                .with_for_update()
            )
            holder_xid = await holder.scalar(text("SELECT pg_current_xact_id()::text"))

            # Both halves in one body: a record field and a dataset field.
            patch = asyncio.create_task(
                client.patch(
                    f"/datasets/{locked_dataset.id}",
                    json={
                        "title": "Renamed by the metadata patch",
                        "tile_columns": ["name"],
                    },
                    headers=admin_auth_header,
                )
            )
            try:
                await _await_waiter_on(probe, holder_xid)
                assert not await _holds_record_lock(probe, locked_dataset.record_id), (
                    "the metadata PATCH is parked on a lock while holding "
                    "catalog.records, which deadlocks against a feature edit "
                    "holding catalog.datasets."
                )
                await holder.execute(
                    text(
                        "UPDATE catalog.records SET updated_at = now() WHERE id = :rid"
                    ),
                    {"rid": locked_dataset.record_id},
                )
                await holder.commit()
            except BaseException:
                await holder.rollback()
                raise
            response = await patch

        assert response.status_code == 200, response.text
        assert response.json()["title"] == "Renamed by the metadata patch"


class TestOneAnswerForAContendedRow:
    """fix(#1847): 409 from every caller, not 409/503/400 by route.

    The acquisition is reached from feature writes, metadata edits, layer DDL
    and dataset deletion. Each classified a lost race differently until the
    helper started raising one domain exception with one handler.
    """

    async def _hold_dataset_row(self, session, dataset_id):
        await session.execute(
            select(Dataset.tile_cache_version)
            .where(Dataset.id == dataset_id)
            .with_for_update()
        )

    async def test_metadata_patch_answers_conflict(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module

        async with db_module.async_session() as holder:
            await self._hold_dataset_row(holder, locked_dataset.id)
            response = await client.patch(
                f"/datasets/{locked_dataset.id}",
                json={"title": "Should not land", "tile_columns": ["name"]},
                headers=admin_auth_header,
            )
            await holder.rollback()

        assert response.status_code == 409, response.text
        # The metadata PATCH used to reach the global DBAPIError handler, which
        # called a contended row an outage.
        assert response.status_code != 503

        # Rolled back: the title the request carried never landed.
        async with db_module.async_session() as check:
            title = await check.scalar(
                select(Record.title).where(Record.id == locked_dataset.record_id)
            )
        assert title != "Should not land"

    async def test_layer_ddl_answers_conflict(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module

        async with db_module.async_session() as holder:
            await self._hold_dataset_row(holder, locked_dataset.id)
            response = await client.post(
                f"/layers/{locked_dataset.id}/columns/",
                json={"column": {"name": "note_col", "type": "text"}},
                headers=admin_auth_header,
            )
            await holder.rollback()

        # This route read the same SQLSTATE as the caller's bad request.
        assert response.status_code == 409, response.text
        assert response.status_code != 400

    async def test_feature_write_still_answers_conflict(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module

        async with db_module.async_session() as holder:
            await self._hold_dataset_row(holder, locked_dataset.id)
            response = await client.post(
                f"/datasets/{locked_dataset.id}/features/",
                json={
                    "geometry": {"type": "Point", "coordinates": [-73.96, 40.74]},
                    "properties": {"name": "blocked"},
                },
                headers=admin_auth_header,
            )
            await holder.rollback()

        assert response.status_code == 409, response.text


class TestDeleteNeverReapsStorageItCannotCommit:
    """fix(#1847): the irreversible step must be behind the lock.

    `delete_dataset` deletes the managed objects permanently and relies on the
    transaction rolling back to keep the catalog consistent with them. An
    acquisition that can time out placed AFTER that reap breaks the
    arrangement: the objects are gone, the transaction rolls back, and the
    catalog keeps a dataset whose assets no longer exist.
    """

    def test_the_lock_precedes_every_irreversible_reap(self):
        """Source order, because the failure mode is an ordering, not a value."""
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "app/modules/catalog/datasets/domain/service_lifecycle.py"
        ).read_text()
        tree = ast.parse(source)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "delete_dataset"
        )
        acquisitions, reaps = [], []
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "lock_catalog_rows_for_write":
                    acquisitions.append(node.lineno)
                elif node.func.id == "_reap_managed_storage":
                    reaps.append(node.lineno)
        assert acquisitions and reaps, (
            f"expected both calls in delete_dataset; got {acquisitions=} {reaps=}"
        )
        for reap in reaps:
            assert any(a < reap for a in acquisitions), (
                f"_reap_managed_storage at line {reap} runs before any "
                "lock_catalog_rows_for_write. A 55P03 after that reap rolls the "
                "transaction back with the objects already deleted, leaving a "
                "catalog row pointing at storage that is gone."
            )

    async def test_a_contended_delete_leaves_the_objects_alone(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        """The whole finding end to end: 409, and nothing reaped."""
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module

        reaped: list[tuple] = []

        async def _record_only(prefixes, tenant_id):
            reaped.append((tuple(prefixes), tenant_id))

        from app.modules.catalog.datasets.domain import service_lifecycle

        monkeypatch.setattr(service_lifecycle, "_reap_managed_storage", _record_only)

        async with db_module.async_session() as holder:
            await holder.execute(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == locked_dataset.id)
                .with_for_update()
            )
            response = await client.request(
                "DELETE",
                f"/datasets/{locked_dataset.id}",
                json={"confirm_title": f"Lock order {locked_dataset.table_name}"},
                headers=admin_auth_header,
            )
            await holder.rollback()

        assert response.status_code == 409, response.text
        assert reaped == [], (
            "the delete reaped managed storage before losing the lock race, so "
            f"those objects are gone and the catalog row is not: {reaped}"
        )
        # And the row really is still there.
        async with db_module.async_session() as check:
            still_there = await check.scalar(
                select(Dataset.id).where(Dataset.id == locked_dataset.id)
            )
        assert still_there == locked_dataset.id


class TestTheOtherSitesHoldTheOrderToo:
    """The layers DDL, the delete and the metadata PATCH, against a held row.

    None of these monkeypatches REQUEST_LOCK_TIMEOUT: raising it hides how a
    contended row is actually answered. The barrier fires in milliseconds, so
    the 2s budget is not reached, and a 409 is accepted if it ever is.
    """

    async def _drive(self, holder, probe, dataset_id, request_coro):
        """Hold the dataset row, run *request_coro*, return it once parked."""
        await holder.execute(
            select(Dataset.tile_cache_version)
            .where(Dataset.id == dataset_id)
            .with_for_update()
        )
        holder_xid = await holder.scalar(text("SELECT pg_current_xact_id()::text"))
        task = asyncio.create_task(request_coro)
        await _await_waiter_on(probe, holder_xid)
        return task

    async def test_layers_add_column_holds_no_record_lock_while_waiting(
        self, locked_dataset, client: AsyncClient, admin_auth_header
    ):
        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            task = await self._drive(
                holder,
                probe,
                locked_dataset.id,
                client.post(
                    f"/layers/{locked_dataset.id}/columns/",
                    json={"column": {"name": "note_a", "type": "text"}},
                    headers=admin_auth_header,
                ),
            )
            try:
                assert not await _holds_record_lock(probe, locked_dataset.record_id), (
                    "the add-column DDL is parked on a lock while holding "
                    "catalog.records"
                )
            finally:
                await holder.rollback()
                response = await task
        assert response.status_code in (201, 409), response.text

    async def test_delete_holds_no_record_lock_while_waiting(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        import app.core.db as db_module
        from app.modules.catalog.datasets.domain import service_lifecycle

        reaped: list = []

        async def _record_only(prefixes, tenant_id):
            reaped.append(tuple(prefixes))

        monkeypatch.setattr(service_lifecycle, "_reap_managed_storage", _record_only)

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            task = await self._drive(
                holder,
                probe,
                locked_dataset.id,
                client.request(
                    "DELETE",
                    f"/datasets/{locked_dataset.id}",
                    json={"confirm_title": f"Lock order {locked_dataset.table_name}"},
                    headers=admin_auth_header,
                ),
            )
            try:
                assert not await _holds_record_lock(probe, locked_dataset.record_id), (
                    "the delete is parked on a lock while holding catalog.records"
                )
                # And it has not reaped anything yet, which is the P1: the
                # objects must not go until the rows are held.
                assert reaped == [], (
                    f"storage was reaped before the pair was held: {reaped}"
                )
            finally:
                await holder.rollback()
                response = await task
        assert response.status_code in (200, 204, 409), response.text

    async def test_metadata_patch_holds_no_record_lock_while_waiting(
        self, locked_dataset, client: AsyncClient, admin_auth_header
    ):
        """The round-2 site, re-tested at the production budget."""
        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            task = await self._drive(
                holder,
                probe,
                locked_dataset.id,
                client.patch(
                    f"/datasets/{locked_dataset.id}",
                    json={"title": "Renamed", "tile_columns": ["name"]},
                    headers=admin_auth_header,
                ),
            )
            try:
                assert not await _holds_record_lock(probe, locked_dataset.record_id)
            finally:
                await holder.rollback()
                response = await task
        assert response.status_code in (200, 409), response.text


class TestWorkerDoorsAcquireBeforeTheirWrites:
    """The three worker sites, checked on emitted order rather than by racing.

    Each needs a staged upload and a live ingest job to reach its swap, and the
    property under test is an ordering.
    `test_reupload_swap_lock_retry.py::TestSwapLocksBeforeItWrites` drives the
    reupload door end to end against a real session.
    """

    SITES = [
        ("processing/ingest/tasks_common.py", "_apply_reupload_swap"),
        ("processing/ingest/tasks_raster_replace.py", "reupload_raster"),
        ("processing/ingest/tasks_vrt.py", "regenerate_vrt"),
    ]

    @pytest.mark.parametrize("rel,name", SITES)
    def test_the_acquisition_precedes_the_first_write(self, rel: str, name: str):
        import ast
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[1] / "app"
        path = app_dir / rel
        tree = ast.parse(path.read_text())
        module = _module_qualname(path.relative_to(app_dir.parent))
        bindings = _local_bindings(tree, module)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
        )
        ok, why = acquisition_dominates_writes(
            fn, bindings, module, _acquiring_functions()
        )
        assert ok, f"{rel}::{name}: {why}"

    def test_worker_doors_do_not_clamp_their_transaction(self):
        """`lock_timeout=None` at each, and nowhere on a request path.

        `SET LOCAL` applies for the rest of the transaction. A worker that
        inherited the request budget would fail a multi-minute ingest on
        contention it is supposed to wait out.
        """
        import ast
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[1] / "app"
        none_sites = []
        for path in sorted(app_dir.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fname = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                if fname != "lock_catalog_rows":
                    continue
                for kw in node.keywords:
                    if kw.arg == "lock_timeout" and isinstance(kw.value, ast.Constant):
                        if kw.value.value is None:
                            none_sites.append(str(path.relative_to(app_dir.parent)))
        assert sorted(set(none_sites)) == [
            "app/processing/ingest/tasks_common.py",
            "app/processing/ingest/tasks_raster_replace.py",
            "app/processing/ingest/tasks_vrt.py",
        ], (
            "lock_timeout=None belongs to worker tasks only. A request path "
            f"that passes it waits forever on a contended row. Found: {none_sites}"
        )


# ---------------------------------------------------------------------------
# The class gate (fix(#1847))
# ---------------------------------------------------------------------------

# A function that writes BOTH catalog rows must acquire them in the house
# order first, or appear here with the reason it cannot deadlock. Adding a name
# is a decision, not a formality: read
# app.platform.catalog_locks.lock_catalog_rows before you do.
_PAIR_WRITER_EXEMPTIONS = {
    # --- both rows are INSERTed by this transaction ------------------------
    # No other transaction can hold either one, so there is nothing to order
    # against.
    "app.modules.catalog.datasets.domain.service_create.create_dataset": "creates the pair",
    "app.modules.catalog.datasets.domain.service_create.create_empty_dataset": "delegates to create_dataset",
    "app.modules.catalog.layers.service.create_layer": "creates the pair",
    "app.processing.ingest.tasks_raster_common.create_raster_dataset": "creates the pair",
    "app.processing.ingest.tasks_vrt.create_vrt_dataset": "creates the pair",
    "app.processing.ingest.tasks_common._finalize_ingest": "creates the pair, then stamps it",
    "app.processing.ingest.tasks_raster.ingest_raster": "creates the pair, then stamps it",
    "app.processing.ingest.tasks_vector.ingest_file": "wrapper around _finalize_ingest",
    "app.processing.ingest.tasks_vector.ingest_service": "wrapper around _finalize_ingest",
    "app.modules.catalog.sources.stac_router.stac_import": "one pair per item, each in its own savepoint",
    "app.processing.analysis.tasks._materialize": "registers a new pair, then applies provenance",
    "app.processing.analysis.tasks.materialize_analysis": "wrapper around _materialize",
    "app.processing.analysis.provenance.apply_analysis_provenance": "record of a pair being created",
    # --- writes one half; the caller owns the ordering ---------------------
    "app.processing.ingest.tasks_common.apply_manifest_record_metadata": "record only",
    "app.processing.ingest.tasks_raster_swap._write_swapped_fields": "sync, no session; reupload_raster acquires before calling it",
    # --- takes the datasets row FOR UPDATE itself --------------------------
    # These are the sites the house order was chosen to match. They do not go
    # through the helper because the lock and the superseded-content check are
    # one indivisible step.
    "app.processing.ingest.tasks_postgis_refresh._apply_measurement": "caller refresh_postgis holds datasets FOR UPDATE",
    "app.processing.ingest.tasks_postgis_refresh.refresh_postgis": "takes datasets FOR UPDATE for its superseded guard",
    "app.processing.ingest.tasks_stac_refresh.refresh_stac": "takes datasets FOR UPDATE for its superseded guard",
}


# Functions whose acquisition is deliberately conditional. Every other site
# must acquire on every path; these carry the reason the unlocked path is safe.
_CONDITIONAL_ACQUISITION = {
    "app.modules.catalog.datasets.domain.service_metadata.update_user_metadata": (
        "the unlocked branch writes the records row ALONE, and a one-row write "
        "has no order to get wrong. Gated on _DATASET_ROW_FIELDS, which is the "
        "set of request fields that reach catalog.datasets."
    ),
    "app.modules.catalog.features.router.patch_single_feature": (
        "both arms acquire, one through the refresh and one directly, which "
        "test_every_write_handler_acquires_on_every_path checks per arm."
    ),
}


ACQUIRERS = frozenset(
    {
        "app.platform.catalog_locks.lock_catalog_rows",
        "app.modules.catalog.features.service.lock_catalog_rows_for_write",
    }
)


def _module_qualname(rel) -> str:
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _local_bindings(tree, module: str) -> dict[str, str]:
    """Local name -> qualified target, from this module's imports and defs.

    fix(#1847): the previous scan keyed everything on the bare
    function name and merged across files, so any function that happened to
    share a name with one of the real acquirers inherited its exemption. A
    call is resolved through the binding that is actually in scope where it
    appears.
    """
    import ast

    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings.setdefault(node.name, f"{module}.{node.name}")
    return bindings


def _resolve(name: str, bindings: dict[str, str], module: str) -> str:
    return bindings.get(name) or f"{module}.{name}"


def _is_acquisition(node, bindings, module) -> bool:
    import ast

    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Name):
        return _resolve(node.func.id, bindings, module) in ACQUIRERS
    # `mod.lock_catalog_rows(...)` -- match on the attribute, which cannot be
    # confused with a same-named local because the acquirers are unique words.
    if isinstance(node.func, ast.Attribute):
        return any(a.rsplit(".", 1)[-1] == node.func.attr for a in ACQUIRERS)
    return False


_PAIR_TABLES = {"Dataset", "DatasetModel", "Record", "RecordModel"}


def _classify_base(base) -> str | None:
    """'record', 'dataset', or None for the object being written to."""
    import ast

    if isinstance(base, ast.Attribute):
        if base.attr == "record":
            return "record"
        if "dataset" in base.attr:
            return "dataset"
    if isinstance(base, ast.Name):
        if base.id in ("record", "rec"):
            return "record"
        if "dataset" in base.id:
            return "dataset"
    return None


def _core_statement_kind(node) -> str | None:
    """'record'/'dataset' for a Core ``update(X)`` / ``delete(X)`` on the pair.

    fix(#1847): latent rather than active today -- the two
    ``update(Dataset)`` sites write the datasets row alone -- but a Core
    statement is a write the attribute scan cannot see at all, so the first one
    that touches both rows would have been invisible.
    """
    import ast

    if not isinstance(node, ast.Call):
        return None
    fname = (
        node.func.id
        if isinstance(node.func, ast.Name)
        else node.func.attr
        if isinstance(node.func, ast.Attribute)
        else None
    )
    if fname not in ("update", "delete") or not node.args:
        return None
    target = node.args[0]
    name = (
        target.id
        if isinstance(target, ast.Name)
        else target.attr
        if isinstance(target, ast.Attribute)
        else None
    )
    if name not in _PAIR_TABLES:
        return None
    return "record" if "Record" in name else "dataset"


def _classify_object(node) -> str | None:
    """'record'/'dataset' for the OBJECT an expression names."""
    import ast

    if isinstance(node, ast.Attribute):
        if node.attr == "record":
            return "record"
        if "dataset" in node.attr:
            return "dataset"
    if isinstance(node, ast.Name):
        if node.id in ("record", "rec"):
            return "record"
        if "dataset" in node.id:
            return "dataset"
    return None


def _write_kinds(node) -> set[str]:
    """Which halves of the pair this single AST node writes."""
    import ast

    kinds: set[str] = set()
    # `session.delete(dataset.record)` removes the records row AND, by the FK
    # cascade on Dataset.record_id, the datasets row. Neither is an attribute
    # assignment, so without this the one endpoint that deletes a dataset is
    # invisible to the scan (fix(#1847)).
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "delete"
        and node.args
        and _classify_object(node.args[0]) == "record"
    ):
        kinds |= {"record", "dataset"}
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        targets = list(getattr(node, "targets", []) or [])
        single = getattr(node, "target", None)
        if single is not None:
            targets.append(single)
        for t in targets:
            if isinstance(t, ast.Attribute):
                kind = _classify_base(t.value)
                if kind:
                    kinds.add(kind)
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "setattr" and node.args:
            kind = _classify_base(node.args[0])
            if kind:
                kinds.add(kind)
        core = _core_statement_kind(node)
        if core:
            kinds.add(core)
    return kinds


def _direct_writes(fn) -> set[str]:
    import ast

    kinds: set[str] = set()
    for node in ast.walk(fn):
        kinds |= _write_kinds(node)
    return kinds


def _called_targets(fn, bindings, module) -> set[str]:
    import ast

    names = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(_resolve(node.func.id, bindings, module))
        elif isinstance(node.func, ast.Attribute):
            names.add(f"?.{node.func.attr}")
    return names


def _walk_app_functions():
    import ast
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    for path in sorted(app_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        rel = path.relative_to(app_dir.parent)
        module = _module_qualname(rel)
        bindings = _local_bindings(tree, module)
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield rel, module, bindings, fn


@functools.lru_cache(maxsize=1)
def _app_function_facts():
    """Per QUALIFIED name: what it writes, what it calls, where it is.

    Keyed by ``module.name``, not by bare name. Two same-named functions in
    different modules are two entries.
    """
    writes: dict[str, set[str]] = {}
    calls: dict[str, set[str]] = {}
    sites: dict[str, str] = {}
    for rel, module, bindings, fn in _walk_app_functions():
        key = f"{module}.{fn.name}"
        writes.setdefault(key, set()).update(_direct_writes(fn))
        calls.setdefault(key, set()).update(_called_targets(fn, bindings, module))
        sites.setdefault(key, f"{rel}:{fn.lineno}")
    return writes, calls, sites


def _closure(seeds: dict[str, set[str]], calls: dict[str, set[str]]):
    """Propagate write kinds along call edges to a fixed point."""
    effective = {name: set(kinds) for name, kinds in seeds.items()}
    for _ in range(8):
        changed = False
        for name, callees in calls.items():
            for callee in callees:
                gained = effective.get(callee, set()) - effective.setdefault(
                    name, set()
                )
                if gained:
                    effective[name] |= gained
                    changed = True
        if not changed:
            break
    return effective


def _pair_writer_report() -> dict[str, str]:
    """Qualified name -> site, for every function that writes BOTH rows."""
    writes, calls, sites = _app_function_facts()
    effective = _closure(writes, calls)
    return {
        name: sites[name]
        for name, kinds in effective.items()
        if kinds >= {"record", "dataset"} and name in sites
    }


def _acquiring_functions() -> set[str]:
    """Qualified names that acquire, or that reach an acquirer through a call."""
    _writes, calls, _sites = _app_function_facts()
    resolved = set(ACQUIRERS)
    for _ in range(8):
        grew = {n for n, c in calls.items() if c & resolved} - resolved
        if not grew:
            break
        resolved |= grew
    return resolved


def _nested_bodies(stmt):
    """Flatten a compound statement's bodies, or None if it is not one.

    `if` is handled by the caller instead, because its two arms have to be
    analysed independently rather than concatenated.
    """
    import ast

    if not isinstance(
        stmt, (ast.Try, ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith)
    ):
        return None
    nested = list(getattr(stmt, "body", []))
    nested += list(getattr(stmt, "orelse", []))
    nested += list(getattr(stmt, "finalbody", []))
    for handler in getattr(stmt, "handlers", []):
        nested += handler.body
    return nested


def acquisition_dominates_writes(
    fn, bindings, module, acquirers=None
) -> tuple[bool, str]:
    """Does an acquisition precede every write, on every path through *fn*?

    fix(#1847): the round-2 check accepted a call to the helper
    ANYWHERE in the body, so an acquisition placed after the writes, or in one
    arm of an `if`, passed. Both are the defect this gate exists to catch.

    *acquirers* is the transitive set: a handler that acquires through a
    wrapper acquires just as surely as one that calls the helper directly.
    """
    import ast

    reach = ACQUIRERS if acquirers is None else acquirers

    def is_acq(node) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Name):
            return _resolve(node.func.id, bindings, module) in reach
        if isinstance(node.func, ast.Attribute):
            return any(a.rsplit(".", 1)[-1] == node.func.attr for a in reach)
        return False

    def plain(stmt, acquired):
        """One non-compound statement: acquisitions and writes by position."""
        acq = [n.lineno for n in ast.walk(stmt) if is_acq(n)]
        writes = [n.lineno for n in ast.walk(stmt) if _write_kinds(n)]
        if writes and not acquired and (not acq or min(acq) > min(writes)):
            return (
                False,
                acquired,
                (
                    f"line {min(writes)} writes a catalog row with no acquisition "
                    "before it on this path"
                ),
            )
        return True, acquired or bool(acq), ""

    def scan(stmts, acquired: bool):
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                then_ok, then_acq, why = scan(stmt.body, acquired)
                if not then_ok:
                    return False, acquired, why
                else_ok, else_acq, why = scan(stmt.orelse, acquired)
                if not else_ok:
                    return False, acquired, why
                acquired = acquired or (then_acq and else_acq)
                continue
            nested = _nested_bodies(stmt)
            if nested is not None:
                ok, nested_acq, why = scan(nested, acquired)
                if not ok:
                    return False, acquired, why
                acquired = acquired or nested_acq
                continue
            ok, acquired, why = plain(stmt, acquired)
            if not ok:
                return False, acquired, why
        return True, acquired, ""

    ok, _acq, why = scan(fn.body, False)
    return ok, why


class TestEveryPairWriterTakesTheHouseOrder:
    """Every transaction that writes both catalog rows must acquire first.

    SQLAlchemy flushes catalog.records before catalog.datasets, so one that
    acquires nothing inverts against every writer holding the dataset row.
    """

    def test_every_pair_writer_acquires_or_is_exempt(self):
        writers = _pair_writer_report()
        acquirers = _acquiring_functions()
        offenders = {
            name: site
            for name, site in writers.items()
            if name not in acquirers and name not in _PAIR_WRITER_EXEMPTIONS
        }
        assert not offenders, (
            "these functions write a Record field and a Dataset field without "
            "taking the (datasets, records) pair first:\n"
            + "\n".join(f"  {n}: {v}" for n, v in sorted(offenders.items()))
            + "\n\nCall lock_catalog_rows_for_write (catalog) or "
            "lock_catalog_rows (processing, with lock_timeout=None) before the "
            "first write, or add the name to _PAIR_WRITER_EXEMPTIONS with the "
            "reason it cannot deadlock."
        )

    def test_the_acquisition_precedes_the_writes_on_every_path(self):
        """fix(#1847): position and branch, not mere presence.

        Calling the helper somewhere in the body proves nothing. After the
        writes it orders nothing, and in one arm of an `if` it orders nothing
        on the other arm -- which is exactly the round-1 defect.
        """
        writers = _pair_writer_report()
        # A handler that acquires through a wrapper (the feature router's
        # _refresh_metadata_guarded, say) acquires just as surely as one that
        # calls the helper directly.
        acquirers = _acquiring_functions()
        failures = []
        for rel, module, bindings, fn in _walk_app_functions():
            key = f"{module}.{fn.name}"
            if key in _PAIR_WRITER_EXEMPTIONS or key in _CONDITIONAL_ACQUISITION:
                continue
            if not _direct_writes(fn):
                continue  # inherits its writes; the callee is checked instead
            # Every function that acquires must do so before ITS OWN writes,
            # not only the ones that write both rows. A helper that writes the
            # datasets row and then acquires has already let the flush order
            # the pair, even though its own body never touches the record --
            # which is how the first version of this check missed
            # `layers.service.add_column` (fix(#1847)).
            if key not in acquirers and key not in writers:
                continue
            ok, why = acquisition_dominates_writes(fn, bindings, module, acquirers)
            if not ok:
                failures.append(f"  {key} ({rel}:{fn.lineno}): {why}")
        assert not failures, (
            "the acquisition does not dominate the writes in:\n"
            + "\n".join(sorted(failures))
            + "\n\nMove it before the first write, on every path, or add the "
            "name to _CONDITIONAL_ACQUISITION with the reason the unlocked "
            "path cannot write both rows."
        )

    def test_the_gate_actually_finds_the_known_writers(self):
        """A positive control: an empty scan would pass the tests above."""
        writers = _pair_writer_report()
        for expected in (
            "app.modules.catalog.datasets.domain.service_metadata.update_user_metadata",
            "app.processing.ingest.tasks_common._apply_reupload_swap",
            "app.modules.catalog.features.service.refresh_dataset_metadata",
            "app.modules.catalog.datasets.domain.service_lifecycle.delete_dataset",
        ):
            assert expected in writers, (
                f"{expected} writes both rows but the scan missed it, so the "
                "gate above is passing vacuously. Widen _pair_writer_report."
            )

    def test_no_exemption_names_a_function_that_is_gone(self):
        """The lists must stay statements about live code, not folklore."""
        _writes, _calls, sites = _app_function_facts()
        missing = [
            name
            for name in (*_PAIR_WRITER_EXEMPTIONS, *_CONDITIONAL_ACQUISITION)
            if name not in sites
        ]
        assert not missing, (
            f"exemptions naming functions that no longer exist: {missing}. "
            "Remove them, or the lists decay into reasons nobody can check."
        )


class TestTheGateRejectsWhatItExistsToCatch:
    """A negative fixture per shape the gate must reject.

    Each is a synthetic module, so a blind spot fails this file.
    """

    MODULE = "app.fixture.probe"

    def _analyse(self, source: str):
        import ast

        tree = ast.parse(source)
        bindings = _local_bindings(tree, self.MODULE)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "probe"
        )
        return fn, bindings

    def test_acquisition_after_the_writes_is_rejected(self):
        fn, bindings = self._analyse(
            "from app.platform.catalog_locks import lock_catalog_rows\n"
            "async def probe(session, dataset):\n"
            "    dataset.record.updated_by = 1\n"
            "    dataset.srid = 4326\n"
            "    await lock_catalog_rows(session)\n"
        )
        ok, why = acquisition_dominates_writes(fn, bindings, self.MODULE)
        assert not ok, "an acquisition after the writes orders nothing"
        assert "no acquisition before it" in why

    def test_acquisition_in_one_arm_only_is_rejected(self):
        fn, bindings = self._analyse(
            "from app.platform.catalog_locks import lock_catalog_rows\n"
            "async def probe(session, dataset, flag):\n"
            "    if flag:\n"
            "        await lock_catalog_rows(session)\n"
            "    dataset.record.updated_by = 1\n"
            "    dataset.srid = 4326\n"
        )
        ok, _why = acquisition_dominates_writes(fn, bindings, self.MODULE)
        assert not ok, "the else path reaches the writes holding nothing"

    def test_acquisition_in_both_arms_is_accepted(self):
        fn, bindings = self._analyse(
            "from app.platform.catalog_locks import lock_catalog_rows\n"
            "async def probe(session, dataset, flag):\n"
            "    if flag:\n"
            "        await lock_catalog_rows(session)\n"
            "    else:\n"
            "        await lock_catalog_rows(session)\n"
            "    dataset.record.updated_by = 1\n"
            "    dataset.srid = 4326\n"
        )
        ok, why = acquisition_dominates_writes(fn, bindings, self.MODULE)
        assert ok, why

    def test_a_name_collision_does_not_inherit_the_exemption(self):
        """A local `lock_catalog_rows` that is somebody else's function.

        The round-2 scan keyed on bare names, so any function sharing a name
        with one of the real acquirers was treated as acquiring.
        """
        fn, bindings = self._analyse(
            "from app.somewhere.other import lock_catalog_rows\n"
            "async def probe(session, dataset):\n"
            "    await lock_catalog_rows(session)\n"
            "    dataset.record.updated_by = 1\n"
            "    dataset.srid = 4326\n"
        )
        ok, _why = acquisition_dominates_writes(fn, bindings, self.MODULE)
        assert not ok, (
            "a call resolved to app.somewhere.other.lock_catalog_rows is not an "
            "acquisition; only the two real helpers are"
        )

    def test_core_update_statements_count_as_writes(self):
        """`update(Dataset)` / `delete(Record)` are invisible to an attribute scan."""
        import ast

        tree = ast.parse(
            "from sqlalchemy import update\n"
            "from app.modules.catalog.datasets.domain.models import Dataset, Record\n"
            "async def probe(session):\n"
            "    await session.execute(update(Dataset).values(srid=1))\n"
            "    await session.execute(update(Record).values(title='x'))\n"
        )
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
        assert _direct_writes(fn) == {"dataset", "record"}, (
            "Core statements against the pair are writes; the attribute scan "
            "alone cannot see them"
        )

    def test_a_record_only_writer_is_not_named(self):
        """The other half of the control: no false positive on one-row writes."""
        import ast

        tree = ast.parse("async def probe(record):\n    record.title = 'x'\n")
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
        assert _direct_writes(fn) == {"record"}
