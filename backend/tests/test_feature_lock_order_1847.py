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

        The request never recomputes an extent, so before fix(#1847 review r1)
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
        """fix(#1847 review r1): unconditionally, or in BOTH arms of the if.

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
    """fix(#1847 review r2): the class from the other side.

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


# ---------------------------------------------------------------------------
# The class gate (fix(#1847 review r2))
# ---------------------------------------------------------------------------

# A function that writes BOTH catalog rows must acquire them in the house
# order first, or appear here with the reason it cannot deadlock. Adding a name
# is a decision, not a formality: read
# app.platform.catalog_locks.lock_catalog_rows before you do.
_PAIR_WRITER_EXEMPTIONS = {
    # Both rows are INSERTed by this transaction, so no other transaction can
    # be holding either one. There is nothing to order against.
    "create_dataset": "creates the pair",
    "create_empty_dataset": "delegates to create_dataset",
    "create_layer": "creates the pair",
    "create_raster_dataset": "creates the pair",
    "create_vrt_dataset": "creates the pair",
    "_finalize_ingest": "creates the pair through the port, then stamps it",
    "ingest_raster": "creates the pair, then stamps it",
    "stac_import": "creates one pair per item inside its own savepoint",
    "_materialize": "registers a new pair, then applies provenance to it",
    "materialize_analysis": "task wrapper around _materialize",
    "ingest_file": "task wrapper around _finalize_ingest",
    "ingest_service": "task wrapper around _finalize_ingest",
    "apply_analysis_provenance": "writes only the record of a pair being created",
    # Writes the record half only; every caller is enumerated above.
    "apply_manifest_record_metadata": "record only",
    # Sync helper. Its caller (reupload_raster) takes the pair before calling
    # it -- asserted by test_every_pair_writer_acquires_or_is_exempt itself,
    # which sees the acquisition in the caller.
    "_write_swapped_fields": "caller acquires; sync, no session of its own",
    # These two take the datasets row FOR UPDATE themselves, before writing
    # either half, as the superseded-content guard their own comments describe.
    # They are the reason the house order is datasets-first; they do not go
    # through the helper because the lock and the token check are one step.
    "_apply_measurement": "caller refresh_postgis holds datasets FOR UPDATE",
    "refresh_postgis": "takes datasets FOR UPDATE for its superseded guard",
    "refresh_stac": "takes datasets FOR UPDATE for its superseded guard",
}


def _assignment_targets(node):
    """Every Attribute node this statement assigns to."""
    import ast

    targets = list(getattr(node, "targets", []) or [])
    single = getattr(node, "target", None)
    if single is not None:
        targets.append(single)
    return [t for t in targets if isinstance(t, ast.Attribute)]


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


def _direct_writes(fn) -> set[str]:
    """Which halves of the pair this function body writes on its own."""
    import ast

    kinds: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for attr in _assignment_targets(node):
                kind = _classify_base(attr.value)
                if kind:
                    kinds.add(kind)
        # `setattr(record, name, value)` is the same write by another spelling,
        # and it is how update_user_metadata assigns most of its fields.
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and node.args
        ):
            kind = _classify_base(node.args[0])
            if kind:
                kinds.add(kind)
    return kinds


def _called_names(fn) -> set[str]:
    import ast

    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
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
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield path.relative_to(app_dir.parent), fn


@functools.lru_cache(maxsize=1)
def _app_function_facts():
    """Per function name: where it is defined, what it writes, what it calls.

    Keyed by bare name. Two functions sharing a name merge, which can only
    widen the result -- a false positive costs an exemption line, a false
    negative costs a production deadlock.
    """
    writes: dict[str, set[str]] = {}
    calls: dict[str, set[str]] = {}
    sites: dict[str, list[str]] = {}
    for rel, fn in _walk_app_functions():
        writes.setdefault(fn.name, set()).update(_direct_writes(fn))
        calls.setdefault(fn.name, set()).update(_called_names(fn))
        sites.setdefault(fn.name, []).append(f"{rel}:{fn.lineno}")
    return writes, calls, sites


def _pair_writer_report() -> dict[str, list[str]]:
    """Every function under app/ that ends up writing BOTH catalog rows.

    Propagates writes through the call graph to a fixed point, because the
    halves are routinely split across helpers: `update_user_metadata` assigns
    `record.updated_by` itself but reaches `dataset.tile_columns` only through
    `_apply_tile_columns`, and a scan that looked at one body at a time missed
    exactly the site codex round 2 reported.

    Heuristic and deliberately broad. A false positive costs one exemption line
    with a reason. A false NEGATIVE costs a production deadlock.
    """
    writes, calls, sites = _app_function_facts()
    effective = {name: set(kinds) for name, kinds in writes.items()}
    for _ in range(6):  # deep enough for this codebase; converges well before
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
    return {
        name: sites[name]
        for name, kinds in effective.items()
        if kinds >= {"record", "dataset"}
    }


def _acquiring_functions() -> set[str]:
    """Names that take the pair, or that reach it through one of their calls."""
    _writes, calls, _sites = _app_function_facts()
    acquirers = {"lock_catalog_rows", "lock_catalog_rows_for_write"}
    resolved = set(acquirers)
    for _ in range(6):
        grew = {n for n, c in calls.items() if c & resolved} - resolved
        if not grew:
            break
        resolved |= grew
    return resolved


class TestEveryPairWriterTakesTheHouseOrder:
    """fix(#1847 review r2): the class, not the four handlers that started it.

    SQLAlchemy flushes catalog.records before catalog.datasets, so ANY
    transaction that writes both rows and acquires nothing takes them in the
    inverted order and can deadlock against a writer holding the dataset row.
    Codex round 2 found `update_user_metadata` this way; this test is what
    stops the next one being found in production instead.
    """

    def test_every_pair_writer_acquires_or_is_exempt(self):
        writers = _pair_writer_report()
        acquirers = _acquiring_functions()
        offenders = {
            name: sites
            for name, sites in writers.items()
            if name not in acquirers and name not in _PAIR_WRITER_EXEMPTIONS
        }
        assert not offenders, (
            "these functions write a Record field and a Dataset field without "
            "taking the (datasets, records) pair first:\n"
            + "\n".join(f"  {n}: {', '.join(v)}" for n, v in sorted(offenders.items()))
            + "\n\nCall lock_catalog_rows_for_write (catalog) or "
            "lock_catalog_rows (processing, with lock_timeout=None) before the "
            "first write, or add the name to _PAIR_WRITER_EXEMPTIONS with the "
            "reason it cannot deadlock."
        )

    def test_the_gate_actually_finds_the_known_writers(self):
        """A positive control: an empty scan would pass the test above."""
        writers = _pair_writer_report()
        for expected in (
            "update_user_metadata",
            "_apply_reupload_swap",
            "refresh_dataset_metadata",
        ):
            assert expected in writers, (
                f"{expected} writes both rows but the scan missed it, so the "
                "gate above is passing vacuously. Widen _pair_writer_report."
            )

    def test_no_exemption_names_a_function_that_is_gone(self):
        """The list must stay a statement about live code, not folklore."""
        _writes, _calls, sites = _app_function_facts()
        missing = [name for name in _PAIR_WRITER_EXEMPTIONS if name not in sites]
        assert not missing, (
            f"exemptions naming functions that no longer exist: {missing}. "
            "Remove them, or the list decays into reasons nobody can check."
        )
