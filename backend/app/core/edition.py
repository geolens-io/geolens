"""Edition detection singleton.

The authoritative enterprise signal is a **signed offline license**
(:mod:`app.core.license`). For backward compatibility, the legacy
``GEOLENS_EDITION`` override and loaded-extension auto-detection still apply
*unless* strict enforcement (``GEOLENS_LICENSE_ENFORCE``) is enabled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import structlog

from app.core.license import LicenseInfo, load_license

logger = structlog.stdlib.get_logger(__name__)

_info: EditionInfo | None = None


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class EditionInfo:
    """Immutable edition descriptor."""

    edition: str
    features: tuple[str, ...] = ()
    # True only when a signed license verified. False for legacy
    # env/extension-detected "enterprise" so ops can tell the two apart.
    licensed: bool = False
    customer: str | None = None
    expires_at: datetime | None = None


def init_edition(loaded_extensions: list[str]) -> None:
    """Initialize the edition from a signed license, with backward-compatible
    env/extension auto-detection.

    Resolution order:

    1. A **valid signed license** (``GEOLENS_LICENSE_KEY``) → enterprise. This
       is the real entitlement and the only path that should grant enterprise
       in production.
    2. Else, if ``GEOLENS_LICENSE_ENFORCE`` is truthy (**strict mode**), the
       instance is community regardless of ``GEOLENS_EDITION`` / loaded
       extensions — the honor-system bypass is closed.
    3. Else (**default, backward-compatible**): the legacy signal —
       ``GEOLENS_EDITION`` override, else enterprise if any extension loaded.
       A warning is logged when this grants enterprise without a license,
       because strict mode will reject it.
    """
    global _info

    license_info: LicenseInfo | None = load_license()
    enforce = _is_truthy(os.environ.get("GEOLENS_LICENSE_ENFORCE"))

    if license_info is not None:
        _info = EditionInfo(
            edition="enterprise",
            features=tuple(loaded_extensions),
            licensed=True,
            customer=license_info.customer,
            expires_at=license_info.expires_at,
        )
        logger.info(
            "Edition: enterprise (licensed)",
            customer=license_info.customer,
            extensions=loaded_extensions,
        )
        return

    # No valid license from here on.
    env_val = os.environ.get("GEOLENS_EDITION", "").lower().strip()

    if enforce:
        if env_val == "enterprise" or loaded_extensions:
            logger.warning(
                "GEOLENS_LICENSE_ENFORCE is on and no valid license is present; "
                "running as community despite GEOLENS_EDITION/extensions."
            )
        _info = EditionInfo(
            edition="community", features=tuple(loaded_extensions), licensed=False
        )
        logger.debug(
            "Edition initialized", edition="community", extensions=loaded_extensions
        )
        return

    # Backward-compatible (default) path.
    if env_val in ("community", "enterprise"):
        edition = env_val
    else:
        edition = "enterprise" if loaded_extensions else "community"

    if edition == "enterprise":
        logger.warning(
            "Running enterprise edition WITHOUT a verified license "
            "(legacy env/extension detection). Configure GEOLENS_LICENSE_KEY; "
            "this becomes mandatory once GEOLENS_LICENSE_ENFORCE is enabled."
        )

    _info = EditionInfo(
        edition=edition, features=tuple(loaded_extensions), licensed=False
    )
    logger.debug("Edition initialized", edition=edition, extensions=loaded_extensions)


def get_edition() -> EditionInfo:
    """Return the current edition info, defaulting to community."""
    if _info is None:
        return EditionInfo(edition="community", features=())
    return _info


def is_enterprise() -> bool:
    """Return True if running in enterprise edition."""
    return get_edition().edition == "enterprise"
