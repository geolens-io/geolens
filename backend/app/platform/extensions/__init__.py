"""Extension registry for GeoLens enterprise extensions.

Discovers and loads extensions via the ``geolens.extensions`` entry-point
group. Community edition runs with an empty registry; enterprise packages
register themselves by providing entry points that populate the registry dict.
"""

from __future__ import annotations

from importlib.metadata import entry_points

import structlog

logger = structlog.stdlib.get_logger(__name__)

_extensions: dict[str, object] = {}
_routers: list = []
_loaded: bool = False


def load_extensions() -> None:
    """Discover and load all extensions from the ``geolens.extensions`` group."""
    global _loaded

    _routers.clear()

    eps = entry_points(group="geolens.extensions")
    for ep in eps:
        try:
            loader = ep.load()
            if callable(loader):
                loader(_extensions)
                logger.info("Loaded extension", name=ep.name)
        except Exception:
            logger.warning("Failed to load extension", name=ep.name, exc_info=True)

    # Extract routers registered by extensions
    routers = _extensions.pop("_routers", [])
    _routers.extend(routers)

    _loaded = True


def get_extension(name: str) -> object | None:
    """Return a registered extension by name, or None if not found."""
    return _extensions.get(name)


def has_extension(name: str) -> bool:
    """Check whether an extension is registered."""
    return name in _extensions


def list_extensions() -> list[str]:
    """Return the names of all registered extensions."""
    return list(_extensions.keys())


def get_extension_routers() -> list:
    """Return FastAPI routers registered by extensions."""
    return list(_routers)
