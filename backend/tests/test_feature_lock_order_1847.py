"""The (datasets, records) lock order, and the gate that holds it (#1847).

Every transaction that writes both catalog rows takes the datasets row and
then the records row before its first write; a raster child comes before the
pair, the attribute row after it. A wait on a contended row answers 409.

The concurrency tests here assert on LOCK STATE, never on elapsed time. The
barrier is ``pg_stat_activity.wait_event_type``, and whether a lock is held is
settled by a third session's ``FOR UPDATE NOWAIT``, which either raises 55P03
or does not.

The DB-backed tests require the Docker test database.
"""

import ast
import asyncio
import functools
import inspect
import uuid
from pathlib import Path

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
from app.platform.catalog_locks import CatalogLockConflict

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


async def _seed_raster_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    """A raster dataset with its RasterAsset child, for the delete path.

    No data table: `delete_dataset`'s raster branch drops nothing and returns
    the storage prefixes for the router to reap after commit; the record
    delete cascades to `raster_assets`.
    """
    from app.processing.raster.models import RasterAsset

    record = Record(
        title=f"Lock order raster {uuid.uuid4().hex[:8]}",
        summary="Fixture raster",
        theme_category=["test"],
        visibility="private",
        record_status="published",
        record_type="raster_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"raster_{uuid.uuid4().hex[:8]}",
        srid=4326,
        geometry_type=None,
        feature_count=0,
        column_info=[],
        source_format="geotiff",
    )
    session.add(dataset)
    await session.flush()
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/source.cog.tif",
        )
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
async def locked_raster_dataset(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _seed_raster_dataset(test_db_session, created_by=admin_id)
    yield dataset
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :r"), {"r": dataset.record_id}
    )
    await test_db_session.commit()


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


async def _holds_attribute_lock(probe, attribute_id: uuid.UUID) -> bool:
    """True when some other transaction holds the attribute_metadata row."""
    try:
        await probe.execute(
            text(
                "SELECT id FROM catalog.attribute_metadata WHERE id = :aid "
                "FOR UPDATE NOWAIT"
            ),
            {"aid": attribute_id},
        )
    except DBAPIError as exc:
        await probe.rollback()
        if is_lock_conflict(exc):
            return True
        raise
    await probe.rollback()
    return False


async def _await_relation_waiter(probe, table_name: str) -> None:
    """Block until somebody is queued on a lock of ``data.<table_name>``."""
    for _ in range(_BARRIER_POLLS):
        waiters = await probe.scalar(
            text(
                "SELECT count(*) FROM pg_locks WHERE NOT granted "
                "AND locktype = 'relation' AND relation = to_regclass(:rel)"
            ),
            {"rel": f"data.{table_name}"},
        )
        await probe.rollback()
        if waiters:
            return
        await asyncio.sleep(_BARRIER_INTERVAL_SECONDS)
    raise AssertionError(f"nobody queued on data.{table_name}")


