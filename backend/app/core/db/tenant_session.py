"""Tenant session GUC plumbing (ISO-01, Phase 1208-01).

Provides ``current_tenant_var``, a ContextVar carrying the active tenant id
across a request or worker job; a SQLAlchemy engine-level ``begin`` hook that
issues ``SELECT set_config('app.current_tenant', :tid, true)``; and statement
hooks binding tenant-schema reads/writes to SET-only per-tenant roles. Active
only in ``multi_tenant`` mode — in ``single_tenant`` (default) the hook
returns after the first ``is_multi_tenant()`` check, a byte-identical no-op
required by Plan 05.

``true`` as the third ``set_config`` arg makes it transaction-local, so it
clears automatically and never bleeds across transactions on a reused
connection. The tenant id is always a bound parameter, never f-string
interpolated (T-1208-01).

``current_tenant_var`` is set by two callers: ``TenantContextMiddleware``
(request plane, resets in a finally block, T-1208-03) and
``tenant_job_context`` (worker plane, for a Procrastinate job's duration).
Both share this hook, so ``get_db`` sessions and the bare ``async_session``
both pick up the GUC.

The engine-level ``"begin"`` event (not Session-level ``after_begin``) is used
because it covers every session type — get_db, raw async_session, and
AsyncConnection.begin() — and hands the listener a ``Connection``, so
``conn.execute()`` is safe with no async plumbing.
"""

from __future__ import annotations

import functools
import re
import uuid
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Generator, TypeVar

import structlog
from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = structlog.stdlib.get_logger(__name__)

#: Active tenant id for the current asyncio task/thread; ``None`` means no-op.
current_tenant_var: ContextVar[str | None] = ContextVar("current_tenant", default=None)

# Prevents double-registration of the listener.
_HOOK_ATTR = "_geolens_tenant_guc_installed"

# Matches only a canonical-UUID tenant schema, not a loose data_t_* prefix, so
# the statement binder can never turn attacker-controlled text into a role name.
_TENANT_SCHEMA_RE = re.compile(
    r"(?<![a-z0-9_])data_t_[0-9a-f]{8}_[0-9a-f]{4}_[0-9a-f]{4}_"
    r"[0-9a-f]{4}_[0-9a-f]{12}(?![a-z0-9_])",
    re.IGNORECASE,
)

_WRITE_SQL_TOKENS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "MERGE",
        "CREATE",
        "ALTER",
        "DROP",
        "TRUNCATE",
        "GRANT",
        "REVOKE",
        "COMMENT",
        "COPY",
        "VACUUM",
        "ANALYZE",
        "CLUSTER",
        "REINDEX",
    }
)
_SCHEMA_BIND_NAMES = frozenset(
    {
        "schema",
        "schema_name",
        "table_schema",
        "data_schema",
        "source_schema",
        "target_schema",
    }
)
_LEGACY_DATA_SCHEMA_RE = re.compile(
    r'(?<![a-z0-9_])(?:"data"|data)\s*\.', re.IGNORECASE
)


