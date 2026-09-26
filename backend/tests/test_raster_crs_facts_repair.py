"""Migration 0073 adds empty CRS facts, and the worker's repair job fills them."""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import rasterio.crs
import sqlalchemy as sa
import structlog
from procrastinate.exceptions import AlreadyEnqueued

from app.core.geo import wkt_crs_facts
from app.processing.ingest import tasks_crs_facts
from app.processing.ingest.tasks_common import task_app
from app.processing.raster import probe
from app.processing.raster.models import RasterAsset

from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query,
    run_alembic,
)
from tests.factories import create_dataset, create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio

_FACTS = ("crs_is_geographic", "crs_has_degree_unit", "crs_metres_per_unit")
_WGS84 = rasterio.crs.CRS.from_epsg(4326).to_wkt(version="WKT2_2019")
_FEET = rasterio.crs.CRS.from_epsg(2263).to_wkt(version="WKT2_2019")
_GRADS = rasterio.crs.CRS.from_epsg(4807).to_wkt()
# Truncated, so PROJ refuses it and the keyword sniff answers.
_TRUNCATED = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84"'


async def _seed(session, crs_wkt: str | None) -> uuid.UUID:
    """One raster row holding ``crs_wkt`` and no facts, as the old writers left it."""
    dataset = await create_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name=f"crs facts repair {uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="scene.tif",
    )
    asset_id = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO catalog.raster_assets (id, dataset_id, asset_uri, crs_wkt) "
            "VALUES (:id, :dataset_id, :asset_uri, :crs_wkt)"
        ),
        {
            "id": asset_id,
            "dataset_id": dataset.id,
            "asset_uri": f"rasters/{asset_id}/source.cog.tif",
            "crs_wkt": crs_wkt,
        },
    )
    await session.commit()
    return asset_id


async def _stored(ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple]:
    rows = await fresh_query(
        f"SELECT id, {', '.join(_FACTS)} FROM catalog.raster_assets "
        "WHERE id = ANY(:ids)",
        {"ids": ids},
    )
    return {row.id: tuple(getattr(row, name) for name in _FACTS) for row in rows}


def _expected(crs_wkt: str) -> tuple:
    facts = wkt_crs_facts(crs_wkt)
    return tuple(facts[name] for name in _FACTS)


async def _delete(ids: list[uuid.UUID]) -> None:
    await fresh_query(
        "DELETE FROM catalog.raster_assets WHERE id = ANY(:ids)", {"ids": ids}
    )


async def _repair(**bounds):
    return await tasks_crs_facts.repair_missing_crs_facts(
        run_texts=bounds.get("run_texts", 10_000),
        run_seconds=bounds.get("run_seconds", 600.0),
    )


@pytest.fixture
def clock(monkeypatch):
    """A clock the test moves, and a backoff table of this test's own."""
    now = SimpleNamespace(value=1_000_000.0)
    monkeypatch.setattr(tasks_crs_facts, "_clock", lambda: now.value)
    monkeypatch.setattr(tasks_crs_facts, "_backoff", {})
    return now


@pytest.fixture
def child(monkeypatch, clock):
    """The probe child, answered in-process; a text in ``failing`` gets no answer."""
    state = SimpleNamespace(asked=[], failing=set())

    def _many(wkts, timeout=None):
        state.asked.extend(wkts)
        if state.failing & set(wkts):
            raise probe.RasterProbeError("timeout", timeout=30)
        return [wkt_crs_facts(wkt) for wkt in wkts]

    def _one(wkt, timeout=None):
        state.asked.append(wkt)
        if wkt in state.failing:
            raise probe.RasterProbeError("timeout", timeout=30)
        return wkt_crs_facts(wkt)

    monkeypatch.setattr(probe, "crs_facts_many", _many)
    monkeypatch.setattr(probe, "crs_facts", _one)
    return state


@pytest.mark.skipif(
    enterprise_migrations_present(),
    reason=(
        "OSS migration round trip; multi-head under the enterprise overlay — "
        "runs in the no-overlay Pytest Parallel Isolation job instead."
    ),
)
class TestSchemaOnlyMigration:
    async def test_the_upgrade_adds_empty_facts_that_the_job_fills(
        self, test_db_session, clock
    ):
        seeded = {wkt: await _seed(test_db_session, wkt) for wkt in (_WGS84, _FEET)}
        ids = list(seeded.values())
        try:
            down = run_alembic("downgrade", "0072_ingest_job_error_code")
            assert down.returncode == 0, down.stderr
            up = run_alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr

            assert set((await _stored(ids)).values()) == {(None, None, None)}

            await _repair()

            stored = await _stored(ids)
            for wkt, asset_id in seeded.items():
                assert stored[asset_id] == _expected(wkt)
        finally:
            restore = run_alembic("upgrade", "head")
            await _delete(ids)
            assert restore.returncode == 0, restore.stderr


