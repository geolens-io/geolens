"""SQL AST validation and RBAC table allowlist.

Defense layer 1: Parse SQL via sqlglot, validate it is a single SELECT
(including set operations), extract table references, and check them
against the user's RBAC-visible datasets.

Two kinds of check live here, and they are NOT the same trust class.

Hard boundaries (must be correct): single-SELECT enforcement, the blocked
function/operator list, the OID/regclass rejection, and — above all — RBAC
table-access (``check_table_access`` against the allowlist). A miss here
lets a query reach data or side effects it must not. These are security
boundaries and are tested as such.

The fan-out / output-width COST MODEL (``_max_table_fanout``, the projection
width cap, the cross-product degree) is explicitly best-effort pre-filtering,
NOT a security boundary. Its only job is to turn an obviously-expensive query
into a fast 422 instead of letting it burn its execution budget. It runs on a
static AST with no catalog statistics, so it cannot be complete: some
cost-multiplying constructs (a same-side ``ON a.x = a.x``, a value laundered
through a cast or CASE, a set-returning function) will be under-counted, and
that is acceptable BY DESIGN because every executed query is already bounded
at runtime (see ``validate_and_execute`` / ``execute_safe``):

  * one in-flight query per user — ``pg_try_advisory_xact_lock`` on the caller
    identity, so a user cannot stack concurrent queries;
  * a global concurrency ceiling — the capacity semaphore (pool//3), so N
    distinct users cannot exhaust the pool or memory in parallel;
  * a hard ``SET LOCAL statement_timeout`` — runaway work is killed, not
    awaited;
  * a READ ONLY transaction on a restricted, fail-closed reader role — no
    writes, no reach beyond granted data;
  * an outer row-limit and a post-fetch serialized-byte cap — the returned
    result is clamped regardless of how the query tried to inflate it;
  * an isolated request-session release so an in-flight query holds one pool
    slot, not two.

So the worst case of ANY cost-model under-count is: one query, for one user,
on the reader role, killed at the timeout, with its output clamped by the row
and byte caps. That is the designed floor. New cost-model bypasses that stay
within this floor are therefore documented and left as-is rather than chased
construct-by-construct (an unbounded enumeration); only a finding that shows a
RUNTIME bound above is missing or bypassable is a real defect to fix here.
"""

from __future__ import annotations

import re

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

# PostgreSQL OID / OID-alias types. The ``reg*`` family resolves an integer OID
# to a catalog NAME (role, relation, namespace, function, type…); ``oid`` and
# the other system column types have no legitimate use in a read-only analytics
# query over ``data.*`` tables and are the building blocks of ``::oid::regrole``
# chains, so the whole family is rejected (fix(#565 codex P1 r11/r12)).
_OID_ALIAS_TYPES: frozenset[str] = frozenset(
    {
        "oid",
        "regrole",
        "regclass",
        "regnamespace",
        "regproc",
        "regprocedure",
        "regoper",
        "regoperator",
        "regtype",
        "regconfig",
        "regdictionary",
        "regcollation",
        "xid",
        "xid8",
        "cid",
        "tid",
    }
)

_IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

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
# fix(#1778): PostgreSQL's identity/introspection niladic functions have a
# parenless keyword spelling, and sqlglot only gives SOME of them a Func
# subclass. Measured on sqlglot 30.17.0 with `SELECT <kw> FROM data.cities`:
# current_user/session_user/current_catalog/current_schema parse as Func nodes
# and hit _BLOCKED_FUNCTIONS via the allowlist walk, but `user`,
# `current_role` and `system_user` parse as exp.Column and never reach it.
# The allowlist's completeness must not depend on that parse shape, so these
# names are also rejected as unqualified, unquoted column references.
#
# PostgreSQL resolves the bare keyword to the SQLValueFunction even when a
# table in scope has a column of the same name, so rejecting the bare spelling
# never blocks a legitimate column read: `t.user` and `"user"` still parse as
# ordinary columns and are left alone, exactly as PostgreSQL reads them.
_BLOCKED_NILADIC_KEYWORDS: frozenset[str] = frozenset(
    {
        "user",
        "current_user",
        "current_role",
        "session_user",
        "system_user",
        "current_catalog",
        "current_schema",
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


def _func_name(func: exp.Func) -> str:
    """Canonical lowercase name of a function node.

    Anonymous nodes carry the raw SQL identifier; named Func subclasses carry
    sqlglot's own name, which may differ from the SQL keyword (see the
    _ALLOWED_FUNCTIONS docs).
    """
    if isinstance(func, exp.Anonymous):
        return func.name.lower() if hasattr(func, "name") else ""
    return func.sql_name().lower() if hasattr(func, "sql_name") else ""


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


# ---------------------------------------------------------------------------
# fix(#1001): the canonical geodesic buffer, recognized whole.
#
# Every metric buffer on the NL->SQL surface is render_geodesic_buffer's
# output — fix(#1589): expanded from a geolens_buffer() marker by
# processing/ai/buffer_marker.py before validation, where the prompt used to
# embed the text — and it needs sixteen function names the fail-closed
# allowlist does not carry. So every buffer question there was refused.
#
# Admitting those names globally is not an option: st_dump, st_dumpsegments,
# st_segmentize and generate_series are the row/vertex amplification classes
# SEC-025 exists to keep out. #994 tried admitting them and bounding them with
# per-call cost guards, and #1002 tried three rounds of recalibrating those
# guards; each drew a real P1. The last one settles it — the buffer segmentizes
# an alias, `_pb_d0.c0`, several derived levels from its input, so proving a
# call's argument is safe and admitting the canonical buffer are contradictory
# under any argument-inspection scheme. That is data-flow analysis, not a
# predicate to tighten.
#
# So nothing is admitted per call. A subtree is exempted only when it is
# EXACTLY what render_geodesic_buffer emits around its own input:
#
#   1. extract loosely — the input expression from the renderer's `AS g
#      OFFSET 0` fence, the distance from its ST_Buffer call;
#   2. verify exactly — re-render the template around that same input and
#      require the two ASTs to be equal.
#
# Extraction may be wrong; verification cannot be, because a mismatch simply
# fails closed. The scaffold's own literals (segmentize lengths, band widths,
# ST_WrapX bounds) come from the reference render, so they cannot be chosen by
# the caller, and the alias-rebinding attack (`FROM data.cities AS _pb_c(c)`)
# cannot match because the template includes the derived-table scaffold that
# binds those aliases.
#
# The input expression itself is NOT exempt. It is the model's, so its
# functions, its cost guards and its tables are all validated normally.
#
# Both sides render through the same render_geodesic_buffer, so a renderer
# change re-admits its own new shape and nothing else. That is the coupling
# this whole incident was about, and it now runs in one direction only —
# analysis_sql carries a pointer back here.
# ---------------------------------------------------------------------------

# render_geodesic_buffer's default alias. A buffer rendered under any other
# alias fails the match and stays refused; the prompt only renders the default.
_BUFFER_INPUT_ALIAS = "_pb"

# Bound on how many subtrees may be re-rendered per statement. Each attempt
# renders ~4 KB of SQL and parses it — measured at ~16 ms — so an adversarial
# statement full of buffer-shaped scaffolds must not turn the validator itself
# into the DoS. Eight covers a query buffering several layers, and nested
# buffers well past anything the prompt teaches. Past the cap no further
# exemption is granted, which fails closed.
_MAX_BUFFER_MATCH_ATTEMPTS = 8


def _numeric_normalized_sql(node: exp.Expression) -> str:
    """Render `node`, with every numeric literal reduced to its float value.

    `50000`, `50000.0` and `5e4` are the same buffer distance, and the model
    may write any of them where the reference render writes one. Comparing
    numeric literals by VALUE keeps the match from turning on spelling, while
    every scaffold constant still has to agree exactly.
    """
    copy = node.copy()
    for literal in copy.find_all(exp.Literal):
        if not literal.is_number:
            continue
        try:
            literal.set("this", repr(float(literal.this)))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            pass
    return copy.sql(dialect="postgres")


def _buffer_shaped_root(node: exp.Expression) -> exp.Subquery | None:
    """Cheap O(1) test for the renderer's outermost shape.

    Only a node that passes this is worth extracting from, which keeps the
    scan off every subquery in the statement.
    """
    if not isinstance(node, exp.Subquery) or node.alias:
        return None
    inner = node.this
    if not isinstance(inner, exp.Select) or len(inner.expressions) != 1:
        return None
    if not isinstance(inner.expressions[0], exp.Case):
        return None
    # Direct children only, never find(): a nested FROM deeper in the tree must
    # not stand in for this SELECT's own. The arg KEY for it has moved between
    # sqlglot releases ("from" -> "from_"), so iterate rather than index.
    source = next(
        (child for child in inner.iter_expressions() if isinstance(child, exp.From)),
        None,
    )
    fenced = source.this if source is not None else None
    if not isinstance(fenced, exp.Subquery) or fenced.alias != _BUFFER_INPUT_ALIAS:
        return None
    return fenced


def _extract_buffer_input(node: exp.Expression) -> tuple[exp.Expression, float] | None:
    """Pull the input expression and the distance out of a buffer-shaped node.

    Deliberately loose. Anything it gets wrong is caught by the exact
    re-render in `_matches_canonical_buffer`.
    """
    fenced = _buffer_shaped_root(node)
    if fenced is None:
        return None
    fenced_select = fenced.this
    if not isinstance(fenced_select, exp.Select) or len(fenced_select.expressions) != 1:
        return None
    projection = fenced_select.expressions[0]
    if not isinstance(projection, exp.Alias) or projection.alias != "g":
        return None

    for func in node.find_all(exp.Func):
        if _func_name(func) != "st_buffer":
            continue
        args = func.expressions or list(func.args.values())
        if len(args) < 2:
            continue
        distance = args[1]
        if not isinstance(distance, exp.Literal) or not distance.is_number:
            continue
        try:
            return projection.this, float(distance.this)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return None
    return None


# How many alias hops a buffer input's lineage may take before it is refused.
# The prompt teaches zero or one; anything deeper is not a shape worth
# resolving, and stopping is a refusal, not an admission.
_MAX_LINEAGE_HOPS = 4


# The managed 4326 geometry column. Ingest keeps a source dataset's ORIGINAL
# `geom` in whatever CRS it arrived in and adds this one alongside
# (`processing/ingest/service.py` probes for both), so "reached a base table"
# is not the same as "reached a bounded geometry": a Web Mercator `s.geom` has
# a 40-million-unit span and drives the scaffold's six-unit bands and 0.1-unit
# segmentization exactly like a reprojection does (fix(#1001 codex r3)).
_MANAGED_GEOMETRY_COLUMN = "geom_4326"


def _own_sources(select: exp.Select) -> list[exp.Expression]:
    """The from/join sources this SELECT itself binds.

    Direct children only. `find_all` here would cross into every nested
    scope, and the buffer scaffold is itself a stack of aliased derived
    tables, so a subtree walk never sees a single source (fix(#1001 codex
    r4)).
    """
    return [
        child.this
        for child in select.iter_expressions()
        if isinstance(child, (exp.From, exp.Join))
    ]


def _binding_name(source: exp.Expression) -> str:
    """The name a from/join source is bound to in its scope."""
    if isinstance(source, exp.Table):
        return source.alias or source.name
    if isinstance(source, exp.Subquery):
        return source.alias
    return ""


def _cte_definition(select: exp.Select, name: str) -> exp.Expression | None:
    """Resolve a CTE `name` against the WITH clauses in scope.

    Walks outward, because a CTE declared on an enclosing SELECT is visible to
    every SELECT beneath it. Returns None when the name is unknown or declared
    more than once, so the caller fails closed.
    """
    node: exp.Expression | None = select
    while node is not None:
        if isinstance(node, exp.Select):
            with_clause = next(
                (
                    child
                    for child in node.iter_expressions()
                    if isinstance(child, exp.With)
                ),
                None,
            )
            if with_clause is not None:
                matches = [
                    cte.this for cte in with_clause.expressions if cte.alias == name
                ]
                if len(matches) == 1:
                    return matches[0]
                if matches:
                    return None
        node = node.parent
    return None


def _resolve_binding(
    select: exp.Select, name: str
) -> tuple[exp.Expression, exp.Select] | None:
    """Find what `name` is bound to, searching outward from `select`.

    Lexical scoping, not a whole-statement search. An unrelated nested query
    that happens to reuse an alias must not make an outer binding look
    ambiguous (fix(#1001 codex r4)); walking outward is also what resolves the
    correlated reference the buffer's own input fence relies on, since
    `(SELECT s.geom_4326 AS g OFFSET 0) AS _pb` has no FROM of its own.

    Returns the bound source and the scope that bound it, or None when the
    name is unknown or bound more than once in one scope.
    """
    node: exp.Expression | None = select
    while node is not None:
        if isinstance(node, exp.Select):
            matches = [src for src in _own_sources(node) if _binding_name(src) == name]
            if len(matches) > 1:
                return None
            if matches:
                return matches[0], node
        node = node.parent
    return None


def _sole_base_table(select: exp.Select) -> exp.Table | None:
    """The one base table the nearest binding scope declares.

    Walks outward past scopes that bind nothing and stops at the first that
    binds anything, which is how PostgreSQL resolves an unqualified name.

    Known limit, and a deliberate one. A bare `geom_4326` handed to the buffer
    at the top level is REFUSED, because the scaffold interposes its own
    `(SELECT ... OFFSET 0) AS _pb` scope between the column and the real FROM,
    and deciding whether the name belongs to `_pb` or to the outer table needs
    the table's column list. The prompt teaches the qualified form
    (`s.geom_4326`) for exactly this reason, and the same bare name INSIDE its
    own subquery — the prompt's other worked shape — resolves normally,
    because that subquery binds the base table itself.
    """
    node: exp.Expression | None = select
    while node is not None:
        if isinstance(node, exp.Select):
            sources = _own_sources(node)
            if sources:
                if len(sources) != 1:
                    return None
                source = sources[0]
                return source if isinstance(source, exp.Table) and source.db else None
        node = node.parent
    return None


def _declares_column_aliases(source: exp.Expression) -> bool:
    """Whether a source renames its columns positionally.

    fix(#1001 codex r4): `FROM data.cities AS s(gid, name, geom_4326)` binds
    the name `geom_4326` to whatever the THIRD physical column happens to be,
    which may well be a projected `geom`. Deciding that needs the table's real
    column order, which the validator does not have, so a positional alias
    list fails closed.
    """
    alias = source.args.get("alias")
    return bool(alias is not None and getattr(alias, "columns", None))


def _terminal_column_is_bounded(source: exp.Table, name: str) -> bool:
    """Whether `name` on base table `source` is the managed 4326 column."""
    if _declares_column_aliases(source):
        return False
    return name == _MANAGED_GEOMETRY_COLUMN


def _derived_select(source: exp.Expression, owner: exp.Select) -> exp.Select | None:
    """The SELECT behind a non-base-table source, or None when undecidable."""
    if _declares_column_aliases(source):
        return None
    if isinstance(source, exp.Table):
        # Schema-less: a reference to a CTE, resolved by the CTE's OWN name
        # rather than by the binding name — `FROM bad AS x` binds x to bad
        # (fix(#1001 codex r3)).
        definition = _cte_definition(owner, source.name)
        return definition if isinstance(definition, exp.Select) else None
    if isinstance(source, exp.Subquery) and isinstance(source.this, exp.Select):
        return source.this
    return None


def _projected_column(select: exp.Select, name: str) -> exp.Column | None:
    """The column `select` projects as `name`, or None when it is not one."""
    projection = next(
        (
            expr
            for expr in select.expressions
            if (expr.alias if isinstance(expr, exp.Alias) else expr.name) == name
        ),
        None,
    )
    if isinstance(projection, exp.Alias):
        projection = projection.this
    return projection if isinstance(projection, exp.Column) else None


def _resolves_to_stored_column(scope: exp.Expression, column: exp.Column) -> bool:
    """Whether `column` traces back to the managed geometry column of a table.

    Fails closed on everything it cannot decide: an unknown qualifier, a name
    bound more than once in one scope, a positional column-alias list, a
    projection that is an expression rather than a column, or a lineage deeper
    than `_MAX_LINEAGE_HOPS`.
    """
    select = column.find_ancestor(exp.Select)
    if select is None:
        select = scope if isinstance(scope, exp.Select) else None
    if select is None:
        return False

    for _ in range(_MAX_LINEAGE_HOPS):
        qualifier, name = column.table, column.name
        if not qualifier:
            # Unqualified: only safe when the nearest binding scope declares
            # exactly one base table, so there is nothing else it could be.
            table = _sole_base_table(select)
            return table is not None and _terminal_column_is_bounded(table, name)

        bound = _resolve_binding(select, qualifier)
        if bound is None:
            return False
        source, owner = bound

        if isinstance(source, exp.Table) and source.db:
            return _terminal_column_is_bounded(source, name)

        inner = _derived_select(source, owner)
        if inner is None:
            return False
        projection = _projected_column(inner, name)
        if projection is None:
            return False
        column, select = projection, inner
    return False


def _is_bounded_geometry_source(stmt: exp.Expression, node: exp.Expression) -> bool:
    """Whether `node` can only be a stored geometry, never a manufactured one.

    fix(#1001 codex r1): the rendered scaffold assumes its input is a 4326
    geometry, so its planar span is at most 360 degrees. It slices that span
    into ~6-degree bands with `generate_series` and densifies it with
    `ST_Segmentize`, both of which scale with the span. A stored `geom_4326`
    column satisfies the assumption by construction. An arbitrary expression
    does not, and two shapes reach past it without tripping any existing
    guard:

      ST_Buffer(ST_SetSRID(ST_MakePoint(0,0),4326), 1000000000)
          a PLANAR buffer, so the radius is DEGREES — a two-billion-degree
          span, hundreds of millions of bands, billions of vertices;
      ST_Transform(geom_4326, 3857)
          hands the scaffold metres with no large literal at all, so a
          40-million-unit span segmentized at 0.1 is the same explosion.

    Deciding this by inspecting the expression's functions is the units
    problem #1002 died on, so the rule is structural instead: a bare column
    reference, or a scalar subquery projecting one. Both shapes the prompt
    teaches qualify — the `<GEOM>` template is substituted with a column, and
    the worked example is `(SELECT geom_4326 FROM data.us_state_capitals
    WHERE name = 'Denver')`. Everything else is refused, which is the right
    failure direction: a refused buffer question beats an unbounded one.

    fix(#1001 codex r2): a bare column is not enough on its own, because an
    alias launders the expression back in —

        WITH x AS (SELECT ST_Transform(geom_4326, 3857) AS g FROM data.cities)
        SELECT <buffer of x.g> FROM x

    puts a projected geometry behind a name that satisfies the column test,
    while the `ST_Transform` sits OUTSIDE the exempt subtree and so passes the
    allowlist on its own. So the column's lineage is resolved through CTE and
    derived-table projections until it reaches a base table, and anything that
    cannot be resolved that way is refused.

    The subquery's other clauses are not exempted by this; they stay under the
    ordinary function allowlist and table checks like any other subquery.
    """
    if isinstance(node, exp.Column):
        return _resolves_to_stored_column(stmt, node)
    if isinstance(node, exp.Subquery):
        inner = node.this
        if isinstance(inner, exp.Select) and len(inner.expressions) == 1:
            projection = inner.expressions[0]
            if isinstance(projection, exp.Alias):
                projection = projection.this
            if not isinstance(projection, exp.Column):
                return False
            # Resolve within the subquery: its own FROM is what binds the
            # projection, and only falls back to the outer statement for a
            # correlated reference.
            return _resolves_to_stored_column(
                inner, projection
            ) or _resolves_to_stored_column(stmt, projection)
    return False


def _matches_canonical_buffer(node: exp.Expression) -> exp.Expression | None:
    """Return the buffer's input expression when `node` is the canonical buffer.

    Returns None otherwise, including on any renderer or sqlglot failure, so
    drift refuses the buffer rather than admitting an unverified subtree.
    """
    extracted = _extract_buffer_input(node)
    if extracted is None:
        return None
    geom, distance = extracted

    # Function-level import: keeps the sandbox importable without pulling the
    # analysis renderer into contexts that never validate SQL.
    from app.platform.analysis_sql import render_geodesic_buffer

    # A renderer or sqlglot drift returns None below, which grants no
    # exemption and so refuses the buffer — the failure direction that matters.
    try:
        rendered = render_geodesic_buffer(geom.sql(dialect="postgres"), distance)
        expected = sqlglot.parse_one(rendered, dialect="postgres")
    except Exception:  # broad: drift must fail CLOSED, never crash validation
        return None
    if expected is None:
        return None
    if _numeric_normalized_sql(expected) != _numeric_normalized_sql(node):
        return None
    return geom


def _canonical_buffer_exempt_ids(stmt: exp.Expression) -> set[int]:
    """Ids of the AST nodes that sit inside a verified canonical buffer.

    Ids are safe as keys here because every node counted is reachable from
    `stmt`, so it stays alive — and therefore uniquely addressed — for the
    whole validation.
    """
    exempt: set[int] = set()
    attempts = 0
    for node in stmt.find_all(exp.Subquery):
        if _buffer_shaped_root(node) is None:
            continue
        if attempts >= _MAX_BUFFER_MATCH_ATTEMPTS:
            break
        attempts += 1
        geom = _matches_canonical_buffer(node)
        if geom is None:
            continue
        # Matching the template is not sufficient on its own: the scaffold's
        # cost is a function of its INPUT's planar span, so the input has to
        # be a stored geometry rather than one the caller manufactured.
        if not _is_bounded_geometry_source(stmt, geom):
            continue
        # The input expression is the model's, so it keeps every check. Only
        # the scaffold the renderer produced around it is exempt.
        caller_supplied = {id(inner) for inner in geom.walk()}
        for inner in node.walk():
            if id(inner) not in caller_supplied:
                exempt.add(id(inner))
    return exempt


# Statement types that write. `validate_sql` isinstance-checks only the ROOT
# node, so before #1011 any of these nested inside a CTE or a scalar subquery
# passed validation — `WITH x AS (INSERT ... RETURNING a) SELECT a FROM x` was
# accepted, and only `SET TRANSACTION READ ONLY` in `execute_safe` stopped it
# from running. Listed explicitly rather than by sqlglot base class: `exp.DDL`
# and `exp.DML` do not partition the way the names suggest (Insert is both,
# Drop and Alter are neither), so an explicit tuple is what stays fail-closed
# across sqlglot upgrades.
_MUTATING_STATEMENTS: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Copy,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,  # sqlglot's catch-all for statements it does not model
)


def _reject_nested_mutation(stmt: exp.Expression, sql: str) -> None:
    """Reject write statements found anywhere in the tree, not just at the root."""
    node = stmt.find(*_MUTATING_STATEMENTS)
    if node is not None:
        logger.info(
            "sandbox.nested_mutation", sql=sql, statement_type=type(node).__name__
        )
        raise SandboxError("invalid_query", "Only SELECT queries are allowed")


def _is_wildcard_projection(proj: exp.Expression) -> bool:
    """Whether a top-level projection is ``*`` or ``t.*`` (not ``count(*)``)."""
    return isinstance(proj, exp.Star) or (
        isinstance(proj, exp.Column) and isinstance(proj.this, exp.Star)
    )


def _projection_slots(expr: exp.Expression) -> int:
    """Value slots a single projection materializes, expanding constructors.

    A scalar (column, arithmetic, function call) is one slot; a composite VALUE
    constructor — a row ``(a, b, c)``, ``ARRAY[…]``, or a struct — materializes
    one slot per element and nests, so ``(payload, payload, … 1600x)`` counts as
    1600 even though it is one AST projection.
    """
    if isinstance(expr, exp.Alias):
        expr = expr.this
    if isinstance(expr, exp.Paren):
        return _projection_slots(expr.this)
    if isinstance(expr, (exp.Tuple, exp.Array, exp.Struct)):
        elements = expr.expressions
        return sum(_projection_slots(e) for e in elements) if elements else 1
    return 1


def _reject_too_many_output_columns(
    stmt: exp.Expression, sql: str, cap: int | None
) -> None:
    """Reject a statement whose output row is too wide.

    fix(#565 codex P1 r20/r21): response width amplifies with no function at
    all. Three forms, all bounded here by counting VALUE SLOTS (not AST
    projections): ``SELECT payload, payload, … 1600x`` (many projections);
    ``SELECT (payload, payload, …)`` (one composite projection, r21); and
    ``SELECT *`` / ``t.*`` against a wide table, which expands to an unknown
    count and so is refused outright — the raw endpoint requires explicit
    columns (r21). The result columns are the outermost scope's projections (a
    set op's branches must match, so the first branch is representative).
    """
    if cap is None:
        return
    outer = stmt
    while isinstance(outer, (exp.Union, exp.Intersect, exp.Except)):
        outer = outer.this
    if not isinstance(outer, exp.Select):
        return
    if any(_is_wildcard_projection(proj) for proj in outer.expressions):
        logger.info("sandbox.wildcard_projection", sql=sql)
        raise SandboxError("invalid_query", "Query must select explicit columns, not *")
    width = sum(_projection_slots(proj) for proj in outer.expressions)
    if width > cap:
        logger.info("sandbox.too_many_columns", sql=sql, columns=width, cap=cap)
        raise SandboxError("invalid_query", "Query selects too many columns")


def _reject_oversized_values(stmt: exp.Expression, sql: str, cap: int | None) -> None:
    """Reject an inline VALUES relation with more than ``cap`` tuples (#565 r17)."""
    if cap is None:
        return
    for values in stmt.find_all(exp.Values):
        if len(values.expressions) > cap:
            logger.info(
                "sandbox.values_too_large",
                sql=sql,
                rows=len(values.expressions),
                cap=cap,
            )
            raise SandboxError(
                "invalid_query", "Query uses too many inline VALUES rows"
            )


def _reject_recursive_cte(stmt: exp.Expression, sql: str) -> None:
    """Reject recursive CTEs, which are unbounded row generators."""
    if any(
        with_clause.args.get("recursive") for with_clause in stmt.find_all(exp.With)
    ):
        logger.info("sandbox.recursive_cte", sql=sql)
        raise SandboxError("invalid_query", "Recursive queries are not allowed")


def _reject_oid_alias_casts(stmt: exp.Expression, sql: str) -> None:
    """Reject casts to PostgreSQL OID-alias types (``regrole``, ``regclass``…).

    fix(#565 codex P1 r11): a cast to a ``reg*`` OID-alias type resolves an
    integer OID to a catalog name — ``SELECT v::regrole FROM data.foo CROSS
    JOIN (VALUES (10), (16384)) AS x(v)`` reads database role names without
    referencing any catalog table, the same disclosure the CTE-scope fixes
    close from the other direction.

    fix(#565 codex P1 r12): match by the NORMALIZED type NAME, not the node
    type. A bare ``regrole`` parses as ``exp.ObjectIdentifier`` but a
    schema-qualified ``pg_catalog.regrole`` parses as a USER-DEFINED
    ``exp.DataType``, so a node-type check missed the qualified spelling. The
    rendered target's identifier tokens are checked against the OID-alias set
    instead, which catches every spelling. Normal types (``int``, ``text``,
    ``numeric(10,2)``, a user enum) never render one of these tokens.
    """
    for cast in stmt.find_all(exp.Cast):
        rendered = cast.to.sql(dialect="postgres").lower()
        if set(_IDENTIFIER_TOKEN_RE.findall(rendered)) & _OID_ALIAS_TYPES:
            logger.info("sandbox.oid_alias_cast", sql=sql, target=rendered)
            raise SandboxError("invalid_query", "Query uses a disallowed type cast")


def _check_niladic_keywords(stmt: exp.Expression, sql: str) -> None:
    """Reject PostgreSQL's parenless identity keywords (fix(#1778)).

    ``SELECT user``/``current_role``/``system_user`` parse as ``exp.Column``,
    so the Func walk in :func:`_check_function_allowlist` never sees them, yet
    PostgreSQL evaluates them as SQLValueFunctions and returns the effective
    role, the login name and the authentication method. On the AI-chat path
    that is a reliable readout of whether ``SET LOCAL ROLE geolens_reader``
    took effect, which is exactly the oracle the sandbox should not hand out.

    Only the unqualified, unquoted spelling is rejected: ``t.user`` and
    ``"user"`` are real column references in PostgreSQL and stay allowed.
    """
    for column in stmt.find_all(exp.Column):
        if column.table:
            continue
        identifier = column.this
        if not isinstance(identifier, exp.Identifier) or identifier.quoted:
            continue
        if identifier.name.lower() not in _BLOCKED_NILADIC_KEYWORDS:
            continue
        logger.info(
            "sandbox.blocked_niladic_keyword", sql=sql, keyword=identifier.name.lower()
        )
        raise SandboxError("invalid_query", "Query uses a disallowed function")


def _check_function_allowlist(
    stmt: exp.Expression,
    sql: str,
    extra_blocked: frozenset[str] | None = None,
) -> None:
    """Fail-closed function check (SEC-025).

    For each Func node in the AST, extract its canonical lowercase name:
      • Anonymous nodes  → fn.name.lower()  (the raw SQL identifier)
      • Named Func nodes → fn.sql_name().lower()  (sqlglot's canonical name,
        which may differ from the SQL keyword — see _ALLOWED_FUNCTIONS docs)

    Then apply fail-closed logic (order matters):
      1. BLOCKED  → always reject (defense-in-depth; checked before allowlist)
      2. Inside a verified canonical buffer → skip 3-5 (fix(#1001))
      3. "st_" name → require the prompt-derived PostGIS allowlist
      4. Other name → require _ALLOWED_FUNCTIONS
      5. Allowed spatial functions → reject unbounded aggregate/complexity forms
      6. Otherwise → reject (fail-closed)

    A second pass rejects the parenless niladic keywords sqlglot parses as
    columns rather than functions (see _BLOCKED_NILADIC_KEYWORDS).
    """
    _check_niladic_keywords(stmt, sql)
    buffer_scaffold = _canonical_buffer_exempt_ids(stmt)
    for func in stmt.find_all(exp.Func):
        # fix(#538): sqlglot models AND/OR (exp.Connector) as Func subclasses,
        # so any compound condition (WHERE x AND y, JOIN ... ON a AND b,
        # CASE WHEN ... AND ...) was rejected as an unlisted "function".
        # Connectors are boolean operators, not callables — and find_all walks
        # their operands regardless, so a disallowed function inside either
        # side of an AND/OR is still caught below.
        if isinstance(func, exp.Connector):
            continue
        # fix(#1017): sqlglot reaches EXISTS through the same Func path (#538),
        # so every EXISTS subquery was rejected as an unlisted "function".
        # EXISTS is a subquery predicate, not a callable — and find_all walks
        # its operand regardless, so a disallowed function inside the subquery
        # is still caught below.
        if isinstance(func, exp.Exists):
            continue
        fn_name = _func_name(func)

        if fn_name in _BLOCKED_FUNCTIONS or (
            extra_blocked is not None and fn_name in extra_blocked
        ):
            # fix(#565 codex P1 r17): extra_blocked lets the raw-SQL endpoint
            # drop output-amplifying functions (e.g. ``format`` with a giant
            # width) that neither the SQL-length cap nor row_limit bounds, while
            # AI chat keeps them.
            logger.info("sandbox.blocked_function", sql=sql, function=fn_name)
            raise SandboxError("invalid_query", "Query uses a disallowed function")

        # fix(#1001): the sixteen names the canonical geodesic buffer needs are
        # admitted here and nowhere else. The BLOCKED check above still runs —
        # nothing in the rendered scaffold can be a blocked function, and
        # keeping the check unconditional means a renderer change could never
        # smuggle one in.
        if id(func) in buffer_scaffold:
            continue

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


def validate_sql(
    sql: str,
    *,
    extra_blocked_functions: frozenset[str] | None = None,
    max_values_rows: int | None = None,
    max_output_columns: int | None = None,
) -> ValidatedQuery:
    """Parse and validate SQL. Returns validated query or raises SandboxError.

    Accepts: single SELECT, UNION, INTERSECT, EXCEPT.
    Rejects: INSERT, UPDATE, DELETE, DROP, CREATE, multi-statement, SELECT INTO.

    ``extra_blocked_functions``, ``max_values_rows``, and ``max_output_columns``
    (fix(#565 codex P1 r17/r20)) are the raw-SQL endpoint's extra guards —
    output-amplifying function names to reject, a per-VALUES tuple-count cap,
    and a projection-count cap (repeated columns amplify response width) — left
    None (off) for AI chat so its behavior is unchanged.
    """
    # Parse with postgres dialect
    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.SqlglotError as exc:
        # fix(#1778): an unterminated literal, identifier, comment or
        # dollar-quote raises TokenError, which is a SIBLING of ParseError
        # under SqlglotError, not a subclass. Catching ParseError alone let the
        # commonest SQL typo escape the security boundary's own parse step and
        # surface as HTTP 500 "Query failed" instead of 422 "Invalid SQL
        # syntax". executor.py makes the same catch for the same reason.
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

    _reject_too_many_output_columns(stmt, sql, max_output_columns)

    _reject_nested_mutation(stmt, sql)

    _reject_recursive_cte(stmt, sql)

    _reject_oid_alias_casts(stmt, sql)

    _reject_oversized_values(stmt, sql, max_values_rows)

    # fix(#565 codex P1 r19): the `||` operator is string concatenation, an
    # output amplifier equivalent to concat — `s || s` chained through
    # MATERIALIZED CTEs doubles a value each stage into hundreds of MB. It is an
    # exp.DPipe operator, not a Func, so the function blocklist misses it. When
    # the caller blocks concat (the raw endpoint), block `||` for the same
    # reason; AI chat blocks neither.
    if (
        extra_blocked_functions
        and "concat" in extra_blocked_functions
        and stmt.find(exp.DPipe)
    ):
        logger.info("sandbox.blocked_concat_operator", sql=sql)
        raise SandboxError("invalid_query", "Query uses a disallowed operator")

    _check_function_allowlist(stmt, sql, extra_blocked=extra_blocked_functions)

    # Extract CTE names (global) for the ValidatedQuery contract and the
    # emptiness gate. Table ACCESS classification below is lexical, not by
    # membership in this flat set (see _is_cte_reference / fix(#565 codex P1)).
    cte_names: set[str] = set()
    for cte in stmt.find_all(exp.CTE):
        if cte.alias:
            cte_names.add(cte.alias)

    # Extract table references as (schema, name) tuples. An unqualified name
    # that resolves to a lexically in-scope CTE is a CTE reference, not a real
    # table, and is excluded here so it is never access-checked. Everything
    # left — schema-qualified tables AND unqualified names with no in-scope CTE
    # — must pass the data.* check in check_table_access.
    tables: set[tuple[str, str]] = set()
    for table in stmt.find_all(exp.Table):
        # fix(#565 codex P2 r23): fold unquoted identifiers the way PostgreSQL
        # resolves them (unquoted → lowercase, quoted → verbatim) BEFORE the
        # access check. `FROM DATA.ROADS` resolves to `data.roads` in the
        # server, so comparing sqlglot's preserved `("DATA", "ROADS")` against
        # the lowercase allowlist would 404 a table the caller can read. Mirrors
        # the CTE resolver's folding.
        schema = _folded_identifier(table.args.get("db")) or ""
        name = _folded_identifier(table.this)
        if not name:
            continue
        if _is_cte_reference(table):
            continue
        tables.add((schema, name))

    # Transitive self-join fan-out: the largest number of times any one base
    # table is multiplied into the statement's cardinality, following the CTE
    # dependency graph (feat(#565); fix(#565 codex P1 r3)). Callers bound this
    # to reject cross-join cost amplification.
    max_table_fanout = _max_table_fanout(stmt)

    return ValidatedQuery(
        sql=sql,
        tables=tables,
        cte_names=cte_names,
        max_table_fanout=max_table_fanout,
    )


def _resolve_cte(table: exp.Table) -> exp.CTE | None:
    """The CTE an unqualified table node references, honoring lexical scope.

    fix(#565 codex P1): validation used to collect every CTE name in the
    statement into one flat set and treat any unqualified table matching a
    member as a CTE reference to skip. A CTE named after a catalog relation in
    another scope masked an unqualified reference of the same name, so a
    top-level ``pg_user`` (or one in an earlier WITH item) was skipped instead
    of rejected, and PostgreSQL resolved it to the readable
    ``pg_catalog.pg_user`` view under the reader role — a restrict_tables
    bypass that discloses catalog metadata including role names.

    The name is resolved against the WITH clauses actually in scope for THIS
    node, honoring PostgreSQL's declaration order (fix(#565 codex P1 r2)):
    within one WITH, a CTE body sees only siblings declared strictly BEFORE it,
    while the owner query body sees them all. The nearest enclosing binding
    wins (lexical shadowing). Recursive WITHs — the one case where a CTE would
    see itself — are already rejected upstream (``_reject_recursive_cte``), so
    forward/self references never resolve here.

    A schema-qualified name (``data.foo``, ``pg_catalog.pg_user``) is never a
    CTE reference. Returns None when the name does not resolve to an in-scope
    CTE, so the reference is treated as a real table (fail-closed).

    fix(#565 codex P1 r12): identifiers are matched with PostgreSQL case
    folding — an UNQUOTED name folds to lowercase, a QUOTED one keeps its case.
    ``WITH "PG_USER" AS (...) SELECT FROM PG_USER`` does NOT bind: the quoted
    CTE is ``PG_USER`` while the unquoted reference folds to ``pg_user``, which
    PostgreSQL then resolves to the ``pg_catalog.pg_user`` view — so the
    reference must stay unresolved and fall through to the data.* check.
    """
    if table.db:
        return None
    target = _folded_identifier(table.this)
    child: exp.Expression = table
    node = table.parent
    while node is not None:
        if isinstance(node, exp.With) and isinstance(child, exp.CTE):
            # The reference lives inside `child`'s body. Only CTEs declared
            # before it in this WITH are visible (non-recursive semantics).
            # Identity, not ``==``: sqlglot nodes compare by structure, so two
            # structurally identical CTE bodies must not be conflated.
            ctes = [c for c in node.expressions if isinstance(c, exp.CTE)]
            idx = next((i for i, c in enumerate(ctes) if c is child), None)
            if idx is not None:
                for c in reversed(ctes[:idx]):
                    if _folded_cte_alias(c) == target:
                        return c
        elif isinstance(node, _SCOPE_TYPES):
            # The WITH is a child of its owner scope under a sqlglot arg key
            # that has drifted across releases ("with" -> "with_"), so find it
            # by type rather than by key (same reason _own_sources iterates).
            # The owner is a SELECT *or* a set operation: fix(#565 codex P2 r5)
            # — `WITH a AS (...) SELECT FROM a UNION ALL SELECT FROM a` attaches
            # the WITH to the exp.Union, not its branch SELECTs, so a
            # Select-only check left both `a` references unresolved and 404'd a
            # valid UNION.
            with_clause = next(
                (c for c in node.iter_expressions() if isinstance(c, exp.With)),
                None,
            )
            # An owner query body (we did NOT ascend from this scope's own WITH
            # node — that path is handled above) sees every CTE it declares.
            if with_clause is not None and child is not with_clause:
                for c in with_clause.expressions:
                    if isinstance(c, exp.CTE) and _folded_cte_alias(c) == target:
                        return c
        child = node
        node = node.parent
    return None


def _folded_identifier(identifier: exp.Expression | None) -> str | None:
    """A PostgreSQL-folded identifier: unquoted → lowercase, quoted → verbatim.

    Returns None when the identifier is absent, so an unresolvable reference
    fails closed rather than matching a folded empty string.
    """
    if not isinstance(identifier, exp.Identifier):
        return None
    return identifier.name if identifier.quoted else identifier.name.lower()


def _folded_cte_alias(cte: exp.CTE) -> str | None:
    """The folded alias of a CTE, honoring quoting on its ``AS name``."""
    alias = cte.args.get("alias")
    ident = alias.this if isinstance(alias, exp.TableAlias) else None
    return _folded_identifier(ident)


def _is_cte_reference(table: exp.Table) -> bool:
    """Whether an unqualified table node resolves to an in-scope CTE."""
    return _resolve_cte(table) is not None


# ---------------------------------------------------------------------------
# Fan-out cost model (best-effort pre-filter, NOT a security boundary)
#
# Everything from here down estimates how many times a query multiplies work,
# so an obviously-expensive statement gets a fast 422. It is deliberately
# incomplete: it reads a static AST with no catalog statistics, so a construct
# that launders or hides a multiplier (a same-side equality, a cast/CASE around
# a wide tuple, a set-returning function) can be under-counted. That is safe by
# design — see the module docstring: every executed query is bounded at runtime
# (one-per-user advisory lock, capacity semaphore, statement_timeout, READ ONLY
# reader role, row + serialized-byte caps), so the worst case of an under-count
# is one query burning its own timeout with clamped output. Under-counts that
# stay within that floor are documented, not chased construct-by-construct.
# ---------------------------------------------------------------------------

# Fan-out saturation ceiling. A CTE chain built to blow past the cap produces
# an astronomically large multiplicity (2**depth); clamping keeps the
# validator's own arithmetic O(1) per node — it never materializes a bignum —
# while any real cap sits far below this, so a saturated value still trips it.
_FANOUT_CEILING = 1 << 16


_FanoutMap = dict[tuple[str, str], int]
_FanoutMemo = dict[int, _FanoutMap | None]
_SCOPE_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)

