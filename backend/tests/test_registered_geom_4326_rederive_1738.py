"""fix(#1738): out-of-band writes to a registered table have to become visible.

Registering an existing table copies no data: the catalog points at the live
relation and every read is served from it. ``geom_4326`` is the exception —
it is a plain column that ``register_existing_table`` populates ONCE, and
nothing re-derives it afterwards. So the owner's own writes, which are the
entire reason to register a table rather than upload one, land in ``geom``
and are never rendered:

* ``UPDATE ... SET geom = ...`` moves a feature that keeps drawing in its old
  place;
* ``DELETE`` + ``INSERT`` (an ETL's ordinary reload) lands rows with a NULL
  render geometry;
* ``ogr2ogr -overwrite`` drops the table and recreates it with no
  ``geom_4326`` column, no GiST index and no reader grant at all.

None of these is visibly wrong, which is what makes the bug expensive: every
reader filters on ``geom_4326 && <envelope>``, and ``NULL && anything`` is
NULL, so an affected row is silently absent from tiles, feature reads, the
extent and analysis rather than drawn in the wrong place.

The assertions below are therefore about what the REAL readers return —
``processing.tiles.service.get_tile`` (the MVT the browser gets) and
``catalog.features.service.get_features`` (the bbox-filtered feature read) —
before and after a refresh. Asserting on the column itself would prove the
UPDATE ran and nothing about whether the dataset renders.

Every test registers a real table through ``register_existing_table``, so
this module joins ``_TENANCY_GLOBAL_STATE_MODULES`` in ``conftest``:
``grant_reader_access`` mutates cluster-global GRANTs and the file otherwise
flakes under ``-n 4``.
"""

from __future__ import annotations

import math
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload

from app.modules.catalog.datasets.api import router_refresh
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.features.service import get_features
from app.platform.jobs.models import IngestJob
from app.platform.refresh.models import DatasetRefreshRun
from app.processing.ingest import tasks_postgis_refresh
from app.processing.ingest.tasks_postgis_refresh import refresh_postgis
from tests.factories import get_user_id

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.usefixtures("_init_tile_pool_for_tests"),
]

# Two places far enough apart to sit in different tiles at z6 and in disjoint
# bboxes: lower Manhattan and central Paris.
_HERE = (-73.98, 40.75)
_THERE = (2.35, 48.86)
_ZOOM = 6


def _bbox(lon: float, lat: float) -> list[float]:
    """A small envelope around one point, for the feature bbox filter."""
    return [lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05]


def _tile_xy(lon: float, lat: float, z: int) -> tuple[int, int]:
    """The slippy-map tile containing a point — the same arithmetic MapLibre does."""
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


async def _create_source_table(session, table_name: str, *, lon: float, lat: float):
    """A table exactly as an owner would leave it: `geom`, and no `geom_4326`.

    This is what registration is handed. The render column, its index and the
    reader grant are all things GeoLens adds on the way in.
    """
    await session.execute(
        text(
            f'CREATE TABLE data."{table_name}" ('
            f"  gid serial PRIMARY KEY,"
            f"  name text,"
            f"  geom geometry(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, geom) '  # noqa: S608
            f"VALUES ('a', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
        ),
        {"lon": lon, "lat": lat},
    )
    await session.commit()


async def _register(session, table_name: str, admin_id: uuid.UUID):
    """Register the table through the real service, and commit.

    Returns the three plain values the tests need rather than the ORM
    instance: every commit and rollback below expires it, and reading an
    expired attribute outside the greenlet raises MissingGreenlet rather than
    lazily loading.
    """
    from app.processing.ingest.schemas import RegisterRequest
    from app.processing.ingest.service import register_existing_table

    dataset = await register_existing_table(
        session,
        RegisterRequest(table_name=table_name, title=f"Registered {table_name}"),
        SimpleNamespace(id=admin_id),
    )
    await session.commit()
    await session.refresh(dataset)
    return SimpleNamespace(
        id=dataset.id,
        record_id=dataset.record_id,
        column_info=dataset.column_info,
    )


async def _drop(session, table_name: str) -> None:
    await session.rollback()
    await session.execute(text(f'DROP TABLE IF EXISTS data."{table_name}" CASCADE'))
    await session.commit()


