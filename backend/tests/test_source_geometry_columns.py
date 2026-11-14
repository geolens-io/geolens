"""Which recorded geometry columns a replacement source has, and how ogrinfo's text reports fields."""

import pytest

from app.platform.source_geometry_columns import (
    GeometrySelection,
    columns_to_build,
    geometry_selection,
)
from app.processing.ingest.ogr import _parse_text_ogrinfo

_PAIR = GeometrySelection({"x_column": "lon", "y_column": "lat"}, 4326)

_TEXT_OUTPUT = """INFO: Open of `places.csv'
      using driver `CSV' successful.

Layer name: places
Geometry: None
Feature Count: 3
Layer SRS WKT:
(unknown)
name: String (0.0)
lon: Real (0.0)
Latitude-Deg: Real (0.0)
flag: Integer(Boolean) (0.0)
"""


def test_the_text_fallback_reports_fields_and_driver():
    result = _parse_text_ogrinfo(_TEXT_OUTPUT)

    assert result["driver"] == "CSV"
    assert [column["name"] for column in result["columns"]] == [
        "name",
        "lon",
        "Latitude-Deg",
        "flag",
    ]
    assert result["columns"][3] == {
        "name": "flag",
        "type": "Integer",
        "subtype": "Boolean",
    }
    selection = GeometrySelection({"x_column": "lon", "y_column": "latitude_deg"}, None)
    assert columns_to_build(
        selection,
        source_geometry_type=None,
        source_columns=result["columns"],
        driver=result["driver"],
    ) == (selection, [])


def test_a_schema_without_the_columns_lacks_them():
    assert columns_to_build(
        _PAIR, source_geometry_type=None, source_columns=[], driver="CSV"
    ) == (None, ["lon", "lat"])


def test_a_non_tabular_source_with_geometry_keeps_it():
    columns = [{"name": "lon"}, {"name": "lat"}]
    assert columns_to_build(
        _PAIR, source_geometry_type="Point", source_columns=columns, driver="GeoJSON"
    ) == (None, [])
    assert columns_to_build(
        _PAIR,
        source_geometry_type="Unknown (any)",
        source_columns=columns,
        driver="CSV",
    ) == (_PAIR, [])


def test_a_commit_override_is_the_recorded_crs_of_an_older_import_job():
    assert geometry_selection(
        {"x_column": "x", "y_column": "y", "srid_override": 27700}
    ) == GeometrySelection({"x_column": "x", "y_column": "y"}, 27700)
    assert geometry_selection({"x_column": "x"}) is None


def test_the_frontend_reads_the_columns_out_of_the_stored_sentence():
    """``failure-reason.ts`` splits the worker's sentence around the column names."""
    from pathlib import Path

    from app.core.upload_errors import geometry_columns_missing_refusal

    found = [
        root / "frontend/src/lib/failure-reason.ts"
        for root in Path(__file__).resolve().parents
        if (root / "frontend/src/lib/failure-reason.ts").is_file()
    ]
    if not found:
        pytest.skip("the frontend sources are not in this checkout")
    source = found[0].read_text(encoding="utf-8")
    prefix, suffix = geometry_columns_missing_refusal(["\0"]).split("\0")
    assert f'"{prefix}"' in source
    assert f"'{suffix}'" in source
