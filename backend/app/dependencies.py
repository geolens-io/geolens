"""Compatibility shim for legacy dependency imports."""

from app.core.dependencies import get_client_ip, get_db

__all__ = ["get_client_ip", "get_db"]
