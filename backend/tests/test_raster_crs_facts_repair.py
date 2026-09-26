"""Migration 0073 adds empty CRS facts, and the worker's repair job fills them."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import sys
import threading
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import rasterio.crs
import sqlalchemy as sa
import structlog
from procrastinate import testing
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.jobs import Status
from sqlalchemy import event

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
from tests.test_raster_probe import _stand_in

pytestmark = pytest.mark.anyio

_FACTS = ("crs_is_geographic", "crs_has_degree_unit", "crs_metres_per_unit")
_WGS84 = rasterio.crs.CRS.from_epsg(4326).to_wkt(version="WKT2_2019")
_FEET = rasterio.crs.CRS.from_epsg(2263).to_wkt(version="WKT2_2019")
_GRADS = rasterio.crs.CRS.from_epsg(4807).to_wkt()
# The CRS of _FEET written as WKT1, so the text differs and the facts don't.
_FEET_WKT1 = rasterio.crs.CRS.from_epsg(2263).to_wkt()
# Truncated, so PROJ refuses it and the keyword sniff answers.
_TRUNCATED = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84"'


async def _seed(
    session, crs_wkt: str | None, asset_id: uuid.UUID | None = None
) -> uuid.UUID:
    """One raster row holding ``crs_wkt`` and no facts, as the old writers left it."""
    dataset = await create_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name=f"crs facts repair {uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="scene.tif",
    )
    asset_id = asset_id or uuid.uuid4()
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


async def _write(asset_id: uuid.UUID, crs_wkt: str, facts: tuple = ()) -> None:
    """One UPDATE of the row's text and, when given, its facts."""
    columns = {"crs_wkt": crs_wkt, **dict(zip(_FACTS, facts))}
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    await fresh_query(
        f"UPDATE catalog.raster_assets SET {assignments} WHERE id = :id",
        {**columns, "id": asset_id},
    )


async def _clearing_trigger() -> tuple[bool, bool]:
    """Whether 0073's trigger and its function exist."""
    ((trigger, function),) = await fresh_query(
        "SELECT EXISTS (SELECT 1 FROM pg_trigger "
        "WHERE tgname = 'trg_clear_stale_raster_crs_facts'), "
        "to_regproc('catalog.clear_stale_raster_crs_facts') IS NOT NULL"
    )
    return trigger, function


def _digest(crs_wkt: str) -> str:
    return hashlib.sha256(crs_wkt.encode("utf-8")).hexdigest()


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item)]
    return []


def _batch_fails(wkts, timeout=None):
    """Answers the control and fails every batch."""
    if wkts == [tasks_crs_facts._CONTROL_WKT]:
        return [tasks_crs_facts._CONTROL_FACTS]
    raise probe.RasterProbeError("timeout", timeout=30)


async def _repair(**bounds):
    return await tasks_crs_facts.repair_missing_crs_facts(
        run_texts=bounds.get("run_texts", 10_000),
        run_seconds=bounds.get("run_seconds", 600.0),
    )


async def _every_fifteen_minutes(clock, runs: int) -> None:
    """Run the job ``runs`` times, a cron tick apart on the test's clock."""
    for _ in range(runs):
        started = clock.value
        await tasks_crs_facts.repair_missing_crs_facts()
        clock.value = max(clock.value, started + 15 * 60)


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


