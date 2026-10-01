"""GeoParquet export writes bounded batches instead of holding the selection.

The row stream used to collect every selected row into Python lists and build
one Arrow table from them, so memory grew with the selection while the row cap
only bounded its count. These tests pin the replacement: rows are cut into
batches by count and by approximate bytes, each batch is appended to one file,
and a column whose Arrow type is still undecided when an early batch is
written does not break the file.

Everything except the last test is DB-free: a fake cursor stands in for the
database so batch boundaries are exact.
"""

import asyncio
import datetime
import decimal
import os
import threading
import time
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import text

from app.processing.export import parquet as export_parquet_module
from app.processing.export.parquet import (
    ParquetExportPlan,
    _GeoParquetWriter,
    _stream_batches,
    export_parquet,
    plan_parquet_export,
)

Decimal = decimal.Decimal


class _Cursor:
    """An async row source that counts how many rows have been pulled."""

    def __init__(self, rows: list[tuple]):
        self._rows = rows
        self.pulled = 0

    def __aiter__(self):
        return self._pull()

    async def _pull(self):
        for row in self._rows:
            self.pulled += 1
            yield row


class _FakeDb:
    def __init__(self, cursor: _Cursor):
        self.cursor = cursor

    async def stream(self, statement):
        return self.cursor


def _plan(*attr_names: str) -> ParquetExportPlan:
    return ParquetExportPlan(attr_names=list(attr_names), where_sql="TRUE", params={})


def _rows(count: int) -> list[tuple]:
    return [(i, f"name-{i}", b"\x01\x02") for i in range(count)]


@pytest.fixture
def staging(monkeypatch, tmp_path):
    monkeypatch.setattr(
        export_parquet_module.settings, "upload_staging_dir", str(tmp_path)
    )
    return tmp_path


async def _batches(db, attr_names):
    return [
        (geom, cols)
        async for geom, cols in _stream_batches(
            db, "SELECT 1", {}, attr_names, len(attr_names)
        )
    ]


class TestStreamBatches:
    @pytest.mark.anyio
    async def test_a_batch_ends_at_the_row_bound(self, monkeypatch):
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", 10)
        db = _FakeDb(_Cursor(_rows(25)))

        batches = await _batches(db, ["pop", "name"])

        assert [len(geom) for geom, _ in batches] == [10, 10, 5]
        assert [pop for _, cols in batches for pop in cols["pop"]] == list(range(25))
        assert [g for geom, _ in batches for g in geom] == [b"\x01\x02"] * 25

    @pytest.mark.anyio
    async def test_a_batch_ends_at_the_byte_bound(self, monkeypatch):
        """A few very wide rows must flush early; the row bound alone would let
        them pile up to 100k rows of megabyte values."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_BYTES", 2_500)
        wide = [(i, "x" * 1_000, b"\x01") for i in range(10)]
        db = _FakeDb(_Cursor(wide))

        batches = await _batches(db, ["pop", "name"])

        sizes = [len(geom) for geom, _ in batches]
        assert sum(sizes) == 10
        assert max(sizes) <= 3, sizes
        assert len(sizes) > 1

    @pytest.mark.anyio
    async def test_array_values_count_their_elements(self, monkeypatch):
        """A shallow size of a list hides the text inside it."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_BYTES", 2_500)
        rows = [(i, ["y" * 1_000, "y" * 1_000], b"\x01") for i in range(6)]
        db = _FakeDb(_Cursor(rows))

        batches = await _batches(db, ["pop", "tags"])

        assert max(len(geom) for geom, _ in batches) <= 2

    @pytest.mark.anyio
    async def test_an_empty_selection_yields_no_batch(self):
        assert await _batches(_FakeDb(_Cursor([])), ["pop", "name"]) == []

    @pytest.mark.anyio
    async def test_null_geometry_stays_null(self):
        db = _FakeDb(_Cursor([(1, "a", None), (2, "b", b"\x01")]))

        [(geom, _)] = await _batches(db, ["pop", "name"])

        assert geom == [None, b"\x01"]


