"""SQL AST validation and RBAC table allowlist.

Defense layer 1: Parse SQL via sqlglot, validate it is a single SELECT
(including set operations), extract table references, and check them
against the user's RBAC-visible datasets.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import sqlglot
from sqlglot import exp

from app.core.identity import Identity
from app.modules.catalog.authorization import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.platform.sandbox.schemas import SandboxError, ValidatedQuery

logger = structlog.stdlib.get_logger(__name__)

# ---------------------------------------------------------------------------
# Defense-in-depth: always denied regardless of allowlist membership.
#
# These are checked FIRST so that a future accidental addition of one of
# these names to _ALLOWED_FUNCTIONS would still be blocked. The allowlist
# already excludes all of them; this is a belt-and-suspenders guard.
# ---------------------------------------------------------------------------
_BLOCKED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # Filesystem access
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        # Large object operations
        "lo_import",
        "lo_export",
        "lo_create",
        "lo_unlink",
        "lo_open",
        "lo_read",
        "lo_write",
        "lo_close",
        "lo_lseek",
        "lo_tell",
        # External connections
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "dblink_send_query",
        # Server info disclosure (Anonymous nodes)
        "current_setting",
        "set_config",
        "inet_server_addr",
        "inet_server_port",
        "inet_client_addr",
        "inet_client_port",
        # DoS / admin
        "pg_sleep",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_reload_conf",
        # Advisory locks (connection-held resource)
        "pg_advisory_lock",
        "pg_advisory_unlock",
        "pg_try_advisory_lock",
        # Copy
        "copy_to",
        "copy_from",
    }
)

# ---------------------------------------------------------------------------
# Fail-closed allowlist (SEC-025)
#
# Every function name that validate_sql may encounter as a sqlglot sql_name()
# (for named Func subclasses) or Anonymous.name (for pass-through calls) is
# enumerated here. Any other function is rejected as invalid_query.
#
# IMPORTANT: All names are lowercased and match what sqlglot produces:
#
#   • Named Func subclasses use fn.sql_name().lower() — which is the
#     canonical sqlglot identifier (e.g. COUNT → "count",
#     STRING_AGG → "group_concat", BOOL_AND → "logical_and",
#     NOW/CURRENT_TIMESTAMP → "current_timestamp",
#     TO_CHAR → "time_to_str", GENERATE_SERIES → "exploding_generate_series").
#     Always verify with sqlglot.parse(...).find_all(exp.Func) when adding new
#     entries — the sqlglot name may differ from the SQL keyword.
#
#   • Anonymous Func nodes use fn.name.lower() — the raw SQL keyword
#     (e.g. "similarity", "jsonb_agg", "st_area").
#
#   • PostGIS functions use a separate explicit allowlist below.
#
#   • CAST, CASE, COALESCE etc. ARE exp.Func subclasses in sqlglot and DO
#     appear in find_all(exp.Func), so they must be in this set
#     ("cast", "case", "if", "coalesce").
#
# How this list was built:
#   1. AI system prompt (backend/app/processing/ai/sql_generator.py) enumerates
#      the intended function set for LLM queries.
#   2. Every function used in existing passing sandbox/AI tests was harvested.
#   3. Safe function families from the CONTEXT were included generously.
#   4. sqlglot AST was probed to obtain the canonical sql_name() for each.
#
# NEVER add: pg_*, current_setting, version/current_version, current_database,
#            txid_current, inet_*, pg_postmaster_start_time, set_config,
#            or any server-introspection/admin function.
# ---------------------------------------------------------------------------
_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # -- Structural (sqlglot Func subclasses for SQL keywords) -----------
        "cast",  # CAST(x AS type), x::type
        "case",  # CASE WHEN ... THEN ... END
        "if",  # sqlglot maps CASE WHEN single-branch to If
        "coalesce",  # COALESCE(x, default)
        "nullif",  # NULLIF(x, y)
        # -- Aggregates (sqlglot named Func subclasses) ---------------------
        "count",  # COUNT(*), COUNT(col)
        "sum",  # SUM(col)
        "avg",  # AVG(col)
        "min",  # MIN(col)
        "max",  # MAX(col)
        "logical_and",  # BOOL_AND(expr) — sqlglot maps to logical_and
        "logical_or",  # BOOL_OR(expr) — sqlglot maps to logical_or
        "every",  # EVERY(expr) — Anonymous, same semantics as bool_and
        "corr",  # CORR(x, y)
        "covar_pop",  # COVAR_POP(x, y)
        "covar_samp",  # COVAR_SAMP(x, y)
        "regr_slope",  # REGR_SLOPE(y, x)
        "regr_intercept",  # REGR_INTERCEPT(y, x)
        "regr_avgx",  # REGR_AVGX(y, x)
        "regr_avgy",  # REGR_AVGY(y, x)
        "regr_count",  # REGR_COUNT(y, x)
        "regr_r2",  # REGR_R2(y, x)
        "regr_sxx",  # REGR_SXX(y, x)
        "regr_sxy",  # REGR_SXY(y, x)
        "regr_syy",  # REGR_SYY(y, x)
        "percentile_cont",  # PERCENTILE_CONT(f) WITHIN GROUP (ORDER BY col)
        "percentile_disc",  # PERCENTILE_DISC(f) WITHIN GROUP (ORDER BY col)
        "mode",  # MODE() WITHIN GROUP (ORDER BY col)
        "stddev",  # STDDEV(col)
        "stddev_pop",  # STDDEV_POP(col)
        "stddev_samp",  # STDDEV_SAMP(col)
        "variance",  # VARIANCE(col) / VAR_SAMP(col) → both map here
        "variance_pop",  # VAR_POP(col)
        # -- Window functions -----------------------------------------------
        "row_number",  # ROW_NUMBER() OVER (...)
        "rank",  # RANK() OVER (...)
        "dense_rank",  # DENSE_RANK() OVER (...)
        "ntile",  # NTILE(n) OVER (...)
        "lag",  # LAG(col) OVER (...)
        "lead",  # LEAD(col) OVER (...)
        "first_value",  # FIRST_VALUE(col) OVER (...)
        "last_value",  # LAST_VALUE(col) OVER (...)
        # -- Math (sqlglot named Func subclasses) --------------------------
        "abs",
        "ceil",  # CEIL() and CEILING() both → sql_name "ceil"
        "floor",
        "round",
        "trunc",  # TRUNC(x)
        "power",  # POWER(x, n) → sql_name "power" (internal Pow)
        "sqrt",
        "exp",
        "ln",
        "log",
        "sign",
        "greatest",
        "least",
        "width_bucket",
        "pi",
        "degrees",
        "radians",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "cbrt",
        # -- String (sqlglot named Func subclasses) ------------------------
        "lower",
        "upper",
        "length",  # LENGTH, CHAR_LENGTH, CHARACTER_LENGTH → "length"
        "trim",  # TRIM, LTRIM, RTRIM → "trim"
        "btrim",  # BTRIM → Anonymous("btrim")
        "substring",  # SUBSTRING → "substring"; SUBSTR → "substring"
        "split_part",
        "concat",
        "concat_ws",
        "left",
        "right",
        "str_position",  # STRPOS, POSITION → sql_name "str_position"
        "initcap",
        "time_to_str",  # TO_CHAR → sqlglot sql_name "time_to_str"
        "format",
        "replace",
        "regexp_replace",
        "starts_with",
        "md5",
        "reverse",
        "ascii",
        "chr",
        "translate",
        # String fns that remain Anonymous in sqlglot:
        "regexp_match",
        "regexp_split_to_array",
        # -- Date/time (sqlglot named Func subclasses) --------------------
        "current_timestamp",  # NOW(), CURRENT_TIMESTAMP → sql_name "current_timestamp"
        "current_date",  # CURRENT_DATE → sql_name "current_date"
        "current_time",  # CURRENT_TIME → sql_name "current_time"
        "localtime",  # LOCALTIME → sql_name "localtime"
        "localtimestamp",  # LOCALTIMESTAMP → sql_name "localtimestamp"
        "timestamp_trunc",  # DATE_TRUNC → sql_name "timestamp_trunc"
        "extract",  # EXTRACT(...), DATE_PART → sql_name "extract"
        "str_to_date",  # TO_DATE → sql_name "str_to_date"
        "str_to_time",  # TO_TIMESTAMP → sql_name "str_to_time"
        "time_from_parts",  # MAKE_TIME → sql_name "time_from_parts"
        "timestamp_from_parts",  # MAKE_TIMESTAMP → sql_name "timestamp_from_parts"
        "make_interval",
        "justify_days",
        "justify_hours",
        # Date fns that remain Anonymous in sqlglot:
        "age",  # AGE(d1, d2)
        "make_date",  # MAKE_DATE(y, m, d)
        # -- JSON/array (mix of named Func and Anonymous) -----------------
        "json_extract",  # JSON_EXTRACT_PATH → sql_name "json_extract"
        "json_extract_scalar",  # JSON_EXTRACT_PATH_TEXT → sql_name "json_extract_scalar"
        "array_size",  # ARRAY_LENGTH → sql_name "array_size"
        "array_position",
        "array_to_string",
        # JSON/array fns that remain Anonymous in sqlglot:
        "json_build_object",
        "jsonb_build_object",
        "jsonb_extract_path",
        "jsonb_extract_path_text",
        "json_array_length",
        "jsonb_array_length",
        "cardinality",
        # -- pg_trgm (text similarity) ------------------------------------
        "similarity",
        "word_similarity",
        "strict_word_similarity",
        # -- pgvector (vector distance — named Func subclasses) -----------
        "cosine_distance",  # CosineDistance → sql_name "cosine_distance"
        # pgvector fns that remain Anonymous:
        "l2_distance",
        "inner_product",
        "l1_distance",
        "vector_dims",
        "vector_norm",
    }
)

# PostGIS is intentionally fail-closed. The SQL generator prompt is the
# source of truth for the spatial functions it may emit; allowing every st_*
# function admitted generators such as ST_GeneratePoints with attacker-chosen
# cardinality.
_ALLOWED_POSTGIS_FUNCTIONS: frozenset[str] = frozenset(
    {
        "st_area",
        "st_asgeojson",
        "st_buffer",
        "st_centroid",
        "st_collect",
        "st_contains",
        "st_distance",
        "st_dwithin",
        "st_intersects",
        "st_length",
        "st_point",  # sqlglot canonical name for ST_MakePoint
        "st_setsrid",
        "st_transform",
        "st_union",
        "st_within",
        "st_x",
        "st_y",
    }
)


def _validate_function_cost(func: exp.Func, fn_name: str, sql: str) -> None:
    """Reject function arguments that can amplify a one-row query into a DoS."""
    if fn_name in {"st_collect", "st_union"} and len(func.expressions) < 2:
        logger.info("sandbox.unbounded_spatial_aggregate", sql=sql, function=fn_name)
        raise SandboxError(
            "invalid_query", "Query uses an unbounded collection aggregate"
        )

    if fn_name == "st_buffer" and len(func.expressions) > 2:
        logger.info("sandbox.custom_buffer_segments", sql=sql)
        raise SandboxError(
            "invalid_query", "Query uses an unbounded geometry complexity option"
        )


def _reject_recursive_cte(stmt: exp.Expression, sql: str) -> None:
    """Reject recursive CTEs, which are unbounded row generators."""
    if any(
        with_clause.args.get("recursive") for with_clause in stmt.find_all(exp.With)
    ):
        logger.info("sandbox.recursive_cte", sql=sql)
        raise SandboxError("invalid_query", "Recursive queries are not allowed")


def _check_function_allowlist(stmt: exp.Expression, sql: str) -> None:
    """Fail-closed function check (SEC-025).

    For each Func node in the AST, extract its canonical lowercase name:
      • Anonymous nodes  → fn.name.lower()  (the raw SQL identifier)
      • Named Func nodes → fn.sql_name().lower()  (sqlglot's canonical name,
        which may differ from the SQL keyword — see _ALLOWED_FUNCTIONS docs)

    Then apply fail-closed logic (order matters):
      1. BLOCKED  → always reject (defense-in-depth; checked before allowlist)
      2. "st_" name → require the prompt-derived PostGIS allowlist
      3. Other name → require _ALLOWED_FUNCTIONS
      4. Allowed spatial functions → reject unbounded aggregate/complexity forms
      5. Otherwise → reject (fail-closed)
    """
    for func in stmt.find_all(exp.Func):
        # fix(#538): sqlglot models AND/OR (exp.Connector) as Func subclasses,
        # so any compound condition (WHERE x AND y, JOIN ... ON a AND b,
        # CASE WHEN ... AND ...) was rejected as an unlisted "function".
        # Connectors are boolean operators, not callables — and find_all walks
        # their operands regardless, so a disallowed function inside either
        # side of an AND/OR is still caught below.
        if isinstance(func, exp.Connector):
            continue
        if isinstance(func, exp.Anonymous):
            fn_name = func.name.lower() if hasattr(func, "name") else ""
        else:
            fn_name = func.sql_name().lower() if hasattr(func, "sql_name") else ""

        if fn_name in _BLOCKED_FUNCTIONS:
            logger.info("sandbox.blocked_function", sql=sql, function=fn_name)
            raise SandboxError("invalid_query", "Query uses a disallowed function")

        if fn_name.startswith("st_"):
            if fn_name not in _ALLOWED_POSTGIS_FUNCTIONS:
                logger.info(
                    "sandbox.unlisted_postgis_function", sql=sql, function=fn_name
                )
                raise SandboxError(
                    "invalid_query", "Query uses a disallowed spatial function"
                )
        elif fn_name not in _ALLOWED_FUNCTIONS:
            logger.info("sandbox.unlisted_function", sql=sql, function=fn_name)
            raise SandboxError("invalid_query", "Query uses a disallowed function")

        _validate_function_cost(func, fn_name, sql)


def validate_sql(sql: str) -> ValidatedQuery:
    """Parse and validate SQL. Returns validated query or raises SandboxError.

    Accepts: single SELECT, UNION, INTERSECT, EXCEPT.
    Rejects: INSERT, UPDATE, DELETE, DROP, CREATE, multi-statement, SELECT INTO.
    """
    # Parse with postgres dialect
    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.ParseError as exc:
        logger.info("sandbox.parse_error", sql=sql, error=str(exc))
        raise SandboxError("invalid_query", "Invalid SQL syntax")

    # Filter out None entries (sqlglot may return None for empty statements)
    statements = [s for s in statements if s is not None]

    # Must be exactly one statement
    if len(statements) != 1:
        logger.info("sandbox.multi_statement", sql=sql, count=len(statements))
        raise SandboxError("invalid_query", "Only single statements are allowed")

    stmt = statements[0]

    # Must be a SELECT or set operation (UNION/INTERSECT/EXCEPT)
    if not isinstance(stmt, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        logger.info("sandbox.non_select", sql=sql, statement_type=type(stmt).__name__)
        raise SandboxError("invalid_query", "Only SELECT queries are allowed")

    # Reject SELECT INTO (creates a table)
    if stmt.find(exp.Into):
        logger.info("sandbox.select_into", sql=sql)
        raise SandboxError("invalid_query", "Only SELECT queries are allowed")

    _reject_recursive_cte(stmt, sql)

    _check_function_allowlist(stmt, sql)

    # Extract CTE names to exclude from table validation
    cte_names: set[str] = set()
    for cte in stmt.find_all(exp.CTE):
        if cte.alias:
            cte_names.add(cte.alias)

    # Extract all table references as (schema, name) tuples
    tables: set[tuple[str, str]] = set()
    for table in stmt.find_all(exp.Table):
        schema = table.db or ""
        name = table.name
        if name:
            tables.add((schema, name))

    return ValidatedQuery(sql=sql, tables=tables, cte_names=cte_names)


async def build_table_allowlist(db: AsyncSession, user: Identity | None) -> set[str]:
    """Return set of data.* table names visible to the user via RBAC.

    Queries visible datasets using apply_visibility_filter() and returns
    their table_name values (slug names like 'us_state_capitals').
    """
    if user:
        user_roles = await get_user_roles(db, user)
    else:
        user_roles = set()

    stmt = select(Dataset.table_name).join(Record, Dataset.record_id == Record.id)
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    result = await db.execute(stmt)
    return {row[0] for row in result.all()}


def check_table_access(
    referenced_tables: set[tuple[str, str]],
    allowed_tables: set[str],
    cte_names: set[str],
) -> None:
    """Validate all referenced tables are in the RBAC allowlist.

    Args:
        referenced_tables: Set of (schema, name) tuples from AST.
        allowed_tables: Set of table names user can access (no schema prefix).
        cte_names: Set of CTE alias names to skip.

    Raises:
        SandboxError: If any table is not accessible.
    """
    for schema, name in referenced_tables:
        # Skip CTE references (no schema, name matches a CTE)
        if not schema and name in cte_names:
            continue
        # All real tables must be in the data schema
        if schema != "data":
            logger.info(
                "sandbox.wrong_schema",
                schema=schema,
                table=name,
            )
            raise SandboxError("table_not_accessible", "Table not accessible")
        if name not in allowed_tables:
            logger.info(
                "sandbox.table_denied",
                table=name,
            )
            raise SandboxError("table_not_accessible", "Table not accessible")
