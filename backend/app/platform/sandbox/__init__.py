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

from app.modules.auth.models import User
from app.platform.sandbox.executor import execute_safe
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
    user: User | None,
    *,
    row_limit: int = 1000,
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

    Returns:
        SandboxResult with query results.

    Raises:
        SandboxError: On validation failure, access denial, timeout, or execution error.
    """
    try:
        # Phase 1: Validate SQL structure
        validated = validate_sql(sql)

        # Phase 2: Build RBAC allowlist
        allowed_tables = await build_table_allowlist(db, user)

        # Phase 3: Check table access
        check_table_access(validated.tables, allowed_tables, validated.cte_names)

        # Phase 4: Execute safely
        return await execute_safe(db, validated.sql, row_limit=row_limit)

    except SandboxError:
        # Already a sandbox error -- re-raise as-is
        raise

    except Exception as exc:
        # Unexpected error -- log full details and raise generic
        logger.warning(
            "sandbox.unexpected_error",
            sql=sql,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise SandboxError("query_failed", "Query failed") from exc
