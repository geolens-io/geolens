"""GeoParquet export writes bounded batches instead of holding the selection.

The row stream used to collect every selected row into Python lists and build
one Arrow table from them, so memory grew with the selection while the row cap
only bounded its count. These tests pin the replacement: rows are cut into
batches by count and by approximate bytes, each batch is appended to one file,
and a column whose Arrow type is still undecided when an early batch is
written does not break the file.

Everything outside TestRealTable is DB-free: a fake cursor stands in for the
database so batch boundaries are exact.
"""

import asyncio
import datetime
import decimal
import json
import os
import threading
import time
import tracemalloc
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import text

from app.processing.export import parquet as export_parquet_module
from app.processing.export.ogr import ExportError
from app.processing.export.parquet import (
    ParquetExportPlan,
    _GeoParquetWriter,
    _stream_batches,
    build_geoparquet_table,
    export_parquet,
    plan_parquet_export,
)

Decimal = decimal.Decimal


class _Cursor:
    """An async row source that counts how many rows have been pulled."""

    def __init__(self, rows: list[tuple]):
        self._rows = rows
        self.pulled = 0

    async def fetchmany(self, size: int) -> list[tuple]:
        rows = self._rows[self.pulled : self.pulled + size]
        self.pulled += len(rows)
        return rows


class _NoRows:
    def all(self) -> list:
        return []


