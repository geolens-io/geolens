"""SQL sandbox module.

Provides safe SQL validation, RBAC table access control, and execution
for LLM-generated queries. The public API is validate_and_execute().

Usage:
    from app.platform.sandbox import validate_and_execute, SandboxResult, SandboxError

    result = await validate_and_execute(sql, db, user)
"""

from __future__ import annotations

import asyncio
import contextlib

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.sandbox.executor import DEFAULT_TIMEOUT_MS, execute_safe
from app.platform.sandbox.schemas import SandboxError, SandboxResult
from app.platform.sandbox.validator import (
    _folded_identifier as folded_identifier,
    build_table_allowlist,
    check_table_access,
    validate_sql,
)

logger = structlog.stdlib.get_logger(__name__)

__all__ = ["validate_and_execute", "SandboxResult", "SandboxError", "folded_identifier"]


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
    release_session: bool = False,
    capacity_semaphore: asyncio.Semaphore | None = None,
    extra_blocked_functions: frozenset[str] | None = None,
    max_values_rows: int | None = None,
    max_output_columns: int | None = None,
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
        max_table_repeats: feat(#565): when set, reject any statement whose
            transitive self-join FAN-OUT exceeds this — the largest number of
            times one base table is multiplied into the worst-case cardinality,
            computed through the CTE dependency graph (fix(#565 codex P1 r3)).
            This is the self-join cost bound for the raw-SQL endpoint:
            ``... FROM data.foo a CROSS JOIN data.foo b CROSS JOIN data.foo c``
            passes every function/table check while its work grows with the
            table's own size to the power of the fan-out, and the outer LIMIT
            bounds rows returned, not work performed. Costing the graph (not
            per-name reference counts) catches a CTE chain that keeps every
            counter at the cap while multiplying one table far past it. Left
            None (no cap) for AI chat so its behavior does not silently change.
            EXPLAIN-based cost rejection is the finer-grained future
            replacement discussed in #565; a static fan-out bound needs no
            planner round-trip.
        require_reader_role: feat(#565): fail closed if the restricted reader
            role cannot be bound in single-tenant mode (see execute_safe).
        release_session: fix(#565 codex P1 r11): close the caller's request
            session AFTER the RBAC allowlist query and BEFORE execute_safe, so
            its pooled connection is returned while the sandbox query runs on
            its own connection. Without this each in-flight query holds two
            pool slots; with the default 10+3 pool a handful of distinct users
            exhaust it and unrelated endpoints block on the pool timeout. Only
            safe when the caller reads nothing from ``db`` afterwards (the
            raw-SQL endpoint does not; AI chat does, so it leaves this False).
        capacity_semaphore: fix(#565 codex P1 r11): a GLOBAL fail-fast bound on
            concurrent sandbox executions, on top of the per-user advisory lock
            (which only stops ONE user stacking queries, not N distinct users
            each holding a connection). If it is already at capacity the query
            is refused with ``query_at_capacity`` rather than queued — the
            client is holding a request open, so a fast refusal beats a slow
            one. Mirrors the analysis-preview ``_preview_slots`` pattern.

    Returns:
        SandboxResult with query results.

    Raises:
        SandboxError: On validation failure, access denial, timeout, or execution error.
    """
    try:
        # Phase 1: Validate SQL structure
        validated = validate_sql(
            sql,
            extra_blocked_functions=extra_blocked_functions,
            max_values_rows=max_values_rows,
            max_output_columns=max_output_columns,
        )
        real_tables = {
            (schema, name)
            for schema, name in validated.tables
            if schema or name not in validated.cte_names
        }
        if not real_tables:
            raise SandboxError(
                "invalid_query", "Query must reference an accessible dataset"
            )

        # feat(#565): self-join fan-out cap (see the kwarg docs above).
        # Checked before the RBAC query so a rejected statement costs no DB
        # round-trip. The message is sanitized — no table names echo back.
        if (
            max_table_repeats is not None
            and validated.max_table_fanout > max_table_repeats
        ):
            logger.info(
                "sandbox.table_fanout_cap",
                sql=sql,
                fanout=validated.max_table_fanout,
                cap=max_table_repeats,
            )
            raise SandboxError(
                "invalid_query",
                "Query references the same table too many times",
            )

        # fix(#565 codex P1 r11 / P2 r23): a global fail-fast capacity bound.
        # `.locked()` then `async with` is atomic — no await between them, and
        # acquiring a free semaphore does not yield — so this is a real
        # check-then-act only in appearance. At capacity, refuse fast rather
        # than queue. Acquired BEFORE phase 2 (r23): the RBAC allowlist query
        # is itself pooled DB work, so N concurrent calls from one user could
        # all run it and drain the pool before either this bound or the
        # per-user advisory lock rejected the excess. Holding the slot across
        # the whole DB-backed pipeline makes the advertised fail-fast real.
        # SQL validation and the fan-out cap above are CPU-only (no pool), so
        # a malformed query is still rejected without consuming a slot.
        if capacity_semaphore is not None and capacity_semaphore.locked():
            raise SandboxError(
                "query_at_capacity",
                "The server is running its maximum number of queries. "
                "Try again in a moment.",
            )

        concurrency_key = str(user.id) if user is not None else "anonymous"
        async with capacity_semaphore or contextlib.nullcontext():
            # Phase 2: Build RBAC allowlist
            allowed_tables = await build_table_allowlist(db, user)
            if restrict_tables is not None:
                allowed_tables = allowed_tables & restrict_tables

            # Phase 3: Check table access. validated.tables already excludes
            # lexically in-scope CTE references (fix(#565 codex P1)), so every
            # remaining reference must be an accessible data.* table — pass no
            # CTE skip set, or a flat name match would re-admit an out-of-scope
            # name (e.g. pg_user) that a same-named inner CTE happens to define.
            check_table_access(validated.tables, allowed_tables, cte_names=set())

            # fix(#565 codex P1 r11): return the request session's pooled
            # connection before the sandbox opens its own, so an in-flight
            # query holds one pool slot, not two. Done after the RBAC query
            # (which needs this session) and only when the caller opted in.
            # ``close()`` rather than ``rollback()``: rollback ends the
            # transaction but keeps the connection associated with the session,
            # and execute_safe reusing that same pooled connection for its
            # advisory-lock transaction then fails (a MissingGreenlet under the
            # async pool); close cleanly returns it. The request handler reads
            # nothing from ``db`` afterwards, and the dependency's own close
            # becomes a no-op.
            if release_session:
                await db.close()

            # Phase 4: Execute safely
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