# fix(#565 codex P1 r20): a synthetic key tracking the TOTAL cross-product
# degree — how many relations a statement multiplies together via UNCONSTRAINED
# (cross / cartesian) joins. Per-base-table exponents catch SELF-join
# amplification (N^k on one table), but three DISTINCT tables cross-joined is
# N×M×K and each carries exponent 1, so the per-table max misses it. This key
# accumulates one unit per unconstrained source, folded into the same cap.
_XPROD_KEY: tuple[str, str] = ("", "__xprod__")


def _set_op_branches(node: exp.Expression) -> list[exp.Expression]:
    """The two operands of a UNION/INTERSECT/EXCEPT node."""
    return [b for b in (node.this, node.args.get("expression")) if b is not None]


def _join_is_constrained(join: exp.Join) -> bool:
    """Whether a JOIN reduces cardinality (an equijoin) rather than multiplying.

    A USING clause, or an ON with an equality whose two sides each reference a
    column, is a lookup that keeps the output near the larger input. A CROSS
    JOIN, a comma-join, ``ON true`` or ``ON 1=1`` do not constrain and multiply
    the cross product. The distinction lets legit multi-table equijoins pass
    while cartesian products of distinct tables are bounded (fix(#565 codex P1
    r20)).
    """
    if join.args.get("using"):
        return True
    return _predicate_constrains(join.args.get("on"))


