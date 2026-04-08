"""Unit tests for csv_to_choropleth.py.

Tests use inline fixtures — no external test data files required.
Run with: pytest scripts/demo/lib/test_csv_to_choropleth.py -v
"""

import csv
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the demo lib package is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.demo.lib.csv_to_choropleth import (
    join_and_write,
    load_indicator_csv,
    shapefile_to_geojson,
)


# ---------------------------------------------------------------------------
# Inline fixture helpers
# ---------------------------------------------------------------------------

def _make_csv(rows: list[dict], tmp_path: Path, filename: str = "test.csv") -> Path:
    """Write a list of dicts to a CSV file and return the path."""
    p = tmp_path / filename
    if rows:
        with open(p, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return p


def _make_geojson(features: list[dict], tmp_path: Path, filename: str = "adm0.geojson") -> Path:
    """Write a minimal GeoJSON FeatureCollection to a file and return the path."""
    p = tmp_path / filename
    p.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": features,
            }
        )
    )
    return p


def _point_feature(iso3: str) -> dict:
    """Return a minimal GeoJSON point feature with the given ISO3 code."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
        "properties": {"ISO_A3": iso3, "NAME": iso3},
    }


# ---------------------------------------------------------------------------
# Test 1: basic join — matched, unmatched, null value
# ---------------------------------------------------------------------------

def test_join_matched_unmatched_null(tmp_path, caplog):
    """3 matched ISO3 + 1 unmatched + 1 null value → 3 features in output."""
    csv_rows = [
        {"iso3": "USA", "value": "12.5"},
        {"iso3": "DEU", "value": "8.3"},
        {"iso3": "BRA", "value": "4.1"},
        {"iso3": "XYZ", "value": "99.0"},   # unmatched
        {"iso3": "FRA", "value": ""},        # null value — skipped
    ]
    csv_path = _make_csv(csv_rows, tmp_path)
    adm0_path = _make_geojson(
        [_point_feature("USA"), _point_feature("DEU"), _point_feature("BRA"), _point_feature("FRA")],
        tmp_path,
    )
    out_path = tmp_path / "output.geojson"

    values = load_indicator_csv(csv_path, join_col="iso3", value_col="value")
    # FRA had null value so it should not appear in values
    assert "FRA" not in values
    assert "USA" in values
    assert "DEU" in values
    assert "BRA" in values
    assert "XYZ" in values  # XYZ is in CSV but unmatched in ADM0

    adm0_geojson = shapefile_to_geojson(adm0_path)
    exit_code = join_and_write(adm0_geojson, values, adm0_join_col="ISO_A3", value_col="value", output_path=out_path)

    assert exit_code == 0
    result = json.loads(out_path.read_text())
    matched_isos = {f["properties"]["ISO_A3"] for f in result["features"]}
    assert matched_isos == {"USA", "DEU", "BRA"}
    for feat in result["features"]:
        assert "_value" in feat["properties"]
        assert feat["properties"]["_value_col"] == "value"


# ---------------------------------------------------------------------------
# Test 2: duplicate ISO3 — last value wins, WARNING logged
# ---------------------------------------------------------------------------

def test_duplicate_iso3_last_value_wins(tmp_path, caplog):
    """Duplicate ISO3 in CSV: last value wins, WARNING is logged."""
    csv_rows = [
        {"iso3": "USA", "value": "10.0"},
        {"iso3": "USA", "value": "99.9"},  # duplicate — this one should win
    ]
    csv_path = _make_csv(csv_rows, tmp_path)

    import logging
    with caplog.at_level(logging.WARNING):
        values = load_indicator_csv(csv_path, join_col="iso3", value_col="value")

    assert values["USA"] == pytest.approx(99.9)
    # A WARNING about duplicate should have been emitted
    assert any("USA" in record.message or "duplicate" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# Test 3: World Bank-style 4-line metadata header detection
# ---------------------------------------------------------------------------

def test_worldbank_header_skipped(tmp_path):
    """World Bank CSVs have 4-line metadata header — header detection must skip it."""
    # World Bank CSV format: 4 lines of metadata, then an empty line, then the header row
    wb_content = (
        '"Data Source","World Development Indicators"\n'
        "\n"
        '"Last Updated Date","2023-12-01"\n'
        "\n"
        '"Country Name","Country Code","Indicator Name","Indicator Code","2023"\n'
        '"United States","USA","GDP","NY.GDP.MKTP.CD","25000"\n'
        '"Germany","DEU","GDP","NY.GDP.MKTP.CD","4000"\n'
    )
    csv_path = tmp_path / "worldbank.csv"
    csv_path.write_text(wb_content)

    values = load_indicator_csv(csv_path, join_col="Country Code", value_col="2023")
    assert "USA" in values
    assert "DEU" in values
    assert values["USA"] == pytest.approx(25000.0)


# ---------------------------------------------------------------------------
# Test 4: --year-filter filters non-matching rows
# ---------------------------------------------------------------------------

def test_year_filter(tmp_path):
    """Year filter must exclude rows not matching the specified year."""
    csv_rows = [
        {"iso3": "USA", "year": "2020", "value": "10.0"},
        {"iso3": "USA", "year": "2021", "value": "11.0"},
        {"iso3": "DEU", "year": "2020", "value": "5.0"},
        {"iso3": "DEU", "year": "2021", "value": "6.0"},
        {"iso3": "BRA", "year": "2022", "value": "3.0"},
    ]
    csv_path = _make_csv(csv_rows, tmp_path)

    values = load_indicator_csv(csv_path, join_col="iso3", value_col="value", year_filter="2021")
    # Only 2021 rows: USA=11.0, DEU=6.0
    assert set(values.keys()) == {"USA", "DEU"}
    assert values["USA"] == pytest.approx(11.0)
    assert values["DEU"] == pytest.approx(6.0)
    assert "BRA" not in values


# ---------------------------------------------------------------------------
# Test 5: zero matches → exit code 1
# ---------------------------------------------------------------------------

def test_zero_matches_exit_code_1(tmp_path):
    """When no features match, join_and_write must return exit code 1."""
    csv_rows = [
        {"iso3": "ZZZ", "value": "1.0"},
    ]
    csv_path = _make_csv(csv_rows, tmp_path)
    adm0_path = _make_geojson([_point_feature("USA")], tmp_path)
    out_path = tmp_path / "output.geojson"

    values = load_indicator_csv(csv_path, join_col="iso3", value_col="value")
    adm0_geojson = shapefile_to_geojson(adm0_path)
    exit_code = join_and_write(adm0_geojson, values, adm0_join_col="ISO_A3", value_col="value", output_path=out_path)

    assert exit_code == 1
