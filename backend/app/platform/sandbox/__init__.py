"""SQL sandbox module.

Provides safe SQL validation, RBAC table access control, and execution
for LLM-generated queries. The public API is validate_and_execute().

Usage:
    from app.platform.sandbox import validate_and_execute, SandboxResult, SandboxError

    result = await validate_and_execute(sql, db, user)
"""

from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.sandbox.executor import DEFAULT_TIMEOUT_MS, execute_safe
from app.platform.sandbox.schemas import SandboxError, SandboxResult
from app.platform.sandbox.validator import (
    build_table_allowlist,
    check_table_access,
    validate_sql,
)

logger = structlog.stdlib.get_logger(__name__)

__all__ = ["validate_and_execute", "SandboxResult", "SandboxError"]


async def validate_and_execute(
    sql: str,
    db: AsyncSession,
    user: Identity | None,
    *,
    row_limit: int = 1000,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    restrict_tables: frozenset[str] | None = None,
    max_table_repeats: int | None = None,
    require_reader_role: bool = False,
) -> SandboxResult:
    """Validate and safely execute a SQL query.

    Pipeline:
        1. Parse and validate SQL (single SELECT only)
        2. Build RBAC table allowlist for user
        3. Check all referenced tables are accessible
        4. Execute in READ ONLY transaction with timeout and row limit

    Args:
        sql: Raw SQL string from user/LLM.
        db: Async database session.
        user: Current user (None for anonymous).
        row_limit: Maximum rows to return (default 1000).
        timeout_ms: Statement timeout in milliseconds, applied as SET LOCAL
            statement_timeout on the execution connection (default 10000).
            Callers that need a tighter budget than the shared default — a
            synchronous request path, say — pass a smaller value.
        restrict_tables: Optional surface-level scope: when set, the effective
            allowlist is the INTERSECTION of the user's RBAC allowlist with
            this set — it can only narrow access, never widen it. Used by
            dataset-scoped chat (PR #531 review) so generated SQL cannot reach
            other tables the user happens to be able to see.
        max_table_repeats: feat(#565): when set, reject any statement that
            references the same table (or CTE name) more than this many times.
            This is the self-join cost bound for the raw-SQL endpoint —
            ``... FROM data.foo a CROSS JOIN data.foo b CROSS JOIN data.foo c``
            passes every function/table check while its work grows with the
            table's own size to the power of the repetition count, and the
            outer LIMIT bounds rows returned, not work performed. Left None
            (no cap) for AI chat so its behavior does not silently change.
            EXPLAIN-based cost rejection is the finer-grained future
            replacement discussed in #565; a repetition cap is the bound that
            needs no planner round-trip.
        require_reader_role: feat(#565): fail closed if the restricted reader
            role cannot be bound in single-tenant mode (see execute_safe).

    Returns:
        SandboxResult with query results.

    Raises:
        SandboxError: On validation failure, access denial, timeout, or execution error.
    """
    try:
        # Phase 1: Validate SQL structure
        validated = validate_sql(sql)
        real_tables = {
            (schema, name)
            for schema, name in validated.tables
            if schema or name not in validated.cte_names
        }
        if not real_tables:
            raise SandboxError(
                "invalid_query", "Query must reference an accessible dataset"
            )

        # feat(#565): self-join repetition cap (see the kwarg docs above).
        # Checked before the RBAC query so a rejected statement costs no DB
        # round-trip. The message is sanitized — no table names echo back.
        if max_table_repeats is not None:
            repeated = max(validated.table_counts.values(), default=0)
            if repeated > max_table_repeats:
                logger.info(
                    "sandbox.table_repetition_cap",
                    sql=sql,
                    repeats=repeated,
                    cap=max_table_repeats,
                )
                raise SandboxError(
                    "invalid_query",
                    "Query references the same table too many times",
                )

        # Phase 2: Build RBAC allowlist
        allowed_tables = await build_table_allowlist(db, user)
        if restrict_tables is not None:
            allowed_tables = allowed_tables & restrict_tables

        # Phase 3: Check table access
        check_table_access(validated.tables, allowed_tables, validated.cte_names)

        # Phase 4: Execute safely
        concurrency_key = str(user.id) if user is not None else "anonymous"
        return await execute_safe(
            db,
            validated.sql,
            row_limit=row_limit,
            timeout_ms=timeout_ms,
            concurrency_key=concurrency_key,
            require_reader_role=require_reader_role,
        )

    except SandboxError:
        # Already a sandbox error -- re-raise as-is
        raise

    except Exception as exc:  # broad: sandbox boundary — sqlparser/validator/executor can throw varied types; map to SandboxError
        # Unexpected error -- log full details and raise generic
        logger.warning(
            "sandbox.unexpected_error",
            sql=sql,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise SandboxError("query_failed", "Query failed") from exc