def _mask_sql_noncode(  # noqa: C901 - small state machine is clearer kept together
    statement: str, *, mask_identifiers: bool
) -> str:
    """Mask comments/literals, optionally quoted identifiers, for safe scanning."""
    chars = list(statement)
    masked = list(statement)
    index = 0
    length = len(chars)

    def _blank(start: int, end: int) -> None:
        masked[start:end] = " " * (end - start)

    while index < length:
        if statement.startswith("--", index):
            end = statement.find("\n", index + 2)
            end = length if end < 0 else end
            _blank(index, end)
            index = end
            continue
        if statement.startswith("/*", index):
            end = statement.find("*/", index + 2)
            end = length if end < 0 else end + 2
            _blank(index, end)
            index = end
            continue
        if chars[index] == "'":
            start = index
            index += 1
            while index < length:
                if chars[index] == "'":
                    if index + 1 < length and chars[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            _blank(start, index)
            continue
        if chars[index] == '"':
            start = index
            index += 1
            while index < length:
                if chars[index] == '"':
                    if index + 1 < length and chars[index + 1] == '"':
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            if mask_identifiers:
                _blank(start, index)
            continue
        if chars[index] == "$":
            delimiter_match = re.match(r"\$[a-zA-Z_0-9]*\$", statement[index:])
            if delimiter_match is not None:
                delimiter = delimiter_match.group(0)
                end = statement.find(delimiter, index + len(delimiter))
                end = length if end < 0 else end + len(delimiter)
                _blank(index, end)
                index = end
                continue
        index += 1
    return "".join(masked)


def _schema_bound_values(parameters: object, context: object) -> list[str]:
    """Return only values whose SQLAlchemy bind name denotes a schema."""
    parameter_maps = getattr(context, "compiled_parameters", None)
    if not isinstance(parameter_maps, Sequence) or isinstance(
        parameter_maps, (str, bytes, bytearray)
    ):
        parameter_maps = [parameters] if isinstance(parameters, Mapping) else []

    values: list[str] = []
    for parameter_map in parameter_maps:
        if not isinstance(parameter_map, Mapping):
            continue
        for name, value in parameter_map.items():
            if str(name).lower() in _SCHEMA_BIND_NAMES and isinstance(value, str):
                values.append(value)
    return values


def _tenant_schemas_in_statement(
    statement: str,
    parameters: object,
    context: object,
) -> tuple[set[str], bool]:
    """Collect physical schemas and detect forbidden legacy ``data`` usage."""
    structural_sql = _mask_sql_noncode(statement, mask_identifiers=False)
    schemas = {
        match.group(0).lower() for match in _TENANT_SCHEMA_RE.finditer(structural_sql)
    }
    legacy_data = _LEGACY_DATA_SCHEMA_RE.search(structural_sql) is not None
    for value in _schema_bound_values(parameters, context):
        schemas.update(
            match.group(0).lower() for match in _TENANT_SCHEMA_RE.finditer(value)
        )
        legacy_data = legacy_data or value.lower() == "data"
    return schemas, legacy_data


def _statement_requires_writer(statement: str) -> bool:
    """Classify the executable SQL operation without comments/string literals."""
    executable_sql = _mask_sql_noncode(statement, mask_identifiers=True)
    tokens = [token.upper() for token in re.findall(r"[a-zA-Z_]+", executable_sql)]
    if not tokens:
        return False
    if tokens[0] in _WRITE_SQL_TOKENS:
        return True
    if tokens[0] in {"WITH", "EXPLAIN"}:
        return any(token in _WRITE_SQL_TOKENS for token in tokens[1:])
    return False


def _before_tenant_cursor_execute(
    _conn: object,
    cursor: object,
    statement: str,
    parameters: object,
    context: object,
    _executemany: bool,
) -> None:
    """Bind one tenant reader/writer role around a data-plane statement.

    The runtime login has only SET-capable membership in two fixed gateways
    and no inherited data-table privilege. When a statement names a physical
    tenant schema, this verifies it matches ``current_tenant_var`` and selects
    that tenant's role; the after-hook returns to the session login so other
    catalog work in the same transaction never inherits data-plane privilege.
    """
    from app.core.db.tenant_schema import (
        tenant_data_schema,
        tenant_reader_role,
        tenant_writer_role,
    )
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return

    referenced_schemas, legacy_data = _tenant_schemas_in_statement(
        statement, parameters, context
    )
    if legacy_data:
        raise RuntimeError(
            "The shared data schema is forbidden in multi-tenant SQL; "
            "resolve the active tenant's physical schema first"
        )
    if not referenced_schemas:
        return

    tenant_id = current_tenant_var.get()
    if tenant_id is None:
        raise RuntimeError("Tenant data-plane SQL requires an active tenant context")

    expected_schema = tenant_data_schema(tenant_id)
    if referenced_schemas != {expected_schema}:
        raise RuntimeError(
            "Tenant data-plane SQL referenced a schema outside the active tenant: "
            f"expected {expected_schema!r}, found {sorted(referenced_schemas)!r}"
        )

    role = (
        tenant_writer_role(tenant_id)
        if _statement_requires_writer(statement)
        else tenant_reader_role(tenant_id)
    )
    # role is a UUID validated by tenant_schema.py; still quoted so it can
    # only ever be read as an identifier, never as executable SQL.
    cursor.execute(f'SET LOCAL ROLE "{role}"')  # type: ignore[attr-defined]
    setattr(context, "_geolens_tenant_role_bound", True)


def _after_tenant_cursor_execute(
    conn: Connection,
    _cursor: object,
    _statement: str,
    _parameters: object,
    context: object,
    _executemany: bool,
) -> None:
    """Return to the session login after a tenant data-plane statement."""
    if not getattr(context, "_geolens_tenant_role_bound", False):
        return
    # A reset on the statement's own cursor would clobber pending result rows
    # with the SET response before SQLAlchemy reads them; use a sibling cursor.
    reset_cursor = conn.connection.cursor()
    try:
        reset_cursor.execute("SET LOCAL ROLE NONE")
    finally:
        reset_cursor.close()
        setattr(context, "_geolens_tenant_role_bound", False)


def _normalize_context_tenant_id(tenant_id: str, *, operation: str) -> str:
    """Validate and canonicalize a UUID before request/job propagation."""
    from app.core.db.tenant_schema import tenant_data_schema

    try:
        # Validate the canonical UUID shape before normalizing.
        tenant_data_schema(tenant_id)
        return str(uuid.UUID(tenant_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{operation}: invalid tenant_id: {tenant_id!r}") from exc


def _on_begin(conn: Connection) -> None:
    """Engine ``begin`` event listener — issues the tenant GUC on txn start.

    single_tenant: zero-SQL no-op. multi_tenant + var set: issues
    ``SET LOCAL app.current_tenant``. multi_tenant + var unset: no-op, so RLS
    fail-closes the unscoped query.

    fix(#1778): use ``SET LOCAL``, never ``SELECT set_config(...)`` — the
    SELECT form takes the transaction's first snapshot, so Postgres then
    refuses a later ``SET TRANSACTION ISOLATION LEVEL``/``[NOT] DEFERRABLE``
    (25001).

    T-1208-01 requires a bound parameter for the tenant id; ``SET`` takes
    none, so the guard moves to the value: ``_normalize_context_tenant_id``
    accepts only a canonical UUID rendering (hex + hyphens, no quote) — the
    same guard used at the ``current_tenant_var.set`` sites (T-1209-14).
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant():
        return

    tid = current_tenant_var.get()
    if tid is None:
        return

    try:
        canonical = _normalize_context_tenant_id(tid, operation="_on_begin")
    except ValueError:
        # Fail closed like the tid-is-None branch above; RLS refuses the
        # unscoped query. The invalid value itself is not logged.
        logger.warning("tenant_guc_skipped_invalid_tenant_id")
        return

    conn.execute(text(f"SET LOCAL app.current_tenant = '{canonical}'"))


def install_tenant_session_hook(engine: object) -> None:
    """Register the tenant GUC hook on ``engine.sync_engine``.

    Attaches the ``"begin"`` listener there so every connection-level
    transaction (get_db, raw async_session, or AsyncConnection.begin()) fires
    it. Idempotent via a sentinel attribute, so repeated calls (e.g. per-test
    re-registration) never stack duplicate listeners.
    """
    from sqlalchemy import event

    sync_engine = engine.sync_engine  # type: ignore[union-attr]
    if getattr(sync_engine, _HOOK_ATTR, False):
        return
    event.listen(sync_engine, "begin", _on_begin)
    event.listen(
        sync_engine,
        "before_cursor_execute",
        _before_tenant_cursor_execute,
    )
    event.listen(
        sync_engine,
        "after_cursor_execute",
        _after_tenant_cursor_execute,
    )
    setattr(sync_engine, _HOOK_ATTR, True)
    logger.debug("tenant_session_guc_hook_installed")


@contextmanager
def tenant_job_context(tenant_id: str | None) -> Generator[None, None, None]:
    """Set ``current_tenant_var`` for a worker job's duration.

    single_tenant: strict no-op, var untouched. multi_tenant: sets the var for
    the ``with`` block and restores the prior value on exit (including on
    exception), preventing bleed between jobs in the same asyncio task
    (T-1208-03). ``tenant_id`` may be ``None`` in core (the cloud overlay
    supplies it from Procrastinate job kwargs) — the var stays unset and RLS
    fail-closes, the intended backstop (T-1208-04).
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant() or tenant_id is None:
        yield
        return

    normalized_tenant_id = _normalize_context_tenant_id(
        tenant_id, operation="tenant_job_context"
    )
    token = current_tenant_var.set(normalized_tenant_id)
    try:
        yield
    finally:
        current_tenant_var.reset(token)


_TaskFn = TypeVar("_TaskFn", bound=Callable[..., Awaitable[Any]])


def tenant_task(fn: _TaskFn) -> _TaskFn:
    """Bind the per-job tenant context around a Procrastinate task callable.

    Worker jobs run in a separate process that does not share the request
    ``current_tenant_var``. Applied UNDER ``@task_app.task``, this reads the
    ``tenant_id`` job kwarg (threaded in by :func:`defer_async_with_tenant`)
    and binds it via :func:`tenant_job_context` for the task's duration.
    Without this, a multi_tenant worker task sees the var unset and falls back
    to the shared ``data`` schema / global reader / no tenant storage prefix
    (fix(#256)).

    single_tenant: ``tenant_job_context`` is a no-op, byte-identical to
    calling ``fn`` directly. ``tenant_id`` is POPPED before calling ``fn``, so
    tasks without ``**kwargs`` (e.g. ``embed_record``) are unaffected.
    """

    @functools.wraps(fn)
    async def _wrapper(*args: Any, **kwargs: Any) -> Any:
        from app.core.tenancy import is_multi_tenant

        tenant_id = kwargs.pop("tenant_id", None)
        if is_multi_tenant() and tenant_id is None:
            raise RuntimeError(
                f"Worker task {fn.__name__} is missing tenant context in "
                "multi-tenant mode"
            )
        with tenant_job_context(tenant_id):
            return await fn(*args, **kwargs)

    return _wrapper  # type: ignore[return-value]


async def defer_async_with_tenant(task: Any, /, **kwargs: Any) -> Any:
    """``task.defer_async(**kwargs)`` with the active tenant id threaded in.

    Captures ``current_tenant_var`` at enqueue time and forwards it as the
    ``tenant_id`` job kwarg so the worker process (no shared ContextVar) can
    rebind it at task entry (see :func:`tenant_task`).

    single_tenant: the var is always ``None``, so no kwarg is added and this
    is byte-identical to ``task.defer_async(**kwargs)``. An explicit
    ``tenant_id`` from the caller is respected (``setdefault``). ``task`` may
    be a bare task or a ``task.configure(...)`` result — both expose
    ``defer_async``.
    """
    tid = current_tenant_var.get()
    from app.core.tenancy import is_multi_tenant

    multi_tenant = is_multi_tenant()
    explicit_tid = kwargs.get("tenant_id")
    if multi_tenant and tid is None and explicit_tid is None:
        raise RuntimeError(
            "Cannot enqueue a worker task without tenant context in multi-tenant mode"
        )
    if multi_tenant:
        normalized_active = (
            _normalize_context_tenant_id(tid, operation="defer_async_with_tenant")
            if tid is not None
            else None
        )
        normalized_explicit = (
            _normalize_context_tenant_id(
                explicit_tid, operation="defer_async_with_tenant"
            )
            if explicit_tid is not None
            else None
        )
        if (
            normalized_active is not None
            and normalized_explicit is not None
            and normalized_active != normalized_explicit
        ):
            raise RuntimeError(
                "Explicit worker tenant_id does not match the active tenant context"
            )
        kwargs["tenant_id"] = normalized_explicit or normalized_active
    elif tid is not None:
        kwargs.setdefault("tenant_id", tid)
    return await task.defer_async(**kwargs)
