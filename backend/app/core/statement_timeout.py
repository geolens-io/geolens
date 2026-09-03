"""A query deadline for the DB sessions API requests run on.

fix(#1778): nothing bounded statement execution on the engine every request
uses. ``database_connect_args`` carries only the SSL branch and, behind an
external pooler, ``statement_cache_size``; ``core/db/session.py`` adds
``pool_size``, ``max_overflow``, ``pool_timeout`` and ``pool_recycle``, and
``pool_timeout`` bounds CHECKOUT, never execution. The cluster sets none of
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

Why here and not on the engine
------------------------------
The obvious fix is ``server_settings={"statement_timeout": ...}`` in
``database_connect_args``. It cannot be: that property builds the connect args
for the ONE engine both the API and the Procrastinate worker import, and the
worker legitimately runs single statements for minutes -- building a spatial
index over a freshly ingested table, deriving ``geom_4326``, computing an
extent. A session default would kill those. The long-running paths that DO know
they are long already carry their own ``SET LOCAL`` override
(``analysis/tasks.py``, ``tenant_adoption_sql.py``), but the ingest ones do not,
and inferring which is which from inside a connect-args property is not
something a config module can do.

Scoping the deadline to ``get_db`` puts it exactly on the surface the finding
is about -- every ordinary DB-touching HTTP request -- and nowhere near the
worker, which never uses that dependency.

Why a per-session listener and not one statement
------------------------------------------------
``SET LOCAL`` lasts for the transaction. A handler that writes, commits, and
then reads again would run the rest of the request unbounded. Listening for
``after_begin`` on this request's session re-applies it to every transaction the
request opens, at the cost of one extra round trip per transaction on a local
socket.

Not set here: ``idle_in_transaction_session_timeout``. ``processing/ingest``'s
job route opens a transaction and then waits out a 300-second ``ogrinfo``
subprocess before its next statement, so any value that would bound an
abandoned transaction also kills a working one. That needs the route to stop
holding a transaction across a subprocess first, which is a different change.
"""

from __future__ import annotations

from sqlalchemy import event


def statement_timeout_ms() -> int:
    """The per-request deadline in milliseconds; 0 means no deadline."""
    from app.core.config import settings

    return max(0, int(settings.db_statement_timeout_seconds)) * 1000


def bind_request_statement_timeout(session) -> None:
    """Apply the request deadline to every transaction *session* opens.

    ``session`` is an ``AsyncSession``. The listener is registered on that one
    instance, so it is discarded with the session at the end of the request.
    """
    timeout_ms = statement_timeout_ms()
    if timeout_ms <= 0:
        return

    # Interpolated rather than bound: it is a validated non-negative int from
    # settings, and SET LOCAL does not accept a parameter placeholder for its
    # value.
    statement = f"SET LOCAL statement_timeout = {timeout_ms}"

    @event.listens_for(session.sync_session, "after_begin")
    def _apply(_session, _transaction, connection) -> None:
        connection.exec_driver_sql(statement)
