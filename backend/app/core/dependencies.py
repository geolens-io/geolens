from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # fix(#909): late-bind — a module-scope `from app.core.db import
    # async_session` snapshots the dev-DB factory before the test fixture
    # rebinds app.core.db.async_session, silently pointing tests at the
    # wrong database. test_layering.py enforces this for the whole tree.
    from app.core.db import async_session

    # fix(#1778): a query deadline on the sessions HTTP requests run on. See
    # app/core/statement_timeout.py for why it is scoped here rather than set
    # on the engine both the API and the worker share.
    from app.core.statement_timeout import bind_request_statement_timeout

    async with async_session() as session:
        bind_request_statement_timeout(session)
        try:
            yield session
        except Exception:  # broad: session boundary — any handler exception triggers rollback then re-raise
            await session.rollback()
            raise


def get_client_ip(request: Request) -> str | None:
    """Extract client IP from a FastAPI request."""
    return request.client.host if request.client else None
