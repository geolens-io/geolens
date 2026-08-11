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
# The NL->SQL prompt mandates render_geodesic_buffer's output verbatim for
# metric buffers (sql_generator.py renders it at import time), and that
# expression needs sixteen function names the fail-closed allowlist does not
# carry — the banding, seam-splitting and dissolve machinery. So every buffer
# question in the NL->SQL surface was refused.
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
      2. Inside a verified canonical buffer → skip 3-5 (fix(#1001))
      3. "st_" name → require the prompt-derived PostGIS allowlist
      4. Other name → require _ALLOWED_FUNCTIONS
      5. Allowed spatial functions → reject unbounded aggregate/complexity forms
      6. Otherwise → reject (fail-closed)
    """
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

        if fn_name in _BLOCKED_FUNCTIONS:
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

    _reject_nested_mutation(stmt, sql)

    _reject_recursive_cte(stmt, sql)

    _check_function_allowlist(stmt, sql)

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
        schema = table.db or ""
        name = table.name
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
    """
    if table.db:
        return None
    name = table.name
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
                    if c.alias == name:
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
                    if isinstance(c, exp.CTE) and c.alias == name:
                        return c
        child = node
        node = node.parent
    return None


def _is_cte_reference(table: exp.Table) -> bool:
    """Whether an unqualified table node resolves to an in-scope CTE."""
    return _resolve_cte(table) is not None


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


def _set_op_branches(node: exp.Expression) -> list[exp.Expression]:
    """The two operands of a UNION/INTERSECT/EXCEPT node."""
    return [b for b in (node.this, node.args.get("expression")) if b is not None]


def _rows_fanout(node: exp.Expression, memo: _FanoutMemo) -> _FanoutMap:
    """Worst-case ROW multiplicity of each base table produced by ``node``.

    Maps ``(schema, name)`` to the exponent that base table carries in the
    node's cardinality: a SELECT's rows are at most the PRODUCT of its
    from/join sources, so exponents SUM across sources and a source referenced
    twice counts twice; a set operation's rows are bounded by the larger
    branch, so exponents take the elementwise MAX. Memoized by node id so a CTE
    referenced k times is costed once, not 2**depth times.
    """
    key = id(node)
    if key in memo:
        # None marks a node currently being resolved: a cycle (defensive —
        # recursion is already rejected) contributes nothing further.
        return memo[key] or {}
    memo[key] = None

    out: _FanoutMap = {}
    if isinstance(node, exp.Select):
        for source in _own_sources(node):
            for base, weight in _source_fanout(source, memo).items():
                out[base] = min(out.get(base, 0) + weight, _FANOUT_CEILING)
    elif isinstance(node, (exp.Union, exp.Intersect, exp.Except)):
        for branch in _set_op_branches(node):
            for base, weight in _rows_fanout(branch, memo).items():
                out[base] = min(max(out.get(base, 0), weight), _FANOUT_CEILING)

    memo[key] = out
    return out


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
    # Anything else in a FROM (VALUES, an allowlisted table function) does not
    # open a base-table cross-join vector; the function/table checks bound it.
    return {}


def _group_fanout(head: exp.Expression, memo: _FanoutMemo) -> _FanoutMap:
    """Row multiplicity of a join group: its head source times each join.

    ``head`` may itself carry ``.args["joins"]`` (a parenthesized cross join);
    the product is the head's fan-out plus each join source's, mirroring how a
    SELECT's ``_own_sources`` compose.
    """
    out: _FanoutMap = {}
    for base, weight in _source_fanout(head, memo).items():
        out[base] = min(out.get(base, 0) + weight, _FANOUT_CEILING)
    for join in head.args.get("joins") or []:
        for base, weight in _source_fanout(join.this, memo).items():
            out[base] = min(out.get(base, 0) + weight, _FANOUT_CEILING)
    return out


def _lateral_inner_scope(source: exp.Lateral) -> exp.Expression | None:
    """The SELECT/set-op beneath a LATERAL source, or None for a table function."""
    inner = source.this
    if isinstance(inner, exp.Subquery):
        inner = inner.this
    return inner if isinstance(inner, _SCOPE_TYPES) else None


def _correlated_scopes(select: exp.Select) -> list[exp.Expression]:
    """Subquery scopes in ``select``'s projection/predicate clauses.

    fix(#565 codex P1 r4): a scalar/EXISTS/IN/WHERE subquery executes per
    output ROW of the enclosing SELECT, so its work multiplies by the enclosing
    row count — a triple self-join hidden in ``SELECT (SELECT ... a CROSS JOIN
    b CROSS JOIN c) FROM ...`` is N^3 work the row-only cost missed. These are
    the outermost such scopes directly under ``select``; its FROM/JOIN sources
    (folded into ``_rows_fanout``) and its WITH bodies (costed where referenced)
    are excluded, and deeper nesting is reached by recursion on each scope.

    A JOIN contributes BOTH a source (``join.this``) and an ``ON`` predicate,
    so it cannot be skipped wholesale: fix(#565 codex P1 r5) — a correlated
    subquery in ``JOIN ... ON`` runs per row like a WHERE and must be costed,
    while a derived table in the join's source position is a row source. The
    walk distinguishes them by which side of the join it ascended from.
    """
    scopes: list[exp.Expression] = []
    for node in select.find_all(*_SCOPE_TYPES):
        if node is select:
            continue
        prev: exp.Expression = node
        ancestor = node.parent
        include = False
        while ancestor is not None:
            if ancestor is select:
                include = True
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
            prev = ancestor
            ancestor = ancestor.parent
        if include:
            scopes.append(node)
    return scopes


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

    out = dict(_rows_fanout(node, rows_memo))
    if isinstance(node, exp.Select):
        # A correlated projection/predicate subquery runs once per output row;
        # its rows are NOT already in this SELECT's product, so its whole work
        # adds.
        for scope in _correlated_scopes(node):
            for base, weight in _work_fanout(scope, work_memo, rows_memo).items():
                out[base] = min(out.get(base, 0) + weight, _FANOUT_CEILING)
        # fix(#565 codex P1 r7): a LATERAL source ALSO re-evaluates per outer
        # row, but its ROWS are already in the product above, so only its
        # EXCESS work — its own internal correlated/nested-lateral cost beyond
        # its row count — adds. `LATERAL (SELECT ... WHERE EXISTS (SELECT ...
        # data.foo c ...))` beside `data.foo a` is N^3 the row count alone
        # missed.
        for src in _own_sources(node):
            if not isinstance(src, exp.Lateral):
                continue
            inner = _lateral_inner_scope(src)
            if inner is None:
                continue
            inner_work = _work_fanout(inner, work_memo, rows_memo)
            inner_rows = _rows_fanout(inner, rows_memo)
            for base, weight in inner_work.items():
                excess = weight - inner_rows.get(base, 0)
                if excess > 0:
                    out[base] = min(out.get(base, 0) + excess, _FANOUT_CEILING)
    work_memo[key] = out
    return out


def _max_table_fanout(stmt: exp.Expression) -> int:
    """The largest base-table WORK multiplicity anywhere in the statement.

    fix(#565 codex P1 r3): a per-reference count cannot see fan-out that
    COMPOSES through the CTE graph — ``WITH a AS (...foo), b AS (a CROSS JOIN
    a), c AS (b CROSS JOIN b) SELECT c CROSS JOIN c`` keeps every name at two
    references while multiplying ``data.foo`` to the eighth power.

    Taking the max over EVERY scope (fix(#565 codex P1 r4)) — not just the
    root's row fan-out — also catches a heavy self-join buried in a scalar or
    predicate subquery, or inside a CTE body's projection, wherever it sits. A
    plain pairwise self-join stays at 2, so a cap bounds real work rather than
    surface spellings.
    """
    rows_memo: _FanoutMemo = {}
    work_memo: _FanoutMemo = {}
    largest = 0
    for scope in stmt.find_all(*_SCOPE_TYPES):
        fanout = _work_fanout(scope, work_memo, rows_memo)
        if fanout:
            largest = max(largest, max(fanout.values()))
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