def _predicate_constrains(node: exp.Expression | None) -> bool:
    """Whether a boolean predicate genuinely narrows the join it gates.

    fix(#565 codex P1 r21): an equality merely OCCURRING in the ON is not
    enough — ``a.gid = b.gid OR TRUE`` is always true, so the join is still a
    cartesian product. The predicate constrains only if an ``AND`` has a
    constraining side, an ``OR`` has ALL sides constraining, or it is itself a
    column-to-column equality. ``TRUE`` / ``1=1`` / an inequality do not.
    """
    if node is None:
        return False
    if isinstance(node, exp.Paren):
        return _predicate_constrains(node.this)
    if isinstance(node, exp.And):
        return _predicate_constrains(node.this) or _predicate_constrains(
            node.expression
        )
    if isinstance(node, exp.Or):
        return _predicate_constrains(node.this) and _predicate_constrains(
            node.expression
        )
    if isinstance(node, exp.EQ):
        return (
            node.this is not None
            and node.expression is not None
            and node.this.find(exp.Column) is not None
            and node.expression.find(exp.Column) is not None
        )
    return False


def _from_join_pairs(select: exp.Select) -> list[tuple[exp.Expression, bool]]:
    """(source, multiplies) for the FROM source and each JOIN of ``select``.

    The FROM source always contributes to the cross product; a JOIN multiplies
    it only when unconstrained (see _join_is_constrained).
    """
    pairs: list[tuple[exp.Expression, bool]] = []
    for child in select.iter_expressions():
        if isinstance(child, exp.From):
            pairs.append((child.this, True))
        elif isinstance(child, exp.Join):
            pairs.append((child.this, not _join_is_constrained(child)))
    return pairs