@asynccontextmanager
async def _dispatch_harness():
    """Patch the deferred task so the door queues nothing real."""
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    port = MagicMock()
    port.refresh_postgis_task.return_value = task
    with patch.object(router_refresh, "get_catalog_port", return_value=port):
        yield task


async def _refresh(session, client: AsyncClient, headers: dict, dataset_id: uuid.UUID):
    """Dispatch through the real door and run the worker, as the queue would.

    ``.func`` is the Procrastinate-registered callable, so the admission gate,
    the run ledger, the heartbeat and the failure handler all run for real.

    The test session is closed out first. It is a SECOND connection to the
    same table, and a SELECT through it leaves an ACCESS SHARE lock held for
    the rest of its transaction — which the worker's ADD COLUMN would then
    queue behind until its lock timeout, reporting the repair blocked. That
    is correct behaviour (see the blocked test below) and an artefact of the
    harness rather than of the scenario under test.
    """
    await session.rollback()

    async with _dispatch_harness():
        resp = await client.post(f"/datasets/{dataset_id}/refresh", headers=headers)
    assert resp.status_code == 202, resp.text
    payload = resp.json()

    job = (
        await session.execute(
            select(IngestJob).where(IngestJob.id == uuid.UUID(payload["job_id"]))
        )
    ).scalar_one()
    await refresh_postgis.func(
        job_id=payload["job_id"],
        dataset_id=payload["dataset_id"],
        attempt_id=str(job.attempt_id),
    )
    return payload


async def _reload(session, dataset_id: uuid.UUID) -> Dataset:
    session.expire_all()
    return (
        await session.execute(
            select(Dataset)
            .options(joinedload(Dataset.record))
            .where(Dataset.id == dataset_id)
        )
    ).scalar_one()


async def _features_at(session, table_name: str, point: tuple[float, float]) -> int:
    """How many features the REAL feature read returns in a bbox around a point."""
    await session.rollback()
    page = await get_features(
        session,
        table_name,
        limit=50,
        bbox=_bbox(*point),
        has_geometry=True,
    )
    return len(page.rows)


async def _tile_at(
    table_name: str, point: tuple[float, float], columns
) -> bytes | None:
    """The MVT the tile endpoint would serve for the tile containing a point."""
    from app.processing.tiles.pool import get_tile_pool
    from app.processing.tiles.service import get_tile

    x, y = _tile_xy(*point, _ZOOM)
    return await get_tile(get_tile_pool(), table_name, _ZOOM, x, y, columns or [])


async def _column_exists(session, table_name: str, column: str) -> bool:
    await session.rollback()
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = 'data' AND table_name = :t "
                "AND column_name = :c)"
            ),
            {"t": table_name, "c": column},
        )
    )


async def _has_gist_index(session, table_name: str) -> bool:
    await session.rollback()
    return bool(
        await session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM pg_indexes "
                "WHERE schemaname = 'data' AND tablename = :t "
                "AND indexdef LIKE '%USING gist (geom_4326)%')"
            ),
            {"t": table_name},
        )
    )


async def _stored_version(session, dataset_id: uuid.UUID) -> int:
    """The dataset's `tile_cache_version` as the database holds it.

    Read as a column, past this session's identity map: the worker rolls the
    counter from its own transaction, so an ORM instance loaded here could
    answer from before it.
    """
    await session.rollback()
    return await session.scalar(
        select(Dataset.tile_cache_version).where(Dataset.id == dataset_id)
    )


async def _reader_can_select(session, table_name: str) -> bool:
    await session.rollback()
    return bool(
        await session.scalar(
            text(
                "SELECT has_table_privilege('geolens_reader', "
                "format('%I.%I', 'data', CAST(:t AS text)), 'SELECT')"
            ),
            {"t": table_name},
        )
    )


# ---------------------------------------------------------------------------
# The load-bearing case: an out-of-band write is invisible until Refresh
# ---------------------------------------------------------------------------


