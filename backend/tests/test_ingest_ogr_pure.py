"""Unit tests for the pure (no-subprocess) helpers in app.ingest.ogr.

These exercise the geometry-column sniffer, the source-path wrapper, the SRID
extraction from ogrinfo JSON output, and the text-fallback parser. All of
them are zero-dependency functions — no GDAL or database calls — so they are
safe to run in any environment.
"""

from app.ingest.ogr import (
    _extract_srid_from_json,
    _parse_text_ogrinfo,
    _resolve_source_path,
    detect_geometry_columns,
)


class TestDetectGeometryColumns:
    def test_detects_lat_lng_conventional(self):
        cols = [
            {"name": "id", "type": "integer"},
            {"name": "lat", "type": "real"},
            {"name": "lon", "type": "real"},
            {"name": "name", "type": "text"},
        ]
        result = detect_geometry_columns(cols)
        assert result == {"x_column": "lon", "y_column": "lat", "wkt_column": None}

    def test_detects_longitude_latitude_spelled_out(self):
        cols = [
            {"name": "Longitude", "type": "real"},
            {"name": "Latitude", "type": "real"},
        ]
        result = detect_geometry_columns(cols)
        # Preserves original casing
        assert result["x_column"] == "Longitude"
        assert result["y_column"] == "Latitude"
        assert result["wkt_column"] is None

    def test_detects_wkt_geom_column(self):
        cols = [
            {"name": "id", "type": "integer"},
            {"name": "the_geom", "type": "text"},
        ]
        result = detect_geometry_columns(cols)
        assert result["wkt_column"] == "the_geom"
        assert result["x_column"] is None
        assert result["y_column"] is None

    def test_case_insensitive_match(self):
        cols = [{"name": "LAT_DD"}, {"name": "LON_DD"}]
        result = detect_geometry_columns(cols)
        # Matches are case-insensitive on the pattern side but the returned
        # value is the original column name
        assert result["x_column"] == "LON_DD"
        assert result["y_column"] == "LAT_DD"

    def test_returns_none_when_nothing_matches(self):
        cols = [{"name": "foo"}, {"name": "bar"}]
        assert detect_geometry_columns(cols) == {
            "x_column": None,
            "y_column": None,
            "wkt_column": None,
        }

    def test_empty_columns_list(self):
        assert detect_geometry_columns([]) == {
            "x_column": None,
            "y_column": None,
            "wkt_column": None,
        }


class TestResolveSourcePath:
    def test_plain_file_returned_unchanged(self):
        assert _resolve_source_path("/tmp/data.geojson") == "/tmp/data.geojson"
        assert _resolve_source_path("/tmp/data.shp") == "/tmp/data.shp"

    def test_zip_wrapped_with_vsizip(self):
        assert _resolve_source_path("/tmp/data.zip") == "/vsizip//tmp/data.zip"

    def test_case_matters_on_extension(self):
        # Uppercase .ZIP is NOT wrapped — the helper is case-sensitive
        assert _resolve_source_path("/tmp/data.ZIP") == "/tmp/data.ZIP"


class TestExtractSridFromJson:
    def test_returns_none_for_empty(self):
        assert _extract_srid_from_json({}) is None
        assert _extract_srid_from_json(None) is None

    def test_extracts_from_projjson_id(self):
        coord = {
            "projjson": {
                "id": {"authority": "EPSG", "code": 4326},
            }
        }
        assert _extract_srid_from_json(coord) == 4326

    def test_extracts_from_projjson_id_string_code(self):
        # Some GDAL versions emit the code as a string
        coord = {
            "projjson": {
                "id": {"authority": "EPSG", "code": "3857"},
            }
        }
        assert _extract_srid_from_json(coord) == 3857

    def test_ignores_non_epsg_authority(self):
        # IAU codes etc. should not be confused for EPSG
        coord = {
            "projjson": {
                "id": {"authority": "IAU", "code": 30100},
            }
        }
        # Falls through to WKT (which is missing) → None
        assert _extract_srid_from_json(coord) is None

    def test_falls_back_to_wkt_authority(self):
        wkt = 'PROJCS["whatever", AUTHORITY["EPSG","26918"]]'
        assert _extract_srid_from_json({"wkt": wkt}) == 26918

    def test_no_wkt_authority_returns_none(self):
        wkt = 'PROJCS["whatever"]'
        assert _extract_srid_from_json({"wkt": wkt}) is None

    def test_prefers_projjson_over_wkt(self):
        coord = {
            "projjson": {"id": {"authority": "EPSG", "code": 4326}},
            "wkt": 'AUTHORITY["EPSG","3857"]',
        }
        assert _extract_srid_from_json(coord) == 4326


class TestParseTextOgrinfo:
    def test_parses_full_output(self):
        # The text parser scans for the ``EPSG:<n>`` literal, which appears
        # in the ``Layer SRS WKT`` line on ogrinfo text output (e.g.
        # "ID[EPSG,26918]" on modern GDAL, but older GDAL also prints an
        # "EPSG:26918" line separately — we include that here).
        output = (
            "INFO: Open of `foo.shp'\n"
            "Layer name: parcels\n"
            "Geometry: Polygon\n"
            "Feature Count: 1234\n"
            "Layer SRS WKT:\n"
            '    PROJCS["NAD83"]\n'
            "EPSG:26918\n"
        )
        result = _parse_text_ogrinfo(output)
        assert result["layer_name"] == "parcels"
        assert result["geometry_type"] == "Polygon"
        assert result["feature_count"] == 1234
        assert result["srid"] == 26918

    def test_handles_missing_fields(self):
        output = "Layer name: empty\n"
        result = _parse_text_ogrinfo(output)
        assert result["layer_name"] == "empty"
        assert result["geometry_type"] is None
        assert result["feature_count"] is None
        assert result["srid"] is None

    def test_invalid_feature_count_is_tolerated(self):
        output = "Feature Count: not-a-number\nGeometry: Point\n"
        result = _parse_text_ogrinfo(output)
        # Parser swallows the ValueError and leaves feature_count as None
        assert result["feature_count"] is None
        assert result["geometry_type"] == "Point"

    def test_first_epsg_wins(self):
        output = "EPSG:4326\nEPSG:3857\n"
        assert _parse_text_ogrinfo(output)["srid"] == 4326

    def test_empty_output(self):
        assert _parse_text_ogrinfo("") == {
            "srid": None,
            "geometry_type": None,
            "layer_name": "",
            "feature_count": None,
        }