class _FakeDb:
    def __init__(self, cursor: _Cursor):
        self.cursor = cursor

    async def execute(self, statement):
        return _NoRows()

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
        monkeypatch.setattr(export_parquet_module, "_FETCH_ROWS", 5)
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
    async def test_a_timeout_while_copying_segments_stops_and_cleans_up(
        self, monkeypatch, staging
    ):
        """The final copy runs within the export's time budget and checks it
        between row groups, so it doesn't finish every group first."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", 1)
        monkeypatch.setattr(
            export_parquet_module,
            "export_subprocess_timeout_seconds",
            lambda deadline: 1.0,
        )
        reads: list[int] = []
        real_read_row_group = pq.ParquetFile.read_row_group

        def _slow_read_row_group(self, i, *args, **kwargs):
            reads.append(i)
            time.sleep(0.5)
            return real_read_row_group(self, i, *args, **kwargs)

        monkeypatch.setattr(pq.ParquetFile, "read_row_group", _slow_read_row_group)
        names = [f"c{i}" for i in range(10)]
        # Each row gives one more column its first value, so each starts a segment.
        rows = [
            tuple(k if j == k else None for j in range(10)) + (b"\x01",)
            for k in range(10)
        ]
        started = time.monotonic()

        with pytest.raises(export_parquet_module.ExportError, match="timed out"):
            await export_parquet(
                _FakeDb(_Cursor(rows)),
                "roads",
                "Roads",
                schema="data",
                plan=_plan(*names),
            )

        assert 0 < len(reads) < 10
        assert time.monotonic() - started < 4
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


def _count_row_group_writes(monkeypatch) -> list[int]:
    """Record the row count of every table any ParquetWriter appends."""
    writes: list[int] = []
    real_write_table = pq.ParquetWriter.write_table

    def _spy(self, table, *args, **kwargs):
        writes.append(table.num_rows)
        return real_write_table(self, table, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetWriter, "write_table", _spy)
    return writes


class TestFileSchemaStaysStable:
    def test_steady_columns_are_appended_without_reencoding(
        self, monkeypatch, tmp_path
    ):
        writes = _count_row_group_writes(monkeypatch)

        written = _write_batches(
            tmp_path / "out.parquet",
            ["pop", "price"],
            [
                {"pop": [1, 2], "price": [Decimal("1.50"), Decimal("2.25")]},
                {"pop": [3], "price": [Decimal("3.00")]},
            ],
        )

        assert writes == [2, 1], "rows were written more than once"
        assert written.metadata.num_row_groups == 2
        assert written.read().column("pop").to_pylist() == [1, 2, 3]

    def test_columns_that_fill_in_batch_by_batch_are_copied_once(
        self, monkeypatch, tmp_path
    ):
        """Each batch gives one more sparse column its first value, widening the
        schema. Rewriting every earlier row at each widening is quadratic in
        the batches; writing segments and copying them once at close is not."""
        names = [f"c{i}" for i in range(50)]
        writes = _count_row_group_writes(monkeypatch)

        written = _write_batches(
            tmp_path / "out.parquet",
            names,
            [
                {name: [k if j == k else None] for j, name in enumerate(names)}
                for k in range(50)
            ],
        )

        assert len(writes) <= 2 * 50
        table = written.read()
        for k, name in enumerate(names):
            assert table.schema.field(name).type == pa.int64()
            assert table.column(name).to_pylist() == [
                k if row == k else None for row in range(50)
            ]
        assert sorted(os.listdir(tmp_path)) == ["out.parquet"]

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

    @pytest.mark.parametrize(
        ("batches", "expected"),
        [
            ([[2**63]], [str(2**63)]),
            ([[1], [2**63]], ["1", str(2**63)]),
            ([[[2**64]]], [f"[{2**64}]"]),
        ],
        ids=["alone", "after-typed-rows", "in-array"],
    )
    def test_integers_past_int64_are_text(self, tmp_path, batches, expected):
        written = _write_batches(
            tmp_path / "out.parquet", ["n"], [{"n": batch} for batch in batches]
        )

        table = written.read()
        assert table.schema.field("n").type == pa.string()
        assert table.column("n").to_pylist() == expected

    @pytest.mark.parametrize(
        "batches",
        [
            [[[Decimal("1.5")], [Decimal("NaN")]]],
            [[[Decimal("1.5")]], [[Decimal("NaN")]]],
        ],
        ids=["one-batch", "split"],
    )
    def test_a_numeric_array_holding_nan_is_json_text(self, tmp_path, batches):
        """Arrow decimals have no NaN, so the column falls back to text."""
        written = _write_batches(
            tmp_path / "out.parquet", ["amounts"], [{"amounts": b} for b in batches]
        )

        assert written.read().column("amounts").to_pylist() == ['["1.5"]', '["NaN"]']

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("values", "batch_rows"),
        [
            ([[1, 2], [[3, 4]]], 1),
            ([[[3, 4]], [1, 2]], 1),
            ([[1, 2], [[3, 4]]], 100_000),
        ],
        ids=["split", "deeper-first", "one-batch"],
    )
    async def test_arrays_of_different_depth_are_json_text(
        self, monkeypatch, staging, values, batch_rows
    ):
        """Rows of one Postgres array column can differ in dimensions. No list
        type holds both, so the column is text however the rows are batched."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", batch_rows)

        path, _filename, _media_type = await export_parquet(
            _FakeDb(_Cursor([(value, b"\x01") for value in values])),
            "roads",
            "Roads",
            schema="data",
            plan=_plan("tags"),
        )

        table = pq.read_table(path)
        assert table.schema.field("tags").type == pa.string()
        assert table.column("tags").to_pylist() == [json.dumps(v) for v in values]

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

    @pytest.mark.anyio
    async def test_json_columns_are_their_json_text_however_batches_split(
        self, test_db_session, monkeypatch, staging
    ):
        """Postgres renders json, jsonb and their arrays, so a value reads the
        same in every batch: numbers keep their digits, a top-level string
        keeps its quotes and JSON null stays apart from SQL NULL."""
        values = [
            "1",
            "1.5",
            '"x"',
            "null",
            None,
            '{"a": 1.50}',
            '[1, {"b": null}]',
            "{}",
        ]
        table_name = f"exp_pqjson_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} (gid serial PRIMARY KEY, i integer, "
                "v jsonb, va jsonb[], vj json, "
                "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (i, v, va, vj, geom, geom_4326) "
                "VALUES (:i, CAST(:v AS jsonb), ARRAY[CAST(:v AS jsonb)], "
                "CAST(:v AS json), ST_SetSRID(ST_MakePoint(0, 0), 4326), "
                "ST_SetSRID(ST_MakePoint(0, 0), 4326))"
            ),
            [{"i": i, "v": v} for i, v in enumerate(values)],
        )
        await test_db_session.commit()

        async def _export(batch_rows: int) -> pa.Table:
            monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", batch_rows)
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            path, _filename, _media_type = await export_parquet(
                test_db_session, table_name, "Json", schema="data", plan=plan
            )
            return pq.read_table(path).sort_by("i")

        try:
            whole = await _export(100_000)
            split = await _export(1)

            for name in ("v", "va", "vj"):
                assert whole.schema.field(name).type == pa.string()
                assert split.column(name).to_pylist() == whole.column(name).to_pylist()
            assert whole.column("v").to_pylist() == values
            assert whole.column("vj").to_pylist() == values
            assert whole.column("va").to_pylist() == [
                "[null]" if v is None else f"[{v}]" for v in values
            ]
            geo = json.loads(whole.schema.metadata[b"geo"])
            assert geo["primary_column"] == "geometry"
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_wide_rows_after_narrow_ones_are_not_prefetched_at_once(
        self, test_db_session, monkeypatch
    ):
        """A fetch is held whole before any of its rows is measured. Sized by
        the 50 narrow rows, or by the driver's growing default buffer, it
        would take most of the 600 wide ones at once."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_BYTES", 1024 * 1024)
        table_name = f"exp_pqwide_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} AS SELECT i, "
                "CASE WHEN i <= 50 THEN 'x' ELSE repeat(md5(i::text), 4096) END AS s "
                "FROM generate_series(1, 650) AS i"
            )
        )
        await test_db_session.commit()
        try:
            tracemalloc.start()
            try:
                rows = 0
                async for geom, _cols in _stream_batches(
                    test_db_session,
                    f"SELECT i, s, NULL::bytea FROM data.{table_name} ORDER BY i",
                    {},
                    ["i", "s"],
                    2,
                ):
                    rows += len(geom)
                    del geom, _cols
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()

            assert rows == 650
            assert peak < 24 * 1024 * 1024, f"peak {peak / 1e6:.1f} MB"
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_column_types_follow_the_table_across_batches(
        self, test_db_session, monkeypatch, staging
    ):
        """Types come from the table, so a NULL-only first batch, whole-number
        decimals and small integers keep their declared type in every batch;
        unconstrained numeric is still inferred."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", 10)
        table_name = f"exp_pqtypes_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} "
                "(gid serial PRIMARY KEY, small smallint, late integer, "
                "price numeric(10,3), loose numeric, ratio double precision, "
                "geom geometry(Point, 4326), "
                "geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} "
                "(small, late, price, loose, ratio, geom, geom_4326) "
                "SELECT i, CASE WHEN i < 15 THEN NULL ELSE i END, "
                "CASE WHEN i < 15 THEN 1 ELSE 1.125 END, i + 0.5, "
                "CASE WHEN i < 15 THEN 2 ELSE 2.5 END, "
                "ST_SetSRID(ST_MakePoint(i, i), 4326), "
                "ST_SetSRID(ST_MakePoint(i, i), 4326) "
                "FROM generate_series(0, 24) AS i"
            )
        )
        await test_db_session.commit()
        try:
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            path, _filename, _media_type = await export_parquet(
                test_db_session, table_name, "Types", schema="data", plan=plan
            )

            written = pq.ParquetFile(path)
            schema = written.schema_arrow
            assert written.metadata.num_row_groups == 3
            assert schema.field("small").type == pa.int16()
            assert schema.field("late").type == pa.int32()
            assert schema.field("price").type == pa.decimal128(10, 3)
            assert pa.types.is_decimal(schema.field("loose").type)
            assert schema.field("ratio").type == pa.float64()
            table = written.read().sort_by("small")
            assert table.column("late").to_pylist()[15:] == list(range(15, 25))
            assert table.column("price").to_pylist()[0] == Decimal("1.000")
            assert table.column("loose").to_pylist()[1] == Decimal("1.5")
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    @pytest.mark.parametrize("populated", [False, True], ids=["empty", "null-first"])
    async def test_numeric_scales_arrow_cannot_hold_export_without_error(
        self, test_db_session, staging, monkeypatch, populated
    ):
        """numeric(2,-3) and numeric(3,5) are valid in Postgres but not as Arrow
        decimals; they must not break the file write."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", 10)
        table_name = f"exp_pqscale_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} (gid serial PRIMARY KEY, "
                "neg numeric(2,-3), big numeric(3,5), geom geometry(Point, 4326), "
                "geom_4326 geometry(Point, 4326))"
            )
        )
        if populated:
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table_name} (neg, big, geom_4326) "
                    "SELECT NULL, NULL, ST_SetSRID(ST_MakePoint(i, i), 4326) "
                    "FROM generate_series(0, 14) AS i"
                )
            )
        await test_db_session.commit()
        try:
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            path, _filename, _media_type = await export_parquet(
                test_db_session, table_name, "Scale", schema="data", plan=plan
            )
            assert pq.read_table(path).num_rows == (15 if populated else 0)
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_a_two_dimensional_integer_array_exports_as_nested_lists(
        self, test_db_session, staging
    ):
        """Postgres array types carry no dimensions, so the nesting is inferred."""
        table_name = f"exp_pqarr_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} (gid serial PRIMARY KEY, "
                "grid integer[], geom geometry(Point, 4326), "
                "geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (grid, geom_4326) VALUES "
                "(ARRAY[[1,2],[3,4]], ST_SetSRID(ST_MakePoint(0, 0), 4326))"
            )
        )
        await test_db_session.commit()
        try:
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            path, _filename, _media_type = await export_parquet(
                test_db_session, table_name, "Arr", schema="data", plan=plan
            )
            table = pq.read_table(path)
            assert table.schema.field("grid").type == pa.list_(pa.list_(pa.int64()))
            assert table.column("grid").to_pylist() == [[[1, 2], [3, 4]]]
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    @pytest.mark.parametrize("populated", [False, True], ids=["empty", "rows"])
    async def test_domain_columns_take_their_base_type(
        self, test_db_session, staging, monkeypatch, populated
    ):
        """A domain over a supported type is declared as that type, keeping the
        numeric scale, rather than inferred."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", 10)
        suffix = uuid.uuid4().hex[:12]
        table_name = f"exp_pqdom_{suffix}"
        for statement in (
            f"CREATE DOMAIN data.int_dom_{suffix} AS integer",
            f"CREATE DOMAIN data.num_dom_{suffix} AS numeric(10,3)",
            f"CREATE DOMAIN data.nested_dom_{suffix} AS data.int_dom_{suffix}",
            f"CREATE TABLE data.{table_name} (gid serial PRIMARY KEY, "
            f"n data.int_dom_{suffix}, p data.num_dom_{suffix}, "
            f"q data.nested_dom_{suffix}, geom geometry(Point, 4326), "
            "geom_4326 geometry(Point, 4326))",
        ):
            await test_db_session.execute(text(statement))
        if populated:
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table_name} (n, p, q, geom_4326) "
                    "SELECT CASE WHEN i < 15 THEN NULL ELSE i END, "
                    "CASE WHEN i < 15 THEN 1 ELSE 1.125 END, NULL, "
                    "ST_SetSRID(ST_MakePoint(i, i), 4326) "
                    "FROM generate_series(0, 24) AS i"
                )
            )
        await test_db_session.commit()
        try:
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            path, _filename, _media_type = await export_parquet(
                test_db_session, table_name, "Dom", schema="data", plan=plan
            )
            schema = pq.ParquetFile(path).schema_arrow
            assert schema.field("n").type == pa.int32()
            assert schema.field("p").type == pa.decimal128(10, 3)
            assert schema.field("q").type == pa.int32()
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            for domain in ("nested_dom", "num_dom", "int_dom"):
                await test_db_session.execute(
                    text(f"DROP DOMAIN IF EXISTS data.{domain}_{suffix}")
                )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_a_user_type_named_like_a_builtin_is_not_declared(
        self, test_db_session, staging
    ):
        """Only pg_catalog types map to Arrow; an enum named int4 elsewhere is
        not an integer, whatever the table holds."""
        table_name = f"exp_pqshadow_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(text("CREATE TYPE data.int4 AS ENUM ('a')"))
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} (gid serial PRIMARY KEY, "
                "shadow data.int4, real_int integer, geom geometry(Point, 4326), "
                "geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.commit()
        try:
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            assert await export_parquet_module._declared_column_types(
                test_db_session, table_name, "data", ["shadow", "real_int"], frozenset()
            ) == {"real_int": pa.int32()}
            path, _filename, _media_type = await export_parquet(
                test_db_session, table_name, "Shadow", schema="data", plan=plan
            )
            assert pq.read_table(path).num_rows == 0
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.execute(text("DROP TYPE IF EXISTS data.int4"))
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_a_table_swapped_after_planning_keeps_its_new_values(
        self, test_db_session, staging
    ):
        """The route releases its connection between planning and streaming, so
        a reupload can replace the table. Types are read when streaming starts."""
        table_name = f"exp_pqswap_{uuid.uuid4().hex[:12]}"
        columns = "(gid serial PRIMARY KEY, v {}, geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
        await test_db_session.execute(
            text(f"CREATE TABLE data.{table_name} {columns.format('integer')}")
        )
        await test_db_session.commit()
        try:
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            await test_db_session.rollback()
            await test_db_session.execute(text(f"DROP TABLE data.{table_name}"))
            await test_db_session.execute(
                text(
                    f"CREATE TABLE data.{table_name} {columns.format('numeric(10,2)')}"
                )
            )
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table_name} (v, geom_4326) "
                    "VALUES (1.75, ST_SetSRID(ST_MakePoint(0, 0), 4326))"
                )
            )
            await test_db_session.commit()

            path, _filename, _media_type = await export_parquet(
                test_db_session, table_name, "Swap", schema="data", plan=plan
            )

            assert pq.read_table(path).column("v").to_pylist() == [Decimal("1.75")]
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table_name}")
            )
            await test_db_session.commit()

    @pytest.mark.anyio
    async def test_a_table_lock_wait_is_bounded_by_the_export_budget(
        self, test_db_session, staging, monkeypatch
    ):
        """DDL holding ACCESS EXCLUSIVE must not keep the export waiting past
        its budget."""
        import app.core.db as db_module

        monkeypatch.setattr(
            export_parquet_module, "export_subprocess_timeout_seconds", lambda d: 0.5
        )
        table_name = f"exp_pqlock_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} (gid serial PRIMARY KEY, "
                "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.commit()
        plan = await plan_parquet_export(test_db_session, table_name, schema="data")
        await test_db_session.rollback()
        async with db_module.async_session() as holder:
            try:
                await holder.execute(
                    text(f"LOCK TABLE data.{table_name} IN ACCESS EXCLUSIVE MODE")
                )
                started = time.monotonic()
                with pytest.raises(ExportError, match="timed out"):
                    await export_parquet(
                        test_db_session, table_name, "Lock", schema="data", plan=plan
                    )
                assert time.monotonic() - started < 5
            finally:
                await holder.rollback()
                await test_db_session.rollback()
                await test_db_session.execute(
                    text(f"DROP TABLE IF EXISTS data.{table_name}")
                )
                await test_db_session.commit()


def test_a_value_the_declared_type_would_alter_falls_back_to_text():
    """A float under a declared integer type is kept as text, not truncated."""
    table = build_geoparquet_table(
        [b"\x01", b"\x01"],
        {"n": [1, 1.75]},
        ["n"],
        column_types={"n": pa.int32()},
    )

    assert table.column("n").to_pylist() == ["1", "1.75"]
