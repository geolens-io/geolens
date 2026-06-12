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


def _assert_rejects(sql: str, expected_category: str = "invalid_query") -> None:
    """Assert that validate_sql raises SandboxError for the given SQL."""
    with pytest.raises(SandboxError) as exc_info:
        validate_sql(sql)
    assert exc_info.value.category == expected_category, (
        f"Expected category={expected_category!r} but got "
        f"{exc_info.value.category!r} for SQL: {sql!r}"
    )


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

    def test_allows_st_collect(self):
        _assert_allows("SELECT ST_Collect(geom_4326) FROM data.cities")

    def test_allows_st_union(self):
        _assert_allows("SELECT ST_Union(geom_4326) FROM data.countries GROUP BY region")

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

    def test_allows_array_agg(self):
        _assert_allows("SELECT ARRAY_AGG(name ORDER BY name) FROM data.cities")

    def test_allows_json_agg(self):
        _assert_allows("SELECT JSON_AGG(name) FROM data.cities")

    def test_allows_jsonb_agg(self):
        _assert_allows("SELECT JSONB_AGG(x) FROM data.t")

    def test_allows_unnest(self):
        _assert_allows("SELECT UNNEST(tags) FROM data.t")

    def test_allows_generate_series(self):
        """generate_series is used in existing SAND-03 row-limit tests."""
        _assert_allows("SELECT * FROM generate_series(1, 100) AS t(n)")

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

    def test_allows_aggregate_date_string_combo(self):
        """Aggregate + date_trunc + string function in one query."""
        _assert_allows(
            "SELECT DATE_TRUNC('month', created_at) AS month, "
            "COUNT(*) AS n, "
            "STRING_AGG(DISTINCT category, ', ') AS categories "
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

    def test_allows_string_agg(self):
        _assert_allows(
            "SELECT country, STRING_AGG(name, ', ' ORDER BY name) AS cities "
            "FROM data.cities GROUP BY country"
        )

    def test_allows_md5(self):
        _assert_allows("SELECT MD5(name) FROM data.cities")
