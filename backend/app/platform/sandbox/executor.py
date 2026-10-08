"""Safe SQL execution with defense-in-depth protections.

Defense layer 2: Database-enforced READ ONLY transaction, PostgreSQL
statement_timeout, and row limit truncation. All errors are sanitized
for end users while full details are logged server-side.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence

import structlog
import sqlglot
from sqlglot import exp
from sqlalchemy import BindParameter, text
from sqlalchemy.exc import DataError, InternalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.db.tenant_schema import tenant_data_schema, tenant_reader_role
from app.core.db.tenant_session import current_tenant_var
from app.core.tenancy import is_multi_tenant
from app.platform.sandbox.schemas import SandboxError, SandboxResult

logger = structlog.stdlib.get_logger(__name__)

DEFAULT_ROW_LIMIT = 1000
DEFAULT_TIMEOUT_MS = 10_000
# Text-form bytes a caller-written query may return. Sized for overlay geometry;
# a row limit and a timeout leave one generated cell free to reach a gigabyte.
DEFAULT_MAX_RESULT_BYTES = 16 * 1024 * 1024

# Columns the byte-bounded wrapper appends after the caller's own.
_BYTE_META_COLUMNS = 3
# The driver decodes each array element into its own Python object plus a list
# slot, about 30-130 bytes on CPython however short the element's text is.
_ARRAY_ELEMENT_BYTES = 64
# Composites, records, multiranges, paths, polygons, JSON and arrays of them nest
# values that cannot be counted without their types, so their text is weighted:
# an element as short as two text bytes ("1,") then costs _ARRAY_ELEMENT_BYTES.
_NESTED_TEXT_WEIGHT = _ARRAY_ELEMENT_BYTES // 2
# record, path, polygon, json and jsonb: reported as scalars, decoded into many
# objects (the engine installs json.loads codecs for both JSON types).
_NESTED_SCALAR_OIDS = (2249, 602, 604, 114, 3802)
# Array types whose elements decode to one object each, so cardinality() counts them.
_FLAT_ARRAY_TYPES_SQL = (
    "SELECT a.oid FROM pg_catalog.pg_type AS a "
    "JOIN pg_catalog.pg_type AS e ON e.oid = a.typelem "
    "WHERE a.oid = ANY($1::oid[]) AND e.typtype IN ('b', 'e') "
    "AND NOT (e.typelem <> 0 AND e.typlen = -1) AND e.oid <> ALL($2::oid[])"
)

# Single-tenant restricted execution role (migration 0007 + init-db.sh).
# Module-level so tests can point it at a nonexistent role to exercise both
# the legacy best-effort fallback and the feat(#565) fail-closed binding.
_SINGLE_TENANT_READER_ROLE = "geolens_reader"


def _is_logical_data_schema(identifier: exp.Identifier) -> bool:
    """True when ``identifier`` folds to the logical ``data`` schema: unquoted
    folds to lowercase, quoted keeps its case, so quoted ``"DATA"`` is not it."""
    name = identifier.name if identifier.quoted else identifier.name.lower()
    return name == "data"


def _logical_data_span(identifier: exp.Identifier, sql: str) -> tuple[int, int]:
    """Source offsets of one logical ``data`` schema qualifier in ``sql``.

    fix(#1892): the slice must spell exactly what sqlglot parsed. An absent or
    shifted offset would move an unrelated span, so it fails closed instead.
    """
    start = identifier.meta.get("start")
    end = identifier.meta.get("end")
    spelling = f'"{identifier.name}"' if identifier.quoted else identifier.name
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or not 0 <= start <= end < len(sql)
        or sql[start : end + 1] != spelling
    ):
        logger.warning(
            "sandbox.schema_span_unusable", start=start, end=end, length=len(sql)
        )
        raise SandboxError("query_failed", "Query failed")
    return start, end


def _rewrite_logical_data_schema(sql: str, physical_schema: str) -> str:
    """Bind validated ``data.*`` references to one physical tenant schema.

    The validator exposes a stable logical ``data`` schema and rejects every
    other real-table schema; multi-tenant storage is per-tenant, so execution
    translates the logical name after validation.

    fix(#1892): only the schema identifier spans of the ORIGINAL text are
    replaced, right to left. Serializing the parsed tree instead re-rendered
    the whole statement, which is why the pgvector cosine operator (sqlglot
    parses ``<=>`` as NullSafeEQ) needed a sentinel swap; every other byte now
    reaches PostgreSQL as the caller wrote it, as it already does in
    single-tenant.

    ``physical_schema`` comes from :func:`tenant_data_schema`, which accepts
    only a normalized UUID-derived identifier in multi-tenant mode.
    """
    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.SqlglotError as exc:
        # execute_safe receives validated SQL in normal operation.  Keep direct
        # callers fail-closed if that contract is accidentally violated (covers
        # both tokenize and parse failures).
        raise SandboxError("invalid_query", "Invalid SQL syntax") from exc

    # fix(#1892): `parse`, not `parse_one`, which reports a second statement as
    # one Block and would rewrite a caller-supplied `a; b` in both halves.
    statements = [statement for statement in statements if statement is not None]
    if len(statements) != 1:
        logger.warning("sandbox.rewrite_multi_statement", count=len(statements))
        raise SandboxError("invalid_query", "Only single statements are allowed")

    spans: set[tuple[int, int]] = set()
    for node in statements[0].walk():
        if not isinstance(node, (exp.Table, exp.Column)):
            continue
        identifier = node.args.get("db")
        if isinstance(identifier, exp.Identifier) and _is_logical_data_schema(
            identifier
        ):
            spans.add(_logical_data_span(identifier, sql))

    replacement = '"' + physical_schema.replace('"', '""') + '"'
    tail = len(sql)
    for start, end in sorted(spans, reverse=True):
        if end >= tail:
            # Overlapping spans would splice into text already replaced.
            logger.warning("sandbox.schema_span_overlap", start=start, end=end)
            raise SandboxError("query_failed", "Query failed")
        sql = sql[:start] + replacement + sql[end + 1 :]
        tail = start
    return sql


def _limited_sql(
    sql: str,
    fetch_limit: int,
    max_result_bytes: int | None,
    token: str,
    weights: dict[int, str] | None = None,
) -> str:
    """Wrap validated SQL in the row cap and, when given, the result-byte cap.

    The byte cap is measured and enforced inside PostgreSQL, so rows past it never
    cross the wire: a running total of each row's estimated size keeps rows while
    the total fits, refuses a first row that alone exceeds it, and reports through
    the trailing ``more`` column that a later row existed but was cut. A row's size
    is its text form plus the ``weights`` of columns that decode to many objects
    (see ``_column_weights``). The row cap sits below the window, so dropped rows
    never extend the scan past ``fetch_limit``. ``token`` is fresh per call so
    neither the meta-column names nor the refusal marker can be matched by a
    caller's own columns or values.
    """
    # The closing paren and LIMIT go on their own line: `--` runs to end of line,
    # so a validated query ending in a line comment would swallow the wrapper.
    limited = f"SELECT * FROM (\n{sql}\n) AS _q LIMIT {fetch_limit}"
    if max_result_bytes is None:
        return limited
    row_bytes, total_bytes = f"_geolens_{token}_row", f"_geolens_{token}_total"
    return (
        f"SELECT * FROM (SELECT _l.*, _s.b AS {row_bytes}, "
        f"pg_catalog.sum(_s.b) OVER _gw AS {total_bytes}, "
        f"pg_catalog.lead(true, 1, false) OVER _gw AS _geolens_{token}_more "
        f"FROM ({limited}) AS _l "
        # `_l.*`, not bare `_l`: a caller's column named _l would shadow the row.
        f"CROSS JOIN LATERAL ({_row_size_sql(weights or {}, token)}) AS _s(b) "
        "WINDOW _gw AS (ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS _w "
        f"WHERE CASE WHEN _w.{total_bytes} <= {int(max_result_bytes)} THEN true "
        f"WHEN _w.{total_bytes} = _w.{row_bytes} "
        f"THEN ('{_too_large_marker(token)} ' || _w.{row_bytes})::int IS NULL "
        "ELSE false END"
    )


def _too_large_marker(token: str) -> str:
    return f"geolens_result_too_large_{token}"


def _row_size_sql(weights: dict[int, str], token: str) -> str:
    """One row's estimated decoded size: its text bytes plus nested-column weights."""
    size = "pg_catalog.octet_length(CAST(_l.* AS text))"
    if not weights:
        return f"SELECT {size}"
    # Positional aliases: a caller's column names may repeat or collide.
    names = [f"_geolens_{token}_{i}" for i in range(max(weights) + 1)]
    terms = [
        f"{_ARRAY_ELEMENT_BYTES}::bigint * {_decoded_objects_sql(f'_a.{names[i]}')}"
        if weight == "elements"
        else f"{_NESTED_TEXT_WEIGHT}::bigint"
        f" * COALESCE(pg_catalog.octet_length(CAST(_a.{names[i]} AS text)), 0)"
        for i, weight in sorted(weights.items())
    ]
    return (
        f"SELECT {size} + {' + '.join(terms)} "
        f"FROM (SELECT _l.*) AS _a({', '.join(names)})"
    )


def _decoded_objects_sql(column: str) -> str:
    """Python objects a flat array decodes to: its elements plus its inner lists.

    Each slot of every dimension but the last decodes to its own list. That
    count is at most (ndims - 1) times the slots of the next-to-last dimension
    (cardinality over the last length): exact for two dimensions and for
    degenerate shapes such as [n, 1, 1, 1, 1, 1].
    """
    elements = f"pg_catalog.cardinality({column})::bigint"
    ndims = f"pg_catalog.array_ndims({column})"
    lists = f"({ndims} - 1) * {elements} / pg_catalog.array_length({column}, {ndims})"
    return f"COALESCE({elements} + {lists}, 0)"


async def _column_weights(
    conn: AsyncConnection, sql: str, binds: Sequence[BindParameter]
) -> dict[int, str] | None:
    """Map result columns that decode to many Python objects to their weighting.

    ``"elements"`` marks an array of flat values, weighted by element count;
    ``"text"`` marks nested values, weighted by text size. The statement is only
    parsed and described, never planned or run. Returns None when describing
    fails, leaving the statement itself to report the error.
    """
    statement = text(sql).bindparams(*binds).compile(dialect=conn.dialect).string
    try:
        async with conn.begin_nested():
            driver = (await conn.get_raw_connection()).driver_connection
            columns = [
                a.type for a in (await driver.prepare(statement)).get_attributes()
            ]
            nested = {
                i: column
                for i, column in enumerate(columns)
                if column.kind not in ("scalar", "range")
                or column.oid in _NESTED_SCALAR_OIDS
            }
            arrays = [c.oid for c in nested.values() if c.kind == "array"]
            flat = set()
            if arrays:
                rows = await driver.fetch(
                    _FLAT_ARRAY_TYPES_SQL, arrays, list(_NESTED_SCALAR_OIDS)
                )
                flat = {row[0] for row in rows}
    except Exception as exc:  # broad: the statement reports its own error
        logger.warning("sandbox.describe_failed", error_type=type(exc).__name__)
        return None
    return {i: "elements" if c.oid in flat else "text" for i, c in nested.items()}


async def _execute_limited(
    conn: AsyncConnection,
    sql: str,
    fetch_limit: int,
    max_result_bytes: int | None,
    token: str,
    binds: Sequence[BindParameter],
):
    """Run ``sql`` under the row cap and, when given, the weighted byte cap."""
    weights: dict[int, str] | None = {}
    if max_result_bytes is not None:
        weights = await _column_weights(
            conn, _limited_sql(sql, fetch_limit, None, token), binds
        )
    result = await conn.execute(
        text(
            _limited_sql(sql, fetch_limit, max_result_bytes, token, weights)
        ).bindparams(*binds)
    )
    if weights is None:
        # The statement ran although it could not be described, so its
        # nested columns went unweighted; refuse rather than return them.
        raise SandboxError("query_failed", "Query failed")
    return result


async def execute_safe(
    db: AsyncSession,
    sql: str,
    *,
    row_limit: int = DEFAULT_ROW_LIMIT,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    concurrency_key: str | None = None,
    require_reader_role: bool = False,
    max_result_bytes: int | None = None,
    binds: Sequence[BindParameter] = (),
) -> SandboxResult:
    """Execute validated SQL inside a READ ONLY transaction with timeout and row cap.

    Uses a dedicated connection from the engine pool (not the caller's session)
    to guarantee transaction isolation: READ ONLY + statement_timeout.

    Args:
        db: Async database session (used only for engine reference).
        sql: Pre-validated SQL string (must be a single SELECT).
        row_limit: Maximum rows to return (default 1000).
        timeout_ms: Statement timeout in milliseconds (default 10000).
        concurrency_key: Stable caller key for a cross-worker, fail-fast query lock.
        require_reader_role: when True, the single-tenant ``SET LOCAL ROLE``
            binding fails CLOSED — a query that cannot be bound to the
            restricted reader role raises a sanitized SandboxError instead
            of running with the application login's (superuser) privileges.
            Default False preserves the legacy best-effort fallback for AI
            chat. Multi-tenant binding is unconditionally fail-closed.
        max_result_bytes: when set, cap the result's text-form size in the
            database. Rows past the cap are cut and ``truncated`` is set; a
            first row that alone exceeds it raises ``result_too_large``.
        binds: bind parameters ``sql`` names, for server-compiled values
            such as a layer filter's literals.

    Returns:
        SandboxResult with rows, columns, row_count, and truncated flag.

    Raises:
        SandboxError: On timeout, read-only violation, oversized result, or any
            DB error.
    """
    multi_tenant = is_multi_tenant()
    tenant_id = current_tenant_var.get() if multi_tenant else None
    if multi_tenant:
        if tenant_id is None:
            # An unscoped query must never fall back to the global reader or
            # the legacy shared data schema. RLS is the final backstop, but
            # fail before acquiring a connection so the error is deterministic.
            raise SandboxError("query_failed", "Query failed")
        sql = _rewrite_logical_data_schema(sql, tenant_data_schema(tenant_id))

    fetch_limit = row_limit + 1
    # Hex, so it is a valid identifier fragment in the wrapper's column names.
    token = secrets.token_hex(6)

    # Use the engine from the database module (patched in tests)
    import app.core.db as db_module

    try:
        async with db_module.engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                if concurrency_key is not None:
                    lock_result = await conn.execute(
                        text(
                            "SELECT pg_try_advisory_xact_lock("
                            "hashtextextended(:concurrency_key, 0))"
                        ),
                        {"concurrency_key": f"geolens:ai-sql:{concurrency_key}"},
                    )
                    if not lock_result.scalar_one():
                        raise SandboxError(
                            "query_busy",
                            "Another data query is already running for this user",
                        )
                # Defense-in-depth: use the restricted reader role if available.
                # Multi-tenant uses the per-tenant reader role (per-tenant
                # schema access only); single-tenant uses "geolens_reader"
                # (guaranteed by migration 0007 + init-db.sh, unlike
                # "geolens_readonly" which lives only in a migration that may
                # be squashed). Multi-tenant never falls back to a global
                # role. Role name derives from validated-UUID
                # current_tenant_var, so it's safe to interpolate.
                if multi_tenant:
                    # tenant_reader_role validates the UUID before building
                    # the identifier.
                    _role = tenant_reader_role(tenant_id)
                    try:
                        await conn.execute(text(f"SET LOCAL ROLE {_role}"))
                    except Exception as exc:  # broad: role binding must fail closed
                        # Falling back to the app role could expose the
                        # shared legacy schema or another tenant's schema;
                        # this binding is mandatory, not best effort.
                        logger.error(
                            "sandbox.tenant_role_bind_failed",
                            tenant_id=tenant_id,
                            role=_role,
                            error_type=type(exc).__name__,
                        )
                        raise SandboxError("query_failed", "Query failed") from exc
                else:
                    _role = _SINGLE_TENANT_READER_ROLE
                    # Legacy compatibility fallback for deployments upgraded
                    # from before this role existed, unless the caller
                    # requires it (the raw-SQL endpoint must never fall
                    # back to superuser).
                    try:
                        await conn.execute(text("SAVEPOINT _role_check"))
                        await conn.execute(text(f"SET LOCAL ROLE {_role}"))
                    except (
                        Exception
                    ) as exc:  # broad: single-tenant legacy role may be absent
                        await conn.execute(text("ROLLBACK TO SAVEPOINT _role_check"))
                        if require_reader_role:
                            logger.error(
                                "sandbox.reader_role_bind_failed",
                                role=_role,
                                error_type=type(exc).__name__,
                            )
                            raise SandboxError("query_failed", "Query failed") from exc
                    finally:
                        try:
                            await conn.execute(text("RELEASE SAVEPOINT _role_check"))
                        except Exception:  # broad: best-effort savepoint cleanup
                            pass
                await conn.execute(
                    text(f"SET LOCAL statement_timeout = '{timeout_ms}'")
                )
                result = await _execute_limited(
                    conn, sql, fetch_limit, max_result_bytes, token, binds
                )
                columns = list(result.keys())
                all_rows = result.fetchall()
    except SandboxError:
        raise
    except Exception as exc:  # broad: varied DB errors; classify in handler
        _handle_execution_error(exc, sql, token)

    # Convert rows to list-of-lists
    rows = [list(row) for row in all_rows]
    truncated = len(rows) > row_limit
    if truncated:
        rows = rows[:row_limit]
    if max_result_bytes is not None:
        columns = columns[:-_BYTE_META_COLUMNS]
        truncated = truncated or bool(rows and rows[-1][-1])
        rows = [row[:-_BYTE_META_COLUMNS] for row in rows]

    return SandboxResult(
        rows=rows,
        columns=columns,
        row_count=len(rows),
        truncated=truncated,
    )


def _handle_execution_error(exc: Exception, sql: str, token: str | None = None) -> None:
    """Classify and re-raise DB exceptions as SandboxError.

    Always logs full details server-side at WARNING level.
    """
    exc_str = str(exc).lower()
    exc_type = type(exc).__name__

    logger.warning(
        "sandbox.execution_error",
        sql=sql,
        error=str(exc),
        error_type=exc_type,
    )

    # The driver error alone: the wrapped exception's text also quotes the
    # statement, which carries the marker on every bounded query.
    if token is not None and _too_large_marker(token) in str(getattr(exc, "orig", "")):
        raise SandboxError(
            "result_too_large", "Query result is too large to return"
        ) from exc

    # Timeout detection (asyncpg.exceptions.QueryCanceledError or message match)
    if "querycancelederror" in exc_type.lower() or "statement timeout" in exc_str:
        raise SandboxError("query_timeout", "Query timed out") from exc

    # Read-only violation (defense-in-depth, validator should prevent this)
    if (
        "readonlysqltransactionerror" in exc_type.lower()
        or "read-only" in exc_str
        or "read only" in exc_str
    ):
        raise SandboxError("query_failed", "Query failed") from exc

    # Data-driven failures: SQLAlchemy maps SQLSTATE class 22 (data
    # exception) to DataError and XX-class (GEOS/PostGIS topology errors) to
    # InternalError. Distinct category lets analysis callers report these
    # as 4xx without reclassifying infra failures as user error.
    if isinstance(exc, (DataError, InternalError)):
        raise SandboxError(
            "query_data_error", "The query failed while processing this data"
        ) from exc

    # All other DB errors
    raise SandboxError("query_failed", "Query failed") from exc