def _rows_fanout(node: exp.Expression, memo: _FanoutMemo) -> _FanoutMap:
    """Worst-case ROW multiplicity of each base table produced by ``node``.

    Maps ``(schema, name)`` to the exponent that base table carries in the
    node's cardinality: a SELECT's rows are at most the PRODUCT of its
    from/join sources, so exponents SUM across sources and a source referenced
    twice counts twice; a set operation's rows are bounded by the larger
    branch, so exponents take the elementwise MAX. Memoized by node id so a CTE
    referenced k times is costed once, not 2**depth times. Also accumulates
    ``_XPROD_KEY`` — the cross-product degree over unconstrained joins.
    """
    key = id(node)
    if key in memo:
        # None marks a node currently being resolved: a cycle (defensive —
        # recursion is already rejected) contributes nothing further.
        return memo[key] or {}
    memo[key] = None

    out: _FanoutMap = {}
    if isinstance(node, exp.Select):
        for source, multiplies in _from_join_pairs(node):
            _accumulate_source(out, _source_fanout(source, memo), multiplies)
    elif isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
        for branch in _set_op_branches(node):
            for base, weight in _rows_fanout(branch, memo).items():
                out[base] = min(max(out.get(base, 0), weight), _FANOUT_CEILING)

    memo[key] = out
    return out


