"""The job queue's database connector."""

import contextlib
from collections.abc import AsyncGenerator
from typing import Any

import psycopg
from procrastinate import PsycopgConnector

from app.core.config import settings


class _TransactionSearchPathConnector(PsycopgConnector):
    """Puts the queue's schema on the search_path inside each transaction.

    A transaction-mode pooler rejects the ``options`` startup parameter and may
    serve each transaction from a different server session, so a session-level
    ``SET`` would land on the wrong one. The sync connector is not covered.
    """

    @contextlib.asynccontextmanager
    async def _get_cursor(
        self, connection: psycopg.AsyncConnection | None = None
    ) -> AsyncGenerator[psycopg.AsyncCursor[Any]]:
        async with super()._get_cursor(connection) as cursor:
            await cursor.execute(
                "SELECT set_config('search_path', %s, true)",
                (settings.procrastinate_search_path,),
            )
            yield cursor


def make_queue_connector() -> PsycopgConnector:
    connect_kwargs: dict[str, Any] = {"connect_timeout": 5}
    connector_cls = PsycopgConnector
    if settings.db_use_external_pooler:
        connect_kwargs["prepare_threshold"] = None
        connector_cls = _TransactionSearchPathConnector
    return connector_cls(
        conninfo=settings.procrastinate_conninfo,
        min_size=1,
        max_size=3,
        kwargs=connect_kwargs,
    )
