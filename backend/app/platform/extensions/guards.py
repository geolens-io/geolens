"""Enterprise gating dependency for FastAPI routes."""

from __future__ import annotations

from fastapi import HTTPException, status

from app.core.edition import is_enterprise


def require_enterprise() -> None:
    """Raise 404 if the current edition is not enterprise.

    Returns 404 (not 403) to prevent feature leakage -- unauthenticated
    callers cannot distinguish between "not found" and "not licensed".
    """
    if not is_enterprise():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