@pytest.fixture
def timed_child(monkeypatch, clock):
    """The probe child on the test's clock; ``stalls`` use up each timeout they get."""
    state = SimpleNamespace(stalls=set(), seconds=0.5, started=[])

    def _run(wkts, timeout):
        state.started.append(clock.value)
        if state.stalls & set(wkts) or state.seconds > timeout:
            clock.value += timeout
            raise probe.RasterProbeError("timeout", timeout=timeout)
        clock.value += state.seconds
        return [wkt_crs_facts(wkt) for wkt in wkts]

    monkeypatch.setattr(
        probe, "crs_facts_many", lambda wkts, timeout=None: _run(wkts, timeout)
    )
    monkeypatch.setattr(
        probe, "crs_facts", lambda wkt, timeout=None: _run([wkt], timeout)[0]
    )
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
            assert await _clearing_trigger() == (False, False)
            up = run_alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr
            assert await _clearing_trigger() == (True, True)

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

    async def test_a_failed_text_backs_off_before_the_run_goes_on(
        self, test_db_session, clock, monkeypatch
    ):
        ids = [await _seed(test_db_session, wkt) for wkt in (_WGS84, _FEET, _GRADS)]
        asked = []

        def _one(wkt, timeout=None):
            asked.append(wkt)
            if len(asked) == 1:
                raise probe.RasterProbeError("internal", timeout=30)
            raise RuntimeError("the run ends before the batch returns")

        monkeypatch.setattr(probe, "crs_facts_many", _batch_fails)
        monkeypatch.setattr(probe, "crs_facts", _one)
        try:
            with pytest.raises(RuntimeError):
                await _repair()

            assert set(tasks_crs_facts._backoff) == {_digest(asked[0])}
        finally:
            await _delete(ids)

    async def test_a_run_out_of_time_backs_off_only_the_text_it_asked(
        self, test_db_session, clock, monkeypatch
    ):
        ids = [await _seed(test_db_session, wkt) for wkt in (_WGS84, _FEET, _GRADS)]
        asked = []

        def _one(wkt, timeout=None):
            asked.append(wkt)
            clock.value += 3600
            raise probe.RasterProbeError("internal", timeout=30)

        monkeypatch.setattr(probe, "crs_facts_many", _batch_fails)
        monkeypatch.setattr(probe, "crs_facts", _one)
        try:
            await _repair(run_seconds=60)

            assert len(asked) == 1
            assert tasks_crs_facts._backoff.keys() == {_digest(asked[0])}
            assert tasks_crs_facts._backoff[_digest(asked[0])][0] == 1
        finally:
            await _delete(ids)

    async def test_a_text_is_keyed_by_the_sha256_of_its_utf8(
        self, test_db_session, child, clock
    ):
        # Non-ASCII, and a backslash that a text-to-bytea cast would misread.
        wkt = _GRADS.replace('"NTF (Paris)"', '"NTF (Paris) é \\ 中"', 1)
        asset_id = await _seed(test_db_session, wkt)
        child.failing.add(wkt)
        try:
            await _repair()
            assert _digest(wkt) in tasks_crs_facts._backoff

            child.failing.clear()
            clock.value += tasks_crs_facts.FIRST_BACKOFF_SECONDS + 1
            await _repair()

            assert (await _stored([asset_id]))[asset_id] == _expected(wkt)
        finally:
            await _delete([asset_id])

    async def test_no_statement_binds_a_crs_text(self, test_db_session, child):
        ids = [await _seed(test_db_session, wkt) for wkt in (_WGS84, _FEET, _GRADS)]
        bound = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            bound.extend(_strings(parameters))

        event.listen(sa.engine.Engine, "before_cursor_execute", _record)
        try:
            await _repair()
        finally:
            event.remove(sa.engine.Engine, "before_cursor_execute", _record)
            await _delete(ids)

        # The fill binds the text's digest, so the listener saw the run's writes.
        assert _digest(_FEET) in bound
        assert [value for value in bound if "CS[" in value] == []

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


class TestTextChangesClearStaleFacts:
    async def test_an_old_writers_new_text_clears_the_facts(self, test_db_session):
        asset_id = await _seed(test_db_session, _FEET)
        try:
            await _write(asset_id, _FEET, _expected(_FEET))
            await _write(asset_id, _FEET)
            assert (await _stored([asset_id]))[asset_id] == _expected(_FEET)

            await _write(asset_id, _WGS84)

            assert (await _stored([asset_id]))[asset_id] == (None, None, None)
        finally:
            await _delete([asset_id])

    async def test_new_text_with_new_facts_keeps_them(self, test_db_session):
        asset_id = await _seed(test_db_session, _FEET)
        try:
            await _write(asset_id, _FEET, _expected(_FEET))
            await _write(asset_id, _WGS84, _expected(_WGS84))

            assert (await _stored([asset_id]))[asset_id] == _expected(_WGS84)
        finally:
            await _delete([asset_id])

    async def test_new_text_with_the_same_facts_is_cleared_then_refilled(
        self, test_db_session, child
    ):
        assert _expected(_FEET_WKT1) == _expected(_FEET)
        asset_id = await _seed(test_db_session, _FEET)
        try:
            await _write(asset_id, _FEET, _expected(_FEET))
            await _write(asset_id, _FEET_WKT1, _expected(_FEET_WKT1))
            assert (await _stored([asset_id]))[asset_id] == (None, None, None)

            await _repair()

            assert (await _stored([asset_id]))[asset_id] == _expected(_FEET_WKT1)
        finally:
            await _delete([asset_id])


