"""API-side statement deadline: `SET LOCAL statement_timeout` on every
transaction the API engine opens.

fix(#1778): bound at the engine's `begin` event, not in `get_db` or a session
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

    Idempotent via a sentinel on the sync engine, so repeated calls don't
    stack listeners. Call only from the API process; a no-op when
    ``DB_STATEMENT_TIMEOUT_SECONDS=0``.
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

    # fix(#1778): plain `SET LOCAL`, NOT `SELECT set_config(..., true)`
    # -- the SELECT form takes the transaction's first snapshot and then
    # Postgres refuses `SET TRANSACTION ISOLATION LEVEL`/`DEFERRABLE` (25001);
    # READ ONLY is unaffected either way. `SET` takes no bind parameter, so the
    # value is interpolated; `timeout_ms` is a validated ge=0 int Settings
    # field, and the int() round-trip below is the injection guard.
    literal_ms = int(timeout_ms)
    if literal_ms < 0:
        raise ValueError(f"statement timeout must be non-negative, got {literal_ms}")
    statement = text(f"SET LOCAL statement_timeout = {literal_ms}")

    @event.listens_for(sync_engine, "begin")
    def _apply_statement_timeout(conn) -> None:
        conn.execute(statement)

    setattr(sync_engine, _INSTALLED_ATTR, True)
    logger.debug("api_statement_timeout_installed", timeout_ms=timeout_ms)