class TestLockOrderAgainstRefreshPhaseThree:
    """The request must reach for the datasets row before the records row."""

    async def test_request_holds_no_record_lock_while_waiting_for_the_dataset(
        self, locked_dataset, monkeypatch
    ):
        """The whole ABBA cycle in one assertion.

        A cycle needs the request to be holding one row and waiting for the
        other. With the datasets row taken first there is nothing to hold: it
        parks at its first acquisition, so the third session can still take
        the records row.
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

        This request recomputes no extent, so its only catalog writes are the
        stamp and the tile-version roll. Both rows, in one flush.
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

        # The ORM emits the records UPDATE only when `updated_by` really
        # changes, and the insert above already stamped this admin. Clearing it
        # restores the ordinary case: the last editor is somebody else.
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

        Drives both sides to completion rather than characterising the state
        in the middle, so PostgreSQL reports any cycle itself.
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
        from sqlalchemy.orm import Session

        self.statements: list[str] = []
        self.info: dict = {}
        self.sync_session = Session()

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

    def test_stac_refresh_locks_the_raster_row_before_the_dataset(self):
        """Phase 3 writes raster_assets after its binding guard, so the child
        row is taken first, the order the is_dem PATCH and the replace hold."""
        lines = self._lines("processing/ingest/tasks_stac_refresh.py")
        raster_lock = next(
            i
            for i, line in enumerate(lines)
            if "select(RasterAsset.dataset_id)" in line
        )
        dataset_lock = next(
            i
            for i, line in enumerate(lines)
            if "with_for_update" in line
            and any("Dataset.origin_uri" in prev for prev in lines[max(0, i - 8) : i])
        )
        assert raster_lock < dataset_lock, (
            "refresh_stac must take raster_assets before the datasets row; "
            "holding datasets first and then repointing the asset is an ABBA "
            "against the is_dem PATCH."
        )


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
    def test_lock_conflict_raises_the_shared_exception(self, code: str):
        """One condition, one shape.

        Returning a 409 of its own here gave a contended row two response
        bodies, depending on whether the acquisition or a later statement hit
        it. A client keying on the local `code` never saw it on the
        acquisition path, which raises and answers through the global handler.
        """
        with pytest.raises(CatalogLockConflict):
            _feature_write_db_error(self._error(code))

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
        """Unconditionally, or in BOTH arms of the if.

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
    """The class from the other side.

    `update_user_metadata` writes record fields and dataset fields and flushes
    them together, so it must take the pair first or invert against every
    writer that leads with the dataset row.
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


class TestTheMetadataPatchTakesThePairOnEveryBody:
    """fix(#1881): the body does not decide the order.

    A workflow hook runs on a `record_status` body with the dataset in its
    context, so a PATCH that names no dataset field can still write the
    datasets row. Every PATCH takes the pair, before its first write.
    """

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"summary": "A record field alone"}, id="record-field"),
            pytest.param({"record_status": "internal"}, id="record-status"),
        ],
    )
    async def test_a_record_only_patch_waits_for_the_datasets_row_holding_nothing(
        self, body, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            await holder.execute(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == locked_dataset.id)
                .with_for_update()
            )
            holder_xid = await holder.scalar(text("SELECT pg_current_xact_id()::text"))

            patch = asyncio.create_task(
                client.patch(
                    f"/datasets/{locked_dataset.id}",
                    json=body,
                    headers=admin_auth_header,
                )
            )
            try:
                await _await_waiter_on(probe, holder_xid)
                assert not await _holds_record_lock(probe, locked_dataset.record_id), (
                    "the record-only PATCH is parked on the datasets row while "
                    "holding catalog.records, which is the inverted order"
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
        for field, value in body.items():
            assert response.json()[field] == value

    def test_the_gate_sees_the_acquisition_on_every_path(self):
        """The structural pin: no exemption, and the walk finds the site."""
        key = (
            "app.modules.catalog.datasets.domain.service_metadata.update_user_metadata"
        )
        assert key not in _CONDITIONAL_ACQUISITION, (
            "update_user_metadata is exempt from the every-path rule again; a "
            "branch around its acquisition is what #1881 removed"
        )
        found = [
            (module, bindings, fn)
            for _rel, module, bindings, fn in _walk_app_functions()
            if f"{module}.{fn.name}" == key
        ]
        assert found, "the gate walk no longer sees update_user_metadata"
        module, bindings, fn = found[0]
        ok, why = acquisition_dominates_writes(
            fn, bindings, module, _acquiring_functions()
        )
        assert ok, why


class TestAttributeEditsTakeThePairToo:
    """Attribute PATCH and reset write the attribute row, then `record.updated_by`;
    every column DDL takes the pair, then the attribute row (#1847).
    """

    @pytest.mark.parametrize(
        ("method", "suffix", "payload"),
        [
            ("PATCH", "", {"title": "Renamed by the attribute patch"}),
            ("POST", "reset/", None),
        ],
        ids=["update", "reset"],
    )
    async def test_attribute_edit_holds_no_attribute_lock_while_waiting(
        self,
        locked_dataset,
        client: AsyncClient,
        test_db_session,
        admin_auth_header,
        monkeypatch,
        method: str,
        suffix: str,
        payload: dict | None,
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module
        from app.modules.catalog.datasets.domain.models import AttributeMetadata

        attr = AttributeMetadata(
            dataset_id=locked_dataset.id,
            field_name="name",
            title="Name",
            data_type="text",
        )
        test_db_session.add(attr)
        await test_db_session.commit()
        await test_db_session.refresh(attr)

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            # Stand in for a column DDL: it holds the pair, in the house order,
            # and will write this attribute row next.
            await holder.execute(
                select(Dataset.tile_cache_version)
                .where(Dataset.id == locked_dataset.id)
                .with_for_update()
            )
            await holder.execute(
                select(Record.id)
                .where(Record.id == locked_dataset.record_id)
                .with_for_update()
            )
            holder_xid = await holder.scalar(text("SELECT pg_current_xact_id()::text"))

            edit = asyncio.create_task(
                client.request(
                    method,
                    f"/datasets/{locked_dataset.id}/attributes/{attr.id}/{suffix}",
                    json=payload,
                    headers=admin_auth_header,
                )
            )
            try:
                await _await_waiter_on(probe, holder_xid)
                assert not await _holds_attribute_lock(probe, attr.id), (
                    "the attribute edit is parked on the pair while holding "
                    "catalog.attribute_metadata, which deadlocks against a "
                    "column DDL holding the pair and writing that row next."
                )
                # The DDL's own next step, which a held attribute row would block.
                await holder.execute(
                    text(
                        "UPDATE catalog.attribute_metadata SET data_type = 'text' "
                        "WHERE id = :aid"
                    ),
                    {"aid": attr.id},
                )
                await holder.commit()
            except BaseException:
                await holder.rollback()
                raise
            response = await edit

        assert response.status_code == 200, response.text
        assert response.json()["field_name"] == "name"

    def test_both_handlers_acquire_before_the_attribute_write(self):
        """Position, in source: the acquisition precedes the service call."""
        import ast
        import inspect

        from app.modules.catalog.datasets.api import router_metadata

        tree = ast.parse(inspect.getsource(router_metadata))
        wanted = {
            "update_attribute_endpoint": "update_attribute",
            "reset_attribute_endpoint": "reset_attribute",
        }
        seen = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted:
                calls = {}
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                        calls.setdefault(sub.func.id, sub.lineno)
                seen[node.name] = calls
        for handler, writer in wanted.items():
            calls = seen[handler]
            assert "lock_catalog_rows_for_write" in calls, handler
            assert calls["lock_catalog_rows_for_write"] < calls[writer], (
                f"{handler} writes the attribute row before taking the pair"
            )
        reset_calls = seen["reset_attribute_endpoint"]
        assert "sample_example_values" in reset_calls
        assert (
            reset_calls["sample_example_values"]
            < reset_calls["lock_catalog_rows_for_write"]
        ), "reset_attribute_endpoint reads the data table after taking the pair"

    async def test_reset_holds_no_catalog_row_while_waiting_for_the_table(
        self,
        locked_dataset,
        client: AsyncClient,
        test_db_session,
        admin_auth_header,
        monkeypatch,
    ):
        """The reset samples the data table; a DDL holds that table before it
        takes the pair, so the reset must reach for the table holding nothing.
        """
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module
        from app.modules.catalog.datasets.domain.models import AttributeMetadata

        attr = AttributeMetadata(
            dataset_id=locked_dataset.id,
            field_name="name",
            title="Name",
            data_type="text",
        )
        test_db_session.add(attr)
        await test_db_session.commit()
        await test_db_session.refresh(attr)

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            # A column DDL's first lock, held until its transaction ends.
            await holder.execute(
                text(
                    f"LOCK TABLE data.{locked_dataset.table_name} "
                    "IN ACCESS EXCLUSIVE MODE"
                )
            )
            reset = asyncio.create_task(
                client.post(
                    f"/datasets/{locked_dataset.id}/attributes/{attr.id}/reset/",
                    headers=admin_auth_header,
                )
            )
            try:
                await _await_relation_waiter(probe, locked_dataset.table_name)
                assert not await _holds_record_lock(probe, locked_dataset.record_id), (
                    "the attribute reset is parked on the data table while "
                    "holding the catalog pair, which deadlocks against a column "
                    "DDL holding the table and taking the pair next."
                )
                # The DDL's next step; NOWAIT so a held pair fails instead of
                # deadlocking the test itself.
                await holder.execute(
                    select(Dataset.tile_cache_version)
                    .where(Dataset.id == locked_dataset.id)
                    .with_for_update(nowait=True)
                )
                await holder.execute(
                    select(Record.id)
                    .where(Record.id == locked_dataset.record_id)
                    .with_for_update(nowait=True)
                )
                await holder.commit()
            except BaseException:
                await holder.rollback()
                raise
            response = await reset

        assert response.status_code == 200, response.text
        assert response.json()["example_values"] == ["seed"]


class TestOneAnswerForAContendedRow:
    """409 from every caller, not 409/503/400 by route.

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
    """The irreversible step must be behind the lock.

    The reap is permanent, so anything that can fail after it leaves the
    catalog holding a dataset whose objects are gone.
    """

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

        monkeypatch.setattr(service_lifecycle, "reap_managed_storage", _record_only)

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


class TestOneShapeForEveryContendedRow:
    """Every endpoint answers a contended row the same way.

    Two shapes were in play. The feature router returned its own 409 body for
    a lock conflict raised by a statement other than the acquisition, and the
    bulk delete swallowed one into a per-item "failed unexpectedly" with a
    stack trace, while single delete answered 409.
    """

    async def _hold(self, session, dataset_id):
        await session.execute(
            select(Dataset.tile_cache_version)
            .where(Dataset.id == dataset_id)
            .with_for_update()
        )

    async def test_a_feature_write_answers_the_shared_problem_detail(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module

        async with db_module.async_session() as holder:
            await self._hold(holder, locked_dataset.id)
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
        body = response.json()
        assert body["detail"]["code"] == "catalog_lock_conflict", body
        assert body["title"] == "Catalog entry is busy", body

    async def test_one_failed_item_does_not_poison_the_rest(
        self, client: AsyncClient, test_db_session, admin_auth_header
    ):
        """A pre-existing bug, found while making the conflict per-item.

        Any per-item failure rolled the session back, which expires every
        instance in it including the actor. The next item's access check then
        read `user.id`, lazy-loaded outside the greenlet, and raised
        MissingGreenlet -- recorded as "Dataset deletion failed unexpectedly".
        One bad item made every later item fail for a reason that had nothing
        to do with it. No lock involved: an ordinary title mismatch does it.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        datasets = [
            await _seed_dataset(test_db_session, created_by=admin_id) for _ in range(3)
        ]
        try:
            response = await client.post(
                "/datasets/bulk-delete",
                json={
                    "datasets": [
                        {
                            "dataset_id": str(datasets[0].id),
                            "confirm_title": f"Lock order {datasets[0].table_name}",
                        },
                        {
                            "dataset_id": str(datasets[1].id),
                            "confirm_title": "not the title",
                        },
                        {
                            "dataset_id": str(datasets[2].id),
                            "confirm_title": f"Lock order {datasets[2].table_name}",
                        },
                    ]
                },
                headers=admin_auth_header,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            by_id = {r["dataset_id"]: r for r in body["results"]}
            assert by_id[str(datasets[0].id)]["status"] == "deleted", body
            assert by_id[str(datasets[2].id)]["status"] == "deleted", body
            middle = by_id[str(datasets[1].id)]
            assert middle["status"] == "error"
            assert "title does not match" in middle["detail"], middle
            assert "failed unexpectedly" not in response.text
        finally:
            for d in datasets:
                await test_db_session.execute(
                    text(f"DROP TABLE IF EXISTS data.{d.table_name}")
                )
            await test_db_session.commit()

    async def test_bulk_delete_records_a_conflict_per_item(
        self, client: AsyncClient, test_db_session, admin_auth_header, monkeypatch
    ):
        """A conflict on one item must not discard the items around it.

        The endpoint commits per item and returns per-item results, so raising
        would throw away work that is already committed. The conflicting entry
        carries the same code the single-delete 409 does.
        """
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module
        from app.modules.catalog.datasets.domain import service_lifecycle

        async def _no_reap(prefixes, tenant_id):
            return None

        monkeypatch.setattr(service_lifecycle, "reap_managed_storage", _no_reap)

        admin_id = await get_user_id(test_db_session, "admin")
        datasets = [
            await _seed_dataset(test_db_session, created_by=admin_id) for _ in range(3)
        ]
        try:
            async with db_module.async_session() as holder:
                # The MIDDLE one is contended; the other two are untouched.
                await self._hold(holder, datasets[1].id)
                response = await client.post(
                    "/datasets/bulk-delete",
                    json={
                        "datasets": [
                            {
                                "dataset_id": str(d.id),
                                "confirm_title": f"Lock order {d.table_name}",
                            }
                            for d in datasets
                        ]
                    },
                    headers=admin_auth_header,
                )
                await holder.rollback()

            assert response.status_code != 409, response.text
            assert response.status_code == 200, response.text
            body = response.json()
            by_id = {r["dataset_id"]: r for r in body["results"]}

            first = by_id[str(datasets[0].id)]
            middle = by_id[str(datasets[1].id)]
            third = by_id[str(datasets[2].id)]

            assert first["status"] == "deleted", body
            assert third["status"] == "deleted", body
            assert middle["status"] == "error", body
            assert middle["code"] == "catalog_lock_conflict", body
            assert "failed unexpectedly" not in response.text
            assert body["deleted"] == 2 and body["errors"] == 1, body
        finally:
            for d in datasets:
                await test_db_session.execute(
                    text(f"DROP TABLE IF EXISTS data.{d.table_name}")
                )
            await test_db_session.commit()

    async def test_bulk_delete_codes_a_conflict_after_the_acquisition(
        self, client: AsyncClient, test_db_session, admin_auth_header, monkeypatch
    ):
        """A wait AFTER the pair is taken is the same contended row: a later
        55P03 arrives as a plain DBAPIError and must carry the same code.
        """
        from app.modules.catalog.datasets.api import router as datasets_router
        from app.modules.catalog.datasets.domain import service_lifecycle

        async def _no_reap(prefixes, tenant_id):
            return None

        monkeypatch.setattr(service_lifecycle, "reap_managed_storage", _no_reap)

        class _Orig:
            sqlstate = "55P03"

        async def _late_wait(*args, **kwargs):
            raise DBAPIError("UPDATE catalog.map_layers", {}, _Orig())

        # The first statement after delete_dataset returns, i.e. after the pair
        # was acquired inside it.
        monkeypatch.setattr(datasets_router, "audit_emit", _late_wait)

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await _seed_dataset(test_db_session, created_by=admin_id)
        try:
            response = await client.post(
                "/datasets/bulk-delete",
                json={
                    "datasets": [
                        {
                            "dataset_id": str(dataset.id),
                            "confirm_title": f"Lock order {dataset.table_name}",
                        }
                    ]
                },
                headers=admin_auth_header,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            (item,) = body["results"]
            assert item["status"] == "error", body
            assert item["code"] == "catalog_lock_conflict", body
            assert "failed unexpectedly" not in response.text
            assert body["deleted"] == 0 and body["errors"] == 1, body
        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
            )
            await test_db_session.commit()


class TestTheRasterChildIsHeldBeforeTheReap:
    """The delete must not reap raster objects it may not get to commit.

    The replace worker holds the RasterAsset row across its upload and only
    then takes the pair. A delete that took the pair, reaped the raster prefix,
    and met that row for the first time at the cascade would wait on the worker
    with the bytes already gone.
    """

    async def test_a_held_raster_row_stops_the_delete_before_it_reaps(
        self,
        locked_raster_dataset,
        client: AsyncClient,
        admin_auth_header,
        monkeypatch,
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module
        from app.modules.catalog.datasets.domain import service_lifecycle
        from app.processing.raster.models import RasterAsset

        reaped: list = []

        async def _record_only(prefixes, tenant_id):
            reaped.append(tuple(prefixes))

        monkeypatch.setattr(service_lifecycle, "reap_managed_storage", _record_only)

        title = locked_raster_dataset.record.title
        async with db_module.async_session() as holder:
            # Exactly what the replace worker holds across its upload.
            await holder.execute(
                select(RasterAsset.dataset_id)
                .where(RasterAsset.dataset_id == locked_raster_dataset.id)
                .with_for_update()
            )
            response = await client.request(
                "DELETE",
                f"/datasets/{locked_raster_dataset.id}",
                json={"confirm_title": title},
                headers=admin_auth_header,
            )
            await holder.rollback()

        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "catalog_lock_conflict"
        assert reaped == [], (
            "the delete reaped storage before it held the raster row, so those "
            f"objects are gone and the dataset is not: {reaped}"
        )


class TestDeleteLeadsWithTheJobRows:
    """A worker holds its job row before any data-table or catalog lock, and
    the record delete cascades into that row: the delete takes it first.
    """

    def test_delete_takes_the_job_rows_before_the_table_and_the_pair(self):
        import inspect

        from app.modules.catalog.datasets.domain import service_lifecycle

        src = inspect.getsource(service_lifecycle.delete_dataset)
        jobs = src.index("await lock_ingest_jobs(")
        assert jobs < src.index("DROP TABLE")
        assert jobs < src.index("await lock_catalog_rows_for_write(")

    async def test_delete_holds_no_catalog_row_while_waiting_for_the_job(
        self,
        locked_raster_dataset,
        client: AsyncClient,
        test_db_session,
        admin_auth_header,
        monkeypatch,
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")
        import app.core.db as db_module
        from app.modules.catalog.datasets.domain import service_lifecycle
        from app.platform.jobs.models import IngestJob
        from app.processing.raster.models import RasterAsset

        async def _no_reap(prefixes, tenant_id):
            return None

        monkeypatch.setattr(service_lifecycle, "reap_managed_storage", _no_reap)

        dataset_id = locked_raster_dataset.id
        record_id = locked_raster_dataset.record_id
        title = locked_raster_dataset.record.title
        job = IngestJob(dataset_id=dataset_id, status="running")
        test_db_session.add(job)
        await test_db_session.commit()
        job_id = job.id

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            # What a phase-2 bracket holds across its upload: the job row.
            await holder.execute(
                select(IngestJob.id)
                .where(IngestJob.id == job_id)
                .with_for_update(key_share=True)
            )
            holder_xid = await holder.scalar(text("SELECT pg_current_xact_id()::text"))
            delete = asyncio.create_task(
                client.request(
                    "DELETE",
                    f"/datasets/{dataset_id}",
                    json={"confirm_title": title},
                    headers=admin_auth_header,
                )
            )
            try:
                await _await_waiter_on(probe, holder_xid)
                assert not await _holds_record_lock(probe, record_id), (
                    "the delete is parked on the job row while holding "
                    "catalog.records, which deadlocks against a worker holding "
                    "its job row and taking the pair next."
                )
                # The worker's next steps; NOWAIT so a held row fails instead
                # of deadlocking the test itself.
                await holder.execute(
                    select(RasterAsset.dataset_id)
                    .where(RasterAsset.dataset_id == dataset_id)
                    .with_for_update(nowait=True)
                )
                await holder.execute(
                    select(Dataset.id)
                    .where(Dataset.id == dataset_id)
                    .with_for_update(nowait=True)
                )
                await holder.execute(
                    select(Record.id)
                    .where(Record.id == record_id)
                    .with_for_update(nowait=True)
                )
                await holder.commit()
            except BaseException:
                await holder.rollback()
                raise
            response = await delete

        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE id = :j"), {"j": job_id}
        )
        await test_db_session.commit()
        assert response.status_code == 204, response.text


class TestEveryJobWriterLeadsWithTheJobRow:
    """A transaction that writes its ingest-job row and locks a catalog or
    raster row takes the job row first, the order the dataset delete holds.
    """

    _JOB_WRITES = ("require_ingest_job_update(", "update_ingest_job_for_attempt(")
    _ROW_LOCKS = ("lock_catalog_rows", "lock_catalog_rows_for_write")

    @classmethod
    def _first_locks(cls, body: list[ast.stmt]) -> tuple[int | None, int | None]:
        """(first job-row lock line, first other row lock line), source order."""
        job = other = None
        nodes = sorted(
            (n for stmt in body for n in ast.walk(stmt)),
            key=lambda n: getattr(n, "lineno", 0),
        )
        for node in nodes:
            if not isinstance(node, ast.Call):
                continue
            func = ast.unparse(node.func)
            if func.endswith(".with_for_update"):
                if "IngestJob" in ast.unparse(node.func.value):
                    job = node.lineno if job is None else job
                else:
                    other = node.lineno if other is None else other
            elif func.rsplit(".", 1)[-1] in cls._ROW_LOCKS:
                other = node.lineno if other is None else other
        return job, other

    def test_every_worker_transaction_that_writes_the_job_locks_it_first(self):
        import app

        offenders: list[str] = []
        root = Path(app.__file__).parent / "processing"
        for path in sorted(root.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.AsyncWith):
                    continue
                for item in node.items:
                    call = item.context_expr
                    if not isinstance(call, ast.Call):
                        continue
                    name = ast.unparse(call.func).rsplit(".", 1)[-1]
                    if name not in ("async_session", "_job_phase_session"):
                        continue
                    body = "\n".join(ast.unparse(stmt) for stmt in node.body)
                    if not any(write in body for write in self._JOB_WRITES):
                        continue
                    job, other = self._first_locks(node.body)
                    if other is None:
                        continue
                    if name == "_job_phase_session":
                        ok = any(k.arg == "require_status" for k in call.keywords)
                    else:
                        ok = job is not None and job < other
                    if not ok:
                        offenders.append(f"{path.relative_to(root)}:{node.lineno}")
        assert offenders == [], offenders

    def test_the_sweep_sees_the_two_phases_it_exists_for(self):
        import app

        root = Path(app.__file__).parent / "processing" / "ingest"
        seen = 0
        for name in ("tasks_vrt.py", "tasks_stac_refresh.py"):
            for node in ast.walk(ast.parse((root / name).read_text())):
                if isinstance(node, ast.AsyncWith):
                    job, other = self._first_locks(node.body)
                    seen += job is not None and other is not None
        assert seen >= 2

    def test_cancel_leads_with_the_job_row_for_every_job_type(self):
        from app.platform.jobs.router import cancel_job

        src = inspect.getsource(cancel_job)
        first_row_lock = src.find(".with_for_update(")
        assert first_row_lock == -1 or src.index("update(IngestJob)") < first_row_lock


class TestALaterLockWaitAnswersTheSameWay:
    """The timeout outlives the acquisition it was set for.

    `SET LOCAL lock_timeout` holds for the whole transaction, so a wait after
    the pair is taken raises 55P03 from a statement the acquisition's own
    translation never wrapped.
    """

    async def test_is_dem_waits_at_the_raster_row_holding_nothing(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        """The request must reach for raster_assets FIRST.

        Holding the pair and then asking for the raster row is the opposite of
        the replace worker's order, and the worker is the side that cannot be
        retried. Parked at its first acquisition the request holds nothing, so
        no cycle can form whichever side arrives first.
        """
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")
        import app.core.db as db_module
        from app.processing.raster.models import RasterAsset

        async with db_module.async_session() as owner:
            owner.add(
                RasterAsset(
                    dataset_id=locked_dataset.id,
                    asset_uri=f"rasters/{locked_dataset.id}/source.cog.tif",
                )
            )
            await owner.commit()

        try:
            async with (
                db_module.async_session() as holder,
                db_module.async_session() as probe,
            ):
                # The worker's first lock, held across its upload.
                await holder.execute(
                    select(RasterAsset.dataset_id)
                    .where(RasterAsset.dataset_id == locked_dataset.id)
                    .with_for_update()
                )
                holder_xid = await holder.scalar(
                    text("SELECT pg_current_xact_id()::text")
                )
                patch = asyncio.create_task(
                    client.patch(
                        f"/datasets/{locked_dataset.id}",
                        json={"tile_columns": ["name"], "is_dem": True},
                        headers=admin_auth_header,
                    )
                )
                try:
                    await _await_waiter_on(probe, holder_xid)
                    assert not await _holds_record_lock(
                        probe, locked_dataset.record_id
                    ), (
                        "the PATCH is parked on the raster row while holding "
                        "catalog.records, which is the cycle the worker loses"
                    )
                    # What the worker does next, under its own raster lock.
                    await holder.execute(
                        text(
                            "UPDATE catalog.records SET updated_at = now() "
                            "WHERE id = :rid"
                        ),
                        {"rid": locked_dataset.record_id},
                    )
                    await holder.commit()
                except BaseException:
                    await holder.rollback()
                    raise
                response = await patch
            assert response.status_code == 200, response.text
        finally:
            async with db_module.async_session() as cleanup:
                await cleanup.execute(
                    text("DELETE FROM catalog.raster_assets WHERE dataset_id = :d"),
                    {"d": locked_dataset.id},
                )
                await cleanup.commit()

    async def test_is_dem_contending_on_the_raster_row_answers_409(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module
        from app.processing.raster.models import RasterAsset

        async with db_module.async_session() as owner:
            owner.add(
                RasterAsset(
                    dataset_id=locked_dataset.id,
                    asset_uri=f"rasters/{locked_dataset.id}/source.cog.tif",
                )
            )
            await owner.commit()

        try:
            async with db_module.async_session() as holder:
                await holder.execute(
                    select(RasterAsset.dataset_id)
                    .where(RasterAsset.dataset_id == locked_dataset.id)
                    .with_for_update()
                )
                # tile_columns takes the pair; is_dem then writes the raster
                # row, which the holder has.
                response = await client.patch(
                    f"/datasets/{locked_dataset.id}",
                    json={"tile_columns": ["name"], "is_dem": True},
                    headers=admin_auth_header,
                )
                await holder.rollback()

            assert response.status_code == 409, response.text
            assert response.json()["detail"]["code"] == "catalog_lock_conflict"
        finally:
            async with db_module.async_session() as cleanup:
                await cleanup.execute(
                    text("DELETE FROM catalog.raster_assets WHERE dataset_id = :d"),
                    {"d": locked_dataset.id},
                )
                await cleanup.commit()


class TestRecoverySurvivesANonMappedIdentity:
    """The recovery path must not assume the actor is a mapped User.

    An `IdentityExtension` supplies an identity that is not a mapped instance,
    and `AsyncSession.refresh()` raises `UnmappedInstanceError` on one -- from
    inside the handler that exists to keep one bad item from taking the rest.
    """

    async def test_refresh_is_skipped_for_an_unmapped_identity(self):
        from app.modules.catalog.datasets.api.router import _rollback_failed_item

        class _Identity:
            """What an overlay supplies: the protocol surface, no mapper."""

            id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
            username = "overlay"

        refreshed: list = []

        class _Session:
            async def rollback(self):
                return None

            async def refresh(self, obj):
                refreshed.append(obj)

        await _rollback_failed_item(_Session(), _Identity())
        assert refreshed == [], (
            "refresh() was called on an identity with no mapper; it raises "
            "UnmappedInstanceError there, aborting the recovery path"
        )


class TestTheReapFollowsTheCommit:
    """The irreversible step must not precede a cascade that can fail.

    The record delete cascades to child rows nobody locks (map_layers,
    record_embeddings, dataset_assets). Under the request timeout a contended
    child raises 55P03 and the transaction rolls back, so a reap that ran first
    left the dataset restored with its objects gone.
    """

    async def test_a_contended_cascade_child_leaves_the_objects_alone(
        self,
        locked_raster_dataset,
        client: AsyncClient,
        admin_auth_header,
        test_db_session,
        monkeypatch,
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module
        from app.modules.catalog.datasets.api import router as datasets_router
        from app.modules.catalog.maps.models import Map, MapLayer

        reaped: list = []

        async def _record_only(prefixes, tenant_id):
            reaped.append(tuple(prefixes))

        monkeypatch.setattr(
            datasets_router,
            "_reap_after_commit",
            lambda deletion: _record_only(deletion.storage_prefixes, None),
        )

        admin_id = await get_user_id(test_db_session, "admin")
        the_map = Map(name="lock order map", created_by=admin_id)
        test_db_session.add(the_map)
        await test_db_session.flush()
        layer = MapLayer(
            map_id=the_map.id,
            dataset_id=locked_raster_dataset.id,
            sort_order=0,
        )
        test_db_session.add(layer)
        await test_db_session.commit()

        title = locked_raster_dataset.record.title
        try:
            async with db_module.async_session() as holder:
                # A cascade child the acquisition does not lock.
                await holder.execute(
                    select(MapLayer.id).where(MapLayer.id == layer.id).with_for_update()
                )
                response = await client.request(
                    "DELETE",
                    f"/datasets/{locked_raster_dataset.id}",
                    json={"confirm_title": title},
                    headers=admin_auth_header,
                )
                await holder.rollback()

            async with db_module.async_session() as check:
                still_there = await check.scalar(
                    select(Dataset.id).where(Dataset.id == locked_raster_dataset.id)
                )
            # Either outcome is sound; what must never happen is the dataset
            # surviving with its objects reaped.
            assert not (still_there is not None and reaped), (
                f"the dataset survived ({still_there}) with storage already "
                f"reaped ({reaped}); response was {response.status_code}"
            )
        finally:
            await test_db_session.execute(
                text("DELETE FROM catalog.maps WHERE id = :m"), {"m": the_map.id}
            )
            await test_db_session.commit()

    def test_delete_dataset_does_not_reap(self):
        """Source-level: the reap is the caller's, after its commit."""
        import ast
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[1] / "app"
        tree = ast.parse(
            (
                app_dir / "modules/catalog/datasets/domain/service_lifecycle.py"
            ).read_text()
        )
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "delete_dataset"
        )
        reaps = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and "reap" in n.func.id
        ]
        assert not reaps, (
            "delete_dataset reaps storage inside its own transaction again. A "
            "cascade that loses a lock race then rolls the rows back with the "
            "objects already gone."
        )


class TestInvalidationsPrecedeTheReap:
    """Cache eviction must not wait on, or be skipped by, object storage.

    The reap awaits a storage backend. Running it first lets a slow one delay
    the invalidations, and a cancellation during it skip them, leaving search
    and the tile map serving a deleted dataset until TTL.
    """

    async def _run(self, client, headers, dataset, monkeypatch, boom, calls):
        from app.modules.catalog.datasets.api import router as datasets_router
        from app.modules.catalog.datasets.domain import service as domain_service

        async def _failing_reap(prefixes, tenant_id):
            calls.append("reap")
            raise boom()

        async def _catalog(*a, **kw):
            calls.append("invalidate_catalog_cache")

        def _notify(table_name):
            calls.append("notify_table_invalidated")

        # The real `_reap_after_commit` stays, so its own error handling is
        # what the test exercises.
        monkeypatch.setattr(domain_service, "reap_managed_storage", _failing_reap)
        monkeypatch.setattr(datasets_router, "invalidate_catalog_cache", _catalog)
        monkeypatch.setattr(datasets_router, "notify_table_invalidated", _notify)

        response = await client.request(
            "DELETE",
            f"/datasets/{dataset.id}",
            json={"confirm_title": dataset.record.title},
            headers=headers,
        )
        return response

    async def test_a_failing_reap_does_not_skip_them(
        self, locked_raster_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        calls: list[str] = []
        response = await self._run(
            client,
            admin_auth_header,
            locked_raster_dataset,
            monkeypatch,
            RuntimeError,
            calls,
        )
        assert response.status_code == 204, response.text
        assert "reap" in calls, calls
        assert calls.index("reap") > calls.index("invalidate_catalog_cache"), calls
        assert calls.index("reap") > calls.index("notify_table_invalidated"), calls

    async def test_a_cancelled_reap_does_not_skip_them(
        self, locked_raster_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        """Cancellation is the shutdown case, and it is a BaseException.

        `_reap_after_commit` catches Exception, so this one propagates. Both
        invalidations have already run by then, which is the point.
        """
        calls: list[str] = []
        try:
            await self._run(
                client,
                admin_auth_header,
                locked_raster_dataset,
                monkeypatch,
                asyncio.CancelledError,
                calls,
            )
        except BaseException:  # broad: the cancellation IS the scenario under test
            pass
        assert "reap" in calls, calls
        assert "invalidate_catalog_cache" in calls, calls
        assert "notify_table_invalidated" in calls, calls


class TestOnlyThisRequestsTimeoutIsAnswered:
    """fix(#1847): a 40P01 from a request that never installed the catalog
    timeout is not a busy dataset; only this request's own wait answers 409."""

    def _handler_input(self, code: str):
        import types

        class _Orig:
            sqlstate = code

        from sqlalchemy.exc import DBAPIError

        return DBAPIError("SELECT 1", {}, _Orig()), types.SimpleNamespace(
            url=types.SimpleNamespace(path="/datasets/x")
        )

    async def test_a_conflict_after_our_timeout_answers_409(self):
        from app.api.main import _database_error_handler

        token = catalog_locks.catalog_timeout_installed.set(True)
        try:
            exc, request = self._handler_input("40P01")
            response = await _database_error_handler(request, exc)
        finally:
            catalog_locks.catalog_timeout_installed.reset(token)
        assert response.status_code == 409

    async def test_an_unrelated_conflict_keeps_its_operational_answer(self):
        """No catalog timeout in this request, so class 40 stays a 503."""
        from app.api.main import _database_error_handler

        assert catalog_locks.catalog_timeout_installed.get() is False
        exc, request = self._handler_input("40P01")
        response = await _database_error_handler(request, exc)
        assert response.status_code == 503, (
            "a deadlock from a request that never installed the catalog "
            "timeout was reported as a busy dataset"
        )


class TestTheMarkerEndsWithItsTransaction:
    """fix(#1890): the marker stands for a `SET LOCAL`, which ends with the
    transaction that ran it. A conflict after that commit is not a busy
    catalog row, and a 409 there would have the client re-apply a committed
    update."""

    async def test_commit_clears_the_marker_the_acquisition_set(self, locked_dataset):
        import app.core.db as db_module

        async with db_module.async_session() as session:
            # Twice: the second acquisition must re-arm the marker and still
            # register one listener.
            for _ in range(2):
                await catalog_locks.lock_catalog_rows(
                    session,
                    dataset_cls=Dataset,
                    record_cls=Record,
                    dataset_id=locked_dataset.id,
                    record_id=locked_dataset.record_id,
                )
                assert catalog_locks.catalog_timeout_installed.get() is True
                await session.commit()
                assert catalog_locks.catalog_timeout_installed.get() is False, (
                    "the transaction that installed the lock timeout has "
                    "committed and the marker still says it is installed"
                )
            listeners = list(session.sync_session.dispatch.after_commit.listeners)
            assert listeners.count(catalog_locks._forget_lock_timeout) == 1

    async def test_a_conflict_after_the_commit_keeps_its_operational_answer(
        self,
        locked_dataset,
        client: AsyncClient,
        admin_auth_header,
        test_db_session,
        monkeypatch,
    ):
        """The PATCH commits, then reads to build its response."""
        import app.modules.catalog.datasets.api.router as router_module

        class _Orig:
            sqlstate = "40P01"

        async def _deadlock_victim(*_args, **_kwargs):
            raise DBAPIError("SELECT 1", {}, _Orig())

        monkeypatch.setattr(router_module, "_load_actor_identities", _deadlock_victim)
        response = await client.patch(
            f"/datasets/{locked_dataset.id}",
            json={"title": "Committed before the deadlock"},
            headers=admin_auth_header,
        )
        assert response.status_code == 503, (
            "a deadlock on the response read, after the update committed, was "
            f"answered as a retryable busy dataset: {response.status_code} "
            f"{response.text}"
        )
        title = await test_db_session.scalar(
            select(Record.title).where(Record.id == locked_dataset.record_id)
        )
        assert title == "Committed before the deadlock"

    async def test_a_conflict_inside_the_transaction_still_answers_409(
        self,
        locked_dataset,
        client: AsyncClient,
        admin_auth_header,
        test_db_session,
        monkeypatch,
    ):
        """A wait after the acquisition, on a cascade child it does not lock.

        The failed transaction is rolled back before the boundary handler
        reads the marker, so a rollback-time reset would answer this 503.
        """
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "150ms")
        import app.core.db as db_module
        from app.modules.catalog.maps.models import Map, MapLayer

        admin_id = await get_user_id(test_db_session, "admin")
        the_map = Map(name="marker scope map", created_by=admin_id)
        test_db_session.add(the_map)
        await test_db_session.flush()
        layer = MapLayer(map_id=the_map.id, dataset_id=locked_dataset.id, sort_order=0)
        test_db_session.add(layer)
        await test_db_session.commit()

        try:
            async with db_module.async_session() as holder:
                await holder.execute(
                    select(MapLayer.id).where(MapLayer.id == layer.id).with_for_update()
                )
                response = await client.request(
                    "DELETE",
                    f"/datasets/{locked_dataset.id}",
                    json={"confirm_title": f"Lock order {locked_dataset.table_name}"},
                    headers=admin_auth_header,
                )
                await holder.rollback()
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["code"] == "catalog_lock_conflict"
        finally:
            await test_db_session.execute(
                text("DELETE FROM catalog.maps WHERE id = :m"), {"m": the_map.id}
            )
            await test_db_session.commit()


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

        monkeypatch.setattr(service_lifecycle, "reap_managed_storage", _record_only)

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
        key = f"{module}.{name}"
        if key in _INMEMORY_UNTIL_ACQUIRED:
            pytest.skip(f"exempt: {_INMEMORY_UNTIL_ACQUIRED[key]}")
        ok, why = acquisition_dominates_writes(
            fn, bindings, module, _acquiring_functions()
        )
        assert ok, f"{rel}::{name}: {why}"

    def test_the_deferred_flush_exemption_still_holds(self):
        """The `no_autoflush` the exemption rests on must actually be there.

        Without it the in-memory assignments reach the database at whatever
        statement the archive path runs next, ahead of the acquisition.
        """
        import ast
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[1] / "app"
        src = (app_dir / "processing/ingest/tasks_raster_replace.py").read_text()
        tree = ast.parse(src)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "reupload_raster"
        )
        swap = next(
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_write_swapped_fields"
        )
        acquire = next(
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "lock_catalog_rows"
        )
        guarded = [
            n.lineno
            for n in ast.walk(fn)
            if isinstance(n, ast.With)
            and any(
                isinstance(item.context_expr, ast.Attribute)
                and item.context_expr.attr == "no_autoflush"
                for item in n.items
            )
        ]
        assert swap < acquire, "the swap helper must precede the acquisition here"
        assert any(swap < line < acquire for line in guarded), (
            "reupload_raster is exempt from the ordering check because its "
            "in-memory assignments are held under `no_autoflush` until the "
            "acquisition. That block is gone, so the exemption is now false: "
            f"swap at {swap}, acquisition at {acquire}, no_autoflush at {guarded}"
        )

    def test_the_worker_takes_the_raster_row_before_the_pair(self):
        """The reason both raster exemptions rest on, checked not asserted.

        Each takes `raster_assets` itself rather than through the helper. If
        that acquisition ever moves below the pair, the exemption is false and
        the site is the ABBA the rule exists to stop.
        """
        import ast
        from pathlib import Path

        app_dir = Path(__file__).resolve().parents[1] / "app"
        for rel, name in (
            ("processing/ingest/tasks_raster_replace.py", "reupload_raster"),
            ("processing/ingest/tasks_vrt.py", "regenerate_vrt"),
        ):
            tree = ast.parse((app_dir / rel).read_text())
            fn = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == name
            )
            raster_lines = [
                n.lineno
                for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("with_for_update", "values")
                and "RasterAsset" in ast.dump(n)
            ]
            pair_lines = [
                n.lineno
                for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "lock_catalog_rows"
            ]
            assert raster_lines, f"{rel}::{name} takes no raster row at all"
            assert pair_lines, f"{rel}::{name} takes no pair"
            assert min(raster_lines) < min(pair_lines), (
                f"{rel}::{name} takes the catalog pair at line "
                f"{min(pair_lines)} before it takes raster_assets at "
                f"{min(raster_lines)}. Its _ORDERS_RASTER_ITSELF exemption is "
                "now false."
            )

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