class TestRunBudget:
    async def test_a_staller_ahead_of_valid_rows_is_backed_off_and_they_fill(
        self, test_db_session, timed_child, clock
    ):
        staller = await _seed(test_db_session, _GRADS, uuid.UUID(int=1))
        valid = {
            wkt: await _seed(test_db_session, wkt, uuid.UUID(int=2 + i))
            for i, wkt in enumerate((_WGS84, _FEET, _FEET_WKT1))
        }
        timed_child.stalls.add(_GRADS)
        try:
            await _every_fifteen_minutes(clock, runs=1)
            assert _digest(_GRADS) in tasks_crs_facts._backoff

            await _every_fifteen_minutes(clock, runs=1)

            stored = await _stored([staller, *valid.values()])
            assert stored[staller] == (None, None, None)
            for wkt, asset_id in valid.items():
                assert stored[asset_id] == _expected(wkt)
        finally:
            await _delete([staller, *valid.values()])

    async def test_a_staller_mid_batch_is_backed_off_and_the_rows_after_it_fill(
        self, test_db_session, timed_child, clock
    ):
        ids = {
            wkt: await _seed(test_db_session, wkt, uuid.UUID(int=1 + i))
            for i, wkt in enumerate((_WGS84, _GRADS, _FEET))
        }
        timed_child.stalls.add(_GRADS)
        try:
            await _every_fifteen_minutes(clock, runs=2)

            stored = await _stored(list(ids.values()))
            assert _digest(_GRADS) in tasks_crs_facts._backoff
            assert stored[ids[_GRADS]] == (None, None, None)
            assert stored[ids[_WGS84]] == _expected(_WGS84)
            assert stored[ids[_FEET]] == _expected(_FEET)
        finally:
            await _delete(list(ids.values()))

    @pytest.mark.parametrize("seconds", [0.5, 9.5, 29.5])
    async def test_a_run_outlasts_its_budget_by_at_most_one_probe_timeout(
        self, test_db_session, timed_child, clock, seconds
    ):
        texts = [rasterio.crs.CRS.from_epsg(32601 + i).to_wkt() for i in range(6)]
        ids = [
            await _seed(test_db_session, wkt, uuid.UUID(int=1 + i))
            for i, wkt in enumerate(texts)
        ]
        timed_child.stalls.update(texts[3:])
        timed_child.seconds = seconds
        deadline = clock.value + tasks_crs_facts.RUN_SECONDS
        try:
            await tasks_crs_facts.repair_missing_crs_facts()

            assert max(timed_child.started) < deadline
            assert clock.value <= deadline + probe.CRS_FACTS_TIMEOUT_SECONDS
            # A text asked alone near the deadline still gets a full timeout.
            assert set(tasks_crs_facts._backoff) <= {_digest(t) for t in texts[3:]}
        finally:
            await _delete(ids)

    @pytest.mark.parametrize("batch_texts", [1, 2])
    async def test_a_batch_the_budget_cuts_short_blames_no_text(
        self, test_db_session, timed_child, clock, monkeypatch, batch_texts
    ):
        monkeypatch.setattr(tasks_crs_facts, "BATCH_TEXTS", batch_texts)
        ids = {
            wkt: await _seed(test_db_session, wkt, uuid.UUID(int=1 + i))
            for i, wkt in enumerate((_WGS84, _FEET, _GRADS, _FEET_WKT1))
        }
        timed_child.stalls.add(_GRADS)
        # 16 s answers leave the batch holding the staller under a full timeout.
        timed_child.seconds = 16
        try:
            await _every_fifteen_minutes(clock, runs=1)
            assert tasks_crs_facts._backoff == {}

            timed_child.seconds = 0.5
            await _every_fifteen_minutes(clock, runs=2)

            stored = await _stored(list(ids.values()))
            assert _digest(_GRADS) in tasks_crs_facts._backoff
            assert stored[ids[_FEET_WKT1]] == _expected(_FEET_WKT1)
        finally:
            await _delete(list(ids.values()))

    async def test_a_run_ends_within_one_probe_of_its_budget_when_every_probe_stalls(
        self, test_db_session, monkeypatch
    ):
        monkeypatch.setattr(tasks_crs_facts, "_backoff", {})
        ids = [await _seed(test_db_session, wkt) for wkt in (_WGS84, _FEET, _GRADS)]
        control = json.dumps([tasks_crs_facts._CONTROL_WKT])
        reply = json.dumps({"result": [tasks_crs_facts._CONTROL_FACTS]})
        # Answers the control at once and stalls on every other request.
        _stand_in(
            monkeypatch,
            "import sys, time\n"
            f"if sys.stdin.read() == {control!r}:\n"
            f"    print({reply!r})\n"
            "    sys.exit(0)\n"
            "time.sleep(60)\n",
        )
        monkeypatch.setattr(probe, "CRS_FACTS_TIMEOUT_SECONDS", 2)
        try:
            started = time.monotonic()
            await tasks_crs_facts.repair_missing_crs_facts(
                run_texts=10_000, run_seconds=4
            )
            elapsed = time.monotonic() - started

            assert elapsed < 4 + 2 + 1.5, f"a 4 s run took {elapsed:.1f} s"
            # The batch had a full timeout, so the first text asked alone is blamed.
            assert len(tasks_crs_facts._backoff) == 1
            assert set((await _stored(ids)).values()) == {(None, None, None)}
        finally:
            await _delete(ids)

    async def test_a_text_that_stalls_its_batch_is_found_and_backed_off(
        self, test_db_session, monkeypatch
    ):
        monkeypatch.setattr(tasks_crs_facts, "_backoff", {})
        stalls = await _seed(test_db_session, _GRADS)
        answers = await _seed(test_db_session, _FEET)
        # Stalls on anything naming the grads CRS; the real child answers the rest.
        script = (
            "import io, sys, time\n"
            "data = sys.stdin.read()\n"
            "if 'NTF (Paris)' in data:\n"
            "    time.sleep(60)\n"
            "sys.stdin = io.StringIO(data)\n"
            "from app.processing.raster import probe\n"
            "sys.exit(probe.main(sys.argv[1:]))\n"
        )
        monkeypatch.setattr(
            probe, "_command", lambda op, *args: [sys.executable, "-c", script, op]
        )
        monkeypatch.setattr(probe, "CRS_FACTS_TIMEOUT_SECONDS", 2)
        try:
            await tasks_crs_facts.repair_missing_crs_facts(
                run_texts=10_000, run_seconds=20
            )

            stored = await _stored([stalls, answers])
            assert stored[answers] == _expected(_FEET)
            assert stored[stalls] == (None, None, None)
            assert list(tasks_crs_facts._backoff.values())[0][0] == 1
        finally:
            await _delete([stalls, answers])