def _accumulate_source(
    out: _FanoutMap, source_fanout: _FanoutMap, multiplies: bool
) -> None:
    """Fold one from/join source into a running rows map (base keys + xprod).

    Base-table exponents SUM (the join product). The cross-product degree grows
    only when the source ``multiplies`` (an unconstrained join): by the source's
    own nested degree if it has one, else its base-scan count.
    """
    base_degree = 0
    for base, weight in source_fanout.items():
        if base == _XPROD_KEY:
            continue
        out[base] = min(out.get(base, 0) + weight, _FANOUT_CEILING)
        base_degree += weight
    if multiplies:
        degree = source_fanout.get(_XPROD_KEY, base_degree)
        out[_XPROD_KEY] = min(out.get(_XPROD_KEY, 0) + degree, _FANOUT_CEILING)


def _source_fanout(source: exp.Expression, memo: _FanoutMemo) -> _FanoutMap:
    """Base-table row multiplicity contributed by one from/join source."""
    if isinstance(source, exp.Table):
        cte = _resolve_cte(source)
        if cte is not None:
            return _rows_fanout(cte.this, memo)
        # A base table (real, or an out-of-scope name the access check will
        # reject) is scanned once.
        return {(source.db or "", source.name): 1}
    if isinstance(source, exp.Lateral):
        # fix(#565 codex P1 r6): a LATERAL re-evaluates its subquery per outer
        # row, and its OUTPUT rows join into the FROM product, so it is a row
        # source like a derived table — `CROSS JOIN LATERAL (SELECT ... FROM
        # data.foo c ...)` beside `data.foo a CROSS JOIN data.foo b` is N^3.
        # (Its INTERNAL per-row work is added separately in _work_fanout.)
        inner = _lateral_inner_scope(source)
        return _rows_fanout(inner, memo) if inner is not None else {}
    if isinstance(source, exp.Subquery):
        inner = source.this
        if isinstance(inner, _SCOPE_TYPES):
            return _rows_fanout(inner, memo)
        # fix(#565 codex P1 r8): a parenthesized FROM join group —
        # `(data.foo a CROSS JOIN data.foo b CROSS JOIN data.foo c)` — is a
        # Subquery wrapping a Table that carries its joins in `.args["joins"]`,
        # not a SELECT. Cost the head source and every joined source, so the
        # cross join inside the parentheses is not a fan-out of 0.
        return _group_fanout(inner, memo)
    if isinstance(source, exp.Values):
        # fix(#565 codex P1 r17/r18): a constant VALUES relation contributes
        # rows too. Cross-joining VALUES k times is a k-way row explosion —
        # whether the same CTE referenced k times or k separately-written
        # inline literals. All VALUES share ONE fan-out key so distinct
        # constant sources combine in the cross-product (r18: per-node ids let
        # k distinct VALUES each report 1 and slip 256^k combinations); each
        # literal's own cardinality is separately capped in validate_sql.
        return {("", "__values__"): 1}
    # Anything else in a FROM (an allowlisted table function) does not open a
    # base-table cross-join vector; the function/table checks bound it.
    return {}