# A function that writes BOTH catalog rows acquires them in the house order
# first, or appears here with the reason it cannot deadlock.
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
    # --- takes the datasets row FOR UPDATE itself -------------------------
    # The lock and the superseded-content check are one step here, so these do
    # not go through the helper.
    "app.processing.ingest.tasks_postgis_refresh._apply_measurement": "caller refresh_postgis holds datasets FOR UPDATE",
    "app.processing.ingest.tasks_postgis_refresh.refresh_postgis": "takes datasets FOR UPDATE for its superseded guard",
    "app.processing.ingest.tasks_stac_refresh.refresh_stac": "takes datasets FOR UPDATE for its superseded guard",
}


# Assigns catalog fields in memory before acquiring, held under `no_autoflush`
# until after it. The reason is enforced by
# test_the_deferred_flush_exemption_still_holds.
_INMEMORY_UNTIL_ACQUIRED = {
    "app.processing.ingest.tasks_raster_replace.reupload_raster": (
        "`_write_swapped_fields` only assigns; the acquisition sits below "
        "`archive_lossy_original`, which uploads the whole original raster, "
        "and `no_autoflush` holds the assignments until after it."
    ),
}


# Functions that write raster_assets and order it themselves, rather than
# through the helper's `with_raster_asset`. The reason is enforced by
# test_the_worker_takes_the_raster_row_before_the_pair.
_ORDERS_RASTER_ITSELF = {
    "app.processing.ingest.tasks_raster_replace.reupload_raster": (
        "takes RasterAsset FOR UPDATE itself, ahead of the pair, which is the "
        "order every other site is matching"
    ),
    "app.processing.ingest.tasks_vrt.regenerate_vrt": (
        "claims the row with an UPDATE and re-reads it FOR UPDATE through its "
        "asset join, both ahead of the pair"
    ),
    "app.processing.ingest.tasks_stac_refresh.refresh_stac": (
        "takes RasterAsset FOR UPDATE ahead of the datasets FOR UPDATE that is "
        "its binding guard; the repoint writes that row after the guard"
    ),
}


