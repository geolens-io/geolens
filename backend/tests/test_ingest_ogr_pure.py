"""Unit tests for the pure (no-subprocess) helpers in app.ingest.ogr.

These exercise the geometry-column sniffer, the source-path wrapper, the SRID
extraction from ogrinfo JSON output, and the text-fallback parser. All of
them are zero-dependency functions — no GDAL or database calls — so they are
safe to run in any environment.
"""

import asyncio

import pytest

from app.processing.ingest.metadata import _sql_quote_ident
from app.processing.ingest.ogr import (
    _extract_common_layer_metadata,
    _sanitize_authorization_token,
    _strip_ogr_driver_list,
    extract_srid_from_json,
    _parse_text_ogrinfo,
    _resolve_source_path,
    detect_geometry_columns,
)
from app.processing.ingest.tasks import (
    _append_job_warning,
    _bind_task_log_context,
    _parse_temporal_fields,
    _resolve_effective_srid,
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
        assert extract_srid_from_json({}) is None
        assert extract_srid_from_json(None) is None

    def test_extracts_from_projjson_id(self):
        coord = {
            "projjson": {
                "id": {"authority": "EPSG", "code": 4326},
            }
        }
        assert extract_srid_from_json(coord) == 4326

    def test_extracts_from_projjson_id_string_code(self):
        # Some GDAL versions emit the code as a string
        coord = {
            "projjson": {
                "id": {"authority": "EPSG", "code": "3857"},
            }
        }
        assert extract_srid_from_json(coord) == 3857

    def test_ignores_non_epsg_authority(self):
        # IAU codes etc. should not be confused for EPSG
        coord = {
            "projjson": {
                "id": {"authority": "IAU", "code": 30100},
            }
        }
        # Falls through to WKT (which is missing) → None
        assert extract_srid_from_json(coord) is None

    def test_falls_back_to_wkt_authority(self):
        wkt = 'PROJCS["whatever", AUTHORITY["EPSG","26918"]]'
        assert extract_srid_from_json({"wkt": wkt}) == 26918

    def test_no_wkt_authority_returns_none(self):
        wkt = 'PROJCS["whatever"]'
        assert extract_srid_from_json({"wkt": wkt}) is None

    def test_prefers_projjson_over_wkt(self):
        coord = {
            "projjson": {"id": {"authority": "EPSG", "code": 4326}},
            "wkt": 'AUTHORITY["EPSG","3857"]',
        }
        assert extract_srid_from_json(coord) == 4326


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
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions

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
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions

        cols = [
            {"name": "pop_2020", "type": "Integer"},
            {"name": "pop_2021", "type": "Integer"},
        ]
        # 'pop_2020'[:10] = 'pop_2020', 'pop_2021'[:10] = 'pop_2021' — no collision
        result = detect_dbf_truncation_collisions(cols)
        assert result == []

    def test_empty_input(self):
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions

        assert detect_dbf_truncation_collisions([]) == []

    def test_single_column_not_a_collision(self):
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions

        cols = [{"name": "population_2020", "type": "Integer"}]
        assert detect_dbf_truncation_collisions(cols) == []

    def test_truncation_is_case_insensitive(self):
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions

        # GDAL LAUNDER=YES lowercases names; the helper also lowercases
        cols = [
            {"name": "Population_2020", "type": "Integer"},
            {"name": "population_2021", "type": "Integer"},
        ]
        result = detect_dbf_truncation_collisions(cols)
        assert len(result) == 1
        assert sorted(result[0]["originals"]) == ["Population_2020", "population_2021"]

    def test_multiple_collision_groups(self):
        from app.processing.ingest.metadata import detect_dbf_truncation_collisions

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
                    "coordinateSystem": {"wkt": 'PROJCS["X",AUTHORITY["EPSG","3857"]]'},
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
        # Phase 1058 (GPKG-01): all_layers stays populated even when a specific
        # layer was requested, so the fan-out endpoint (Plan 1058-04) can
        # validate layer names without re-running ogrinfo.
        assert meta["all_layers"] is not None
        assert {lyr["name"] for lyr in meta["all_layers"]} == {"first", "second"}

    def test_multi_layer_named_layer_not_found_falls_back_to_first(self):
        data = {
            "layers": [
                {"name": "first", "featureCount": 10, "geometryFields": []},
                {"name": "second", "featureCount": 20, "geometryFields": []},
            ]
        }
        target, _ = _extract_common_layer_metadata(data, "missing")
        assert target["name"] == "first"

    def test_columns_populated_from_target_layer_fields(self):
        """PERF-1: columns come through the shared helper so shapefile ingest
        does not need a second run_ogrinfo_preview subprocess.
        """
        data = {
            "layers": [
                {
                    "name": "parcels",
                    "featureCount": 10,
                    "geometryFields": [{"type": "Polygon"}],
                    "fields": [
                        {"name": "PARCELID", "type": "String"},
                        {"name": "OWNER_NAME", "type": "String"},
                        {"name": "AREA_ACRES", "type": "Real"},
                    ],
                }
            ]
        }
        _, meta = _extract_common_layer_metadata(data, None)
        assert meta["columns"] == [
            {"name": "PARCELID", "type": "String"},
            {"name": "OWNER_NAME", "type": "String"},
            {"name": "AREA_ACRES", "type": "Real"},
        ]

    def test_columns_empty_when_target_layer_has_no_fields(self):
        data = {
            "layers": [
                {
                    "name": "empty",
                    "featureCount": 0,
                    "geometryFields": [],
                }
            ]
        }
        _, meta = _extract_common_layer_metadata(data, None)
        assert meta["columns"] == []


class _FakeJob:
    """Minimal stand-in for IngestJob for pure-unit tests."""

    def __init__(self, user_metadata=None):
        self.user_metadata = user_metadata


class TestAppendJobWarning:
    """Post-impl audit KISS-1 helper — consolidated warning accumulator.

    TYPE-1: warnings are now TypedDicts built via the producer helpers in
    ``app.ingest.warnings``. These tests exercise the accumulator logic;
    producer-shape tests live in ``TestIngestWarningProducers`` below.
    """

    def test_appends_to_empty_user_metadata(self):
        from app.processing.ingest.warnings import make_reserved_rename_warning

        job = _FakeJob(user_metadata=None)
        warning = make_reserved_rename_warning(
            [{"original": "gid", "renamed": "src_gid"}]
        )
        _append_job_warning(job, warning)
        assert job.user_metadata == {
            "warnings": [
                {
                    "kind": "reserved_rename",
                    "details": [{"original": "gid", "renamed": "src_gid"}],
                }
            ]
        }

    def test_appends_to_existing_metadata_without_warnings(self):
        from app.processing.ingest.warnings import make_dbf_truncation_warning

        job = _FakeJob(user_metadata={"title": "Roads", "visibility": "public"})
        _append_job_warning(job, make_dbf_truncation_warning([]))
        assert job.user_metadata["title"] == "Roads"
        assert job.user_metadata["visibility"] == "public"
        assert job.user_metadata["warnings"] == [
            {"kind": "dbf_truncation_collision", "details": []}
        ]

    def test_appends_to_existing_warnings_list(self):
        from app.processing.ingest.warnings import (
            make_dbf_truncation_warning,
            make_reserved_rename_warning,
        )

        first = make_reserved_rename_warning(
            [{"original": "gid", "renamed": "src_gid"}]
        )
        job = _FakeJob(user_metadata={"warnings": [first]})
        _append_job_warning(job, make_dbf_truncation_warning([]))
        assert len(job.user_metadata["warnings"]) == 2
        assert job.user_metadata["warnings"][0]["kind"] == "reserved_rename"
        assert job.user_metadata["warnings"][1]["kind"] == "dbf_truncation_collision"

    def test_preserves_unrelated_metadata_keys(self):
        from app.processing.ingest.warnings import (
            make_dbf_truncation_warning,
            make_reserved_rename_warning,
        )

        existing = make_reserved_rename_warning(
            [{"original": "fid", "renamed": "src_fid"}]
        )
        job = _FakeJob(
            user_metadata={
                "title": "T",
                "collision_warning": "old",
                "warnings": [existing],
            }
        )
        _append_job_warning(job, make_dbf_truncation_warning([]))
        assert job.user_metadata["title"] == "T"
        assert job.user_metadata["collision_warning"] == "old"
        assert [w["kind"] for w in job.user_metadata["warnings"]] == [
            "reserved_rename",
            "dbf_truncation_collision",
        ]

    def test_does_not_mutate_original_user_metadata_dict_identity(self):
        from app.processing.ingest.warnings import make_dbf_truncation_warning

        # The helper replaces user_metadata with a new dict so SQLAlchemy
        # JSONB change-detection sees a dirty attribute.
        original = {
            "title": "T",
            "warnings": [
                {"kind": "reserved_rename", "details": []},
            ],
        }
        job = _FakeJob(user_metadata=original)
        _append_job_warning(job, make_dbf_truncation_warning([]))
        assert job.user_metadata is not original


class TestIngestWarningProducers:
    """TYPE-1: ensure the producer helpers emit shapes the Pydantic models accept."""

    def test_reserved_rename_producer_round_trips_through_pydantic(self):
        from app.processing.ingest.warnings import make_reserved_rename_warning
        from app.platform.jobs.schemas import ReservedRenameWarning

        warning = make_reserved_rename_warning(
            [
                {"original": "geom", "renamed": "src_geom"},
                {"original": "fid", "renamed": "src_fid"},
            ]
        )
        validated = ReservedRenameWarning.model_validate(warning)
        assert validated.kind == "reserved_rename"
        assert len(validated.details) == 2
        assert validated.details[0].original == "geom"
        assert validated.details[1].renamed == "src_fid"

    def test_dbf_truncation_producer_round_trips_through_pydantic(self):
        from app.processing.ingest.warnings import make_dbf_truncation_warning
        from app.platform.jobs.schemas import DbfTruncationCollisionWarning

        warning = make_dbf_truncation_warning(
            [
                {
                    "truncated": "population",
                    "originals": ["population_2020", "population_2021"],
                }
            ]
        )
        validated = DbfTruncationCollisionWarning.model_validate(warning)
        assert validated.kind == "dbf_truncation_collision"
        assert validated.details[0].truncated == "population"
        assert validated.details[0].originals == [
            "population_2020",
            "population_2021",
        ]

    def test_reserved_rename_producer_coerces_missing_fields(self):
        """Missing original/renamed keys fall back to empty strings, not KeyError."""
        from app.processing.ingest.warnings import make_reserved_rename_warning

        warning = make_reserved_rename_warning([{"original": "gid"}])
        assert warning["details"][0]["original"] == "gid"
        assert warning["details"][0]["renamed"] == ""


class TestRunServiceImportWithWfsFallback:
    """Post-impl audit KISS-8 helper — WFS namespace retry + auth detection."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_success_on_first_try_no_retry(self):
        from app.processing.ingest.ogr import IngestionError  # noqa: F401

        calls = []

        async def import_fn(layer_name: str) -> None:
            calls.append(layer_name)

        asyncio.run(_run_service_import_with_wfs_fallback(import_fn, "workspace:roads"))
        assert calls == ["workspace:roads"]

    def test_retries_with_unqualified_layer_on_ingestion_error(self):
        from app.processing.ingest.ogr import IngestionError

        calls = []

        async def import_fn(layer_name: str) -> None:
            calls.append(layer_name)
            if ":" in layer_name:
                raise IngestionError("WFS layer not found")

        asyncio.run(_run_service_import_with_wfs_fallback(import_fn, "workspace:roads"))
        assert calls == ["workspace:roads", "roads"]

    def test_reraises_when_layer_has_no_namespace(self):
        from app.processing.ingest.ogr import IngestionError

        async def import_fn(layer_name: str) -> None:
            raise IngestionError("any error")

        with pytest.raises(IngestionError, match="any error"):
            asyncio.run(_run_service_import_with_wfs_fallback(import_fn, "roads"))

    def test_reraises_when_both_attempts_fail(self):
        from app.processing.ingest.ogr import IngestionError

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
        from app.processing.ingest.ogr import IngestionError

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
        from app.processing.ingest.ogr import IngestionError

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
        from app.processing.ingest.ogr import IngestionError

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
        from app.processing.ingest.ogr import IngestionError

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


class TestResolveEffectiveSrid:
    """Post-impl audit K1 extraction — ingest_file SRID resolution helper."""

    def test_override_wins_over_detected(self):
        """User-supplied srid_override takes precedence over ogrinfo-detected SRID."""
        assert _resolve_effective_srid(detected_srid=4326, srid_override=2154) == 2154

    def test_detected_used_when_no_override(self):
        """Detected SRID is used when override is None."""
        assert _resolve_effective_srid(detected_srid=3857, srid_override=None) == 3857

    def test_falls_back_to_4326_when_nothing_detected(self):
        """4326 is the safe default for GeoJSON/CSV with no detected CRS."""
        assert _resolve_effective_srid(detected_srid=None, srid_override=None) == 4326

    def test_override_wins_over_nothing(self):
        """srid_override also beats the None-and-fallback path."""
        assert _resolve_effective_srid(detected_srid=None, srid_override=32633) == 32633

    def test_returns_int_even_when_input_is_int_like(self):
        """Result is always a plain int — the caller feeds it to add_4326_column."""
        result = _resolve_effective_srid(detected_srid=4326, srid_override=None)
        assert isinstance(result, int)
        assert result == 4326


class TestBindTaskLogContext:
    """Post-impl audit N1 — worker task log correlation via structlog contextvars."""

    def test_binds_job_id_and_task_name(self):
        import structlog

        structlog.contextvars.clear_contextvars()
        _bind_task_log_context(task_name="ingest_file", job_id="job-123")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["task"] == "ingest_file"
        assert ctx["job_id"] == "job-123"
        assert ctx["service"] == "worker"
        structlog.contextvars.clear_contextvars()

    def test_clears_stale_vars_from_previous_task(self):
        """Re-used workers must not leak state from a prior job."""
        import structlog

        # Simulate leftover state from a previous run.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            stale_key="should_be_gone",
            task="old_task",
            job_id="old-job",
        )

        _bind_task_log_context(task_name="ingest_raster", job_id="job-456")

        ctx = structlog.contextvars.get_contextvars()
        assert ctx["task"] == "ingest_raster"
        assert ctx["job_id"] == "job-456"
        assert "stale_key" not in ctx, (
            f"stale_key from prior task leaked into new task context: {ctx}"
        )
        structlog.contextvars.clear_contextvars()

    def test_extra_kwargs_are_bound(self):
        """Callers can pass extra correlation keys (e.g., dataset_id for reupload)."""
        import structlog

        structlog.contextvars.clear_contextvars()
        _bind_task_log_context(
            task_name="reupload_file",
            job_id="job-789",
            dataset_id="ds-abc",
        )
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["dataset_id"] == "ds-abc"
        assert ctx["job_id"] == "job-789"
        structlog.contextvars.clear_contextvars()


class TestParseTemporalFields:
    """Post-impl audit N5 — raster ingest temporal field parsing + error surface."""

    def test_both_fields_valid(self):
        """Happy path: both fields parse cleanly, no errors."""
        from datetime import date

        start, end, errors = _parse_temporal_fields(
            temporal_start="2024-01-15",
            temporal_end="2024-12-31",
        )
        assert start == date(2024, 1, 15)
        assert end == date(2024, 12, 31)
        assert errors == {}

    def test_both_fields_none(self):
        """Both None → (None, None, {}) — the no-op case."""
        start, end, errors = _parse_temporal_fields(
            temporal_start=None, temporal_end=None
        )
        assert start is None
        assert end is None
        assert errors == {}

    def test_empty_string_treated_as_absent(self):
        """Empty strings are falsy → skipped, no errors recorded."""
        start, end, errors = _parse_temporal_fields(temporal_start="", temporal_end="")
        assert start is None
        assert end is None
        assert errors == {}

    def test_invalid_start_recorded_in_errors(self):
        """Unparseable temporal_start → parsed=None, errors['temporal_start']=raw."""
        from datetime import date

        start, end, errors = _parse_temporal_fields(
            temporal_start="not-a-date",
            temporal_end="2024-06-01",
        )
        assert start is None
        assert end == date(2024, 6, 1)
        assert errors == {"temporal_start": "not-a-date"}

    def test_invalid_end_recorded_in_errors(self):
        """Unparseable temporal_end → parsed=None, errors['temporal_end']=raw."""
        from datetime import date

        start, end, errors = _parse_temporal_fields(
            temporal_start="2024-01-01",
            temporal_end="2024-13-45",
        )
        assert start == date(2024, 1, 1)
        assert end is None
        assert errors == {"temporal_end": "2024-13-45"}

    def test_both_invalid_both_recorded(self):
        """Both unparseable → both in errors dict, both parsed return None."""
        start, end, errors = _parse_temporal_fields(
            temporal_start="invalid1",
            temporal_end="invalid2",
        )
        assert start is None
        assert end is None
        assert errors == {
            "temporal_start": "invalid1",
            "temporal_end": "invalid2",
        }

    def test_very_long_raw_value_truncated_to_100_chars(self):
        """Long bogus inputs are capped at 100 chars so JSONB doesn't balloon."""
        long_value = "X" * 500

        _, _, errors = _parse_temporal_fields(
            temporal_start=long_value, temporal_end=None
        )
        assert "temporal_start" in errors
        assert len(errors["temporal_start"]) == 100

    def test_non_string_type_recorded_as_error(self):
        """TypeError from passing a non-string also ends up in the errors dict."""
        # The helper annotates ``str | None`` but real ingest_raster pulls
        # values from a JSONB dict which can carry any type. Guard the
        # coercion path even if the type hint suggests it won't happen.
        start, _, errors = _parse_temporal_fields(
            temporal_start=12345,  # type: ignore[arg-type]
            temporal_end=None,
        )
        assert start is None
        assert "temporal_start" in errors
        # Truncated str() representation of the int input
        assert errors["temporal_start"] == "12345"


class TestStripOgrDriverList:
    """SEED-04: driver-list stripping helper — removes GDAL driver enumeration
    from ogr2ogr stderr so IngestionError messages show only actionable lines.
    """

    def test_strips_driver_list_lines_and_keeps_error(self):
        """Core case: contiguous driver-list lines removed; ERROR line preserved."""
        stderr = "blah\n -> 'FITS' (read-only)\n -> 'PCIDSK'\nERROR 1: real error"
        result = _strip_ogr_driver_list(stderr)
        assert "ERROR 1: real error" in result
        assert "-> 'FITS'" not in result
        assert "-> 'PCIDSK'" not in result

    def test_no_driver_list_returns_unchanged(self):
        """When no driver-list lines are present, the string is returned as-is."""
        stderr = "ERROR 1: timeout after 120002ms"
        result = _strip_ogr_driver_list(stderr)
        assert result == "ERROR 1: timeout after 120002ms"

    def test_empty_string_returns_empty(self):
        """Empty input is safe and returns empty string."""
        assert _strip_ogr_driver_list("") == ""

    def test_strips_leading_blank_line_between_driver_list_and_error(self):
        """Blank lines between the driver list and the error line are collapsed."""
        stderr = (
            "  -> 'XYZ' (rw+v)\n"
            "  -> 'OGR_GMT' (rw+v)\n"
            "\n"
            "ERROR 6: Unable to load shared library"
        )
        result = _strip_ogr_driver_list(stderr)
        assert result.startswith("ERROR 6:")
        assert "-> 'XYZ'" not in result
        assert "-> 'OGR_GMT'" not in result

    def test_settings_has_ingest_http_timeout_seconds_default_300(self):
        """Settings field ingest_http_timeout_seconds exists and defaults to 300."""
        from app.core.config import settings

        assert hasattr(settings, "ingest_http_timeout_seconds")
        assert settings.ingest_http_timeout_seconds == 300


class TestSecFu04SanitizeAuthorizationToken:
    """SEC-FU-04 (sec-audit-20260519.md line 535, Phase 1063-03): base64url charset filter
    for the Authorization bearer token before GDAL_HTTP_HEADERS env-var composition.

    A malicious token with CR/LF or arbitrary unicode could smuggle extra HTTP headers
    into libcurl via the env-var pipeline. JWT-shaped tokens use the base64url charset
    (RFC 4648 §5) plus dot separators; restricting to that charset is a tight
    defense-in-depth guard with no legitimate-traffic impact.
    """

    def test_sec_fu_04_happy_path_jwt_token_passes_through_unchanged(self):
        """A JWT-shaped token (base64url segments + dot separators) passes through unchanged."""
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature_value-"
        assert _sanitize_authorization_token(token) == token

    def test_sec_fu_04_crlf_injection_raises_value_error(self):
        """Token with CR/LF raises ValueError naming SEC-FU-04 and the offending character."""
        token = "valid.jwt.sig\r\nX-Smuggled-Header: evil"
        with pytest.raises(ValueError) as exc_info:
            _sanitize_authorization_token(token)
        msg = str(exc_info.value)
        assert "SEC-FU-04" in msg
        # The first offending char is \r — confirm it's named in the message
        assert repr("\r") in msg or "\\r" in msg

    def test_sec_fu_04_whitespace_raises_value_error(self):
        """Token with literal space characters raises ValueError."""
        token = "valid jwt sig"
        with pytest.raises(ValueError) as exc_info:
            _sanitize_authorization_token(token)
        assert "SEC-FU-04" in str(exc_info.value)

    def test_sec_fu_04_unicode_raises_value_error(self):
        """Token with non-ASCII unicode characters raises ValueError."""
        token = "valid.jwt.signaturé"  # U+00E9
        with pytest.raises(ValueError) as exc_info:
            _sanitize_authorization_token(token)
        assert "SEC-FU-04" in str(exc_info.value)

    def test_sec_fu_04_empty_string_raises_value_error(self):
        """Empty string raises ValueError (operator misconfiguration guard)."""
        with pytest.raises(ValueError) as exc_info:
            _sanitize_authorization_token("")
        assert "SEC-FU-04" in str(exc_info.value)

    def test_sec_fu_04_none_returns_none(self):
        """None passes through unchanged (the no-token path from the calling code)."""
        assert _sanitize_authorization_token(None) is None
