from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_client_ip(request: Request) -> str | None:
    """Extract client IP from a FastAPI request."""
    return request.client.host if request.client else None
