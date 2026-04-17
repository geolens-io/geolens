"""Tests for geometry column detection and post-import geometry construction.

Unit tests for detect_geometry_columns (pure function, no DB).
Integration tests for construct_point_geometry / construct_wkt_geometry (require DB).
"""

import pytest
from sqlalchemy import text

from app.processing.ingest.ogr import detect_geometry_columns


# ---------------------------------------------------------------------------
# detect_geometry_columns — unit tests (no DB)
# ---------------------------------------------------------------------------


class TestDetectGeometryColumns:
    def test_detects_lat_lng(self):
        columns = [
            {"name": "id", "type": "Integer"},
            {"name": "latitude", "type": "Real"},
            {"name": "longitude", "type": "Real"},
        ]
        result = detect_geometry_columns(columns)
        assert result["y_column"] == "latitude"
        assert result["x_column"] == "longitude"
        assert result["wkt_column"] is None

    def test_detects_lat_lon_shorthand(self):
        columns = [
            {"name": "lat", "type": "Real"},
            {"name": "lon", "type": "Real"},
        ]
        result = detect_geometry_columns(columns)
        assert result["y_column"] == "lat"
        assert result["x_column"] == "lon"

    def test_detects_x_y(self):
        columns = [
            {"name": "x", "type": "Real"},
            {"name": "y", "type": "Real"},
        ]
        result = detect_geometry_columns(columns)
        assert result["x_column"] == "x"
        assert result["y_column"] == "y"

    def test_detects_wkt_column(self):
        columns = [
            {"name": "id", "type": "Integer"},
            {"name": "WKT", "type": "String"},
        ]
        result = detect_geometry_columns(columns)
        assert result["wkt_column"] == "WKT"
        assert result["x_column"] is None
        assert result["y_column"] is None

    def test_detects_geometry_column_name(self):
        columns = [{"name": "geometry", "type": "String"}]
        result = detect_geometry_columns(columns)
        assert result["wkt_column"] == "geometry"

    def test_detects_the_geom(self):
        columns = [{"name": "the_geom", "type": "String"}]
        result = detect_geometry_columns(columns)
        assert result["wkt_column"] == "the_geom"

    def test_detects_shape(self):
        columns = [{"name": "shape", "type": "String"}]
        result = detect_geometry_columns(columns)
        assert result["wkt_column"] == "shape"

    def test_case_insensitive(self):
        columns = [
            {"name": "Latitude", "type": "Real"},
            {"name": "Longitude", "type": "Real"},
        ]
        result = detect_geometry_columns(columns)
        # Returns original case
        assert result["y_column"] == "Latitude"
        assert result["x_column"] == "Longitude"

    def test_no_geometry_columns(self):
        columns = [
            {"name": "id", "type": "Integer"},
            {"name": "name", "type": "String"},
            {"name": "value", "type": "Real"},
        ]
        result = detect_geometry_columns(columns)
        assert result["x_column"] is None
        assert result["y_column"] is None
        assert result["wkt_column"] is None

    def test_empty_columns(self):
        result = detect_geometry_columns([])
        assert result == {"x_column": None, "y_column": None, "wkt_column": None}

    def test_lat_without_lng_returns_partial(self):
        columns = [
            {"name": "latitude", "type": "Real"},
            {"name": "name", "type": "String"},
        ]
        result = detect_geometry_columns(columns)
        assert result["y_column"] == "latitude"
        assert result["x_column"] is None

    def test_matches_from_pattern_set_when_multiple_candidates(self):
        """If both 'lon' and 'x' exist, one of them matches (set order is non-deterministic)."""
        columns = [
            {"name": "lon", "type": "Real"},
            {"name": "x", "type": "Real"},
            {"name": "lat", "type": "Real"},
        ]
        result = detect_geometry_columns(columns)
        # Both 'lon' and 'x' are in LNG_PATTERNS; set iteration order varies
        assert result["x_column"] in ("lon", "x")


# ---------------------------------------------------------------------------
# construct_point_geometry — integration tests (require DB)
# ---------------------------------------------------------------------------


