"""Tenant session GUC plumbing (ISO-01, Phase 1208-01).

Provides a single ContextVar (``current_tenant_var``) that carries the active
tenant id across a request or worker job, a SQLAlchemy ``begin`` hook that
issues ``SET LOCAL app.current_tenant = :tid``, and statement hooks that bind
physical tenant-schema reads/writes to SET-only per-tenant roles. All hooks are
active only in ``multi_tenant`` mode.

Single-tenant behaviour
-----------------------
In ``single_tenant`` (the default) the hook returns immediately after the first
``is_multi_tenant()`` check, touching no SQL state.  This is a hard no-op with
zero planner cost — the byte-identical guarantee required by Plan 05.

Multi-tenant behaviour
----------------------
When ``GEOLENS_TENANCY_MODE=multi_tenant`` and ``current_tenant_var`` holds a
tenant id the hook executes::

    SELECT set_config('app.current_tenant', :tid, true)

The ``true`` third argument makes the setting **transaction-local** — it is
automatically cleared when the transaction ends, so there is no GUC bleed
between transactions on a reused connection.

The tenant id is always passed as a **bound parameter** (never f-string
interpolated into SQL), satisfying T-1208-01.

Entrypoints
-----------
``current_tenant_var`` is populated by two separate callers:

1. **Request plane** — ``TenantContextMiddleware`` sets the var from
   ``request.state.tenant_id`` and resets it in a finally block (T-1208-03).
2. **Worker plane** — ``tenant_job_context(tenant_id)`` context manager sets
   the var for the duration of a Procrastinate job.

Both paths share the same hook so both the request-scoped ``get_db`` sessions
AND the bare global ``async_session`` pick up the GUC.

Implementation note on event choice
------------------------------------
The ``"begin"`` engine-level event fires synchronously when a connection-level
transaction is opened (equivalent to the Session-level ``after_begin`` but
registered on the engine so it covers ALL session types — get_db, raw
async_session, and AsyncConnection.begin()).  The listener receives the
``Connection`` object and runs synchronously inside the engine layer, making
``conn.execute()`` safe without any async plumbing.
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

#: Carries the active tenant id for the current asyncio task / thread.
#: Default ``None`` → hook is a no-op (tenant unknown / single_tenant).
current_tenant_var: ContextVar[str | None] = ContextVar("current_tenant", default=None)

# Sentinel attribute name used to prevent double-registration of the listener.
_HOOK_ATTR = "_geolens_tenant_guc_installed"

# A tenant data-plane schema is derived exclusively from a canonical UUID.  The
# expression deliberately does not match a loose ``data_t_*`` prefix: the
# statement binder must never turn attacker-controlled identifier text into a
# PostgreSQL role name.
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

    The runtime login receives only SET-capable membership in two fixed
    gateways.  It has no inherited data-table privilege.  When a statement
    names a physical tenant schema (directly or through a bound schema
    parameter), this hook verifies that it matches ``current_tenant_var`` and
    temporarily selects that tenant's reader or writer role.  The companion
    after-hook immediately returns to the session login so catalog work in the
    same transaction does not inherit data-plane privileges.
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
    # ``role`` is derived from a UUID validated by tenant_schema.py. Quoting is
    # still retained so this remains an identifier, never executable SQL.
    cursor.execute(f'SET LOCAL ROLE "{role}"')  # type: ignore[attr-defined]
    setattr(context, "_geolens_tenant_role_bound", True)


def _after_tenant_cursor_execute(
    _conn: object,
    cursor: object,
    _statement: str,
    _parameters: object,
    context: object,
    _executemany: bool,
) -> None:
    """Return to the session login after a tenant data-plane statement."""
    if not getattr(context, "_geolens_tenant_role_bound", False):
        return
    cursor.execute("SET LOCAL ROLE NONE")  # type: ignore[attr-defined]
    setattr(context, "_geolens_tenant_role_bound", False)


def _normalize_context_tenant_id(tenant_id: str, *, operation: str) -> str:
    """Validate and canonicalize a UUID before request/job propagation."""
    from app.core.db.tenant_schema import tenant_data_schema

    try:
        # tenant_data_schema enforces the canonical UUID-shaped input contract;
        # UUID then emits one normalized lowercase/hyphenated representation.
        tenant_data_schema(tenant_id)
        return str(uuid.UUID(tenant_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{operation}: invalid tenant_id: {tenant_id!r}") from exc


def _on_begin(conn: Connection) -> None:
    """Engine ``begin`` event listener — issues the tenant GUC on txn start.

    Fires synchronously when a connection-level transaction is opened (i.e.
    immediately before the first statement in a BEGIN/COMMIT block).

    In ``single_tenant`` (default): one boolean check, zero SQL → hard no-op.
    In ``multi_tenant`` + var set: executes ``set_config`` with a bound param.
    In ``multi_tenant`` + var None: no-op (RLS fail-closes the unscoped query).

    Parameters
    ----------
    conn:
        The synchronous ``Connection`` being transacted.
    """
    from app.core.tenancy import is_multi_tenant

    # Fast path: single_tenant → unconditional no-op, zero SQL cost.
    if not is_multi_tenant():
        return

    tid = current_tenant_var.get()
    if tid is None:
        # Var unset in multi_tenant — leave GUC unset so RLS fail-closes.
        return

    # T-1208-01: bound param — never f-string the tenant id into SQL.
    stmt = text("SELECT set_config('app.current_tenant', :tid, true)").bindparams(
        tid=tid
    )
    conn.execute(stmt)


def install_tenant_session_hook(engine: object) -> None:
    """Register the tenant GUC hook on *engine*.

    Attaches an ``"begin"`` event listener to ``engine.sync_engine`` so every
    connection-level transaction begun via this engine (whether via get_db,
    raw async_session, or AsyncConnection.begin()) fires the GUC hook.

    Safe to call multiple times — idempotent via a sentinel attribute on the
    sync engine so repeated calls (e.g. per-test re-registration) do not stack
    duplicate listeners.

    Parameters
    ----------
    engine:
        An ``AsyncEngine`` instance.  The hook is registered on
        ``engine.sync_engine`` (the underlying synchronous engine that
        SQLAlchemy uses for event dispatch).
    """
    from sqlalchemy import event

    sync_engine = engine.sync_engine  # type: ignore[union-attr]
    if getattr(sync_engine, _HOOK_ATTR, False):
        return  # already registered
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
    """Context manager that sets ``current_tenant_var`` for a worker job.

    In ``single_tenant`` (the default) this is a strict no-op — the var is
    never touched so the transaction hook remains silent.

    In ``multi_tenant`` the var is set for the duration of the ``with`` block
    and reset to its prior value on exit (including on exception), preventing
    bleed between jobs that run in the same asyncio task (T-1208-03).

    The cloud overlay (Phase 1211) supplies the per-job ``tenant_id`` from the
    Procrastinate job's kwargs/context.  In core (this plan) ``tenant_id`` may
    be ``None`` — the var stays unset and RLS fail-closes, which is the
    intended backstop (T-1208-04).

    Parameters
    ----------
    tenant_id:
        The tenant id to stamp for this job, or ``None`` (no-op).
    """
    from app.core.tenancy import is_multi_tenant

    if not is_multi_tenant() or tenant_id is None:
        # single_tenant or no tenant id available → strict no-op
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

    Procrastinate worker jobs run in a SEPARATE process that does not share the
    request-plane ``current_tenant_var``. This decorator — applied UNDER
    ``@task_app.task`` — reads the ``tenant_id`` job kwarg (threaded in at
    enqueue time by :func:`defer_async_with_tenant`) and binds
    ``current_tenant_var`` for the duration of the task via
    :func:`tenant_job_context` (which resets it on exit, so it cannot bleed into
    the next job on a reused worker asyncio task).

    Single-tenant (default): ``tenant_job_context`` is a hard no-op, so the
    wrapper is byte-identical to calling ``fn`` directly. The ``tenant_id``
    kwarg is POPPED before ``fn`` is called, so tasks need no signature change
    and tasks without ``**kwargs`` (e.g. ``embed_record``) are unaffected.

    Worker correctness (Codex review of PR #256): without this, a multi_tenant
    worker task sees ``current_tenant_var`` unset and falls back to the shared
    ``data`` schema / global reader / no tenant storage prefix.
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
    ``tenant_id`` job kwarg so the worker — a separate process that does not
    share the request ContextVar — can rebind the tenant context at task entry
    (see :func:`tenant_task`).

    Single-tenant (default): ``current_tenant_var`` is always ``None`` → no
    kwarg is added and this is byte-identical to ``task.defer_async(**kwargs)``.
    An explicit ``tenant_id`` passed by the caller is respected (``setdefault``).

    ``task`` may be a bare task or a ``task.configure(...)`` result — both expose
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