class TestExportStreams:
    @pytest.mark.anyio
    async def test_the_selection_is_never_held_whole(self, monkeypatch, staging):
        """The file is written while the cursor is still being read: each write
        sees at most one batch, and the cursor is only a batch further along."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", 10)
        cursor = _Cursor(_rows(25))
        seen: list[tuple[int, int]] = []
        real_write = _GeoParquetWriter.write

        def _spy(self, geom, cols):
            seen.append((len(geom), cursor.pulled))
            return real_write(self, geom, cols)

        monkeypatch.setattr(_GeoParquetWriter, "write", _spy)

        path, _filename, _media_type = await export_parquet(
            _FakeDb(cursor),
            "roads",
            "Roads",
            schema="data",
            plan=_plan("pop", "name"),
        )

        assert seen == [(10, 10), (10, 20), (5, 25)]
        written = pq.ParquetFile(path)
        assert written.metadata.num_row_groups == 3
        assert written.read().column("pop").to_pylist() == list(range(25))

    @pytest.mark.anyio
    async def test_cancelling_mid_write_drains_the_thread_and_removes_the_file(
        self, monkeypatch, staging
    ):
        finished = {"write": False}
        started = threading.Event()

        def _slow_write(self, geom, cols):
            started.set()
            time.sleep(0.2)
            finished["write"] = True

        monkeypatch.setattr(_GeoParquetWriter, "write", _slow_write)
        task = asyncio.create_task(
            export_parquet(
                _FakeDb(_Cursor(_rows(3))),
                "roads",
                "Roads",
                schema="data",
                plan=_plan("pop", "name"),
            )
        )
        await asyncio.to_thread(started.wait, 10)  # the batch is in the writer thread
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert finished["write"], "scratch files were removed under a live writer"
        assert os.listdir(staging / "exports") == []

    @pytest.mark.anyio
    async def test_a_failed_write_removes_the_scratch_directory(
        self, monkeypatch, staging
    ):
        def _broken_write(self, geom, cols):
            raise OSError("disk full")

        monkeypatch.setattr(_GeoParquetWriter, "write", _broken_write)

        with pytest.raises(OSError, match="disk full"):
            await export_parquet(
                _FakeDb(_Cursor(_rows(3))),
                "roads",
                "Roads",
                schema="data",
                plan=_plan("pop", "name"),
            )

        assert os.listdir(staging / "exports") == []

    @pytest.mark.anyio
    async def test_an_empty_selection_is_a_valid_empty_geoparquet(self, staging):
        path, _filename, _media_type = await export_parquet(
            _FakeDb(_Cursor([])),
            "roads",
            "Roads",
            schema="data",
            plan=_plan("pop", "name"),
        )

        table = pq.read_table(path)
        assert table.num_rows == 0
        assert table.column_names == ["pop", "name", "geometry"]
        assert b"geo" in table.schema.metadata


def _write_batches(path, attr_names, batches):
    writer = _GeoParquetWriter(str(path), attr_names, "geometry")
    for cols in batches:
        count = len(next(iter(cols.values())))
        writer.write([b"\x01"] * count, cols)
    writer.close()
    return pq.ParquetFile(str(path))


class TestFileSchemaStaysStable:
    def test_steady_columns_are_appended_without_reencoding(
        self, monkeypatch, tmp_path
    ):
        def _no_reencode(self, writer, schema):
            raise AssertionError("a column whose type held steady was re-encoded")

        monkeypatch.setattr(_GeoParquetWriter, "_reencode", _no_reencode)

        written = _write_batches(
            tmp_path / "out.parquet",
            ["pop", "price"],
            [
                {"pop": [1, 2], "price": [Decimal("1.50"), Decimal("2.25")]},
                {"pop": [3], "price": [Decimal("3.00")]},
            ],
        )

        assert written.metadata.num_row_groups == 2
        assert written.read().column("pop").to_pylist() == [1, 2, 3]

    def test_a_column_null_in_early_batches_takes_its_later_type(self, tmp_path):
        written = _write_batches(
            tmp_path / "out.parquet",
            ["note"],
            [{"note": [None, None]}, {"note": ["a", None]}],
        )

        table = written.read()
        assert table.schema.field("note").type == pa.string()
        assert table.column("note").to_pylist() == [None, None, "a", None]
        assert written.metadata.num_row_groups == 2

    def test_decimals_widen_to_hold_the_digits_of_every_batch(self, tmp_path):
        written = _write_batches(
            tmp_path / "out.parquet",
            ["price"],
            [
                {"price": [Decimal("1.50")]},
                {"price": [Decimal("99999999.99")]},
                {"price": [Decimal("123.4567")]},
            ],
        )

        table = written.read()
        assert pa.types.is_decimal(table.schema.field("price").type)
        assert table.column("price").to_pylist() == [
            Decimal("1.5000"),
            Decimal("99999999.9900"),
            Decimal("123.4567"),
        ]

    def test_a_list_of_nulls_takes_its_later_element_type(self, tmp_path):
        written = _write_batches(
            tmp_path / "out.parquet",
            ["tags"],
            [{"tags": [[], []]}, {"tags": [[1, 2], []]}],
        )

        table = written.read()
        assert table.schema.field("tags").type == pa.list_(pa.int64())
        assert table.column("tags").to_pylist() == [[], [], [1, 2], []]

    def test_json_objects_with_different_keys_merge_into_one_struct(self, tmp_path):
        written = _write_batches(
            tmp_path / "out.parquet",
            ["doc"],
            [{"doc": [{"a": 1}]}, {"doc": [{"b": "x"}]}],
        )

        table = written.read()
        assert table.schema.field("doc").type == pa.struct(
            [("a", pa.int64()), ("b", pa.string())]
        )
        assert table.column("doc").to_pylist() == [
            {"a": 1, "b": None},
            {"a": None, "b": "x"},
        ]

    def test_decimal_arrays_widen_their_elements(self, tmp_path):
        written = _write_batches(
            tmp_path / "out.parquet",
            ["amounts"],
            [{"amounts": [[Decimal("1.50")]]}, {"amounts": [[Decimal("99999.99")]]}],
        )

        assert written.read().column("amounts").to_pylist() == [
            [Decimal("1.50")],
            [Decimal("99999.99")],
        ]

    def test_batches_that_disagree_fall_back_to_string(self, tmp_path):
        written = _write_batches(
            tmp_path / "out.parquet",
            ["weird"],
            [{"weird": [1, 2]}, {"weird": [{"nested": True}]}],
        )

        table = written.read()
        assert table.schema.field("weird").type == pa.string()
        values = table.column("weird").to_pylist()
        assert values[:2] == ["1", "2"]
        assert "nested" in values[2]

    def test_the_geo_metadata_and_geometry_survive_a_reencode(self, tmp_path):
        out = tmp_path / "out.parquet"
        writer = _GeoParquetWriter(str(out), ["note"], "geometry")
        writer.write([b"\x01", None], {"note": [None, None]})
        writer.write([b"\x02"], {"note": ["late"]})
        writer.close()

        table = pq.read_table(out)
        assert b"geo" in table.schema.metadata
        assert table.column("geometry").to_pylist() == [b"\x01", None, b"\x02"]
        assert sorted(os.listdir(tmp_path)) == ["out.parquet"], (
            "the previous file was left behind"
        )

    def test_dates_and_timestamps_keep_their_native_types(self, tmp_path):
        written = _write_batches(
            tmp_path / "out.parquet",
            ["day", "seen"],
            [
                {
                    "day": [datetime.date(2020, 1, 15)],
                    "seen": [datetime.datetime(2020, 1, 15, 1, 2, 3)],
                },
                {
                    "day": [datetime.date(2021, 2, 1)],
                    "seen": [datetime.datetime(2021, 2, 1, 4, 5, 6)],
                },
            ],
        )

        schema = written.schema_arrow
        assert pa.types.is_date(schema.field("day").type)
        assert pa.types.is_timestamp(schema.field("seen").type)


class TestRealTable:
    @pytest.mark.anyio
    async def test_a_table_with_late_types_exports_in_batches_without_loss(
        self, test_db_session, monkeypatch, staging
    ):
        """End to end through the planner and the real cursor: a sparse text
        column and growing decimals decide their types after the first batch."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", 10)
        table_name = f"exp_pqstream_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} "
                "(gid serial PRIMARY KEY, pop integer, price numeric(14,2), "
                "note text, geom geometry(Point, 4326), "
                "geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (pop, price, note, geom, geom_4326) "
                "SELECT i, power(10::numeric, i / 3) + 0.25, "
                "CASE WHEN i < 15 THEN NULL ELSE 'n' || i END, "
                "ST_SetSRID(ST_MakePoint(i, i), 4326), "
                "ST_SetSRID(ST_MakePoint(i, i), 4326) "
                "FROM generate_series(0, 24) AS i"
            )
        )
        await test_db_session.commit()
        try:
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            path, _filename, _media_type = await export_parquet(
                test_db_session,
                table_name,
                "Streamed",
                schema="data",
                plan=plan,
            )
            expected = (
                await test_db_session.execute(
                    text(f"SELECT pop, price, note FROM data.{table_name} ORDER BY pop")
                )
            ).all()

            written = pq.ParquetFile(path)
            table = written.read()
            exported = sorted(
                zip(
                    table.column("pop").to_pylist(),
                    table.column("price").to_pylist(),
                    table.column("note").to_pylist(),
                )
            )

            assert written.metadata.num_row_groups == 3
            assert table.num_rows == 25
            assert [tuple(row) for row in expected] == exported
            assert table.schema.field("note").type == pa.string()
            assert b"geo" in table.schema.metadata
        finally:
            # The export's cursor holds the table open until the transaction ends.
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.commit()
