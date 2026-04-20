"""Safe SQL execution with defense-in-depth protections.

Defense layer 2: Database-enforced READ ONLY transaction, PostgreSQL
statement_timeout, and row limit truncation. All errors are sanitized
for end users while full details are logged server-side.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.sandbox.schemas import SandboxError, SandboxResult

logger = structlog.stdlib.get_logger(__name__)

DEFAULT_ROW_LIMIT = 1000
DEFAULT_TIMEOUT_MS = 30_000


async def execute_safe(
    db: AsyncSession,
    sql: str,
    *,
    row_limit: int = DEFAULT_ROW_LIMIT,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> SandboxResult:
    """Execute validated SQL inside a READ ONLY transaction with timeout and row cap.

    Uses a dedicated connection from the engine pool (not the caller's session)
    to guarantee transaction isolation: READ ONLY + statement_timeout.

    Args:
        db: Async database session (used only for engine reference).
        sql: Pre-validated SQL string (must be a single SELECT).
        row_limit: Maximum rows to return (default 1000).
        timeout_ms: Statement timeout in milliseconds (default 30000).

    Returns:
        SandboxResult with rows, columns, row_count, and truncated flag.

    Raises:
        SandboxError: On timeout, read-only violation, or any DB error.
    """
    fetch_limit = row_limit + 1
    limited_sql = f"SELECT * FROM ({sql}) AS _q LIMIT {fetch_limit}"

    # Use the engine from the database module (patched in tests)
    import app.core.db as db_module

    try:
        async with db_module.engine.connect() as conn:
            async with conn.begin():
                await conn.execute(text("SET TRANSACTION READ ONLY"))
                # Defense-in-depth: use the restricted readonly role if available.
                # Wrapped in a savepoint so a missing role doesn't abort the txn.
                try:
                    await conn.execute(text("SAVEPOINT _role_check"))
                    await conn.execute(text("SET LOCAL ROLE geolens_readonly"))
                except Exception:
                    await conn.execute(text("ROLLBACK TO SAVEPOINT _role_check"))
                finally:
                    try:
                        await conn.execute(text("RELEASE SAVEPOINT _role_check"))
                    except Exception:
                        pass
                await conn.execute(
                    text(f"SET LOCAL statement_timeout = '{timeout_ms}'")
                )
                result = await conn.execute(text(limited_sql))
                columns = list(result.keys())
                all_rows = result.fetchall()
    except Exception as exc:
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
