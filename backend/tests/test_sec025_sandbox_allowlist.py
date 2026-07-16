"""SEC-025 regression tests: fail-closed function allowlist for LLM SQL.

These tests verify that the sandbox rejects server-introspection functions
(which were previously allowed under the fail-open denylist) while still
allowing every legitimate function the AI SQL generator can produce.

RED → GREEN history:
  - Pre-fix (denylist only): version(), pg_postmaster_start_time(),
    txid_current(), current_database(), current_setting('x') all PASSED
    validation (not in the ~40-item denylist) — information disclosure risk.
  - Post-fix (allowlist): every function not in _ALLOWED_FUNCTIONS is
    rejected; the tests below reflect the correct post-fix behaviour.
"""

from __future__ import annotations

import pytest

from app.platform.sandbox.schemas import SandboxError
from app.platform.sandbox.validator import validate_sql


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_rejects(
    sql: str,
    expected_category: str = "invalid_query",
    expected_message: str | None = None,
) -> None:
    """Assert that validate_sql raises SandboxError for the given SQL."""
    with pytest.raises(SandboxError) as exc_info:
        validate_sql(sql)
    assert exc_info.value.category == expected_category, (
        f"Expected category={expected_category!r} but got "
        f"{exc_info.value.category!r} for SQL: {sql!r}"
    )
    if expected_message is not None:
        assert exc_info.value.user_message == expected_message


def _assert_allows(sql: str) -> None:
    """Assert that validate_sql does NOT raise for the given SQL."""
    try:
        validate_sql(sql)
    except SandboxError as exc:
        pytest.fail(
            f"validate_sql raised SandboxError({exc.category!r}, "
            f"{exc.user_message!r}) for SQL that should be allowed:\n  {sql}"
        )


# ---------------------------------------------------------------------------
# SEC-025-REJECT: introspection / server-metadata functions must be rejected
# ---------------------------------------------------------------------------


class TestIntrospectionFunctionsRejected:
    """Unlisted server-introspection functions must raise SandboxError.

    These are the acceptance-criteria queries from the SEC-025 plan.
    Pre-fix: all PASSED (not in small denylist). Post-fix: all REJECTED.
    """

    def test_rejects_version(self):
        """version() leaks server PostgreSQL version — must be rejected."""
        _assert_rejects("SELECT version()")

    def test_rejects_pg_postmaster_start_time(self):
        """pg_postmaster_start_time() leaks server uptime — must be rejected."""
        _assert_rejects("SELECT pg_postmaster_start_time()")

    def test_rejects_txid_current(self):
        """txid_current() leaks internal transaction state — must be rejected."""
        _assert_rejects("SELECT txid_current()")

    def test_rejects_current_database(self):
        """current_database() leaks DB name — must be rejected."""
        _assert_rejects("SELECT current_database()")

    def test_rejects_current_setting(self):
        """current_setting() leaks GUC config — must be rejected."""
        _assert_rejects("SELECT current_setting('x')")

    def test_rejects_pg_database_size(self):
        """pg_database_size() leaks storage info — must be rejected."""
        _assert_rejects("SELECT pg_database_size(current_database())")

    def test_rejects_pg_relation_size(self):
        """pg_relation_size() leaks schema internals — must be rejected."""
        _assert_rejects("SELECT pg_relation_size('pg_class')")

    def test_rejects_pg_stat_activity(self):
        # pg_stat_activity is a table not a function, but pg_* functions still blocked
        _assert_rejects("SELECT pg_backend_pid()")

    def test_rejects_pg_get_userbyid(self):
        _assert_rejects("SELECT pg_get_userbyid(1)")

    def test_rejects_has_table_privilege(self):
        _assert_rejects("SELECT has_table_privilege('admin', 'pg_class', 'SELECT')")

    def test_rejects_inet_server_addr(self):
        _assert_rejects("SELECT inet_server_addr()")

    def test_rejects_inet_client_addr(self):
        _assert_rejects("SELECT inet_client_addr()")


