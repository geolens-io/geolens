"""Drop the staging tables that settled ingest attempts left behind.

An import or replacement copies its candidate into
``<table>_staging_<attempt hex>`` and drops it in a ``finally`` that a killed
worker never runs. This pass starts from the tables in the tenant's data
schema and drops one only when every one of these holds, each read again,
under the job row's lock, right before the drop:

- Its name is exactly what ``attempt_scoped_staging_table`` produces.
- The job row whose attempt the name carries is ``failed`` or ``cancelled``,
  so that attempt can no longer publish, and nothing holds the row.
- No dataset uses the name as its table.

A plain DROP, never CASCADE, so a table something else depends on stays. A
table whose attempt no job row names is left alone. The pass declines in
multi-tenant mode without a tenant context, and is bounded.
"""

from __future__ import annotations

import re
import uuid

import structlog
from sqlalchemy import text

from app.platform.jobs.heartbeat import ATTEMPT_STAGING_NAME_PATTERN

log = structlog.get_logger()

# Only the names table generation can produce, so a hand-made table that
# happens to end the same way, or one needing quotes, is never a candidate.
_OWNED_NAME_PATTERN = rf"^[a-z0-9_]+{ATTEMPT_STAGING_NAME_PATTERN}"
_OWNED_NAME_RE = re.compile(_OWNED_NAME_PATTERN)

_TABLES_PER_PASS = 100

# The CASE keeps the cast off any name the pattern does not match. The
# LIMIT counts only tables a settled attempt owns, so tables nothing proves
# an owner for can never fill the batch.
_CANDIDATES_SQL = text(
    """
    SELECT c.relname
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema
      AND c.relkind = 'r'
      AND c.relname ~ :pattern
      AND EXISTS (
          SELECT 1 FROM catalog.ingest_jobs j
          WHERE j.attempt_id = CASE WHEN c.relname ~ :pattern
                THEN CAST(right(c.relname, 32) AS uuid) END
            AND j.status IN ('failed', 'cancelled')
      )
      AND NOT EXISTS (
          SELECT 1 FROM catalog.datasets d WHERE d.table_name = c.relname
      )
    ORDER BY c.relname
    LIMIT :limit
    """
)

# The row lock keeps a retry or a fan-out restore from moving the job while
# the table goes; a row a task or another pass holds is left for later.
_HOLD_SETTLED_JOB_SQL = text(
    """
    SELECT 1 FROM catalog.ingest_jobs
    WHERE attempt_id = :attempt AND status IN ('failed', 'cancelled')
    FOR UPDATE SKIP LOCKED
    """
)

_CLAIMED_SQL = text("SELECT 1 FROM catalog.datasets WHERE table_name = :name LIMIT 1")


def _attempt_of(table_name: str) -> uuid.UUID:
    return uuid.UUID(hex=table_name[-32:])


async def reap_settled_attempt_tables() -> int:
    """Drop the staging tables of settled attempts in the current tenant's schema.

    Call after the commit that settled the jobs. Returns how many were
    dropped; a table that could not be dropped waits for the next pass.
    """
    from app.core.db import async_session
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    try:
        schema = tenant_data_schema(
            current_tenant_var.get() if is_multi_tenant() else None
        )
    except ValueError:
        return 0
    try:
        async with async_session() as session:
            found = (
                await session.execute(
                    _CANDIDATES_SQL,
                    {
                        "schema": schema,
                        "pattern": _OWNED_NAME_PATTERN,
                        "limit": _TABLES_PER_PASS,
                    },
                )
            ).scalars()
            names = [name for name in found if _OWNED_NAME_RE.search(name)]
    except Exception:  # broad: an unreadable catalog must not license a drop
        log.warning("Skipped attempt staging table reap, candidate query failed")
        return 0

    dropped = 0
    for name in names:
        if await _drop_if_settled(schema, name, _attempt_of(name)):
            dropped += 1
    if dropped:
        log.info("Dropped settled attempt staging tables", count=dropped)
    return dropped


async def _drop_if_settled(schema: str, name: str, attempt: uuid.UUID) -> bool:
    """Drop ``name`` in one transaction that holds its settled job row."""
    from app.core.db import async_session

    try:
        async with async_session() as session:
            await session.execute(text("SET LOCAL lock_timeout = '2s'"))
            held = await session.scalar(_HOLD_SETTLED_JOB_SQL, {"attempt": attempt})
            if held is None or await session.scalar(_CLAIMED_SQL, {"name": name}):
                return False
            await session.execute(
                # codeql[py/sql-injection]
                text(f'DROP TABLE IF EXISTS "{schema}"."{name}"')
            )
            await session.commit()
    except Exception:  # broad: the table waits for the next pass
        log.warning(
            "Failed to drop a settled attempt staging table", attempt=str(attempt)
        )
        return False
    return True
