from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    # fix(#909): late-bind — a module-scope import would snapshot the dev-DB
    # factory before the test fixture rebinds app.core.db.async_session.
    from app.core.db import async_session

    async with async_session() as session:
        try:
            yield session
        except Exception:  # broad: session boundary — any handler exception triggers rollback then re-raise
            await session.rollback()
            raise


def get_client_ip(request: Request) -> str | None:
    """Extract client IP from a FastAPI request."""
    return request.client.host if request.client else None