async def test_an_out_of_band_geometry_update_renders_only_after_refresh(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """`UPDATE ... SET geom` moves the feature; nothing moves the render column.

    Both readers are asserted at BOTH locations, before and after, because a
    one-sided assertion cannot tell "the refresh fixed it" from "the reader
    never filtered on geometry in the first place".
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_upd_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)
        columns = dataset.column_info

        # The owner moves the feature, touching only their own column.
        await test_db_session.execute(
            text(
                f'UPDATE data."{table_name}" '  # noqa: S608
                f"SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
            ),
            {"lon": _THERE[0], "lat": _THERE[1]},
        )
        await test_db_session.commit()

        # The bug: every reader still shows the OLD position.
        assert await _features_at(test_db_session, table_name, _HERE) == 1
        assert await _features_at(test_db_session, table_name, _THERE) == 0
        assert await _tile_at(table_name, _HERE, columns) is not None
        assert await _tile_at(table_name, _THERE, columns) is None

        await _refresh(test_db_session, client, admin_auth_header, dataset.id)

        assert await _features_at(test_db_session, table_name, _HERE) == 0
        assert await _features_at(test_db_session, table_name, _THERE) == 1
        assert await _tile_at(table_name, _HERE, columns) is None
        assert await _tile_at(table_name, _THERE, columns) is not None
    finally:
        await _drop(test_db_session, table_name)


async def test_a_delete_and_reinsert_reload_renders_only_after_refresh(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """An ETL's ordinary reload lands rows whose render geometry is NULL.

    ``NULL && <envelope>`` is NULL, so the new rows are absent rather than
    misplaced — the dataset looks EMPTY while the table is full. The stored
    extent is asserted too: it is what spatial search and the map's initial
    viewport read, and it has to move with the data.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_del_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)
        columns = dataset.column_info

        await test_db_session.execute(text(f'DELETE FROM data."{table_name}"'))  # noqa: S608
        await test_db_session.execute(
            text(
                f'INSERT INTO data."{table_name}" (name, geom) '  # noqa: S608
                f"SELECT 'reloaded-' || i, "
                f"       ST_SetSRID(ST_MakePoint(:lon, :lat), 4326) "
                f"FROM generate_series(1, 3) AS i"
            ),
            {"lon": _THERE[0], "lat": _THERE[1]},
        )
        await test_db_session.commit()

        assert await _features_at(test_db_session, table_name, _THERE) == 0
        assert await _tile_at(table_name, _THERE, columns) is None

        await _refresh(test_db_session, client, admin_auth_header, dataset.id)

        assert await _features_at(test_db_session, table_name, _THERE) == 3
        assert await _tile_at(table_name, _THERE, columns) is not None

        reloaded = await _reload(test_db_session, dataset.id)
        assert reloaded.feature_count == 3
        # The extent is stored as a 4326 polygon; it has to contain the new
        # position and not the old one.
        assert await test_db_session.scalar(
            text(
                "SELECT ST_Intersects(spatial_extent, "
                "  ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) "
                "FROM catalog.records WHERE id = :rid"
            ),
            {"lon": _THERE[0], "lat": _THERE[1], "rid": reloaded.record_id},
        )
    finally:
        await _drop(test_db_session, table_name)


