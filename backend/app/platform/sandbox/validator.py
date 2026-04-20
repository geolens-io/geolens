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

from app.modules.auth.models import User
from app.modules.auth.visibility import apply_visibility_filter, get_user_roles
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant, Record
from app.platform.sandbox.schemas import SandboxError, ValidatedQuery

logger = structlog.stdlib.get_logger(__name__)

# Functions blocked in LLM-generated SQL for defense-in-depth.
# READ ONLY transactions prevent most damage, but these can still
# leak server metadata or waste connections.
_BLOCKED_FUNCTIONS: set[str] = {
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
    # Server info disclosure
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

    # Check for blocked function calls (single AST walk — Anonymous is a Func subclass)
    for func in stmt.find_all(exp.Func):
        if isinstance(func, exp.Anonymous):
            fn_name = func.name.lower() if hasattr(func, "name") else ""
        else:
            fn_name = func.sql_name().lower() if hasattr(func, "sql_name") else ""
        if fn_name in _BLOCKED_FUNCTIONS:
            logger.info("sandbox.blocked_function", sql=sql, function=fn_name)
            raise SandboxError("invalid_query", "Query uses a disallowed function")

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


async def build_table_allowlist(db: AsyncSession, user: User | None) -> set[str]:
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
