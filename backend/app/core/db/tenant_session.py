"""Tenant session GUC plumbing (ISO-01, Phase 1208-01).

Provides a single ContextVar (``current_tenant_var``) that carries the active
tenant id across a request or worker job, plus a SQLAlchemy ``begin`` engine
event hook that issues ``SET LOCAL app.current_tenant = :tid`` (via
``set_config``) at transaction start — ONLY in ``multi_tenant`` mode.

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

    token = current_tenant_var.set(tenant_id)
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
        with tenant_job_context(kwargs.pop("tenant_id", None)):
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
    if tid is not None:
        kwargs.setdefault("tenant_id", tid)
    return await task.defer_async(**kwargs)
