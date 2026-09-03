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

``do_connect`` rather than executing SQL on ``connect``: asyncpg's
``server_settings`` is sent in the startup packet, so the deadline is in force
before the first statement and costs no extra round trip. It is the same knob
``processing/tiles/pool.py`` passes to its own pool. A ``SET LOCAL`` inside a
transaction still overrides it, which is how the handful of API routes that
need longer keep working.

Not set here: ``idle_in_transaction_session_timeout``. ``processing/ingest``'s
job route opens a transaction and then waits out a 300-second ``ogrinfo``
subprocess before its next statement, so any value that would bound an
abandoned transaction also kills a working one. That needs the route to stop
holding a transaction across a subprocess first.
"""

from __future__ import annotations

import structlog
from sqlalchemy import event

logger = structlog.get_logger(__name__)

_INSTALLED_ATTR = "_geolens_api_statement_timeout_installed"


def statement_timeout_ms() -> int:
    """The API-side deadline in milliseconds; 0 means no deadline."""
    from app.core.config import settings

    return max(0, int(settings.db_statement_timeout_seconds)) * 1000


def install_api_statement_timeout(engine) -> None:
    """Give every connection *engine* opens the API's statement deadline.

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
    if getattr(sync_engine, _INSTALLED_ATTR, False):
        return

    @event.listens_for(sync_engine, "do_connect")
    def _apply_statement_timeout(_dialect, _conn_rec, _cargs, cparams):
        # Merge rather than assign: the SSL branch and the external-pooler
        # branch of database_connect_args may already have put keys here, and
        # a future one must not be dropped by this hook.
        server_settings = dict(cparams.get("server_settings") or {})
        server_settings.setdefault("statement_timeout", str(timeout_ms))
        cparams["server_settings"] = server_settings
        # None means "carry on and connect normally" -- this hook only edits
        # the parameters it was handed.
        return None

    setattr(sync_engine, _INSTALLED_ATTR, True)
    logger.debug("api_statement_timeout_installed", timeout_ms=timeout_ms)
