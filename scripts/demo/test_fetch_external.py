from __future__ import annotations

import importlib.util
from pathlib import Path

_MODULE_PATH = Path(__file__).with_name("fetch_external.py")
_SPEC = importlib.util.spec_from_file_location("demo_fetch_external", _MODULE_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_fetch_external = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_fetch_external)

_normalize_bbl_key = _fetch_external._normalize_bbl_key
_normalize_landuse = _fetch_external._normalize_landuse
_nyc_pluto_geojson_has_landuse = _fetch_external._nyc_pluto_geojson_has_landuse


def test_normalize_bbl_key_strips_socrata_decimal_suffix() -> None:
    assert _normalize_bbl_key("1022150610.00000000") == "1022150610"
    assert _normalize_bbl_key("3004287507") == "3004287507"


def test_normalize_landuse_matches_fixture_style_codes() -> None:
    assert _normalize_landuse("5") == "05"
    assert _normalize_landuse("05") == "05"
    assert _normalize_landuse("5.0000000") == "05"
    assert _normalize_landuse(None) is None


def test_nyc_pluto_cached_geojson_requires_landuse(tmp_path: Path) -> None:
    path = tmp_path / "nyc_pluto_zoning.geojson"
    path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"landuse":""}}]}'
        + (" " * 1024)
    )
    assert _nyc_pluto_geojson_has_landuse(path) is False

    path.write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"landuse":"02"}}]}'
        + (" " * 1024)
    )
    assert _nyc_pluto_geojson_has_landuse(path) is True