# ---------------------------------------------------------------------------
# SEC-025-ALLOW: legitimate AI-generated queries must still pass
# ---------------------------------------------------------------------------


class TestLegitimateQueriesAllowed:
    """Representative queries from the AI SQL generator must remain allowed."""

    # -- Aggregates -----------------------------------------------------------

    def test_allows_count_star(self):
        _assert_allows("SELECT COUNT(*) FROM data.cities")

    def test_allows_sum(self):
        _assert_allows("SELECT SUM(population) FROM data.cities")

    def test_allows_avg(self):
        _assert_allows("SELECT AVG(population) FROM data.cities")

    def test_allows_min_max(self):
        _assert_allows("SELECT MIN(pop), MAX(pop) FROM data.cities")

    def test_allows_count_with_group_by(self):
        _assert_allows(
            "SELECT country_id, COUNT(*) AS city_count "
            "FROM data.cities GROUP BY country_id ORDER BY city_count DESC"
        )

    # -- PostGIS (ST_* prefix) ------------------------------------------------

    def test_allows_st_area(self):
        _assert_allows("SELECT ST_Area(geom_4326) FROM data.parcels")

    def test_allows_st_distance_geography(self):
        _assert_allows(
            "SELECT ST_Distance(a.geom_4326::geography, b.geom_4326::geography) "
            "FROM data.cities a, data.cities b WHERE a.name = 'X'"
        )

    def test_allows_st_intersects(self):
        _assert_allows(
            "SELECT c.name FROM data.countries c "
            "JOIN data.cities ci ON ST_Intersects(c.geom_4326, ci.geom_4326)"
        )

    def test_allows_st_buffer(self):
        _assert_allows(
            "SELECT ST_Buffer(geom_4326::geography, 1000)::geometry FROM data.parks"
        )

    def test_allows_st_dwithin(self):
        _assert_allows(
            "SELECT name FROM data.parks "
            "WHERE ST_DWithin(geom_4326::geography, "
            "ST_SetSRID(ST_MakePoint(-74.006, 40.7128), 4326)::geography, 8046.72)"
        )

    def test_allows_st_makepoint_setsrid(self):
        _assert_allows(
            "SELECT ST_Distance(geom_4326::geography, "
            "ST_SetSRID(ST_MakePoint(-74.0, 40.7), 4326)::geography) / 1609.344 "
            "FROM data.cities"
        )

    def test_allows_st_asgeojson(self):
        _assert_allows("SELECT name, ST_AsGeoJSON(geom_4326) AS geom FROM data.cities")

    def test_allows_binary_st_collect(self):
        _assert_allows("SELECT ST_Collect(first_geom, second_geom) FROM data.cities")

    def test_allows_binary_st_union(self):
        _assert_allows("SELECT ST_Union(first_geom, second_geom) FROM data.countries")

    def test_allows_st_centroid(self):
        _assert_allows("SELECT ST_Centroid(geom_4326) FROM data.polygons")

    def test_allows_st_length(self):
        _assert_allows("SELECT ST_Length(geom_4326::geography) FROM data.roads")

    def test_allows_st_transform(self):
        _assert_allows("SELECT ST_Transform(geom_4326, 3857) FROM data.parcels")

    def test_allows_st_x_y(self):
        _assert_allows("SELECT ST_X(geom_4326), ST_Y(geom_4326) FROM data.pts")

    # -- pg_trgm --------------------------------------------------------------

    def test_allows_similarity(self):
        _assert_allows(
            "SELECT name, similarity(name, 'springfield') AS score "
            "FROM data.cities WHERE similarity(name, 'springfield') > 0.3 "
            "ORDER BY score DESC LIMIT 10"
        )

    def test_allows_word_similarity(self):
        _assert_allows("SELECT word_similarity(name, 'NYC') FROM data.cities")

    def test_allows_strict_word_similarity(self):
        _assert_allows("SELECT strict_word_similarity(name, 'NYC') FROM data.cities")

    # -- Math -----------------------------------------------------------------

    def test_allows_abs_round(self):
        _assert_allows(
            "SELECT ABS(population - 1000000), ROUND(area, 2) FROM data.cities"
        )

    def test_allows_sqrt_power(self):
        _assert_allows("SELECT SQRT(x * x + y * y) FROM data.pts")

    def test_allows_greatest_least(self):
        _assert_allows("SELECT GREATEST(a, b), LEAST(c, d) FROM data.t")

    # -- String ---------------------------------------------------------------

    def test_allows_lower_upper_length(self):
        _assert_allows(
            "SELECT LOWER(name), UPPER(state), LENGTH(description) FROM data.cities"
        )

    def test_allows_substring_replace(self):
        _assert_allows(
            "SELECT SUBSTRING(name FROM 1 FOR 3), REPLACE(code, '-', '') FROM data.t"
        )

    def test_allows_concat(self):
        _assert_allows("SELECT CONCAT(name, ', ', state) FROM data.cities")

    def test_allows_split_part(self):
        _assert_allows("SELECT SPLIT_PART(address, ',', 1) FROM data.t")

    def test_allows_trim_ltrim_rtrim(self):
        _assert_allows("SELECT TRIM(name), LTRIM(name), RTRIM(name) FROM data.t")

    def test_allows_to_char(self):
        _assert_allows("SELECT TO_CHAR(created_at, 'YYYY-MM-DD') FROM data.t")

    def test_allows_regexp_replace(self):
        _assert_allows("SELECT REGEXP_REPLACE(name, '[0-9]', '') FROM data.t")

    def test_allows_initcap(self):
        _assert_allows("SELECT INITCAP(name) FROM data.cities")

    # -- Date/time ------------------------------------------------------------

    def test_allows_date_trunc(self):
        _assert_allows(
            "SELECT DATE_TRUNC('month', created_at) AS month, COUNT(*) "
            "FROM data.incidents GROUP BY 1 ORDER BY 1"
        )

    def test_allows_extract(self):
        _assert_allows("SELECT EXTRACT(YEAR FROM date_col) FROM data.events")

    def test_allows_age(self):
        _assert_allows("SELECT AGE(end_date, start_date) FROM data.projects")

    def test_allows_now(self):
        _assert_allows("SELECT NOW() AS ts")

    def test_allows_to_date(self):
        _assert_allows("SELECT TO_DATE(date_str, 'YYYY-MM-DD') FROM data.t")

    def test_allows_to_timestamp(self):
        _assert_allows(
            "SELECT TO_TIMESTAMP(ts_str, 'YYYY-MM-DD HH24:MI:SS') FROM data.t"
        )

    # -- JSON/array -----------------------------------------------------------

    def test_allows_coalesce(self):
        _assert_allows("SELECT COALESCE(population, 0) FROM data.cities")

    def test_allows_nullif(self):
        _assert_allows("SELECT NULLIF(value, 0) FROM data.t")

    def test_allows_json_build_object(self):
        _assert_allows(
            "SELECT JSON_BUILD_OBJECT('name', name, 'pop', population) FROM data.cities"
        )

    def test_allows_jsonb_build_object(self):
        _assert_allows("SELECT JSONB_BUILD_OBJECT('k', v) FROM data.t")

    def test_allows_cardinality(self):
        _assert_allows("SELECT CARDINALITY(tags) FROM data.t")

    def test_allows_array_to_string(self):
        _assert_allows("SELECT ARRAY_TO_STRING(tags, ', ') FROM data.t")

    def test_allows_array_length(self):
        _assert_allows("SELECT ARRAY_LENGTH(tags, 1) FROM data.t")

    # -- Window functions -----------------------------------------------------

    def test_allows_row_number(self):
        _assert_allows(
            "SELECT name, ROW_NUMBER() OVER (ORDER BY population DESC) AS rank "
            "FROM data.cities"
        )

    def test_allows_rank_dense_rank(self):
        _assert_allows(
            "SELECT name, RANK() OVER (ORDER BY pop DESC), "
            "DENSE_RANK() OVER (ORDER BY pop DESC) FROM data.cities"
        )

    def test_allows_lag_lead(self):
        _assert_allows(
            "SELECT date, value, LAG(value) OVER (ORDER BY date) AS prev, "
            "LEAD(value) OVER (ORDER BY date) AS next FROM data.t"
        )

    def test_allows_first_value_last_value(self):
        _assert_allows(
            "SELECT FIRST_VALUE(name) OVER (ORDER BY pop DESC), "
            "LAST_VALUE(name) OVER (ORDER BY pop ASC) FROM data.cities"
        )

    def test_allows_ntile(self):
        _assert_allows(
            "SELECT name, NTILE(4) OVER (ORDER BY population) AS quartile "
            "FROM data.cities"
        )

    # -- CASE / CAST / structural (not Func nodes per sqlglot, but verify) ----

    def test_allows_case_when(self):
        _assert_allows(
            "SELECT CASE WHEN population > 1000000 THEN 'large' "
            "ELSE 'small' END FROM data.cities"
        )

    def test_allows_cast_integer(self):
        _assert_allows("SELECT CAST(population AS float) FROM data.cities")

    def test_allows_geography_cast(self):
        _assert_allows(
            "SELECT ST_Area(geom_4326::geography) / 4046.8564224 AS acres "
            "FROM data.parcels"
        )

    # -- Complex realistic query (matches AI SQL prompt example) --------------

    def test_allows_full_example_query(self):
        """Reproduces the AI SQL prompt example exactly."""
        _assert_allows(
            "SELECT c.name, c.state, "
            "ST_Distance(c.geom_4326::geography, p.geom_4326::geography) / 1609.344 "
            "AS distance_miles "
            "FROM data.us_state_capitals c, data.airports p "
            "WHERE p.name = 'JFK' "
            "ORDER BY distance_miles LIMIT 10"
        )

    def test_allows_cte_with_aggregate(self):
        _assert_allows(
            "WITH big_cities AS ("
            "  SELECT geom_4326, name, population FROM data.cities "
            "  WHERE population > 500000"
            ") "
            "SELECT COUNT(*) AS cnt FROM big_cities"
        )

    def test_allows_aggregate_date_combo(self):
        """Bounded aggregates remain available with date truncation."""
        _assert_allows(
            "SELECT DATE_TRUNC('month', created_at) AS month, "
            "COUNT(*) AS n, "
            "MIN(category) AS first_category "
            "FROM data.incidents "
            "GROUP BY 1 ORDER BY 1"
        )

    def test_allows_stddev_variance(self):
        _assert_allows(
            "SELECT STDDEV(population), VARIANCE(population) FROM data.cities"
        )

    def test_allows_percentile_cont(self):
        _assert_allows(
            "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY population) "
            "AS median_pop FROM data.cities"
        )

    def test_allows_bool_and_bool_or(self):
        _assert_allows(
            "SELECT BOOL_AND(is_active), BOOL_OR(has_permit) FROM data.parcels"
        )

    def test_allows_md5(self):
        _assert_allows("SELECT MD5(name) FROM data.cities")


