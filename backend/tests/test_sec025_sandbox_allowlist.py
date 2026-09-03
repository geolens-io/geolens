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

import contextlib

import pytest

from app.platform.sandbox import validator as _validator
from app.platform.sandbox.schemas import SandboxError
from app.platform.sandbox.validator import _MAX_BUFFER_MATCH_ATTEMPTS, validate_sql


@contextlib.contextmanager
def _recording_validator_logger():
    """Collect the validator's structured rejection events, immune to caching.

    fix(#1024): `structlog.testing.capture_logs()` observes the GLOBAL
    structlog configuration, so what it sees depends on what else ran earlier
    in the same xdist worker rather than on the code under test. Under `-n 4`
    it started yielding `[]` here while the rejection itself still happened,
    which turned main red. The same file passes run alone, and two failing
    runs disagreed on how many of the three broke.

    fix(#1064 codex r3): the trigger IS now pinned down, and this paragraph
    used to say it was not. It is a CONJUNCTION, which is why five separate
    reproduction attempts came back empty — each had one half:

        `cache_logger_on_first_use=True` is in force
        AND a module-level logger EMITS during that window.

    The emit is what matters. Enabling caching alone does nothing; the proxy
    only freezes when it is first used. On that first call a
    `BoundLoggerLazyProxy` binds itself to the chain in force and caches the
    result ON THE PROXY OBJECT, so reapplying a config afterwards cannot undo
    it — that logger is invisible to every later `capture_logs()` in the
    worker. Measured against a module logger: `capture_logs` saw 1 record
    before, 0 after something emitted through it while caching was on.

    `setup_logging()` turns caching on, so anything that calls it and then
    logs seeds this. That is the same symptom documented at
    test_tile_signing.py:648-656.

    The fix below is unchanged and still right. Removing the dependency
    outright — the call sites resolve `logger` from module globals at call
    time, so swapping it is immune regardless — is stronger than avoiding one
    known trigger, and it was the correct call when the trigger was unknown.
    Knowing the mechanism does not make a narrower fix preferable.

    Two consequences worth knowing if you are here debugging something
    similar. A snapshot-and-restore guard CANNOT repair a proxy frozen while
    it was off-guard, because the cache is on the proxy rather than in the
    config; preventing the freeze is the only thing that closes the class
    (#1066). And a helper that calls `setup_logging()` will seed this unless it
    turns caching back off AFTER that call — order matters, since
    `setup_logging()` turns it on. Use `configured_logging()` from
    `tests/_logging_state.py`, which owns both steps; its sibling
    `preserved_logging_state()` only snapshots and restores, so composing that
    one with `setup_logging()` by hand leaves the freeze armed (#1064 codex r4).
    """
    events: list[dict] = []

    class _Recorder:
        def _record(self, event=None, **kwargs):
            events.append({"event": event, **kwargs})

        # `exception` included deliberately: without it __getattr__ below would
        # return a silent no-op, and an assertion would fail with an empty list
        # — the exact confusing symptom this helper exists to remove.
        debug = info = warning = error = critical = exception = _record

        def __getattr__(self, _name):
            # bind() and friends: no-op that supports chaining.
            def _noop(*args, **kwargs):
                return self

            return _noop

    original = _validator.logger
    _validator.logger = _Recorder()
    try:
        yield events
    finally:
        _validator.logger = original


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


