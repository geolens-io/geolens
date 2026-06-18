"""Dummy overlay fixture package for GeoLens core test suite.

Re-exports the primary API surface from ``overlay.py`` for convenient
``from tests.fixtures.dummy_overlay import register_extensions`` imports.
"""

from tests.fixtures.dummy_overlay.overlay import (
    DummyCatalogPort,
    DummyOverlayPing,
    install,
    register_extensions,
    router,
    uninstall,
)

__all__ = [
    "DummyCatalogPort",
    "DummyOverlayPing",
    "install",
    "register_extensions",
    "router",
    "uninstall",
]
