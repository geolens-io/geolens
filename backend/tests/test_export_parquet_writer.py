"""DB-free unit tests for the GeoParquet writer core.

These exercise build_geoparquet_table() directly (no Postgres, no HTTP), so the
risky bits — geo metadata, WKB round-trip, mixed-type fallback — are verified
without infrastructure. The DB-backed endpoint path is covered by
test_export_parquet.py.
"""

import io
import json

import pyarrow.parquet as pq
from shapely import wkb as shapely_wkb
from shapely.geometry import Point

from app.processing.export.parquet import _attr_names, build_geoparquet_table


def _roundtrip(table):
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    return pq.read_table(buf)


def test_attr_names_strips_internal_geometry_columns():
    column_info = [
        {"name": "gid", "type": "integer"},
        {"name": "geom", "type": "geometry"},
        {"name": "geom_4326", "type": "geometry"},
        {"name": "pop", "type": "integer"},
        {"name": "name", "type": "text"},
    ]
    assert _attr_names(column_info) == ["pop", "name"]


def test_build_table_has_geoparquet_metadata_and_decodes():
    geom = [Point(0, 0).wkb, Point(1, 1).wkb]
    cols = {"pop": [10, 20], "name": ["a", "b"]}
    table = _roundtrip(build_geoparquet_table(geom, cols, ["pop", "name"]))

    assert table.num_rows == 2
    assert table.column_names == ["pop", "name", "geometry"]

    geo = json.loads(table.schema.metadata[b"geo"])
    assert geo["version"] == "1.1.0"
    assert geo["primary_column"] == "geometry"
    assert geo["columns"]["geometry"]["encoding"] == "WKB"

    pt = shapely_wkb.loads(table.column("geometry").to_pylist()[0])
    assert (pt.x, pt.y) == (0.0, 0.0)


def test_build_table_null_geometry_allowed():
    table = _roundtrip(build_geoparquet_table([None], {"pop": [1]}, ["pop"]))
    assert table.column("geometry").to_pylist() == [None]


def test_build_table_mixed_type_column_falls_back_to_string():
    # A column pyarrow cannot unify (int + dict) must not crash the export; it
    # degrades to string so the file still writes.
    geom = [Point(0, 0).wkb, Point(1, 1).wkb]
    cols = {"weird": [1, {"nested": True}]}
    table = _roundtrip(build_geoparquet_table(geom, cols, ["weird"]))
    vals = table.column("weird").to_pylist()
    assert vals[0] == "1"
    assert "nested" in vals[1]
