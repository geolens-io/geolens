"""Unit tests for the pure (no-subprocess) helpers in app.ingest.ogr.

These exercise the geometry-column sniffer, the source-path wrapper, the SRID
extraction from ogrinfo JSON output, and the text-fallback parser. All of
them are zero-dependency functions — no GDAL or database calls — so they are
safe to run in any environment.
"""

import asyncio

import pytest

from app.ingest.metadata import _sql_quote_ident
from app.ingest.ogr import (
    _extract_common_layer_metadata,
    _extract_srid_from_json,
    _parse_text_ogrinfo,
    _resolve_source_path,
    detect_geometry_columns,
)
from app.ingest.tasks import (
    _append_job_warning,
    _run_service_import_with_wfs_fallback,
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


class TestDetectDbfTruncationCollisions:
    """Pure-unit tests for the DBF 10-char truncation collision detector.

    These tests do not require ogr2ogr or a database and always run
    regardless of environment (RESEARCH §2.3).
    """

    def test_detects_collision(self):
        from app.ingest.metadata import detect_dbf_truncation_collisions

        cols = [
            {"name": "population_2020", "type": "Integer"},
            {"name": "population_2021", "type": "Integer"},
            {"name": "region", "type": "String"},
        ]
        result = detect_dbf_truncation_collisions(cols)
        assert len(result) == 1
        assert sorted(result[0]["originals"]) == ["population_2020", "population_2021"]
        # 'population_2020'[:10] = 'population'
        assert result[0]["truncated"] == "population"

    def test_no_collision_when_names_differ_in_first_10(self):
        from app.ingest.metadata import detect_dbf_truncation_collisions

        cols = [
            {"name": "pop_2020", "type": "Integer"},
            {"name": "pop_2021", "type": "Integer"},
        ]
        # 'pop_2020'[:10] = 'pop_2020', 'pop_2021'[:10] = 'pop_2021' — no collision
        result = detect_dbf_truncation_collisions(cols)
        assert result == []

    def test_empty_input(self):
        from app.ingest.metadata import detect_dbf_truncation_collisions

        assert detect_dbf_truncation_collisions([]) == []

    def test_single_column_not_a_collision(self):
        from app.ingest.metadata import detect_dbf_truncation_collisions

        cols = [{"name": "population_2020", "type": "Integer"}]
        assert detect_dbf_truncation_collisions(cols) == []

    def test_truncation_is_case_insensitive(self):
        from app.ingest.metadata import detect_dbf_truncation_collisions

        # GDAL LAUNDER=YES lowercases names; the helper also lowercases
        cols = [
            {"name": "Population_2020", "type": "Integer"},
            {"name": "population_2021", "type": "Integer"},
        ]
        result = detect_dbf_truncation_collisions(cols)
        assert len(result) == 1
        assert sorted(result[0]["originals"]) == ["Population_2020", "population_2021"]

    def test_multiple_collision_groups(self):
        from app.ingest.metadata import detect_dbf_truncation_collisions

        cols = [
            {"name": "population_2020", "type": "Integer"},
            {"name": "population_2021", "type": "Integer"},
            {"name": "temperature_avg", "type": "Real"},
            {"name": "temperature_max", "type": "Real"},
            {"name": "region", "type": "String"},
        ]
        result = detect_dbf_truncation_collisions(cols)
        assert len(result) == 2
        truncated_keys = {r["truncated"] for r in result}
        assert "population" in truncated_keys
        assert "temperatur" in truncated_keys


class TestSqlQuoteIdent:
    """Post-impl audit PERF-6 / KISS-N helper."""

    def test_plain_identifier(self):
        assert _sql_quote_ident("foo") == '"foo"'

    def test_identifier_with_spaces(self):
        assert _sql_quote_ident("my col") == '"my col"'

    def test_identifier_with_embedded_double_quote(self):
        # Embedded double quote must be doubled (PostgreSQL standard).
        assert _sql_quote_ident('foo"bar') == '"foo""bar"'

    def test_non_ascii_identifier_preserved(self):
        # Non-ASCII / mixed-case / CJK must round-trip without escaping.
        assert _sql_quote_ident("nom_français") == '"nom_français"'
        assert _sql_quote_ident("名称") == '"名称"'

    def test_empty_identifier(self):
        # Empty string is technically valid but unusual — we still quote it.
        assert _sql_quote_ident("") == '""'

    def test_identifier_with_multiple_quotes(self):
        assert _sql_quote_ident('a"b"c') == '"a""b""c"'


class TestExtractCommonLayerMetadata:
    """Post-impl audit KISS-12 helper — shared ogrinfo JSON parser."""

    def test_raises_keyerror_when_no_layers(self):
        with pytest.raises(KeyError):
            _extract_common_layer_metadata({"layers": []}, None)

    def test_raises_keyerror_when_layers_missing(self):
        with pytest.raises(KeyError):
            _extract_common_layer_metadata({}, None)

    def test_single_layer_with_geometry(self):
        data = {
            "layers": [
                {
                    "name": "parcels",
                    "featureCount": 42,
                    "geometryFields": [
                        {
                            "type": "Polygon",
                            "coordinateSystem": {
                                "wkt": 'GEOGCS["WGS 84",AUTHORITY["EPSG","4326"]]'
                            },
                        }
                    ],
                }
            ]
        }
        target, meta = _extract_common_layer_metadata(data, None)
        assert target["name"] == "parcels"
        assert meta["srid"] == 4326
        assert meta["geometry_type"] == "Polygon"
        assert meta["layer_name"] == "parcels"
        assert meta["feature_count"] == 42
        assert meta["all_layers"] is None  # single layer → no list

    def test_coord_system_at_top_level(self):
        # Some GDAL versions place coordinateSystem at the layer root
        # instead of nested inside geometryFields[0].
        data = {
            "layers": [
                {
                    "name": "roads",
                    "featureCount": 100,
                    "coordinateSystem": {
                        "wkt": 'PROJCS["X",AUTHORITY["EPSG","3857"]]'
                    },
                    "geometryFields": [{"type": "LineString"}],
                }
            ]
        }
        _, meta = _extract_common_layer_metadata(data, None)
        assert meta["srid"] == 3857
        assert meta["geometry_type"] == "LineString"

    def test_non_spatial_layer_has_no_geometry_fields(self):
        data = {
            "layers": [
                {
                    "name": "lookup_table",
                    "featureCount": 5,
                    "geometryFields": [],
                }
            ]
        }
        _, meta = _extract_common_layer_metadata(data, None)
        assert meta["srid"] is None
        assert meta["geometry_type"] is None
        assert meta["feature_count"] == 5

    def test_multi_layer_picks_first_without_layer_name(self):
        data = {
            "layers": [
                {
                    "name": "first",
                    "featureCount": 10,
                    "geometryFields": [{"type": "Point"}],
                },
                {
                    "name": "second",
                    "featureCount": 20,
                    "geometryFields": [{"type": "Polygon"}],
                },
            ]
        }
        target, meta = _extract_common_layer_metadata(data, None)
        assert target["name"] == "first"
        assert meta["geometry_type"] == "Point"
        # all_layers surfaces the list when multiple layers exist
        assert meta["all_layers"] is not None
        assert len(meta["all_layers"]) == 2
        assert {lyr["name"] for lyr in meta["all_layers"]} == {"first", "second"}

    def test_multi_layer_picks_named_layer(self):
        data = {
            "layers": [
                {
                    "name": "first",
                    "featureCount": 10,
                    "geometryFields": [{"type": "Point"}],
                },
                {
                    "name": "second",
                    "featureCount": 20,
                    "geometryFields": [{"type": "Polygon"}],
                },
            ]
        }
        target, meta = _extract_common_layer_metadata(data, "second")
        assert target["name"] == "second"
        assert meta["geometry_type"] == "Polygon"
        # all_layers is None when a specific layer was requested
        assert meta["all_layers"] is None

    def test_multi_layer_named_layer_not_found_falls_back_to_first(self):
        data = {
            "layers": [
                {"name": "first", "featureCount": 10, "geometryFields": []},
                {"name": "second", "featureCount": 20, "geometryFields": []},
            ]
        }
        target, _ = _extract_common_layer_metadata(data, "missing")
        assert target["name"] == "first"


class _FakeJob:
    """Minimal stand-in for IngestJob for pure-unit tests."""

    def __init__(self, user_metadata=None):
        self.user_metadata = user_metadata


class TestAppendJobWarning:
    """Post-impl audit KISS-1 helper — consolidated warning accumulator."""

    def test_appends_to_empty_user_metadata(self):
        job = _FakeJob(user_metadata=None)
        _append_job_warning(job, {"kind": "reserved_rename", "details": [{"a": 1}]})
        assert job.user_metadata == {
            "warnings": [{"kind": "reserved_rename", "details": [{"a": 1}]}]
        }

    def test_appends_to_existing_metadata_without_warnings(self):
        job = _FakeJob(user_metadata={"title": "Roads", "visibility": "public"})
        _append_job_warning(job, {"kind": "dbf_truncation_collision", "details": []})
        assert job.user_metadata["title"] == "Roads"
        assert job.user_metadata["visibility"] == "public"
        assert job.user_metadata["warnings"] == [
            {"kind": "dbf_truncation_collision", "details": []}
        ]

    def test_appends_to_existing_warnings_list(self):
        job = _FakeJob(
            user_metadata={
                "warnings": [{"kind": "reserved_rename", "details": [{"a": 1}]}]
            }
        )
        _append_job_warning(job, {"kind": "dbf_truncation_collision", "details": []})
        assert len(job.user_metadata["warnings"]) == 2
        assert job.user_metadata["warnings"][0]["kind"] == "reserved_rename"
        assert job.user_metadata["warnings"][1]["kind"] == "dbf_truncation_collision"

    def test_preserves_unrelated_metadata_keys(self):
        job = _FakeJob(
            user_metadata={
                "title": "T",
                "collision_warning": "old",
                "warnings": [{"kind": "a"}],
            }
        )
        _append_job_warning(job, {"kind": "b"})
        assert job.user_metadata["title"] == "T"
        assert job.user_metadata["collision_warning"] == "old"
        assert [w["kind"] for w in job.user_metadata["warnings"]] == ["a", "b"]

    def test_does_not_mutate_original_user_metadata_dict_identity(self):
        # The helper replaces user_metadata with a new dict so SQLAlchemy
        # JSONB change-detection sees a dirty attribute.
        original = {"title": "T", "warnings": [{"kind": "a"}]}
        job = _FakeJob(user_metadata=original)
        _append_job_warning(job, {"kind": "b"})
        assert job.user_metadata is not original


class TestRunServiceImportWithWfsFallback:
    """Post-impl audit KISS-8 helper — WFS namespace retry + auth detection."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_success_on_first_try_no_retry(self):
        from app.ingest.ogr import IngestionError  # noqa: F401

        calls = []

        async def import_fn(layer_name: str) -> None:
            calls.append(layer_name)

        asyncio.run(
            _run_service_import_with_wfs_fallback(import_fn, "workspace:roads")
        )
        assert calls == ["workspace:roads"]

    def test_retries_with_unqualified_layer_on_ingestion_error(self):
        from app.ingest.ogr import IngestionError

        calls = []

        async def import_fn(layer_name: str) -> None:
            calls.append(layer_name)
            if ":" in layer_name:
                raise IngestionError("WFS layer not found")

        asyncio.run(
            _run_service_import_with_wfs_fallback(import_fn, "workspace:roads")
        )
        assert calls == ["workspace:roads", "roads"]

    def test_reraises_when_layer_has_no_namespace(self):
        from app.ingest.ogr import IngestionError

        async def import_fn(layer_name: str) -> None:
            raise IngestionError("any error")

        with pytest.raises(IngestionError, match="any error"):
            asyncio.run(_run_service_import_with_wfs_fallback(import_fn, "roads"))

    def test_reraises_when_both_attempts_fail(self):
        from app.ingest.ogr import IngestionError

        calls = []

        async def import_fn(layer_name: str) -> None:
            calls.append(layer_name)
            raise IngestionError(f"fail {layer_name}")

        with pytest.raises(IngestionError, match="fail roads"):
            asyncio.run(
                _run_service_import_with_wfs_fallback(import_fn, "workspace:roads")
            )
        # Retried once with unqualified name, both failed.
        assert calls == ["workspace:roads", "roads"]

    def test_auth_error_message_raised_on_no_namespace_auth_failure(self):
        from app.ingest.ogr import IngestionError

        async def import_fn(layer_name: str) -> None:
            raise IngestionError("HTTP 401 Unauthorized")

        with pytest.raises(IngestionError, match="needs a token"):
            asyncio.run(
                _run_service_import_with_wfs_fallback(
                    import_fn,
                    "roads",
                    token=None,
                    auth_error_message="This service needs a token",
                )
            )

    def test_auth_error_message_raised_on_retry_auth_failure(self):
        from app.ingest.ogr import IngestionError

        async def import_fn(layer_name: str) -> None:
            raise IngestionError("HTTP 403 Forbidden")

        with pytest.raises(IngestionError, match="needs a token"):
            asyncio.run(
                _run_service_import_with_wfs_fallback(
                    import_fn,
                    "workspace:roads",
                    token=None,
                    auth_error_message="This service needs a token",
                )
            )

    def test_auth_error_suppressed_when_token_provided(self):
        # If the caller DID provide a token and it still fails, the auth
        # message is NOT substituted — the user already tried a token.
        from app.ingest.ogr import IngestionError

        async def import_fn(layer_name: str) -> None:
            raise IngestionError("HTTP 401 Unauthorized")

        with pytest.raises(IngestionError, match="Unauthorized"):
            asyncio.run(
                _run_service_import_with_wfs_fallback(
                    import_fn,
                    "roads",
                    token="supplied_token",
                    auth_error_message="This service needs a token",
                )
            )

    def test_auth_error_message_not_used_on_non_auth_error(self):
        from app.ingest.ogr import IngestionError

        async def import_fn(layer_name: str) -> None:
            raise IngestionError("Connection refused")

        with pytest.raises(IngestionError, match="Connection refused"):
            asyncio.run(
                _run_service_import_with_wfs_fallback(
                    import_fn,
                    "roads",
                    token=None,
                    auth_error_message="This service needs a token",
                )
            )
