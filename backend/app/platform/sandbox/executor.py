"""Safe SQL execution with defense-in-depth protections.

Defense layer 2: Database-enforced READ ONLY transaction, PostgreSQL
statement_timeout, and row limit truncation. All errors are sanitized
for end users while full details are logged server-side.
"""

from __future__ import annotations

import structlog
import sqlglot
from sqlglot import exp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.tenant_schema import tenant_data_schema, tenant_reader_role
from app.core.db.tenant_session import current_tenant_var
from app.core.tenancy import is_multi_tenant
from app.platform.sandbox.schemas import SandboxError, SandboxResult

logger = structlog.stdlib.get_logger(__name__)

DEFAULT_ROW_LIMIT = 1000
DEFAULT_TIMEOUT_MS = 10_000


def _rewrite_logical_data_schema(sql: str, physical_schema: str) -> str:
    """Rewrite validated ``data.*`` references to one physical tenant schema.

    The validator intentionally exposes a stable logical ``data`` schema to the
    LLM and rejects every other real-table schema.  Multi-tenant storage uses a
    per-tenant physical schema, so execution must translate that logical name
    after validation.  Rewriting the parsed AST avoids string-replacement bugs
    in literals, comments, aliases, and identifiers that merely contain the word
    ``data``.

    ``physical_schema`` is produced by :func:`tenant_data_schema`, which accepts
    only a normalized UUID-derived identifier in multi-tenant mode.
    """
    try:
        statement = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError as exc:
        # execute_safe receives validated SQL in normal operation.  Keep direct
        # callers fail-closed if that contract is accidentally violated.
        raise SandboxError("invalid_query", "Invalid SQL syntax") from exc

    for table in statement.find_all(exp.Table):
        if table.db == "data":
            table.set("db", exp.to_identifier(physical_schema, quoted=True))

    for column in statement.find_all(exp.Column):
        if column.db == "data":
            column.set("db", exp.to_identifier(physical_schema, quoted=True))

    return statement.sql(dialect="postgres")


async def execute_safe(
    db: AsyncSession,
    sql: str,
    *,
    row_limit: int = DEFAULT_ROW_LIMIT,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    concurrency_key: str | None = None,
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

    Returns:
        SandboxResult with rows, columns, row_count, and truncated flag.

    Raises:
        SandboxError: On timeout, read-only violation, or any DB error.
    """
    multi_tenant = is_multi_tenant()
    tenant_id = current_tenant_var.get() if multi_tenant else None
    if multi_tenant:
        if tenant_id is None:
            # An unscoped query must never fall back to the global reader or the
            # legacy shared data schema.  RLS is the final backstop, but fail
            # before acquiring a connection so the error is deterministic.
            raise SandboxError("query_failed", "Query failed")
        sql = _rewrite_logical_data_schema(sql, tenant_data_schema(tenant_id))

    fetch_limit = row_limit + 1
    limited_sql = f"SELECT * FROM ({sql}) AS _q LIMIT {fetch_limit}"

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
                # DP-02 (Phase 1209-03): in multi_tenant, use the per-tenant reader
                # role so the sandbox SQL runs with only per-tenant schema access.
                # CR-04 (Phase 1209): single_tenant uses "geolens_reader"
                # (guaranteed by migration 0007 and init-db.sh) rather than
                # "geolens_readonly" (only in migration 0001_baseline, which may
                # be squashed). Multi-tenant never falls back to a global role.
                # Role name derives from validated-UUID current_tenant_var — safe
                # to interpolate (T-1209-14).
                if multi_tenant:
                    # tenant_id was required above and tenant_reader_role validates
                    # the UUID before constructing this identifier.
                    _role = tenant_reader_role(tenant_id)
                    try:
                        await conn.execute(text(f"SET LOCAL ROLE {_role}"))
                    except Exception as exc:  # broad: role binding must fail closed
                        # Falling back to the application role here can expose the
                        # shared legacy schema or any other tenant schema reachable
                        # by that broader login.  Multi-tenant role binding is a
                        # mandatory isolation control, not best effort.
                        logger.error(
                            "sandbox.tenant_role_bind_failed",
                            tenant_id=tenant_id,
                            role=_role,
                            error_type=type(exc).__name__,
                        )
                        raise SandboxError("query_failed", "Query failed") from exc
                else:
                    _role = "geolens_reader"
                    # Preserve the legacy single-tenant compatibility fallback for
                    # deployments upgraded from versions that predate this role.
                    try:
                        await conn.execute(text("SAVEPOINT _role_check"))
                        await conn.execute(text(f"SET LOCAL ROLE {_role}"))
                    except Exception:  # broad: single-tenant legacy role may be absent
                        await conn.execute(text("ROLLBACK TO SAVEPOINT _role_check"))
                    finally:
                        try:
                            await conn.execute(text("RELEASE SAVEPOINT _role_check"))
                        except Exception:  # broad: best-effort savepoint cleanup
                            pass
                await conn.execute(
                    text(f"SET LOCAL statement_timeout = '{timeout_ms}'")
                )
                result = await conn.execute(text(limited_sql))
                columns = list(result.keys())
                all_rows = result.fetchall()
    except SandboxError:
        raise
    except Exception as exc:  # broad: SQL execution can throw asyncpg/sqlalchemy errors of varied types; classify in handler
        _handle_execution_error(exc, sql)

    # Convert rows to list-of-lists
    rows = [list(row) for row in all_rows]
    truncated = len(rows) > row_limit
    if truncated:
        rows = rows[:row_limit]

    return SandboxResult(
        rows=rows,
        columns=columns,
        row_count=len(rows),
        truncated=truncated,
    )


def _handle_execution_error(exc: Exception, sql: str) -> None:
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

    # All other DB errors
    raise SandboxError("query_failed", "Query failed") from exc
