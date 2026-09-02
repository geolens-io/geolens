"""What a synchronous export is allowed to hold, and for how long.

Two findings from the codebase audit of 2026-08-30 (8dc529f17), tracked in
#1778:

- "The export handler holds an API DB-pool connection open for the entire
  ogr2ogr conversion (up to 1 hour)"
- "Synchronous export runs on a 3600s subprocess deadline behind a 600s edge
  read timeout, and uvicorn never cancels the orphaned handler"

The deadline tests drive the real clock rather than a fake one, by placing the
deadline relative to ``time.monotonic()``: a deadline set 500s out IS a
request that has already spent 100s of its 600s window, and no monkeypatching
of a module the whole process shares is needed to say so. Comparisons are to
the second, which is four orders of magnitude looser than the arithmetic under
test.

The pool test counts checkouts on the app's own engine rather than asserting
on the session object, because the checkout is the resource the finding is
about: a connection the handler is not using is still one the rest of the API
cannot have. It carries its own positive control, so a counter that could
never observe a held connection fails instead of passing vacuously.
"""

import asyncio
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.processing.export import ogr as export_ogr
from app.processing.export.ogr import FORMAT_MAP, ExportError
from app.processing.ingest.ogr import OGR2OGR_FILE_TIMEOUT_SECONDS
from app.processing.ingest.url_fetch import EDGE_PROXY_READ_TIMEOUT_SECONDS

from tests.factories import create_dataset, get_user_id


def _deadline_after(elapsed: float) -> float:
    """The deadline a request would hold ``elapsed`` seconds into its window."""
    return time.monotonic() + EDGE_PROXY_READ_TIMEOUT_SECONDS - elapsed


# ---------------------------------------------------------------------------
# The deadline
# ---------------------------------------------------------------------------


