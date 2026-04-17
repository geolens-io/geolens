"""Compatibility shim for legacy database imports."""

from app.core.db import Base, async_session, engine

__all__ = ["Base", "async_session", "engine"]
