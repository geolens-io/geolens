"""Unit tests for ephemeral GeoJSON extraction from query_data results."""

import json
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID

import shapely


# Import helpers from chat_service
from app.ai.chat_service import (
    _is_geom_value,
    _detect_geom_column,
    _safe_value,
    _extract_geojson,
)


# ---------------------------------------------------------------------------
# Fixtures: sample WKB hex and ST_AsGeoJSON strings
# ---------------------------------------------------------------------------

# A simple POINT(1 2) as WKB hex (little-endian)
POINT_WKB_HEX = shapely.to_wkb(shapely.Point(1, 2), hex=True)
# A POINT(3 4) as WKB hex
POINT2_WKB_HEX = shapely.to_wkb(shapely.Point(3, 4), hex=True)

# ST_AsGeoJSON output (plain JSON string)
POINT_GEOJSON_STR = json.dumps({"type": "Point", "coordinates": [10, 20]})


class TestIsGeomValue:
    def test_wkb_hex_detected(self):
        assert _is_geom_value(POINT_WKB_HEX) is True

    def test_st_as_geojson_detected(self):
        assert _is_geom_value(POINT_GEOJSON_STR) is True

    def test_short_hex_rejected(self):
        assert _is_geom_value("ABCD") is False

    def test_non_hex_rejected(self):
        assert _is_geom_value("hello world") is False

    def test_none_rejected(self):
        assert _is_geom_value(None) is False

    def test_int_rejected(self):
        assert _is_geom_value(42) is False


class TestDetectGeomColumn:
    def test_geom_column_by_name(self):
        cols = ["id", "name", "geom_4326"]
        row = [1, "test", POINT_WKB_HEX]
        assert _detect_geom_column(cols, row) == 2

    def test_geometry_column_name(self):
        cols = ["id", "geometry"]
        row = [1, POINT_WKB_HEX]
        assert _detect_geom_column(cols, row) == 1

    def test_the_geom_column_name(self):
        cols = ["the_geom", "name"]
        row = [POINT_WKB_HEX, "test"]
        assert _detect_geom_column(cols, row) == 0

    def test_st_prefix_column(self):
        cols = ["id", "st_asgeojson"]
        row = [1, POINT_GEOJSON_STR]
        assert _detect_geom_column(cols, row) == 1

    def test_no_geom_column(self):
        cols = ["id", "name", "population"]
        row = [1, "test", 1000]
        assert _detect_geom_column(cols, row) is None

    def test_geom_name_but_null_value(self):
        """Column name matches but value is null -- still detected (None values are skipped later)."""
        cols = ["id", "geom"]
        row = [1, None]
        # With null value, _is_geom_value returns False, so no detection
        assert _detect_geom_column(cols, row) is None


class TestSafeValue:
    def test_str_passthrough(self):
        assert _safe_value("hello") == "hello"

    def test_int_passthrough(self):
        assert _safe_value(42) == 42

    def test_float_passthrough(self):
        assert _safe_value(3.14) == 3.14

    def test_bool_passthrough(self):
        assert _safe_value(True) is True

    def test_none_passthrough(self):
        assert _safe_value(None) is None

    def test_datetime_converted(self):
        dt = datetime(2024, 1, 15, 10, 30)
        assert _safe_value(dt) == str(dt)

    def test_date_converted(self):
        d = date(2024, 1, 15)
        assert _safe_value(d) == str(d)

    def test_decimal_converted(self):
        assert _safe_value(Decimal("99.99")) == str(Decimal("99.99"))

    def test_uuid_converted(self):
        u = UUID("12345678-1234-5678-1234-567812345678")
        assert _safe_value(u) == str(u)

    def test_bytes_converted(self):
        assert _safe_value(b"raw") == str(b"raw")


class TestExtractGeojson:
    def test_wkb_rows_to_feature_collection(self):
        cols = ["id", "name", "geom_4326"]
        rows = [
            [1, "A", POINT_WKB_HEX],
            [2, "B", POINT2_WKB_HEX],
        ]
        result = _extract_geojson(cols, rows)
        assert result is not None
        fc, bbox = result
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 2
        # Check properties
        assert fc["features"][0]["properties"] == {"id": 1, "name": "A"}
        assert fc["features"][1]["properties"] == {"id": 2, "name": "B"}
        # Check geometry type
        assert fc["features"][0]["geometry"]["type"] == "Point"

    def test_bbox_computed(self):
        cols = ["geom"]
        rows = [
            [POINT_WKB_HEX],  # Point(1, 2)
            [POINT2_WKB_HEX],  # Point(3, 4)
        ]
        result = _extract_geojson(cols, rows)
        assert result is not None
        _, bbox = result
        # bbox = [west, south, east, north] = [minx, miny, maxx, maxy]
        assert bbox == [1.0, 2.0, 3.0, 4.0]

    def test_st_as_geojson_string(self):
        cols = ["id", "st_asgeojson"]
        rows = [
            [1, POINT_GEOJSON_STR],
        ]
        result = _extract_geojson(cols, rows)
        assert result is not None
        fc, bbox = result
        assert fc["features"][0]["geometry"]["type"] == "Point"
        assert fc["features"][0]["geometry"]["coordinates"] == [10, 20]

    def test_null_geometry_skipped(self):
        cols = ["id", "geom"]
        rows = [
            [1, POINT_WKB_HEX],
            [2, None],
            [3, POINT2_WKB_HEX],
        ]
        result = _extract_geojson(cols, rows)
        assert result is not None
        fc, _ = result
        # Only 2 features (null row skipped)
        assert len(fc["features"]) == 2

    def test_non_serializable_properties(self):
        cols = ["id", "created", "amount", "geom"]
        rows = [
            [1, datetime(2024, 1, 1), Decimal("42.5"), POINT_WKB_HEX],
        ]
        result = _extract_geojson(cols, rows)
        assert result is not None
        fc, _ = result
        props = fc["features"][0]["properties"]
        assert isinstance(props["created"], str)
        assert isinstance(props["amount"], str)

    def test_no_geom_column_returns_none(self):
        cols = ["id", "name"]
        rows = [[1, "test"]]
        assert _extract_geojson(cols, rows) is None

    def test_empty_rows_returns_none(self):
        cols = ["id", "geom"]
        rows = []
        assert _extract_geojson(cols, rows) is None
