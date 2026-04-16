"""Compatibility shim for legacy config imports."""

from app.core.config import Settings, reveal, settings

__all__ = ["Settings", "reveal", "settings"]