class TestRepairJob:
    async def test_the_job_fills_rows_whose_facts_are_missing(
        self, test_db_session, child
    ):
        seeded = {
            wkt: await _seed(test_db_session, wkt)
            for wkt in (_WGS84, _FEET, _GRADS, _TRUNCATED)
        }
        twin = await _seed(test_db_session, _FEET)
        no_crs = await _seed(test_db_session, None)
        ids = [*seeded.values(), twin, no_crs]
        try:
            await _repair()

            stored = await _stored(ids)
            for wkt, asset_id in seeded.items():
                assert stored[asset_id] == _expected(wkt), wkt
            assert stored[twin] == _expected(_FEET)
            assert stored[no_crs] == (None, None, None)
            assert child.asked.count(_FEET) == 1
        finally:
            await _delete(ids)

    async def test_a_row_an_old_writer_stores_later_is_filled(
        self, test_db_session, child
    ):
        dataset = await create_raster_dataset(
            test_db_session,
            created_by=await get_user_id(test_db_session, "admin"),
            name=f"old writer {uuid.uuid4().hex[:8]}",
            create_raster_asset=True,
            raster_asset_kwargs={"crs_wkt": _FEET},
        )
        asset_id = await test_db_session.scalar(
            sa.select(RasterAsset.id).where(RasterAsset.dataset_id == dataset.id)
        )
        try:
            assert (await _stored([asset_id]))[asset_id] == (None, None, None)

            await _repair()

            assert (await _stored([asset_id]))[asset_id] == _expected(_FEET)
        finally:
            await _delete([asset_id])

    async def test_a_transient_failure_is_filled_on_a_later_run(
        self, test_db_session, child, clock
    ):
        asset_id = await _seed(test_db_session, _FEET)
        child.failing.add(_FEET)
        try:
            first = await _repair()
            assert str(asset_id) in first.unanswered
            assert (await _stored([asset_id]))[asset_id] == (None, None, None)

            child.failing.clear()
            clock.value += tasks_crs_facts.FIRST_BACKOFF_SECONDS + 1
            await _repair()

            assert (await _stored([asset_id]))[asset_id] == _expected(_FEET)
        finally:
            await _delete([asset_id])

    async def test_a_text_that_keeps_failing_stays_unknown_and_backs_off(
        self, test_db_session, child, clock
    ):
        asset_id = await _seed(test_db_session, _GRADS)
        child.failing.add(_GRADS)
        first = tasks_crs_facts.FIRST_BACKOFF_SECONDS
        try:
            asked = []
            for step in (0, 1, first, 1, first, first + 1):
                clock.value += step
                before = child.asked.count(_GRADS)
                await _repair()
                asked.append(child.asked.count(_GRADS) > before)

            # Asked at once, again after 15 minutes, then not for another 30.
            assert asked == [True, False, True, False, False, True]
            assert (await _stored([asset_id]))[asset_id] == (None, None, None)
        finally:
            await _delete([asset_id])

    async def test_one_text_that_stalls_the_batch_does_not_block_the_others(
        self, test_db_session, child
    ):
        stalled = await _seed(test_db_session, _GRADS)
        answered = await _seed(test_db_session, _FEET)
        child.failing.add(_GRADS)
        try:
            outcome = await _repair()

            stored = await _stored([stalled, answered])
            assert stored[answered] == _expected(_FEET)
            assert stored[stalled] == (None, None, None)
            assert outcome.unanswered.count(str(stalled)) == 1
        finally:
            await _delete([stalled, answered])

    async def test_a_child_that_fails_its_control_writes_nothing(
        self, test_db_session, child, monkeypatch
    ):
        asset_id = await _seed(test_db_session, _FEET)

        def _broken(wkts, timeout=None):
            child.asked.extend(wkts)
            raise probe.RasterProbeError("internal", timeout=30)

        monkeypatch.setattr(probe, "crs_facts_many", _broken)
        try:
            outcome = await _repair()

            assert outcome.skipped is True
            assert child.asked == [tasks_crs_facts._CONTROL_WKT]
            assert (await _stored([asset_id]))[asset_id] == (None, None, None)
        finally:
            await _delete([asset_id])

    async def test_a_run_stops_at_its_text_bound(self, test_db_session, child):
        await _repair()
        ids = [await _seed(test_db_session, wkt) for wkt in (_WGS84, _FEET)]

        async def _filled() -> int:
            return sum(f != (None, None, None) for f in (await _stored(ids)).values())

        try:
            await _repair(run_texts=1)
            assert await _filled() == 1

            await _repair(run_texts=1)
            assert await _filled() == 2
        finally:
            await _delete(ids)


class TestScheduling:
    def test_the_job_runs_every_fifteen_minutes(self):
        periodic = task_app.periodic_registry.periodic_tasks[
            (tasks_crs_facts.repair_crs_facts.name, "crs-facts-repair")
        ]

        assert periodic.cron == "*/15 * * * *"

    async def test_the_worker_queues_a_run_when_it_starts(self, monkeypatch):
        from app.platform.jobs import worker

        defer = AsyncMock(
            side_effect=[None, AlreadyEnqueued("queued"), ConnectionError("down")]
        )
        monkeypatch.setattr(tasks_crs_facts.repair_crs_facts, "defer_async", defer)

        with structlog.testing.capture_logs() as logs:
            for _ in range(3):
                await worker._queue_crs_facts_repair_safely()

        assert defer.await_count == 3
        # An already queued run is not a failure; only the lost connection is.
        assert [e["event"] for e in logs if e["log_level"] == "warning"] == [
            "crs_facts_repair_queue_failed"
        ]
        assert "await _queue_crs_facts_repair_safely()" in inspect.getsource(
            worker.main
        )