class TestBooleanOperatorsAllowed:
    """AND/OR are boolean operators, not callables — sqlglot models them as
    exp.Connector (a Func subclass), so the fail-closed walk rejected every
    compound condition as an unlisted "function" (found by the live NL→SQL
    evals; fix skips Connector nodes, whose operands are still walked)."""

    def test_allows_where_and(self):
        _assert_allows("SELECT name FROM data.cities WHERE pop > 1 AND area < 2")

    def test_allows_where_or(self):
        _assert_allows("SELECT name FROM data.cities WHERE pop > 1 OR area < 2")

    def test_allows_join_on_compound_condition(self):
        _assert_allows(
            "SELECT 1 FROM data.cities a JOIN data.cities b "
            "ON a.name = 'x' AND b.name = 'y'"
        )

    def test_allows_case_when_and(self):
        _assert_allows(
            "SELECT CASE WHEN pop > 1 AND area < 2 THEN 'y' ELSE 'n' END "
            "FROM data.cities"
        )

    def test_allows_having_and(self):
        _assert_allows(
            "SELECT name, COUNT(*) FROM data.cities "
            "GROUP BY name HAVING COUNT(*) > 1 AND name != 'x'"
        )

    def test_rejects_blocked_function_inside_and(self):
        """Skipping the Connector node must NOT hide functions in its operands."""
        _assert_rejects(
            "SELECT name FROM data.cities WHERE pg_sleep(1) IS NULL AND pop > 1"
        )

    def test_rejects_unlisted_function_inside_or(self):
        _assert_rejects(
            "SELECT name FROM data.cities WHERE dblink('a','b') IS NULL OR pop > 1"
        )

    def test_rejects_unlisted_spatial_function_inside_and(self):
        _assert_rejects(
            "SELECT name FROM data.cities WHERE ST_EvilThing(geom_4326) AND pop > 1"
        )


