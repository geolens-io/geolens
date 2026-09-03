"""A query deadline for every session the API process opens.

fix(#1778): nothing bounded statement execution on the engine the API uses.
``database_connect_args`` carries only the SSL branch and, behind an external
pooler, ``statement_cache_size``; ``core/db/session.py`` adds ``pool_size``,
``max_overflow``, ``pool_timeout`` and ``pool_recycle``, and ``pool_timeout``
bounds CHECKOUT, never execution. The cluster sets none of
``statement_timeout``, ``idle_in_transaction_session_timeout`` or
``lock_timeout`` (``db/postgresql.conf`` sets one thing, ``max_connections``).
The mechanism was never unavailable: ``processing/tiles/pool.py`` passes
``command_timeout`` to its own asyncpg pool, and four sites set ``lock_timeout``
deliberately, so the team knows it exists.

The consequence is that one pathological plan -- a seq-scanned dataset lookup,
an unindexed keyword filter, a heavy STAC aggregate -- pins one of a handful of
pool slots indefinitely, and uvicorn does not cancel a handler when its client
disconnects, so the query outlives the request that asked for it with no
ceiling at all.

Why the engine and not the dependency
------------------------------------
fix(#1778 codex r2): the first version bound the deadline to the session
``get_db`` yields. That is not the whole API surface. Handlers open
request-scoped sessions directly through ``async_session()`` in more than
twenty modules -- ``GET /stac/collections`` runs three aggregates that way --
and every one of those pinned a pool slot with no deadline. Binding at the
engine covers all of them, including any added later, and costs nothing per
request.

Why an event and not ``database_connect_args``
----------------------------------------------
That property builds the connect args for the ONE engine module both the API
and the Procrastinate worker import, and the worker legitimately runs single
statements for minutes -- building a spatial index over a freshly ingested
table, deriving ``geom_4326``, computing an extent. A session default there
would kill those. The long-running paths that know they are long already carry
their own ``SET LOCAL`` override (``analysis/tasks.py``,
``tenant_adoption_sql.py``), but the ingest ones do not.

The two processes have separate engine INSTANCES, so a per-process
registration separates them exactly. ``app/api/main.py`` installs this; the
worker entrypoint never imports that module, so its engine is untouched.

One shape, both topologies
--------------------------
fix(#1778 codex r3): the deadline is issued as ``SET LOCAL`` at the start of
every transaction, and NOT as asyncpg ``server_settings``.

``server_settings`` travels in the startup packet, and standard PgBouncer
rejects a startup parameter it does not track. ``DB_USE_EXTERNAL_POOLER=true``
is a documented, supported topology (``.env.example``, and
``database_connect_args`` already turns off the prepared-statement cache for
it), so a startup-packet deadline would have failed every connection and taken
API boot with it. Telling operators to add ``statement_timeout`` to PgBouncer's
``ignore_startup_parameters`` is worse than useless: the parameter is then
dropped in silence and the deadline is simply gone.

A connection-scoped ``SET`` is not the answer either. Under transaction-mode
pooling a server connection is handed to a different client between
transactions, so a session-level ``SET`` would either be reset away or leak
onto someone else's transaction.

``SET LOCAL`` at transaction start is correct under both topologies, which is
why it is used under both rather than branching on the flag -- a branch is two
behaviours that drift, and only one of them gets exercised in CI. It costs one
extra round trip per transaction, on a local socket, which is the price of the
deadline applying at all when a pooler is in front.

A later ``SET LOCAL`` in the same transaction still wins, which is how the
handful of API routes that need longer keep working.

It rides the engine's ``begin`` event rather than the ORM ``Session``'s
``after_begin``, for two reasons: the listener is then scoped to ONE engine
instance instead of to every Session in the process, and it fires for a raw
``engine.connect()`` transaction as well as an ORM one.
``install_tenant_session_hook`` uses the same event for the same reasons, and
``set_config(..., is_local => true)`` is ``SET LOCAL`` with a bound parameter
rather than an interpolated one.

Not set here: ``idle_in_transaction_session_timeout``. ``processing/ingest``'s
job route opens a transaction and then waits out a 300-second ``ogrinfo``
subprocess before its next statement, so any value that would bound an
abandoned transaction also kills a working one. That needs the route to stop
holding a transaction across a subprocess first.
"""

from __future__ import annotations

import structlog
from sqlalchemy import event, text

logger = structlog.get_logger(__name__)

_INSTALLED_ATTR = "_geolens_api_statement_timeout_installed"


def statement_timeout_ms() -> int:
    """The API-side deadline in milliseconds; 0 means no deadline."""
    from app.core.config import settings

    return max(0, int(settings.db_statement_timeout_seconds)) * 1000


def install_api_statement_timeout(engine) -> None:
    """Give every transaction *engine* opens the API's statement deadline.

    Idempotent via a sentinel on the sync engine, mirroring
    ``install_tenant_session_hook``, so repeated calls (a test re-registering,
    a module imported twice) do not stack listeners.

    Call this only from the API process. Called with the deadline disabled
    (``DB_STATEMENT_TIMEOUT_SECONDS=0``) it registers nothing.
    """
    timeout_ms = statement_timeout_ms()
    if timeout_ms <= 0:
        return

    sync_engine = engine.sync_engine
    # `is True`, not truthiness: the sentinel is one this function sets, and an
    # object that answers every attribute would otherwise report itself already
    # installed and silently leave the engine unbounded.
    if getattr(sync_engine, _INSTALLED_ATTR, False) is True:
        return

    # `set_config(..., is_local => true)` IS `SET LOCAL`, and unlike the `SET
    # LOCAL` statement it accepts a bound parameter, so the value is never
    # interpolated into SQL. The tenant GUC hook issues the tenant id the same
    # way. Postgres reads a bare number for statement_timeout as milliseconds.
    statement = text("SELECT set_config('statement_timeout', :ms, true)").bindparams(
        ms=str(timeout_ms)
    )

    @event.listens_for(sync_engine, "begin")
    def _apply_statement_timeout(conn) -> None:
        conn.execute(statement)

    setattr(sync_engine, _INSTALLED_ATTR, True)
    logger.debug("api_statement_timeout_installed", timeout_ms=timeout_ms)
