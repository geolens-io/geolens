"""API-side statement deadline: `SET LOCAL statement_timeout` on every
transaction the API engine opens.

Bound at the engine's `begin` event, not in `get_db` or a session
default, because >20 modules open request-scoped sessions directly via
`async_session()` and would otherwise run unbounded. Engine-scoped rather than
via `database_connect_args`, since that module is shared with the worker
engine, which legitimately runs long single statements (index builds, extent
derivation) that must stay unbounded. `SET LOCAL` (not asyncpg
`server_settings`) because a startup-packet deadline breaks PgBouncer's
`DB_USE_EXTERNAL_POOLER=true` topology, and a session-level `SET` would leak
across clients under transaction-mode pooling. A later `SET LOCAL` in the
same transaction still wins, which is how routes that need longer keep
working. Never add `statement_timeout` to PgBouncer's
`ignore_startup_parameters`: the deadline is then dropped in silence. The
plain `SET LOCAL` form matters for `tasks_postgis_refresh.py`, which sets
REPEATABLE READ after begin; a `SELECT set_config(...)` would take the
snapshot first and Postgres would refuse it (25001).

Deliberately not set: `idle_in_transaction_session_timeout`. The ingest job
route holds a transaction open across a ~300s `ogrinfo` subprocess, so any
value here would kill that working transaction along with an abandoned one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextvars import ContextVar

import structlog
from fastapi import Request
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_INSTALLED_ATTR = "_geolens_api_statement_timeout_installed"

# Read by the engine `begin` listener, so every transaction the request opens,
# on any session and after any commit, starts under the anonymous deadline.
_anonymous_read: ContextVar[bool] = ContextVar("anonymous_read", default=False)


def statement_timeout_ms() -> int:
    """The API-side deadline in milliseconds; 0 means no deadline."""
    from app.core.config import settings

    return max(0, int(settings.db_statement_timeout_seconds)) * 1000


def anonymous_read_timeout_ms() -> int:
    """The anonymous read deadline in milliseconds, capped at the API-wide one;
    0 means none shorter applies."""
    from app.core.config import settings

    anonymous_ms = max(0, int(settings.db_anonymous_read_timeout_seconds)) * 1000
    api_ms = statement_timeout_ms()
    return min(anonymous_ms, api_ms) if anonymous_ms and api_ms else anonymous_ms


def _anonymous_statement():
    timeout_ms = int(anonymous_read_timeout_ms())
    if timeout_ms <= 0:
        return None
    return text(f"SET LOCAL statement_timeout = {timeout_ms}")


async def hold_to_anonymous_read_deadline(db: AsyncSession) -> None:
    """Hold the rest of the current request to the anonymous read deadline:
    *db*'s open transaction now, and every transaction begun after it."""
    _anonymous_read.set(True)
    statement = _anonymous_statement()
    if statement is not None and db.in_transaction():
        await db.execute(statement)


def release_anonymous_read_deadline() -> None:
    """End the anonymous read deadline for transactions begun from here on."""
    _anonymous_read.set(False)


_BOUND_STATE = "anonymous_reads_bound"


async def bound_anonymous_reads(request: Request) -> AsyncIterator[None]:
    """Router dependency: a caller ``get_optional_user`` resolves to no one reads
    under the anonymous statement deadline for the rest of the request. Embed
    and share links read anonymously."""
    setattr(request.state, _BOUND_STATE, True)
    try:
        yield
    finally:
        release_anonymous_read_deadline()


async def bound_every_read() -> AsyncIterator[None]:
    """Route dependency for a read that resolves no caller: every transaction the
    request begins runs under the anonymous statement deadline."""
    _anonymous_read.set(True)
    try:
        yield
    finally:
        release_anonymous_read_deadline()


async def hold_if_anonymous_reads_bound(request: Request, db: AsyncSession) -> None:
    """Called once a request has resolved to no caller."""
    if getattr(request.state, _BOUND_STATE, False):
        await hold_to_anonymous_read_deadline(db)


def install_api_statement_timeout(engine) -> None:
    """Give every transaction *engine* opens the API's statement deadline.

    Idempotent via a sentinel on the sync engine, so repeated calls don't
    stack listeners. Call only from the API process; a no-op when both
    ``DB_STATEMENT_TIMEOUT_SECONDS`` and ``DB_ANONYMOUS_READ_TIMEOUT_SECONDS`` are 0.
    """
    timeout_ms = statement_timeout_ms()
    if timeout_ms <= 0 and anonymous_read_timeout_ms() <= 0:
        return

    sync_engine = engine.sync_engine
    # `is True`, not truthiness: the sentinel is one this function sets, and an
    # object that answers every attribute would otherwise report itself already
    # installed and silently leave the engine unbounded.
    if getattr(sync_engine, _INSTALLED_ATTR, False) is True:
        return

    # Plain `SET LOCAL`, not `SELECT set_config(...)` (see the module docstring).
    # `SET` takes no bind parameter, so the value is interpolated; `timeout_ms` is
    # a validated ge=0 int Settings field, and the int() round-trip below is the
    # injection guard.
    literal_ms = int(timeout_ms)
    if literal_ms < 0:
        raise ValueError(f"statement timeout must be non-negative, got {literal_ms}")
    statement = (
        text(f"SET LOCAL statement_timeout = {literal_ms}") if literal_ms else None
    )

    @event.listens_for(sync_engine, "begin")
    def _apply_statement_timeout(conn) -> None:
        chosen = _anonymous_statement() if _anonymous_read.get() else None
        if chosen is None:
            chosen = statement
        if chosen is not None:
            conn.execute(chosen)

    setattr(sync_engine, _INSTALLED_ATTR, True)
    logger.debug("api_statement_timeout_installed", timeout_ms=timeout_ms)