async def test_an_overwrite_restores_the_column_the_index_and_the_grant(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """`ogr2ogr -overwrite` drops the table; the repair has to rebuild it.

    This is the case that decided the design: nothing IN the table survives a
    DROP, so a trigger, a generated column or an index would all be gone with
    it. Only an invariant re-applied from outside — the same ADD COLUMN,
    expression, index-if-absent and GRANT registration uses — brings the
    dataset back without deleting it and registering it again, which would
    cost its id, its permalinks and its saved maps.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_ovr_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)
        columns = dataset.column_info
        assert await _column_exists(test_db_session, table_name, "geom_4326")

        # -overwrite, simulated exactly: same name, source column only.
        await test_db_session.execute(text(f'DROP TABLE data."{table_name}" CASCADE'))
        await test_db_session.execute(
            text(
                f'CREATE TABLE data."{table_name}" ('
                f"  gid serial PRIMARY KEY, name text, "
                f"  geom geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f'INSERT INTO data."{table_name}" (name, geom) '  # noqa: S608
                f"VALUES ('rewritten', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
            ),
            {"lon": _THERE[0], "lat": _THERE[1]},
        )
        # ogr2ogr's new table carries no grant of ours. Revoked explicitly so
        # the assertion does not depend on this cluster's default privileges.
        await test_db_session.execute(
            text(f'REVOKE ALL ON data."{table_name}" FROM geolens_reader')
        )
        await test_db_session.commit()

        assert not await _column_exists(test_db_session, table_name, "geom_4326")
        assert not await _has_gist_index(test_db_session, table_name)
        assert not await _reader_can_select(test_db_session, table_name)

        await _refresh(test_db_session, client, admin_auth_header, dataset.id)

        assert await _column_exists(test_db_session, table_name, "geom_4326")
        assert await _has_gist_index(test_db_session, table_name)
        assert await _reader_can_select(test_db_session, table_name)
        assert await _features_at(test_db_session, table_name, _THERE) == 1
        assert await _tile_at(table_name, _THERE, columns) is not None
    finally:
        await _drop(test_db_session, table_name)


# ---------------------------------------------------------------------------
# Cost: the scan is unconditional, the writes are not
# ---------------------------------------------------------------------------


async def test_a_refresh_that_finds_no_drift_rewrites_no_rows(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """Idempotence, which is what makes this safe to run on every refresh.

    The UPDATE is scoped to rows whose stored value would actually change, so
    a table nobody wrote to costs one sequential scan and no writes — no
    bloat, no autovacuum debt, and a re-derive count an operator can read as
    a drift signal rather than as noise.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_idem_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)
        await test_db_session.commit()

        # Registration has just written the column with the same expression,
        # so even the FIRST repair has nothing to do.
        first = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        assert first.code == tasks_postgis_refresh._REPAIR_REPAIRED
        assert (first.rows_rewritten, first.column_added, first.index_added) == (
            0,
            False,
            False,
        )

        await _refresh(test_db_session, client, admin_auth_header, dataset.id)

        second = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        assert second.code == tasks_postgis_refresh._REPAIR_REPAIRED
        assert second.rows_rewritten == 0
    finally:
        await _drop(test_db_session, table_name)


async def test_only_the_rows_that_moved_are_rewritten(
    test_db_session,
) -> None:
    """A bulk out-of-band reload rewrites exactly its own rows, and no more.

    The size is the point: this is the fixture the repair's cost was measured
    on, and it pins that the count reported back is the number of rows that
    actually changed rather than the table's size.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_bulk_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)

        await test_db_session.execute(
            text(
                f'INSERT INTO data."{table_name}" (name, geom) '  # noqa: S608
                f"SELECT 'bulk-' || i, ST_SetSRID(ST_MakePoint("
                f"  :lon + mod(i, 100) * 0.001, :lat + (i / 100) * 0.001), 4326) "
                f"FROM generate_series(1, 5000) AS i"
            ),
            {"lon": _THERE[0], "lat": _THERE[1]},
        )
        await test_db_session.commit()

        started = time.perf_counter()
        report = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        elapsed = time.perf_counter() - started
        print(f"\n#1738 repair of 5000 drifted rows took {elapsed:.3f}s")

        assert report.code == tasks_postgis_refresh._REPAIR_REPAIRED
        # The one pre-existing row was already correct.
        assert report.rows_rewritten == 5000

        again = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        assert again.rows_rewritten == 0
    finally:
        await _drop(test_db_session, table_name)


# ---------------------------------------------------------------------------
# The deadline, and what happens when it fires
# ---------------------------------------------------------------------------


async def test_the_repair_runs_under_a_statement_deadline_and_gives_up_quietly(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
) -> None:
    """The worker has no statement timeout, so the repair installs its own.

    ``install_api_statement_timeout`` is an API-process concern, so a worker
    UPDATE on a relation GeoLens does not own would otherwise hold locks on
    somebody else's table indefinitely. When the deadline fires the refresh
    must still do the job it was asked to do — re-measure — and report the
    repair as incomplete, rather than turning a metadata recount into a new
    way for this strategy to fail.

    The deadline is proven by making the repair sleep past it, which is also
    what proves ``SET LOCAL`` reached the session that runs the repair: with
    no deadline installed the sleep simply succeeds.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_slow_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    async def _sleepy_rederive(session, *args, **kwargs):
        await session.execute(text("SELECT pg_sleep(5)"))
        raise AssertionError("the statement deadline should have fired")

    try:
        dataset = await _register(test_db_session, table_name, admin_id)

        monkeypatch.setattr(tasks_postgis_refresh, "_REPAIR_STATEMENT_TIMEOUT_MS", 250)
        with patch(
            "app.processing.ingest.metadata.rederive_geom_4326",
            new=_sleepy_rederive,
        ):
            report = await tasks_postgis_refresh._repair_geom_4326(
                dataset.id, Dataset, schema="data", role="geolens_reader"
            )
            assert report.code == tasks_postgis_refresh._REPAIR_TIMED_OUT
            assert report.rows_rewritten == 0

            payload = await _refresh(
                test_db_session, client, admin_auth_header, dataset.id
            )

        # The refresh itself completed: the measurement is what the user asked
        # for, and a repair that could not run leaves the dataset exactly as it
        # was rather than failing the run.
        job = (
            await test_db_session.execute(
                select(IngestJob).where(IngestJob.id == uuid.UUID(payload["job_id"]))
            )
        ).scalar_one()
        await test_db_session.refresh(job)
        assert job.status == "complete"

        run = (
            await test_db_session.execute(
                select(DatasetRefreshRun).where(
                    DatasetRefreshRun.dataset_id == dataset.id
                )
            )
        ).scalar_one()
        await test_db_session.refresh(run)
        assert run.status == "succeeded"
    finally:
        await _drop(test_db_session, table_name)


