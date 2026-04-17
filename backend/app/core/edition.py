"""Edition detection singleton.

Determines whether the running instance is community or enterprise based
on loaded extensions and an optional GEOLENS_EDITION environment override.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import structlog

logger = structlog.stdlib.get_logger(__name__)

_info: EditionInfo | None = None


@dataclass(frozen=True)
class EditionInfo:
    """Immutable edition descriptor."""

    edition: str
    features: tuple[str, ...] = ()


def init_edition(loaded_extensions: list[str]) -> None:
    """Initialize edition based on env var or auto-detection."""
    global _info

    env_val = os.environ.get("GEOLENS_EDITION", "").lower().strip()

    if env_val in ("community", "enterprise"):
        edition = env_val
    else:
        # Auto-detect: enterprise if any extensions are loaded
        edition = "enterprise" if loaded_extensions else "community"

    _info = EditionInfo(edition=edition, features=tuple(loaded_extensions))
    logger.debug("Edition initialized", edition=edition, extensions=loaded_extensions)


def get_edition() -> EditionInfo:
    """Return the current edition info, defaulting to community."""
    if _info is None:
        return EditionInfo(edition="community", features=())
    return _info


def is_enterprise() -> bool:
    """Return True if running in enterprise edition."""
    return get_edition().edition == "enterprise"