class TestResourceAmplificationRejected:
    """One-row SELECTs must not create attacker-sized intermediate values."""

    def test_rejects_unlisted_postgis_generator(self):
        _assert_rejects(
            "SELECT ST_GeneratePoints("
            "ST_SetSRID(ST_Buffer(ST_MakePoint(0, 0), 1), 4326), "
            "1000000000)"
        )

    def test_rejects_unknown_postgis_function(self):
        _assert_rejects("SELECT ST_MakeEnvelope(0, 0, 1, 1, 4326)")

    def test_rejects_oversized_generate_series(self):
        _assert_rejects("SELECT array_agg(i) FROM generate_series(1, 1000000000) AS i")

    def test_rejects_dynamic_generate_series_bounds(self):
        _assert_rejects(
            "SELECT * FROM data.cities c "
            "CROSS JOIN generate_series(1, c.population) AS i"
        )

    def test_rejects_oversized_repeat(self):
        _assert_rejects("SELECT REPEAT('x', 1000000000)")

    def test_rejects_dynamic_repeat_count(self):
        _assert_rejects("SELECT REPEAT(name, population) FROM data.cities")

    def test_rejects_even_individually_bounded_generator_composition(self):
        _assert_rejects(
            "SELECT count(*) FROM generate_series(1, 10000) a, "
            "generate_series(1, 10000) b"
        )

    def test_rejects_nested_string_amplification(self):
        _assert_rejects("SELECT REPEAT(REPEAT('x', 10000), 10000)")

    def test_rejects_custom_buffer_complexity(self):
        _assert_rejects(
            "SELECT ST_Buffer(geom_4326, 1, 'quad_segs=1000000000') FROM data.cities"
        )

    def test_rejects_recursive_cte_generator(self):
        _assert_rejects(
            "WITH RECURSIVE bomb(n) AS ("
            "SELECT 1 UNION ALL SELECT n + 1 FROM bomb WHERE n < 1000000000"
            ") SELECT count(*) FROM bomb, data.cities"
        )

    def test_rejects_nested_recursive_cte_after_non_recursive_outer_cte(self):
        _assert_rejects(
            "WITH harmless AS (SELECT 1 AS marker) "
            "SELECT count(*) FROM data.cities CROSS JOIN LATERAL ("
            "WITH RECURSIVE bomb(n) AS ("
            "SELECT 1 UNION ALL SELECT n + 1 FROM bomb WHERE n < 1000000000"
            ") SELECT n FROM bomb"
            ") AS nested",
            expected_message="Recursive queries are not allowed",
        )

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT ARRAY_AGG(name) FROM data.cities",
            "SELECT STRING_AGG(name, ',') FROM data.cities",
            "SELECT JSON_AGG(name) FROM data.cities",
            "SELECT JSONB_AGG(name) FROM data.cities",
            "SELECT ST_Collect(geom_4326) FROM data.cities",
            "SELECT ST_Union(geom_4326) FROM data.cities",
            "SELECT UNNEST(tags) FROM data.cities",
            "SELECT JSONB_OBJECT_KEYS(properties) FROM data.cities",
        ],
    )
    def test_rejects_unbounded_collection_builders(self, sql):
        _assert_rejects(sql)