# Functions whose acquisition is deliberately conditional. Every other site
# must acquire on every path; these carry the reason the unlocked path is safe.
_CONDITIONAL_ACQUISITION = {
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

    A call resolves through the binding in scope where it appears, so a
    function sharing a name with an acquirer does not inherit its exemption.
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


_PAIR_TABLES = {"Dataset", "DatasetModel", "Record", "RecordModel", "RasterAsset"}


# Names that stand for a `raster_assets` row. Deliberately loose: a false
# positive costs one exemption line, a false negative costs an ABBA against the
# replace worker, which takes that row first and the pair afterwards.
_RASTER_NAMES = {"ra", "raster_asset", "vrt_asset", "asset"}


def _classify_base(base) -> str | None:
    """'record', 'dataset', 'raster', or None for the object written to."""
    import ast

    if isinstance(base, ast.Attribute):
        if base.attr == "record":
            return "record"
        if base.attr in _RASTER_NAMES or "raster" in base.attr:
            return "raster"
        if "dataset" in base.attr:
            return "dataset"
    if isinstance(base, ast.Name):
        if base.id in ("record", "rec"):
            return "record"
        if base.id in _RASTER_NAMES or "raster" in base.id:
            return "raster"
        if "dataset" in base.id:
            return "dataset"
    return None


def _core_statement_kind(node) -> str | None:
    """'record'/'dataset' for a Core ``update(X)`` / ``delete(X)`` on the pair.

    A Core statement is a write the attribute scan cannot see, so the first
    one to touch both rows would otherwise be invisible.
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
    if "Raster" in name:
        return "raster"
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
    # `session.delete(dataset.record)` removes the records row AND, by FK
    # cascade, the datasets row. Neither is an attribute assignment, so the
    # delete endpoint would otherwise be invisible to the scan.
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


@functools.lru_cache(maxsize=1)
def _effective_writes() -> dict[str, set[str]]:
    """Qualified name -> the write kinds it reaches, directly or via callees."""
    writes, calls, _sites = _app_function_facts()
    return _closure(writes, calls)


def _pair_writer_report() -> dict[str, str]:
    """Qualified name -> site, for every function that writes BOTH rows."""
    _writes, _calls, sites = _app_function_facts()
    return {
        name: sites[name]
        for name, kinds in _effective_writes().items()
        if kinds >= {"record", "dataset"} and name in sites
    }


def _raster_writer_report() -> dict[str, str]:
    """Qualified name -> site, for every function that writes raster_assets."""
    _writes, _calls, sites = _app_function_facts()
    return {
        name: sites[name]
        for name, kinds in _effective_writes().items()
        if "raster" in kinds and name in sites
    }


def _acquires_raster_first(fn) -> bool:
    """Does every acquisition in *fn* extend the order to the raster child?"""
    import ast

    calls = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id in ("lock_catalog_rows", "lock_catalog_rows_for_write")
    ]
    if not calls:
        return False

    def _extends(call) -> bool:
        for kw in call.keywords:
            if kw.arg == "with_raster_asset" and not (
                isinstance(kw.value, ast.Constant) and kw.value.value is False
            ):
                return True
            if kw.arg == "raster_asset_cls" and not (
                isinstance(kw.value, ast.Constant) and kw.value.value is None
            ):
                return True
        return False

    # Every site, not any: an arm that takes the plain pair and later writes
    # the child is the ABBA this gate exists to reject.
    return all(_extends(call) for call in calls)


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


def _acq_predicate(bindings, module, reach):
    import ast

    def is_acq(node) -> bool:
        if not isinstance(node, ast.Call):
            return False
        if isinstance(node.func, ast.Name):
            return _resolve(node.func.id, bindings, module) in reach
        if isinstance(node.func, ast.Attribute):
            return any(a.rsplit(".", 1)[-1] == node.func.attr for a in reach)
        return False

    return is_acq


def _write_predicate(bindings, module, is_acq, reaches_write):
    """A write here, or a call to something that writes.

    A body-only scan misses a wrapper whose halves are both in callees.
    """
    import ast

    def is_write(node) -> bool:
        # Pair writes only: a raster_assets write belongs BEFORE the pair,
        # and is ordered by test_a_raster_writer_orders_the_child_first.
        if _write_kinds(node) & {"record", "dataset"}:
            return True
        if not isinstance(node, ast.Call) or is_acq(node):
            return False
        if not isinstance(node.func, ast.Name):
            return False  # unresolvable attribute call; do not guess
        reached = reaches_write.get(_resolve(node.func.id, bindings, module)) or set()
        return bool(reached & {"record", "dataset"})

    return is_write


def acquisition_dominates_writes(
    fn, bindings, module, acquirers=None, writers=None
) -> tuple[bool, str]:
    """Does an acquisition precede every write, on every path through *fn*?

    Calling the helper somewhere in the body proves nothing: after the writes
    it orders nothing, and in one arm of an `if` it orders nothing on the
    other. *acquirers* and *writers* are the transitive sets.
    """
    import ast

    is_acq = _acq_predicate(
        bindings, module, ACQUIRERS if acquirers is None else acquirers
    )
    is_write = _write_predicate(
        bindings, module, is_acq, _effective_writes() if writers is None else writers
    )

    def plain(stmt, acquired):
        acq = [n.lineno for n in ast.walk(stmt) if is_acq(n)]
        writes = [n.lineno for n in ast.walk(stmt) if is_write(n)]
        if writes and not acquired and (not acq or min(acq) > min(writes)):
            return (
                False,
                acquired,
                f"line {min(writes)} writes a catalog row with no acquisition "
                "before it on this path",
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
        """Position and branch, not mere presence.

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
            if (
                key in _PAIR_WRITER_EXEMPTIONS
                or key in _CONDITIONAL_ACQUISITION
                or key in _INMEMORY_UNTIL_ACQUIRED
            ):
                continue
            # Every acquirer OR pair writer, whether its writes are its own
            # or a callee's: either selection alone has a blind spot.
            if key not in acquirers and key not in writers:
                continue
            if not (_direct_writes(fn) or key in writers):
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

    def test_a_raster_writer_orders_the_child_first(self):
        """The gate owns this class now, not a human reading diffs.

        The replace worker holds `raster_assets` across its upload and asks
        for the pair afterwards, so taking the pair first is an ABBA.
        """
        acquirers = _acquiring_functions()
        raster_writers = _raster_writer_report()
        failures = []
        for rel, module, _bindings, fn in _walk_app_functions():
            key = f"{module}.{fn.name}"
            if key not in acquirers or key not in raster_writers:
                continue
            if key in _ORDERS_RASTER_ITSELF or key in _PAIR_WRITER_EXEMPTIONS:
                continue
            if not _acquires_raster_first(fn):
                failures.append(f"  {key} ({rel}:{fn.lineno})")
        assert not failures, (
            "these take the catalog pair and then write raster_assets, which "
            "inverts against the replace worker:\n"
            + "\n".join(sorted(failures))
            + "\n\nPass with_raster_asset=True (catalog) or raster_asset_cls "
            "(processing) so the child row is taken first, or add the name to "
            "_ORDERS_RASTER_ITSELF with the reason it already orders it."
        )

    def test_the_raster_scan_finds_the_known_writers(self):
        """Positive control: an empty raster scan would pass the test above."""
        writers = _raster_writer_report()
        for expected in (
            "app.modules.catalog.datasets.domain.service_metadata._apply_is_dem",
            "app.modules.catalog.datasets.domain.service_metadata.update_user_metadata",
            "app.processing.ingest.tasks_raster_swap._write_swapped_fields",
        ):
            assert expected in writers, (
                f"{expected} writes raster_assets but the scan missed it, so "
                "the rule above is passing vacuously"
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

    def _local_writers(self, source: str) -> dict[str, set[str]]:
        """Effective write kinds per qualified name, for a synthetic module."""
        import ast

        tree = ast.parse(source)
        bindings = _local_bindings(tree, self.MODULE)
        writes, calls = {}, {}
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = f"{self.MODULE}.{fn.name}"
            writes[key] = _direct_writes(fn)
            calls[key] = _called_targets(fn, bindings, self.MODULE)
        return _closure(writes, calls)

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

    def test_a_wrapper_whose_writes_are_all_in_callees_is_rejected(self):
        """The shape the gate was blind to: writes only in callees.

        Nothing in this body assigns a catalog field, so a scan that looked at
        direct writes alone saw no writes to order and skipped the function
        entirely -- while the sequence it emits is records, then the
        acquisition, then datasets. Exactly the inversion.
        """
        source = (
            "from app.platform.catalog_locks import lock_catalog_rows\n"
            "async def stamp_record(session, dataset):\n"
            "    dataset.record.updated_by = 1\n"
            "async def bump_dataset(session, dataset):\n"
            "    dataset.srid = 4326\n"
            "async def probe(session, dataset):\n"
            "    await stamp_record(session, dataset)\n"
            "    await lock_catalog_rows(session)\n"
            "    await bump_dataset(session, dataset)\n"
        )
        fn, bindings = self._analyse(source)
        writers = self._local_writers(source)
        ok, why = acquisition_dominates_writes(fn, bindings, self.MODULE, None, writers)
        assert not ok, (
            "the wrapper writes catalog.records through a callee before it "
            "acquires, which is the records-before-datasets order the gate "
            "exists to reject"
        )
        assert "no acquisition before it" in why

    def test_the_same_wrapper_with_the_acquisition_first_is_accepted(self):
        """The control: only the ordering differs."""
        source = (
            "from app.platform.catalog_locks import lock_catalog_rows\n"
            "async def stamp_record(session, dataset):\n"
            "    dataset.record.updated_by = 1\n"
            "async def bump_dataset(session, dataset):\n"
            "    dataset.srid = 4326\n"
            "async def probe(session, dataset):\n"
            "    await lock_catalog_rows(session)\n"
            "    await stamp_record(session, dataset)\n"
            "    await bump_dataset(session, dataset)\n"
        )
        fn, bindings = self._analyse(source)
        ok, why = acquisition_dominates_writes(
            fn, bindings, self.MODULE, None, self._local_writers(source)
        )
        assert ok, why

    def test_a_raster_writer_that_takes_the_pair_first_is_rejected(self):
        """The shape that inverts against the replace worker."""
        import ast

        source = (
            "from app.modules.catalog.features.service import "
            "lock_catalog_rows_for_write\n"
            "async def probe(session, dataset):\n"
            "    await lock_catalog_rows_for_write(session, dataset)\n"
            "    ra = await get_raster_asset(session, dataset.id)\n"
            "    ra.is_dem = True\n"
        )
        tree = ast.parse(source)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "probe"
        )
        assert "raster" in _direct_writes(fn), "the raster write must be seen"
        assert not _acquires_raster_first(fn), (
            "this takes the pair and only then writes raster_assets, which is "
            "the opposite of the order the replace worker takes"
        )

    def test_the_same_writer_extending_the_order_is_accepted(self):
        """The control: only the acquisition's reach differs."""
        import ast

        source = (
            "from app.modules.catalog.features.service import "
            "lock_catalog_rows_for_write\n"
            "async def probe(session, dataset):\n"
            "    await lock_catalog_rows_for_write(\n"
            "        session, dataset, with_raster_asset=True\n"
            "    )\n"
            "    ra = await get_raster_asset(session, dataset.id)\n"
            "    ra.is_dem = True\n"
        )
        tree = ast.parse(source)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "probe"
        )
        assert _acquires_raster_first(fn)

    def test_one_unguarded_acquisition_among_two_is_rejected(self):
        """Every site must extend the order, not any one of them."""
        import ast

        source = (
            "from app.modules.catalog.features.service import "
            "lock_catalog_rows_for_write\n"
            "async def probe(session, dataset, flag):\n"
            "    if flag:\n"
            "        await lock_catalog_rows_for_write(\n"
            "            session, dataset, with_raster_asset=True\n"
            "        )\n"
            "    else:\n"
            "        await lock_catalog_rows_for_write(session, dataset)\n"
            "    ra = await get_raster_asset(session, dataset.id)\n"
            "    ra.is_dem = True\n"
        )
        tree = ast.parse(source)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "probe"
        )
        assert not _acquires_raster_first(fn), (
            "one arm takes the plain pair and later writes raster_assets"
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


async def _published_version(dataset_id: uuid.UUID) -> int:
    import app.core.db as db_module

    async with db_module.async_session() as check:
        return await check.scalar(
            select(Dataset.tile_cache_version).where(Dataset.id == dataset_id)
        )


class TestOverlappingEditsEachPublishAVersion:
    """Two edits of one dataset publish N+1 and then N+2 (#1826, #1902).

    The holder stands in for the first edit: it holds the datasets row, rolls
    the counter and commits while the request is parked behind it. The request
    loaded its instance before it waited, so an absolute write from that
    instance would publish N+1 a second time and serve the second edit's tiles
    under the first edit's URL.
    """

    async def _overlap(self, holder, probe, dataset_id, request_coro):
        """Hold the row, park the request, bump, commit, then let it finish."""
        before = await holder.scalar(
            select(Dataset.tile_cache_version)
            .where(Dataset.id == dataset_id)
            .with_for_update()
        )
        holder_xid = await holder.scalar(text("SELECT pg_current_xact_id()::text"))
        task = asyncio.create_task(request_coro)
        try:
            await _await_waiter_on(probe, holder_xid)
            first = await holder.scalar(
                text(
                    "UPDATE catalog.datasets SET tile_cache_version = "
                    "tile_cache_version + 1 WHERE id = :d RETURNING tile_cache_version"
                ),
                {"d": dataset_id},
            )
            await holder.commit()
        except BaseException:
            await holder.rollback()
            raise
        response = await task
        assert first == before + 1
        return before, response

    def _message(self, before: int, published: int) -> str:
        return (
            f"the second commit published {published}. The first edit committed "
            f"{before + 1} while this request was parked, so the second must "
            f"publish {before + 2}: an absolute write from the instance loaded "
            "before the wait re-publishes the first edit's version."
        )

    async def test_a_feature_insert_publishes_the_next_version(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            before, response = await self._overlap(
                holder,
                probe,
                locked_dataset.id,
                client.post(
                    f"/datasets/{locked_dataset.id}/features/",
                    json={
                        "geometry": {"type": "Point", "coordinates": [-73.96, 40.74]},
                        "properties": {"name": "second"},
                    },
                    headers=admin_auth_header,
                ),
            )
        assert response.status_code == 201, response.text
        published = await _published_version(locked_dataset.id)
        assert published == before + 2, self._message(before, published)

    async def test_a_column_add_publishes_the_next_version(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            before, response = await self._overlap(
                holder,
                probe,
                locked_dataset.id,
                client.post(
                    f"/layers/{locked_dataset.id}/columns/",
                    json={"column": {"name": "note_v", "type": "text"}},
                    headers=admin_auth_header,
                ),
            )
        assert response.status_code == 201, response.text
        published = await _published_version(locked_dataset.id)
        assert published == before + 2, self._message(before, published)

    async def test_a_tile_columns_patch_publishes_the_next_version(
        self, locked_dataset, client: AsyncClient, admin_auth_header, monkeypatch
    ):
        monkeypatch.setattr(catalog_locks, "REQUEST_LOCK_TIMEOUT", "60s")

        import app.core.db as db_module

        async with (
            db_module.async_session() as holder,
            db_module.async_session() as probe,
        ):
            before, response = await self._overlap(
                holder,
                probe,
                locked_dataset.id,
                client.patch(
                    f"/datasets/{locked_dataset.id}",
                    json={"title": "Renamed", "tile_columns": ["name"]},
                    headers=admin_auth_header,
                ),
            )
        assert response.status_code == 200, response.text
        published = await _published_version(locked_dataset.id)
        assert published == before + 2, self._message(before, published)


class TestTheAtomicBumpReportsWhatItPublished:
    """The instance carries the returned value and stays clean (#1902)."""

    async def test_the_instance_is_updated_without_being_dirtied(
        self, locked_dataset, test_db_session
    ):
        from sqlalchemy import inspect as sa_inspect

        dataset = await test_db_session.get(Dataset, locked_dataset.id)
        before = dataset.tile_cache_version
        version = await catalog_locks.bump_tile_cache_version_on(
            test_db_session, dataset
        )
        assert version == before + 1
        assert dataset.tile_cache_version == version
        assert not sa_inspect(dataset).modified, (
            "the instance is dirty after the atomic bump, so the flush would "
            "write the value back as an absolute assignment"
        )
        await test_db_session.commit()
        assert await _published_version(locked_dataset.id) == version

    async def test_a_missing_row_answers_none(self, test_db_session):
        version = await catalog_locks.bump_tile_cache_version_atomic(
            test_db_session, dataset_cls=Dataset, dataset_id=uuid.uuid4()
        )
        assert version is None


class TestNoCatalogModuleWritesAnAbsoluteTileVersion:
    """Nothing under modules/catalog/ calls ``bump_tile_cache_version()``.

    A request handler's instance was loaded before it waited for the row, so
    the absolute spelling there writes a stale counter (#1902). The atomic
    spelling is the only one a catalog module may use.
    """

    CATALOG = Path(__file__).resolve().parents[1] / "app/modules/catalog"
    ATOMIC = "bump_tile_cache_version_on"
    ABSOLUTE = "bump_tile_cache_version"

    @staticmethod
    def _calls_named(tree, name: str) -> list[int]:
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else None
            )
            if called == name:
                out.append(node.lineno)
        return out

    def _sites(self, name: str) -> dict[str, int]:
        sites: dict[str, int] = {}
        for path in sorted(self.CATALOG.rglob("*.py")):
            for lineno in self._calls_named(ast.parse(path.read_text()), name):
                rel = str(path.relative_to(self.CATALOG))
                sites[f"{rel}:{lineno}"] = lineno
        return sites

    def test_no_catalog_module_calls_the_absolute_bump(self):
        offenders = sorted(self._sites(self.ABSOLUTE))
        assert not offenders, (
            "absolute tile-version writes under modules/catalog/: "
            f"{offenders}. Use bump_tile_cache_version_on (platform/catalog_locks), "
            "which increments the row at write time."
        )

    def test_the_scan_sees_the_known_request_sites(self):
        by_file: dict[str, int] = {}
        for site in self._sites(self.ATOMIC):
            rel = site.rsplit(":", 1)[0]
            by_file[rel] = by_file.get(rel, 0) + 1
        assert by_file == {
            "features/router.py": 4,
            "layers/router.py": 4,
            "datasets/api/router.py": 1,
        }, by_file

    def test_the_scan_catches_the_absolute_spelling(self):
        tree = ast.parse(
            "async def handler(db, dataset):\n"
            "    dataset.bump_tile_cache_version()\n"
            "    await db.commit()\n"
        )
        assert self._calls_named(tree, self.ABSOLUTE) == [2]
        assert self._calls_named(tree, self.ATOMIC) == []
