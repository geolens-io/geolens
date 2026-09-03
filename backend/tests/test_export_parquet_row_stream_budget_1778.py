"""GeoParquet's row stream has a wall clock too (#1778, codebase audit 2026-08-30).

fix(#1781) bounded every ogr2ogr export format by what is left of the edge
proxy's read-timeout window (``export_subprocess_timeout_seconds`` in
``export/ogr.py``): a kill-on-timeout for the subprocess plus a matching libpq
``statement_timeout`` on its own connection. GeoParquet (``export/parquet.py``)
has no subprocess — it streams SELECT rows straight into Python lists — and
inherited none of that: an unindexed table or a wide selection could stream
well past the edge's window with nothing to stop it, holding the request open
(and its pooled connection with it) long after nginx had already answered the
client with a 504.

The fix reuses ``export_subprocess_timeout_seconds`` rather than deriving a
second bound, and wraps the row stream in ``asyncio.wait_for`` on that budget,
raising the SAME ``ExportError`` the ogr2ogr timeout raises — so the router's
``except ExportError`` handling (one 500, not a hang past the proxy's own
timeout) is identical for every export format.

Mirrors ``test_export_request_budget.py::TestExportSubprocessBudget::
test_the_deadline_terminates_the_child``, the equivalent test for the ogr2ogr
formats, but with a fake row source instead of a real subprocess — there is no
child process here to reap.
"""

import asyncio
import os
import shutil

import pytest

from app.processing.export import parquet as export_parquet_module
from app.processing.export.ogr import ExportError
from app.processing.export.parquet import ParquetExportPlan, export_parquet


def _plan() -> ParquetExportPlan:
    return ParquetExportPlan(attr_names=["name"], where_sql="TRUE", params={})


class TestParquetRowStreamBudget:
    @pytest.mark.anyio
    async def test_a_slow_row_source_past_the_deadline_raises_export_error(
        self, monkeypatch
    ):
        """A row source that outlives its budget stops the same way the
        ogr2ogr formats do: ``ExportError``, not a hang past the edge proxy's
        own read timeout."""
        monkeypatch.setattr(
            export_parquet_module,
            "export_subprocess_timeout_seconds",
            lambda deadline: 0.05,
        )

        async def _slow_stream_rows(db, sql, params, attr_names, geom_idx):
            await asyncio.sleep(30)
            raise AssertionError(
                "the row source ran to completion instead of being bounded"
            )

        monkeypatch.setattr(export_parquet_module, "_stream_rows", _slow_stream_rows)

        with pytest.raises(ExportError) as exc:
            await export_parquet(
                db=None,
                table_name="roads",
                dataset_name="Roads",
                schema="data",
                plan=_plan(),
            )

        assert "timed out" in str(exc.value)

    @pytest.mark.anyio
    async def test_a_fast_row_source_is_unaffected(self, monkeypatch, tmp_path):
        """Counterfactual: a row source that finishes inside the budget must
        not be treated as timed out, and still produces a real file."""
        monkeypatch.setattr(
            export_parquet_module,
            "export_subprocess_timeout_seconds",
            lambda deadline: 30,
        )
        monkeypatch.setattr(
            export_parquet_module.settings, "upload_staging_dir", str(tmp_path)
        )

        async def _fast_stream_rows(db, sql, params, attr_names, geom_idx):
            return [b"\x01\x02"], {"name": ["a"]}

        monkeypatch.setattr(export_parquet_module, "_stream_rows", _fast_stream_rows)

        file_path, filename, media_type = await export_parquet(
            db=None,
            table_name="roads",
            dataset_name="Roads",
            schema="data",
            plan=_plan(),
        )
        try:
            assert os.path.exists(file_path)
            assert filename.endswith(".parquet")
        finally:
            shutil.rmtree(os.path.dirname(file_path), ignore_errors=True)

    @pytest.mark.anyio
    async def test_no_deadline_reuses_the_ogr2ogr_helper_not_a_second_one(
        self, monkeypatch, tmp_path
    ):
        """The budget must come from ``export_subprocess_timeout_seconds``
        (fix(#1781)'s helper) rather than a parquet-specific reimplementation —
        a second bound could drift from the edge window the first one tracks."""
        calls: list[float | None] = []
        real = export_parquet_module.export_subprocess_timeout_seconds

        def _spy(deadline):
            calls.append(deadline)
            return real(deadline)

        monkeypatch.setattr(
            export_parquet_module, "export_subprocess_timeout_seconds", _spy
        )
        monkeypatch.setattr(
            export_parquet_module.settings, "upload_staging_dir", str(tmp_path)
        )

        async def _fast_stream_rows(db, sql, params, attr_names, geom_idx):
            return [b"\x01"], {"name": ["a"]}

        monkeypatch.setattr(export_parquet_module, "_stream_rows", _fast_stream_rows)

        file_path, _filename, _media_type = await export_parquet(
            db=None,
            table_name="roads",
            dataset_name="Roads",
            schema="data",
            plan=_plan(),
            deadline=None,
        )
        try:
            assert calls == [None]
        finally:
            shutil.rmtree(os.path.dirname(file_path), ignore_errors=True)
