"""Unit tests for ephemeral GeoJSON extraction from query_data results."""

import json
from datetime import datetime, date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import shapely


# Import helpers from chat_service
from app.processing.ai.chat_service import (
    _is_geom_value,
    _detect_geom_column,
    _safe_value,
    _extract_geojson,
    ensure_geometry_selected,
    strip_geometry_columns,
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
        assert _detect_geom_column(cols, [row]) == 2

    def test_geometry_column_name(self):
        cols = ["id", "geometry"]
        row = [1, POINT_WKB_HEX]
        assert _detect_geom_column(cols, [row]) == 1

    def test_the_geom_column_name(self):
        cols = ["the_geom", "name"]
        row = [POINT_WKB_HEX, "test"]
        assert _detect_geom_column(cols, [row]) == 0

    def test_st_prefix_column(self):
        cols = ["id", "st_asgeojson"]
        row = [1, POINT_GEOJSON_STR]
        assert _detect_geom_column(cols, [row]) == 1

    def test_no_geom_column(self):
        cols = ["id", "name", "population"]
        row = [1, "test", 1000]
        assert _detect_geom_column(cols, [row]) is None

    def test_geom_name_but_null_value(self):
        """Column name matches but value is null -- still detected (None values are skipped later)."""
        cols = ["id", "geom"]
        row = [1, None]
        # With null value, _is_geom_value returns False, so no detection
        assert _detect_geom_column(cols, [row]) is None

    def test_null_leading_row_probes_later_rows(self):
        # fix(#556 review P2): a NULL geometry in row 0 must not break
        # detection when later rows are mappable.
        cols = ["id", "geom_4326"]
        rows = [[1, None], [2, POINT_WKB_HEX]]
        assert _detect_geom_column(cols, rows) == 1

    def test_value_fallback_detects_aliased_geometry(self):
        # fix(#556 review P2): aliased computed geometry (ST_Buffer(...) AS
        # buffer) has no geometry-ish name — detect it by value.
        cols = ["name", "buffer"]
        rows = [["A", POINT_WKB_HEX]]
        assert _detect_geom_column(cols, rows) == 1

    def test_value_fallback_ignores_non_geometry_json(self):
        cols = ["name", "meta"]
        rows = [["A", json.dumps({"type": "station", "zone": 2})]]
        assert _detect_geom_column(cols, rows) is None

    def test_value_fallback_skips_hex_hash_column(self):
        # fix(#556 review P2): md5(name) AS id is a long even-length hex
        # string but not WKB — it must not shadow the real geometry column.
        md5_hex = "9e107d9d372bb6826bd81d3542a419d6"
        cols = ["id", "buffer"]
        rows = [[md5_hex, POINT_WKB_HEX]]
        assert _detect_geom_column(cols, rows) == 1


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

    def test_null_leading_geometry_still_extracts(self):
        # fix(#556 review P2): first row NULL, later rows mappable.
        cols = ["id", "geom_4326"]
        rows = [[1, None], [2, POINT_WKB_HEX]]
        result = _extract_geojson(cols, rows)
        assert result is not None
        fc, _ = result
        assert len(fc["features"]) == 1

    def test_aliased_computed_geometry_extracts(self):
        # fix(#556 review P2): ST_Buffer(...) AS buffer — the overlay must
        # come from the computed geometry, found by value.
        cols = ["name", "buffer"]
        rows = [["A", POINT_WKB_HEX]]
        result = _extract_geojson(cols, rows)
        assert result is not None
        fc, _ = result
        assert fc["features"][0]["properties"] == {"name": "A"}


# ---------------------------------------------------------------------------
# fix(#544): deterministic geometry append + WKB stripping
# ---------------------------------------------------------------------------


def _layer(table="parks", geometry_type="Polygon"):
    return SimpleNamespace(dataset_table_name=table, geometry_type=geometry_type)


class TestEnsureGeometrySelected:
    def test_appends_geometry_to_plain_select(self):
        sql = ensure_geometry_selected("SELECT name FROM data.parks", [_layer()])
        assert sql == "SELECT name, parks.geom_4326 FROM data.parks"

    def test_uses_table_alias(self):
        sql = ensure_geometry_selected(
            "SELECT p.name FROM data.parks AS p WHERE p.name ILIKE '%river%'",
            [_layer()],
        )
        assert "p.geom_4326" in sql

    def test_preserves_quoted_uppercase_alias(self):
        # fix(#556 review P2): a quoted alias must survive the append — unquoted
        # "P" folds to lowercase p in Postgres and fails at execution.
        sql = ensure_geometry_selected(
            'SELECT "P".name FROM data.parks AS "P"', [_layer()]
        )
        assert '"P".geom_4326' in sql

    def test_preserves_alias_with_spaces(self):
        # fix(#556 review P2): a spaced alias must not raise a ParseError inside
        # stmt.select() (the old f-string path did).
        sql = ensure_geometry_selected(
            'SELECT t.name FROM data.parks AS "my tbl"', [_layer()]
        )
        assert '"my tbl".geom_4326' in sql

    def test_skips_when_geometry_already_selected(self):
        sql = "SELECT name, geom_4326 FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_unaliased_st_asgeojson(self):
        sql = "SELECT name, ST_ASGEOJSON(geom_4326) FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_appends_when_st_x_only(self):
        # ST_X yields a float, not a detectable geometry — still append.
        sql = ensure_geometry_selected(
            "SELECT name, ST_X(geom_4326) AS longitude, ST_Y(geom_4326) AS latitude"
            " FROM data.parks",
            [_layer()],
        )
        assert sql.count("geom_4326") == 3
        assert "parks.geom_4326" in sql

    def test_appends_when_scalar_aliased_to_geometry_name(self):
        # fix(#556 review P2): md5(name) AS geometry is a scalar aliased to a
        # geometry-looking name — the append must still fire (the alias name
        # alone must not count as selected geometry).
        sql = ensure_geometry_selected(
            "SELECT md5(name) AS geometry FROM data.parks", [_layer()]
        )
        assert "parks.geom_4326" in sql

    def test_appends_when_st_x_aliased_to_st_name(self):
        # fix(#556 review P2): ST_X(...) AS st_x — scalar under an st_-prefixed
        # alias; append must fire.
        sql = ensure_geometry_selected(
            "SELECT name, ST_X(geom_4326) AS st_x FROM data.parks", [_layer()]
        )
        assert "parks.geom_4326" in sql
        # the scalar st_x is untouched; only the source geom_4326 is added
        assert sql.count("geom_4326") == 2

    def test_skips_select_star(self):
        sql = "SELECT * FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_aggregates(self):
        sql = "SELECT COUNT(*) FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_anonymous_aggregate(self):
        sql = "SELECT EVERY(name IS NOT NULL) FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_ordered_set_aggregate(self):
        # MODE()/PERCENTILE_* parse as exp.AggFunc subclasses — still blocked
        # (they collapse to one row), independent of the _ANON_AGG_NAMES gate.
        sql = "SELECT MODE() WITHIN GROUP (ORDER BY category) FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_appends_when_casting_column_named_like_aggregate(self):
        # fix(#556 review P2): CAST(mode AS TEXT) is exp.Cast with name="mode";
        # the _ANON_AGG_NAMES check must not fire on named funcs, or a row-level
        # query casting a column named `mode` loses its overlay.
        sql = ensure_geometry_selected(
            "SELECT name, CAST(mode AS TEXT) AS mode_text FROM data.parks",
            [_layer()],
        )
        assert "parks.geom_4326" in sql

    def test_appends_for_window_count(self):
        # fix(#556 review P2): COUNT(*) OVER () is a row-level window function
        # (no cardinality collapse, no GROUP BY) — the append must still fire.
        sql = ensure_geometry_selected(
            "SELECT name, COUNT(*) OVER () AS total FROM data.parks", [_layer()]
        )
        assert "parks.geom_4326" in sql

    def test_appends_for_window_rank(self):
        sql = ensure_geometry_selected(
            "SELECT name, RANK() OVER (ORDER BY name DESC) AS r FROM data.parks",
            [_layer()],
        )
        assert "parks.geom_4326" in sql

    def test_skips_group_by(self):
        sql = "SELECT category, COUNT(*) AS n FROM data.parks GROUP BY category"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_distinct(self):
        sql = "SELECT DISTINCT category FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_having_without_group_by(self):
        # fix(#556 review P2): HAVING without GROUP BY is an aggregate query
        # (implicit single group) — appending geom_4326 makes Postgres reject
        # the non-grouped column. The COUNT lives outside the SELECT list.
        sql = "SELECT 1 FROM data.parks HAVING COUNT(*) > 0"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_appends_despite_subquery_having(self):
        # A HAVING inside a subquery does not make the outer query an aggregate;
        # the append must still fire on the row-level outer SELECT.
        sql = ensure_geometry_selected(
            "SELECT name FROM data.parks WHERE category IN "
            "(SELECT category FROM data.parks GROUP BY category HAVING COUNT(*) > 1)",
            [_layer()],
        )
        assert "parks.geom_4326" in sql

    def test_skips_joins(self):
        sql = (
            "SELECT p.name FROM data.parks AS p"
            " JOIN data.cities AS c ON ST_INTERSECTS(p.geom_4326, c.geom_4326)"
        )
        assert ensure_geometry_selected(sql, [_layer(), _layer(table="cities")]) == sql

    def test_skips_cte(self):
        sql = "WITH big AS (SELECT name FROM data.parks) SELECT name FROM big"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_union(self):
        sql = "SELECT name FROM data.parks UNION SELECT name FROM data.cities"
        assert ensure_geometry_selected(sql, [_layer(), _layer(table="cities")]) == sql

    def test_skips_non_geometry_layer(self):
        sql = "SELECT name FROM data.attendance"
        layers = [_layer(table="attendance", geometry_type=None)]
        assert ensure_geometry_selected(sql, layers) == sql

    def test_skips_table_not_in_layers(self):
        sql = "SELECT name FROM data.other_table"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_unparseable_sql_unchanged(self):
        sql = "SELECT FROM WHERE ((("
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_aliased_geometry_column(self):
        # fix(#556 review P2): geom_4326 AS location already yields geometry
        # (found by value) — appending the source column would duplicate it.
        sql = "SELECT name, geom_4326 AS location FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_aliased_computed_geometry(self):
        # fix(#556 review P2): the overlay must show the buffers, not the
        # source geometry — don't append geom_4326 beside them.
        sql = (
            "SELECT name, ST_BUFFER(geom_4326::geography, 1000)::geometry"
            " AS buffer FROM data.parks"
        )
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_unaliased_cast_wrapped_geometry(self):
        # fix(#556 review P2): an UNALIASED cast-wrapped geometry expression
        # already selects geometry — the append must be suppressed even though
        # there's no AS clause. Previously the Cast/Paren unwrap only ran
        # inside exp.Alias, so geom_4326 got appended beside the buffer.
        sql = "SELECT ST_BUFFER(geom_4326::geography, 1000)::geometry FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_unaliased_parenthesized_cast_geometry(self):
        sql = "SELECT (ST_BUFFER(geom_4326::geography, 1000)::geometry) FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_unaliased_cast_of_geom_column(self):
        sql = "SELECT geom_4326::geometry FROM data.parks"
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_skips_parenthesized_aliased_geometry(self):
        # fix(#556 review P2): sqlglot wraps a parenthesized alias body in
        # exp.Paren — unwrap it too, or the source geometry gets appended
        # and the overlay shows the wrong shapes.
        sql = (
            "SELECT name, (ST_BUFFER(geom_4326::geography, 1000)::geometry)"
            " AS buffer FROM data.parks"
        )
        assert ensure_geometry_selected(sql, [_layer()]) == sql

    def test_row_level_spatial_expr_still_appends(self):
        # ST_Distance is row-level (not an aggregate) — append proceeds.
        sql = ensure_geometry_selected(
            "SELECT name, ST_DISTANCE(geom_4326, geom_4326) AS d FROM data.parks",
            [_layer()],
        )
        assert "parks.geom_4326" in sql


class TestStripGeometryColumns:
    def test_strips_wkb_column(self):
        cols, rows = strip_geometry_columns(
            ["name", "geom_4326"], [["A", POINT_WKB_HEX], ["B", POINT2_WKB_HEX]]
        )
        assert cols == ["name"]
        assert rows == [["A"], ["B"]]

    def test_no_geom_column_unchanged(self):
        cols, rows = strip_geometry_columns(["name", "pop"], [["A", 1]])
        assert cols == ["name", "pop"]
        assert rows == [["A", 1]]

    def test_empty_rows_unchanged(self):
        cols, rows = strip_geometry_columns(["name", "geom_4326"], [])
        assert cols == ["name", "geom_4326"]
        assert rows == []

    def test_short_row_padded_with_none(self):
        cols, rows = strip_geometry_columns(
            ["geom_4326", "name", "pop"], [[POINT_WKB_HEX, "A"]]
        )
        assert cols == ["name", "pop"]
        assert rows == [["A", None]]

    def test_strips_aliased_geojson_string_column(self):
        # Live smoke (#544): the model emitted ST_AsGeoJSON(geom_4326) AS
        # location — a name-based strip missed it and raw GeoJSON strings
        # rendered in the table. Value-based strip drops both geometry cols.
        cols, rows = strip_geometry_columns(
            ["stop_name", "location", "geom_4326"],
            [["Jay St", POINT_GEOJSON_STR, POINT_WKB_HEX]],
        )
        assert cols == ["stop_name"]
        assert rows == [["Jay St"]]

    def test_json_attribute_with_type_key_kept(self):
        meta = json.dumps({"type": "station", "zone": 2})
        cols, rows = strip_geometry_columns(
            ["name", "meta", "geom_4326"], [["A", meta, POINT_WKB_HEX]]
        )
        assert cols == ["name", "meta"]
        assert rows == [["A", meta]]

    def test_null_leading_geometry_still_stripped(self):
        # fix(#556 review P2): NULL geometry in row 0 must not leak later
        # rows' WKB into the table.
        cols, rows = strip_geometry_columns(
            ["name", "geom_4326"], [["A", None], ["B", POINT_WKB_HEX]]
        )
        assert cols == ["name"]
        assert rows == [["A"], ["B"]]

    def test_hex_hash_column_kept(self):
        # fix(#556 review P2): hex-like attributes (md5 hashes) are not
        # geometry and must stay in the table.
        md5_hex = "9e107d9d372bb6826bd81d3542a419d6"
        cols, rows = strip_geometry_columns(
            ["id", "geom_4326"], [[md5_hex, POINT_WKB_HEX]]
        )
        assert cols == ["id"]
        assert rows == [[md5_hex]]
