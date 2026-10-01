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

    async def fetchmany(self, size: int) -> list[tuple]:
        rows = self._rows[self.pulled : self.pulled + size]
        self.pulled += len(rows)
        return rows


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
    @pytest.mark.parametrize(
        "payload",
        [
            {"note": "y" * 1_000},
            {"y" * 1_000: 1},
            [{"deep": {"note": "y" * 1_000}}],
        ],
        ids=["value", "key", "nested"],
    )
    async def test_json_values_count_their_keys_and_values(self, monkeypatch, payload):
        """JSON arrives as dicts, whose shallow size hides the text inside them."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_BYTES", 2_500)
        db = _FakeDb(_Cursor([(i, payload, b"\x01") for i in range(6)]))

        batches = await _batches(db, ["pop", "doc"])

        assert max(len(geom) for geom, _ in batches) <= 2

    @pytest.mark.anyio
    async def test_json_nested_past_the_recursion_limit_is_measured(self):
        deep = json.loads("[" * 5_000 + "]" * 5_000)
        db = _FakeDb(_Cursor([(1, deep, b"\x01")]))

        [(_geom, cols)] = await _batches(db, ["pop", "doc"])

        assert cols["doc"][0] is deep

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


def _assert_geoparquet(table: pa.Table) -> None:
    geo = json.loads(table.schema.metadata[b"geo"])
    assert geo["primary_column"] == "geometry"
    assert geo["columns"]["geometry"]["encoding"] == "WKB"
    assert table.column("geometry").to_pylist() == [b"\x01"] * table.num_rows


class TestFileSchemaStaysStable:
    def test_steady_columns_are_appended_without_reencoding(
        self, monkeypatch, tmp_path
    ):
        def _no_reencode(self, schema):
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

    @pytest.mark.parametrize(
        ("batches", "expected"),
        [
            ([[{"a": 1}], [{"b": "x"}]], ['{"a": 1}', '{"b": "x"}']),
            ([[{}, None], [{"a": 1}]], ["{}", None, '{"a": 1}']),
            ([[{"a": 1}], [{}, None]], ['{"a": 1}', "{}", None]),
            ([[{"x": {}}], [{"x": {"y": 1}}]], ['{"x": {}}', '{"x": {"y": 1}}']),
            ([[[{}]], [[{"a": 1}]]], ["[{}]", '[{"a": 1}]']),
            ([[{}], [{}]], ["{}", "{}"]),
            (
                [[{"ok": True, "n": None, "name": "Zürich"}]],
                ['{"ok": true, "n": null, "name": "Zürich"}'],
            ),
        ],
        ids=[
            "keys-differ",
            "empty-first",
            "empty-after",
            "nested-empty",
            "in-array",
            "never-populated",
            "json-literals",
        ],
    )
    def test_json_objects_are_json_text(self, tmp_path, batches, expected):
        """As a struct, every row would take a slot for every key in the
        column, so memory would follow the keys rather than the data."""
        written = _write_batches(
            tmp_path / "out.parquet", ["doc"], [{"doc": batch} for batch in batches]
        )

        table = written.read()
        assert table.schema.field("doc").type == pa.string()
        assert table.column("doc").to_pylist() == expected
        _assert_geoparquet(table)

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
        assert table.column("weird").to_pylist() == ["1", "2", '{"nested": true}']

    @pytest.mark.parametrize(
        ("batches", "expected"),
        [
            ([[[{"a": 1}]], [[1]]], ['[{"a": 1}]', "[1]"]),
            ([[[1]], [[{"a": 1}]]], ["[1]", '[{"a": 1}]']),
            ([[[1, 2]], [["a"]]], ["[1, 2]", '["a"]']),
        ],
        ids=["objects-first", "numbers-first", "scalars"],
    )
    def test_json_arrays_whose_elements_disagree_fall_back_to_string(
        self, tmp_path, batches, expected
    ):
        """As within one batch, the whole value becomes text, not each element."""
        written = _write_batches(
            tmp_path / "out.parquet", ["tags"], [{"tags": batch} for batch in batches]
        )

        table = written.read()
        assert table.schema.field("tags").type == pa.string()
        assert table.column("tags").to_pylist() == expected
        _assert_geoparquet(table)

    @pytest.mark.parametrize(
        ("batches", "expected"),
        [
            ([[1], [2**60 + 1], [1.5]], ["1", str(2**60 + 1), "1.5"]),
            ([[1.5], [2**60 + 1]], ["1.5", str(2**60 + 1)]),
        ],
        ids=["written-rows-fail", "new-batch-fails"],
    )
    def test_values_that_do_not_fit_the_wider_type_fall_back_to_string(
        self, tmp_path, batches, expected
    ):
        """No double holds an integer past 2**53 exactly, so int and float
        batches can't share a float column."""
        written = _write_batches(
            tmp_path / "out.parquet", ["n"], [{"n": batch} for batch in batches]
        )

        table = written.read()
        assert table.schema.field("n").type == pa.string()
        assert table.column("n").to_pylist() == expected
        _assert_geoparquet(table)
        assert sorted(os.listdir(tmp_path)) == ["out.parquet"]

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
        "values",
        [
            [1, {"a": 1}],
            [[1, 2], ["a"]],
            [[{"a": 1}], [1]],
            [{"x": {}}, {"x": {"y": 1}}],
            [2**60 + 1, 1.5],
            [1, 2**63],
        ],
        ids=["scalar-object", "arrays", "array-of-objects", "nested", "float", "int64"],
    )
    def test_text_reads_the_same_however_the_batches_split(self, tmp_path, values):
        whole = _write_batches(tmp_path / "whole.parquet", ["v"], [{"v": values}])
        split = _write_batches(
            tmp_path / "split.parquet", ["v"], [{"v": [value]} for value in values]
        )

        assert (
            whole.read().column("v").to_pylist() == split.read().column("v").to_pylist()
        )

    def test_null_rows_then_wide_objects_stay_text(self, tmp_path):
        """Objects arriving after null rows don't widen those rows into a
        struct slot per key, whatever the number of keys or columns."""
        names = [f"doc{i}" for i in range(20)] + ["late"]
        wide = {f"k{j}": j for j in range(64)}
        written = _write_batches(
            tmp_path / "out.parquet",
            names,
            [
                {name: [None] * 10_000 for name in names},
                {name: [None if name == "late" else wide] for name in names},
                {name: [1 if name == "late" else None] for name in names},
            ],
        )

        table = written.read()
        assert {table.schema.field(name).type for name in names[:-1]} == {pa.string()}
        assert json.loads(table.column("doc0")[10_000].as_py()) == wide
        assert table.column("doc0").null_count == 10_001
        assert table.column("late").to_pylist()[-1] == 1
        _assert_geoparquet(table)

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
    async def test_json_columns_that_change_shape_between_batches_export(
        self, test_db_session, monkeypatch, staging
    ):
        """jsonb reaches the writer as Python objects. One column has only empty
        objects in the first batch; another holds arrays of objects, then of
        numbers."""
        monkeypatch.setattr(export_parquet_module, "_BATCH_MAX_ROWS", 10)
        table_name = f"exp_pqjson_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} "
                "(gid serial PRIMARY KEY, pop integer, doc jsonb, tags jsonb, "
                "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (pop, doc, tags, geom, geom_4326) "
                "SELECT i, "
                "CASE WHEN i < 10 THEN '{}'::jsonb "
                "ELSE jsonb_build_object('a', i) END, "
                "CASE WHEN i < 10 THEN jsonb_build_array(jsonb_build_object('a', i)) "
                "ELSE jsonb_build_array(i) END, "
                "ST_SetSRID(ST_MakePoint(i, i), 4326), "
                "ST_SetSRID(ST_MakePoint(i, i), 4326) "
                "FROM generate_series(0, 19) AS i"
            )
        )
        await test_db_session.commit()
        try:
            plan = await plan_parquet_export(test_db_session, table_name, schema="data")
            path, _filename, _media_type = await export_parquet(
                test_db_session,
                table_name,
                "Json",
                schema="data",
                plan=plan,
            )

            written = pq.ParquetFile(path)
            table = written.read()
            rows = sorted(
                zip(
                    table.column("pop").to_pylist(),
                    table.column("doc").to_pylist(),
                    table.column("tags").to_pylist(),
                )
            )

            assert written.metadata.num_row_groups == 2
            assert [
                (pop, json.loads(doc), json.loads(tags)) for pop, doc, tags in rows
            ] == [
                (i, {}, [{"a": i}]) if i < 10 else (i, {"a": i}, [i]) for i in range(20)
            ]
            geo = json.loads(table.schema.metadata[b"geo"])
            assert geo["primary_column"] == "geometry"
            assert table.column("geometry").null_count == 0
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
