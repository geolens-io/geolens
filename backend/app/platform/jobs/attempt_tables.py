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
table whose attempt no job row names is left alone, so the retention purge
keeps a row while a table carries its attempt. The pass declines in
multi-tenant mode without a tenant context, and is bounded; each pass starts
after the last name the previous one reached, so tables that cannot be
dropped never hold the others back.
"""

from __future__ import annotations

import re
import uuid

import structlog
from sqlalchemy import false, text

from app.platform.jobs.heartbeat import ATTEMPT_STAGING_NAME_PATTERN

log = structlog.get_logger()

# Only the names table generation can produce, so a hand-made table that
# happens to end the same way, or one needing quotes, is never a candidate.
_OWNED_NAME_PATTERN = rf"^[a-z0-9_]+{ATTEMPT_STAGING_NAME_PATTERN}"
_OWNED_NAME_RE = re.compile(_OWNED_NAME_PATTERN)

_TABLES_PER_PASS = 100

# The last name each schema's previous pass reached, per process.
_cursors: dict[str, str] = {}

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
    ORDER BY c.relname <= :after, c.relname
    LIMIT :limit
    """
)

# The same name test as the candidate query, against the job row's attempt.
_OWNS_NO_STAGING_TABLE_SQL = """
NOT EXISTS (
    SELECT 1 FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :staging_schema
      AND c.relkind = 'r'
      AND c.relname ~ :staging_pattern
      AND right(c.relname, 32) = replace(ingest_jobs.attempt_id::text, '-', '')
)
"""

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


def _current_schema() -> str:
    from app.core.db.tenant_schema import tenant_data_schema
    from app.core.db.tenant_session import current_tenant_var
    from app.core.tenancy import is_multi_tenant

    return tenant_data_schema(current_tenant_var.get() if is_multi_tenant() else None)


def owns_no_staging_table():
    """Predicate: no staging table in the tenant's schema carries this job row's attempt.

    False for every row when the schema can't be resolved.
    """
    try:
        schema = _current_schema()
    except ValueError:
        return false()
    return text(_OWNS_NO_STAGING_TABLE_SQL).bindparams(
        staging_schema=schema, staging_pattern=_OWNED_NAME_PATTERN
    )


async def reap_settled_attempt_tables() -> int:
    """Drop the staging tables of settled attempts in the current tenant's schema.

    Call after the commit that settled the jobs. Returns how many were
    dropped; a table that could not be dropped waits for the next pass.
    """
    from app.core.db import async_session

    try:
        schema = _current_schema()
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
                        "after": _cursors.get(schema, ""),
                        "limit": _TABLES_PER_PASS,
                    },
                )
            ).scalars()
            names = [name for name in found if _OWNED_NAME_RE.search(name)]
    except Exception:  # broad: an unreadable catalog must not license a drop
        log.warning("Skipped attempt staging table reap, candidate query failed")
        return 0
    if names:
        _cursors[schema] = names[-1]

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