class TestOneRunAtATime:
    async def test_a_second_worker_does_not_probe_while_a_run_is_going(
        self, test_db_session, clock, monkeypatch
    ):
        asset_id = await _seed(test_db_session, _FEET)
        probing = threading.Event()
        release = threading.Event()
        asked = []

        def _many(wkts, timeout=None):
            asked.append(wkts)
            if len(asked) == 1:
                probing.set()
                release.wait(10)
            return [wkt_crs_facts(wkt) for wkt in wkts]

        monkeypatch.setattr(probe, "crs_facts_many", _many)
        manager = task_app.job_manager

        async def run_next(worker_id: int) -> bool:
            job = await manager.fetch_job(queues=["raster"], worker_id=worker_id)
            if job is None:
                return False
            await task_app.tasks[job.task_name](**job.task_kwargs)
            await manager.finish_job(job, status=Status.SUCCEEDED, delete_job=False)
            return True

        try:
            with task_app.replace_connector(testing.InMemoryConnector()):
                async with task_app.open_async():
                    first, second = [await manager.register_worker() for _ in "ab"]
                    await tasks_crs_facts.repair_crs_facts.defer_async()
                    running = asyncio.create_task(run_next(first))
                    try:
                        await asyncio.to_thread(probing.wait, 10)
                        # The next tick's run, queued while the first is probing.
                        await tasks_crs_facts.repair_crs_facts.defer_async()

                        assert await run_next(second) is False
                        assert len(asked) == 1
                    finally:
                        release.set()
                        assert await running is True
                    assert await run_next(second) is True
        finally:
            await _delete([asset_id])


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