def _group_fanout(head: exp.Expression, memo: _FanoutMemo) -> _FanoutMap:
    """Row multiplicity of a join group: its head source times each join.

    ``head`` may itself carry ``.args["joins"]`` (a parenthesized cross join);
    the product is the head's fan-out plus each join source's, mirroring how a
    SELECT's sources compose, and accumulating the cross-product degree over
    the group's unconstrained joins.
    """
    out: _FanoutMap = {}
    _accumulate_source(out, _source_fanout(head, memo), True)
    for join in head.args.get("joins") or []:
        multiplies = not _join_is_constrained(join)
        _accumulate_source(out, _source_fanout(join.this, memo), multiplies)
    return out


def _group_sources(head: exp.Expression) -> list[exp.Expression]:
    """The head source plus every joined source of a parenthesized group."""
    return [head] + [join.this for join in head.args.get("joins") or []]


def _group_head(source: exp.Expression) -> exp.Expression | None:
    """The join-group head under a parenthesized FROM source, else None.

    A parenthesized group is a Subquery wrapping a NON-scope (a Table that
    carries its joins); a Subquery wrapping a SELECT/set-op is a derived table.
    """
    if isinstance(source, exp.Subquery) and not isinstance(source.this, _SCOPE_TYPES):
        return source.this
    return None


def _group_work(head: exp.Expression, wm: _FanoutMemo, rm: _FanoutMemo) -> _FanoutMap:
    """Work of building a parenthesized join group ONCE.

    fix(#565 codex P1 r9): its rows are the head/joins cross product, PLUS each
    join's ON predicate runs per group row (a correlated ON scan is N^k the row
    count missed), PLUS any LATERAL among its sources carries its own excess. A
    group builds once, so this stands as its own candidate in the
    statement-wide max rather than multiplying an enclosing SELECT.
    """
    key = id(head)
    if key in wm:
        return wm[key] or {}
    wm[key] = None
    out = dict(_group_fanout(head, rm))
    # Per-group-row work — the group's LATERAL/derived source excesses and its
    # joins' ON-predicate subqueries — are siblings, so combine them by MAX and
    # add once to the group's row fan-out (fix(#565 codex P2 r13)).
    per_row: _FanoutMap = {}
    for source in _group_sources(head):
        _merge_max(per_row, _source_excess(source, wm, rm))
    for join in head.args.get("joins") or []:
        on = join.args.get("on")
        if on is not None:
            for scope in _outermost_scopes(on):
                _merge_max(per_row, _work_fanout(scope, wm, rm))
    for base, weight in per_row.items():
        out[base] = min(out.get(base, 0) + weight, _FANOUT_CEILING)
    wm[key] = out
    return out


def _outermost_scopes(root: exp.Expression) -> list[exp.Expression]:
    """Top-level subquery scopes within a predicate expression (an ON/WHERE).

    A scope whose nearest scope-ancestor lies OUTSIDE ``root`` is top-level in
    it; deeper scopes are reached by recursion when their parent is costed.
    """
    out: list[exp.Expression] = []
    for node in root.find_all(*_SCOPE_TYPES):
        ancestor = node.parent
        outermost = True
        while ancestor is not None and ancestor is not root:
            if isinstance(ancestor, _SCOPE_TYPES):
                outermost = False
                break
            ancestor = ancestor.parent
        if outermost:
            out.append(node)
    return out


def _source_excess(
    source: exp.Expression, wm: _FanoutMemo, rm: _FanoutMemo
) -> _FanoutMap:
    """A per-outer-row source's EXCESS work (work minus its own rows).

    A LATERAL re-evaluates per outer row; its rows are already in the product,
    so only its internal correlated/nested work beyond its row count adds
    (fix(#565 codex P1 r7)). A parenthesized group's excess is folded in the
    same way when the group sits in a per-row position (e.g. inside a LATERAL).

    fix(#565 codex P1 r10): a CTE reference carries excess too. PostgreSQL
    inlines a non-recursive CTE — always for ``NOT MATERIALIZED``, and by
    default when referenced once — so its internal correlated work re-executes
    per outer row rather than materializing once. Costing a reference as
    rows-only let ``a p CROSS JOIN a q`` over a CTE with a correlated scan slip
    the bound; propagating its excess treats every reference as inlined, the
    worst case.

    fix(#565 codex P1 r12): an ordinary derived table (a subquery in FROM/JOIN)
    is the same worst case — PostgreSQL can FLATTEN it, pulling its correlated
    subquery up to run per outer row, so ``(SELECT x.gid, (correlated) n FROM
    foo x) p CROSS JOIN foo q`` is N^3. Its excess propagates like a CTE's.

    fix(#565 codex P1 r16): a LATERAL over a NON-scope — ``LATERAL (VALUES
    ((SELECT ... a CROSS JOIN b ...)))`` — carries no inner scope to unwrap,
    but the subqueries buried in it still run per outer row. Cost those
    directly as the lateral's per-row work.
    """
    work: _FanoutMap
    rows: _FanoutMap
    inner_scope: exp.Expression | None = None
    if isinstance(source, exp.Table):
        cte = _resolve_cte(source)
        inner_scope = cte.this if cte is not None else None
    elif isinstance(source, exp.Lateral):
        inner_scope = _lateral_inner_scope(source)
    elif isinstance(source, exp.Subquery) and isinstance(source.this, _SCOPE_TYPES):
        inner_scope = source.this

    if inner_scope is not None and isinstance(inner_scope, _SCOPE_TYPES):
        work = _work_fanout(inner_scope, wm, rm)
        rows = _rows_fanout(inner_scope, rm)
    elif isinstance(source, exp.Lateral):
        # Non-scope LATERAL (VALUES / table function): it produces no
        # base-table rows, so its whole per-outer-row cost is the subqueries
        # buried inside it, combined by MAX (siblings).
        per_row: _FanoutMap = {}
        for scope in _outermost_scopes(source):
            _merge_max(per_row, _work_fanout(scope, wm, rm))
        return per_row
    else:
        head = _group_head(source)
        if head is None:
            return {}
        work = _group_work(head, wm, rm)
        rows = _group_fanout(head, rm)
    # _XPROD_KEY is an input-cardinality metric (computed by _rows_fanout /
    # _group_fanout); it is not per-row EXCESS work, so drop it here.
    return {
        base: weight - rows.get(base, 0)
        for base, weight in work.items()
        if base != _XPROD_KEY and weight - rows.get(base, 0) > 0
    }


def _lateral_inner_scope(source: exp.Lateral) -> exp.Expression | None:
    """The SELECT/set-op beneath a LATERAL source, or None for a table function."""
    inner = source.this
    if isinstance(inner, exp.Subquery):
        inner = inner.this
    return inner if isinstance(inner, _SCOPE_TYPES) else None