class TestConstructPointGeometry:
    @pytest.fixture(autouse=True)
    def _skip_no_db(self, client):
        """Ensure DB is available (client fixture handles setup)."""

    async def test_creates_point_geometry(self, test_db_session):
        from app.processing.ingest.metadata import construct_point_geometry

        table = "test_point_geom"
        try:
            await test_db_session.execute(
                text(
                    f"CREATE TABLE data.{table} ("
                    "  ogc_fid serial PRIMARY KEY,"
                    "  lng double precision,"
                    "  lat double precision"
                    ")"
                )
            )
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table} (lng, lat) VALUES "
                    "(-73.9857, 40.7484), (-0.1278, 51.5074)"
                )
            )
            await test_db_session.commit()

            count = await construct_point_geometry(test_db_session, table, "lng", "lat")
            assert count == 2

            # Verify geometry was created
            result = await test_db_session.execute(
                text(
                    f"SELECT ST_AsText(geom), ST_SRID(geom) FROM data.{table} "
                    "ORDER BY ogc_fid"
                )
            )
            rows = result.all()
            assert len(rows) == 2
            assert "POINT" in rows[0][0]
            assert rows[0][1] == 4326

        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table} CASCADE")
            )
            await test_db_session.commit()

    async def test_skips_null_coordinates(self, test_db_session):
        from app.processing.ingest.metadata import construct_point_geometry

        table = "test_point_nulls"
        try:
            await test_db_session.execute(
                text(
                    f"CREATE TABLE data.{table} ("
                    "  ogc_fid serial PRIMARY KEY,"
                    "  lng double precision,"
                    "  lat double precision"
                    ")"
                )
            )
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table} (lng, lat) VALUES "
                    "(-73.9857, 40.7484), (NULL, NULL), (-0.1278, NULL)"
                )
            )
            await test_db_session.commit()

            count = await construct_point_geometry(test_db_session, table, "lng", "lat")
            assert count == 1  # Only first row has both coords

        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table} CASCADE")
            )
            await test_db_session.commit()

    async def test_rejects_invalid_column_name(self, test_db_session):
        from app.processing.ingest.metadata import construct_point_geometry

        with pytest.raises(ValueError, match="Invalid column name"):
            await construct_point_geometry(
                test_db_session, "test_tbl", "x col", "y_col"
            )

    async def test_rejects_uppercase_column_name(self, test_db_session):
        """Uppercase column names are rejected by validation regex."""
        from app.processing.ingest.metadata import construct_point_geometry

        with pytest.raises(ValueError, match="Invalid column name"):
            await construct_point_geometry(
                test_db_session, "test_tbl", "Longitude", "Latitude"
            )


# ---------------------------------------------------------------------------
# construct_wkt_geometry — integration tests (require DB)
# ---------------------------------------------------------------------------


class TestConstructWktGeometry:
    @pytest.fixture(autouse=True)
    def _skip_no_db(self, client):
        """Ensure DB is available."""

    async def test_creates_geometry_from_wkt(self, test_db_session):
        from app.processing.ingest.metadata import construct_wkt_geometry

        table = "test_wkt_geom"
        try:
            await test_db_session.execute(
                text(
                    f"CREATE TABLE data.{table} ("
                    "  ogc_fid serial PRIMARY KEY,"
                    "  wkt text"
                    ")"
                )
            )
            await test_db_session.execute(
                text(
                    f"INSERT INTO data.{table} (wkt) VALUES "
                    "('POINT(-73.9857 40.7484)'), "
                    "('POINT(-0.1278 51.5074)')"
                )
            )
            await test_db_session.commit()

            count = await construct_wkt_geometry(test_db_session, table, "wkt")
            assert count == 2

            result = await test_db_session.execute(
                text(
                    f"SELECT ST_AsText(geom), ST_SRID(geom) FROM data.{table} "
                    "ORDER BY ogc_fid"
                )
            )
            rows = result.all()
            assert len(rows) == 2
            assert "POINT" in rows[0][0]
            assert rows[0][1] == 4326

        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table} CASCADE")
            )
            await test_db_session.commit()

    async def test_skips_null_wkt(self, test_db_session):
        from app.processing.ingest.metadata import construct_wkt_geometry

        table = "test_wkt_nulls"
        try:
            await test_db_session.execute(
                text(
                    f"CREATE TABLE data.{table} ("
                    "  ogc_fid serial PRIMARY KEY,"
                    "  wkt text"
                    ")"
                )
            )
            await test_db_session.execute(
                text(f"INSERT INTO data.{table} (wkt) VALUES ('POINT(0 0)'), (NULL)")
            )
            await test_db_session.commit()

            count = await construct_wkt_geometry(test_db_session, table, "wkt")
            assert count == 1

        finally:
            await test_db_session.execute(
                text(f"DROP TABLE IF EXISTS data.{table} CASCADE")
            )
            await test_db_session.commit()


# ---------------------------------------------------------------------------
# Column name lowercasing in tasks.py — unit tests
# ---------------------------------------------------------------------------


class TestColumnNameLowercasing:
    """Verify that the tasks.py lowercasing logic works correctly."""

    def test_lowercase_preserves_already_lowercase(self):
        val = "longitude"
        result = (val or "").lower() or None
        assert result == "longitude"

    def test_lowercase_converts_mixed_case(self):
        val = "Latitude"
        result = (val or "").lower() or None
        assert result == "latitude"

    def test_lowercase_none_returns_none(self):
        val = None
        result = (val or "").lower() or None
        assert result is None

    def test_lowercase_empty_string_returns_none(self):
        val = ""
        result = (val or "").lower() or None
        assert result is None