class TestExportSubprocessBudget:
    def test_budget_is_what_is_left_of_the_edge_window(self, monkeypatch):
        """The number comes from the proxy in front, minus time already spent."""
        monkeypatch.setattr(settings, "db_pool_timeout", 30)
        reserve = export_ogr.export_post_work_reserve_seconds()

        budget = export_ogr.export_subprocess_timeout_seconds(_deadline_after(100))

        assert budget == pytest.approx(
            EDGE_PROXY_READ_TIMEOUT_SECONDS - 100 - reserve, abs=1
        )
        # Same claim, spelled out, so a change to the arithmetic has to be
        # argued rather than mirrored: 600 - 100 - (120 + 30).
        assert budget == pytest.approx(350, abs=1)

    def test_unspent_pre_work_time_goes_to_the_conversion(self, monkeypatch):
        """The defect codex r1 named, in both directions.

        A fixed allowance for pool waits that did not happen killed a
        conversion that would have fitted; the same allowance let a request
        whose pre-work really did overrun run on past the edge. Elapsed time
        is what separates the two cases, so the budget has to move with it.
        """
        monkeypatch.setattr(settings, "db_pool_timeout", 30)

        quick = export_ogr.export_subprocess_timeout_seconds(_deadline_after(1))
        slow = export_ogr.export_subprocess_timeout_seconds(_deadline_after(120))

        assert quick - slow == pytest.approx(119, abs=1)

    def test_no_request_clock_assumes_the_whole_window(self, monkeypatch):
        """``None`` is the zero-elapsed case, not a special one."""
        monkeypatch.setattr(settings, "db_pool_timeout", 30)

        assert export_ogr.export_subprocess_timeout_seconds(None) == pytest.approx(
            export_ogr.export_subprocess_timeout_seconds(_deadline_after(0)), abs=1
        )

    def test_budget_shrinks_as_the_pool_timeout_grows(self, monkeypatch):
        """The audit commit's checkout has not happened yet, so it is reserved.

        Derived per call rather than stated once: ``db_pool_timeout`` is
        operator-settable and CI only ever runs the default, so a fixed figure
        would break silently in the field.
        """
        monkeypatch.setattr(settings, "db_pool_timeout", 30)
        at_default = export_ogr.export_subprocess_timeout_seconds(_deadline_after(0))
        monkeypatch.setattr(settings, "db_pool_timeout", 60)
        at_double = export_ogr.export_subprocess_timeout_seconds(_deadline_after(0))

        assert at_default - at_double == pytest.approx(30, abs=1)

    @pytest.mark.parametrize("elapsed", [0, 1, 60, 300, 450])
    @pytest.mark.parametrize("pool_timeout", [1, 5, 30, 60])
    def test_the_rest_of_the_request_fits_inside_the_edge_deadline(
        self, monkeypatch, elapsed, pool_timeout
    ):
        monkeypatch.setattr(settings, "db_pool_timeout", pool_timeout)
        deadline = _deadline_after(elapsed)
        reserve = export_ogr.export_post_work_reserve_seconds()

        budget = export_ogr.export_subprocess_timeout_seconds(deadline)

        if budget > export_ogr.EXPORT_BUDGET_FLOOR_SECONDS:
            finishes_at = time.monotonic() + budget + reserve
            assert finishes_at <= deadline + 1
        else:
            # The floor is the one case that overruns on purpose, and it is
            # reachable only when less than the reserve was left before the
            # conversion could even start. Pinning that condition is what
            # keeps the branch from swallowing a real arithmetic error.
            assert deadline - time.monotonic() < reserve + 1

    def test_pre_work_that_overran_the_deadline_yields_the_floor(self, monkeypatch):
        """A negative remainder is not a deadline, it is a crash.

        The request is lost either way; it is lost through the ordinary
        timeout path with the ordinary error rather than through
        ``asyncio.wait_for`` being handed a negative number.
        """
        monkeypatch.setattr(settings, "db_pool_timeout", 30)

        for elapsed in (EDGE_PROXY_READ_TIMEOUT_SECONDS, 10_000):
            budget = export_ogr.export_subprocess_timeout_seconds(
                _deadline_after(elapsed)
            )
            assert budget == export_ogr.EXPORT_BUDGET_FLOOR_SECONDS
            assert budget > 0

    def test_a_pathological_pool_timeout_warns_once(self, monkeypatch):
        """DB_POOL_TIMEOUT=500 reserves more than the edge window allows."""
        monkeypatch.setattr(export_ogr, "_export_reserve_warned", False)
        monkeypatch.setattr(settings, "db_pool_timeout", 500)

        assert (
            export_ogr.export_subprocess_timeout_seconds(_deadline_after(0))
            == export_ogr.EXPORT_BUDGET_FLOOR_SECONDS
        )
        # The operator gets a cause rather than a mysterious 502. Asserted via
        # the once-only flag: structlog records do not reach caplog.
        assert export_ogr._export_reserve_warned is True

    def test_the_worker_file_timeout_is_not_reachable_from_the_export_path(
        self, monkeypatch
    ):
        """The regression this replaces: importing the offline-ingest bound.

        ``OGR2OGR_FILE_TIMEOUT_SECONDS`` is the Procrastinate worker's, where
        an hour is reasonable because no proxy is waiting. Re-importing it
        here would restore a deadline six times the edge's.
        """
        monkeypatch.setattr(settings, "db_pool_timeout", 30)

        assert not hasattr(export_ogr, "OGR2OGR_FILE_TIMEOUT_SECONDS")
        assert (
            export_ogr.export_subprocess_timeout_seconds(_deadline_after(0))
            < OGR2OGR_FILE_TIMEOUT_SECONDS
        )

    @pytest.mark.anyio
    async def test_remaining_budget_bounds_both_the_child_and_the_query(
        self, monkeypatch, tmp_path
    ):
        """One read, so the wall clock and statement_timeout cannot disagree."""
        monkeypatch.setattr(settings, "db_pool_timeout", 30)
        seen: dict = {}

        async def _capture(*args, env=None, **kwargs):
            seen["env"] = env or {}

            class _Proc:
                returncode = 0

            return _Proc()

        async def _communicate(proc, timeout, *, tool_name):
            seen["timeout"] = timeout
            return b"", b""

        monkeypatch.setattr(export_ogr.asyncio, "create_subprocess_exec", _capture)
        monkeypatch.setattr(export_ogr, "_communicate_with_timeout", _communicate)

        await export_ogr.run_ogr2ogr_export(
            "roads",
            str(tmp_path / "out.geojson"),
            "GeoJSON",
            schema="data",
            deadline=_deadline_after(100),
        )

        reserve = export_ogr.export_post_work_reserve_seconds()
        expected = EDGE_PROXY_READ_TIMEOUT_SECONDS - 100 - reserve
        assert seen["timeout"] == pytest.approx(expected, abs=1)
        # libpq wants an integer number of milliseconds.
        assert seen["env"]["PGOPTIONS"] == (
            f"-c statement_timeout={int(seen['timeout'] * 1000)}"
        )

    @pytest.mark.anyio
    async def test_the_deadline_terminates_the_child(self, monkeypatch, tmp_path):
        """A real subprocess, really reaped, on a deliberately tiny budget.

        The deadline is only worth deriving if reaching it actually stops the
        conversion; a timeout that raised while the child kept running would
        leave exactly the orphan the finding is about.
        """
        real_exec = asyncio.create_subprocess_exec
        spawned: dict = {}

        async def _spawn_sleeper(*args, env=None, **kwargs):
            proc = await real_exec(
                "sleep",
                "30",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            spawned["proc"] = proc
            return proc

        monkeypatch.setattr(
            export_ogr.asyncio, "create_subprocess_exec", _spawn_sleeper
        )
        monkeypatch.setattr(
            export_ogr, "export_subprocess_timeout_seconds", lambda deadline: 0.05
        )

        with pytest.raises(ExportError) as exc:
            await export_ogr.run_ogr2ogr_export(
                "roads", str(tmp_path / "out.geojson"), "GeoJSON", schema="data"
            )

        assert "timed out" in str(exc.value)
        assert spawned["proc"].returncode is not None


# ---------------------------------------------------------------------------
# The pooled connection, and the route's own clock
# ---------------------------------------------------------------------------


class TestExportReleasesThePoolConnection:
    @pytest.mark.anyio
    async def test_nothing_is_checked_out_while_the_conversion_runs(
        self,
        client: AsyncClient,
        test_db_session,
        admin_auth_header: dict,
        monkeypatch,
        tmp_path,
    ):
        import app.core.db as db_module
        from app.processing.export import artifact_cache

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            created_by=admin_id,
            name="PoolReleaseExport",
            visibility="public",
        )

        live = {"n": 0}

        def _on_checkout(dbapi_connection, connection_record, connection_proxy):
            live["n"] += 1

        def _on_checkin(dbapi_connection, connection_record):
            live["n"] -= 1

        sync_engine = db_module.engine.sync_engine
        event.listen(sync_engine, "checkout", _on_checkout)
        event.listen(sync_engine, "checkin", _on_checkin)

        probes: dict = {}
        real_lookup = artifact_cache.lookup

        async def _probing_lookup(*args, **kwargs):
            # Read from inside the handler, after get_dataset and the access
            # checks, before the release. The positive control.
            #
            # setdefault, not assignment: the publish path calls lookup a
            # second time after the conversion, and that later call would
            # otherwise overwrite the control with the released count and make
            # this test pass for the wrong reason.
            probes.setdefault("at_lookup", live["n"])
            return await real_lookup(*args, **kwargs)

        async def _fake_export(
            table_name, dataset_name, format_key, *, schema, **kwargs
        ):
            # Read from where ogr2ogr would be running.
            probes["at_conversion"] = live["n"]
            probes["deadline"] = kwargs.get("deadline")
            probes["observed_at"] = time.monotonic()
            out_dir = tmp_path / uuid.uuid4().hex
            out_dir.mkdir()
            path = out_dir / f"{dataset_name}.gpkg"
            path.write_bytes(b"mock export data")
            return str(path), path.name, FORMAT_MAP["gpkg"]["media"]

        monkeypatch.setattr(artifact_cache, "lookup", _probing_lookup)
        monkeypatch.setattr("app.processing.export.router.export_dataset", _fake_export)

        try:
            baseline = live["n"]
            response = await client.get(
                f"/datasets/{dataset.id}/export",
                params={"format": "gpkg"},
                headers=admin_auth_header,
            )
        finally:
            event.remove(sync_engine, "checkout", _on_checkout)
            event.remove(sync_engine, "checkin", _on_checkin)

        assert response.status_code == 200
        # Positive control: the counter CAN see the handler holding one.
        assert probes["at_lookup"] == baseline + 1
        # The finding: it holds none across the conversion, the hash and the
        # object-store upload.
        assert probes["at_conversion"] == baseline

        # The route hands the conversion its own clock, stamped on entry, so
        # the subprocess is bounded by what is left of the edge window rather
        # than by a fresh allowance. A route that stopped passing it would
        # silently fall back to assuming the whole window.
        assert probes["deadline"] is not None
        remaining = probes["deadline"] - probes["observed_at"]
        assert 0 < remaining <= EDGE_PROXY_READ_TIMEOUT_SECONDS

        # And it re-acquires afterwards: the audit row is the proof that the
        # rolled-back session is still usable, not merely released.
        rows = (
            (
                await test_db_session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "dataset.export",
                        AuditLog.resource_id == dataset.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