def _assert_rejects_function(sql: str, expected_function: str) -> None:
    """Assert validate_sql rejects `sql` and names `expected_function` as the cause.

    Plain `_assert_rejects` cannot tell "the function inside the subquery was
    caught" from "the enclosing predicate was itself refused as an unlisted
    function", which is exactly the confusion #538/#1017 are about. Reading the
    structured log's `function` field pins the reason.
    """
    with _recording_validator_logger() as logs:
        with pytest.raises(SandboxError) as exc_info:
            validate_sql(sql)
    assert exc_info.value.category == "invalid_query"
    rejected = [
        entry.get("function")
        for entry in logs
        if str(entry.get("event") or "").startswith("sandbox.")
        and entry.get("function") is not None
    ]
    assert rejected == [expected_function], (
        f"Expected rejection on {expected_function!r} but the validator "
        f"reported {rejected!r} for SQL: {sql!r}"
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


class TestNiladicKeywordFunctionsRejected:
    """PostgreSQL's parenless identity keywords must be rejected too.

    fix(#1778): the SEC-025 allowlist is driven by one
    ``stmt.find_all(exp.Func)`` walk, and sqlglot 30.17.0 gives only some of
    PostgreSQL's SQLValueFunction keywords a Func subclass. Measured before the
    fix, ``user``, ``current_role`` and ``system_user`` parsed as ``exp.Column``
    and passed validation on both the AI-chat and POST /query/ kwarg sets,
    handing back the effective role name. All seven spellings are pinned here
    so the allowlist's completeness stops depending on a parse shape a sqlglot
    bump could change either way.
    """

    @pytest.mark.parametrize(
        "keyword",
        [
            "user",
            "current_user",
            "current_role",
            "session_user",
            "system_user",
            "current_catalog",
            "current_schema",
        ],
    )
    def test_rejects_bare_keyword(self, keyword):
        _assert_rejects(f"SELECT {keyword} AS c FROM data.cities")

    @pytest.mark.parametrize(
        "keyword",
        ["user", "current_role", "system_user"],
    )
    def test_rejects_bare_keyword_in_where_clause(self, keyword):
        _assert_rejects(f"SELECT name FROM data.cities WHERE name = {keyword}")

    def test_rejects_uppercase_spelling(self):
        _assert_rejects("SELECT USER AS c FROM data.cities")

    def test_rejects_bare_keyword_inside_subquery(self):
        _assert_rejects("SELECT * FROM (SELECT user AS u FROM data.cities) AS sub")

    def test_allows_quoted_identifier(self):
        """``"user"`` is a column reference in PostgreSQL, not the keyword."""
        _assert_allows('SELECT "user" FROM data.cities')

    def test_allows_table_qualified_column(self):
        """``t.user`` is a column reference in PostgreSQL, not the keyword."""
        _assert_allows("SELECT t.user FROM data.cities AS t")


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


class TestExistsSubqueryAllowed:
    """EXISTS is a subquery predicate, not a callable — but sqlglot models
    exp.Exists on the same Func path that trapped AND/OR (#538), so the
    fail-closed walk rejected every EXISTS subquery as function "exists"
    (#1017; fix skips Exists nodes, whose operands are still walked)."""

    def test_allows_exists_subquery(self):
        _assert_allows(
            "SELECT name FROM data.t AS a "
            "WHERE EXISTS (SELECT 1 FROM data.u AS b WHERE b.id = a.id)"
        )

    def test_allows_not_exists_subquery(self):
        _assert_allows(
            "SELECT name FROM data.t AS a "
            "WHERE NOT EXISTS (SELECT 1 FROM data.u AS b WHERE b.id = a.id)"
        )

    def test_allows_exists_with_allowed_functions_inside(self):
        _assert_allows(
            "SELECT c.name FROM data.cities AS c "
            "WHERE EXISTS (SELECT 1 FROM data.parks AS p "
            "WHERE ST_Intersects(p.geom_4326, c.geom_4326) AND LOWER(p.name) = 'x')"
        )

    def test_rejects_blocked_function_inside_exists(self):
        """Skipping the Exists node must NOT hide functions in its subquery."""
        _assert_rejects_function(
            "SELECT name FROM data.t AS a "
            "WHERE EXISTS (SELECT 1 FROM data.u AS b WHERE pg_sleep(1) IS NULL)",
            "pg_sleep",
        )

    def test_rejects_unlisted_function_inside_exists(self):
        _assert_rejects_function(
            "SELECT name FROM data.t AS a "
            "WHERE EXISTS (SELECT version() FROM data.u AS b WHERE b.id = a.id)",
            "current_version",
        )

    def test_rejects_unlisted_spatial_function_inside_exists(self):
        _assert_rejects_function(
            "SELECT name FROM data.t AS a "
            "WHERE EXISTS (SELECT 1 FROM data.u AS b "
            "WHERE ST_MakeEnvelope(0, 0, 1, 1, 4326) IS NOT NULL)",
            "st_makeenvelope",
        )

    def test_rejects_recursive_cte_inside_exists(self):
        """The other tree-wide guards still reach into an EXISTS subquery."""
        _assert_rejects(
            "SELECT name FROM data.t AS a WHERE EXISTS ("
            "WITH RECURSIVE bomb(n) AS ("
            "SELECT 1 UNION ALL SELECT n + 1 FROM bomb WHERE n < 1000000000"
            ") SELECT n FROM bomb)",
            expected_message="Recursive queries are not allowed",
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
        # fix(#1001): ST_GeneratePoints is the attacker-chosen-cardinality
        # generator the allowlist comment cites. Kept alongside ST_MakeEnvelope
        # rather than replacing it: #1001 admits the buffer's machinery only
        # inside the rendered template, so ST_MakeEnvelope on its own is still
        # an unknown spatial function and both belong here.
        _assert_rejects("SELECT ST_GeneratePoints(geom_4326, 100) FROM data.cities")

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

    def test_rejects_table_scanning_unary_st_collect_however_aliased(self):
        """fix(#935 codex r2, restored by #1001): the canonical buffer's unary
        ST_Collect is admitted by whole-template match, not by a per-call
        exception. Hiding a table scan one derived level down — or borrowing
        the renderer's own alias names — must not slip past."""
        _assert_rejects(
            "SELECT (SELECT ST_Collect(_pb_p.p) FROM "
            "(SELECT geom_4326 AS p FROM data.cities) AS _pb_p) AS blob"
        )

    def test_rejects_tiny_or_dynamic_segmentize_length(self):
        """fix(#935 codex r2, restored by #1001): ST_Segmentize's max-edge
        argument controls vertex amplification. Outside the rendered template
        the function is not allowlisted at all, so no argument saves it."""
        _assert_rejects("SELECT ST_Segmentize(geom_4326, 1e-100) FROM data.cities")
        _assert_rejects("SELECT ST_Segmentize(geom_4326, population) FROM data.cities")
        # The lengths the renderer itself uses buy nothing on their own.
        _assert_rejects(
            "SELECT ST_Segmentize(geom_4326::geography, 20000) FROM data.cities LIMIT 5"
        )

    def test_rejects_table_scanning_st_dump(self):
        """fix(#935 codex r3, restored by #1001): ST_Dump over a table is the
        UNNEST row-amplification class."""
        _assert_rejects(
            "SELECT COUNT(*) FROM data.cities c "
            "CROSS JOIN LATERAL ST_Dump(c.geom_4326) d"
        )
        _assert_rejects("SELECT (ST_Dump(geom_4326)).geom FROM data.cities")
        _assert_rejects(
            "SELECT COUNT(*) FROM data.roads r, LATERAL ST_DumpSegments(r.geom_4326) s"
        )


# ---------------------------------------------------------------------------
# fix(#1001): the canonical geodesic buffer
# ---------------------------------------------------------------------------


def _canonical_buffer(geom: str = "s.geom_4326", distance: float = 10000) -> str:
    from app.platform.analysis_sql import render_geodesic_buffer

    return render_geodesic_buffer(geom, distance)


def _unlisted_names_in_canonical_buffer() -> set[str]:
    """Function names the rendered buffer uses that neither allowlist carries.

    Derived from the renderer rather than hard-coded, so a renderer change
    moves this set and the paired negative controls follow it.
    """
    import sqlglot
    from sqlglot import exp

    from app.platform.sandbox.validator import (
        _ALLOWED_FUNCTIONS,
        _ALLOWED_POSTGIS_FUNCTIONS,
        _func_name,
    )

    parsed = sqlglot.parse_one(
        f"SELECT {_canonical_buffer('geom_4326', 1000)} AS g FROM data.t",
        dialect="postgres",
    )
    names: set[str] = set()
    for func in parsed.find_all(exp.Func):
        # Skipped by the walk itself, so not part of the gap this issue closes.
        if isinstance(func, (exp.Connector, exp.Exists)):
            continue
        name = _func_name(func)
        if name.startswith("st_"):
            if name not in _ALLOWED_POSTGIS_FUNCTIONS:
                names.add(name)
        elif name not in _ALLOWED_FUNCTIONS:
            names.add(name)
    return names


class TestCanonicalGeodesicBufferAdmitted:
    """fix(#1001): every metric buffer on the NL->SQL surface is
    render_geodesic_buffer's output, and the fail-closed allowlist refused it —
    every buffer question in the surface was dead. The functions it needs are
    admitted only inside a subtree that re-renders to exactly the same AST,
    never per call.

    fix(#1589): the model no longer types that output. It writes a
    geolens_buffer() marker and processing/ai/buffer_marker.py expands it
    before validation, so what arrives here is unchanged and so is this."""

    def test_admits_the_rendered_buffer(self):
        _assert_allows(
            f"SELECT s.name, ST_AsGeoJSON({_canonical_buffer()}) AS geometry "
            "FROM data.stations s LIMIT 100"
        )

    def test_admits_a_buffer_over_a_subquery_input(self):
        _assert_allows(
            "SELECT p.name FROM data.national_parks p WHERE ST_Intersects("
            "p.geom_4326, "
            + _canonical_buffer(
                "(SELECT geom_4326 FROM data.us_state_capitals WHERE name = 'Denver')",
                50000,
            )
            + ") LIMIT 100"
        )

    @pytest.mark.parametrize("spelling", ["10000", "10000.0", "1e4"])
    def test_admits_every_spelling_of_the_same_distance(self, spelling):
        """The model may write 1e4 where the renderer writes 10000. Numeric
        literals compare by value, so the match does not turn on spelling."""
        rendered = _canonical_buffer()
        _assert_allows(
            f"SELECT ST_AsGeoJSON({rendered.replace('10000', spelling)}) "
            "FROM data.stations s"
        )

    def test_admits_a_subquery_input_whose_column_is_aliased(self):
        """The bounded-source rule looks through the projection alias."""
        _assert_allows(
            "SELECT ST_AsGeoJSON("
            + _canonical_buffer("(SELECT geom_4326 AS g FROM data.cities LIMIT 1)")
            + ") FROM data.stations s"
        )

    def test_the_gap_is_real(self):
        """Guards the guard: if this set ever empties, the tests below stop
        proving anything and the exemption has quietly become unnecessary."""
        assert len(_unlisted_names_in_canonical_buffer()) >= 10

    @pytest.mark.parametrize("name", sorted(_unlisted_names_in_canonical_buffer()))
    def test_each_readmitted_function_is_still_refused_on_its_own(self, name):
        """The paired negative control for every function the buffer readmits.

        Nothing was added to either allowlist, so each of these is still an
        unlisted function the moment it appears outside the rendered template.
        """
        # sqlglot's canonical name for generate_series is not itself valid SQL.
        call = "generate_series" if name == "exploding_generate_series" else name
        _assert_rejects(f"SELECT {call}(geom_4326) FROM data.cities")

    def test_the_scaffold_holds_no_blocked_function(self):
        """A renderer change cannot smuggle a blocked function through the
        exemption — the BLOCKED check runs inside a match too — but a tripwire
        here fails at the renderer instead of at a user's query."""
        import sqlglot
        from sqlglot import exp

        from app.platform.sandbox.validator import _BLOCKED_FUNCTIONS, _func_name

        parsed = sqlglot.parse_one(
            f"SELECT {_canonical_buffer('geom_4326', 1000)} AS g FROM data.t",
            dialect="postgres",
        )
        used = {_func_name(func) for func in parsed.find_all(exp.Func)}
        assert not (used & _BLOCKED_FUNCTIONS)


class TestCanonicalBufferExemptionIsScoped:
    """The exemption covers the rendered scaffold and nothing else."""

    def test_rejects_a_disallowed_function_in_the_buffer_input(self):
        """The input expression is the model's, so it keeps every check."""
        _assert_rejects(
            f"SELECT ST_AsGeoJSON({_canonical_buffer('ST_GeneratePoints(s.geom_4326, 100000)')}) "
            "FROM data.stations s"
        )

    def test_rejects_a_blocked_function_in_the_buffer_input(self):
        _assert_rejects(
            f"SELECT ST_AsGeoJSON({_canonical_buffer('pg_read_file(s.path)')}) "
            "FROM data.stations s"
        )

    def test_rejects_an_unbounded_generator_in_the_buffer_input(self):
        _assert_rejects(
            "SELECT ST_AsGeoJSON("
            + _canonical_buffer("(SELECT i FROM generate_series(1, 1000000000) AS i)")
            + ") FROM data.stations s"
        )

    def test_does_not_exempt_the_rest_of_the_query(self):
        """A canonical buffer in one clause must not license anything in another."""
        _assert_rejects(
            f"SELECT ST_AsGeoJSON({_canonical_buffer()}) AS geometry, "
            "ST_GeneratePoints(s.geom_4326, 100000) AS pts "
            "FROM data.stations s"
        )

    def test_rejects_a_tampered_segmentize_length(self):
        """One scaffold constant changed and the whole subtree fails the match.

        1e-100 is the vertex-amplification payload #1002 chased with a numeric
        floor; here it simply is not the rendered template.
        """
        tampered = _canonical_buffer().replace("20000)::geometry", "1e-100)::geometry")
        assert tampered != _canonical_buffer()
        _assert_rejects(
            f"SELECT ST_AsGeoJSON({tampered}) FROM data.stations s",
        )

    def test_rejects_a_tampered_band_series(self):
        """The banding series is bounded by a longitude span in the template;
        swapping in a literal bound must not survive."""
        rendered = _canonical_buffer()
        tampered = rendered.replace(
            "generate_series(0, GREATEST(", "generate_series(0, 1000000000 + GREATEST("
        )
        assert tampered != rendered
        _assert_rejects(f"SELECT ST_AsGeoJSON({tampered}) FROM data.stations s")

    def test_rejects_a_scaffold_borrowing_the_renderer_aliases(self):
        """The alias-rebinding attack: the template includes the derived-table
        scaffold that binds `_pb`, so a real table bound to those names is not
        the rendered expression."""
        _assert_rejects(
            "SELECT ST_UnaryUnion(ST_Collect(_pb_p.p)) FROM "
            "(SELECT (ST_Dump(c.geom_4326)).geom AS p FROM data.cities c) AS _pb_p"
        )

    def test_rejects_a_truncated_lookalike(self):
        """Just wearing the renderer's input fence is not enough."""
        _assert_rejects(
            "SELECT (SELECT CASE WHEN ST_XMax(_pb.g) - ST_XMin(_pb.g) >= 6 "
            "THEN ST_UnaryUnion(_pb.g) ELSE _pb.g END "
            "FROM (SELECT s.geom_4326 AS g OFFSET 0) AS _pb) FROM data.stations s"
        )

    @pytest.mark.parametrize(
        ("label", "geom"),
        [
            # The reported payload. A PLANAR buffer, so 1000000000 is DEGREES:
            # a two-billion-degree span, hundreds of millions of bands from the
            # scaffold's generate_series, billions of vertices from its
            # ST_Segmentize.
            (
                "planar buffer with a degrees radius",
                "ST_Buffer(ST_SetSRID(ST_MakePoint(0,0),4326), 1000000000)",
            ),
            # The same explosion with no large literal anywhere: a projected
            # geometry hands the scaffold metres.
            ("reprojected input", "ST_Transform(s.geom_4326, 3857)"),
            # A buffer of a buffer. Bounded in fact, since a geography buffer
            # returns 4326, but proving that needs recursion, so it fails
            # closed like anything else that is not a stored geometry.
            ("nested canonical buffer", None),
        ],
    )
    def test_rejects_an_unbounded_buffer_input(self, label, geom):
        """fix(#1001 codex r1): matching the template is not sufficient. The
        scaffold's cost is a function of its INPUT's planar span, so the input
        has to be a stored geometry rather than one the caller manufactured."""
        rendered = (
            _canonical_buffer(_canonical_buffer("s.geom_4326", 1000), 2000)
            if geom is None
            else _canonical_buffer(geom, 1000)
        )
        _assert_rejects(f"SELECT ST_AsGeoJSON({rendered}) FROM data.stations s")

    @pytest.mark.parametrize(
        ("label", "sql_template"),
        [
            # fix(#1001 codex r2): a bare column is not enough on its own. An
            # alias launders the projected geometry back in, and the
            # ST_Transform sits OUTSIDE the exempt subtree so it clears the
            # allowlist on its own.
            (
                "CTE",
                "WITH x AS (SELECT ST_Transform(geom_4326, 3857) AS g "
                "FROM data.cities) SELECT ST_AsGeoJSON({buffer}) FROM x",
            ),
            (
                "derived table",
                "SELECT ST_AsGeoJSON({buffer}) FROM ("
                "SELECT ST_Transform(geom_4326, 3857) AS g FROM data.cities) AS x",
            ),
            (
                "two CTE hops",
                "WITH a AS (SELECT ST_Transform(geom_4326, 3857) AS g "
                "FROM data.cities), b AS (SELECT a.g AS g FROM a) "
                "SELECT ST_AsGeoJSON({buffer2}) FROM b",
            ),
            (
                "scalar subquery",
                "SELECT ST_AsGeoJSON({subquery_buffer}) FROM data.stations s",
            ),
        ],
    )
    def test_rejects_a_laundered_buffer_input(self, label, sql_template):
        _assert_rejects(
            sql_template.format(
                buffer=_canonical_buffer("x.g", 1000),
                buffer2=_canonical_buffer("b.g", 1000),
                subquery_buffer=_canonical_buffer(
                    "(SELECT ST_Transform(geom_4326, 3857) AS g "
                    "FROM data.cities LIMIT 1)",
                    1000,
                ),
            )
        )

    @pytest.mark.parametrize(
        ("label", "sql"),
        [
            (
                "CTE pass-through",
                "WITH x AS (SELECT geom_4326 AS g FROM data.cities) "
                "SELECT ST_AsGeoJSON(" + _canonical_buffer("x.g", 1000) + ") FROM x",
            ),
            (
                "derived-table pass-through",
                "SELECT ST_AsGeoJSON("
                + _canonical_buffer("x.g", 1000)
                + ") FROM (SELECT geom_4326 AS g FROM data.cities) AS x",
            ),
        ],
    )
    def test_admits_an_input_whose_lineage_reaches_a_base_table(self, label, sql):
        """The resolver has to follow a pass-through alias, or a CTE the model
        wrote for readability would be refused for no reason."""
        _assert_allows(sql)

    def test_rejects_an_unqualified_column_with_two_tables_in_scope(self):
        """Which table it came from is undecidable, so it fails closed."""
        _assert_rejects(
            "SELECT ST_AsGeoJSON("
            + _canonical_buffer("geom_4326", 10000)
            + ") FROM data.stations, data.cities"
        )

    def test_rejects_a_bare_top_level_column(self):
        """fix(#1001 codex r4): documented limit. The scaffold interposes its
        own `(SELECT ... OFFSET 0) AS _pb` scope between the column and the
        real FROM, so deciding whether a bare name belongs to `_pb` or to the
        outer table needs the table's column list. The prompt teaches the
        qualified form, and the bare name inside its OWN subquery still
        resolves, because that subquery binds the base table itself."""
        _assert_rejects(
            "SELECT ST_AsGeoJSON("
            + _canonical_buffer("geom_4326", 10000)
            + ") FROM data.stations"
        )

    @pytest.mark.parametrize(
        ("label", "prefix", "source"),
        [
            ("base table", "", "FROM data.cities AS s(gid, name, geom_4326)"),
            (
                "CTE reference",
                "WITH x AS (SELECT geom_4326 FROM data.cities) ",
                "FROM x AS s(geom_4326)",
            ),
        ],
    )
    def test_rejects_a_positional_column_alias_list(self, label, prefix, source):
        """fix(#1001 codex r4): `AS s(gid, name, geom_4326)` binds the NAME
        geom_4326 to whatever the third physical column is, which may be a
        projected geom. Deciding that needs the table's real column order,
        which the validator does not have."""
        _assert_rejects(
            prefix
            + "SELECT ST_AsGeoJSON("
            + _canonical_buffer("s.geom_4326", 1000)
            + f") {source}"
        )

    def test_an_unrelated_nested_alias_does_not_refuse_the_buffer(self):
        """fix(#1001 codex r4): binding resolution is lexical. A nested query
        that happens to reuse an alias must not make the outer binding look
        ambiguous — before this, adding `(SELECT count(*) FROM data.cities s)`
        as a sibling projection refused a buffer that was fine."""
        _assert_allows(
            "SELECT ST_AsGeoJSON("
            + _canonical_buffer("s.geom_4326", 1000)
            + "), (SELECT count(*) FROM data.cities s) AS n FROM data.stations s"
        )

    def test_rejects_an_alias_shadowing_a_safe_cte(self):
        """fix(#1001 codex r3): `FROM bad AS x` binds x to `bad`, whatever a
        CTE literally named x also defines. Resolving through CTE definitions
        instead of through the from/join reference read the safe one."""
        _assert_rejects(
            "WITH x AS (SELECT s.geom_4326 AS g FROM data.safe s), "
            "bad AS (SELECT ST_Transform(c.geom_4326, 3857) AS g "
            "FROM data.cities c) "
            "SELECT ST_AsGeoJSON(" + _canonical_buffer("x.g", 1000) + ") FROM bad AS x"
        )

    def test_admits_a_cte_reference_under_an_alias(self):
        """The paired control: binding through the reference has to keep
        working for the ordinary aliased case."""
        _assert_allows(
            "WITH good AS (SELECT geom_4326 AS g FROM data.cities) "
            "SELECT ST_AsGeoJSON(" + _canonical_buffer("x.g", 1000) + ") FROM good AS x"
        )

    @pytest.mark.parametrize(
        ("label", "sql"),
        [
            (
                "qualified",
                "SELECT ST_AsGeoJSON("
                + _canonical_buffer("s.geom", 1000)
                + ") FROM data.stations s",
            ),
            (
                "unqualified",
                "SELECT ST_AsGeoJSON("
                + _canonical_buffer("geom", 1000)
                + ") FROM data.stations",
            ),
            (
                "through a CTE",
                "WITH x AS (SELECT geom AS g FROM data.cities) "
                "SELECT ST_AsGeoJSON(" + _canonical_buffer("x.g", 1000) + ") FROM x",
            ),
        ],
    )
    def test_rejects_a_base_column_that_is_not_the_managed_4326_column(
        self, label, sql
    ):
        """fix(#1001 codex r3): reaching a base table is not enough. Ingest
        keeps a dataset's ORIGINAL `geom` in whatever CRS it arrived in and
        adds `geom_4326` alongside, so a Web Mercator `s.geom` has a
        40-million-unit span and drives the scaffold exactly like a
        reprojection does."""
        _assert_rejects(sql)

    def test_rejects_an_unresolvable_qualifier(self):
        _assert_rejects(
            "SELECT ST_AsGeoJSON("
            + _canonical_buffer("zz.g", 1000)
            + ") FROM data.stations s"
        )

    def test_follows_a_two_hop_pass_through(self):
        """Sibling CTEs are in scope for each other, so lineage crosses them.

        fix(#1001 codex r4): the earlier resolver stopped at one hop and
        refused this; walking WITH clauses outward from the scope that binds
        the reference is what makes it resolve.
        """
        _assert_allows(
            "WITH a AS (SELECT geom_4326 AS g FROM data.cities), "
            "b AS (SELECT a.g AS g FROM a) "
            "SELECT ST_AsGeoJSON(" + _canonical_buffer("b.g", 1000) + ") FROM b"
        )

    def test_rejects_a_two_hop_laundered_input(self):
        """The same two hops with a reprojection at the far end stay refused."""
        _assert_rejects(
            "WITH a AS (SELECT ST_Transform(geom_4326, 3857) AS g "
            "FROM data.cities), b AS (SELECT a.g AS g FROM a) "
            "SELECT ST_AsGeoJSON(" + _canonical_buffer("b.g", 1000) + ") FROM b"
        )

    def test_refuses_a_lineage_deeper_than_the_hop_cap(self):
        """Stopping is a refusal, not an admission."""
        _assert_rejects(
            "WITH a AS (SELECT geom_4326 AS g FROM data.cities), "
            "b AS (SELECT a.g AS g FROM a), c AS (SELECT b.g AS g FROM b), "
            "d AS (SELECT c.g AS g FROM c), e AS (SELECT d.g AS g FROM d) "
            "SELECT ST_AsGeoJSON(" + _canonical_buffer("e.g", 1000) + ") FROM e"
        )

    def test_rejects_a_wrapped_column_input(self):
        """Even a harmless-looking wrapper is refused: deciding which wrappers
        preserve a bounded span is the units problem #1002 died on."""
        _assert_rejects(
            f"SELECT ST_AsGeoJSON({_canonical_buffer('ST_MakeValid(s.geom_4326)')}) "
            "FROM data.stations s"
        )

    def test_rejects_a_buffer_rendered_under_a_different_alias(self):
        """Only the renderer's default alias can match, which is what the
        prompt emits; anything else fails closed."""
        from app.platform.analysis_sql import render_geodesic_buffer

        odd = render_geodesic_buffer("s.geom_4326", 10000, alias="_zz")
        _assert_rejects(f"SELECT ST_AsGeoJSON({odd}) FROM data.stations s")

    @staticmethod
    def _n_buffers(count: int) -> str:
        # Distinct DISTANCES rather than distinct columns: only the managed
        # geom_4326 column resolves as a bounded source, so varying the column
        # would refuse them all for the wrong reason.
        buffers = ", ".join(
            f"ST_AsGeoJSON({_canonical_buffer('s.geom_4326', 1000 + i)}) AS g{i}"
            for i in range(count)
        )
        return f"SELECT {buffers} FROM data.stations s"

    def test_up_to_the_cap_still_validates(self):
        _assert_allows(self._n_buffers(_MAX_BUFFER_MATCH_ATTEMPTS))

    def test_match_attempts_are_capped(self):
        """Each match re-renders and re-parses ~4 KB of SQL, so a statement
        stuffed with buffer-shaped scaffolds must not turn the validator into
        the DoS. Past the cap nothing more is exempted, which fails closed —
        a query carrying more buffers than the cap is refused, not slow."""
        _assert_rejects(self._n_buffers(_MAX_BUFFER_MATCH_ATTEMPTS + 1))
