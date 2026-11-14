"""Which recorded geometry columns a replacement source has, and how ogrinfo's text reports fields."""

import re

import pytest

from app.core.geometry_build_errors import GEOMETRY_BUILD_SENTENCES, columns_missing
from app.platform.source_geometry_columns import (
    GeometrySelection,
    declared_build_type,
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


def test_the_frontend_has_every_sentence_it_reads_values_from():
    """``failure-reason.ts`` matches stored reasons against these templates."""
    from pathlib import Path

    found = [
        root / "frontend/src/lib/failure-reason.ts"
        for root in Path(__file__).resolve().parents
        if (root / "frontend/src/lib/failure-reason.ts").is_file()
    ]
    if not found:
        pytest.skip("the frontend sources are not in this checkout")
    source = found[0].read_text(encoding="utf-8")
    for code, template in GEOMETRY_BUILD_SENTENCES.items():
        if "{" in template:
            frontend = re.sub(r"\{(\w+)\}", r"{{\1}}", template)
            assert f"{code}:" in source and f'"{frontend}"' in source, code


def test_a_header_on_several_lines_is_named_on_one():
    """The stored sentence keeps the suffix the frontend reads the names before."""
    reason = columns_missing(["Lat:\nDeg", "lon"]).reason
    assert reason.code == "geometry_columns_missing"
    assert str(reason) == GEOMETRY_BUILD_SENTENCES["geometry_columns_missing"].format(
        columns="Lat: Deg, lon"
    )


@pytest.mark.parametrize(
    "values,declared",
    [
        (["POINT (1 2)", "POINT(3 4)"], "POINT"),
        (["POINT (1 2)", "MULTIPOINT ((3 4))"], "MULTIPOINT"),
        (["POINT Z (1 2 3)", "POINTZ(3 4 5)"], "POINTZ"),
        (["POINT Z (1 2 3)", "POINT (3 4)"], "GEOMETRY"),
        (["POINT (1 2 3)", "POINT(3 4 5)"], "POINTZ"),
        (["MULTIPOINT ((1 2 3 4))"], "MULTIPOINTZM"),
        (["POINT M (1 2 3)"], "POINTM"),
        (["POINT (1 2)", "LINESTRING (0 0, 1 1)"], "GEOMETRY"),
        (["SRID=4326;POLYGON ((0 0, 1 0, 1 1, 0 0))"], "POLYGON"),
        (["not wkt"], "GEOMETRY"),
    ],
)
def test_a_preview_declares_what_the_build_stores(values, declared):
    build = GeometrySelection({"geom_column": "Shape_WKT"}, None)
    rows = [{"name": "a", "shape_wkt": value} for value in values]
    assert declared_build_type(build, rows) == declared


@pytest.mark.parametrize(
    "found,typmod,stored",
    [
        ([("POINT", 0)], "POINT", "g"),
        ([("POINT", 0), ("MULTIPOINT", 0)], "MULTIPOINT", "ST_Multi(g)"),
        ([("POLYGON", 0), ("LINESTRING", 0)], "GEOMETRY", "ST_Multi(g)"),
        ([("POINTM", 1)], "POINTM", "g"),
        ([], "GEOMETRY", "g"),
    ],
)
def test_the_build_stores_one_family_in_multi_form(found, typmod, stored):
    from app.processing.ingest.metadata_geometry import _wkt_column_type

    assert _wkt_column_type(found, "g") == (typmod, stored)


@pytest.mark.parametrize(
    "found,dimensions",
    [
        ([("POINT", 2), ("POINT", 3)], "XYZ, XYZM"),
        ([("POINTM", 1), ("MULTIPOINTM", 3)], "XYM, XYZM"),
        ([("POINT", 0), ("MULTIPOINT", 2)], "XY, XYZ"),
    ],
)
def test_rows_that_disagree_on_dimensions_build_nothing(found, dimensions):
    from app.core.geometry_build_errors import GeometryBuildError
    from app.processing.ingest.metadata_geometry import _wkt_column_type

    with pytest.raises(GeometryBuildError) as refused:
        _wkt_column_type(found, "g")
    assert refused.value.reason.code == "geometry_wkt_mixed_dimensions"
    assert f"({dimensions})" in str(refused.value)