async def test_the_repair_gives_up_its_lock_queue_position_on_a_busy_table(
    test_db_session,
) -> None:
    """Adding the column back takes ACCESS EXCLUSIVE on somebody else's table.

    A lock request that is merely QUEUED already blocks every reader arriving
    behind it, so waiting out the five-minute statement deadline for one would
    stall the owner's own traffic for five minutes in order to fix a column.
    The repair therefore carries a short ``lock_timeout`` as well, gives the
    queue position back, and reports itself blocked; the next refresh tries
    again.

    Staged with a real conflicting lock — a second session holding ACCESS
    SHARE through an open SELECT — because the property is about lock
    conflicts and a mocked one would prove only that the mock was wired up.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_lock_{uuid.uuid4().hex[:10]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)

        # The column is gone (as after -overwrite), so the repair must ALTER.
        await test_db_session.execute(
            text(f'ALTER TABLE data."{table_name}" DROP COLUMN geom_4326')
        )
        await test_db_session.commit()

        with (
            patch.object(tasks_postgis_refresh, "_REPAIR_LOCK_TIMEOUT_MS", 250),
            patch.object(tasks_postgis_refresh, "_REPAIR_STATEMENT_TIMEOUT_MS", 60_000),
        ):
            # This session's SELECT holds ACCESS SHARE for the rest of its
            # transaction, which is exactly what a reader of a live registered
            # table looks like.
            await test_db_session.execute(text(f'SELECT 1 FROM data."{table_name}"'))  # noqa: S608

            started = time.perf_counter()
            report = await tasks_postgis_refresh._repair_geom_4326(
                dataset.id, Dataset, schema="data", role="geolens_reader"
            )
            elapsed = time.perf_counter() - started

        assert report.code == tasks_postgis_refresh._REPAIR_BLOCKED
        # Bounded by the LOCK timeout, not by the statement deadline.
        assert elapsed < 30
        await test_db_session.rollback()
        assert not await _column_exists(test_db_session, table_name, "geom_4326")
    finally:
        await _drop(test_db_session, table_name)


# ---------------------------------------------------------------------------
# The grant and the index are not conditional on the re-derive
# ---------------------------------------------------------------------------


async def test_a_recreated_generated_column_gets_its_index_and_grant_back(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """The GRANT and the INDEX are the other two things `-overwrite` destroys.

    Losing them does not depend on the render column needing a rewrite. A
    table recreated with a valid STORED GENERATED `geom_4326` re-derives
    itself on every write, so the repair has nothing to do to the column — and
    gating the other two restorations on the re-derive let exactly that table
    pass a refresh unreadable by `geolens_reader` (fix(#1738 round 1)) and
    with no GiST index behind the `geom_4326 && <envelope>` predicate every
    reader issues (fix(#1738 round 2)).

    A generated column is the case that isolates them: it is the one shape
    where the render values are already correct and the two things around
    them are still missing.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_gengr_{uuid.uuid4().hex[:8]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)

        # -overwrite, into a table whose render column is generated.
        await test_db_session.execute(text(f'DROP TABLE data."{table_name}" CASCADE'))
        await test_db_session.execute(
            text(
                f'CREATE TABLE data."{table_name}" ('
                f"  gid serial PRIMARY KEY, name text,"
                f"  geom geometry(Point, 4326),"
                f"  geom_4326 geometry(Geometry, 4326) GENERATED ALWAYS AS "
                f"    (ST_Force2D(ST_CurveToLine(ST_SetSRID(geom, 4326)))) STORED)"
            )
        )
        await test_db_session.execute(
            text(
                f'INSERT INTO data."{table_name}" (name, geom) '  # noqa: S608
                f"VALUES ('generated', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
            ),
            {"lon": _THERE[0], "lat": _THERE[1]},
        )
        await test_db_session.execute(
            text(f'REVOKE ALL ON data."{table_name}" FROM geolens_reader')
        )
        await test_db_session.commit()

        # A freshly created table carries neither: CREATE TABLE makes no
        # index, and the grant was revoked above.
        assert not await _reader_can_select(test_db_session, table_name)
        assert not await _has_gist_index(test_db_session, table_name)

        report = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        # Nothing to re-derive, and both of the others restored anyway.
        assert report.code == tasks_postgis_refresh._REPAIR_NOT_APPLICABLE
        assert report.rows_rewritten == 0
        assert report.index_added is True
        assert await _reader_can_select(test_db_session, table_name)
        assert await _has_gist_index(test_db_session, table_name)

        # And through the real refresh, which must not fail on it either.
        await _refresh(test_db_session, client, admin_auth_header, dataset.id)
        assert await _reader_can_select(test_db_session, table_name)
        assert await _has_gist_index(test_db_session, table_name)
        assert await _features_at(test_db_session, table_name, _THERE) == 1
    finally:
        await _drop(test_db_session, table_name)


async def test_a_registered_non_spatial_table_is_not_a_repair_failure(
    test_db_session,
) -> None:
    """fix(#1738 round 1): `Find_SRID` raises; it does not return NULL.

    Registration admits tables with no geometry (#1359), and resolving the
    source SRID before knowing whether there IS one turned every refresh of
    such a dataset into a logged repair failure — which also skipped the
    reader grant. The SRID is resolved only once the probe says there is a
    geometry column to resolve it for.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_flatreg_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table_name}" '
            f"(gid serial PRIMARY KEY, code text, population integer)"
        )
    )
    await test_db_session.execute(
        text(
            f'INSERT INTO data."{table_name}" (code, population) '  # noqa: S608
            f"VALUES ('a', 1)"
        )
    )
    await test_db_session.commit()

    try:
        dataset = await _register(test_db_session, table_name, admin_id)
        await test_db_session.execute(
            text(f'REVOKE ALL ON data."{table_name}" FROM geolens_reader')
        )
        await test_db_session.commit()

        report = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        assert report.code == tasks_postgis_refresh._REPAIR_NOT_APPLICABLE
        assert report.code != tasks_postgis_refresh._REPAIR_FAILED
        # The grant reaches an attribute table too — registration grants it.
        assert await _reader_can_select(test_db_session, table_name)
        assert not await _column_exists(test_db_session, table_name, "geom_4326")
    finally:
        await _drop(test_db_session, table_name)


# ---------------------------------------------------------------------------
# The version bump survives a writer that does not lock
# ---------------------------------------------------------------------------


async def test_the_version_bump_does_not_lose_a_concurrent_increment(
    test_db_session,
) -> None:
    """fix(#1738 round 1): the counter is incremented in the database.

    The repair holds no lock on the datasets row, and the feature-edit
    routers roll the counter through a plain read-modify-write without one
    either — so an absolute value computed from an earlier read lands on top
    of whatever committed in between. Staged here as that exact shape: a
    stale in-memory value written after the repair's increment, then the
    repair again. `tile_cache_version = tile_cache_version + 1` evaluated at
    write time cannot be clobbered by the read it never took.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    table_name = f"rd_bump_{uuid.uuid4().hex[:8]}"
    await _create_source_table(test_db_session, table_name, lon=_HERE[0], lat=_HERE[1])

    try:
        dataset = await _register(test_db_session, table_name, admin_id)

        await test_db_session.execute(
            text(
                f'UPDATE data."{table_name}" '  # noqa: S608
                f"SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
            ),
            {"lon": _THERE[0], "lat": _THERE[1]},
        )
        await test_db_session.commit()

        before = await _stored_version(test_db_session, dataset.id)
        first = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        # The report carries the version the increment actually published,
        # read back from the UPDATE rather than computed in Python.
        assert first.rows_rewritten == 1
        assert first.tile_cache_version == before + 1
        assert await _stored_version(test_db_session, dataset.id) == before + 1

        # A second drifting write, and a repair whose increment is evaluated
        # against the row as it stands rather than against `before`.
        await test_db_session.execute(
            text(
                f'UPDATE data."{table_name}" '  # noqa: S608
                f"SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"
            ),
            {"lon": _HERE[0], "lat": _HERE[1]},
        )
        await test_db_session.commit()

        second = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        assert second.tile_cache_version == before + 2
        assert await _stored_version(test_db_session, dataset.id) == before + 2

        # And a pass that rewrites nothing publishes no new version.
        third = await tasks_postgis_refresh._repair_geom_4326(
            dataset.id, Dataset, schema="data", role="geolens_reader"
        )
        assert (third.rows_rewritten, third.tile_cache_version) == (0, None)
        assert await _stored_version(test_db_session, dataset.id) == before + 2
    finally:
        await _drop(test_db_session, table_name)


# ---------------------------------------------------------------------------
# The two tables the repair must not write to
# ---------------------------------------------------------------------------


async def test_a_generated_render_column_is_skipped_rather_than_written(
    test_db_session,
) -> None:
    """PostgreSQL rejects any non-DEFAULT write to a generated column.

    Same refusal ``linearize_existing_4326`` makes, and for the same reason:
    such a column re-derives itself on every write, so there is nothing to
    repair and an UPDATE would fail at parse time even with a WHERE that
    matches no rows.
    """
    from app.processing.ingest.metadata import REPAIR_GENERATED, rederive_geom_4326

    table_name = f"rd_gen_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(
            f'CREATE TABLE data."{table_name}" ('
            f"  gid serial PRIMARY KEY,"
            f"  geom geometry(Point, 4326),"
            f"  geom_4326 geometry(Geometry, 4326) GENERATED ALWAYS AS "
            f"    (ST_Force2D(ST_CurveToLine(ST_SetSRID(geom, 4326)))) STORED"
            f")"
        )
    )
    await test_db_session.commit()

    try:
        repair = await rederive_geom_4326(test_db_session, table_name, 4326)
        assert repair.outcome == REPAIR_GENERATED
        assert repair.rows_rewritten == 0
    finally:
        await _drop(test_db_session, table_name)


async def test_a_table_with_no_geometry_is_skipped(test_db_session) -> None:
    """Registration admits attribute tables (#1359); the repair must too.

    A spatial table whose geometry hides under another name is refused at
    registration (#1737), so "no geom column" here means a legitimately
    non-spatial dataset rather than a broken one.
    """
    from app.processing.ingest.metadata import REPAIR_NO_GEOMETRY, rederive_geom_4326

    table_name = f"rd_flat_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(f'CREATE TABLE data."{table_name}" (gid serial PRIMARY KEY, code text)')
    )
    await test_db_session.commit()

    try:
        repair = await rederive_geom_4326(test_db_session, table_name, 4326)
        assert repair.outcome == REPAIR_NO_GEOMETRY
        assert (repair.column_added, repair.rows_rewritten) == (False, 0)
        assert not await _column_exists(test_db_session, table_name, "geom_4326")
    finally:
        await _drop(test_db_session, table_name)
