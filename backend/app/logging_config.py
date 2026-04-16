"""Compatibility shim for legacy logging config imports."""

from app.core.logging_config import setup_logging

__all__ = ["setup_logging"]