def _correlated_scopes(
    select: exp.Select,
) -> tuple[list[exp.Expression], list[exp.Expression], list[exp.Expression]]:
    """Per-INPUT-row and per-OUTPUT-row subquery scopes of ``select``.

    fix(#565 codex P1 r4): a scalar/EXISTS/IN/WHERE subquery executes per row
    of the enclosing SELECT, so its work multiplies by that row count — a
    triple self-join hidden in ``SELECT (SELECT ... a CROSS JOIN b CROSS JOIN
    c) FROM ...`` is N^3 work the row-only cost missed. These are the outermost
    such scopes directly under ``select``; its FROM/JOIN sources (folded into
    ``_rows_fanout``) and its WITH bodies (costed where referenced) are
    excluded, and deeper nesting is reached by recursion on each scope.

    Returns ``(per_input, per_output, per_statement)``: whether the scope runs
    per INPUT row (WHERE / JOIN-ON / GROUP BY, before aggregation), per OUTPUT
    row (SELECT list / HAVING / ORDER BY, after it), or ONCE per statement
    (LIMIT / OFFSET — evaluated a single time, never correlated). Only per-output
    work shrinks when the SELECT aggregates (fix(#565 codex P2 r14)); per-
    statement work never gets a row multiplier (fix(#565 codex P2 r16)).

    A JOIN contributes BOTH a source (``join.this``) and an ``ON`` predicate,
    so it cannot be skipped wholesale: fix(#565 codex P1 r5) — a correlated
    subquery in ``JOIN ... ON`` runs per row like a WHERE and must be costed,
    while a derived table in the join's source position is a row source. The
    walk distinguishes them by which side of the join it ascended from.
    """
    per_input: list[exp.Expression] = []
    per_output: list[exp.Expression] = []
    per_statement: list[exp.Expression] = []
    for node in select.find_all(*_SCOPE_TYPES):
        if node is select:
            continue
        prev: exp.Expression = node
        ancestor = node.parent
        clause: exp.Expression | None = None
        under_aggregate = False
        while ancestor is not None:
            if ancestor is select:
                clause = prev
                break
            if isinstance(ancestor, exp.From):
                break
            if isinstance(ancestor, exp.Join):
                # In the join's SOURCE -> a row source (costed by _rows_fanout).
                # In its ON/USING predicate -> keep ascending toward `select`.
                if prev is ancestor.this:
                    break
            elif isinstance(ancestor, (exp.With, exp.CTE, *_SCOPE_TYPES)):
                # A CTE body, or nested inside another subquery scope: not this
                # SELECT's own per-row predicate.
                break
            elif isinstance(ancestor, exp.AggFunc):
                # fix(#565 codex P1 r15): the scope is an aggregate ARGUMENT (or
                # FILTER), which the aggregate evaluates for every INPUT row —
                # ``sum((SELECT ... WHERE b.gid = a.gid))`` runs the correlated
                # subquery per outer row, so the ungrouped-aggregate reduction
                # must NOT zero its multiplier.
                under_aggregate = True
            prev = ancestor
            ancestor = ancestor.parent
        if clause is None:
            continue
        # fix(#565 codex P2 r14): classify by the clause that runs the scope.
        # WHERE / JOIN-ON / GROUP BY are evaluated per INPUT row (before
        # aggregation); the SELECT list, HAVING, ORDER BY, QUALIFY run per
        # OUTPUT row (after aggregation). Only per-output work shrinks when the
        # SELECT aggregates to fewer rows — EXCEPT an aggregate argument, which
        # still runs per input row (fix(#565 codex P1 r15)). LIMIT / OFFSET are
        # evaluated ONCE (fix(#565 codex P2 r16)).
        if isinstance(clause, (exp.Limit, exp.Offset)):
            per_statement.append(node)
        elif isinstance(clause, (exp.Where, exp.Join, exp.Group)) or under_aggregate:
            per_input.append(node)
        else:
            per_output.append(node)
    return per_input, per_output, per_statement


def _work_fanout(
    node: exp.Expression, work_memo: _FanoutMemo, rows_memo: _FanoutMemo
) -> _FanoutMap:
    """Worst-case WORK multiplicity: rows plus per-row correlated subquery work.

    A set operation's work is the larger branch's; a SELECT's is its row
    fan-out plus, for each correlated subquery it runs once per row, that
    subquery's own work (exponents add — the subquery repeats for every row).
    """
    key = id(node)
    if key in work_memo:
        return work_memo[key] or {}
    work_memo[key] = None

    if isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
        out: _FanoutMap = {}
        for branch in _set_op_branches(node):
            for base, weight in _work_fanout(branch, work_memo, rows_memo).items():
                out[base] = min(max(out.get(base, 0), weight), _FANOUT_CEILING)
        work_memo[key] = out
        return out

    input_rows = _rows_fanout(node, rows_memo)
    out = dict(input_rows)
    if isinstance(node, exp.Select):
        # Per-row subquery/source work at THIS level. SIBLINGS run additively —
        # PostgreSQL evaluates them sequentially per row — so combine each group
        # by the per-table MAX, not the sum (fix(#565 codex P2 r13): summing
        # rejected a legit query with two scalar subqueries over one table).
        # Genuine NESTING adds, and the recursion inside each scope's own
        # _work_fanout already handles that.
        per_input, per_output, per_statement = _correlated_scopes(node)
        pin: _FanoutMap = {}
        for scope in per_input:
            _merge_max(pin, _work_fanout(scope, work_memo, rows_memo))
        for source in _own_sources(node):
            _merge_max(pin, _source_excess(source, work_memo, rows_memo))
        pout: _FanoutMap = {}
        for scope in per_output:
            _merge_max(pout, _work_fanout(scope, work_memo, rows_memo))
        pstmt: _FanoutMap = {}
        for scope in per_statement:
            _merge_max(pstmt, _work_fanout(scope, work_memo, rows_memo))
        # _XPROD_KEY is an input-cardinality metric already in `out` from
        # input_rows; per-row work must not re-multiply it.
        for bucket in (pin, pout, pstmt):
            bucket.pop(_XPROD_KEY, None)

        # A per-INPUT-row scope multiplies by the input scan; a per-OUTPUT-row
        # scope by the output cardinality, which an ungrouped aggregate
        # collapses to one row (exponent 0) — fix(#565 codex P2 r14); a
        # per-STATEMENT scope (LIMIT/OFFSET) runs once, multiplier 0
        # (fix(#565 codex P2 r16)). Each term is additive with the scan, so
        # combine by MAX.
        aggregated = _is_ungrouped_aggregate(node)
        for base, weight in pin.items():
            total = min(input_rows.get(base, 0) + weight, _FANOUT_CEILING)
            out[base] = max(out.get(base, 0), total)
        for base, weight in pout.items():
            multiplier = 0 if aggregated else input_rows.get(base, 0)
            total = min(multiplier + weight, _FANOUT_CEILING)
            out[base] = max(out.get(base, 0), total)
        for base, weight in pstmt.items():
            out[base] = max(out.get(base, 0), weight)
    work_memo[key] = out
    return out


def _is_ungrouped_aggregate(select: exp.Select) -> bool:
    """Whether ``select`` collapses its input to a single row.

    True when it has an aggregate in its own SELECT list and no GROUP BY, so
    per-output-row work runs once (fix(#565 codex P2 r14)). A GROUP BY is
    treated conservatively as not reducing (its output cardinality is unknown).
    """
    if select.args.get("group"):
        return False
    for projection in select.expressions:
        for agg in projection.find_all(exp.AggFunc):
            if agg.find_ancestor(exp.Select) is select:
                return True
    return False


def _merge_max(target: _FanoutMap, other: _FanoutMap) -> None:
    """Per-table MAX-merge ``other`` into ``target`` (sibling combination)."""
    for base, weight in other.items():
        target[base] = min(max(target.get(base, 0), weight), _FANOUT_CEILING)


def _max_table_fanout(stmt: exp.Expression) -> int:
    """The largest base-table WORK multiplicity anywhere in the statement.

    fix(#565 codex P1 r3): a per-reference count cannot see fan-out that
    COMPOSES through the CTE graph — ``WITH a AS (...foo), b AS (a CROSS JOIN
    a), c AS (b CROSS JOIN b) SELECT c CROSS JOIN c`` keeps every name at two
    references while multiplying ``data.foo`` to the eighth power.

    Taking the max over EVERY scope (fix(#565 codex P1 r4)) — not just the
    root's row fan-out — also catches a heavy self-join buried in a scalar or
    predicate subquery, or inside a CTE body's projection, wherever it sits.
    Parenthesized join groups (fix(#565 codex P1 r9)) are costed as their own
    candidates too, since their ON-predicate work has no wrapping SELECT. A
    plain pairwise self-join stays at 2, so a cap bounds real work rather than
    surface spellings.
    """
    rows_memo: _FanoutMemo = {}
    work_memo: _FanoutMemo = {}
    largest = 0

    def _consider(fanout: _FanoutMap) -> None:
        nonlocal largest
        if fanout:
            largest = max(largest, max(fanout.values()))

    for scope in stmt.find_all(*_SCOPE_TYPES):
        _consider(_work_fanout(scope, work_memo, rows_memo))
    # Parenthesized join groups have no wrapping SELECT, so cost them directly.
    for subquery in stmt.find_all(exp.Subquery):
        head = _group_head(subquery)
        if head is not None:
            _consider(_group_work(head, work_memo, rows_memo))
    return largest


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
